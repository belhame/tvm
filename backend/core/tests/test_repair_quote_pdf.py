"""Frozen public repair quote documents; fictional snapshots, no database."""
from copy import deepcopy
from io import BytesIO

from django.test import SimpleTestCase
from pypdf import PdfReader
from rest_framework.exceptions import ValidationError

from core.repair_quote_money import repair_quote_amounts
from core.repair_quote_pdf import repair_quote_pdf, validate_repair_quote_snapshot


def repair_snapshot(**changes):
    facts = {'version': 1, 'reference': 'REPAR-26-00042', 'issued_on': '2026-10-29',
        'issued_at': '2026-10-29T12:00:00+00:00', 'valid_until': '2026-11-29',
        'service_request': {'id': 42, 'call_number': '26-00042', 'client_reference': '000-CLIENT-42'},
        'equipment': {'id': 7, 'serial_number': 'REPAIR-FICTIVE-007', 'model': 'Onduleur de laboratoire 3 kVA', 'brand': 'Marque fictive'},
        'client': {'id': 5, 'name': 'Centre de réparation fictif', 'address': 'Adresse de test uniquement',
                   'city': 'Ville fictive', 'postal_code': '00000', 'country': 'Tunisie',
                   'contact_name': 'Contact fictif', 'email': 'repair@example.invalid', 'phone': '+000 123 456', 'tax_id': 'FISCAL-FICTIF-42'},
        'amounts': repair_quote_amounts([
            {'description': 'Remplacement de la carte fictive', 'quantity': '2.5', 'unit_ht': '10.125'},
            {'description': 'Paramétrage fictif', 'quantity': '3', 'unit_ht': '4.200'},
        ], vat_rate='19', discount_kind='percent', discount_value='7.5'),
        'terms': 'Délai proposé après accord : cinq jours ouvrés. Conditions publiques fictives.'}
    facts.update(changes)
    return facts


def pdf_text(data):
    return '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(data)).pages)


