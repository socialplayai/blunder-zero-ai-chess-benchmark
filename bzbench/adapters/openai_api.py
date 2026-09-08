"""OpenAI Responses API adapter.

The model plays with nothing but the benchmark prompt. Concretely, every
request is built by `_build_request` and contains `tools=[]`: no function
calling, no code interpreter, no file search, no web search, no computer use,
no structured output schema. The adapter does not parse the position, does not
generate or check moves, and does not extract a move from the reply. It returns
the model's visible text verbatim and lets the referee judge it.

Conversation state
------------------
One game is one response chain. Each turn sends the new prompt with
`previous_response_id` set to the id of the previous response, and `store=True`
so the provider keeps the chain, which is what lets the model retain its own
earlier reasoning. A new adapter instance is created for every game and starts
with no previous response id, so no context crosses a game boundary.

Retry policy
------------
Retries exist only for failures that happened *before* a model response
existed, and only for transient classes: rate limit, timeout, connection error
and 5xx. Authentication failures and rejected requests are never retried. A
completed response is never retried, whatever it contains: a malformed or
illegal move is a result of the benchmark, not an error to paper over. Every
attempt is recorded. Retries resend a byte identical request, so a retry cannot
put more chess information in front of the model.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, Callable

from ..pricing import BudgetExceeded, CostLedger, Pricing, extract_usage
from ..protocol import TurnView
from .base import (
    AIPlayer,
    AuthenticationFailure,
    BudgetStop,
    NetworkFailure,
    OutputLimitReached,
    PlayerInfrastructureError,
    ProviderError,
    RateLimited,
    RequestRejected,
    RequestTimeout,
    TokenBudgetStop,
)

DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"

# Effort levels the Responses API accepts, and the per model exceptions.
# Source: OpenAI reasoning guide, https://developers.openai.com/api/docs/guides/reasoning
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
UNSUPPORTED_EFFORTS: dict[str, tuple[str, ...]] = {
    # gpt-6-astra rejects `none` with HTTP 400.
    "gpt-6-astra": ("none",),
}


class ReasoningEffortNotSupported(ValueError):
    """The requested reasoning level cannot be used. Never silently replaced."""


def validate_reasoning_effort(model: str, effort: str) -> str:
    if effort not in REASONING_EFFORTS:
        raise ReasoningEffortNotSupported(
            f"reasoning effort {effort!r} is not a value the Responses API accepts; "
            f"allowed: {', '.join(REASONING_EFFORTS)}"
        )
    if effort in UNSUPPORTED_EFFORTS.get(model, ()):  # pragma: no branch
        raise ReasoningEffortNotSupported(
            f"model {model!r} does not support reasoning effort {effort!r}"
        )
    return effort


class OpenAIResponsesAdapter(AIPlayer):
    """Plays through the OpenAI Responses API with no tools of any kind."""

    name = "openai"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = "high",
        pricing: Pricing | None = None,
        max_cost_usd: float | None = 15.0,
        max_total_tokens: int | None = None,
        max_output_tokens: int | None = None,
        store: bool = True,
        service_tier: str | None = None,
        request_timeout: float = 900.0,
        max_attempts: int = 3,
        backoff_seconds: float = 5.0,
        game_id: str = "",
        api_key_env: str = DEFAULT_API_KEY_ENV,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.requested_reasoning_effort = reasoning_effort
        self.reasoning_effort = validate_reasoning_effort(model, reasoning_effort)
        self.pricing = pricing or Pricing.for_model(model)
        self.ledger = CostLedger(
            pricing=self.pricing,
            max_cost_usd=max_cost_usd,
            max_total_tokens=max_total_tokens,
        )
        self.max_output_tokens = max_output_tokens
        self.store = store
        self.service_tier = service_tier
        self.request_timeout = request_timeout
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_seconds = backoff_seconds
        self.game_id = game_id
        self.api_key_env = api_key_env
        self._sleep = sleep

        self._client = client if client is not None else build_client(api_key_env)
        self._previous_response_id: str | None = None
        self._response_ids: list[str] = []
        self._pending_metadata: dict[str, Any] | None = None
        self._calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------- requests

    def _build_request(self, prompt: str, view: TurnView) -> dict[str, Any]:
        """The complete request. `tools` is always an empty list."""
        request: dict[str, Any] = {
            "model": self.model,
            "input": prompt,
            "reasoning": {"effort": self.reasoning_effort},
            "tools": [],
            "store": self.store,
            "metadata": {
                "benchmark": "blunder-zero-ai-chess-benchmark",
                "game_id": self.game_id,
                "ply": str(view.ply),
                "protocol": view.protocol.value,
            },
        }
        if self._previous_response_id is not None:
            request["previous_response_id"] = self._previous_response_id
        if self.max_output_tokens is not None:
            request["max_output_tokens"] = self.max_output_tokens
        if self.service_tier is not None:
            request["service_tier"] = self.service_tier
        return request

    def propose_move(self, prompt: str, view: TurnView) -> str:
        try:
            self.ledger.check_before_request()
        except BudgetExceeded as exc:
            cls = TokenBudgetStop if exc.kind == "tokens" else BudgetStop
            raise cls(str(exc), detail=self.ledger.summary()) from exc

        request = self._build_request(prompt, view)
        response, attempts = self._call_with_retries(request)

        usage = extract_usage(_as_dict(getattr(response, "usage", None)))
        cost = self.ledger.add(usage)
        response_id = getattr(response, "id", None)
        status = getattr(response, "status", None)

        if self.store and response_id:
            self._previous_response_id = response_id
            self._response_ids.append(response_id)

        text = _visible_text(response)

        record = {
            "ply": view.ply,
            "request": _redacted_request(request),
            "response_id": response_id,
            "previous_response_id": request.get("previous_response_id"),
            "status": status,
            "incomplete_details": _as_dict(
                getattr(response, "incomplete_details", None)
            ),
            "model_reported": getattr(response, "model", None),
            "service_tier_reported": getattr(response, "service_tier", None),
            "reasoning_requested": self.requested_reasoning_effort,
            "reasoning_effective": self.reasoning_effort,
            "usage": usage,
            "raw_usage": _as_dict(getattr(response, "usage", None)),
            "cost": cost.to_dict(),
            "cumulative_cost_usd": self.ledger.total_cost_usd,
            "cumulative_total_tokens": self.ledger.total_tokens,
            "attempts": attempts,
        }
        self._calls.append(record)
        self._pending_metadata = record

        if status == "incomplete":
            # The model never finished a response. That is an operator set cap
            # or a provider stop, not a chess decision, so it must not be
            # scored as a loss.
            details = record["incomplete_details"] or {}
            reason = details.get("reason") if isinstance(details, dict) else None
            failure = (
                OutputLimitReached
                if reason == "max_output_tokens"
                else PlayerInfrastructureError
            )
            raise failure(
                f"response {response_id} came back incomplete: {details}"
                + (
                    f"; max_output_tokens={self.max_output_tokens}"
                    if self.max_output_tokens is not None
                    else ""
                ),
                detail=record,
            )

        return text

    def _call_with_retries(self, request: dict[str, Any]) -> tuple[Any, list[dict]]:
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                response = self._client.responses.create(
                    timeout=self.request_timeout, **request
                )
            except Exception as exc:  # noqa: BLE001 - re-raised as a typed failure
                failure = classify_exception(exc)
                entry = {
                    "attempt": attempt,
                    "outcome": "error",
                    "error_kind": failure.kind,
                    "error": _safe_error_text(exc),
                    "status_code": getattr(exc, "status_code", None),
                    "request_id": getattr(exc, "request_id", None),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
                attempts.append(entry)
                retryable = isinstance(
                    failure, (RateLimited, RequestTimeout, NetworkFailure, ProviderError)
                )
                if not retryable or attempt == self.max_attempts:
                    failure.detail = {"attempts": attempts}
                    raise failure from exc
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                delay += random.uniform(0, self.backoff_seconds)
                entry["retry_in_seconds"] = round(delay, 3)
                self._sleep(delay)
                continue
            attempts.append(
                {
                    "attempt": attempt,
                    "outcome": "response",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "request_id": getattr(response, "_request_id", None),
                }
            )
            return response, attempts
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------ telemetry

    def pop_turn_metadata(self) -> dict[str, Any] | None:
        metadata, self._pending_metadata = self._pending_metadata, None
        return metadata

    def describe(self) -> dict[str, Any]:
        """Generation configuration. Never contains the API key."""
        return {
            "adapter": self.name,
            "provider": "openai",
            "api": "responses",
            "model": self.model,
            "reasoning_effort_requested": self.requested_reasoning_effort,
            "reasoning_effort_effective": self.reasoning_effort,
            "tools": [],
            "tool_use_enabled": False,
            "structured_output": False,
            "store": self.store,
            "service_tier": self.service_tier,
            "max_output_tokens": self.max_output_tokens,
            "request_timeout_seconds": self.request_timeout,
            "max_attempts": self.max_attempts,
            "backoff_seconds": self.backoff_seconds,
            "api_key_env": self.api_key_env,
            "max_cost_usd": self.ledger.max_cost_usd,
            "max_total_tokens": self.ledger.max_total_tokens,
            "pricing": self.pricing.to_dict(),
        }

    def max_single_call_exposure_usd(
        self, assumed_input_tokens: int | None = None
    ) -> dict[str, Any]:
        """Bounded metered exposure of one more request. See docs/api-adapter.md.

        The output side is bounded by `max_output_tokens`. The input side is
        bounded only by the model's context window, so the honest answer is a
        range: the realistic bound uses the largest input seen so far in this
        game, and the worst case bound uses the short context threshold.
        """
        pricing = self.pricing
        ceiling = self.max_output_tokens
        seen = [c["usage"]["input_tokens"] or 0 for c in self._calls]
        observed_max_input = max(seen) if seen else 0
        assumed = assumed_input_tokens or max(observed_max_input, 4000)
        output_bound = (
            None if ceiling is None else ceiling * pricing.output_per_mtok / 1e6
        )
        return {
            "max_output_tokens": ceiling,
            "output_cost_bound_usd": (
                None if output_bound is None else round(output_bound, 6)
            ),
            "assumed_input_tokens": assumed,
            "input_cost_at_assumed_usd": round(
                assumed * pricing.input_per_mtok / 1e6, 6
            ),
            "single_call_bound_at_assumed_usd": (
                None
                if output_bound is None
                else round(output_bound + assumed * pricing.input_per_mtok / 1e6, 6)
            ),
            "input_cost_at_short_context_threshold_usd": round(
                pricing.long_context_threshold_tokens * pricing.input_per_mtok / 1e6, 6
            ),
            "observed_max_input_tokens": observed_max_input,
            "note": (
                "The guard is metered on usage the API reports. One in flight "
                "request can still land after the cap is reached, so the cap is "
                "not a billing ceiling. Cache write tokens are not exposed by the "
                "API and are not included in any figure here."
            ),
        }

    def session_summary(self) -> dict[str, Any]:
        summary = self.ledger.summary()
        summary["max_output_tokens"] = self.max_output_tokens
        summary["max_single_call_exposure"] = self.max_single_call_exposure_usd()
        summary["response_ids"] = list(self._response_ids)
        summary["calls"] = len(self._calls)
        return summary


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def build_client(api_key_env: str = DEFAULT_API_KEY_ENV, **kwargs: Any) -> Any:
    """Build an OpenAI client from the environment. The key is never stored."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise RequestRejected(
            "the openai package is not installed; pip install openai"
        ) from exc
    if not os.environ.get(api_key_env):
        raise AuthenticationFailure(
            f"environment variable {api_key_env} is not set; the benchmark reads the "
            "API key from the environment only"
        )
    # max_retries=0: this adapter owns the retry policy, so every attempt is
    # visible in the record instead of being hidden inside the SDK.
    return OpenAI(api_key=os.environ[api_key_env], max_retries=0, **kwargs)


