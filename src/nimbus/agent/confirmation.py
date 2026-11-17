import json
import re
from decimal import Decimal

from nimbus.agent.tools import Tools
from nimbus.agent.types import ToolCall

SENSITIVE_TOOLS = frozenset({"open_dispute", "request_refund"})

_YES = re.compile(
    r"^\W*(yes|yeah|yep|sure|ok|okay|confirm\w*|go ahead|sim|pode|claro|confirmo)\b",
    re.IGNORECASE,
)

_NO = re.compile(r"\b(no|not|don'?t|cancel\w*|não|nao|cancela\w*)\b", re.IGNORECASE)

_DECIMALS = {"BTC": 8}

_REASONS = {
    "en": {
        "duplicate": "duplicate charge",
        "unauthorized": "unauthorized transaction",
        "not_received": "not received",
        "wrong_amount": "wrong amount",
        "other": "other reason",
    },
    "pt": {
        "duplicate": "cobrança duplicada",
        "unauthorized": "transação não autorizada",
        "not_received": "não recebido",
        "wrong_amount": "valor errado",
        "other": "outro motivo",
    },
}

_TEMPLATES = {
    "en": {
        "refund": "request a refund of {amount} for {tx}",
        "dispute": "open a dispute ({reason}) on {tx}",
        "question": 'Before I go ahead, please confirm: {actions}. Reply "yes" '
        'to confirm or "no" to cancel.',
    },
    "pt": {
        "refund": "solicitar reembolso de {amount} da {tx}",
        "dispute": "abrir uma disputa ({reason}) na {tx}",
        "question": 'Antes de continuar, confirme: {actions}. Responda "sim" '
        'para continuar ou "não" para cancelar.',
    },
}


def is_confirmation(reply: str) -> bool:
    return bool(_YES.search(reply)) and not _NO.search(reply)


def format_amount(amount_minor: int, asset: str, language: str) -> str:
    decimals = _DECIMALS.get(asset, 2)
    value = Decimal(amount_minor).scaleb(-decimals)
    text = f"{value:,.{decimals}f}"
    if decimals > 2:
        text = text.rstrip("0").rstrip(".")
    if language == "pt":
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}" if asset == "BRL" else f"{text} {asset}".strip()


async def _asset_of(tools: Tools, transaction_id: str) -> str | None:
    try:
        text, is_error = await tools.call("get_transaction", {"transaction_id": transaction_id})
    except Exception:
        return None
    if is_error:
        return None
    try:
        return json.loads(text).get("asset")
    except json.JSONDecodeError:
        return None


async def confirmation_question(calls: list[ToolCall], tools: Tools, language: str) -> str:
    lang = language if language in _TEMPLATES else "en"
    templates = _TEMPLATES[lang]
    actions = []
    for call in calls:
        tx = call.arguments.get("transaction_id", "?")
        if call.name == "request_refund":
            amount = call.arguments.get("amount_minor")
            asset = await _asset_of(tools, tx) or ""
            shown = format_amount(amount, asset, lang) if isinstance(amount, int) else "?"
            actions.append(templates["refund"].format(amount=shown, tx=tx))
        else:
            code = call.arguments.get("reason_code", "")
            reason = _REASONS[lang].get(code, code)
            actions.append(templates["dispute"].format(reason=reason, tx=tx))
    return templates["question"].format(actions="; ".join(actions))
