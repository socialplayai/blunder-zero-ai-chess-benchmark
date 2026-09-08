"""Post-game analysis: correct arithmetic, and invisible to the player."""

from __future__ import annotations

import chess
import chess.engine
import pytest

from bzbench.analysis import (
    BLUNDER_CP,
    INACCURACY_CP,
    MISTAKE_CP,
    analyse_record,
    classify,
    move_accuracy,
    win_percent,
)
from bzbench.config import Color, MatchConfig, Protocol
from bzbench.referee import Referee
from conftest import FirstLegalOpponent, ScriptedAI


class FakeEvaluator:
    """Returns a scripted centipawn score per position, side-to-move relative."""

    def __init__(self, scores: list[int]) -> None:
        self._scores = list(scores)
        self.calls = 0

    def evaluate(self, board: chess.Board) -> chess.engine.PovScore:
        cp = self._scores[self.calls]
        self.calls += 1
        return chess.engine.PovScore(chess.engine.Cp(cp), board.turn)

    def describe(self) -> dict:
        return {"engine_name": "FakeEvaluator", "depth": 0}


def make_record(responses: list[str]):
    config = MatchConfig(model_name="m", protocol=Protocol.RAW,
                         ai_color=Color.WHITE, adapter="scripted")
    return Referee(config, ScriptedAI(responses), FirstLegalOpponent()).run()


# ------------------------------------------------------------------- formulas


def test_win_percent_is_centred_and_monotonic():
    assert win_percent(0) == pytest.approx(50.0)
    assert win_percent(300) > win_percent(100) > win_percent(0)
    assert win_percent(-300) == pytest.approx(100 - win_percent(300))


def test_move_accuracy_is_full_for_a_move_that_keeps_the_evaluation():
    assert move_accuracy(50.0, 50.0) == pytest.approx(100.0, abs=0.01)
    assert move_accuracy(80.0, 20.0) < 30.0
    assert 0.0 <= move_accuracy(99.0, 1.0) <= 100.0


@pytest.mark.parametrize(
    "cpl,expected",
    [
        (0, None),
        (INACCURACY_CP - 1, None),
        (INACCURACY_CP, "inaccuracy"),
        (MISTAKE_CP - 1, "inaccuracy"),
        (MISTAKE_CP, "mistake"),
        (BLUNDER_CP - 1, "mistake"),
        (BLUNDER_CP, "blunder"),
        (5000, "blunder"),
    ],
)
def test_classification_thresholds(cpl, expected):
    assert classify(cpl) == expected


# ------------------------------------------------------------------- the pass


def test_centipawn_loss_is_measured_from_the_movers_point_of_view():
    record = make_record(["e4", "Bc4"])
    moves = [t for t in record.turns if t.uci]
    # Positions: start, then one per move. A perfect white move, then a bad one.
    scores = [20, -20, 20, 400, 0]
    evaluator = FakeEvaluator(scores)
    result = analyse_record(record, engine=evaluator)

    assert evaluator.calls == len(moves) + 1
    first = result["moves"][0]
    assert first["cp_before"] == 20 and first["cp_after"] == 20
    assert first["centipawn_loss"] == 0
    second_ai = [m for m in result["moves"] if m["actor"] == "ai"][1]
    assert second_ai["cp_before"] == 20 and second_ai["cp_after"] == -400
    assert second_ai["centipawn_loss"] == 420
    assert second_ai["judgement"] == "blunder"


def test_side_statistics_are_separated():
    record = make_record(["e4", "Bc4"])
    result = analyse_record(record, engine=FakeEvaluator([20, -20, 20, 400, 0]))
    assert result["ai"]["moves"] == 2
    assert result["opponent"]["moves"] == 2
    assert result["ai"]["blunders"] == 1
    assert result["ai"]["average_centipawn_loss"] == 210.0
    assert 0 <= result["ai"]["accuracy"] <= 100
    assert result["thresholds"]["blunder_cp"] == BLUNDER_CP


def test_analysis_is_attached_to_the_record_and_survives_serialisation(tmp_path):
    record = make_record(["e4", "Bc4"])
    analyse_record(record, engine=FakeEvaluator([20, -20, 20, 400, 0]))
    paths = record.save(tmp_path)
    from bzbench.record import GameRecord

    reloaded = GameRecord.load(paths["json"])
    assert reloaded.analysis["ai"]["blunders"] == 1


def test_analysis_never_reaches_the_prompts():
    """The pass runs after the game; prompts are already fixed and unchanged."""
    record = make_record(["e4", "Bc4"])
    before = [t.prompt for t in record.turns]
    analyse_record(record, engine=FakeEvaluator([20, -20, 20, 400, 0]))
    after = [t.prompt for t in record.turns]
    assert before == after
    for prompt in [p for p in after if p]:
        for term in ("centipawn", "accuracy", "blunder", "cp_before"):
            assert term not in prompt.lower()


def test_empty_game_analyses_to_empty_statistics():
    record = make_record(["not-a-move"])
    result = analyse_record(record, engine=FakeEvaluator([0]))
    assert result["moves"] == []
    assert result["ai"]["moves"] == 0
    assert result["ai"]["accuracy"] is None


# --------------------------------------------------------------- integration


@pytest.mark.slow
def test_real_stockfish_scores_a_real_blunder(stockfish_path):
    """A hung queen must register as a blunder against the real engine."""
    record = make_record(["e4", "Qh5", "Qxh7"])  # Qxh7 loses the queen to Rxh7
    from bzbench.record import GameRecord

    assert isinstance(record, GameRecord)
    result = analyse_record(record, stockfish_path=stockfish_path, depth=10)
    ai_moves = [m for m in result["moves"] if m["actor"] == "ai"]
    assert ai_moves[-1]["centipawn_loss"] > BLUNDER_CP
    assert ai_moves[-1]["judgement"] == "blunder"
    assert result["ai"]["blunders"] >= 1
