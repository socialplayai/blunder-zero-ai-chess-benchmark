"""Adapter interface for AI players.

An adapter turns a protocol-filtered prompt into a raw text response. It is the
only place a model is contacted. Adapters receive the prompt and the `TurnView`
that produced it; both are already protocol-filtered, so an adapter cannot leak
information the protocol forbids.
"""

from __future__ import annotations

import abc

from ..protocol import TurnView


class AbortGame(Exception):
    """Raised by an adapter when the operator aborts the session."""


class ResignGame(Exception):
    """Raised by an adapter when the AI player resigns."""


class AIPlayer(abc.ABC):
    """Base class for every AI player adapter."""

    name: str = "abstract"

    @abc.abstractmethod
    def propose_move(self, prompt: str, view: TurnView) -> str:
        """Return the raw, unmodified model response for this turn."""

    def describe(self) -> dict:
        """Reproducibility metadata recorded with the game."""
        return {"adapter": self.name}

    def close(self) -> None:  # pragma: no cover - default no-op
        pass
