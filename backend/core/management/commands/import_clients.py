from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from core.client_import import MAX_CLIENT_BYTES, ClientImportError, import_clients_csv


class Command(BaseCommand):
    help = 'Vérifie un CSV clients privé et ajoute uniquement les nouvelles fiches avec --apply.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--actor', required=True, help='Administrateur ou responsable SAV actif qui effectue l’import.')
        parser.add_argument('--apply', action='store_true', help='Crée les nouvelles fiches valides. Sans cet argument : simulation sans écriture.')

    def handle(self, *args, **options):
        path = Path(options['file']).expanduser()
        try:
            with path.open('rb') as stream:
                data = stream.read(MAX_CLIENT_BYTES + 1)
        except OSError as exc:
            raise CommandError('Le fichier clients ne peut pas être lu.') from exc
        actor = get_user_model().objects.filter(username=options['actor'], is_active=True).first()
        try:
            result = import_clients_csv(data, path.name, actor=actor, apply=options['apply'])
        except (ClientImportError, PermissionDenied) as exc:
            raise CommandError(str(exc)) from exc
        summary = result['summary']
        mode = 'Import effectué' if options['apply'] else 'Simulation sans écriture'
        self.stdout.write(self.style.SUCCESS(f"{mode} : {summary['total']} lignes ; {summary['create']} nouvelles fiches possibles ; {summary['created']} créées ; {summary['existing']} existantes ; {summary['duplicate']} doublons ; {summary['conflict']} conflits ; {summary['invalid']} invalides. Aucun compte ni mot de passe créé."))
        # Do not print contacts or raw source values to shared terminal logs.
        for row in result['rows']:
            if row['errors']:
                self.stdout.write(f"Ligne {row['line']} ({row['status']}) : {' '.join(row['errors'])}")
