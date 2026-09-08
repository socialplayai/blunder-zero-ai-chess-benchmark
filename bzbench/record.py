"""Game records: everything needed to audit and reproduce one experiment."""

from __future__ import annotations

import dataclasses
import datetime as dt
import io
import json
import pathlib
import platform
import subprocess
import sys
from typing import Any

import chess
import chess.pgn

from .config import Color, MatchConfig

SCHEMA_VERSION = 1


class Actor(str):
    AI = "ai"
    OPPONENT = "opponent"


class Termination(str):
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    SEVENTYFIVE_MOVES = "seventyfive_moves"
    FIVEFOLD_REPETITION = "fivefold_repetition"
    ILLEGAL_MOVE = "illegal_move"
    TIME_FORFEIT = "time_forfeit"
    RESIGNATION = "resignation"
    MAX_PLIES = "max_plies"
    ABORTED = "aborted"
    ENGINE_ERROR = "engine_error"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


@dataclasses.dataclass
class TurnRecord:
    """One half-move, including everything the AI was shown and replied."""

    ply: int
    actor: str
    color: str
    fen_before: str
    san: str | None = None
    uci: str | None = None
    started_at: str = ""
    finished_at: str = ""
    response_seconds: float | None = None

    # AI turns only.
    prompt: str | None = None
    raw_response: str | None = None
    normalized_response: str | None = None
    legal: bool | None = None
    rejection_reason: str | None = None
    view: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class GameRecord:
    config: MatchConfig
    opponent: dict[str, Any]
    adapter: dict[str, Any]
    environment: dict[str, Any] = dataclasses.field(default_factory=dict)
    started_at: str = dataclasses.field(default_factory=utc_now)
    finished_at: str | None = None
    turns: list[TurnRecord] = dataclasses.field(default_factory=list)
    result: str = "*"
    termination: str | None = None
    termination_detail: str = ""
    illegal_moves: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    analysis: dict[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION

    # ---------------------------------------------------------------- helpers

    @property
    def moves_uci(self) -> list[str]:
        return [t.uci for t in self.turns if t.uci]

    @property
    def ai_color(self) -> Color:
        return self.config.ai_color

    def ai_outcome(self) -> str:
        """'win', 'loss', 'draw' or 'unfinished' from the AI's point of view."""
        if self.result == "1/2-1/2":
            return "draw"
        if self.result == "1-0":
            return "win" if self.ai_color.is_white else "loss"
        if self.result == "0-1":
            return "loss" if self.ai_color.is_white else "win"
        return "unfinished"

    def effective_elo(self) -> int:
        """The Elo the opponent actually played at, falling back to the request."""
        value = self.opponent.get("effective_elo")
        return self.config.stockfish_elo if value is None else int(value)

    def board(self) -> chess.Board:
        board = chess.Board()
        for uci in self.moves_uci:
            board.push(chess.Move.from_uci(uci))
        return board

    # ------------------------------------------------------------ serialising

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config": self.config.to_dict(),
            "opponent": self.opponent,
            "adapter": self.adapter,
            "environment": self.environment,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "ai_outcome": self.ai_outcome(),
            "termination": self.termination,
            "termination_detail": self.termination_detail,
            "illegal_moves": self.illegal_moves,
            "turns": [t.to_dict() for t in self.turns],
            "analysis": self.analysis,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_pgn(self) -> str:
        game = chess.pgn.Game()
        cfg = self.config
        ai_name = cfg.model_name
        engine_name = self.opponent.get("engine_name", "Stockfish")
        elo = self.effective_elo()
        opponent_label = f"{engine_name} (Elo {elo})"

        game.headers["Event"] = "BlunderZero AI Chess Benchmark"
        game.headers["Site"] = platform.node() or "local"
        game.headers["Date"] = self.started_at[:10].replace("-", ".")
        game.headers["Round"] = "-"
        game.headers["White"] = ai_name if cfg.ai_color.is_white else opponent_label
        game.headers["Black"] = opponent_label if cfg.ai_color.is_white else ai_name
        game.headers["Result"] = self.result
        game.headers["GameId"] = cfg.game_id
        game.headers["Protocol"] = cfg.protocol.value
        game.headers["AIColor"] = cfg.ai_color.value
        game.headers["AIModel"] = ai_name
        game.headers["Adapter"] = cfg.adapter
        game.headers["StockfishElo"] = str(elo)
        if self.termination:
            game.headers["Termination"] = self.termination
        if self.termination_detail:
            game.headers["TerminationDetail"] = self.termination_detail

        node: chess.pgn.GameNode = game
        for uci in self.moves_uci:
            node = node.add_variation(chess.Move.from_uci(uci))

        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=True)
        return game.accept(exporter)

    # ----------------------------------------------------------------- saving

    def save(self, root: str | pathlib.Path) -> dict[str, pathlib.Path]:
        directory = pathlib.Path(root) / self.config.game_id
        directory.mkdir(parents=True, exist_ok=True)
        pgn_path = directory / "game.pgn"
        json_path = directory / "game.json"
        pgn_path.write_text(self.to_pgn() + "\n", encoding="utf-8")
        json_path.write_text(self.to_json() + "\n", encoding="utf-8")
        return {"pgn": pgn_path, "json": json_path, "dir": directory}

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "GameRecord":
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        record = cls(
            config=MatchConfig.from_dict(data["config"]),
            opponent=data.get("opponent", {}),
            adapter=data.get("adapter", {}),
            environment=data.get("environment", {}),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at"),
            result=data.get("result", "*"),
            termination=data.get("termination"),
            termination_detail=data.get("termination_detail", ""),
            illegal_moves=data.get("illegal_moves", []),
            analysis=data.get("analysis"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )
        record.turns = [TurnRecord(**t) for t in data.get("turns", [])]
        return record


def environment_fingerprint() -> dict[str, Any]:
    """Machine and library versions, so a run can be placed in context later."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=pathlib.Path(__file__).resolve().parent,
        ).stdout.strip() or None
    except Exception:
        commit = None
    return {
        "python": sys.version.split()[0],
        "python_chess": chess.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "bzbench_commit": commit,
    }
