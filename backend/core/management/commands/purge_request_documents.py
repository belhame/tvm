from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.attachment_models import RequestAttachment
from core.attachment_service import purge_document_file
from core.attachment_storage import STORED_NAME, private_path, private_storage


class Command(BaseCommand):
    help = 'Reprend les suppressions physiques en attente ; --orphans supprime aussi les fichiers UUID non référencés de plus de 24 heures.'

    def add_arguments(self, parser):
        parser.add_argument('--orphans', action='store_true', help='Inclut les fichiers applicatifs non référencés âgés de plus de 24 heures ; ne touche pas les autres chemins.')

    def handle(self, *args, **options):
        purged = pending = 0
        for document_id in RequestAttachment.objects.filter(deleted_at__isnull=False, storage_deleted_at__isnull=True).values_list('pk', flat=True).iterator():
            if purge_document_file(document_id):
                purged += 1
            else:
                pending += 1
        orphans = 0
        if options['orphans']:
            root = Path(private_storage().location).resolve()
            cutoff = (timezone.now() - timedelta(hours=24)).timestamp()
            known = set(RequestAttachment.objects.values_list('stored_name', flat=True))
            for path in (root / 'requests').glob('*/*'):
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not path.is_file() or not STORED_NAME.fullmatch(relative) or relative in known:
                    continue
                try:
                    checked_path = private_path(relative)
                    if checked_path.stat().st_mtime < cutoff:
                        checked_path.unlink()
                        orphans += 1
                except (OSError, ValueError):
                    continue
        self.stdout.write(f'Fichiers supprimés : {purged} ; reprises en attente : {pending} ; orphelins anciens supprimés : {orphans}.')
