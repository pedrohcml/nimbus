from nimbus.agent.language import conversation_language, detect_language


def test_common_portuguese_request_detected():
    assert detect_language("Quero reembolso de R$ 100 da tx_51c7e0d4") == "pt"


def test_common_english_request_detected():
    assert detect_language("Refund R$ 100 of tx_51c7e0d4") == "en"


def test_too_short_to_tell():
    assert detect_language("sim") is None
    assert detect_language("tx_51c7e0d4") is None


def test_conversation_keeps_language_when_last_message_unclear():
    assert conversation_language(["Quero o reembolso da tx_1", "sim"]) == "pt"


def test_conversation_defaults_to_english():
    assert conversation_language(["tx_1", "ok"]) == "en"
