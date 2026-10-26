import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Client, Contract, DeliveryLine, DeliveryNote, DemoInitialization, Equipment, Intervention, Part, ServiceRequest, StockMovement, Warranty


class Command(BaseCommand):
    help = 'Ajoute un jeu de démonstration fictif, explicitement activé, sans écraser les données ni les mots de passe existants.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.TVM_DEMO_MODE:
            raise CommandError('La démo exige TVM_DEMO_MODE=1. Ne l’activez pas sur une base réelle.')
        if DemoInitialization.objects.filter(pk='powercare-demo-v1').exists():
            self.stdout.write(self.style.SUCCESS('Démonstration déjà initialisée : toutes les données et tous les mots de passe sont préservés, aucun ajout effectué.'))
            return
        password = os.environ.get('TVM_DEMO_PASSWORD', '')
        try:
            password_validation.validate_password(password)
        except ValidationError as exc:
            raise CommandError('TVM_DEMO_PASSWORD doit respecter les règles de mot de passe (10 caractères minimum).') from exc
        for model in (Client, Equipment, ServiceRequest, Intervention, Part, Contract, Warranty, DeliveryNote):
            if model.objects.filter(Q(legacy_id__isnull=True) | ~Q(legacy_id__startswith='demo:')).exists():
                raise CommandError('Cette base contient des données hors démonstration. Initialisation refusée pour éviter tout mélange.')
        User = get_user_model()
        accounts = [('admin', 'Alex', 'Martin', 'admin'), ('responsable', 'Camille', 'Dubois', 'manager'), ('technicien', 'Thomas', 'Leroy', 'technician'), ('sofia', 'Sofia', 'Moreau', 'technician'), ('amine', 'Amine', 'Karim', 'technician'), ('client', 'Jean', 'Dupont', 'client'), ('livreur', 'Noé', 'Bernard', 'courier')]
        for username, *_ in accounts:
            if User.objects.filter(username=username).exclude(legacy_id=f'demo:user:{username}').exists():
                raise CommandError(f'Le compte {username} existe déjà hors démo. Aucun compte n’a été modifié.')
        today = timezone.localdate()
        now = timezone.now()
        clients = []
        client_rows = [
            ('Centre Hospitalier Lumière', 'Marie Laurent', 'Lyon', '69003', '12 avenue des Lumières'),
            ('DataCenter Solutek', 'Jean Dupont', 'Paris', '75017', '28 rue des Réseaux'),
            ('Groupe Altéa Paris', 'Julie Garnier', 'Paris', '75008', '6 boulevard Altéa'),
            ('Clinique Saint-Roch Démo', 'Karim Benali', 'Montpellier', '34000', '14 rue Saint-Roch'),
            ('Université des Rives', 'Claire Morel', 'Nantes', '44000', '3 allée des Sciences'),
        ]
        for i, (name, contact, city, postcode, address) in enumerate(client_rows):
            client, _ = Client.objects.get_or_create(legacy_id=f'demo:client:{i}', defaults={'name': name, 'contact_name': contact, 'city': city, 'postal_code': postcode, 'address': address, 'email': f'contact{i}@example.invalid', 'phone': '', 'country': 'France'})
            clients.append(client)
        users = {}
        for username, first, last, role in accounts:
            user, created = User.objects.get_or_create(username=username, defaults={'first_name': first, 'last_name': last, 'email': f'{username}@example.invalid', 'role': role, 'client': clients[1] if role == 'client' else None, 'legacy_id': f'demo:user:{username}', 'is_staff': role == 'admin', 'is_superuser': role == 'admin'})
            if created:
                user.set_password(password)
                user.save(update_fields=['password'])
            users[username] = user
        equipment_rows = [
            (0, 'Power Xpert 9395', 'PC-DEMO-9395-001', 200, 'Local énergie · Bâtiment A'),
            (1, '93PM', 'PC-DEMO-93PM-002', 100, 'Salle informatique A'),
            (2, '93E', 'PC-DEMO-93E-003', 40, 'Local technique · Sous-sol'),
            (3, '9390', 'PC-DEMO-9390-004', 160, 'Salle énergie'),
            (4, 'BladeUPS', 'PC-DEMO-BLADE-005', 60, 'Centre de calcul'),
            (1, '9PX', 'PC-DEMO-9PX-006', 11, 'Baie réseau B'),
            (0, '93PM', 'PC-DEMO-93PM-007', 120, 'Bloc opératoire'),
            (2, '9SX', 'PC-DEMO-9SX-008', 6, 'Bureau direction'),
        ]
        equipment = []
        for i, (ci, model, serial, power, location) in enumerate(equipment_rows):
            item, _ = Equipment.objects.get_or_create(legacy_id=f'demo:equipment:{i}', defaults={'client': clients[ci], 'serial_number': serial, 'brand': 'Eaton', 'model': model, 'power_kva': power, 'location': location, 'commissioned_on': today - timedelta(days=400), 'warranty_until': today + timedelta(days=330), 'status': 'maintenance' if i in (0, 1, 3) else 'active'})
            equipment.append(item)
        requests = []
        states = ['testing', 'in_progress', 'scheduled', 'in_progress', 'completed', 'scheduled', 'completed', 'scheduled', 'testing', 'completed', 'in_progress', 'completed']
        subjects = ['Contrôle annuel et test d’autonomie', 'Maintenance corrective — batterie', 'Visite préventive semestrielle', 'Alarme température module', 'Test de remise en service', 'Vérification du bypass', 'Remplacement des ventilateurs', 'Contrôle de la chaîne batterie']
        technicians = [users['technicien'], users['sofia'], users['amine']]
        for i, state in enumerate(states):
            item = equipment[i % len(equipment)]
            request, created = ServiceRequest.objects.get_or_create(legacy_id=f'demo:request:{i}', defaults={'reference': f'SAV-{today.year}-{842-i:04d}', 'equipment': item, 'subject': subjects[i % len(subjects)], 'description': subjects[i % len(subjects)] + '. Dossier fictif destiné à tester le parcours de maintenance.', 'priority': 'high' if i == 1 else 'normal', 'status': 'resolved' if state == 'completed' else 'in_progress' if state in ('in_progress', 'testing') else 'scheduled', 'requested_by': users['responsable']})
            if created:
                ServiceRequest.objects.filter(pk=request.pk).update(created_at=now - timedelta(days=i % 12, hours=2))
            requests.append(request)
            intervention, created = Intervention.objects.get_or_create(legacy_id=f'demo:intervention:{i}', defaults={'reference': f'INT-{today.year}-{842-i:04d}', 'service_request': request, 'technician': technicians[i % 3], 'scheduled_at': now + timedelta(days=(i % 5) - 1, hours=i % 4), 'duration_minutes': 120, 'status': state, 'diagnosis': 'Usure des batteries détectée lors du contrôle de capacité.' if i == 1 else 'Vérification des journaux et contrôle visuel de l’équipement.', 'work_done': 'Contrôles électriques, nettoyage et test de fonctionnement réalisés.' if state == 'completed' else '', 'recommendations': 'Prévoir le prochain contrôle selon le contrat de maintenance.', 'internal_notes': 'Note interne fictive : accès technique à confirmer avec le responsable du site.', 'completed_at': now - timedelta(days=i % 6) if state == 'completed' else None})
            if created:
                Intervention.objects.filter(pk=intervention.pk).update(created_at=now - timedelta(days=i % 12))
        part_rows = [('BAT-12V-9AH', 'Batterie 12V — 9Ah', 'battery', 6, 10, '39.90'), ('BAT-12V-7AH', 'Batterie 12V — 7Ah', 'battery', 24, 10, '29.50'), ('PWR-CARD-93PM', 'Carte de puissance 93PM', 'board', 3, 5, '420.00'), ('CTRL-BOARD', 'Carte de contrôle', 'board', 8, 5, '280.00'), ('FAN-120MM', 'Ventilateur 120 mm', 'ventilation', 14, 8, '24.00'), ('FAN-92MM', 'Ventilateur 92 mm', 'ventilation', 2, 5, '18.00'), ('FILT-AIR-93E', 'Filtre à air 93E', 'other', 18, 10, '12.50')]
        parts = []
        for i, (sku, name, category, stock, minimum, price) in enumerate(part_rows):
            part, created = Part.objects.get_or_create(legacy_id=f'demo:part:{i}', defaults={'sku': sku, 'name': name, 'category': category, 'stock_quantity': 0, 'min_stock': minimum, 'unit_price': Decimal(price)})
            if created:
                StockMovement.objects.create(part=part, quantity=stock, kind='in', reference='DEMO-INITIAL', created_by=users['admin'])
                part.stock_quantity = stock
                part.save(update_fields=['stock_quantity'])
            parts.append(part)
        for i, client in enumerate(clients):
            Contract.objects.get_or_create(legacy_id=f'demo:contract:{i}', defaults={'number': f'CTR-{today.year}-{i+1:03d}', 'client': client, 'starts_on': today - timedelta(days=150), 'ends_on': today + timedelta(days=215), 'coverage': 'Maintenance préventive, assistance et contrôle annuel. Conditions fictives à valider.', 'visits_per_year': 2, 'status': 'active'})
        for i, item in enumerate(equipment):
            Warranty.objects.get_or_create(legacy_id=f'demo:warranty:{i}', defaults={'equipment': item, 'provider': 'Garantie constructeur — démo', 'starts_on': today - timedelta(days=400), 'ends_on': today + timedelta(days=330), 'terms': 'Conditions fictives. Vérifier les garanties et justificatifs réels avant toute décision.'})
        note, created = DeliveryNote.objects.get_or_create(legacy_id='demo:delivery:1', defaults={'reference': f'BL-{today.year}-001', 'client': clients[1], 'status': 'ready', 'notes': 'Livraison de démonstration. Le BL ne débite pas le stock automatiquement.'})
        if created:
            DeliveryLine.objects.create(delivery_note=note, part=parts[1], description=parts[1].name, quantity=2)
        DemoInitialization.objects.create(name='powercare-demo-v1')
        self.stdout.write(self.style.SUCCESS('Démonstration fictive initialisée. Comptes : admin, responsable, technicien, livreur, client. Mots de passe existants préservés.'))
