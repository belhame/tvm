"""Pure, conservative geometries from the supplied serialisation documents.

No catalogue lookup, ORM access, equipment mutation, or warranty calculation is
performed here. Dates based on a week are reference Mondays, never a claim about
an exact manufacturing day or contractual warranty commencement.
"""
from __future__ import annotations

from datetime import date
import re

PROFILES = ('Eaton', 'Pulsar', 'Powerware', 'NV DX')
_ALPHANUMERIC = re.compile(r'[A-Z0-9]+\Z', re.ASCII)
_DX = re.compile(r'(\d{2})(\d{2})(\d{2})-(\d{8})\Z', re.ASCII)
_NV_YEARS = {**{str(n): 2000 + n for n in range(1, 10)}, 'D': 2010, 'E': 2011, 'F': 2012}
_NV_MONTHS = {**{str(n): n for n in range(1, 10)}, 'A': 10, 'B': 11, 'C': 12}


def _candidate(profile: str, format_name: str, segments: dict) -> dict:
    return {
        'profile': profile, 'format': format_name, 'segments': segments,
        'year': None, 'week': None, 'manufactured_on': None,
        'manufacture_date_basis': {
            'type': 'unproven', 'reconstructed': False, 'source': '',
            'precision': 'unknown', 'blocked_reason': None,
        },
        'warnings': [],
    }


def _block(candidate: dict, reason: str, source: str) -> dict:
    candidate['manufactured_on'] = None
    candidate['manufacture_date_basis'].update(
        type='unproven', reconstructed=False, source=source,
        precision='unknown', blocked_reason=reason,
    )
    candidate['warnings'].append(reason)
    return candidate


def _year(code: str, profile: str, year_tables: list, *, explicit: dict | None = None) -> tuple[int | None, str | None]:
    """An explicit source mapping is required; aliases never imply a cycle."""
    values = set()
    if explicit is not None and code in explicit:
        values.add(explicit[code])
    for row in year_tables:
        if not isinstance(row, dict):
            continue
        structure = row.get('structure')
        row_code = row.get('code')
        value = row.get('year')
        if not isinstance(structure, str) or not isinstance(row_code, str):
            continue
        if structure.strip().casefold() != profile.casefold() or row_code.strip().upper() != code:
            continue
        if type(value) is int and 1900 <= value <= 2200:
            values.add(value)
    if len(values) == 1:
        return next(iter(values)), None
    if len(values) > 1:
        return None, 'Plusieurs années sont associées à ce code dans ce profil ; validation manuelle nécessaire.'
    return None, 'Code année absent du référentiel de ce profil ; aucune année ni cycle n’est extrapolé.'


def _week_candidate(candidate: dict, year_tables: list, *, proven_iso: bool) -> dict:
    profile = candidate['profile']
    segments = candidate['segments']
    source = (
        'Catalogue importé / Eaton Structure et instruction Eaton, annexe C : semaine ISO, lundi de référence.'
        if proven_iso else
        f'Catalogue importé / {profile} Structure ; convention interne de reconstruction ISO, lundi de référence.'
    )
    candidate['year'], year_error = _year(segments['year_code'], profile, year_tables)
    week_code = segments['week_code']
    if re.fullmatch(r'[0-9]{2}', week_code) and 1 <= int(week_code) <= 53:
        candidate['week'] = int(week_code)
    else:
        reason = 'La semaine ne contient pas une valeur numérique de 01 à 53 ; date à vérifier manuellement.'
        if profile == 'Pulsar' and re.fullmatch(r'[A-F]{2}', week_code):
            candidate['year'] = None
            reason = ('Codage compatible avec une semaine de réparation Pulsar ; la règle est incomplète. '
                      'Aucune date de fabrication ou de garantie n’est déduite.')
        return _block(candidate, reason, source)
    if year_error:
        return _block(candidate, year_error, source)
    if profile == 'Powerware':
        if segments['special_code'] != 'A':
            return _block(candidate, 'Usage spécial Powerware : la règle standard ne permet pas de proposer une date ; validation manuelle nécessaire.', source)
        if not 1 <= int(segments['unit_order_code']) <= 9999:
            return _block(candidate, 'Ordre Powerware hors de la plage 0001 à 9999 ; validation manuelle nécessaire.', source)
        if segments['day_code'] not in '1234567':
            return _block(candidate, 'Jour Powerware hors de la plage 1 à 7 ; validation manuelle nécessaire.', source)
    try:
        monday = date.fromisocalendar(candidate['year'], candidate['week'], 1)
    except ValueError:
        return _block(candidate, 'Le couple année/semaine ne peut pas être calculé selon la convention ISO ; aucune normalisation vers une autre semaine n’est appliquée.', source)
    candidate['manufactured_on'] = monday.isoformat()
    candidate['manufacture_date_basis'].update(
        type='iso_week' if proven_iso else 'reconstructed_iso_week',
        reconstructed=not proven_iso, source=source, precision='week', blocked_reason=None,
    )
    candidate['warnings'].append('Cette date est le lundi de référence de la semaine, pas le jour exact de fabrication ni un début de garantie contractuel établi.')
    if not proven_iso:
        candidate['warnings'].append(f'La convention ISO n’est pas établie pour {profile} par la source : le lundi est une reconstruction interne à valider.')
    if profile == 'Powerware':
        candidate['warnings'].append('Le jour Powerware codé est conservé séparément ; la proposition reste le lundi de référence selon la convention interne.')
    return candidate


