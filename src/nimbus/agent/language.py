import re

_LANGUAGE_MARKERS = {
    "en": re.compile(r"\b(the|your|you|is|and|with|please|transaction|withdrawal|hello)\b", re.I),
    "pt": re.compile(
        r"\b(você|sua|seu|não|com|para|uma|está|transação|saque|retirada|olá|obrigad\w*)\b", re.I
    ),
}


def detect_language(text: str) -> str | None:
    counts = {lang: len(pattern.findall(text)) for lang, pattern in _LANGUAGE_MARKERS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None
