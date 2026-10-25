"""Read a serial-number reference workbook as data, without database access.

Only xlrd's BIFF reader is used. No macros, hyperlinks, embedded objects,
instructions, or external connections are executed. Protection of worksheet
editing is not workbook encryption; genuinely encrypted workbooks are refused.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import struct
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

import xlrd
from xlrd.compdoc import CompDocError


MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 20_000
MAX_COLUMNS = 64
MAX_CELL_TEXT = 4096
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SHEETS = (
    "Summary", "Serial numbers", "Warranty period", "Eaton Structure",
    "Pulsar Structure", "Powerware Structure", "NV DX Structure",
)
PRODUCT_HEADERS = (
    "Range", "Product name", "Serial number", "Year of launching",
    "Manufacturing part number", "Catalogue number", "Market / No longer into market",
    "Product name replacement", "Part number", "Serial number structure", "Version", "Return",
)
STRUCTURES = {"Eaton", "Pulsar", "Powerware", "NV DX"}
YEAR_SHEETS = {
    "Eaton Structure": "Eaton", "Pulsar Structure": "Pulsar", "Powerware Structure": "Powerware",
}
NA_CODES = {"NA", "N/A"}


class CatalogueParseError(ValueError):
    """A contextual, safe-to-display error; source record values are not echoed."""


def _error(message, sheet=None, row=None, column=None):
    location = []
    if sheet is not None:
        location.append(f"feuille « {sheet} »")
    if row is not None:
        location.append(f"ligne {row}")
    if column is not None:
        location.append(f"colonne {column}")
    suffix = f" ({', '.join(location)})" if location else ""
    return CatalogueParseError(message + suffix + ".")


def _column(index):
    result = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(sheet, row, column):
    if row >= sheet.nrows or column >= sheet.ncols or column >= sheet.row_len(row):
        return xlrd.empty_cell
    return sheet.cell(row, column)


def _text(sheet, row, column, *, allow_date=False, datemode=0):
    cell = _cell(sheet, row, column)
    value = cell.value
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_ERROR:
        raise _error("Cellule Excel en erreur", sheet.name, row + 1, _column(column))
    if cell.ctype == xlrd.XL_CELL_DATE:
        if not allow_date:
            raise _error("Date Excel inattendue dans une référence ou une durée", sheet.name, row + 1, _column(column))
        try:
            return xlrd.xldate_as_datetime(value, datemode).isoformat()
        except (ValueError, OverflowError, xlrd.XLDateError) as exc:
            raise _error("Date Excel invalide", sheet.name, row + 1, _column(column)) from exc
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        if not math.isfinite(value):
            raise _error("Valeur numérique non finie", sheet.name, row + 1, _column(column))
        # Preserve numeric cell values as text without inventing leading zeros.
        # Integer reference numbers must not acquire a trailing '.0'.
        result = str(int(value)) if value == int(value) else repr(value)
    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
        result = "TRUE" if value else "FALSE"
    else:
        result = str(value)
    if len(result) > MAX_CELL_TEXT or "\x00" in result:
        raise _error("Texte de cellule trop long ou invalide", sheet.name, row + 1, _column(column))
    return result


def _preflight(book):
    names = book.sheet_names()
    if len(names) != len(SHEETS) or set(names) != set(SHEETS):
        raise _error("Le classeur doit contenir les sept feuilles attendues, sans feuille manquante ou supplémentaire")
    total_rows = 0
    for name in SHEETS:
        sheet = book.sheet_by_name(name)
        total_rows += sheet.nrows
        if sheet.nrows > MAX_ROWS or total_rows > MAX_ROWS:
            raise _error("Le classeur dépasse la limite de 20 000 lignes cumulées", name)
        if sheet.ncols > MAX_COLUMNS:
            raise _error("Le classeur dépasse la limite de 64 colonnes", name)
        # Bound every used cell, including cells that do not become a product.
        for row in range(sheet.nrows):
            for column in range(sheet.ncols):
                _text(sheet, row, column, allow_date=True, datemode=book.datemode)


def _summary(book, warnings):
    sheet = book.sheet_by_name("Summary")
    header_row = None
    for row in range(sheet.nrows):
        if (
            _text(sheet, row, 0, allow_date=True, datemode=book.datemode).strip() == "Date"
            and _text(sheet, row, 1, allow_date=True, datemode=book.datemode).strip() == "Revision"
        ):
            header_row = row
            break
    if header_row is None:
        raise _error("En-têtes Date et Revision incomplets", sheet.name)
    revision_row = None
    revision = ""
    for row in range(header_row + 1, sheet.nrows):
        candidate = _text(sheet, row, 1).strip()
        if not candidate:
            continue
        if not re.fullmatch(r"[A-Z]{1,8}", candidate):
            raise _error("Code de révision invalide", sheet.name, row + 1, "B")
        revision_row, revision = row, candidate
    if revision_row is None:
        raise _error("Aucune révision de catalogue trouvée", sheet.name)
    cell = _cell(sheet, revision_row, 0)
    raw_date = _text(sheet, revision_row, 0, allow_date=True, datemode=book.datemode)
    revision_date = None
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            revision_date = xlrd.xldate_as_datetime(cell.value, book.datemode).date().isoformat()
        except (ValueError, OverflowError, xlrd.XLDateError) as exc:
            raise _error("Date de révision invalide", sheet.name, revision_row + 1, "A") from exc
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date.strip()):
        try:
            revision_date = date.fromisoformat(raw_date.strip()).isoformat()
        except ValueError as exc:
            raise _error("Date de révision invalide", sheet.name, revision_row + 1, "A") from exc
    else:
        warnings.append("La date de révision reste textuelle : aucun format de date n'a été supposé.")
    return {
        "revision": revision, "revision_date": revision_date, "revision_date_raw": raw_date,
        "summary_row": revision_row + 1,
        "revision_source_cell": f"B{revision_row + 1}",
        "revision_date_source_cell": f"A{revision_row + 1}",
    }


def _products(book, warnings):
    sheet = book.sheet_by_name("Serial numbers")
    if sheet.nrows < 2 or sheet.ncols < len(PRODUCT_HEADERS):
        raise _error("Table des produits vide ou en-têtes incomplets", sheet.name)
    headers = [_text(sheet, 0, column).strip() for column in range(len(PRODUCT_HEADERS))]
    if tuple(headers) != PRODUCT_HEADERS:
        raise _error("Les douze en-têtes du catalogue ne correspondent pas au format attendu", sheet.name, 1)
    products = []
    unknown_years = 0
    for row in range(1, sheet.nrows):
        values = [_text(sheet, row, column) for column in range(len(PRODUCT_HEADERS))]
        if any(_text(sheet, row, column).strip() for column in range(len(PRODUCT_HEADERS), sheet.ncols)):
            raise _error("Colonne supplémentaire non reconnue dans le catalogue", sheet.name, row + 1)
        if not any(value.strip() for value in values):
            continue
        normalized = [value.strip() for value in values]
        if not normalized[0] or not normalized[1] or not normalized[2]:
            raise _error("Gamme, nom du produit et code produit sont obligatoires", sheet.name, row + 1)
        if len(normalized[2]) > 64 or any(ord(character) < 32 for character in normalized[2]):
            raise _error("Code produit invalide ou trop long", sheet.name, row + 1, "C")
        structure = normalized[9]
        if structure not in STRUCTURES:
            raise _error("Profil de structure de numéro de série non reconnu", sheet.name, row + 1, "J")
        launch_year = None
        if re.fullmatch(r"\d{4}", normalized[3]) and 1900 <= int(normalized[3]) <= 2200:
            launch_year = int(normalized[3])
        else:
            unknown_years += 1
        products.append({
            "source_sheet": sheet.name, "source_row": row + 1,
            "raw_data": dict(zip(PRODUCT_HEADERS, values)),
            "range_name": normalized[0], "product_name": normalized[1], "product_code": normalized[2],
            "launch_year": launch_year, "launch_year_raw": values[3],
            "manufacturing_part_number": normalized[4], "catalogue_number": normalized[5],
            "market_status": normalized[6], "replacement_product_name": normalized[7],
            "replacement_part_number": normalized[8], "structure": structure,
            "version": normalized[10], "return_text": normalized[11],
        })
    if not products:
        raise _error("Aucun produit de référence à importer", sheet.name)
    if unknown_years:
        warnings.append(f"{unknown_years} année(s) de lancement conservée(s) en texte ; aucune année de fabrication n'en est déduite.")
    return products


def _duration_months(text, year_header, sheet, row, column, warnings):
    normalized = " ".join(text.casefold().split())
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(years?|ans?|années?|months?|mois)", normalized)
    if match:
        amount, unit = match.groups()
        factor = 1 if unit in {"month", "months", "mois"} else 12
    elif re.fullmatch(r"[+-]?\d+(?:\.\d+)?", normalized) and year_header:
        amount, factor = normalized, 12
    else:
        warnings.append(f"Durée de garantie conservée en texte, sans unité ou règle supposée ({sheet}, ligne {row}, colonne {column}).")
        return None
    try:
        months = Decimal(amount) * factor
    except InvalidOperation as exc:
        raise _error("Durée de garantie numérique invalide", sheet, row, column) from exc
    if months < 0 or months > 2_147_483_647:
        raise _error("Durée de garantie hors limites", sheet, row, column)
    if months != months.to_integral_value():
        warnings.append(f"Durée de garantie fractionnaire conservée en texte, sans arrondi ({sheet}, ligne {row}, colonne {column}).")
        return None
    return int(months)


def _scope(label):
    normalized = "".join(
        character for character in unicodedata.normalize("NFKD", label.casefold())
        if not unicodedata.combining(character)
    )
    electronic_pattern = r"electronic(?:s)?|electroniques?"
    battery_pattern = r"batter(?:y|ies)|batteries?|batt"
    electronic = bool(re.search(rf"\b(?:{electronic_pattern})\b", normalized))
    battery = bool(re.search(rf"\b(?:{battery_pattern})\b", normalized))
    exclusion = r"(?:except|excluding|without|no|hors|sans|sauf)\s+(?:internal\s+)?"
    excludes_battery = bool(re.search(rf"\b{exclusion}(?:{battery_pattern})\b", normalized))
    excludes_electronic = bool(re.search(rf"\b{exclusion}(?:{electronic_pattern})\b", normalized))
    if electronic and battery:
        if excludes_battery and not excludes_electronic:
            return "electronics"
        if excludes_electronic and not excludes_battery:
            return "batteries"
        if excludes_battery or excludes_electronic:
            return "unspecified"
        if re.search(r"\b(?:and|et)\b|[&+]", normalized):
            return "electronics_and_batteries"
        return "unspecified"
    if electronic and not excludes_electronic:
        return "electronics"
    if battery and not excludes_battery:
        return "batteries"
    return "unspecified"


def _warranties(book, warnings):
    sheet = book.sheet_by_name("Warranty period")
    if sheet.ncols < 9:
        raise _error("Les trois paires de colonnes produit/garantie sont requises", sheet.name)
    pairs = ((1, 2), (4, 5), (7, 8))
    categories, duration_headers = {}, {}
    seen_headers = set()
    brand_group = ""
    result = []
    for row in range(sheet.nrows):
        group_label = _text(sheet, row, 1).strip()
        if group_label in {"FORMER BRANDS", "EATON BRAND"} and not _text(sheet, row, 2).strip():
            brand_group = group_label
            continue
        for product_column, duration_column in pairs:
            raw_label = _text(sheet, row, product_column)
            raw_duration = _text(sheet, row, duration_column)
            label, duration = raw_label.strip(), raw_duration.strip()
            if not label and not duration:
                continue
            if re.fullmatch(r"Warranty(?:\s*\(\s*Years?\s*\))?", duration, re.IGNORECASE):
                if not label:
                    raise _error("Titre de catégorie de garantie manquant", sheet.name, row + 1, _column(product_column))
                categories[product_column] = label
                duration_headers[product_column] = duration
                seen_headers.add(product_column)
                continue
            if product_column not in categories:
                raise _error("En-tête de catégorie/garantie absent avant les données", sheet.name, row + 1, _column(product_column))
            if not label:
                raise _error("Produit manquant pour une durée de garantie", sheet.name, row + 1, _column(product_column))
            header = duration_headers[product_column]
            source_column = _column(product_column)
            months = _duration_months(
                duration, bool(re.search(r"\byears?\b", header, re.IGNORECASE)),
                sheet.name, row + 1, _column(duration_column), warnings,
            )
            result.append({
                "source_sheet": sheet.name, "source_row": row + 1, "source_column": source_column,
                "product_name": label, "category": categories[product_column], "brand_group": brand_group,
                "scope": _scope(label), "duration_text": duration, "duration_months": months,
                # Preserve the full qualification/exclusion wording. No coverage
                # is inferred for components not explicitly named by the source.
                "conditions": label,
                "raw_data": {
                    "product_cell": f"{source_column}{row + 1}",
                    "duration_cell": f"{_column(duration_column)}{row + 1}",
                    "product_name": raw_label, "duration_text": raw_duration,
                    "header": header, "brand_group": brand_group,
                },
            })
    if seen_headers != {1, 4, 7}:
        raise _error("En-têtes incomplets : les trois paires de colonnes de garantie sont nécessaires", sheet.name)
    if not result:
        raise _error("Aucune ligne de garantie de référence trouvée", sheet.name)
    return result


def _year_tables(book):
    result = []
    for sheet_name, structure in YEAR_SHEETS.items():
        sheet = book.sheet_by_name(sheet_name)
        header_positions = []
        for row in range(sheet.nrows):
            for column in range(max(0, sheet.ncols - 1)):
                if _text(sheet, row, column).strip() == "Year of manufacturing" and _text(sheet, row, column + 1).strip() == "Year":
                    header_positions.append((row, column))
        if len(header_positions) != 1:
            raise _error("Une table explicite Year of manufacturing / Year est requise", sheet_name)
        header_row, code_column = header_positions[0]
        used_codes = {}
        for row in range(header_row + 1, sheet.nrows):
            raw_code = _text(sheet, row, code_column)
            raw_year = _text(sheet, row, code_column + 1).strip()
            if not raw_code.strip() and not raw_year:
                continue
            if not raw_code.strip() or not re.fullmatch(r"\d{4}", raw_year) or not 1900 <= int(raw_year) <= 2200:
                raise _error("Couple code/année incomplet ou année invalide", sheet_name, row + 1, _column(code_column))
            aliases = re.split(r"\s*(?:/|,|\bor\b)\s*", raw_code.strip(), flags=re.IGNORECASE)
            if not aliases or any(not re.fullmatch(r"[A-Z0-9]", alias) for alias in aliases) or len(set(aliases)) != len(aliases):
                raise _error("Code ou expression d'alias d'année non reconnu", sheet_name, row + 1, _column(code_column))
            year = int(raw_year)
            for code in aliases:
                if code in used_codes and used_codes[code] != year:
                    raise _error("Code d'année ambigu dans une même structure", sheet_name, row + 1, _column(code_column))
                used_codes[code] = year
                result.append({
                    "structure": structure, "source_sheet": sheet_name, "source_row": row + 1,
                    "source_column": _column(code_column),
                    "source_cells": {"code": f"{_column(code_column)}{row + 1}", "year": f"{_column(code_column + 1)}{row + 1}"},
                    "code": code, "year": year, "raw_code": raw_code,
                })
        if not used_codes:
            raise _error("Table d'années vide", sheet_name)
    return result


def parse_catalogue(data: bytes, filename: str = "catalogue.xls") -> dict:
    """Validate all records and return plain Python data without side effects.

    A product is identified by snapshot + source sheet + row, never by the code
    alone. 'Serial number' in this catalogue is a product reference code; it is
    not the serial number of a customer's physical device.
    """
    if not isinstance(data, bytes):
        raise _error("Le contenu du classeur doit être fourni en octets")
    if not data or len(data) > MAX_BYTES:
        raise _error("Le fichier est vide ou dépasse la limite de 8 Mio")
    if not data.startswith(OLE_SIGNATURE):
        raise _error("Format attendu : classeur Excel .xls BIFF non chiffré")
    if not isinstance(filename, str) or not filename or len(filename) > 1024:
        raise _error("Nom de fichier invalide")
    clean_filename = re.split(r"[\\/]", filename)[-1]
    if not clean_filename or len(clean_filename) > 255 or any(ord(character) < 32 for character in clean_filename):
        raise _error("Nom de fichier invalide")
    book = None
    try:
        book = xlrd.open_workbook(
            file_contents=data, on_demand=True, formatting_info=False,
            ragged_rows=True, logfile=io.StringIO(), ignore_workbook_corruption=False,
        )
        _preflight(book)
        warnings = []
        summary = _summary(book, warnings)
        products = _products(book, warnings)
        warranties = _warranties(book, warnings)
        years = _year_tables(book)
        code_counts = Counter(
            (product["structure"], product["product_code"].strip().casefold())
            for product in products if product["product_code"].upper() not in NA_CODES
        )
        duplicate_groups = sum(count > 1 for count in code_counts.values())
        na_count = sum(product["product_code"].upper() in NA_CODES for product in products)
        profiles_by_code = defaultdict(set)
        for structure, code in code_counts:
            profiles_by_code[code].add(structure)
        if duplicate_groups:
            warnings.append(f"{duplicate_groups} code(s) possèdent plusieurs lignes dans un même profil : sélection explicite du produit obligatoire.")
        if na_count:
            warnings.append(f"{na_count} code(s) NA/N/A conservé(s) ; aucun code de produit ni numéro de série physique n'a été inventé.")
        warnings.append("Les tables d'années restent propres à chaque structure ; aucune extrapolation ni date de fin de garantie n'a été calculée.")
        metadata = {
            "filename": clean_filename, "sha256": hashlib.sha256(data).hexdigest(),
            "source_format": "xls", "encrypted": False, "sheets": list(book.sheet_names()), **summary,
        }
        return {
            "metadata": metadata, "products": products, "warranties": warranties,
            "year_tables": years,
            "counts": {
                "products": len(products), "warranties": len(warranties), "year_mappings": len(years),
                "na_codes": na_count, "duplicate_code_groups": duplicate_groups,
                "cross_structure_codes": sum(len(profiles) > 1 for profiles in profiles_by_code.values()),
            },
            "warnings": warnings,
        }
    except CatalogueParseError:
        raise
    except xlrd.XLRDError as exc:
        if "encrypt" in str(exc).casefold():
            raise _error("Le classeur est chiffré : fournissez un export .xls déchiffré ; aucune tentative de mot de passe n'est exécutée") from exc
        raise _error("Le classeur .xls est endommagé ou son format BIFF n'est pas pris en charge") from exc
    except (OSError, ValueError, IndexError, TypeError, OverflowError, EOFError, CompDocError, struct.error, AssertionError) as exc:
        raise _error("Le classeur .xls est mal formé ou contient une valeur non prise en charge") from exc
    finally:
        if book is not None:
            book.release_resources()
