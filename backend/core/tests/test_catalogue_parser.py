"""Parser tests use an entirely fictional XLS, never the customer's workbook."""

import hashlib
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import xlrd

from core.catalogue_parser import (
    CatalogueParseError, MAX_BYTES, MAX_CELL_TEXT, parse_catalogue,
)


FIXTURE = Path(__file__).with_name("fixtures") / "catalogue_synthetic.xls"


class CatalogueParserTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = FIXTURE.read_bytes()

    def parse(self):
        return parse_catalogue(self.data, "catalogue_synthetic.xls")

    def mutated(self, change):
        # Exercise validation against a real xlrd-decoded BIFF workbook while
        # changing one cell or dimension. xlwt is only fixture-generation tooling.
        book = xlrd.open_workbook(file_contents=self.data, on_demand=True, ragged_rows=False)
        book.sheets()
        change(book)
        with patch("core.catalogue_parser.xlrd.open_workbook", return_value=book):
            return self.parse()

    @staticmethod
    def cell(book, sheet, row, column, value, kind=xlrd.XL_CELL_TEXT):
        target = book.sheet_by_name(sheet)
        target._cell_values[row][column] = value
        target._cell_types[row][column] = kind

    def test_real_xls_reads_all_sections_and_metadata(self):
        parsed = self.parse()
        self.assertEqual(parsed["metadata"]["revision"], "ZZ")
        self.assertEqual(parsed["metadata"]["revision_date"], "2024-01-15")
        self.assertEqual(parsed["metadata"]["sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertFalse(parsed["metadata"]["encrypted"])
        self.assertEqual(len(parsed["metadata"]["sheets"]), 7)
        self.assertEqual(parsed["counts"], {
            "products": 4, "warranties": 6, "year_mappings": 9, "na_codes": 1,
            "duplicate_code_groups": 1, "cross_structure_codes": 1,
        })

    def test_numeric_references_do_not_gain_decimal_suffix_and_text_keeps_zeros(self):
        products = self.parse()["products"]
        self.assertEqual(products[0]["manufacturing_part_number"], "000012345")
        self.assertEqual(products[3]["manufacturing_part_number"], "1234500000")
        self.assertEqual(products[3]["catalogue_number"], "00012")
        self.assertEqual(products[0]["raw_data"]["Manufacturing part number"], "000012345")
        self.assertEqual(products[3]["raw_data"]["Manufacturing part number"], "1234500000")

    def test_duplicate_product_codes_and_na_are_preserved_with_source_identity(self):
        parsed = self.parse()
        candidates = [p for p in parsed["products"] if p["structure"] == "Eaton" and p["product_code"] == "QX1"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual([p["source_row"] for p in candidates], [2, 3])
        self.assertNotEqual(candidates[0]["catalogue_number"], candidates[1]["catalogue_number"])
        self.assertEqual(parsed["products"][3]["product_code"], "NA")
        self.assertTrue(any("sélection explicite" in warning for warning in parsed["warnings"]))

    def test_code_statistics_are_case_insensitive_without_changing_source_values(self):
        parsed = self.mutated(lambda book: self.cell(book, "Serial numbers", 1, 2, "  qx1  "))
        self.assertEqual(parsed["products"][0]["product_code"], "qx1")
        self.assertEqual(parsed["products"][0]["raw_data"]["Serial number"], "  qx1  ")
        self.assertEqual(parsed["counts"]["duplicate_code_groups"], 1)
        self.assertEqual(parsed["counts"]["cross_structure_codes"], 1)

    def test_launch_year_is_not_manufacture_year_and_raw_na_is_kept(self):
        products = self.parse()["products"]
        self.assertEqual(products[0]["launch_year"], 2024)
        self.assertEqual(products[0]["launch_year_raw"], "2024")
        self.assertIsNone(products[3]["launch_year"])
        self.assertEqual(products[3]["launch_year_raw"], "NA")
        self.assertNotIn("manufactured_at", products[0])

    def test_warranty_electronics_and_battery_are_separate_and_do_not_create_dates(self):
        warranties = self.parse()["warranties"]
        electronic = next(w for w in warranties if w["scope"] == "electronics")
        battery = next(w for w in warranties if "Internal battery" in w["product_name"])
        self.assertEqual(electronic["duration_months"], 36)
        self.assertEqual(battery["scope"], "batteries")
        self.assertEqual(battery["duration_months"], 24)
        self.assertIn("Only Electronic", electronic["conditions"])
        self.assertEqual(electronic["source_column"], "B")
        self.assertEqual(electronic["raw_data"]["duration_cell"], "C6")
        self.assertTrue(all("ends_on" not in item and "starts_on" not in item for item in warranties))

    def test_text_units_and_ambiguous_duration_are_preserved(self):
        warranties = self.parse()["warranties"]
        self.assertEqual(next(w for w in warranties if w["duration_text"] == "3 months")["duration_months"], 3)
        self.assertEqual(next(w for w in warranties if w["duration_text"] == "1 year")["duration_months"], 12)
        ambiguous = next(w for w in warranties if w["duration_text"] == "selon contrat")
        self.assertIsNone(ambiguous["duration_months"])
        self.assertEqual(ambiguous["raw_data"]["duration_text"], "selon contrat")

    def test_numeric_duration_without_year_header_is_not_silently_assumed(self):
        parsed = self.mutated(lambda book: self.cell(book, "Warranty period", 5, 8, 5.0, xlrd.XL_CELL_NUMBER))
        warranty = next(w for w in parsed["warranties"] if w["source_column"] == "H" and w["source_row"] == 6)
        self.assertEqual(warranty["duration_text"], "5")
        self.assertIsNone(warranty["duration_months"])

    def test_explicit_exclusion_does_not_become_combined_coverage(self):
        parsed = self.mutated(lambda book: self.cell(book, "Warranty period", 5, 1, "Fiction electronic except battery"))
        warranty = next(w for w in parsed["warranties"] if w["source_column"] == "B" and w["source_row"] == 6)
        self.assertEqual(warranty["scope"], "electronics")
        self.assertEqual(warranty["conditions"], "Fiction electronic except battery")

    def test_year_aliases_remain_independent_per_structure_with_source_cells(self):
        tables = self.parse()["year_tables"]
        lookup = {(item["structure"], item["code"]): item for item in tables}
        self.assertEqual(lookup[("Eaton", "A")]["year"], 2040)
        self.assertEqual(lookup[("Pulsar", "A")]["year"], 2001)
        self.assertEqual(lookup[("Powerware", "A")]["year"], 2021)
        self.assertEqual(lookup[("Eaton", "I")]["year"], lookup[("Eaton", "J")]["year"])
        self.assertEqual(lookup[("Pulsar", "I")]["raw_code"], "I,J")
        self.assertEqual(lookup[("Powerware", "Z")]["raw_code"], "Z or A")
        self.assertEqual(lookup[("Eaton", "I")]["source_cells"], {"code": "K6", "year": "L6"})
        self.assertNotIn(("Eaton", "B"), lookup)
        self.assertFalse(any(item["structure"] == "NV DX" for item in tables))

    def test_ambiguous_year_mapping_is_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "ambigu.*Eaton Structure.*ligne 6"):
            self.mutated(lambda book: self.cell(book, "Eaton Structure", 5, 10, "A"))

    def test_unknown_alias_expression_is_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "alias.*Eaton Structure.*ligne 6"):
            self.mutated(lambda book: self.cell(book, "Eaton Structure", 5, 10, "I and J"))

    def test_missing_year_value_is_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "code/année.*Pulsar Structure"):
            self.mutated(lambda book: self.cell(book, "Pulsar Structure", 5, 11, ""))

    def test_incomplete_catalogue_header_is_rejected_before_any_result(self):
        with self.assertRaisesRegex(CatalogueParseError, "douze en-têtes.*Serial numbers.*ligne 1"):
            self.mutated(lambda book: self.cell(book, "Serial numbers", 0, 4, "Unrecognized header"))

    def test_missing_summary_header_is_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "Date et Revision.*Summary"):
            self.mutated(lambda book: self.cell(book, "Summary", 7, 0, "Unknown"))

    def test_incomplete_warranty_headers_are_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "En-tête.*Warranty period"):
            self.mutated(lambda book: self.cell(book, "Warranty period", 4, 8, ""))

    def test_unknown_structure_is_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "Profil.*Serial numbers.*ligne 2"):
            self.mutated(lambda book: self.cell(book, "Serial numbers", 1, 9, "Unknown fictional profile"))

    def test_dates_in_reference_or_warranty_cells_are_rejected(self):
        for sheet, row, column in [("Serial numbers", 1, 2), ("Warranty period", 5, 2)]:
            with self.subTest(sheet=sheet), self.assertRaisesRegex(CatalogueParseError, "Date Excel inattendue"):
                self.mutated(lambda book: self.cell(book, sheet, row, column, 45260.0, xlrd.XL_CELL_DATE))

    def test_ambiguous_summary_date_is_kept_as_text(self):
        parsed = self.mutated(lambda book: self.cell(book, "Summary", 8, 0, "01/02/2024"))
        self.assertIsNone(parsed["metadata"]["revision_date"])
        self.assertEqual(parsed["metadata"]["revision_date_raw"], "01/02/2024")
        self.assertTrue(any("date de révision reste textuelle" in w for w in parsed["warnings"]))

    def test_negative_or_excessive_duration_is_rejected(self):
        for duration in [-1.0, 1_000_000_000.0]:
            with self.subTest(duration=duration), self.assertRaisesRegex(CatalogueParseError, "Durée.*hors limites"):
                self.mutated(lambda book: self.cell(book, "Warranty period", 5, 2, duration, xlrd.XL_CELL_NUMBER))

    def test_fractional_month_is_kept_in_text_without_rounding(self):
        parsed = self.mutated(lambda book: self.cell(book, "Warranty period", 5, 8, "1.5 months"))
        item = next(w for w in parsed["warranties"] if w["source_row"] == 6 and w["source_column"] == "H")
        self.assertIsNone(item["duration_months"])
        self.assertEqual(item["duration_text"], "1.5 months")

    def test_cell_text_size_is_bounded(self):
        with self.assertRaisesRegex(CatalogueParseError, "Texte.*trop long"):
            self.mutated(lambda book: self.cell(book, "Serial numbers", 1, 1, "x" * (MAX_CELL_TEXT + 1)))

    def test_sheet_rows_and_columns_are_bounded_before_cell_read(self):
        for attr, value, expected in [("nrows", 20_001, "20 000"), ("ncols", 65, "64 colonnes")]:
            with self.subTest(dimension=attr), self.assertRaisesRegex(CatalogueParseError, expected):
                self.mutated(lambda book: setattr(book.sheet_by_name("Serial numbers"), attr, value))

    def test_missing_sheet_is_rejected(self):
        with self.assertRaisesRegex(CatalogueParseError, "sept feuilles"):
            self.mutated(lambda book: book._sheet_names.pop())

    def test_non_biff_malformed_or_too_large_input_is_rejected(self):
        for data in [b"", b"not-an-excel-workbook", b"PK\x03\x04fake-xlsx", b"x" * (MAX_BYTES + 1)]:
            with self.subTest(length=len(data)), self.assertRaises(CatalogueParseError):
                parse_catalogue(data)
        with self.assertRaises(CatalogueParseError):
            parse_catalogue(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1broken")

    def test_encryption_error_is_explicit_without_password_attempt(self):
        with patch("core.catalogue_parser.xlrd.open_workbook", side_effect=xlrd.XLRDError("Workbook is encrypted")) as opener:
            with self.assertRaisesRegex(CatalogueParseError, "chiffré.*dé chiffré|chiffré.*déchiffré"):
                self.parse()
            opener.assert_called_once()

    def test_workbook_is_opened_read_only_without_formatting_or_external_execution(self):
        original = xlrd.open_workbook
        with patch("core.catalogue_parser.xlrd.open_workbook", wraps=original) as opener:
            self.parse()
        self.assertFalse(opener.call_args.kwargs["formatting_info"])
        self.assertTrue(opener.call_args.kwargs["on_demand"])
        self.assertFalse(opener.call_args.kwargs["ignore_workbook_corruption"])
        self.assertNotIn("password", opener.call_args.kwargs)

    def test_filename_is_metadata_basename_only(self):
        result = parse_catalogue(self.data, r"C:\fakepath\synthetic.xls")
        self.assertEqual(result["metadata"]["filename"], "synthetic.xls")
