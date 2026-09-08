"""The rehearsal harness must drive a real CLI session end to end."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import chess
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from mock_operator import board_from_prompt, parse_history  # noqa: E402

from bzbench.config import Color, Protocol  # noqa: E402
from bzbench.protocol import build_prompt  # noqa: E402


def test_raw_prompt_alone_is_enough_to_reconstruct_the_position():
    """If this fails, the RAW protocol does not carry a playable game state."""
    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O"]:
        board.push_san(san)
    history = [h for h in chess.Board().variation_san(board.move_stack).split()
               if not h.endswith(".")]
    prompt, _ = build_prompt(board, history, Protocol.RAW, Color.BLACK)
    assert parse_history(prompt) == history
    assert board_from_prompt(prompt).board_fen() == board.board_fen()


def test_fen_prompt_is_read_from_the_fen_line():
    board = chess.Board()
    board.push_san("d4")
    prompt, _ = build_prompt(board, ["d4"], Protocol.FEN, Color.BLACK)
    assert board_from_prompt(prompt).fen() == board.fen()


@pytest.mark.slow
def test_mock_operator_plays_a_whole_game(tmp_path, stockfish_path):
    result = subprocess.run(
        [
            sys.executable, "tools/mock_operator.py",
            "--game-id", "mocktest",
            "--out", str(tmp_path),
            "--seed", "11",
            "--elo", "1350",
            "--nodes", "1000",
            "--stockfish", stockfish_path,
            "--max-plies", "60",
        ],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "mocktest" / "game.json").read_text())
    assert data["turns"], "no moves were played"
    assert data["termination"] in {
        "checkmate", "stalemate", "insufficient_material", "max_plies",
        "fivefold_repetition", "seventyfive_moves",
    }
    assert data["illegal_moves"] == []
    assert all(t["prompt"] for t in data["turns"] if t["actor"] == "ai")


@pytest.mark.slow
def test_mock_operator_illegal_move_is_an_immediate_loss(tmp_path, stockfish_path):
    result = subprocess.run(
        [
            sys.executable, "tools/mock_operator.py",
            "--game-id", "mockillegal",
            "--out", str(tmp_path),
            "--illegal-rate", "1.0",
            "--stockfish", stockfish_path,
            "--nodes", "1000",
        ],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "mockillegal" / "game.json").read_text())
    assert data["termination"] == "illegal_move"
    assert data["result"] == "0-1"
    assert len(data["illegal_moves"]) == 1
    assert len([t for t in data["turns"] if t["uci"]]) == 0
