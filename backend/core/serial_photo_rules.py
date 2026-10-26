"""Conservative serial suggestions; never fix ambiguous OCR characters."""
import re
import unicodedata


MAX_CANDIDATES = 10
SERIAL_LABEL = re.compile(r'(?<![A-Z0-9])(?:S\s*[/\\.-]\s*N\.?|SN\b|SERIAL(?:\s+(?:NUMBER|NO\.?))?|N[°ºO.]?\s*(?:DE\s*)?S[ÉE]RIE)\s*[:#=.-]?\s*', re.IGNORECASE)
OTHER_LABEL = re.compile(r'\b(?:MODEL|MOD[ÈE]LE|P\s*/\s*N|PN|PART|SKU|INPUT|OUTPUT|POWER|VOLT|T[ÉE]L|PHONE|MATRICULE|FISCAL|M/?F|TAX|VAT)\b', re.IGNORECASE)
SERIAL_TOKEN = re.compile(r'[A-Z0-9][A-Z0-9._/-]{5,39}\Z')
UPS_PATTERNS = (
    re.compile(r'[A-Z]{1,2}[0-9]{2,4}[A-Z][0-9]{4,6}\Z'),
    re.compile(r'[0-9][A-Z][0-9]{3}[A-Z]{2,3}[0-9]{2}\Z'),
    re.compile(r'[0-9]{6}-[0-9]{8}\Z'),
)


def _normalized(value):
    return unicodedata.normalize('NFKC', value).upper().translate(str.maketrans({'–': '-', '—': '-', '−': '-'}))


def serial_candidate(value, *, labeled=False):
    value = _normalized(str(value)).strip(' \t\r\n:;#="\'()[]{}')
    if not SERIAL_TOKEN.fullmatch(value) or sum(character.isdigit() for character in value) < 3:
        return None
    if value.isdigit():
        # A naked phone, EAN or tax number is not evidence of an equipment SN.
        return value if labeled and 6 <= len(value) <= 24 else None
    if not any(character.isalpha() for character in value) and not UPS_PATTERNS[-1].fullmatch(value):
        return None
    # Plain electrical values and common capacity/model tokens are not serials.
    if re.fullmatch(r'[0-9]+(?:[._][0-9]+)?(?:V|VA|KVA|W|KW|HZ|AH|MAH)', value):
        return None
    if re.fullmatch(r'(?:3S|5E|5S|5P(?:X)?|9E|9P(?:X)?|9S(?:X)?|93[EPTMR])[0-9][A-Z0-9._/-]*', value):
        return None
    return value


def labeled_serials(text):
    lines = _normalized(text).splitlines()
    result = []
    for index, line in enumerate(lines):
        for label in SERIAL_LABEL.finditer(line):
            tail = line[label.end():].strip()
            if not tail:
                following = next((entry.strip() for entry in lines[index + 1:index + 3] if entry.strip()), '')
                tail = following if not OTHER_LABEL.search(following) else ''
            tail = OTHER_LABEL.split(tail, maxsplit=1)[0].strip()
            tokens = re.findall(r'[A-Z0-9][A-Z0-9._/-]*', tail)
            if not tokens:
                continue
            candidate = serial_candidate(tokens[0], labeled=True)
            if not candidate and len(tokens) >= 2 and len(tokens[0]) < 6:
                candidate = serial_candidate(''.join(tokens[:2]), labeled=True)
            if candidate and candidate not in result:
                result.append(candidate)
    return result[:MAX_CANDIDATES]


def barcode_serials(text):
    if not isinstance(text, str) or len(text) > 4096:
        return []
    labeled = labeled_serials(text)
    if labeled:
        return labeled
    if OTHER_LABEL.search(text) or re.fullmatch(r'[0-9]{4}-[A-Z][0-9]{3}-[0-9]{2}', _normalized(text).strip()):
        return []
    candidate = serial_candidate(text)
    return [candidate] if candidate else []


def ocr_serials(text):
    if not isinstance(text, str) or len(text) > 65536:
        return []
    labeled = labeled_serials(text)
    if labeled:
        return labeled
    result = []
    for line in _normalized(text).splitlines():
        if OTHER_LABEL.search(line):
            continue
        for token in re.findall(r'[A-Z0-9][A-Z0-9._/-]{4,39}', line):
            if any(pattern.fullmatch(token) for pattern in UPS_PATTERNS):
                candidate = serial_candidate(token)
                if candidate and candidate not in result:
                    result.append(candidate)
    return result[:MAX_CANDIDATES]
