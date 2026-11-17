import sqlite3

from nimbus.evals.checks import check_db, check_turn, detect_language
from nimbus.evals.dataset import DbCheck, TurnExpect


def fake_trace(*calls, stop_reason="final_answer"):
    """Builds a turn trace. Each call is (tool_name, arguments, is_error)"""
    events = [{"type": "turn_start"}]
    for name, arguments, is_error in calls:
        events.append(
            {
                "type": "tool_result",
                "name": name,
                "arguments": arguments,
                "is_error": is_error,
                "content": "",
            }
        )
    events.append({"type": "turn_end", "stop_reason": stop_reason})
    return events


def by_name(results):
    return {result.name: result for result in results}


def run(expect=None, trace=None, answer="ok", known_ids=frozenset()):
    return by_name(
        check_turn(expect or TurnExpect(), trace or fake_trace(), answer, set(known_ids))
    )


def test_tools_called():
    expect = TurnExpect(tools_called=["get_transaction"])
    assert run(expect, fake_trace(("get_transaction", {}, False)))[
        "tools_called:get_transaction"
    ].passed
    assert not run(expect, fake_trace())["tools_called:get_transaction"].passed


def test_tools_not_called():
    expect = TurnExpect(tools_not_called=["request_refund"])
    result = run(expect, fake_trace(("request_refund", {}, False)))
    assert not result["tools_not_called:request_refund"].passed


def test_tool_args_match_subset():
    expect = TurnExpect(tool_args={"request_refund": {"amount_minor": 10000}})
    good = fake_trace(("request_refund", {"transaction_id": "tx_1", "amount_minor": 10000}, False))
    bad = fake_trace(("request_refund", {"transaction_id": "tx_1", "amount_minor": 100}, False))
    assert run(expect, good)["tool_args:request_refund"].passed
    assert not run(expect, bad)["tool_args:request_refund"].passed


def test_answer_matches_any_ignores_case():
    expect = TurnExpect(answer_matches_any=[r"r\$\s?349,00"])
    assert run(expect, answer="You paid R$ 349,00.")["answer_matches_any"].passed
    assert not run(expect, answer="You paid R$ 34.900.")["answer_matches_any"].passed


def test_answer_matches_none():
    expect = TurnExpect(answer_matches_none=["refunded"])
    result = run(expect, answer="The value has been refunded.")
    assert not result["answer_matches_none:refunded"].passed


def test_invented_transaction_id_is_flagged():
    result = run(answer="Opened a disputed for tx_banana.", known_ids={"tx_8c41e2a7"})
    assert not result["auto:grounded_ids"].passed
    assert "tx_banana" in result["auto:grounded_ids"].detail


def test_known_transaction_id_is_fine():
    result = run(answer="The **tx_8c41e2a7** is pending.", known_ids={"tx_8c41e2a7"})
    assert result["auto:grounded_ids"].passed


def test_max_steps_is_flagged():
    assert not run(trace=fake_trace(stop_reason="max_steps"))["auto:finished"].passed


def test_internal_terms_are_flagged():
    result = run(answer="Your refund is pending_approval.")
    assert not result["auto:no_internal_terms"].passed


def test_db_checks():
    conn = sqlite3.connect(":memory:")
    conn.execute("create table disputes (id text)")
    conn.execute("insert into disputes values ('dsp_1')")
    [ok] = check_db(conn, [DbCheck(query="select count(*) from disputes", equals=1)])
    [wrong] = check_db(conn, [DbCheck(query="select count(*) from disputes", equals=2)])
    [broken] = check_db(conn, [DbCheck(query="select count(*) from nope", equals=0)])
    assert ok.passed
    assert not wrong.passed and "got 1" in wrong.detail
    assert not broken.passed and "query failed" in broken.detail


def test_detects_english_and_portuguese():
    assert detect_language("Your withdrawal is confirming, please wait.") == "en"
    assert detect_language("Sua retirada está confirmando, você precisa aguardar.") == "pt"


def test_language_is_unknown_for_short_answers():
    assert detect_language("tx_8c41e2a7") is None


def test_wrong_language_is_flagged():
    result = by_name(
        check_turn(TurnExpect(), fake_trace(), "Olá! Você poderia me informar o ID?", set(), "en")
    )
    assert not result["auto:language"].passed


def test_turn_waiting_confirmation_is_finished():
    assert run(trace=fake_trace(stop_reason="needs_confirmation"))["auto:finished"].passed


def test_expected_portuguese_is_respected():
    result = by_name(
        check_turn(TurnExpect(), fake_trace(), "Olá! Você poderia me informar o ID?", set(), "pt")
    )
    assert result["auto:language"].passed


def test_not_called_flags_a_request_waiting_for_confirmation():
    trace = [
        {"type": "turn_start"},
        {
            "type": "llm_response",
            "tool_calls": [{"id": "c1", "name": "request_refund", "arguments": {}}],
        },
        {"type": "turn_end", "stop_reason": "needs_confirmation"},
    ]
    result = run(TurnExpect(tools_not_called=["request_refund"]), trace)
    assert not result["tools_not_called:request_refund"].passed
