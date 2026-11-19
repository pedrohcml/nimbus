from datetime import date
from pathlib import Path

import pytest

from nimbus.agent.confirmation import format_amount
from nimbus.backend import services
from nimbus.backend.seed import BASE_TIME
from nimbus.rag.corpus import in_effect, load_policies, parse_policy

SHIPPED = Path("policies")

DOC = """---
id: refunds
title: Refund policy
version: 2
effective_from: 2025-11-01
---
# Refund policy

Body.
"""


def write(folder, name, version, effective_from):
    text = DOC.replace("version: 2", f"version: {version}").replace("2025-11-01", effective_from)
    (folder / name).write_text(text, encoding="utf-8")


def test_parses_header_and_body():
    doc = parse_policy(DOC, "refunds_v2.md")
    assert doc.id == "refunds"
    assert doc.version == 2
    assert doc.effective_from == date(2025, 11, 1)
    assert doc.text.startswith("# Refund policy")


def test_missing_header_is_error():
    with pytest.raises(ValueError):
        parse_policy(DOC.replace("version: 2", "version: 2\nowner: me"), "x.md")


def test_in_effect_picks_latest_started_version(tmp_path):
    write(tmp_path, "refunds_v1.md", 1, "2025-03-01")
    write(tmp_path, "refunds_v2.md", 2, "2025-11-01")
    docs = load_policies(tmp_path)
    assert [d.version for d in in_effect(docs, date(2025, 6, 1))] == [1]
    assert [d.version for d in in_effect(docs, date(2026, 1, 15))] == [2]
    assert in_effect(docs, date(2025, 1, 1)) == []


def test_duplicate_version_is_error(tmp_path):
    write(tmp_path, "a.md", 2, "2025-11-01")
    write(tmp_path, "b.md", 2, "2025-11-01")
    with pytest.raises(ValueError):
        load_policies(tmp_path)


def test_shipped_policies_are_valid():
    docs = load_policies(SHIPPED)
    assert {d.id for d in docs} == {
        "refunds",
        "disputes",
        "fees",
        "withdrawals",
        "account_security",
        "faq",
        "identity_verification",
        "limits",
        "card",
        "trading",
        "deposits",
        "account_closure",
    }


def current(policy_id):
    docs = in_effect(load_policies(SHIPPED), BASE_TIME.date())
    return next(d for d in docs if d.id == policy_id)


def test_refund_policy_matches_backedn_threshold():
    threshold = format_amount(services.REFUND_APPROVAL_THRESHOLD_MINOR, "BRL", "en")
    assert threshold in current("refunds").text


def test_dispute_policy_matches_backend_window():
    assert f"{services.DISPUTE_WINDOW.days} days" in current("disputes").text


def test_faq_matches_backend_rules():
    faq = current("faq").text
    assert format_amount(services.REFUND_APPROVAL_THRESHOLD_MINOR, "BRL", "en") in faq
    assert f"{services.DISPUTE_WINDOW.days} days" in faq
    for limit in services.DELAY_LIMITS.values():
        assert f"{int(limit.total_seconds() // 3600)} hours" in faq
