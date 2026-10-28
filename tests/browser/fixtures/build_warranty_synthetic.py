"""Build a wholly fictional BIFF workbook; no uploaded catalogue entry is used.

Tooling only: xlwt==1.3.0. The committed XLS lets browser tests run without it.
"""
from datetime import datetime
from pathlib import Path
import xlwt


def build():
    book = xlwt.Workbook()
    summary = book.add_sheet('Summary')
    for column, title in enumerate(['Date', 'Revision', 'Modifications', 'Who', '', 'Links']):
        summary.write(7, column, title)
    summary.write(8, 0, datetime(2024, 1, 1), xlwt.easyxf(num_format_str='YYYY-MM-DD'))
    summary.write(8, 1, 'QA')
    summary.write(8, 2, 'FICTIONAL PUBLIC WARRANTY TEST — NOT A MANUFACTURER ENTRY')
    serial = book.add_sheet('Serial numbers')
    headers = ['Range', 'Product name', 'Serial number', 'Year of launching',
               'Manufacturing part number', 'Catalogue number', 'Market / No longer into market',
               'Product name replacement', 'Part number', 'Serial number structure', 'Version', 'Return']
    for column, title in enumerate(headers):
        serial.write(0, column, title)
    row = ['Laboratoire Garantie G2', 'Onduleur de laboratoire fictif G2', 'WG2', 2023,
           'LAB-IND-WAR', 'LAB-WAR-G2', 'In market', '', '', 'Eaton', 'G2', '']
    for column, value in enumerate(row):
        serial.write(1, column, value)
    warranty = book.add_sheet('Warranty period')
    warranty.write(2, 1, 'FORMER BRANDS')
    for column, category in [(1, 'Pulsar'), (4, 'Powerware'), (7, 'Other')]:
        warranty.write(4, column, category)
        warranty.write(4, column + 1, 'Warranty (Year)')
    warranty.write(5, 1, 'Laboratoire Garantie')
    warranty.write(5, 2, 2)
    for name, column, code, year in [('Eaton Structure', 10, 'A', 2023),
                                     ('Pulsar Structure', 10, 'B', 2004),
                                     ('Powerware Structure', 8, 'S', 2020)]:
        sheet = book.add_sheet(name)
        sheet.write(3, column, 'Year of manufacturing')
        sheet.write(3, column + 1, 'Year')
        sheet.write(4, column, code)
        sheet.write(4, column + 1, year)
    nv = book.add_sheet('NV DX Structure')
    nv.write(2, 1, 'FICTIONAL STRUCTURE TEST — NO YEAR INFERENCE')
    book.save(str(Path(__file__).with_name('warranty_synthetic.xls')))


if __name__ == '__main__':
    build()
