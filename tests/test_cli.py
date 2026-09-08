"""End to end CLI runs, including against the real engine."""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

from bzbench.cli import main
from bzbench.config import Color, MatchConfig, Protocol
from bzbench.referee import Referee
from conftest import FirstLegalOpponent, ScriptedAI


def _saved_game(tmp_path: pathlib.Path) -> pathlib.Path:
    config = MatchConfig(model_name="m", protocol=Protocol.RAW,
                         ai_color=Color.WHITE, adapter="scripted", game_id="cli1")
    record = Referee(config, ScriptedAI(["e4", "Bc4", "Qh5", "Qxf7#"]),
                     FirstLegalOpponent()).run()
    return record.save(tmp_path)["json"]


def test_summarize_prints_a_table(tmp_path, capsys):
    _saved_game(tmp_path)
    assert main(["summarize", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "game_id" in out and "cli1" in out
    assert "wins" in out


def test_summarize_json(tmp_path, capsys):
    _saved_game(tmp_path)
    assert main(["summarize", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["aggregate"]["games"] == 1
    assert data["games"][0]["game_id"] == "cli1"


def test_show_prints_every_prompt_for_audit(tmp_path, capsys):
    _saved_game(tmp_path)
    assert main(["show", str(_saved_game(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "raw response:" in out
    assert "You are playing a game of chess as White" in out


def test_play_refuses_the_visual_protocol(tmp_path, capsys):
    code = main(["play", "--model", "m", "--protocol", "visual", "--out", str(tmp_path)])
    assert code == 2
    assert "reserved" in capsys.readouterr().err


def test_play_reports_a_missing_engine(tmp_path, capsys):
    code = main([
        "play", "--model", "m", "--stockfish", "/nonexistent/stockfish",
        "--out", str(tmp_path),
    ])
    assert code == 3
    assert "could not start Stockfish" in capsys.readouterr().err


@pytest.mark.slow
def test_play_against_real_stockfish_through_the_manual_interface(
    tmp_path, stockfish_path, monkeypatch, capsys
):
    """A short real game: one pasted move, then the operator resigns."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("e4\n:resign\n"))
    code = main([
        "play",
        "--model", "mock-model",
        "--protocol", "raw",
        "--color", "white",
        "--adapter", "manual",
        "--elo", "1350",
        "--nodes", "2000",
        "--stockfish", stockfish_path,
        "--game-id", "clireal",
        "--out", str(tmp_path),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "COPY THE BLOCK BELOW INTO THE MODEL" in out
    data = json.loads((tmp_path / "clireal" / "game.json").read_text())
    assert data["termination"] == "resignation"
    assert data["result"] == "0-1"
    assert data["opponent"]["engine_name"].lower().startswith("stockfish")
    assert data["opponent"]["effective_elo"] >= 1320
    assert data["turns"][0]["raw_response"] == "e4\n"
    # The prompt the operator was shown carries no engine output.
    assert "cp" not in data["turns"][0]["prompt"].split()
    pgn = (tmp_path / "clireal" / "game.pgn").read_text()
    assert "[Protocol \"raw\"]" in pgn
