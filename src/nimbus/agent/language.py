import re
from collections.abc import Iterable

_LANGUAGE_MARKERS = {
    "en": re.compile(
        r"\b(the|your|you|is|and|with|please|transaction|withdrawal|hello|want|refund"
        r"|dispute|my|of)\b",
        re.I,
    ),
    "pt": re.compile(
        r"\b(você|voce|sua|seu|minha|meu|não|nao|com|para|uma|está|transação|transacao"
        r"|saque|retirada|olá|ola|obrigad\w*|quero|reembolso|disputa|contestar|cobrança"
        r"|cobranca|de|da|do)\b",
        re.I,
    ),
}


def detect_language(text: str) -> str | None:
    counts = {lang: len(pattern.findall(text)) for lang, pattern in _LANGUAGE_MARKERS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None


def conversation_language(texts: Iterable[str], default: str = "en") -> str:
    for text in reversed(list(texts)):
        if language := detect_language(text):
            return language
    return default
