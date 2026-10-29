"""Displayed repair quote arithmetic; no database and no real client data."""
from copy import deepcopy
from decimal import Decimal, Inexact, ROUND_DOWN, Rounded, localcontext

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from core.repair_quote_money import repair_quote_amounts


def line(quantity='1', unit_ht='10.000', description='Prestation fictive'):
    return {'description': description, 'quantity': quantity, 'unit_ht': unit_ht}


class RepairQuoteMoneyTests(SimpleTestCase):
    def test_fractional_lines_percentage_discount_then_vat_are_rounded_half_up_in_tnd(self):
        amounts = repair_quote_amounts([line('2.5', '10.125'), line('3', '4.200')],
            vat_rate='19', discount_kind='percent', discount_value='7.5')
        self.assertEqual(amounts, {
            'currency': 'TND', 'precision': 3,
            'lines': [dict(line('2.5', '10.125'), total_ht='25.313'), dict(line('3', '4.200'), total_ht='12.600')],
            'subtotal_ht': '37.913', 'discount_kind': 'percent', 'discount_value': '7.5',
            'discount_ht': '2.843', 'net_ht': '35.070', 'vat_rate': '19', 'vat_amount': '6.663',
            'total_ttc': '41.733', 'fully_discounted': False})

    def test_subtotal_is_the_sum_of_rounded_displayed_lines_not_unrounded_products(self):
        amounts = repair_quote_amounts([line('1.5', '0.01'), line('1.5', '0.01')], vat_rate='19', currency='EUR')
        self.assertEqual([row['total_ht'] for row in amounts['lines']], ['0.02', '0.02'])
        self.assertEqual(amounts['subtotal_ht'], '0.04')
        self.assertEqual(amounts['vat_amount'], '0.01')
        self.assertEqual(amounts['total_ttc'], '0.05')

    def test_discount_and_tax_both_use_half_up_at_currency_precision(self):
        amounts = repair_quote_amounts([line('3', '0.005')], vat_rate='50', discount_kind='percent', discount_value='50')
        self.assertEqual((amounts['subtotal_ht'], amounts['discount_ht'], amounts['net_ht']), ('0.015', '0.008', '0.007'))
        self.assertEqual((amounts['vat_amount'], amounts['total_ttc']), ('0.004', '0.011'))

    def test_fixed_discount_is_ht_and_vat_is_computed_on_net(self):
        for currency in ('EUR', 'USD'):
            with self.subTest(currency=currency):
                amounts = repair_quote_amounts([line('3.333', '1.23')], vat_rate='19.00', currency=currency,
                    discount_kind='fixed', discount_value='0.10')
                self.assertEqual(amounts['precision'], 2)
                self.assertEqual((amounts['subtotal_ht'], amounts['discount_ht'], amounts['net_ht']), ('4.10', '0.10', '4.00'))
                self.assertEqual((amounts['vat_amount'], amounts['total_ttc']), ('0.76', '4.76'))

    def test_full_discount_is_explicit_without_creating_financial_workflow_evidence(self):
        for kind, value in [('percent', '100'), ('fixed', '42.000')]:
            with self.subTest(kind=kind):
                amounts = repair_quote_amounts([line(unit_ht='42.000')], vat_rate='19', discount_kind=kind, discount_value=value)
                self.assertTrue(amounts['fully_discounted'])
                self.assertEqual(amounts['discount_ht'], '42.000')
                self.assertEqual((amounts['net_ht'], amounts['vat_amount'], amounts['total_ttc']), ('0.000', '0.000', '0.000'))
                for forbidden in ('invoice_reference', 'paid', 'free_approved', 'accepted', 'finance_validated_at'):
                    self.assertNotIn(forbidden, amounts)

    def test_zero_price_is_not_a_claim_of_full_discount_and_zero_vat_is_explicit(self):
        amounts = repair_quote_amounts([line(unit_ht='0.000')], vat_rate='0')
        self.assertFalse(amounts['fully_discounted'])
        self.assertEqual(amounts['total_ttc'], '0.000')
        for rate in (None, '', ' ', False):
            with self.subTest(rate=rate), self.assertRaises(ValidationError):
                repair_quote_amounts([line()], vat_rate=rate)

    def test_bad_discounts_cannot_create_negative_net_or_silently_disappear(self):
        for kind, value in [('fixed', '10.001'), ('percent', '100.01'), ('percent', '-0.01'),
                            ('percent', '7.501'), ('fixed', '-1.000'), ('none', '1'), ('unknown', '0'),
                            ('fixed', '0.0001'), ('percent', 'NaN'), ('percent', True), ('percent', 7.5)]:
            with self.subTest(kind=kind, value=value), self.assertRaises(ValidationError):
                repair_quote_amounts([line()], vat_rate='19', discount_kind=kind, discount_value=value)

    def test_unknown_currency_and_raw_excess_currency_precision_are_rejected(self):
        for currency, price in [('BTC', '1'), ('', '1'), (True, '1'), (None, '1'), ('EUR', '1.001'),
                                 ('USD', '1.000'), ('TND', '1.0001')]:
            with self.subTest(currency=currency, price=price), self.assertRaises(ValidationError):
                repair_quote_amounts([line(unit_ht=price)], vat_rate='19', currency=currency)
        for currency in ('EUR', 'USD'):
            with self.assertRaises(ValidationError):
                repair_quote_amounts([line(unit_ht='10.00')], vat_rate='19', currency=currency, discount_kind='fixed', discount_value='0.001')

    def test_quantities_are_positive_bounded_and_have_at_most_three_decimals(self):
        for quantity in ('0', '-1', '1000000', '0.0001', '1.0000', True, 1.5):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                repair_quote_amounts([line(quantity=quantity)], vat_rate='19')
        amounts = repair_quote_amounts([line(quantity='999999.999', unit_ht='0.001')], vat_rate='0')
        self.assertEqual(amounts['lines'][0]['quantity'], '999999.999')
        self.assertEqual(amounts['subtotal_ht'], '1000.000')

    def test_nonfinite_exponents_floats_controls_and_negative_prices_are_rejected(self):
        for value in ('NaN', 'sNaN', 'Infinity', '-Infinity', '1e2', '-0.001', '1,25', '1_000', True, 1.25, {}, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                repair_quote_amounts([line(unit_ht=value)], vat_rate='19')
        for rate in ('NaN', 'Infinity', '19.001', '100.01', '1e1', '-1', True, 19.0):
            with self.subTest(rate=rate), self.assertRaises(ValidationError):
                repair_quote_amounts([line()], vat_rate=rate)
        for description in ('', '   ', 'x' * 2001, 'Fictif\x00', 'Fictif\ud800', 42):
            with self.subTest(description=repr(description)), self.assertRaises(ValidationError):
                repair_quote_amounts([line(description=description)], vat_rate='19')

    def test_lines_are_bounded_and_cannot_smuggle_readonly_totals_or_internal_fields(self):
        for lines in ([], [line()] * 101, (), {}, [dict(line(), total_ht='0.000')], [dict(line(), internal_notes='PRIVATE')],
                      [{'description': 'Fictif', 'quantity': '1'}], [True]):
            with self.subTest(lines=type(lines)), self.assertRaises(ValidationError):
                repair_quote_amounts(lines, vat_rate='19')
        self.assertEqual(len(repair_quote_amounts([line(unit_ht='0.001')] * 100, vat_rate='0')['lines']), 100)

    def test_database_decimal_padding_is_accepted_but_significant_extra_precision_is_not(self):
        amounts = repair_quote_amounts([line(Decimal('1.25000'), Decimal('19.99000'))], vat_rate=Decimal('19.0000'), currency='EUR')
        self.assertEqual(amounts['lines'][0]['quantity'], '1.25')
        self.assertEqual(amounts['lines'][0]['unit_ht'], '19.99')
        for price in (Decimal('19.991'), Decimal('0.001')):
            with self.subTest(price=price), self.assertRaises(ValidationError):
                repair_quote_amounts([line(unit_ht=price)], vat_rate='19', currency='EUR')

    def test_extreme_negative_exponents_are_rejected_without_decimal_underflow_normalization(self):
        for key in ('quantity', 'unit_ht'):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                repair_quote_amounts([dict(line(), **{key: Decimal('1e-99999999')})], vat_rate='19')

    def test_line_and_subtotal_bounds_prevent_overflow_but_allow_maximum_valid_quote(self):
        amounts = repair_quote_amounts([line(unit_ht='999999999.999')], vat_rate='100')
        self.assertEqual(amounts['total_ttc'], '1999999999.998')
        for lines in ([line(unit_ht='1000000000')], [line(quantity='2', unit_ht='999999999.999')],
                      [line(unit_ht='999999999.999'), line(unit_ht='0.001')]):
            with self.subTest(lines=lines), self.assertRaises(ValidationError):
                repair_quote_amounts(lines, vat_rate='19')

    def test_hostile_global_decimal_context_does_not_affect_or_get_changed_by_calculation(self):
        lines = [line('2.5', '123456.789')]
        expected = repair_quote_amounts(lines, vat_rate='19.99', discount_kind='percent', discount_value='7.55')
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            context.Emin, context.Emax = -3, 3
            context.traps[Inexact] = context.traps[Rounded] = True
            self.assertEqual(repair_quote_amounts(lines, vat_rate='19.99', discount_kind='percent', discount_value='7.55'), expected)
            self.assertEqual((context.prec, context.rounding, context.Emin, context.Emax), (2, ROUND_DOWN, -3, 3))
            self.assertTrue(context.traps[Inexact])

    def test_canonical_formatting_and_negative_zero_do_not_mutate_input(self):
        lines = [line('1.250', '-0.000', '  Prestation fictive  ')]
        original = deepcopy(lines)
        amounts = repair_quote_amounts(lines, vat_rate='-0.00', currency=' tnd ')
        self.assertEqual(lines, original)
        self.assertEqual(amounts['currency'], 'TND')
        self.assertEqual(amounts['lines'][0], {'description': 'Prestation fictive', 'quantity': '1.25', 'unit_ht': '0.000', 'total_ht': '0.000'})
        self.assertEqual(amounts['vat_rate'], '0')
