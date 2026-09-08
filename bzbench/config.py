"""Experiment configuration.

Everything needed to reproduce a single benchmark game lives here. The config
is serialised verbatim into the game record.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import uuid
from typing import Any


class Protocol(str, enum.Enum):
    """Information protocol: exactly what the AI player is allowed to see."""

    RAW = "raw"
    """Rules/instructions + chronological SAN move history. Nothing else."""

    FEN = "fen"
    """RAW + the current FEN."""

    LEGAL = "legal"
    """Current FEN + the list of legal moves (SAN)."""

    VISUAL = "visual"
    """Reserved for a future board-image / computer-use experiment."""


class Color(str, enum.Enum):
    WHITE = "white"
    BLACK = "black"

    @property
    def is_white(self) -> bool:
        return self is Color.WHITE


DEFAULT_STOCKFISH_PATH = "stockfish"


@dataclasses.dataclass(frozen=True)
class MatchConfig:
    """Configuration of one benchmark game."""

    model_name: str
    protocol: Protocol = Protocol.RAW
    ai_color: Color = Color.WHITE
    adapter: str = "manual"

    # Opponent engine (never an oracle for the AI).
    stockfish_elo: int = 1400
    stockfish_path: str = DEFAULT_STOCKFISH_PATH
    stockfish_move_time_ms: int = 100
    stockfish_nodes: int | None = None
    """If set, the opponent searches a fixed node count instead of a fixed
    wall-clock time. Fixed nodes is the reproducible choice; movetime depends on
    the speed of the machine the experiment ran on."""
    stockfish_threads: int = 1
    stockfish_hash_mb: int = 16

    # Experiment bookkeeping.
    game_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex[:12])
    max_move_seconds: float | None = None
    """Wall-clock budget for one AI move. None disables the limit.

    Exceeding it terminates the game as an AI loss (time forfeit)."""
    max_plies: int = 400
    random_seed: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("model_name must not be empty")
        if not 500 <= self.stockfish_elo <= 4000:
            raise ValueError("stockfish_elo out of the plausible range 500-4000")
        if self.stockfish_move_time_ms <= 0:
            raise ValueError("stockfish_move_time_ms must be positive")
        if self.stockfish_nodes is not None and self.stockfish_nodes <= 0:
            raise ValueError("stockfish_nodes must be positive or None")
        if self.max_move_seconds is not None and self.max_move_seconds <= 0:
            raise ValueError("max_move_seconds must be positive or None")
        if self.max_plies <= 0:
            raise ValueError("max_plies must be positive")

    def to_dict(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["protocol"] = self.protocol.value
        out["ai_color"] = self.ai_color.value
        return out

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchConfig":
        data = dict(data)
        data["protocol"] = Protocol(data["protocol"])
        data["ai_color"] = Color(data["ai_color"])
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)