def _nv_candidate(serial: str, year_tables: list) -> dict:
    segments = {
        'production_code': serial[:2], 'product_code': serial[0],
        'year_code': serial[2], 'month_code': serial[3],
        'unit_order_code': serial[4:],
        'month_number': _NV_MONTHS.get(serial[3]),
    }
    candidate = _candidate('NV DX', 'nv_9', segments)
    source = 'Document NV DX Structure / NV : précision mensuelle ; codes explicites 2001–2009 et D/E/F pour 2010/2011/2012.'
    candidate['year'], year_error = _year(serial[2], 'NV DX', year_tables, explicit=_NV_YEARS)
    reason = year_error
    if segments['month_number'] is None:
        reason = 'Code mois NV inconnu ; seules les valeurs 1 à 9, A, B et C sont documentées.'
    if not 1 <= int(serial[4:]) <= 99999:
        reason = 'Ordre NV hors de la plage 00001 à 99999 ; validation manuelle nécessaire.'
    candidate['manufacture_date_basis'].update(
        type='month_only', reconstructed=False, source=source, precision='month',
        blocked_reason=reason or 'Le format NV ne fournit aucun jour ; aucune date au premier du mois n’est inventée.',
    )
    candidate['warnings'].append('Le format NV fournit un mois et non un jour. La date de fabrication et le début de garantie restent à renseigner ou valider.')
    if reason:
        candidate['warnings'].append(reason)
    return candidate


def _dx_candidate(match: re.Match) -> dict:
    year_code, month_code, day_code, order = match.groups()
    candidate = _candidate('NV DX', 'dx_15', {
        'year_code': year_code, 'month_code': month_code, 'day_code': day_code,
        'unit_order_code': order,
    })
    reason = 'Le format DX code une année sur deux chiffres sans établir son siècle ; aucune date ni garantie automatique n’est calculée.'
    # A representative 400-year cycle checks whether the month/day is possible
    # without assigning that century to the actual device. YY=00 can be leap.
    try:
        date(2000 + int(year_code), int(month_code), int(day_code))
    except ValueError:
        reason = 'Composantes calendaires DX impossibles ; date à vérifier manuellement. Le siècle reste inconnu.'
    return _block(candidate, reason, 'Document NV DX Structure / DX : YYMMDD et compteur sur huit chiffres ; siècle non défini.')


def decode_profiles(serial_number: str, year_tables: list, profile: str | None = None) -> list[dict]:
    """Return every compatible geometry, preserving uncertainty and raw codes.

    ``year_tables`` contains explicit ``{structure, code, year, ...}`` records.
    An optional profile limits candidates but never changes the numbering rules.
    Non-ASCII serials and internal separators are not silently rewritten.
    """
    if not isinstance(serial_number, str):
        raise TypeError('serial_number doit être une chaîne de caractères.')
    if not isinstance(year_tables, list):
        raise TypeError('year_tables doit être une liste de correspondances explicites.')
    if profile is not None and not isinstance(profile, str):
        raise TypeError('profile doit être une chaîne ou None.')
    selected = next((name for name in PROFILES if profile and profile.strip().casefold() == name.casefold()), None)
    if profile is not None and selected is None:
        return []
    serial = serial_number.strip()
    if not serial.isascii():
        return []
    serial = serial.upper()
    candidates = []
    enabled = lambda name: selected is None or selected == name
    if len(serial) == 10 and _ALPHANUMERIC.fullmatch(serial) and enabled('Eaton'):
        candidates.append(_week_candidate(_candidate('Eaton', 'eaton_10', {
            'manufacturing_location_code': serial[0], 'product_code': serial[1:4],
            'year_code': serial[4], 'week_code': serial[5:7], 'unit_order_code': serial[7:],
        }), year_tables, proven_iso=True))
    if len(serial) in (9, 11) and _ALPHANUMERIC.fullmatch(serial) and enabled('Pulsar'):
        segments = {
            'product_code': serial[:3], 'year_code': serial[3],
            'week_code': serial[4:6], 'unit_order_code': serial[6:9],
        }
        if len(serial) == 11:
            segments['oem_code'] = serial[9:11]
        candidates.append(_week_candidate(_candidate('Pulsar', 'pulsar_oem_11' if len(serial) == 11 else 'pulsar_9', segments), year_tables, proven_iso=False))
    if len(serial) == 10 and re.fullmatch(r'[A-Z0-9]{2}[0-9]{3}[A-Z0-9][0-9]{4}', serial) and enabled('Powerware'):
        candidates.append(_week_candidate(_candidate('Powerware', 'powerware_10', {
            'manufacturing_location_code': serial[0], 'year_code': serial[1],
            'week_code': serial[2:4], 'day_code': serial[4],
            'special_code': serial[5], 'unit_order_code': serial[6:],
        }), year_tables, proven_iso=False))
    if enabled('NV DX'):
        if len(serial) == 9 and re.fullmatch(r'[0-9]{2}[A-Z0-9]{2}[0-9]{5}', serial):
            candidates.append(_nv_candidate(serial, year_tables))
        match = _DX.fullmatch(serial)
        if match:
            candidates.append(_dx_candidate(match))
    return candidates
