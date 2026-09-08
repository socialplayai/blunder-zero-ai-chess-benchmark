"""Adversarial tests: try to get forbidden information into the AI's prompt.

These are the integrity tests of the benchmark. Each one attempts a specific
leak and asserts the protocol layer refuses it.
"""

from __future__ import annotations

import ast
import pathlib
import re

import chess
import pytest

from bzbench.config import Color, MatchConfig, Protocol
from bzbench.protocol import TurnView, build_prompt, build_turn_view, render_prompt
from bzbench.referee import Referee
from conftest import FirstLegalOpponent, ScriptedAI

REPO = pathlib.Path(__file__).resolve().parents[1]

SAN_TOKEN = re.compile(
    r"\b(?:O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)\b"
)

# Vocabulary that would indicate engine output reaching the model.
FORBIDDEN_TERMS = [
    "stockfish",
    "centipawn",
    "evaluation",
    "eval:",
    "best move",
    "bestmove",
    "principal variation",
    " pv ",
    "multipv",
    "nodes/s",
    "nps",
    "search depth",
    "depth ",
    "cp ",
    "mate in",
    "opening database",
    "opening theory",
    "book move",
    "advantage",
    "winning",
    "losing",
    "blunder",
    "tablebase",
]

OPENING = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]


def board_after(moves: list[str]) -> tuple[chess.Board, list[str]]:
    board = chess.Board()
    history: list[str] = []
    for san in moves:
        history.append(board.san(board.parse_san(san)))
        board.push_san(san)
    return board, history


def template_tokens() -> set[str]:
    """Move-like tokens that come from the static instruction text alone."""
    view = build_turn_view(chess.Board(), [], Protocol.RAW, Color.WHITE)
    return set(SAN_TOKEN.findall(render_prompt(view)))


def move_tokens(prompt: str) -> set[str]:
    return set(SAN_TOKEN.findall(prompt))


# --------------------------------------------------------------------------
# Structure of the view
# --------------------------------------------------------------------------


def test_raw_view_carries_no_fen_and_no_legal_moves():
    board, history = board_after(OPENING)
    view = build_turn_view(board, history, Protocol.RAW, Color.WHITE)
    assert view.fen is None
    assert view.legal_moves_san is None


def test_fen_view_carries_fen_but_no_legal_moves():
    board, history = board_after(OPENING)
    view = build_turn_view(board, history, Protocol.FEN, Color.WHITE)
    assert view.fen == board.fen()
    assert view.legal_moves_san is None


def test_legal_view_carries_both():
    board, history = board_after(OPENING)
    view = build_turn_view(board, history, Protocol.LEGAL, Color.WHITE)
    assert view.fen == board.fen()
    assert set(view.legal_moves_san) == {board.san(m) for m in board.legal_moves}


def test_visual_protocol_is_reserved_not_silently_downgraded():
    board, history = board_after(OPENING)
    with pytest.raises(NotImplementedError):
        build_turn_view(board, history, Protocol.VISUAL, Color.WHITE)


# --------------------------------------------------------------------------
# RAW mode: nothing but instructions and history
# --------------------------------------------------------------------------


def test_raw_prompt_does_not_contain_the_fen():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    assert board.fen() not in prompt
    assert board.board_fen() not in prompt
    assert board.epd() not in prompt


def test_raw_prompt_contains_no_move_tokens_beyond_history_and_template():
    """The strongest legal-move-list check: no unexpected SAN token appears."""
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    allowed = template_tokens() | set(history)
    assert move_tokens(prompt) <= allowed

    legal = {board.san(m) for m in board.legal_moves}
    leaked = (legal - allowed) & move_tokens(prompt)
    assert leaked == set()


def test_raw_prompt_is_a_pure_function_of_history():
    """A fabricated board with the same history length cannot change the prompt.

    If any board detail (piece placement, castling rights, side to move,
    en passant square) reached the RAW prompt, these two would differ.
    """
    board, history = board_after(OPENING)
    decoy = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4")
    while decoy.ply() < board.ply():
        decoy.push(sorted(decoy.legal_moves, key=lambda m: m.uci())[0])

    real, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    fake, _ = build_prompt(decoy, history, Protocol.RAW, Color.WHITE)
    assert real == fake


def test_raw_prompt_has_no_engine_vocabulary():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    lowered = prompt.lower()
    for term in FORBIDDEN_TERMS:
        assert term not in lowered, f"forbidden term {term!r} in RAW prompt"


def test_raw_prompt_carries_no_numeric_score():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    stripped = prompt.replace("+", "").replace("#", "")
    # No signed decimal like +0.34 / -1.2, and no bare centipawn integer.
    assert re.search(r"[-+]\d+\.\d+", prompt) is None
    assert re.search(r"\b\d{3,}\b", stripped) is None


def test_raw_prompt_history_is_chronological_and_complete():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    assert "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6" in prompt
    assert prompt.index("e4") < prompt.index("Nf3") < prompt.index("Bb5")


def test_raw_prompt_at_move_one_says_no_moves_yet():
    prompt, _ = build_prompt(chess.Board(), [], Protocol.RAW, Color.WHITE)
    assert "no moves yet" in prompt


