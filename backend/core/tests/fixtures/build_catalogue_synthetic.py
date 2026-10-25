"""Generate the entirely fictional, public BIFF fixture used by catalogue tests.

Tooling only: run with xlwt==1.3.0 installed in a separate tooling environment.
There are no entries copied from a customer's catalogue in this workbook.
"""

from datetime import datetime
from pathlib import Path

import xlwt


HEADERS = [
    "Range", "Product name", "Serial number", "Year of launching",
    "Manufacturing part number", "Catalogue number", "Market / No longer into market",
    "Product name replacement", "Part number", "Serial number structure", "Version", "Return",
]


def build(destination):
    book = xlwt.Workbook()
    summary = book.add_sheet("Summary")
    for c, value in enumerate(["Date", "Revision", "Modifications", "Who", "", "Links"]):
        summary.write(7, c, value)
    summary.write(8, 0, datetime(2024, 1, 15), xlwt.easyxf(num_format_str="YYYY-MM-DD"))
    summary.write(8, 1, "ZZ")
    summary.write(8, 2, "SYNTHETIC PUBLIC TEST FIXTURE — NOT A MANUFACTURER CATALOGUE")
    serial = book.add_sheet("Serial numbers")
    for c, value in enumerate(HEADERS):
        serial.write(0, c, value)
    rows = [
        ["Laboratoire fiction", "Onduleur laboratoire Alpha", "QX1", 2024, "000012345", "DEMO-001", "In market", "", "", "Eaton", "V1", ""],
        ["Laboratoire fiction", "Onduleur laboratoire Alpha variante", "QX1", 2024, "MFG-DEMO-002", "DEMO-002", "In market", "Remplacement fictif", "DEMO-NEXT", "Eaton", "V2", ""],
        ["Laboratoire fiction", "Onduleur laboratoire Beta", "QX1", 2001, "MFG-DEMO-003", "DEMO-003", "No longer into market", "No replacement", "No replacement", "Pulsar", "", ""],
        ["Laboratoire fiction", "Onduleur laboratoire Gamma", "NA", "NA", 1234500000, "00012", "In market", "", "", "Powerware", "", ""],
    ]
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            serial.write(r, c, value)
    warranty = book.add_sheet("Warranty period")
    warranty.write(2, 1, "FORMER BRANDS")
    for pc, dc, category, header in [(1, 2, "Pulsar", "Warranty (Year)"), (4, 5, "Powerware", "Warranty (Year)"), (7, 8, "Other", "Warranty")]:
        warranty.write(4, pc, category)
        warranty.write(4, dc, header)
    entries = [
        (5, 1, "Onduleur laboratoire Alpha (Only Electronic)", 3),
        (6, 1, "Onduleur laboratoire Alpha Internal battery", 2),
        (5, 4, "Onduleur laboratoire Gamma", 2),
        (6, 4, "Couverture fiction selon contrat", "selon contrat"),
        (5, 7, "Accessoire de laboratoire", "3 months"),
        (6, 7, "Batterie de laboratoire", "1 year"),
    ]
    for r, c, label, duration in entries:
        warranty.write(r, c, label)
        warranty.write(r, c + 1, duration)
    for name, column, pairs in [
        ("Eaton Structure", 10, [("A", 2040), ("I/J", 2041)]),
        ("Pulsar Structure", 10, [("A", 2001), ("I,J", 2002)]),
        ("Powerware Structure", 8, [("S", 2020), ("Z or A", 2021)]),
    ]:
        sheet = book.add_sheet(name)
        sheet.write(3, column, "Year of manufacturing")
        sheet.write(3, column + 1, "Year")
        for row, (code, year) in enumerate(pairs, start=4):
            sheet.write(row, column, code)
            sheet.write(row, column + 1, year)
    nv_dx = book.add_sheet("NV DX Structure")
    nv_dx.write(2, 1, "DX RANGE — SYNTHETIC FIXTURE")
    nv_dx.write(2, 9, "NV RANGE — NO YEAR TABLE")
    book.save(str(destination))


if __name__ == "__main__":
    build(Path(__file__).with_name("catalogue_synthetic.xls"))
