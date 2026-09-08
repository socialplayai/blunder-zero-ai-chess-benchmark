"""OpenAI Responses adapter: no tools, no repair, no leakage, no fake losses."""

from __future__ import annotations

import json
import re

import pytest

from bzbench import adapters
from bzbench.adapters.base import (
    AuthenticationFailure,
    BudgetStop,
    PlayerInfrastructureError,
    RateLimited,
)
from bzbench.adapters.openai_api import (
    OpenAIResponsesAdapter,
    ReasoningEffortNotSupported,
    classify_exception,
    scrub_secrets,
    validate_reasoning_effort,
)
from bzbench.config import Color, MatchConfig, Protocol
from bzbench.pricing import Pricing
from bzbench.record import NON_CHESS_TERMINATIONS, Termination
from bzbench.referee import Referee
from conftest import FirstLegalOpponent
from fake_openai import FakeClient, FakeResponse, FakeUsage, moves

PRICING = Pricing.for_model("gpt-6-astra")


def make_adapter(script, **kwargs) -> tuple[OpenAIResponsesAdapter, FakeClient]:
    client = FakeClient(script)
    adapter = OpenAIResponsesAdapter(
        pricing=PRICING, client=client, game_id="t1", sleep=lambda _s: None, **kwargs
    )
    return adapter, client


def play(script, *, responses_config=None, **adapter_kwargs):
    config = responses_config or MatchConfig(
        model_name="gpt-6-astra", protocol=Protocol.RAW, ai_color=Color.WHITE,
        adapter="openai", game_id="apitest",
    )
    adapter, client = make_adapter(script, **adapter_kwargs)
    record = Referee(config, adapter, FirstLegalOpponent()).run()
    return record, client, adapter


# --------------------------------------------------------------- no tools


def test_request_exposes_no_tools_and_no_structured_output():
    record, client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    assert record.termination == Termination.CHECKMATE
    assert client.calls == 4
    for request in client.requests:
        assert request["tools"] == []
        for forbidden in (
            "tool_choice", "parallel_tool_calls", "response_format",
            "functions", "function_call", "max_tool_calls", "include",
        ):
            assert forbidden not in request
        assert "format" not in json.dumps(request.get("text", {}))


def test_request_input_is_exactly_the_benchmark_prompt():
    record, client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    prompts = [t.prompt for t in record.turns if t.actor == "ai"]
    assert [r["input"] for r in client.requests] == prompts


def test_raw_mode_request_carries_no_fen_and_no_legal_moves():
    record, client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    import chess

    board = chess.Board()
    for request, turn in zip(client.requests, [t for t in record.turns if t.uci]):
        assert board.fen() not in request["input"]
        assert "Legal moves" not in request["input"]
        board.push(chess.Move.from_uci(turn.uci))


def test_adapter_never_receives_an_engine_or_engine_information():
    import inspect

    signature = inspect.signature(OpenAIResponsesAdapter.__init__)
    for name in signature.parameters:
        assert "engine" not in name and "stockfish" not in name
    record, client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    blob = json.dumps(client.requests).lower()
    for term in ("stockfish", "centipawn", "evaluation", "best move", "depth "):
        assert term not in blob


# ------------------------------------------------------- reasoning effort


def test_unsupported_reasoning_effort_fails_loudly_with_no_fallback():
    with pytest.raises(ReasoningEffortNotSupported):
        validate_reasoning_effort("gpt-6-astra", "none")
    with pytest.raises(ReasoningEffortNotSupported):
        validate_reasoning_effort("gpt-6-astra", "extreme")
    with pytest.raises(ReasoningEffortNotSupported):
        make_adapter([], reasoning_effort="none")


def test_reasoning_effort_is_sent_and_recorded():
    record, client, adapter = play(moves("e4", "Bc4", "Qh5", "Qxf7#"),
                                   reasoning_effort="high")
    assert all(r["reasoning"] == {"effort": "high"} for r in client.requests)
    assert adapter.describe()["reasoning_effort_requested"] == "high"
    assert adapter.describe()["reasoning_effort_effective"] == "high"
    first = [t for t in record.turns if t.actor == "ai"][0]
    assert first.api["reasoning_requested"] == "high"
    assert first.api["reasoning_effective"] == "high"


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high", "xhigh", "max"])
def test_every_documented_effort_level_is_accepted_for_astra(effort):
    adapter, _ = make_adapter([], reasoning_effort=effort)
    assert adapter.reasoning_effort == effort


# ----------------------------------------------------- conversation state


def test_one_game_is_one_response_chain():
    record, client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    assert "previous_response_id" not in client.requests[0]
    ids = [t.api["response_id"] for t in record.turns if t.actor == "ai"]
    for request, previous in zip(client.requests[1:], ids[:-1]):
        assert request["previous_response_id"] == previous
    assert record.api["response_ids"] == ids


