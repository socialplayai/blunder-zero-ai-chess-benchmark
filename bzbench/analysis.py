"""Post-game Stockfish analysis.

This pass runs only after a game record is closed. Its output is written into
the record and into reports; it is never available to the AI player during play.
The referee does not import this module.

Method
------
Every position of the game is evaluated once, at a fixed depth, with a
full-strength engine. For the move played at ply i:

    cp_before = eval(position i)          from the mover's point of view
    cp_after  = -eval(position i + 1)     same point of view
    cpl       = clamp(max(0, cp_before - cp_after), 0, CP_CAP)

Accuracy uses the Lichess win-percentage model. It is an approximation of the
Lichess number, not a reimplementation of it: move accuracies are averaged
uniformly rather than volatility weighted.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Iterable

import chess

from .engine import AnalysisEngine
from .record import Actor, GameRecord

CP_CAP = 1000
MATE_SCORE = 10000

INACCURACY_CP = 50
MISTAKE_CP = 100
BLUNDER_CP = 300


def win_percent(cp: float) -> float:
    """Lichess win percentage for a centipawn score, 0-100."""
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def move_accuracy(wp_before: float, wp_after: float) -> float:
    """Lichess per-move accuracy in 0-100 from the mover's win percentages."""
    drop = max(0.0, wp_before - wp_after)
    value = 103.1668 * math.exp(-0.04354 * drop) - 3.1669
    return max(0.0, min(100.0, value))


def classify(cpl: float) -> str | None:
    if cpl >= BLUNDER_CP:
        return "blunder"
    if cpl >= MISTAKE_CP:
        return "mistake"
    if cpl >= INACCURACY_CP:
        return "inaccuracy"
    return None


@dataclasses.dataclass
class MoveAnalysis:
    ply: int
    actor: str
    color: str
    san: str
    cp_before: int
    cp_after: int
    centipawn_loss: int
    accuracy: float
    judgement: str | None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _side_stats(moves: Iterable[MoveAnalysis]) -> dict[str, Any]:
    moves = list(moves)
    if not moves:
        return {
            "moves": 0,
            "accuracy": None,
            "average_centipawn_loss": None,
            "inaccuracies": 0,
            "mistakes": 0,
            "blunders": 0,
        }
    return {
        "moves": len(moves),
        "accuracy": round(sum(m.accuracy for m in moves) / len(moves), 2),
        "average_centipawn_loss": round(
            sum(m.centipawn_loss for m in moves) / len(moves), 1
        ),
        "inaccuracies": sum(1 for m in moves if m.judgement == "inaccuracy"),
        "mistakes": sum(1 for m in moves if m.judgement == "mistake"),
        "blunders": sum(1 for m in moves if m.judgement == "blunder"),
    }


def analyse_record(
    record: GameRecord,
    *,
    stockfish_path: str | None = None,
    depth: int = 16,
    threads: int = 1,
    hash_mb: int = 128,
    engine: Any | None = None,
) -> dict[str, Any]:
    """Run the post-game pass and attach the result to `record`.

    `engine` injects an already-open evaluator (used by the tests); when it is
    None a full-strength Stockfish is started and closed here.
    """
    path = stockfish_path or record.config.stockfish_path
    moves = [t for t in record.turns if t.uci]
    if not moves:
        result = {
            "engine": None,
            "thresholds": _thresholds(),
            "moves": [],
            "ai": _side_stats([]),
            "opponent": _side_stats([]),
        }
        record.analysis = result
        return result

    if engine is not None:
        engine_desc, scores = _score_game(engine, moves)
    else:
        with AnalysisEngine(
            path, depth=depth, threads=threads, hash_mb=hash_mb
        ) as opened:
            engine_desc, scores = _score_game(opened, moves)

    analyses: list[MoveAnalysis] = []
    for index, turn in enumerate(moves):
        cp_before = scores[index]
        cp_after = -scores[index + 1]  # same point of view as the mover
        cp_before_c = _clamp(cp_before)
        cp_after_c = _clamp(cp_after)
        cpl = max(0, cp_before_c - cp_after_c)
        accuracy = move_accuracy(win_percent(cp_before_c), win_percent(cp_after_c))
        analyses.append(
            MoveAnalysis(
                ply=turn.ply,
                actor=turn.actor,
                color=turn.color,
                san=turn.san or "",
                cp_before=cp_before_c,
                cp_after=cp_after_c,
                centipawn_loss=cpl,
                accuracy=round(accuracy, 2),
                judgement=classify(cpl),
            )
        )

    result = {
        "engine": engine_desc,
        "thresholds": _thresholds(),
        "moves": [m.to_dict() for m in analyses],
        "ai": _side_stats(m for m in analyses if m.actor == Actor.AI),
        "opponent": _side_stats(m for m in analyses if m.actor == Actor.OPPONENT),
    }
    record.analysis = result
    return result


def _score_game(engine: Any, moves: list) -> tuple[dict[str, Any], list[int]]:
    """Evaluate every position of the game once, side-to-move point of view."""
    board = chess.Board()
    scores = [_cp(engine.evaluate(board))]
    for turn in moves:
        board.push(chess.Move.from_uci(turn.uci))
        scores.append(_cp(engine.evaluate(board)))
    return engine.describe(), scores


def _thresholds() -> dict[str, int]:
    return {
        "inaccuracy_cp": INACCURACY_CP,
        "mistake_cp": MISTAKE_CP,
        "blunder_cp": BLUNDER_CP,
        "cp_cap": CP_CAP,
        "mate_score": MATE_SCORE,
    }


def _cp(score: chess.engine.PovScore) -> int:  # type: ignore[name-defined]
    """Centipawns from the side-to-move's point of view."""
    return score.relative.score(mate_score=MATE_SCORE)


def _clamp(cp: int) -> int:
    return max(-CP_CAP, min(CP_CAP, cp))
