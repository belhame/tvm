from copy import deepcopy
from io import BytesIO

from django.test import SimpleTestCase, override_settings
from pypdf import PdfReader

from core.logistics_delivery_note_pdf import render_delivery_note


def snapshot():
    return {
        'version': 1, 'reference': 'BL-FICTIF-0001', 'issued_at': '2026-10-28T09:00:00+00:00',
        'client': {'id': 1, 'name': 'Centre de laboratoire fictif', 'address': '1 rue de laboratoire', 'city': 'Ville fictive', 'postal_code': '00000', 'country': 'Pays fictif'},
        'courier': {'id': 2, 'name': 'Livreur de laboratoire', 'courier_kind': 'internal'},
        'prepared_by': {'id': 3, 'name': 'Préparateur de laboratoire'},
        'comment': 'Préparation de validation uniquement.',
        'lines': [{
            'job': 10, 'assignment_revision': 1, 'service_request': 20, 'call_number': '26-00001', 'client_reference': '000AB-001',
            'equipment': 30, 'original_serial_number': 'FICTION-ORIGINAL-001', 'serial_number': 'FICTION-ORIGINAL-001',
            'brand': 'Marque fictive', 'model': 'Modèle de laboratoire', 'kind': 'delivery', 'delivery_address': 'Site Alpha fictif\nEntrée laboratoire',
        }],
    }


def read_pdf(data):
    pdf = PdfReader(BytesIO(data))
    return pdf, '\n'.join(page.extract_text() for page in pdf.pages)