def test_a_new_game_starts_a_fresh_conversation():
    _, first_client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    _, second_client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    assert "previous_response_id" not in second_client.requests[0]
    first_ids = {r.get("previous_response_id") for r in first_client.requests}
    second_ids = {r.get("previous_response_id") for r in second_client.requests}
    assert first_ids & second_ids == {None}


def test_store_is_enabled_so_the_model_keeps_its_own_reasoning():
    _, client, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    assert all(request["store"] is True for request in client.requests)


# ------------------------------------------------------- output discipline


def test_malformed_output_is_not_repaired_and_loses_immediately():
    record, client, _ = play([FakeResponse("I will play **e4**, a strong move.")])
    assert record.termination == Termination.ILLEGAL_MOVE
    assert record.result == "0-1"
    assert record.turns[-1].raw_response == "I will play **e4**, a strong move."
    assert record.turns[-1].san is None
    assert client.calls == 1  # no retry of a completed response


def test_illegal_move_still_loses_immediately():
    record, client, _ = play([FakeResponse("Ke2")])
    assert record.termination == Termination.ILLEGAL_MOVE
    assert record.result == "0-1"
    assert record.illegal_moves[0]["normalized_response"] == "Ke2"
    assert client.calls == 1


def test_empty_response_is_a_loss_not_an_error():
    record, _, _ = play([FakeResponse("")])
    assert record.termination == Termination.ILLEGAL_MOVE
    assert record.illegal_moves[0]["reason"] == "empty response"


# ------------------------------------------------------- failure taxonomy


def _openai_error(kind: str) -> Exception:
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    if kind == "rate_limit":
        return openai.RateLimitError(
            "rate limited", response=httpx.Response(429, request=request), body=None
        )
    if kind == "auth":
        return openai.AuthenticationError(
            "bad key", response=httpx.Response(401, request=request), body=None
        )
    if kind == "server":
        return openai.InternalServerError(
            "boom", response=httpx.Response(500, request=request), body=None
        )
    if kind == "timeout":
        return openai.APITimeoutError(request=request)
    if kind == "connection":
        return openai.APIConnectionError(request=request)
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind,termination",
    [
        ("rate_limit", Termination.API_RATE_LIMIT),
        ("auth", Termination.API_AUTHENTICATION),
        ("server", Termination.API_SERVER_ERROR),
        ("timeout", Termination.API_TIMEOUT),
        ("connection", Termination.API_NETWORK),
    ],
)
def test_api_failures_never_become_chess_losses(kind, termination):
    error = _openai_error(kind)
    record, _, _ = play([error, error, error], max_attempts=3)
    assert record.termination == termination
    assert record.result == "*"
    assert record.ai_outcome() == "unfinished"
    assert record.termination in NON_CHESS_TERMINATIONS
    assert record.infrastructure_failure["kind"] == termination


def test_transient_failure_is_retried_then_the_game_continues():
    script = [_openai_error("rate_limit")] + moves("e4", "Bc4", "Qh5", "Qxf7#")
    record, client, _ = play(script, max_attempts=3)
    assert record.termination == Termination.CHECKMATE
    assert client.calls == 5  # one failed attempt plus four moves
    first = [t for t in record.turns if t.actor == "ai"][0]
    assert [a["outcome"] for a in first.api["attempts"]] == ["error", "response"]
    assert first.api["attempts"][0]["error_kind"] == "api_rate_limit"


def test_authentication_failure_is_never_retried():
    record, client, _ = play([_openai_error("auth")], max_attempts=5)
    assert client.calls == 1
    assert record.termination == Termination.API_AUTHENTICATION


def test_retries_resend_an_identical_request():
    script = [_openai_error("server"), _openai_error("server")] + moves("e4")
    _, client, _ = play(script, max_attempts=3)
    assert client.requests[0] == client.requests[1] == client.requests[2]


def test_incomplete_response_is_infrastructure_not_a_loss():
    response = FakeResponse("", status="incomplete",
                            incomplete_details={"reason": "max_output_tokens"})
    record, _, _ = play([response])
    assert record.result == "*"
    assert record.termination == "infrastructure_error"
    assert record.ai_outcome() == "unfinished"


def test_classify_exception_maps_every_documented_class():
    assert isinstance(classify_exception(_openai_error("rate_limit")), RateLimited)
    assert isinstance(classify_exception(_openai_error("auth")), AuthenticationFailure)
    assert isinstance(
        classify_exception(RuntimeError("odd")), PlayerInfrastructureError
    )


# ------------------------------------------------------------ spend guards


