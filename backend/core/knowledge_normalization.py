import unicodedata


def normalized_key(value):
    decomposed = unicodedata.normalize('NFKD', str(value or ''))
    return ' '.join(''.join(char for char in decomposed if not unicodedata.combining(char)).casefold().split())