# --------------------------------------------------------------------------
# FEN mode: FEN, still no legal move list
# --------------------------------------------------------------------------


def test_fen_prompt_adds_only_the_fen():
    board, history = board_after(OPENING)
    raw, _ = build_prompt(board, history, Protocol.RAW, Color.WHITE)
    fen_prompt, _ = build_prompt(board, history, Protocol.FEN, Color.WHITE)
    assert board.fen() in fen_prompt
    added = [line for line in fen_prompt.splitlines() if line not in raw.splitlines()]
    assert added == ["Current position (FEN):", board.fen()]


def test_fen_prompt_does_not_leak_the_legal_move_list():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.FEN, Color.WHITE)
    allowed = template_tokens() | set(history)
    # The FEN itself contains no SAN tokens beyond what SAN_TOKEN may match in
    # the piece placement field, so compare against the FEN-free body.
    body = prompt.replace(board.fen(), "")
    assert move_tokens(body) <= allowed
    assert "Legal moves" not in prompt


def test_fen_prompt_has_no_engine_vocabulary():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.FEN, Color.WHITE)
    lowered = prompt.lower()
    for term in FORBIDDEN_TERMS:
        assert term not in lowered


# --------------------------------------------------------------------------
# LEGAL mode: exactly the legal moves, no ordering signal
# --------------------------------------------------------------------------


def test_legal_prompt_lists_every_legal_move_alphabetically():
    board, history = board_after(OPENING)
    prompt, view = build_prompt(board, history, Protocol.LEGAL, Color.WHITE)
    assert list(view.legal_moves_san) == sorted(view.legal_moves_san)
    for san in {board.san(m) for m in board.legal_moves}:
        assert san in prompt


def test_legal_prompt_ordering_carries_no_engine_ranking():
    """Alphabetical order proves the list is not an engine's move ordering."""
    board, history = board_after(OPENING)
    _, view = build_prompt(board, history, Protocol.LEGAL, Color.WHITE)
    assert tuple(sorted(view.legal_moves_san)) == view.legal_moves_san


def test_legal_prompt_has_no_engine_vocabulary():
    board, history = board_after(OPENING)
    prompt, _ = build_prompt(board, history, Protocol.LEGAL, Color.WHITE)
    lowered = prompt.lower()
    for term in FORBIDDEN_TERMS:
        assert term not in lowered


# --------------------------------------------------------------------------
# Rendering cannot be tricked into showing more than the view holds
# --------------------------------------------------------------------------


def test_render_prompt_shows_only_what_the_view_holds():
    view = TurnView(
        protocol=Protocol.RAW,
        ai_color=Color.WHITE,
        ply=6,
        move_number=4,
        history_san=tuple(OPENING),
        fen=None,
        legal_moves_san=None,
    )
    prompt = render_prompt(view)
    assert "FEN" not in prompt
    assert "Legal moves" not in prompt


def test_turn_view_is_immutable():
    board, history = board_after(OPENING)
    view = build_turn_view(board, history, Protocol.RAW, Color.WHITE)
    with pytest.raises(Exception):
        view.fen = board.fen()  # type: ignore[misc]


# --------------------------------------------------------------------------
# Whole game audit and static separation
# --------------------------------------------------------------------------


def test_every_prompt_of_a_full_raw_game_is_clean():
    config = MatchConfig(model_name="test-model", protocol=Protocol.RAW,
                         ai_color=Color.WHITE, adapter="scripted", stockfish_elo=1400)
    ai = ScriptedAI(["e4", "Bc4", "Qh5", "Qxf7#"])
    record = Referee(config, ai, FirstLegalOpponent()).run()

    replay = chess.Board()
    history: list[str] = []
    prompt_index = 0
    for turn in record.turns:
        if turn.actor == "ai":
            prompt = ai.prompts[prompt_index]
            prompt_index += 1
            lowered = prompt.lower()
            for term in FORBIDDEN_TERMS:
                assert term not in lowered
            assert replay.fen() not in prompt
            assert move_tokens(prompt) <= template_tokens() | set(history)
        history.append(turn.san)
        replay.push(chess.Move.from_uci(turn.uci))
    assert record.termination == "checkmate"
    assert prompt_index == len(ai.prompts)


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(f"{'.' * node.level}{node.module or ''}")
    return names


def test_ai_facing_modules_never_import_the_engine():
    """Structural guarantee: the prompt path cannot reach Stockfish at all."""
    ai_facing = [REPO / "bzbench" / "protocol.py"]
    ai_facing += sorted((REPO / "bzbench" / "adapters").glob("*.py"))
    for path in ai_facing:
        imports = _imported_modules(path)
        assert not any("engine" in name for name in imports), path
        assert not any("analysis" in name for name in imports), path
        assert "chess.engine" not in imports, path


def test_adapters_receive_no_engine_handle():
    """The adapter signature exposes only the prompt and the filtered view."""
    import inspect

    from bzbench.adapters.base import AIPlayer

    params = list(inspect.signature(AIPlayer.propose_move).parameters)
    assert params == ["self", "prompt", "view"]
