"""Pricing metadata, per move cost accounting and spend guards.

Prices are never hard coded in the code path. They live in a JSON file under
`pricing/` that records the rates, the moment they were verified and the
official source, so a published cost figure can be audited later.

Billing model, stated explicitly because getting it wrong is the easiest way to
publish a wrong number:

* `usage.output_tokens` from the Responses API already includes
  `usage.output_tokens_details.reasoning_tokens`. Reasoning is billed as
  output. This module therefore charges output tokens once and reports the
  reasoning share as information only.
* `usage.input_tokens` already includes
  `usage.input_tokens_details.cached_tokens`. Cached tokens are charged at the
  cached rate and the remainder at the full input rate.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
from typing import Any

DEFAULT_PRICING_DIR = pathlib.Path(__file__).resolve().parents[1] / "pricing"


class PricingError(ValueError):
    """The pricing file is missing, malformed or incomplete."""


@dataclasses.dataclass(frozen=True)
class Pricing:
    """Rates in dollars per million tokens, plus provenance."""

    model: str
    input_per_mtok: float
    cached_input_per_mtok: float
    output_per_mtok: float
    long_input_per_mtok: float
    long_cached_input_per_mtok: float
    long_output_per_mtok: float
    long_context_threshold_tokens: int
    currency: str
    service_tier: str
    verified_at: str
    source: str
    notes: tuple[str, ...] = ()
    path: str | None = None

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Pricing":
        path = pathlib.Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PricingError(f"pricing file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise PricingError(f"pricing file is not valid JSON: {path}: {exc}") from exc
        return cls.from_dict(data, path=str(path))

    @classmethod
    def for_model(
        cls, model: str, pricing_dir: str | pathlib.Path | None = None
    ) -> "Pricing":
        directory = pathlib.Path(pricing_dir or DEFAULT_PRICING_DIR)
        path = directory / f"{model}.json"
        if not path.exists():
            raise PricingError(
                f"no pricing file for model {model!r} in {directory}; add one with "
                "the official rates, the verification date and the source URL"
            )
        pricing = cls.load(path)
        if pricing.model != model:
            raise PricingError(
                f"pricing file {path} declares model {pricing.model!r}, expected {model!r}"
            )
        return pricing

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str | None = None) -> "Pricing":
        try:
            standard = data["standard"]
            long_context = data.get("long_context", standard)
            pricing = cls(
                model=data["model"],
                input_per_mtok=float(standard["input"]),
                cached_input_per_mtok=float(standard["cached_input"]),
                output_per_mtok=float(standard["output"]),
                long_input_per_mtok=float(long_context["input"]),
                long_cached_input_per_mtok=float(long_context["cached_input"]),
                long_output_per_mtok=float(long_context["output"]),
                long_context_threshold_tokens=int(
                    data.get("long_context_input_threshold_tokens", 0) or 0
                ),
                currency=data.get("currency", "USD"),
                service_tier=data.get("service_tier", "standard"),
                verified_at=data["verified_at"],
                source=data["source"],
                notes=tuple(data.get("notes", ())),
                path=path,
            )
        except KeyError as exc:
            raise PricingError(f"pricing file is missing field {exc}") from exc
        pricing.validate()
        return pricing

    def validate(self) -> None:
        for name in ("input_per_mtok", "cached_input_per_mtok", "output_per_mtok"):
            if getattr(self, name) < 0:
                raise PricingError(f"{name} must not be negative")
        try:
            dt.datetime.fromisoformat(self.verified_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PricingError(
                f"verified_at must be an ISO 8601 timestamp, got {self.verified_at!r}"
            ) from exc
        if not self.source.startswith("http"):
            raise PricingError("source must be the official pricing URL")

    def age_days(self, now: dt.datetime | None = None) -> float:
        verified = dt.datetime.fromisoformat(self.verified_at.replace("Z", "+00:00"))
        now = now or dt.datetime.now(dt.timezone.utc)
        return (now - verified).total_seconds() / 86400.0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------------------
# Usage and cost
# --------------------------------------------------------------------------


def extract_usage(raw_usage: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise the Responses API usage object without inventing fields.

    Any field the API did not return stays `None`. Reasoning tokens in
    particular are never inferred.
    """
    raw_usage = raw_usage or {}
    input_details = raw_usage.get("input_tokens_details") or {}
    output_details = raw_usage.get("output_tokens_details") or {}
    return {
        "input_tokens": raw_usage.get("input_tokens"),
        "cached_input_tokens": input_details.get("cached_tokens"),
        "output_tokens": raw_usage.get("output_tokens"),
        "reasoning_tokens": output_details.get("reasoning_tokens"),
        "total_tokens": raw_usage.get("total_tokens"),
    }


