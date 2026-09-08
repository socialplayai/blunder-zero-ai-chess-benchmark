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


class PlayerInfrastructureError(Exception):
    """A failure of the plumbing, not of the model's chess.

    Everything raised from this class ends the game without a result. It is
    never scored as a chess loss: an authentication failure, a rate limit or a
    dropped connection says nothing about how well the model plays.
    """

    kind = "infrastructure_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class AuthenticationFailure(PlayerInfrastructureError):
    kind = "api_authentication"


class RateLimited(PlayerInfrastructureError):
    kind = "api_rate_limit"


class RequestTimeout(PlayerInfrastructureError):
    kind = "api_timeout"


class NetworkFailure(PlayerInfrastructureError):
    kind = "api_network"


class ProviderError(PlayerInfrastructureError):
    """A 5xx or otherwise server side failure."""

    kind = "api_server_error"


class RequestRejected(PlayerInfrastructureError):
    """A 4xx that is our fault: bad parameters, unsupported setting, no access."""

    kind = "api_request_rejected"


class OutputLimitReached(PlayerInfrastructureError):
    """The response stopped at the configured output ceiling.

    The ceiling is an operator setting, so an answer cut short by it says
    nothing about the model's chess and is never scored as a loss.
    """

    kind = "api_output_limit"


class BudgetStop(PlayerInfrastructureError):
    """A configured spend or token guard stopped the game before a request."""

    kind = "cost_limit_abort"


class TokenBudgetStop(BudgetStop):
    kind = "token_limit_abort"


class AIPlayer(abc.ABC):
    """Base class for every AI player adapter."""

    name: str = "abstract"

    @abc.abstractmethod
    def propose_move(self, prompt: str, view: TurnView) -> str:
        """Return the raw, unmodified model response for this turn."""

    def describe(self) -> dict:
        """Reproducibility metadata recorded with the game. Never secrets."""
        return {"adapter": self.name}

    def pop_turn_metadata(self) -> dict | None:
        """Per turn telemetry for the record, consumed once by the referee."""
        return None

    def session_summary(self) -> dict | None:
        """Whole game telemetry for the record, read when the game ends."""
        return None

    def close(self) -> None:  # pragma: no cover - default no-op
        pass
