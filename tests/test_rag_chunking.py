from datetime import date

import pytest

from nimbus.rag.chunking import chunk_all, chunk_by_section, chunk_by_window
from nimbus.rag.corpus import PolicyDoc, load_policies

DOC = PolicyDoc(
    id="refunds",
    title="Refund policy",
    version=2,
    effective_from=date(2025, 11, 1),
    source="refunds_v2.md",
    text=(
        "# Refund policy\n\n"
        "## What can be refunded\nCard charges and fees.\n\n"
        "## Approval\nUp to R$ 500.00 is automatic. \nAbove that, the team reviews it. \n"
    ),
)


def body(chunk):
    return chunk.text.split("\n\n", 1)[1].split()


def test_section_chunks_follow_headings():
    chunks = chunk_by_section(DOC)
    assert [c.id for c in chunks] == ["refunds@v2#what-can-be-refunded", "refunds@v2#approval"]
    assert chunks[1].sections == ("approval",)
    assert chunks[1].text.startswith("Refund policy - Approval")
    assert "the team reviews it." in chunks[1].text


def test_text_before_first_section_is_error():
    doc = DOC.model_copy(update={"text": "# Title\nloose text\n## A\nbody"})
    with pytest.raises(ValueError):
        chunk_by_section(doc)


def test_windows_overlap():
    first, second = chunk_by_window(DOC, size=6, overlap=2)[:2]
    assert body(first)[-2:] == body(second)[:2]


def test_windows_reach_end():
    last = chunk_by_window(DOC, size=6, overlap=2)[-1]
    assert body(last)[-1] == "it."


def test_window_crossing_heading_lists_both_sections():
    chunks = chunk_by_window(DOC, size=6, overlap=2)
    assert any(c.sections == ("what-can-be-refunded", "approval") for c in chunks)


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_by_window(DOC, size=5, overlap=5)


@pytest.mark.parametrize("chunker", [chunk_by_section, chunk_by_window])
def test_shipped_corpus_has_unique_chunk_ids(chunker):
    chunks = chunk_all(load_policies(), chunker)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert {c.policy_id for c in chunks} == {
        "refunds",
        "disputes",
        "fees",
        "withdrawals",
        "account_security",
    }
