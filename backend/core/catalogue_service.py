"""Transactional catalogue snapshots, separate from clients and equipment."""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath

from django.core.exceptions import PermissionDenied
from django.db import transaction

from .catalogue_models import CatalogueImport, CatalogueProduct, CatalogueState, CatalogueWarranty
from .models import AuditLog

MAX_CATALOGUE_BYTES = 8 * 1024 * 1024


class CatalogueValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogueImportResult:
    snapshot: CatalogueImport
    created: bool
    activated: bool


def safe_filename(filename):
    name = PurePosixPath(str(filename or 'catalogue.xls').replace('\\', '/')).name
    return ''.join(c for c in name if ord(c) >= 32 and c != '\x7f')[:255] or 'catalogue.xls'


def usable_code(code):
    return str(code or '').strip().upper() not in ('', 'NA', 'N/A')


def collision_counts(products):
    return Counter(
        (str(structure).strip().casefold(), str(code).strip().casefold())
        for structure, code in products
        if usable_code(code)
    )


def analyse_catalogue(data, filename='catalogue.xls'):
    if not isinstance(data, bytes) or not data:
        raise CatalogueValidationError('Le fichier catalogue est vide ou invalide.')
    if len(data) > MAX_CATALOGUE_BYTES:
        raise CatalogueValidationError('Le fichier catalogue dépasse la limite de 8 Mio.')
    from .catalogue_parser import parse_catalogue, CatalogueParseError
    try:
        parsed = parse_catalogue(data, filename=safe_filename(filename))
    except CatalogueParseError as exc:
        raise CatalogueValidationError(str(exc)) from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get('products'), list) or not parsed['products'] or not isinstance(parsed.get('warranties'), list):
        raise CatalogueValidationError('Le catalogue ne contient pas les tables attendues.')
    digest = hashlib.sha256(data).hexdigest()
    metadata = parsed.get('metadata')
    if not isinstance(metadata, dict) or metadata.get('sha256') != digest:
        raise CatalogueValidationError('L’empreinte du catalogue ne correspond pas au fichier analysé.')
    try:
        json.dumps(parsed, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CatalogueValidationError('Le catalogue contient des valeurs non conservables.') from exc
    metadata = dict(metadata)
    metadata.update(
        counts={**parsed.get('counts', {}), 'products': len(parsed['products']), 'warranties': len(parsed['warranties'])},
        year_tables=parsed.get('year_tables', []),
        warnings=parsed.get('warnings', []),
    )
    return {**parsed, 'metadata': metadata}


def require_import_actor(actor):
    if not actor or not getattr(actor, 'pk', None) or not actor.is_active or actor.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('L’import du catalogue est réservé aux administrateurs et responsables SAV actifs.')


def import_catalogue(data, filename, *, actor):
    require_import_actor(actor)
    # Finish all workbook validation before acquiring the lock or changing state.
    parsed = analyse_catalogue(data, filename)
    digest = parsed['metadata']['sha256']
    with transaction.atomic():
        CatalogueState.objects.get_or_create(pk=1)
        CatalogueState.objects.select_for_update().get(pk=1)
        snapshot = CatalogueImport.objects.filter(sha256=digest).first()
        created = snapshot is None
        if created:
            snapshot = CatalogueImport.objects.create(
                filename=safe_filename(filename), sha256=digest, imported_by=actor,
                product_count=len(parsed['products']), warranty_count=len(parsed['warranties']),
                metadata=parsed['metadata'],
            )
            products = []
            for row in parsed['products']:
                products.append(CatalogueProduct(
                    snapshot=snapshot, source_row=row['source_row'], source_sheet=row.get('source_sheet', ''),
                    range_name=row.get('range_name', ''), product_name=row['product_name'],
                    product_code=row.get('product_code', ''), structure=row['structure'],
                    launch_year=row.get('launch_year_raw', ''),
                    manufacturing_part_number=row.get('manufacturing_part_number', ''),
                    catalogue_number=row.get('catalogue_number', ''), market_status=row.get('market_status', ''),
                    replacement_product=row.get('replacement_product_name', ''),
                    replacement_part_number=row.get('replacement_part_number', ''),
                    version=row.get('version', ''), return_text=row.get('return_text', ''), raw_data=row['raw_data'],
                ))
            CatalogueProduct.objects.bulk_create(products, batch_size=250)
            CatalogueWarranty.objects.bulk_create([
                CatalogueWarranty(
                    snapshot=snapshot, source_sheet=row.get('source_sheet', ''), source_row=row['source_row'],
                    source_column=row['source_column'], scope=row['scope'], category=row.get('category', ''),
                    product_name=row.get('product_name', ''), brand_group=row.get('brand_group', ''),
                    duration_text=row.get('duration_text', ''), duration_months=row.get('duration_months'),
                    conditions=row.get('conditions', ''), raw_data=row.get('raw_data', {}),
                ) for row in parsed['warranties']
            ], batch_size=250)
        activated = not snapshot.is_active
        if activated:
            CatalogueImport.objects.filter(is_active=True).exclude(pk=snapshot.pk).update(is_active=False)
            snapshot.is_active = True
            snapshot.save(update_fields=['is_active'])
        if created or activated:
            AuditLog.objects.create(actor=actor, action='catalogue_import' if created else 'catalogue_activate', resource='catalogueimport', resource_id=str(snapshot.pk))
        return CatalogueImportResult(snapshot=snapshot, created=created, activated=activated)