class RepairQuoteSnapshotTests(SimpleTestCase):
    def test_validation_is_pure_and_supports_minimal_public_client(self):
        snapshot = repair_snapshot(client={'id': 5, 'name': 'Client fictif'}, valid_until=None)
        original = deepcopy(snapshot)
        parsed = validate_repair_quote_snapshot(snapshot)
        parsed['client']['name'] = 'Autre nom fictif'
        self.assertEqual(snapshot, original)
        self.assertEqual(parsed['client']['email'], '')
        self.assertIn('Client fictif', pdf_text(repair_quote_pdf(snapshot)))

    def test_private_metadata_and_live_client_decisions_are_rejected_from_public_snapshot(self):
        for changes in ({'internal_notes': 'PRIVATE'}, {'billing_notes': 'PRIVATE'}, {'issued_by': 'PRIVATE'},
                        {'accepted_at': '2026-10-30'}, {'client_decision': 'accepted'}, {'version': True}, {'version': 2}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_repair_quote_snapshot(repair_snapshot(**changes))
        for section, key in [('client', 'notes'), ('equipment', 'warranty_until'), ('service_request', 'internal_notes')]:
            snapshot = repair_snapshot()
            snapshot[section][key] = 'PRIVATE'
            with self.subTest(section=section), self.assertRaises(ValidationError):
                repair_quote_pdf(snapshot)

    def test_emission_and_validity_dates_are_strict_without_inventing_a_timezone(self):
        for changes in ({'issued_on': '2026-02-31'}, {'issued_on': '20261029'}, {'issued_on': None},
                        {'issued_at': '2026-10-29T12:00:00'}, {'issued_at': '2026-10-29'},
                        {'issued_at': '2026-10-29T25:00:00Z'}, {'valid_until': '2026-10-28'}, {'valid_until': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_repair_quote_snapshot(repair_snapshot(**changes))
        # The issued calendar date may be local while the exact timestamp is UTC.
        validate_repair_quote_snapshot(repair_snapshot(issued_on='2026-10-30', issued_at='2026-10-29T23:30:00Z'))

    def test_snapshot_line_totals_discount_net_tax_total_and_flags_cannot_be_forged(self):
        for key, value in [('subtotal_ht', '0.000'), ('discount_ht', '0.000'), ('net_ht', '0.000'),
                           ('vat_amount', '0.000'), ('total_ttc', '0.000'), ('precision', True), ('fully_discounted', 0)]:
            snapshot = repair_snapshot()
            snapshot['amounts'][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_repair_quote_snapshot(snapshot)
        for mutation in ('total', 'unknown', 'quantity'):
            snapshot = repair_snapshot()
            if mutation == 'total':
                snapshot['amounts']['lines'][0]['total_ht'] = '0.000'
            elif mutation == 'unknown':
                snapshot['amounts']['lines'][0]['internal_notes'] = 'PRIVATE'
            else:
                snapshot['amounts']['lines'][0]['quantity'] = 2.5
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                repair_quote_pdf(snapshot)

    def test_public_fields_are_bounded_and_invalid_text_cannot_reach_reportlab(self):
        for section, key, value in [('client', 'name', ''), ('equipment', 'serial_number', ''),
                                    ('service_request', 'call_number', ''), ('client', 'name', 'x' * 201),
                                    ('client', 'address', 'Fictif\x00'), ('equipment', 'model', 'Fictif\ud800')]:
            snapshot = repair_snapshot()
            snapshot[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValidationError):
                repair_quote_pdf(snapshot)
        with self.assertRaises(ValidationError):
            repair_quote_pdf(repair_snapshot(terms='x' * 10001))


class RepairQuotePDFTests(SimpleTestCase):
    def test_real_a4_pdf_contains_both_call_references_equipment_client_and_financial_breakdown(self):
        data = repair_quote_pdf(repair_snapshot())
        self.assertTrue(data.startswith(b'%PDF-'))
        reader = PdfReader(BytesIO(data), strict=True)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.276, places=2)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.height), 841.890, places=2)
        text = pdf_text(data)
        for value in ('Devis de réparation', 'REPAR-26-00042', '26-00042', '000-CLIENT-42', '29/10/2026', '29/11/2026',
                      'REPAIR-FICTIVE-007', 'Onduleur de laboratoire 3 kVA', 'Centre de réparation fictif',
                      'Contact fictif', 'repair@example.invalid', '+000 123 456', 'FISCAL-FICTIF-42',
                      'Remplacement de la carte fictive', '25.313', '12.600', 'Sous-total HT', '37.913',
                      'Remise (7.5 %)', '-2.843', 'Net HT', '35.070', 'TVA (19 %)', '6.663', 'Total TTC', '41.733', 'TND',
                      'Conditions publiques fictives.', 'Ce devis n’est pas une facture.'):
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertNotIn('Remise totale', text)

    def test_equal_issued_facts_always_return_equal_bytes_without_mutating_snapshot(self):
        snapshot = repair_snapshot()
        original = deepcopy(snapshot)
        first = repair_quote_pdf(snapshot)
        repair_quote_pdf(repair_snapshot(reference='REPAR-26-ANOTHER-FICTIVE'))
        second = repair_quote_pdf(deepcopy(snapshot))
        self.assertEqual(first, second)
        self.assertEqual(snapshot, original)
        reader = PdfReader(BytesIO(first))
        self.assertEqual(reader.metadata.creation_date.date().isoformat(), snapshot['issued_on'])

    def test_full_discount_is_explicit_without_claiming_an_invoice_or_financial_waiver(self):
        amounts = repair_quote_amounts([{'description': 'Prestation fictive offerte', 'quantity': '1', 'unit_ht': '42.000'}],
            vat_rate='19', discount_kind='percent', discount_value='100')
        text = pdf_text(repair_quote_pdf(repair_snapshot(amounts=amounts)))
        for value in ('REMISE TOTALE', 'Remise (100 %)', '-42.000', '0.000 TND', 'Ce devis n’est pas une facture.'):
            self.assertIn(value, text)
        for false_evidence in ('Facture payée', 'Gratuité validée', 'Garantie approuvée', 'Client a accepté'):
            self.assertNotIn(false_evidence, text)

    def test_euro_fixed_discount_keeps_two_decimals_and_currency_labels(self):
        amounts = repair_quote_amounts([{'description': 'Prestation fictive', 'quantity': '2', 'unit_ht': '10.05'}],
            vat_rate='19', currency='EUR', discount_kind='fixed', discount_value='0.10')
        text = pdf_text(repair_quote_pdf(repair_snapshot(amounts=amounts)))
        for value in ('Remise HT (montant fixe)', '-0.10 EUR', '20.00 EUR', '3.80 EUR', '23.80 EUR'):
            self.assertIn(value, text)
        self.assertNotIn('TND', text)
        self.assertNotIn('23.800', text)

    def test_long_multiline_row_and_public_conditions_split_across_pages_without_clipping(self):
        description = 'Travaux publics fictifs\n' * 75 + 'FIN-DESCRIPTION-PUBLIQUE'
        terms = 'Condition publique fictive pour la réparation.\n' * 170 + 'FIN-CONDITIONS-PUBLIQUES'
        amounts = repair_quote_amounts([{'description': description, 'quantity': '1', 'unit_ht': '10.000'}], vat_rate='19')
        data = repair_quote_pdf(repair_snapshot(amounts=amounts, terms=terms))
        reader = PdfReader(BytesIO(data))
        self.assertGreater(len(reader.pages), 2)
        text = pdf_text(data)
        self.assertIn('FIN-DESCRIPTION-PUBLIQUE', text)
        self.assertIn('FIN-CONDITIONS-PUBLIQUES', text)
        self.assertGreaterEqual(text.count('Désignation'), 2)
        self.assertIn('Total TTC', text)

    def test_public_markup_is_printed_literally_without_links_or_external_images(self):
        amounts = repair_quote_amounts([{'description': '<script>PUBLIC-LITERAL</script> & contrôle <img src="file:///private.png"/>',
            'quantity': '1', 'unit_ht': '10.000'}], vat_rate='19')
        data = repair_quote_pdf(repair_snapshot(amounts=amounts, terms='<a href="https://example.invalid">Condition publique</a>'))
        text = ' '.join(pdf_text(data).split())
        self.assertIn('<script>PUBLIC-LITERAL</script>', text)
        self.assertIn('<img src="file:///private.png"/>', text)
        self.assertIn('<a href="https://example.invalid">Condition publique</a>', text)
        self.assertTrue(all(not page.get('/Annots') for page in PdfReader(BytesIO(data)).pages))
