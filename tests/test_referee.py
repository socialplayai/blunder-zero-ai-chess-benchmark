"""Referee rules: strict SAN, no repair, immediate loss on an illegal move."""

from __future__ import annotations

import chess
import pytest

from bzbench.config import Color, MatchConfig, Protocol
from bzbench.record import Termination
from bzbench.referee import IllegalMove, Referee, normalize_response, parse_san_strict
from conftest import FirstLegalOpponent, ScriptedAI, ScriptedOpponent


def make_config(**kwargs) -> MatchConfig:
    base = dict(
        model_name="test-model",
        protocol=Protocol.RAW,
        ai_color=Color.WHITE,
        adapter="scripted",
        stockfish_elo=1400,
    )
    base.update(kwargs)
    return MatchConfig(**base)


def run(responses, opponent=None, **config_kwargs):
    config = make_config(**config_kwargs)
    ai = ScriptedAI(responses)
    record = Referee(config, ai, opponent or FirstLegalOpponent()).run()
    return record, ai


# --------------------------------------------------------------------- parsing


def test_normalize_response_only_trims_whitespace():
    assert normalize_response("  e4 \n") == "e4"
    assert normalize_response("1. e4") == "1. e4"
    assert normalize_response("e4!") == "e4!"


@pytest.mark.parametrize(
    "response",
    [
        "",
        "   ",
        "e5",             # legal for black, not for white at move 1
        "e2e4",           # UCI, not SAN
        "1. e4",          # move number
        "e4 e5",          # two moves
        "My move is e4",  # prose
        "Ke2",            # illegal in the start position
        "Zz9",            # nonsense
        "e4.",            # trailing punctuation
    ],
)
def test_illegal_or_malformed_responses_are_rejected(response):
    with pytest.raises(IllegalMove):
        parse_san_strict(chess.Board(), response)


def test_ambiguous_san_is_rejected_not_guessed():
    board = chess.Board("6k1/8/8/8/8/7K/8/R6R w - - 0 1")
    assert len([m for m in board.legal_moves if m.to_square == chess.D1]) == 2
    with pytest.raises(IllegalMove) as exc:
        parse_san_strict(board, "Rd1")
    assert "ambiguous" in exc.value.reason
    # The disambiguated forms are accepted.
    assert parse_san_strict(board, "Rad1") == chess.Move.from_uci("a1d1")
    assert parse_san_strict(board, "Rhd1") == chess.Move.from_uci("h1d1")


def test_legal_san_variants_are_accepted():
    board = chess.Board()
    assert parse_san_strict(board, "e4") == chess.Move.from_uci("e2e4")
    assert parse_san_strict(board, "Nf3") == chess.Move.from_uci("g1f3")


# ------------------------------------------------------- illegal move handling


def test_illegal_move_ends_the_game_immediately_as_an_ai_loss():
    record, ai = run(["e4", "Qz9", "e5"])
    assert record.termination == Termination.ILLEGAL_MOVE
    assert record.result == "0-1"
    assert record.ai_outcome() == "loss"
    # The third response was never requested: the game stopped at the illegal one.
    assert len(ai.prompts) == 2
    assert len(record.illegal_moves) == 1
    assert record.illegal_moves[0]["raw_response"] == "Qz9"


def test_illegal_move_is_not_repaired_or_retried():
    record, ai = run(["e2e4"])
    assert record.termination == Termination.ILLEGAL_MOVE
    assert len(ai.prompts) == 1                # no retry
    assert [t.uci for t in record.turns if t.uci] == []  # nothing was played
    assert record.turns[-1].legal is False
    assert record.turns[-1].san is None


def test_illegal_move_by_black_gives_white_the_win():
    record, _ = run(["nonsense"], ai_color=Color.BLACK)
    assert record.result == "1-0"
    assert record.ai_outcome() == "loss"


def test_raw_response_is_recorded_verbatim():
    record, _ = run(["  e4\n", "Qz9"])
    assert record.turns[0].raw_response == "  e4\n"
    assert record.turns[0].normalized_response == "e4"


# ------------------------------------------------------------------ game flow


def test_ai_can_win_by_checkmate():
    record, _ = run(["e4", "Bc4", "Qh5", "Qxf7#"])
    assert record.termination == Termination.CHECKMATE
    assert record.result == "1-0"
    assert record.ai_outcome() == "win"


def test_ai_as_black_moves_second_and_can_be_mated():
    # Fool's mate: white (the opponent) mates on move 2.
    opponent = ScriptedOpponent(["f3", "g4"])
    record, _ = run(["e5", "Qh4#"], opponent=opponent, ai_color=Color.BLACK)
    assert record.termination == Termination.CHECKMATE
    assert record.result == "0-1"
    assert record.ai_outcome() == "win"
    assert record.turns[0].actor == "opponent"


def test_resignation_is_a_loss_and_is_recorded():
    record, _ = run(["e4", ":resign"])
    assert record.termination == Termination.RESIGNATION
    assert record.result == "0-1"
    assert record.turns[-1].raw_response == ":resign"


def test_abort_leaves_the_game_unfinished():
    record, _ = run(["e4", ":abort"])
    assert record.termination == Termination.ABORTED
    assert record.result == "*"
    assert record.ai_outcome() == "unfinished"


def test_max_plies_stops_the_game():
    record, _ = run(["e4", "Nf3", "Ng1", "Nf3"], max_plies=4)
    assert record.termination == Termination.MAX_PLIES
    assert record.result == "*"
    assert len([t for t in record.turns if t.uci]) == 4


def test_time_forfeit_when_the_budget_is_exceeded(monkeypatch):
    import bzbench.referee as referee_mod

    ticks = iter([0.0, 99.0, 100.0, 200.0])
    monkeypatch.setattr(referee_mod.time, "monotonic", lambda: next(ticks))
    record, _ = run(["e4"], max_move_seconds=1.0)
    assert record.termination == Termination.TIME_FORFEIT
    assert record.result == "0-1"
    assert record.turns[-1].san is None


def test_every_turn_records_position_and_timestamps():
    record, _ = run(["e4", "Bc4", "Qh5", "Qxf7#"])
    for turn in record.turns:
        assert turn.fen_before
        assert turn.started_at and turn.finished_at
    ai_turns = [t for t in record.turns if t.actor == "ai"]
    assert all(t.prompt for t in ai_turns)
    assert all(t.view is not None for t in ai_turns)


def test_visual_protocol_is_refused_by_the_referee():
    with pytest.raises(NotImplementedError):
        Referee(make_config(protocol=Protocol.VISUAL), ScriptedAI([]),
                FirstLegalOpponent())


def test_draw_by_stalemate_is_recorded():
    # AI (white) stalemates black from a prepared position via scripted play.
    config = make_config()
    ai = ScriptedAI(["Qg6"])
    referee = Referee(config, ai, FirstLegalOpponent())
    referee.board = chess.Board("7k/8/8/8/8/8/6Q1/K7 w - - 0 1")
    record = referee.run()
    assert record.termination == Termination.STALEMATE
    assert record.result == "1/2-1/2"
    assert record.ai_outcome() == "draw"