@override_settings(TIME_ZONE='Africa/Lagos')
class LogisticsDeliveryNotePdfTests(SimpleTestCase):
    def test_pdf_has_distinct_bl_header_and_each_call_reference(self):
        data = render_delivery_note(snapshot())
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertGreater(len(data), 1000)
        _, text = read_pdf(data)
        for value in ['BON DE LIVRAISON', 'N° de bon de livraison', 'BL-FICTIF-0001', '28/10/2026 à 10:00',
                      'Centre de laboratoire fictif', '1 rue de laboratoire', 'Pays fictif', 'Préparateur de laboratoire',
                      'Livreur de laboratoire', '26-00001', '000AB-001', 'FICTION-ORIGINAL-001', 'Modèle de laboratoire',
                      'Site Alpha fictif', 'Entrée laboratoire', 'Quantité : 1', 'ne vaut pas preuve de remise physique']:
            self.assertIn(value, text)
        self.assertNotIn('N° d’intervention / appel TVM', text)

    def test_multiple_lines_keep_their_own_references_and_destinations(self):
        value = snapshot()
        second = {**value['lines'][0], 'job': 11, 'service_request': 21, 'call_number': '26-00002', 'client_reference': '000AB-002',
                  'original_serial_number': 'FICTION-RETURN-002', 'serial_number': 'FICTION-RETURN-002', 'kind': 'return',
                  'delivery_address': 'Site Beta fictif'}
        value['lines'].append(second)
        _, text = read_pdf(render_delivery_note(value))
        for marker in ['26-00001', '26-00002', '000AB-001', '000AB-002', 'Site Alpha fictif', 'Site Beta fictif', 'Retour au client', '2 ONDULEUR(S)']:
            self.assertIn(marker, text)

    def test_exchange_prints_new_delivery_serial_and_distinct_original(self):
        value = snapshot()
        value['lines'][0]['serial_number'] = 'FICTION-REPLACEMENT-001'
        _, text = read_pdf(render_delivery_note(value))
        self.assertIn('S/N à remettre : FICTION-REPLACEMENT-001', text)
        self.assertIn('S/N d’origine : FICTION-ORIGINAL-001', text)
        self.assertEqual(text.count('Quantité : 1'), 1)

    def test_unchanged_serial_does_not_print_a_spurious_exchange(self):
        _, text = read_pdf(render_delivery_note(snapshot()))
        self.assertNotIn('S/N d’origine', text)

    def test_untrusted_markup_is_printed_literally(self):
        value = snapshot()
        value['client']['name'] = '<b>Centre & partenaires</b>'
        value['lines'][0]['model'] = '<font color="red">Modèle fictif</font>'
        value['comment'] = '<img src="https://example.invalid/private.png"/> & <script>exemple</script>'
        _, text = read_pdf(render_delivery_note(value))
        text = ' '.join(text.split())
        for marker in ['<b>Centre & partenaires</b>', '<font color="red">Modèle fictif</font>', '<script>exemple</script>', 'https://example.invalid/private.png']:
            self.assertIn(marker, text)

    def test_private_and_financial_extra_keys_are_ignored_at_every_level(self):
        value = snapshot()
        value.update(internal_notes='PRIVATE-ROOT-NOTES', price='SECRET-ROOT-PRICE', finance='PRIVATE-FINANCE')
        value['client']['notes'] = 'PRIVATE-CLIENT-NOTES'
        value['courier']['email'] = 'PRIVATE-COURIER-EMAIL'
        value['lines'][0].update(internal_notes='PRIVATE-LINE-NOTES', diagnosis='PRIVATE-DIAGNOSIS', unit_price='SECRET-UNIT-PRICE', invoice_reference='PRIVATE-INVOICE')
        _, text = read_pdf(render_delivery_note(value))
        for marker in ['PRIVATE-', 'SECRET-', 'Facture', 'Prix', 'TVA', 'Montant']:
            self.assertNotIn(marker, text)

    def test_one_hundred_lines_and_long_addresses_make_a_valid_multipage_pdf(self):
        value = snapshot()
        address = ('Adresse de laboratoire très longue, accès au dépôt. ' * 78)[:3950] + ' FIN-ADRESSE'
        value['client']['name'] = 'Client ' + 'A' * 193
        value['client']['address'] = address
        value['comment'] = ('Commentaire public de laboratoire. ' * 115)[:3950] + ' FIN-COMMENTAIRE'
        value['lines'] = [
            {**value['lines'][0], 'job': index, 'call_number': f'26-{index:05d}', 'client_reference': f'CLIENT-{index:03d}',
             'serial_number': f'LAB-SERIAL-{index:03d}', 'original_serial_number': f'LAB-SERIAL-{index:03d}',
             'delivery_address': address if index in (1, 100) else f'Destination fictive {index}'}
            for index in range(1, 101)
        ]
        pdf, text = read_pdf(render_delivery_note(value))
        self.assertGreater(len(pdf.pages), 2)
        self.assertIn('26-00001', text)
        self.assertIn('26-00100', text)
        self.assertIn('LAB-SERIAL-100', text)
        self.assertIn('FIN-ADRESSE', text)
        self.assertIn('FIN-COMMENTAIRE', text)
        self.assertEqual(text.count('Quantité : 1'), 100)

    def test_empty_or_oversized_line_sets_are_not_rendered(self):
        for lines in ([], [snapshot()['lines'][0]] * 101):
            value = snapshot()
            value['lines'] = lines
            with self.assertRaises(ValueError):
                render_delivery_note(value)

    def test_snapshot_requires_known_version_and_aware_issue_date(self):
        for changes in ({'version': 2}, {'version': True}, {'issued_at': '2026-10-28T10:00:00'}, {'issued_at': 'invalid'}):
            with self.assertRaises(ValueError):
                render_delivery_note({**snapshot(), **changes})

    def test_required_names_serials_and_document_type_are_validated(self):
        for path, invalid in [('client.name', ''), ('courier.courier_kind', 'unknown'), ('lines.serial_number', 'A\x00B'),
                              ('lines.kind', 'invoice'), ('comment', 'x' * 4001)]:
            value = deepcopy(snapshot())
            if path.startswith('lines.'):
                value['lines'][0][path.split('.')[1]] = invalid
            elif '.' in path:
                outer, key = path.split('.')
                value[outer][key] = invalid
            else:
                value[path] = invalid
            with self.subTest(path=path), self.assertRaises(ValueError):
                render_delivery_note(value)
