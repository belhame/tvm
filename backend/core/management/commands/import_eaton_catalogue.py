from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from core.catalogue_service import MAX_CATALOGUE_BYTES, CatalogueValidationError, analyse_catalogue, import_catalogue


class Command(BaseCommand):
    help = 'Valide ou importe un catalogue Eaton XLS en snapshot, sans modifier les clients ni équipements.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--validate-only', action='store_true', help='Validation seule, aucune écriture.')
        parser.add_argument('--actor', help='Identifiant d’un administrateur ou responsable SAV actif, requis pour importer.')

    def handle(self, *args, **options):
        path = Path(options['file']).expanduser()
        try:
            with path.open('rb') as stream:
                data = stream.read(MAX_CATALOGUE_BYTES + 1)
        except OSError as exc:
            raise CommandError('Le fichier catalogue ne peut pas être lu.') from exc
        try:
            if options['validate_only']:
                parsed = analyse_catalogue(data, path.name)
                counts = parsed['metadata']['counts']
                self.stdout.write(self.style.SUCCESS(f"Catalogue validé sans écriture : {counts['products']} produits, {counts['warranties']} garanties."))
                for warning in parsed.get('warnings', []):
                    self.stdout.write(f'Avertissement : {warning}')
                return
            if not options['actor']:
                raise CommandError('--actor est obligatoire pour importer ; utilisez --validate-only pour une validation sans écriture.')
            actor = get_user_model().objects.filter(username=options['actor'], is_active=True).first()
            result = import_catalogue(data, path.name, actor=actor)
        except (CatalogueValidationError, PermissionDenied) as exc:
            raise CommandError(str(exc)) from exc
        except IntegrityError as exc:
            raise CommandError('Insertion refusée : identités source ou données incompatibles. L’import actif est conservé.') from exc
        if result.created:
            outcome = 'Nouvelle version importée et activée'
        elif result.activated:
            outcome = 'Version déjà connue réactivée sans duplication'
        else:
            outcome = 'Version déjà active ; aucune modification'
        self.stdout.write(self.style.SUCCESS(f'{outcome} : {result.snapshot.product_count} produits, {result.snapshot.warranty_count} garanties. Aucun client ni équipement modifié.'))
