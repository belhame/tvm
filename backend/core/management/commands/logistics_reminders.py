"""A polling in-app reminder worker, with no external notification transport."""
import os
import signal
from threading import Event

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from core.notification_service import run_daily_reminders


class Command(BaseCommand):
    help = 'Crée les rappels internes opt-in de 08:00 ; ne contacte aucun service WhatsApp.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Vérifie une seule fois les rappels dus et quitte.')
        parser.add_argument('--interval', type=int, default=None, help='Intervalle de vérification en secondes (60 par défaut).')

    def handle(self, *args, **options):
        try:
            interval = options['interval'] if options['interval'] is not None else int(os.environ.get('TVM_REMINDER_POLL_SECONDS', '60'))
        except ValueError as exc:
            raise CommandError('TVM_REMINDER_POLL_SECONDS doit être un nombre entier.') from exc
        if not 10 <= interval <= 3600:
            raise CommandError('L’intervalle doit être compris entre 10 et 3 600 secondes.')
        if options['once']:
            count = run_daily_reminders()
            self.stdout.write(f'Rappels internes créés : {count}. WhatsApp non connecté ; aucun envoi externe.')
            return
        stopped = Event()
        previous = {}
        def stop(signum, frame):
            stopped.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        self.stdout.write('Rappels internes actifs : contrôle de 08:00 ; WhatsApp non connecté.')
        try:
            while not stopped.is_set():
                close_old_connections()
                try:
                    count = run_daily_reminders()
                    if count:
                        self.stdout.write(f'Rappels internes créés : {count}.')
                except OperationalError:
                    self.stderr.write('Base temporairement indisponible ; les rappels internes seront revérifiés au prochain passage.')
                stopped.wait(interval)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            close_old_connections()
