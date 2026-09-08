"""Shared fixtures: fake opponents and scripted AI players.

Unit tests never start Stockfish. The integration tests that do are marked
`slow` and skip when no engine binary is present.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
from typing import Any, Iterable

import chess
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from bzbench.adapters.base import AbortGame, AIPlayer, ResignGame  # noqa: E402
from bzbench.protocol import TurnView  # noqa: E402


class ScriptedAI(AIPlayer):
    """Replays a fixed list of raw responses and records every prompt it saw."""

    name = "scripted"

    def __init__(self, responses: Iterable[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.views: list[TurnView] = []

    def propose_move(self, prompt: str, view: TurnView) -> str:
        self.prompts.append(prompt)
        self.views.append(view)
        if not self._responses:
            raise AbortGame("scripted responses exhausted")
        response = self._responses.pop(0)
        if response == ":resign":
            raise ResignGame("scripted resignation")
        if response == ":abort":
            raise AbortGame("scripted abort")
        return response

    def describe(self) -> dict[str, Any]:
        return {"adapter": self.name}


class SlowAI(ScriptedAI):
    """Scripted player that reports a long response time via a fake clock."""

    name = "slow"


class FirstLegalOpponent:
    """Deterministic stand-in for Stockfish: plays the first move in UCI order."""

    def play(self, board: chess.Board) -> chess.Move:
        return sorted(board.legal_moves, key=lambda m: m.uci())[0]

    def describe(self) -> dict[str, Any]:
        return {
            "engine_name": "FirstLegalOpponent",
            "engine_author": "tests",
            "requested_elo": 0,
            "effective_elo": 0,
            "limit": {},
            "options": {},
        }


class ScriptedOpponent(FirstLegalOpponent):
    """Plays a fixed SAN script, then falls back to the first legal move."""

    def __init__(self, moves: Iterable[str]) -> None:
        self._moves = list(moves)

    def play(self, board: chess.Board) -> chess.Move:
        if self._moves:
            return board.parse_san(self._moves.pop(0))
        return super().play(board)


@pytest.fixture
def first_legal_opponent() -> FirstLegalOpponent:
    return FirstLegalOpponent()


@pytest.fixture
def stockfish_path() -> str:
    path = shutil.which("stockfish")
    if path is None:
        pytest.skip("stockfish binary not available")
    return path
