"""Financial rounding and frozen, public diagnostic quote documents."""
from copy import deepcopy
from decimal import Decimal, Inexact, localcontext
from io import BytesIO

from django.test import SimpleTestCase
from pypdf import PdfReader
from rest_framework.exceptions import ValidationError

from core.diagnostic_quote import diagnostic_quote_pdf, quote_amounts, validate_quote_snapshot


def quote_snapshot(**changes):
    snapshot = {
        'version': 1, 'reference': 'DIAG-26-00042', 'issued_on': '2026-10-26',
        'service_request': {'id': 42, 'call_number': '26-00042', 'client_reference': '000-CENTRE-42', 'subject': 'Diagnostic fictif'},
        'equipment': {'id': 7, 'serial_number': 'DIAG-FICTIF-ORIGINAL-007', 'model': 'Modèle de laboratoire 3 kVA', 'brand': 'Marque fictive'},
        'client': {'id': 5, 'name': 'Société de diagnostic fictive', 'contact_name': 'Contact fictif',
                   'email': 'diagnostic@example.invalid', 'phone': '', 'address': 'Adresse de test uniquement',
                   'city': 'Ville fictive', 'postal_code': '00000', 'country': 'Tunisie', 'tax_id': 'TEST-FISCAL-00042'},
        'diagnosis': 'Diagnostic fictif : carte non réparable, retour du matériel d’origine prévu.',
        'amounts': quote_amounts('10.005', '19', 'TND'),
        'fee_mode': 'billable', 'free_status': None,
        'quote_notes': 'Précision publique de démonstration.',
    }
    snapshot.update(changes)
    return snapshot


def pdf_text(data):
    return '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(data)).pages)


class DiagnosticQuoteMoneyTests(SimpleTestCase):
    def test_tnd_rounds_vat_half_up_and_sums_the_rounded_tax(self):
        self.assertEqual(quote_amounts('10.005', '19'), {
            'currency': 'TND', 'precision': 3, 'amount_ht': '10.005', 'vat_rate': '19',
            'vat_amount': '1.901', 'total_ttc': '11.906',
        })
        self.assertEqual(quote_amounts('0.005', '50')['vat_amount'], '0.003')
        self.assertEqual(quote_amounts('0.005', '50')['total_ttc'], '0.008')

    def test_eur_and_usd_use_two_decimals_and_are_not_tnd_formatted(self):
        for currency in ('EUR', 'USD'):
            with self.subTest(currency=currency):
                self.assertEqual(quote_amounts('10.05', '19', currency), {
                    'currency': currency, 'precision': 2, 'amount_ht': '10.05', 'vat_rate': '19',
                    'vat_amount': '1.91', 'total_ttc': '11.96',
                })

    def test_database_decimal_padding_is_accepted_without_rounding_nonzero_precision(self):
        self.assertEqual(quote_amounts(Decimal('19.990'), Decimal('19.00'), 'EUR')['amount_ht'], '19.99')
        self.assertEqual(quote_amounts(Decimal('19.000'), Decimal('0.00'), 'USD')['total_ttc'], '19.00')
        for value in (Decimal('19.991'), Decimal('0.001')):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                quote_amounts(value, Decimal('19.00'), 'EUR')

    def test_raw_text_excess_precision_is_rejected_not_silently_rounded(self):
        for amount, rate, currency in (('1.0001', '19', 'TND'), ('1.001', '19', 'EUR'), ('1.000', '19', 'EUR'), ('1', '19.001', 'TND')):
            with self.subTest(amount=amount, rate=rate, currency=currency), self.assertRaises(ValidationError):
                quote_amounts(amount, rate, currency)

    def test_zero_vat_must_be_explicit_and_negative_zero_never_prints_negative(self):
        self.assertEqual(quote_amounts('123.400', '0')['total_ttc'], '123.400')
        self.assertEqual(quote_amounts('-0.000', '-0.00')['amount_ht'], '0.000')
        for missing in (None, '', ' '):
            with self.subTest(rate=missing), self.assertRaises(ValidationError):
                quote_amounts('10.000', missing)

    def test_nonfinite_exponents_negatives_booleans_floats_and_invalid_currency_are_rejected(self):
        for amount in ('NaN', 'Infinity', '-Infinity', '1e2', '-1.000', True, 1.25, {}, '1,25', '1000000000.000'):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                quote_amounts(amount, '19')
        for rate in ('NaN', 'Infinity', '1e1', '-1', '100.01', True, 19.0):
            with self.subTest(rate=rate), self.assertRaises(ValidationError):
                quote_amounts('10.000', rate)
        for currency in ('BTC', '', None, True):
            with self.subTest(currency=currency), self.assertRaises(ValidationError):
                quote_amounts('10.000', '19', currency)

    def test_money_calculation_does_not_inherit_global_precision_or_inexact_traps(self):
        expected = quote_amounts(Decimal('123456.789'), Decimal('19.99'), 'TND')
        with localcontext() as context:
            context.prec = 3
            context.traps[Inexact] = True
            self.assertEqual(quote_amounts(Decimal('123456.789'), Decimal('19.99'), 'TND'), expected)


