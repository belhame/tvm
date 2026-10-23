import hashlib
import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.management.commands.import_hfsql import MANIFEST_TABLE, SOURCE_IDS
from core.models import Client, LegacyRecord


class HFSQLImportTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.rows = {name: [] for name in SOURCE_IDS}
        self.rows["Client"] = [{"IDClient": "9007199254740993123", "Raison_sociale": "Électricité Démo", "Mail": None}]
        self.write_export()

    def write_export(self, snapshot_id="test-export-2026-10-22"):
        tables = []
        for index, (name, records) in enumerate(self.rows.items()):
            filename = f"table-{index}.jsonl"
            data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records).encode("utf-8")
            (self.root / filename).write_bytes(data)
            tables.append({"name": name, "file": filename, "row_count": len(records), "sha256": hashlib.sha256(data).hexdigest()})
        self.manifest = {
            "schema_version": 1, "format": "tvm-hfsql-jsonl", "snapshot_id": snapshot_id,
            "timezone": "Africa/Lagos", "tables": tables,
        }
        self.save_manifest()

    def save_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")

    def run_import(self, *flags):
        output = io.StringIO()
        call_command("import_hfsql", str(self.root), *flags, stdout=output)
        return output.getvalue()

    def test_default_validation_does_not_write(self):
        output = self.run_import()
        self.assertIn("Validation seule", output)
        self.assertEqual(LegacyRecord.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 0)

    def test_stage_preserves_64_bit_string_and_is_idempotent(self):
        self.run_import("--stage")
        source = LegacyRecord.objects.get(table_name="Client")
        self.assertEqual(source.source_id, "9007199254740993123")
        self.assertEqual(source.payload, self.rows["Client"][0])
        self.assertEqual(LegacyRecord.objects.count(), 2)  # one source row and one manifest marker
        self.assertEqual(Client.objects.count(), 0)
        self.assertIn("0 nouvelles lignes", self.run_import("--stage"))
        self.assertEqual(LegacyRecord.objects.count(), 2)

    def test_empty_export_also_has_immutable_manifest(self):
        self.rows["Client"] = []
        self.write_export()
        self.run_import("--stage")
        self.assertEqual(LegacyRecord.objects.count(), 1)
        self.assertEqual(LegacyRecord.objects.get().table_name, MANIFEST_TABLE)
        self.rows["Client"] = [{"IDClient": "1"}]
        self.write_export()
        with self.assertRaisesMessage(CommandError, "autre contenu"):
            self.run_import("--stage")
        self.assertEqual(LegacyRecord.objects.count(), 1)

    def test_mutating_snapshot_is_refused_without_overwrite(self):
        self.run_import("--stage")
        self.rows["Client"][0]["Raison_sociale"] = "Nouveau nom"
        self.write_export()
        with self.assertRaisesMessage(CommandError, "autre contenu"):
            self.run_import("--stage")
        self.assertEqual(LegacyRecord.objects.get(table_name="Client").payload["Raison_sociale"], "Électricité Démo")

    def test_checksum_failure_writes_nothing(self):
        self.manifest["tables"][1]["sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "SHA-256 non conforme"):
            self.run_import("--stage")
        self.assertFalse(LegacyRecord.objects.exists())

    def test_row_count_failure_writes_nothing(self):
        self.manifest["tables"][1]["row_count"] = 2
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "Nombre de lignes non conforme"):
            self.run_import("--stage")
        self.assertFalse(LegacyRecord.objects.exists())

    def test_missing_table_is_refused(self):
        self.manifest["tables"].pop()
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "25 tables"):
            self.run_import("--stage")
        self.assertFalse(LegacyRecord.objects.exists())

    def test_duplicate_table_is_refused(self):
        self.manifest["tables"][-1] = self.manifest["tables"][0]
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "dupliqué"):
            self.run_import()

    def test_removing_table_from_existing_snapshot_is_refused(self):
        self.run_import("--stage")
        self.manifest["tables"].pop()
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "25 tables"):
            self.run_import("--stage")
        self.assertEqual(LegacyRecord.objects.count(), 2)

    def test_path_traversal_is_refused(self):
        self.manifest["tables"][0]["file"] = "../outside.jsonl"
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "rester dans le dossier"):
            self.run_import("--stage")

    def test_symlink_file_is_refused(self):
        source = self.root / self.manifest["tables"][0]["file"]
        link = self.root / "linked.jsonl"
        link.symlink_to(source)
        self.manifest["tables"][0]["file"] = link.name
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "symboliques"):
            self.run_import()

    def test_duplicate_ids_are_refused(self):
        self.rows["Client"].append(self.rows["Client"][0].copy())
        self.write_export()
        with self.assertRaisesMessage(CommandError, "Identifiant source dupliqué"):
            self.run_import("--stage")
        self.assertFalse(LegacyRecord.objects.exists())

    def test_duplicate_json_properties_are_not_silently_overwritten(self):
        entry = self.manifest["tables"][1]
        data = b'{"IDClient":"1","IDClient":"2"}\n'
        (self.root / entry["file"]).write_bytes(data)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "clé dupliquée"):
            self.run_import("--stage")
        self.assertFalse(LegacyRecord.objects.exists())

    def test_decimal_amount_must_be_string_to_avoid_precision_loss(self):
        self.rows["item_bl"] = [{"IDitem_bl": "1", "Montant": 1.25}]
        self.write_export()
        with self.assertRaisesMessage(CommandError, "décimal"):
            self.run_import()
        self.rows["item_bl"][0]["Montant"] = "1.250000000000000001"
        self.write_export()
        self.run_import("--stage")
        self.assertEqual(LegacyRecord.objects.get(table_name="item_bl").payload["Montant"], "1.250000000000000001")

    def test_nul_strings_are_rejected_before_database_write(self):
        self.rows["Client"][0]["Raison_sociale"] = "Nom\x00invalide"
        self.write_export()
        with self.assertRaisesMessage(CommandError, "NUL"):
            self.run_import("--stage")
        self.assertFalse(LegacyRecord.objects.exists())

    def test_numeric_pk_or_fk_is_refused_to_protect_precision(self):
        for record in ({"IDClient": 9007199254740993123}, {"IDDemande": "1", "IDClient": 42}):
            table = "Client" if "IDDemande" not in record else "Demande"
            with self.subTest(table=table):
                self.rows[table] = [record]
                self.write_export()
                with self.assertRaisesMessage(CommandError, "chaîne"):
                    self.run_import("--stage")
                self.rows[table] = []
        self.assertFalse(LegacyRecord.objects.exists())

    def test_credentials_are_rejected_without_echoing_the_value(self):
        for table, field in (("Client", "mot_de_passe"), ("collaborateurs", "mot_de_passe"), ("user", "spassword"), ("param_mail", "mot_de_passe")):
            with self.subTest(table=table):
                self.rows[table] = [{SOURCE_IDS[table]: "1", field: "sensitive-example-value"}]
                self.write_export()
                with self.assertRaises(CommandError) as context:
                    self.run_import("--stage")
                self.assertNotIn("sensitive-example-value", str(context.exception))
                self.assertIn("désensibilisé", str(context.exception))
                self.rows[table] = []
        self.assertFalse(LegacyRecord.objects.exists())

    def test_dates_are_not_silently_converted(self):
        self.rows["Demande"] = [{"IDDemande": "1", "Date_arrivee": "20261022"}]
        self.write_export()
        with self.assertRaisesMessage(CommandError, "YYYY-MM-DD"):
            self.run_import()
        self.rows["Demande"][0]["Date_arrivee"] = "2026-02-30"
        self.write_export()
        with self.assertRaisesMessage(CommandError, "invalide"):
            self.run_import()

    def test_binary_memos_are_separate_not_imported_inline(self):
        self.rows["joints"] = [{"IDjoints": "1", "piece": "base64-blob"}]
        self.write_export()
        with self.assertRaisesMessage(CommandError, "Mémo binaire"):
            self.run_import("--stage")
        self.rows["joints"][0]["piece"] = None
        self.write_export()
        self.run_import("--stage")
        self.assertIsNone(LegacyRecord.objects.get(table_name="joints").payload["piece"])

    def test_stage_failure_rolls_back_all_new_rows_and_marker(self):
        self.rows["qualifications"] = [{"IDqualifications": "1", "Titre": "Technicien"}]
        self.write_export()
        # Simulate a conflicting older staging row. It must not be overwritten,
        # and the qualifications row and manifest inserted before it must roll back.
        old = LegacyRecord.objects.create(
            batch_id=self.manifest["snapshot_id"], table_name="Client",
            source_id=self.rows["Client"][0]["IDClient"], payload={"old": "content"},
        )
        with self.assertRaisesMessage(CommandError, "diffère"):
            self.run_import("--stage")
        self.assertEqual(list(LegacyRecord.objects.values_list("pk", flat=True)), [old.pk])
        old.refresh_from_db()
        self.assertEqual(old.payload, {"old": "content"})

    def test_existing_extra_rows_are_not_silently_deleted(self):
        self.run_import("--stage")
        LegacyRecord.objects.create(
            batch_id=self.manifest["snapshot_id"], table_name="Client", source_id="extra", payload={"IDClient": "extra"},
        )
        with self.assertRaisesMessage(CommandError, "supplémentaires"):
            self.run_import("--stage")
        self.assertTrue(LegacyRecord.objects.filter(source_id="extra").exists())
