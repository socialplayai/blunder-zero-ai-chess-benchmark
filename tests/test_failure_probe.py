"""The diagnostic probe must reproduce the position, judge like the referee,
and never touch a game."""

from __future__ import annotations

import json
import pathlib
import sys

import chess
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import failure_probe  # noqa: E402

from bzbench.config import Color, MatchConfig, Protocol  # noqa: E402
from bzbench.protocol import build_prompt  # noqa: E402
from bzbench.record import GameRecord  # noqa: E402
from bzbench.referee import Referee  # noqa: E402
from conftest import FirstLegalOpponent, ScriptedAI  # noqa: E402
from fake_openai import FakeClient, FakeResponse  # noqa: E402

FAILURE_FEN = "r3r1k1/pp3ppp/8/5N2/Pn6/1N2P3/4KP1P/R1B4q b - - 1 23"


def a_record(tmp_path) -> pathlib.Path:
    config = MatchConfig(model_name="m", protocol=Protocol.RAW,
                         ai_color=Color.WHITE, adapter="scripted", game_id="probesrc")
    record = Referee(config, ScriptedAI(["e4", "Bc4", "Qh5", "Qxf7#"]),
                     FirstLegalOpponent()).run()
    return record.save(tmp_path)["json"]


def test_state_at_ply_rebuilds_the_exact_position(tmp_path):
    source = a_record(tmp_path)
    record = GameRecord.load(source)
    board, history, colour = failure_probe.state_at_ply(record, 4)
    assert board.fen() == record.turns[4].fen_before
    assert history == [t.san for t in record.turns[:4]]
    assert colour is Color.WHITE


def test_the_probe_prompt_is_the_frozen_prompt(tmp_path):
    source = a_record(tmp_path)
    record = GameRecord.load(source)
    board, history, colour = failure_probe.state_at_ply(record, 4)
    prompt, _ = build_prompt(board, history, Protocol.RAW, colour)
    assert prompt == record.turns[4].prompt


def test_the_judge_matches_the_referee_and_splits_the_failure_kinds():
    board = chess.Board(FAILURE_FEN)
    assert failure_probe.judge(board, "Qh5+")["category"] == "state_tracking_failure"
    assert failure_probe.judge(board, "Qxh2")["legal"] is True
    assert failure_probe.judge(board, "Qxh2")["uci"] == "h1h2"
    assert failure_probe.judge(board, "I would play Qxh2")["category"] == (
        "malformed_response"
    )
    assert failure_probe.judge(board, "")["category"] == "malformed_response"
    # Whitespace only, exactly as the referee treats it.
    assert failure_probe.judge(board, "  Qxh2\n")["legal"] is True


def test_the_recorded_failure_position_is_reproduced_from_the_published_record():
    """Guards the published evidence: game 2's ply 45 really is that position."""
    published = REPO / "results/api-pilot-v0.1/game-002/game.json"
    if not published.exists():
        pytest.skip("game 2 has not been published in this checkout")
    record = GameRecord.load(published)
    board, _, colour = failure_probe.state_at_ply(record, 45)
    assert board.fen() == FAILURE_FEN
    assert colour is Color.BLACK
    assert failure_probe.judge(board, "Qh5+")["legal"] is False
    assert len(list(board.legal_moves)) == 40


def test_probe_trials_are_independent_and_cannot_seed_a_game(tmp_path, monkeypatch):
    source = a_record(tmp_path)
    created: list[FakeClient] = []

    class Recorder(failure_probe.OpenAIResponsesAdapter):
        def __init__(self, **kwargs):
            client = FakeClient([FakeResponse("Qxh2")])
            created.append(client)
            super().__init__(client=client, **kwargs)

    monkeypatch.setattr(failure_probe, "OpenAIResponsesAdapter", Recorder)
    out = tmp_path / "probe.json"
    args = failure_probe.build_parser().parse_args(
        [str(source), "--ply", "4", "--trials", "3", "--protocols", "raw", "fen",
         "--out", str(out)]
    )
    assert failure_probe.run(args) == 0

    assert len(created) == 6  # one fresh client per trial
    for client in created:
        request = client.requests[0]
        assert request["store"] is False
        assert "previous_response_id" not in request
        assert request["tools"] == []
        assert request["max_output_tokens"] == 12000
        assert request["reasoning"] == {"effort": "high"}

    payload = json.loads(out.read_text())
    assert payload["scored"] is False
    assert payload["kind"] == "diagnostic_probe"
    assert payload["summary"]["raw"]["trials"] == 3
    assert payload["prompts"]["fen"] != payload["prompts"]["raw"]
    assert payload["fen"] in payload["prompts"]["fen"]
    assert payload["fen"] not in payload["prompts"]["raw"]
    assert not list(pathlib.Path(tmp_path).glob("**/games/**/game.pgn"))


def test_probe_output_is_not_a_scored_path():
    rules = [
        line.strip()
        for line in (REPO / ".gitignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "diagnostics/" in rules