class DiagnosticQuoteSnapshotTests(SimpleTestCase):
    def test_snapshot_validation_does_not_mutate_issued_facts(self):
        snapshot = quote_snapshot()
        original = deepcopy(snapshot)
        parsed = validate_quote_snapshot(snapshot)
        self.assertEqual(snapshot, original)
        parsed['client']['name'] = 'Modification externe fictive'
        self.assertEqual(snapshot, original)

    def test_totals_and_precision_cannot_be_forged_or_misrepresented(self):
        for key, value in (('total_ttc', '0.000'), ('vat_amount', '0.000'), ('precision', True), ('amount_ht', '10.00')):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                snapshot = quote_snapshot()
                snapshot['amounts'][key] = value
                validate_quote_snapshot(snapshot)

    def test_free_mode_requires_zero_money_and_an_explicit_public_proposal_state(self):
        zero = quote_amounts('0.000', '0')
        for state in ('proposed', 'approved'):
            snapshot = quote_snapshot(amounts=zero, fee_mode='free', free_status=state)
            self.assertEqual(validate_quote_snapshot(snapshot)['free_status'], state)
        for changes in ({'amounts': zero}, {'free_status': 'proposed'}, {'fee_mode': 'free'}, {'fee_mode': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_quote_snapshot(quote_snapshot(**changes))

    def test_private_metadata_unknown_schema_and_broken_issued_dates_are_rejected(self):
        for changes in ({'version': True}, {'version': 2}, {'issued_on': '2026-02-31'}, {'issued_on': '20261026'}, {'billing_notes': 'INTERNAL'}, {'free_reason': 'PRIVATE'}, {'issued_by': 'PERSON-PRIVATE'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_quote_snapshot(quote_snapshot(**changes))
        snapshot = quote_snapshot()
        snapshot['client']['internal_notes'] = 'PRIVATE'
        with self.assertRaises(ValidationError):
            validate_quote_snapshot(snapshot)


class DiagnosticQuotePDFTests(SimpleTestCase):
    def test_actual_a4_pdf_contains_issued_numbers_original_equipment_and_price_facts(self):
        snapshot = quote_snapshot()
        data = diagnostic_quote_pdf(snapshot)
        self.assertTrue(data.startswith(b'%PDF-'))
        reader = PdfReader(BytesIO(data), strict=True)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.276, places=2)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.height), 841.890, places=2)
        text = pdf_text(data)
        for value in ('Devis de diagnostic', 'DIAG-26-00042', '26-00042', '000-CENTRE-42', '26/10/2026',
                      'DIAG-FICTIF-ORIGINAL-007', 'Modèle de laboratoire 3 kVA', 'Société de diagnostic fictive',
                      'TEST-FISCAL-00042', 'diagnostic@example.invalid', '10.005', '1.901', '11.906', 'TND',
                      'Précision publique de démonstration.', 'carte non réparable', 'ni facture, ni preuve de paiement'):
            self.assertIn(value, text)

    def test_same_issued_snapshot_reprints_identical_bytes_with_its_issued_date(self):
        snapshot = quote_snapshot()
        original = deepcopy(snapshot)
        first = diagnostic_quote_pdf(snapshot)
        second = diagnostic_quote_pdf(deepcopy(snapshot))
        self.assertEqual(first, second)
        self.assertEqual(snapshot, original)
        reader = PdfReader(BytesIO(first))
        self.assertEqual(reader.metadata.creation_date.date().isoformat(), snapshot['issued_on'])

    def test_free_proposal_and_approved_snapshot_are_labeled_differently_without_private_reasons(self):
        zero = quote_amounts('0.000', '0')
        proposal = pdf_text(diagnostic_quote_pdf(quote_snapshot(amounts=zero, fee_mode='free', free_status='proposed')))
        approved = pdf_text(diagnostic_quote_pdf(quote_snapshot(amounts=zero, fee_mode='free', free_status='approved')))
        self.assertIn('GRATUITÉ PROPOSÉE', proposal)
        self.assertNotIn('GRATUITÉ VALIDÉE', proposal)
        self.assertIn('GRATUITÉ VALIDÉE', approved)
        self.assertIn('0.000 TND', proposal)
        for text in (proposal, approved):
            self.assertNotIn('Facture payée', text)
            self.assertNotIn('PRIVATE', text)

    def test_long_public_diagnosis_and_quote_notes_are_kept_and_not_clipped(self):
        diagnosis = 'Diagnostic fictif détaillé.\n' * 600 + 'FIN-DIAGNOSTIC-PUBLIC'
        notes = 'Condition publique fictive.\n' * 80 + 'FIN-CONDITIONS-PUBLIQUES'
        data = diagnostic_quote_pdf(quote_snapshot(diagnosis=diagnosis, quote_notes=notes))
        self.assertGreater(len(PdfReader(BytesIO(data)).pages), 1)
        text = pdf_text(data)
        self.assertIn('FIN-DIAGNOSTIC-PUBLIC', text)
        self.assertIn('FIN-CONDITIONS-PUBLIQUES', text)

    def test_public_markup_is_printed_as_text_instead_of_pdf_markup(self):
        data = diagnostic_quote_pdf(quote_snapshot(diagnosis='Diagnostic fictif : <script>PUBLIC-TEXTE</script> & contrôle.'))
        self.assertIn('<script>PUBLIC-TEXTE</script>', pdf_text(data))
