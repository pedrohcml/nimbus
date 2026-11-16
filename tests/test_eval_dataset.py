import pydantic
import pytest

from nimbus.backend.seed import CUSTOMER_MAIN, TX_DUPLICATE_B
from nimbus.evals.dataset import load_dataset


def write(tmp_path, text):
    path = tmp_path / "cases.yaml"
    path.write_text(text, encoding="utf-8")
    return path


VALID = """
cases:
  - id: partial_refund
    category: actions
    turns:
      - user: "I want a R$ 100 refund from {TX_DUPLICATE_B}"
        expect:
          tools_called: [request_refund]
          answer_matches_any: ['\\d{2}']
    db:
      - query: "select count(*) from refund_requests"
        equals: 1
"""


def test_loads_case_and_resolves_placeholders(tmp_path):
    [case] = load_dataset(write(tmp_path, VALID))
    assert case.id == "partial_refund"
    assert TX_DUPLICATE_B in case.turns[0].user
    assert case.customer == CUSTOMER_MAIN


def test_regex_braces_not_treated_as_placeholders(tmp_path):
    [case] = load_dataset(write(tmp_path, VALID))
    assert case.turns[0].expect.answer_matches_any == [r"\d{2}"]


def test_unknown_placeholder_is_error(tmp_path):
    with pytest.raises(ValueError, match="TX_TYPO"):
        load_dataset(write(tmp_path, VALID.replace("{TX_DUPLICATE_B}", "{TX_TYPO}")))


def test_misspelled_key_is_error(tmp_path):
    with pytest.raises(pydantic.ValidationError):
        load_dataset(write(tmp_path, VALID.replace("tools_called", "tool__called")))


def test_duplicate_case_ids_are_error(tmp_path):
    doubled = VALID + VALID.replace("cases:", "")
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(write(tmp_path, doubled))


def test_db_checks_must_be_read_only(tmp_path):
    with pytest.raises(pydantic.ValidationError):
        load_dataset(write(tmp_path, VALID.replace("select count(*)", "delete")))
