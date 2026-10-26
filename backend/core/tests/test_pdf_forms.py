"""Real PDF text/raster checks, using fictional records only."""
import os
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import skipUnless
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import Client, Equipment, Intervention, OperationEvent, ServiceRequest
from core.pdf import intervention_report, service_request_report


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PDFFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.company = Client.objects.create(name='Société de validation PDF', city='Ville fictive', contact_name='Contact de validation')
        cls.other_company = Client.objects.create(name='Autre société fictive PDF')
        cls.admin = User.objects.create_user('pdf-admin', role='admin', password='SyntheticPdfValidation42!')
        cls.customer = User.objects.create_user('pdf-client', role='client', client=cls.company, password='SyntheticPdfValidation42!')
        cls.equipment = Equipment.objects.create(client=cls.company, serial_number='PDF-FICTION-001', model='Modèle de laboratoire')
        cls.other_equipment = Equipment.objects.create(client=cls.other_company, serial_number='PDF-OTHER-002', model='Autre modèle fictif')
        cls.request = ServiceRequest.objects.create(
            equipment=cls.equipment, subject='Contrôle de validation PDF', description='Signalement public de laboratoire.',
            arrived_at=datetime(2026, 1, 5, 9, tzinfo=dt_timezone.utc), client_reference='REF-PDF-CLIENT',
            packaging='Carton de validation', accessories='Câble de laboratoire', service_location='workshop',
            contact_email='pdf@example.invalid',
        )
        cls.intervention = Intervention.objects.create(
            service_request=cls.request, technician=cls.admin, status='completed',
            diagnosis='Diagnostic public de validation.', work_done='Travaux publics réalisés.',
            summary='Synthèse publique de validation.', internal_notes='INTERNAL-PDF-NEVER-PRINT',
            structured_data={'maintenance': {'battery_failure': True, 'configure': False}},
        )
        OperationEvent.objects.create(equipment=cls.equipment, service_request=cls.request,
                                      kind='summary', summary='SYNTHESIS-PUBLIC-VALIDATION', is_internal=False)
        OperationEvent.objects.create(equipment=cls.equipment, service_request=cls.request,
                                      kind='observation', observation='PRIVATE-TIMELINE-NEVER-PRINT', is_internal=True)

    def artifact(self, filename, data):
        folder = os.environ.get('TVM_PDF_REVIEW_DIR')
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            (target / filename).write_bytes(data)

    def text(self, data, *options):
        return subprocess.run(['pdftotext', *options, '-', '-'], input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True).stdout.decode('utf-8')

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler le PDF réellement produit.')
    def test_intervention_form_reproduces_sections_and_unknown_checks_without_private_notes(self):
        data = intervention_report(self.intervention)
        self.artifact('intervention-fiction.pdf', data)
        text = self.text(data)
        for value in ['Rapport d’intervention', 'SOCIÉTÉ', 'TYPE', 'TRAVAUX PRÉVENTIFS', 'Maintenance',
                      'MISE EN SERVICE', 'SYNTHÈSE', 'CONCLUSION', 'VALIDATION', 'Visa non recueilli',
                      'Signature / cachet non recueilli', self.equipment.serial_number,
                      '[X] Défaillance des batteries', '[ ] Paramétrage', '[-] Surcharge']:
            self.assertIn(value, text)
        self.assertNotIn('INTERNAL-PDF-NEVER-PRINT', text)
        self.assertIn('Synthèse publique de validation.', text)

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler le PDF réellement produit.')
    def test_follow_up_prints_arrival_reception_public_history_and_no_private_notes(self):
        OperationEvent.objects.create(equipment=self.equipment, service_request=self.request,
                                      kind='baseline', source='baseline', status_after='new',
                                      summary='Situation fictive reprise sans ancienne transition reconstituée.')
        data = service_request_report(self.request)
        self.artifact('suivi-fiction.pdf', data)
        text = self.text(data)
        for value in ['Fiche de suivi SAV', 'Arrivée', 'REF-PDF-CLIENT', 'Carton de validation',
                      'Câble de laboratoire', 'Atelier', 'heures ouvrées', 'samedi et dimanche exclus',
                      'SYNTHESIS-PUBLIC-VALIDATION', self.intervention.reference, 'Équipe SAV']:
            self.assertIn(value, text)
        for value in ['PRIVATE-TIMELINE-NEVER-PRINT', 'INTERNAL-PDF-NEVER-PRINT', self.other_equipment.serial_number]:
            self.assertNotIn(value, text)
        self.assertIn('État initial : Non affecté', text)
        self.assertIn('État constaté : Non affecté', text)
        self.assertNotIn('non renseigné ->', text)

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler le PDF réellement produit.')
    def test_long_text_spans_pages_without_losing_end_or_drawing_outside_page(self):
        intervention = Intervention.objects.get(pk=self.intervention.pk)
        intervention.summary = 'Résumé complet de validation. ' * 250 + 'FIN-SYNTHESE-VERIFIEE'
        intervention.diagnosis = 'Diagnostic long avec <balise> & caractères échappés. ' * 650 + 'FIN-DIAGNOSTIC-VERIFIEE'
        intervention.work_done = 'Travaux longs de laboratoire. ' * 250 + 'FIN-TRAVAUX-VERIFIEE'
        data = intervention_report(intervention)
        self.artifact('intervention-longue-fiction.pdf', data)
        text = self.text(data)
        for marker in ['FIN-SYNTHESE-VERIFIEE', 'FIN-DIAGNOSTIC-VERIFIEE', 'FIN-TRAVAUX-VERIFIEE']:
            self.assertIn(marker, text)
        self.assertGreater(text.count('\f'), 2)
        xml = ElementTree.fromstring(self.text(data, '-bbox'))
        pages = xml.findall('.//{*}page')
        for page in pages:
            width, height = float(page.attrib['width']), float(page.attrib['height'])
            for word in page.findall('.//{*}word'):
                self.assertGreaterEqual(float(word.attrib['xMin']), 0)
                self.assertGreaterEqual(float(word.attrib['yMin']), 0)
                self.assertLessEqual(float(word.attrib['xMax']), width + .5)
                self.assertLessEqual(float(word.attrib['yMax']), height + .5)

    @skipUnless(shutil.which('pdftoppm'), 'Poppler requis pour le rendu raster indépendant.')
    def test_intervention_and_follow_up_render_as_a4_images(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, data in [('intervention', intervention_report(self.intervention)), ('suivi', service_request_report(self.request))]:
                source, target = Path(folder) / f'{name}.pdf', Path(folder) / name
                source.write_bytes(data)
                subprocess.run(['pdftoppm', '-f', '1', '-singlefile', '-scale-to', '1000', '-png', str(source), str(target)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                png = target.with_suffix('.png').read_bytes()
                self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
                self.assertGreater(len(png), 10_000)
                self.artifact(f'{name}-fiction.png', png)

    def test_request_report_endpoint_is_scoped_and_private(self):
        api = APIClient()
        self.assertIn(api.get(f'/api/requests/{self.request.pk}/report/').status_code, (401, 403))
        api.force_authenticate(self.customer)
        response = api.get(f'/api/requests/{self.request.pk}/report/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn(self.request.reference, response['Content-Disposition'])
        other = ServiceRequest.objects.create(equipment=self.other_equipment, subject='Autre suivi privé')
        self.assertEqual(api.get(f'/api/requests/{other.pk}/report/').status_code, 404)
        self.assertIn(api.post(f'/api/requests/{self.request.pk}/report/', {}, format='json').status_code, (403, 405))

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler le compteur imprimé.')
    @override_settings(TIME_ZONE='Europe/Paris')
    def test_closed_report_keeps_elapsed_weekday_time_and_overdue_state(self):
        request = ServiceRequest.objects.get(pk=self.request.pk)
        ServiceRequest.objects.filter(pk=request.pk).update(status='closed', closed_at=datetime(2026, 1, 7, 10, tzinfo=dt_timezone.utc))
        request.refresh_from_db()
        for now in [datetime(2026, 1, 8, 12, tzinfo=dt_timezone.utc), datetime(2026, 2, 8, 12, tzinfo=dt_timezone.utc)]:
            text = ' '.join(self.text(service_request_report(request, now=now)).split())
            self.assertIn('49.00 heures ouvrées', text)
            self.assertIn('Arrêté à la clôture', text)
            self.assertIn('Dépassé', text)
            self.assertIn('Europe/Paris', text)
            self.assertIn(now.astimezone(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M'), text)
            self.assertNotIn(now.isoformat(), text)

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler les données historiques imprimées.')
    def test_legacy_unknown_dates_never_become_a_counter_based_on_creation(self):
        ServiceRequest.objects.filter(pk=self.request.pk).update(status='closed', closed_at=None)
        request = ServiceRequest.objects.get(pk=self.request.pk)
        text = ' '.join(self.text(service_request_report(request)).split())
        self.assertIn('Temps écoulé Inconnu', text)
        self.assertIn('Ancien dossier clôturé', text)
        ServiceRequest.objects.filter(pk=request.pk).update(status='pending', arrived_at=None)
        request.refresh_from_db()
        text = ' '.join(self.text(service_request_report(request)).split())
        self.assertIn('Temps écoulé Inconnu', text)
        self.assertIn('la date de création du dossier ne la remplace pas', text)

    @skipUnless(shutil.which('pdftotext'), 'Poppler requis pour contrôler les priorités des champs imprimés.')
    @override_settings(TIME_ZONE='UTC')
    def test_intervention_uses_reception_details_but_explicit_intervention_fields_take_priority(self):
        Client.objects.filter(pk=self.company.pk).update(contact_name='CONTACT-CLIENT-FALLBACK', phone='PHONE-CLIENT-FALLBACK')
        Equipment.objects.filter(pk=self.equipment.pk).update(location='SITE-EQUIPMENT-FALLBACK')
        ServiceRequest.objects.filter(pk=self.request.pk).update(
            contact_name='CONTACT-RECEPTION', contact_phone='PHONE-RECEPTION', end_customer='END-CUSTOMER-RECEPTION',
            client_reference='CLIENT-REFERENCE-RECEPTION', status='closed',
            closed_at=datetime(2026, 1, 7, 10, tzinfo=dt_timezone.utc),
        )
        intervention = Intervention.objects.get(pk=self.intervention.pk)
        text = ' '.join(self.text(intervention_report(intervention)).split())
        for value in ['CONTACT-RECEPTION', 'PHONE-RECEPTION', 'END-CUSTOMER-RECEPTION',
                      'SITE-EQUIPMENT-FALLBACK', 'CLIENT-REFERENCE-RECEPTION',
                      'Arrivée du matériel 05/01/2026 à 09:00', 'Clôture du dossier 07/01/2026 à 10:00']:
            self.assertIn(value, text)
        self.assertNotIn('CONTACT-CLIENT-FALLBACK', text)
        self.assertNotIn('PHONE-CLIENT-FALLBACK', text)
        # Reception timestamps remain supplementary information, never an
        # invented operation date on a historical maintenance intervention.
        self.assertIsNone(intervention.performed_on)
        self.assertIn('Date Non renseignée', text)
        intervention.contact_name = 'CONTACT-INTERVENTION'
        intervention.contact_phone = 'PHONE-INTERVENTION'
        intervention.end_customer = 'END-CUSTOMER-INTERVENTION'
        intervention.site = 'SITE-INTERVENTION'
        intervention.performed_on = datetime(2026, 1, 6, tzinfo=dt_timezone.utc).date()
        text = ' '.join(self.text(intervention_report(intervention)).split())
        for value in ['CONTACT-INTERVENTION', 'PHONE-INTERVENTION', 'END-CUSTOMER-INTERVENTION', 'SITE-INTERVENTION', 'Date 06/01/2026']:
            self.assertIn(value, text)
        for value in ['CONTACT-RECEPTION', 'PHONE-RECEPTION', 'END-CUSTOMER-RECEPTION', 'SITE-EQUIPMENT-FALLBACK']:
            self.assertNotIn(value, text)
        intervention.contact_name = intervention.contact_phone = ''
        intervention.service_request.contact_name = intervention.service_request.contact_phone = ''
        text = ' '.join(self.text(intervention_report(intervention)).split())
        self.assertIn('CONTACT-CLIENT-FALLBACK', text)
        self.assertIn('PHONE-CLIENT-FALLBACK', text)
