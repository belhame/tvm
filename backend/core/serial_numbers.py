"""Lecture consultative du document « eaton structure.xlsx », feuille Table 1.

Ce document décrit une structure de série, pas un catalogue d'appareils. Aucun
accès aux données métier, aucune recherche et aucune écriture ne sont effectués.
Les exemples d'années du document étant incohérents, seuls leurs codes sont lus.
"""

from string import ascii_uppercase, digits


RULE_ID = 'eaton-structure-10-v1'
SOURCE = 'eaton structure.xlsx / Table 1'
ALPHANUMERIC = frozenset(ascii_uppercase + digits)
EXCLUDED_GENERAL = frozenset('IOQSUXZ')
EXCLUDED_LOCATION = frozenset('IOQX')
GENERAL_CODES = ALPHANUMERIC - EXCLUDED_GENERAL
LOCATION_CODES = ALPHANUMERIC - EXCLUDED_LOCATION
YEAR_CODES = GENERAL_CODES

ADVISORY_WARNING = (
    'Cette lecture est indicative : une structure compatible ne certifie ni '
    'le fabricant ni l’authenticité de l’équipement.'
)
YEAR_WARNING = (
    'L’exemple d’année du fichier est incohérent (« A for 201O, B for 1011 »). '
    'Le code année est conservé sans calculer d’année civile.'
)
CODE_WARNING = (
    'Le fichier ne fournit pas les correspondances des codes de site ou de '
    'produit. Aucun nom de site, modèle d’onduleur ou compteur d’unité n’est déduit.'
)


def analyze_serial_number(serial_number: str) -> dict:
    """Analyse 1 + 3 + 1 + 2 + 3 caractères sans modifier la série enregistrée.

    Seuls les espaces aux extrémités et la casse ASCII sont normalisés. Les
    séparateurs internes et caractères Unicode ne sont pas réinterprétés.
    L'API valide séparément le type, la présence et la longueur maximale.
    """
    if not isinstance(serial_number, str):
        raise TypeError('serial_number doit être une chaîne de caractères.')
    stripped = serial_number.strip()
    normalized = stripped.upper() if stripped.isascii() else stripped
    result = {
        'status': 'not_applicable',
        'normalized_serial_number': normalized,
        'rule_id': RULE_ID,
        'source': SOURCE,
        'segments': None,
        'calendar_year': None,
        'warnings': [],
    }
    if len(normalized) != 10 or not stripped.isascii() or any(c not in ALPHANUMERIC for c in normalized):
        result['warnings'] = [
            'Ce document décrit uniquement une structure de 10 caractères ASCII '
            'alphanumériques, sans séparateur : 1 + 3 + 1 + 2 + 3. '
            'Les autres formats de série restent enregistrables dans l’application.',
            ADVISORY_WARNING,
        ]
        return result

    location, product, year, week, order = (
        normalized[0], normalized[1:4], normalized[4], normalized[5:7], normalized[7:10],
    )
    reasons = []
    if location not in LOCATION_CODES:
        reasons.append('Le code de lieu contient un caractère exclu par le document : I, O, Q ou X.')
    if any(c not in GENERAL_CODES for c in product):
        reasons.append('Le code produit contient un caractère exclu : I, O, Q, S, U, X ou Z.')
    if year not in YEAR_CODES:
        reasons.append('Le code année contient un caractère exclu : I, O, Q, S, U, X ou Z ; aucune correspondance civile n’est supposée.')
    if any(c not in digits for c in week) or not 1 <= int(week) <= 53:
        reasons.append('La semaine de fabrication doit contenir deux chiffres, de 01 à 53.')
    if any(c not in GENERAL_CODES for c in order):
        reasons.append('Le code d’ordre d’unité contient un caractère exclu : I, O, Q, S, U, X ou Z.')
    if reasons:
        result['warnings'] = [*reasons, ADVISORY_WARNING]
        return result

    result['status'] = 'matches'
    result['segments'] = {
        'manufacturing_location_code': location,
        'product_identification_code': product,
        'year_code': year,
        'week_code': week,
        'week_number': int(week),
        'unit_order_code': order,
    }
    result['warnings'] = [ADVISORY_WARNING, YEAR_WARNING, CODE_WARNING]
    return result
