"""Exercise PostgreSQL row locks, not just sequential stock validation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from core.models import Client, Equipment, Intervention, Part, ServiceRequest, StockMovement
from core.serializers import InterventionSerializer, StockMovementSerializer


@skipUnless(connection.vendor == 'postgresql', 'Le verrouillage concurrent exige PostgreSQL.')
class SharedStockTests(TransactionTestCase):
    def test_two_users_cannot_consume_the_last_part_twice(self):
        part = Part.objects.create(sku='CONCURRENT-LAST', name='Dernière batterie', stock_quantity=1)
        barrier = Barrier(2)

        def consume():
            close_old_connections()
            try:
                serializer = StockMovementSerializer(data={
                    'part': part.pk, 'kind': 'out', 'quantity': -1,
                    'reference': 'Concurrent stock validation',
                })
                serializer.is_valid(raise_exception=True)
                barrier.wait(timeout=10)
                try:
                    serializer.save()
                    return 'saved'
                except ValidationError:
                    return 'insufficient'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: consume(), range(2)))
        self.assertCountEqual(outcomes, ['saved', 'insufficient'])
        part.refresh_from_db()
        self.assertEqual(part.stock_quantity, 0)
        self.assertEqual(StockMovement.objects.filter(part=part).count(), 1)

    def test_two_interventions_keep_the_shared_request_open(self):
        client = Client.objects.create(name='Client simultané')
        equipment = Equipment.objects.create(client=client, serial_number='CONCURRENT-UPS', model='93PM')
        request = ServiceRequest.objects.create(equipment=equipment, subject='Deux visites requises')
        barrier = Barrier(2)

        def create_intervention(status):
            close_old_connections()
            try:
                serializer = InterventionSerializer(data={
                    'service_request': request.pk, 'status': status,
                    'work_done': 'Première visite réalisée' if status == 'completed' else '',
                })
                serializer.is_valid(raise_exception=True)
                barrier.wait(timeout=10)
                return serializer.save().pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            identifiers = list(pool.map(create_intervention, ['completed', 'scheduled'], timeout=30))
        self.assertEqual(len(set(identifiers)), 2)
        self.assertEqual(Intervention.objects.filter(service_request=request).count(), 2)
        request.refresh_from_db()
        self.assertEqual(request.status, 'scheduled')
