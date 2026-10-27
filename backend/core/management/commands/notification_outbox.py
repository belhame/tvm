from django.core.management.base import BaseCommand

from core.outbox_service import process_outbox


class Command(BaseCommand):
    help = 'Traite les notifications externes autorisées ; aucun canal n’est activé par cette commande.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Un passage contrôlé (le worker reminders assure la boucle).')
        parser.add_argument('--limit', type=int, default=20)

    def handle(self, *args, **options):
        count = process_outbox(limit=options['limit'])
        self.stdout.write(f'Notifications examinées : {count}. Acceptation fournisseur distincte de la réception ou lecture.')