def test_cost_guard_aborts_before_the_next_request_without_a_chess_result():
    usage = dict(input_tokens=100_000, output_tokens=100_000, reasoning_tokens=90_000)
    record, client, adapter = play(moves("e4", "Bc4", **usage), max_cost_usd=6.0)
    # $1 + $5 = $6.00 after the first move, so the second request never happens.
    assert client.calls == 1
    assert record.termination == Termination.COST_LIMIT_ABORT
    assert record.result == "*"
    assert record.ai_outcome() == "unfinished"
    assert record.api["total_cost_usd"] == pytest.approx(6.0)


def test_token_guard_aborts_the_game():
    usage = dict(input_tokens=1000, output_tokens=1000, reasoning_tokens=500)
    record, client, _ = play(moves("e4", "Bc4", **usage), max_total_tokens=1500)
    assert client.calls == 1
    assert record.termination == Termination.TOKEN_LIMIT_ABORT
    assert record.result == "*"


def test_budget_stop_is_raised_before_any_request_is_built():
    adapter, client = make_adapter(moves("e4"), max_cost_usd=0.0001)
    adapter.ledger.total_cost_usd = 1.0
    from bzbench.protocol import build_prompt
    import chess

    prompt, view = build_prompt(chess.Board(), [], Protocol.RAW, Color.WHITE)
    with pytest.raises(BudgetStop):
        adapter.propose_move(prompt, view)
    assert client.calls == 0


# --------------------------------------------------------------- recording


def test_every_move_records_usage_cost_and_identifiers():
    record, _, _ = play(moves("e4", "Bc4", "Qh5", "Qxf7#"))
    for turn in [t for t in record.turns if t.actor == "ai"]:
        api = turn.api
        assert api["response_id"].startswith("resp_fake_")
        assert api["usage"]["input_tokens"] == 1000
        assert api["usage"]["reasoning_tokens"] == 400
        assert api["raw_usage"]["output_tokens_details"]["reasoning_tokens"] == 400
        assert api["cost"]["total_cost_usd"] > 0
        assert api["status"] == "completed"
        assert api["request"]["tools"] == []
        assert "input" not in api["request"]
    assert record.api["calls"] == 4
    assert record.api["total_tokens"] == 4 * 1500
    assert record.api["pricing"]["source"].startswith("https://")


def test_usage_fields_are_never_invented():
    response = FakeResponse("e4", usage=FakeUsage(reasoning_tokens=None))
    record, _, _ = play([response] + moves("Bc4", "Qh5", "Qxf7#"))
    first = [t for t in record.turns if t.actor == "ai"][0]
    assert first.api["usage"]["reasoning_tokens"] is None
    assert first.api["cost"]["reasoning_tokens"] is None
    assert first.api["cost"]["reasoning_cost_share_usd"] is None


# ----------------------------------------------------------------- secrets


def test_the_api_key_never_reaches_any_artifact(tmp_path, monkeypatch, capsys):
    secret = "sk-test-DEADBEEF-must-never-appear-0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    error = RuntimeError(f"boom with Authorization: Bearer {secret}")
    record, _, adapter = play([error], max_attempts=1)
    paths = record.save(tmp_path)
    printed = capsys.readouterr()

    for blob in (
        paths["json"].read_text(),
        paths["pgn"].read_text(),
        json.dumps(adapter.describe()),
        json.dumps(record.api),
        printed.out,
        printed.err,
    ):
        assert secret not in blob
        assert not re.search(r"sk-test-DEADBEEF", blob)
    assert "***REDACTED***" in json.dumps(record.infrastructure_failure)


def test_scrub_secrets_removes_key_shaped_strings():
    assert "sk-" not in scrub_secrets("token sk-abcdefghijklmnop is leaking").replace(
        "sk-***REDACTED***", ""
    )


def test_describe_contains_configuration_but_no_credentials():
    adapter, _ = make_adapter([])
    described = json.dumps(adapter.describe())
    assert "api_key" not in described.replace("api_key_env", "")
    assert "OPENAI_API_KEY" in described  # the variable name, never the value


# ------------------------------------------------- the manual path is intact


def test_manual_adapter_behaviour_is_unchanged():
    import io

    from bzbench.adapters.manual import ManualAdapter
    from bzbench.protocol import build_prompt
    import chess

    prompt, view = build_prompt(chess.Board(), [], Protocol.RAW, Color.WHITE)
    out = io.StringIO()
    adapter = ManualAdapter(input_fn=lambda: "  e4 \n", out=out)
    assert adapter.propose_move(prompt, view) == "  e4 \n"
    assert adapter.pop_turn_metadata() is None
    assert adapter.session_summary() is None
    assert prompt in out.getvalue()


def test_manual_games_record_no_api_section():
    from conftest import ScriptedAI

    config = MatchConfig(model_name="m", adapter="scripted", game_id="manualish")
    record = Referee(config, ScriptedAI(["e4", "Bc4", "Qh5", "Qxf7#"]),
                     FirstLegalOpponent()).run()
    assert record.api is None
    assert all(t.api is None for t in record.turns)
    assert record.to_dict()["api"] is None
