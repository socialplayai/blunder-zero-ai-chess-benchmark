"""Stockfish wrappers.

Two strictly separate roles, both implemented here and neither reachable from
the AI interface:

* `StockfishOpponent` - the playing opponent. It answers exactly one question,
  "what is your move", and returns a `chess.Move`. It never returns a score, a
  depth or a principal variation, so there is nothing for the referee to leak.
* `AnalysisEngine` - the post-game evaluator. Constructed only by the analysis
  pass, after a game record is closed.

Neither `bzbench.protocol` nor any adapter imports this module; the leakage
tests assert that statically.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import chess
import chess.engine


class EngineUnavailable(RuntimeError):
    """Stockfish could not be started."""


def _open(path: str) -> chess.engine.SimpleEngine:
    try:
        return chess.engine.SimpleEngine.popen_uci(path)
    except (OSError, chess.engine.EngineError) as exc:
        raise EngineUnavailable(f"could not start Stockfish at {path!r}: {exc}") from exc


def _apply(engine: chess.engine.SimpleEngine, options: dict[str, Any]) -> None:
    for key, value in options.items():
        if key in engine.options:
            engine.configure({key: value})


@dataclasses.dataclass
class OpponentDescription:
    """Reproducibility metadata about the opponent, recorded with the game."""

    engine_name: str
    engine_author: str
    requested_elo: int
    effective_elo: int | None
    limit: dict[str, Any]
    options: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class StockfishOpponent:
    """The playing opponent. Returns moves and nothing else."""

    def __init__(
        self,
        path: str,
        *,
        elo: int,
        move_time_ms: int = 100,
        nodes: int | None = None,
        threads: int = 1,
        hash_mb: int = 16,
    ) -> None:
        self._engine = _open(path)
        self._requested_elo = elo
        self._effective_elo: int | None = None

        options: dict[str, Any] = {"Threads": threads, "Hash": hash_mb}
        elo_option = self._engine.options.get("UCI_Elo")
        if elo_option is not None:
            low = elo_option.min if elo_option.min is not None else elo
            high = elo_option.max if elo_option.max is not None else elo
            self._effective_elo = max(low, min(high, elo))
            options["UCI_LimitStrength"] = True
            options["UCI_Elo"] = self._effective_elo
        _apply(self._engine, options)
        self._options = options

        if nodes is not None:
            self._limit = chess.engine.Limit(nodes=nodes)
            self._limit_desc = {"nodes": nodes}
        else:
            self._limit = chess.engine.Limit(time=move_time_ms / 1000.0)
            self._limit_desc = {"movetime_ms": move_time_ms}

    @property
    def effective_elo(self) -> int | None:
        return self._effective_elo

    def play(self, board: chess.Board) -> chess.Move:
        """Return the opponent's move for `board`. No evaluation is exposed."""
        result = self._engine.play(board, self._limit, info=chess.engine.INFO_NONE)
        if result.move is None:
            raise chess.engine.EngineError("opponent returned no move")
        return result.move

    def describe(self) -> OpponentDescription:
        ident = self._engine.id
        return OpponentDescription(
            engine_name=ident.get("name", "unknown"),
            engine_author=ident.get("author", "unknown"),
            requested_elo=self._requested_elo,
            effective_elo=self._effective_elo,
            limit=dict(self._limit_desc),
            options=dict(self._options),
        )

    def close(self) -> None:
        try:
            self._engine.quit()
        except Exception:  # pragma: no cover - best effort teardown
            pass

    def __enter__(self) -> "StockfishOpponent":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AnalysisEngine:
    """Full-strength Stockfish used only after a game is over."""

    def __init__(
        self,
        path: str,
        *,
        depth: int = 16,
        threads: int = 1,
        hash_mb: int = 128,
        multipv: int = 1,
    ) -> None:
        self._engine = _open(path)
        self._options = {"Threads": threads, "Hash": hash_mb}
        _apply(self._engine, self._options)
        self._limit = chess.engine.Limit(depth=depth)
        self._depth = depth
        self._multipv = multipv

    def evaluate(self, board: chess.Board) -> chess.engine.PovScore:
        """Score `board` from the side-to-move's point of view."""
        info = self._engine.analyse(board, self._limit)
        return info["score"]

    def best_move(self, board: chess.Board) -> chess.Move | None:
        info = self._engine.analyse(board, self._limit)
        pv = info.get("pv") or []
        return pv[0] if pv else None

    def describe(self) -> dict[str, Any]:
        ident = self._engine.id
        return {
            "engine_name": ident.get("name", "unknown"),
            "engine_author": ident.get("author", "unknown"),
            "depth": self._depth,
            "options": dict(self._options),
            "multipv": self._multipv,
        }

    def close(self) -> None:
        try:
            self._engine.quit()
        except Exception:  # pragma: no cover
            pass

    def __enter__(self) -> "AnalysisEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
