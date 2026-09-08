"""Cost accounting must be auditable and must never double count reasoning."""

from __future__ import annotations

import json

import pytest

from bzbench.pricing import (
    BudgetExceeded,
    CostLedger,
    Pricing,
    PricingError,
    cost_of,
    estimate_game_cost,
    extract_usage,
)

PRICING = Pricing.for_model("gpt-6-astra")


def usage(**kwargs):
    raw = {
        "input_tokens": kwargs.get("input_tokens", 0),
        "input_tokens_details": {"cached_tokens": kwargs.get("cached", 0)},
        "output_tokens": kwargs.get("output_tokens", 0),
        "output_tokens_details": {"reasoning_tokens": kwargs.get("reasoning", None)},
        "total_tokens": kwargs.get(
            "total", kwargs.get("input_tokens", 0) + kwargs.get("output_tokens", 0)
        ),
    }
    return extract_usage(raw)


# ------------------------------------------------------------- the file


def test_the_shipped_pricing_file_is_complete_and_sourced():
    assert PRICING.model == "gpt-6-astra"
    assert PRICING.input_per_mtok == 10.0
    assert PRICING.cached_input_per_mtok == 1.0
    assert PRICING.output_per_mtok == 50.0
    assert PRICING.long_context_threshold_tokens == 272_000
    assert PRICING.source.startswith("https://")
    assert PRICING.verified_at.endswith("Z")
    assert any("billed as output" in note for note in PRICING.notes)


def test_a_pricing_file_without_provenance_is_rejected():
    with pytest.raises(PricingError):
        Pricing.from_dict({"model": "x", "standard": {"input": 1, "cached_input": 0,
                                                      "output": 2}})
    with pytest.raises(PricingError):
        Pricing.from_dict({
            "model": "x", "standard": {"input": 1, "cached_input": 0, "output": 2},
            "verified_at": "not-a-date", "source": "https://example.com",
        })
    with pytest.raises(PricingError):
        Pricing.from_dict({
            "model": "x", "standard": {"input": 1, "cached_input": 0, "output": 2},
            "verified_at": "2026-09-08T00:00:00Z", "source": "hearsay",
        })


def test_missing_pricing_for_a_model_is_an_error_not_a_guess():
    with pytest.raises(PricingError):
        Pricing.for_model("gpt-7-nonexistent")


# ------------------------------------------------------------- the maths


def test_reasoning_tokens_are_not_charged_on_top_of_output_tokens():
    with_reasoning = cost_of(
        usage(input_tokens=1000, output_tokens=5000, reasoning=4900), PRICING
    )
    without_reasoning = cost_of(
        usage(input_tokens=1000, output_tokens=5000, reasoning=None), PRICING
    )
    assert with_reasoning.total_cost_usd == without_reasoning.total_cost_usd
    assert with_reasoning.output_cost_usd == pytest.approx(5000 * 50 / 1e6)
    assert with_reasoning.total_cost_usd == pytest.approx(
        with_reasoning.input_cost_usd + with_reasoning.output_cost_usd
    )
    # The reasoning share is reported for information, never added.
    assert with_reasoning.reasoning_cost_share_usd == pytest.approx(4900 * 50 / 1e6)
    assert with_reasoning.reasoning_included_in_output_cost is True


def test_cached_input_is_charged_at_the_cached_rate_and_only_once():
    cost = cost_of(usage(input_tokens=1000, cached=400, output_tokens=0), PRICING)
    assert cost.uncached_input_tokens == 600
    assert cost.input_cost_usd == pytest.approx((600 * 10 + 400 * 1) / 1e6)


def test_cached_tokens_cannot_exceed_input_tokens():
    cost = cost_of(usage(input_tokens=100, cached=500), PRICING)
    assert cost.cached_input_tokens == 100
    assert cost.uncached_input_tokens == 0


def test_long_context_requests_use_the_long_context_rates():
    short = cost_of(usage(input_tokens=272_000, output_tokens=1000), PRICING)
    long = cost_of(usage(input_tokens=272_001, output_tokens=1000), PRICING)
    assert short.long_context is False
    assert long.long_context is True
    assert long.input_cost_usd > short.input_cost_usd
    assert long.output_cost_usd == pytest.approx(1000 * 75 / 1e6)


def test_missing_usage_fields_are_reported_as_none_not_zero():
    extracted = extract_usage({"input_tokens": 10, "output_tokens": 5})
    assert extracted["reasoning_tokens"] is None
    assert extracted["cached_input_tokens"] is None
    assert extract_usage(None)["total_tokens"] is None


# ------------------------------------------------------------ the ledger


def test_ledger_accumulates_and_guards_on_cost():
    ledger = CostLedger(pricing=PRICING, max_cost_usd=1.0)
    ledger.check_before_request()
    ledger.add(usage(input_tokens=100_000, output_tokens=0))  # exactly $1.00
    with pytest.raises(BudgetExceeded) as exc:
        ledger.check_before_request()
    assert exc.value.kind == "cost"
    assert ledger.total_cost_usd == pytest.approx(1.0)


def test_ledger_guards_on_tokens():
    ledger = CostLedger(pricing=PRICING, max_total_tokens=1000)
    ledger.add(usage(input_tokens=600, output_tokens=400))
    with pytest.raises(BudgetExceeded) as exc:
        ledger.check_before_request()
    assert exc.value.kind == "tokens"


def test_ledger_summary_is_serialisable_and_carries_provenance():
    ledger = CostLedger(pricing=PRICING, max_cost_usd=15.0)
    ledger.add(usage(input_tokens=1000, output_tokens=2000, reasoning=1500))
    summary = ledger.summary()
    assert summary["reasoning_tokens"] == 1500
    assert summary["reasoning_included_in_output_cost"] is True
    assert summary["max_cost_usd"] == 15.0
    assert summary["pricing"]["verified_at"] == PRICING.verified_at
    json.dumps(summary)


def test_ledger_reports_none_when_the_api_never_exposed_reasoning_tokens():
    ledger = CostLedger(pricing=PRICING)
    ledger.add(usage(input_tokens=10, output_tokens=10, reasoning=None))
    assert ledger.summary()["reasoning_tokens"] is None


# ---------------------------------------------------------- the estimate


def test_upper_bound_estimate_assumes_no_caching():
    estimate = estimate_game_cost(
        PRICING, moves=60, input_tokens_per_move=2000, output_tokens_per_move=6000
    )
    assert estimate["assumed_cached_input"] == 0
    assert estimate["input_cost_usd"] == pytest.approx(60 * 2000 * 10 / 1e6)
    assert estimate["output_cost_usd"] == pytest.approx(60 * 6000 * 50 / 1e6)
    assert estimate["total_cost_usd"] == pytest.approx(
        estimate["input_cost_usd"] + estimate["output_cost_usd"]
    )
    assert estimate["pricing_source"] == PRICING.source
