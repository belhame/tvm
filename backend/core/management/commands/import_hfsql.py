"""Validate a complete, sanitized HFSQL export and optionally stage it.

This deliberately does not create application objects. In particular, the
WINDEV analysis does not establish equipment ownership or all current links.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import LegacyRecord


# Automatic identifier fields read from the supplied TVM.xdd, generation 46.
# IDClient in Contrat is also a unique key; it is NOT the source primary ID.
SOURCE_IDS = {
    "qualifications": "IDqualifications",
    "Client": "IDClient",
    "onduleurs": "IDonduleurs",
    "modèles_des_onduleurs": "IDmodèles_des_onduleurs",
    "collaborateurs": "IDcollaborateurs",
    "Demande": "IDDemande",
    "param": "IDparam",
    "journal": "IDjournal",
    "BL": "IDBL",
    "item_bl": "IDitem_bl",
    "joints": "IDjoints",
    "echange": "IDechange",
    "miseenservice": "IDmiseenservice",
    "Preventif": "IDPreventif",
    "Garantie": "IDGarantie",
    "Contrat": "IDContrat",
    "user": "IDuser",
    "JM": "IDjoints",
    "JP": "IDjoints",
    "JG": "IDjoints",
    "JC": "IDjoints",
    "JE": "IDjoints",
    "param_notif": "IDparam_notif",
    "param_mail": "IDparam_mail",
    "snumber": "IDsnumber",
}

DATE_FIELDS = {
    "onduleurs": {"Début_du_garantie"},
    "Demande": {
        "Date_arrivee", "Date_cloture", "Debur_garantie", "debut_contart",
        "Fin_contrat", "debut_extension", "Fin_extension", "Date_traitement", "Date_etat",
    },
    "BL": {"Date"},
    "joints": {"Date"},
    "echange": {"Date", "Date_validation", "Date_cloture"},
    "miseenservice": {"Date", "Date_cloture"},
    "Preventif": {"Date", "Date_cloture"},
    "Garantie": {"Duree_DU", "Duree_AU", "Date_cloture"},
    "Contrat": {"Duree_DU", "Duree_AU", "Date_cloture"},
    "JM": {"Date"}, "JP": {"Date"}, "JG": {"Date"}, "JC": {"Date"}, "JE": {"Date"},
}

BINARY_FIELDS = {
    "param": {"Logo"},
    "joints": {"piece"},
    "echange": {"fichier"}, "miseenservice": {"fichier"}, "Preventif": {"fichier"},
    "Garantie": {"fichier"}, "Contrat": {"fichier"},
    "JM": {"piece"}, "JP": {"piece"}, "JG": {"piece"}, "JC": {"piece"}, "JE": {"piece"},
}

MANIFEST_TABLE = "__manifest__"
MANIFEST_ID = "__manifest__"
MAX_LINE_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class TableExport:
    name: str
    path: Path
    row_count: int
    sha256: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _json(text):
    def reject_constant(_):
        raise ValueError("non-finite JSON number")

    def reject_decimal(_):
        # Export decimals as strings so that the staging loader cannot round
        # a monetary value while parsing JSON into Python and PostgreSQL JSONB.
        raise ValueError("decimal values must be JSON strings")

    return json.loads(
        text, object_pairs_hook=_unique_object,
        parse_constant=reject_constant, parse_float=reject_decimal,
    )


def _normalized_key(value):
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold())
        if c.isalnum() and not unicodedata.combining(c)
    )


def _contains_secret_key(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if (
                any(token in normalized for token in ("password", "motdepasse", "passwd", "apikey", "secret", "token"))
                or normalized in {"pwd", "mdp", "pass", "cleapi", "jeton"}
                or normalized.startswith("mdp")
                or _contains_secret_key(item)
            ):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


def _valid_json_strings(value):
    """PostgreSQL JSONB cannot store NUL or unpaired Unicode surrogates."""
    if isinstance(value, str):
        if "\x00" in value:
            return False
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            return False
    elif isinstance(value, dict):
        return all(_valid_json_strings(key) and _valid_json_strings(item) for key, item in value.items())
    elif isinstance(value, list):
        return all(_valid_json_strings(item) for item in value)
    return True


def _safe_file(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise CommandError("Nom de fichier d'export invalide dans le manifeste.")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise CommandError("Les fichiers d'export doivent rester dans le dossier d'export.")
    candidate = root
    for component in path.parts:
        candidate = candidate / component
        if candidate.is_symlink():
            raise CommandError("Les liens symboliques sont interdits dans l'export.")
    try:
        candidate = candidate.resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CommandError("Fichier d'export absent ou hors du dossier d'export.") from exc
    if not candidate.is_file():
        raise CommandError("Un fichier d'export déclaré n'est pas un fichier ordinaire.")
    return candidate


def _load_manifest(export_dir):
    directory = Path(export_dir).expanduser()
    if directory.is_symlink():
        raise CommandError("Le dossier d'export ne doit pas être un lien symbolique.")
    try:
        root = directory.resolve(strict=True)
    except OSError as exc:
        raise CommandError("Dossier d'export introuvable.") from exc
    if not root.is_dir():
        raise CommandError("Le chemin d'export doit être un dossier.")
    manifest_path = _safe_file(root, "manifest.json")
    try:
        if manifest_path.stat().st_size > 1024 * 1024:
            raise CommandError("Le manifeste dépasse la taille autorisée (1 Mo).")
        manifest = _json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CommandError("manifest.json doit être un objet JSON UTF-8 valide, sans clés dupliquées.") from exc
    if not isinstance(manifest, dict):
        raise CommandError("manifest.json doit être un objet JSON.")
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1:
        raise CommandError("Version de manifeste non prise en charge (schema_version attendu : 1).")
    if manifest.get("format") != "tvm-hfsql-jsonl":
        raise CommandError("Format attendu : tvm-hfsql-jsonl.")
    snapshot_id = manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not SNAPSHOT_RE.fullmatch(snapshot_id):
        raise CommandError("snapshot_id doit contenir 1 à 128 caractères ASCII alphanumériques, points, tirets ou underscores.")
    timezone = manifest.get("timezone")
    if not isinstance(timezone, str):
        raise CommandError("Le fuseau horaire IANA de l'export est obligatoire.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CommandError("Fuseau horaire IANA invalide dans le manifeste.") from exc
    entries = manifest.get("tables")
    if not isinstance(entries, list) or len(entries) != len(SOURCE_IDS):
        raise CommandError("Les 25 tables TVM sont requises, y compris les tables vides.")
    tables = []
    names, paths = set(), set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise CommandError("Chaque table du manifeste doit être un objet JSON.")
        name = entry.get("name")
        if not isinstance(name, str) or name not in SOURCE_IDS or name in names:
            raise CommandError("Nom de table inconnu ou dupliqué dans le manifeste.")
        count = entry.get("row_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise CommandError(f"Nombre de lignes invalide pour la table {name}.")
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
            raise CommandError(f"Empreinte SHA-256 invalide pour la table {name}.")
        path = _safe_file(root, entry.get("file"))
        if path in paths or path == manifest_path:
            raise CommandError("Chaque table doit disposer de son propre fichier JSONL.")
        tables.append(TableExport(name, path, count, checksum.lower()))
        names.add(name)
        paths.add(path)
    if names != set(SOURCE_IDS):
        raise CommandError("Les 25 tables TVM sont requises, sans substitution.")
    return root, snapshot_id, timezone, tables


def _validate_record(table, payload, line_number):
    position = f"{table.name}, ligne {line_number}"
    if not isinstance(payload, dict):
        raise CommandError(f"Un objet JSON par ligne est requis ({position}).")
    if not _valid_json_strings(payload):
        raise CommandError(f"Chaîne Unicode non stockable dans PostgreSQL : NUL ou surrogate isolé ({position}).")
    if _contains_secret_key(payload):
        raise CommandError(
            f"Champ d'authentification ou secret détecté ({position}). "
            "Demandez un export désensibilisé : omettez les champs secrets, même vides. Aucune valeur n'a été affichée."
        )
    source_id = payload.get(SOURCE_IDS[table.name])
    if not isinstance(source_id, str) or not source_id or len(source_id) > 128 or source_id.strip() != source_id:
        raise CommandError(f"Identifiant source obligatoire en chaîne de 1 à 128 caractères ({position}).")
    for key, value in payload.items():
        if key.casefold().startswith("id") and value is not None and not isinstance(value, str):
            raise CommandError(f"Tous les identifiants PK/FK doivent être exportés en chaînes JSON ({position}).")
    for field in DATE_FIELDS.get(table.name, ()):
        value = payload.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not ISO_DATE_RE.fullmatch(value):
            raise CommandError(f"Date {field} attendue au format YYYY-MM-DD ou null ({position}).")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f"Date {field} invalide ({position}).") from exc
    for field in BINARY_FIELDS.get(table.name, ()):
        if payload.get(field) is not None:
            raise CommandError(f"Mémo binaire {field} à exporter séparément ; champ absent ou null attendu ({position}).")
    return source_id


def _records(table):
    digest = hashlib.sha256()
    seen = set()
    count = 0
    try:
        with table.path.open("rb") as source:
            while raw := source.readline(MAX_LINE_BYTES + 1):
                count += 1
                if len(raw) > MAX_LINE_BYTES:
                    raise CommandError(f"Ligne JSONL trop volumineuse dans {table.name} ; exportez les binaires séparément.")
                digest.update(raw)
                try:
                    payload = _json(raw.decode("utf-8"))
                except (UnicodeError, ValueError, RecursionError) as exc:
                    raise CommandError(
                        f"JSON UTF-8 invalide, clé dupliquée ou nombre décimal non exporté en chaîne ({table.name}, ligne {count})."
                    ) from exc
                source_id = _validate_record(table, payload, count)
                if source_id in seen:
                    raise CommandError(f"Identifiant source dupliqué dans {table.name} (ligne {count}).")
                seen.add(source_id)
                yield source_id, payload
    except OSError as exc:
        raise CommandError(f"Lecture impossible pour la table {table.name}.") from exc
    if count != table.row_count:
        raise CommandError(f"Nombre de lignes non conforme pour {table.name} : attendu {table.row_count}, lu {count}.")
    if digest.hexdigest() != table.sha256:
        raise CommandError(f"Empreinte SHA-256 non conforme pour la table {table.name}.")


class Command(BaseCommand):
    help = (
        "Valide l'export JSONL complet des 25 tables HFSQL. Par défaut aucune écriture. "
        "--stage conserve les lignes dans LegacyRecord, sans créer de clients/dossiers ni déduire les liaisons. "
        "Une ligne interne __manifest__ protège l'immuabilité du snapshot, même vide. "
        "Les pièces jointes binaires et leurs empreintes ne sont pas importées ni validées par cette commande."
    )

    def add_arguments(self, parser):
        parser.add_argument("export_dir", help="Dossier contenant manifest.json et les 25 JSONL désensibilisés.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--validate-only", action="store_true", help="Validation sans écriture (mode par défaut).")
        mode.add_argument("--stage", action="store_true", help="Conservation atomique en staging serveur, sans promotion métier.")

    def handle(self, *args, **options):
        root, batch_id, timezone, tables = _load_manifest(options["export_dir"])
        total = 0
        # Validate every file before opening a write transaction.
        for table in tables:
            total += sum(1 for _ in _records(table))
        self.stdout.write(f"Export vérifié : 25 tables, {total} lignes ; identifiants et valeurs conservés sans conversion.")
        if not options["stage"]:
            self.stdout.write(self.style.SUCCESS("Validation seule terminée. Aucune donnée n'a été écrite."))
        else:
            metadata = {
                "schema_version": 1, "format": "tvm-hfsql-jsonl", "snapshot_id": batch_id, "timezone": timezone,
                "tables": [
                    {"name": table.name, "row_count": table.row_count, "sha256": table.sha256}
                    for table in sorted(tables, key=lambda item: item.name)
                ],
            }
            created = self._stage(batch_id, tables, metadata, total)
            self.stdout.write(self.style.SUCCESS(
                f"Staging terminé : {created} nouvelles lignes, {total - created} déjà présentes. "
                "Aucun objet métier ni compte n'a été créé ; les relations restent à valider."
            ))
        if (root / "attachments_manifest.jsonl").exists():
            self.stdout.write(self.style.WARNING(
                "Pièces jointes présentes : non importées et non vérifiées par cette commande. Conserver leurs fichiers séparément."
            ))

    @transaction.atomic
    def _stage(self, batch_id, tables, metadata, expected_count):
        marker, _ = LegacyRecord.objects.get_or_create(
            batch_id=batch_id, table_name=MANIFEST_TABLE, source_id=MANIFEST_ID,
            defaults={"payload": metadata},
        )
        # Serialize concurrent imports of the same snapshot in PostgreSQL.
        marker = LegacyRecord.objects.select_for_update().get(pk=marker.pk)
        if marker.payload != metadata:
            raise CommandError(
                "Ce snapshot_id existe avec un autre contenu. Aucun écrasement autorisé : créez un nouvel identifiant d'export."
            )
        created_count = 0
        for table in tables:
            # Recheck bytes and checksums inside the transaction; a changed file
            # between validation and staging causes a complete rollback.
            for source_id, payload in _records(table):
                record, created = LegacyRecord.objects.get_or_create(
                    batch_id=batch_id, table_name=table.name, source_id=source_id,
                    defaults={"payload": payload},
                )
                if record.payload != payload:
                    raise CommandError("Une ligne de staging diffère de l'export vérifié. Aucun écrasement autorisé.")
                created_count += int(created)
        if LegacyRecord.objects.filter(batch_id=batch_id).exclude(table_name=MANIFEST_TABLE).count() != expected_count:
            raise CommandError("Le staging contient des lignes supplémentaires non présentes dans l'export. Aucune suppression automatique.")
        return created_count