def classify_exception(exc: Exception) -> PlayerInfrastructureError:
    """Map an SDK or transport exception onto the benchmark's failure taxonomy."""
    try:
        import openai
    except ImportError:  # pragma: no cover - dependency missing
        return NetworkFailure(_safe_error_text(exc))

    message = _safe_error_text(exc)
    if isinstance(exc, openai.AuthenticationError):
        return AuthenticationFailure(message)
    if isinstance(exc, openai.PermissionDeniedError):
        return AuthenticationFailure(message)
    if isinstance(exc, openai.RateLimitError):
        return RateLimited(message)
    if isinstance(exc, openai.APITimeoutError):
        return RequestTimeout(message)
    if isinstance(exc, openai.APIConnectionError):
        return NetworkFailure(message)
    if isinstance(exc, openai.InternalServerError):
        return ProviderError(message)
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", 0) or 0
        if status >= 500:
            return ProviderError(message)
        return RequestRejected(message)
    if isinstance(exc, openai.APIError):
        return ProviderError(message)
    if isinstance(exc, PlayerInfrastructureError):
        return exc
    return NetworkFailure(message)


def _visible_text(response: Any) -> str:
    """The model's visible output, verbatim, with no extraction or repair."""
    text = getattr(response, "output_text", None)
    if isinstance(text, str):
        return text
    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for chunk in getattr(item, "content", None) or []:
            value = getattr(chunk, "text", None)
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def _as_dict(value: Any) -> Any:
    if value is None:
        return None
    for method in ("model_dump", "to_dict", "dict"):
        fn = getattr(value, method, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # pragma: no cover - defensive
                continue
    if isinstance(value, dict):
        return dict(value)
    return str(value)


def _redacted_request(request: dict[str, Any]) -> dict[str, Any]:
    """The request as recorded: the prompt is stored on the turn already."""
    recorded = {k: v for k, v in request.items() if k != "input"}
    recorded["input_length_chars"] = len(request.get("input", ""))
    return recorded


def _safe_error_text(exc: Exception) -> str:
    """Error text with anything that looks like a key removed."""
    text = f"{type(exc).__name__}: {exc}"
    return scrub_secrets(text)


def scrub_secrets(text: str) -> str:
    """Remove API keys from any string before it is stored or printed."""
    import re

    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***REDACTED***", text)
    for name in (DEFAULT_API_KEY_ENV, "OPENAI_ADMIN_KEY"):
        value = os.environ.get(name)
        if value and len(value) >= 8:
            text = text.replace(value, "***REDACTED***")
    return text