@dataclasses.dataclass
class MoveCost:
    """Cost of one API call, derived only from usage fields the API returned."""

    input_tokens: int
    cached_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    reasoning_cost_share_usd: float | None
    long_context: bool
    reasoning_included_in_output_cost: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def cost_of(usage: dict[str, Any], pricing: Pricing) -> MoveCost:
    """Cost of a single response. Reasoning tokens are never charged twice."""
    input_tokens = int(usage.get("input_tokens") or 0)
    cached = int(usage.get("cached_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    reasoning = usage.get("reasoning_tokens")
    total = usage.get("total_tokens")
    total_tokens = int(total) if total is not None else input_tokens + output_tokens

    cached = min(cached, input_tokens)
    uncached = input_tokens - cached

    long_context = bool(
        pricing.long_context_threshold_tokens
        and input_tokens > pricing.long_context_threshold_tokens
    )
    if long_context:
        in_rate = pricing.long_input_per_mtok
        cached_rate = pricing.long_cached_input_per_mtok
        out_rate = pricing.long_output_per_mtok
    else:
        in_rate = pricing.input_per_mtok
        cached_rate = pricing.cached_input_per_mtok
        out_rate = pricing.output_per_mtok

    per_token = 1_000_000.0
    input_cost = (uncached * in_rate + cached * cached_rate) / per_token
    # Reasoning tokens are part of output_tokens; charging output once is the
    # whole charge for reasoning as well.
    output_cost = output_tokens * out_rate / per_token
    reasoning_share = (
        None if reasoning is None else int(reasoning) * out_rate / per_token
    )

    return MoveCost(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        uncached_input_tokens=uncached,
        output_tokens=output_tokens,
        reasoning_tokens=None if reasoning is None else int(reasoning),
        total_tokens=total_tokens,
        input_cost_usd=round(input_cost, 8),
        output_cost_usd=round(output_cost, 8),
        total_cost_usd=round(input_cost + output_cost, 8),
        reasoning_cost_share_usd=(
            None if reasoning_share is None else round(reasoning_share, 8)
        ),
        long_context=long_context,
    )


# --------------------------------------------------------------------------
# Spend guards
# --------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """A configured spend or token guard is already at its limit."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # "cost" or "tokens"


@dataclasses.dataclass
class CostLedger:
    """Accumulates usage across a game and refuses to let a run run away."""

    pricing: Pricing
    max_cost_usd: float | None = None
    max_total_tokens: int | None = None
    calls: int = 0
    total_cost_usd: float = 0.0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    reasoning_tokens_reported: bool = False
    total_tokens: int = 0

    def check_before_request(self) -> None:
        """Raise if a further request would breach a guard. Called first."""
        if self.max_cost_usd is not None and self.total_cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(
                "cost",
                f"accumulated cost ${self.total_cost_usd:.4f} reached the per game "
                f"cap of ${self.max_cost_usd:.2f}",
            )
        if (
            self.max_total_tokens is not None
            and self.total_tokens >= self.max_total_tokens
        ):
            raise BudgetExceeded(
                "tokens",
                f"accumulated {self.total_tokens} tokens reached the per game cap "
                f"of {self.max_total_tokens}",
            )

    def add(self, usage: dict[str, Any]) -> MoveCost:
        cost = cost_of(usage, self.pricing)
        self.calls += 1
        self.total_cost_usd = round(self.total_cost_usd + cost.total_cost_usd, 8)
        self.input_cost_usd = round(self.input_cost_usd + cost.input_cost_usd, 8)
        self.output_cost_usd = round(self.output_cost_usd + cost.output_cost_usd, 8)
        self.input_tokens += cost.input_tokens
        self.cached_input_tokens += cost.cached_input_tokens
        self.output_tokens += cost.output_tokens
        self.total_tokens += cost.total_tokens
        if cost.reasoning_tokens is not None:
            self.reasoning_tokens += cost.reasoning_tokens
            self.reasoning_tokens_reported = True
        return cost

    def summary(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": (
                self.reasoning_tokens if self.reasoning_tokens_reported else None
            ),
            "total_tokens": self.total_tokens,
            "input_cost_usd": round(self.input_cost_usd, 6),
            "output_cost_usd": round(self.output_cost_usd, 6),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "reasoning_included_in_output_cost": True,
            "max_cost_usd": self.max_cost_usd,
            "max_total_tokens": self.max_total_tokens,
            "pricing": self.pricing.to_dict(),
        }


# --------------------------------------------------------------------------
# Pre-run estimation
# --------------------------------------------------------------------------


def estimate_game_cost(
    pricing: Pricing,
    *,
    moves: int,
    input_tokens_per_move: int,
    output_tokens_per_move: int,
) -> dict[str, Any]:
    """A deliberately pessimistic upper bound for one game, for budgeting.

    No caching is assumed, every input token is charged at the full rate, and
    every output token (reasoning included, since reasoning is billed as
    output) is charged at the output rate.
    """
    input_cost = moves * input_tokens_per_move * pricing.input_per_mtok / 1_000_000.0
    output_cost = moves * output_tokens_per_move * pricing.output_per_mtok / 1_000_000.0
    return {
        "assumed_moves": moves,
        "assumed_input_tokens_per_move": input_tokens_per_move,
        "assumed_output_tokens_per_move": output_tokens_per_move,
        "assumed_cached_input": 0,
        "input_cost_usd": round(input_cost, 4),
        "output_cost_usd": round(output_cost, 4),
        "total_cost_usd": round(input_cost + output_cost, 4),
        "pricing_source": pricing.source,
        "pricing_verified_at": pricing.verified_at,
    }
