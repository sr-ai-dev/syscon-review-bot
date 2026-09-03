import asyncio
from datetime import date
from decimal import Decimal

import pytest

from src.review.cost import (
    GPT_5_6_TERRA_PRICING,
    CostLedger,
    CostLimitExceeded,
    CostPolicy,
    ModelPricing,
    RequestLimitExceeded,
    UnknownModelPricing,
    calculate_usage_cost_nusd,
    estimate_preflight_nusd,
    estimate_request_ceiling_nusd,
    get_model_pricing,
)


def test_terra_pricing_is_versioned_and_effective_dated():
    pricing = GPT_5_6_TERRA_PRICING

    assert pricing.model == "gpt-5.6-terra"
    assert pricing.version
    assert isinstance(pricing.effective_from, date)
    assert pricing.uncached_input_nusd_per_token == 2_000
    assert pricing.cached_input_nusd_per_token == 200
    assert pricing.output_nusd_per_token == 12_000
    assert get_model_pricing("gpt-5.6-terra") is pricing


def test_unknown_model_has_no_implicit_fallback():
    with pytest.raises(UnknownModelPricing):
        get_model_pricing("some-future-model")


def test_usage_cost_uses_exact_integer_cached_discount():
    assert calculate_usage_cost_nusd(
        prompt_tokens=1_000,
        cached_tokens=250,
        completion_tokens=100,
        pricing=GPT_5_6_TERRA_PRICING,
    ) == 2_750_000


@pytest.mark.parametrize(
    "prompt,cached,completion",
    [(-1, 0, 0), (1, -1, 0), (1, 0, -1), (1, 2, 0), (True, 0, 0)],
)
def test_usage_cost_rejects_invalid_usage(prompt, cached, completion):
    with pytest.raises((TypeError, ValueError)):
        calculate_usage_cost_nusd(
            prompt_tokens=prompt,
            cached_tokens=cached,
            completion_tokens=completion,
            pricing=GPT_5_6_TERRA_PRICING,
        )


def test_request_ceiling_ignores_cache_and_rounds_margin_up():
    base = 3 * 2_000 + 2 * 12_000
    assert estimate_request_ceiling_nusd(
        3, 2, GPT_5_6_TERRA_PRICING, margin_bps=1_500
    ) == (base * 11_500 + 9_999) // 10_000


def test_preflight_applies_margin_after_summing_all_calls():
    assert estimate_preflight_nusd(
        [(3, 2), (7, 1)], GPT_5_6_TERRA_PRICING, margin_bps=1_500
    ) == ((10 * 2_000 + 3 * 12_000) * 11_500 + 9_999) // 10_000


def test_cost_policy_defaults_are_exact_and_strict():
    policy = CostPolicy()

    assert policy.enabled is True
    assert policy.hard_limit_usd == Decimal("1.00")
    assert policy.hard_limit_nusd == 1_000_000_000
    assert policy.warning_ratio == Decimal("0.80")
    assert policy.warning_nusd == 800_000_000
    assert policy.allowed_models == ("gpt-5.6-terra",)
    assert policy.max_requests_per_pr == 12
    assert policy.max_completion_tokens_per_call == 4096
    assert policy.max_tool_result_tokens_per_call == 4096
    assert policy.max_history_tokens == 12000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hard_limit_usd": 1.0},
        {"hard_limit_usd": "0"},
        {"warning_ratio": "1.01"},
        {"preflight_margin_bps": -1},
        {"preflight_margin_bps": 10_001},
        {"allowed_models": ()},
        {"max_requests_per_pr": True},
        {"max_completion_tokens_per_call": 0},
    ],
)
def test_cost_policy_rejects_ambiguous_or_invalid_values(kwargs):
    with pytest.raises((TypeError, ValueError)):
        CostPolicy(**kwargs)


async def test_ledger_reserves_and_reconciles_actual_usage():
    policy = CostPolicy(hard_limit_usd="0.01")
    ledger = CostLedger(policy, GPT_5_6_TERRA_PRICING)

    reservation = await ledger.reserve("call-1", 5_000_000)
    assert reservation.call_id == "call-1"
    assert ledger.reserved_nusd == 5_000_000
    assert ledger.remaining_nusd == 5_000_000

    reconciliation = await ledger.reconcile("call-1", 100, 25, 10)

    assert reconciliation.actual_nusd == 275_000
    assert reconciliation.usage_unknown is False
    assert ledger.actual_nusd == 275_000
    assert ledger.usage_unknown_nusd == 0
    assert ledger.reserved_nusd == 0
    assert ledger.remaining_nusd == 9_725_000


async def test_ledger_keeps_full_reservation_when_usage_is_unknown():
    ledger = CostLedger(CostPolicy(hard_limit_usd="0.01"), GPT_5_6_TERRA_PRICING)
    await ledger.reserve("failed-call", 4_000_000)

    result = await ledger.reconcile("failed-call", None, None, None)

    assert result.usage_unknown is True
    assert result.actual_nusd is None
    assert ledger.actual_nusd == 0
    assert ledger.usage_unknown_nusd == 4_000_000
    assert ledger.remaining_nusd == 6_000_000


async def test_ledger_reservation_check_is_atomic_under_contention():
    ledger = CostLedger(CostPolicy(hard_limit_usd="0.001"), GPT_5_6_TERRA_PRICING)

    results = await asyncio.gather(
        ledger.reserve("a", 600_000),
        ledger.reserve("b", 600_000),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, CostLimitExceeded) for item in results) == 1
    assert ledger.reserved_nusd == 600_000
    assert ledger.remaining_nusd == 400_000


async def test_ledger_requires_new_call_id_for_retry_and_known_reservation():
    ledger = CostLedger(CostPolicy(), GPT_5_6_TERRA_PRICING)
    await ledger.reserve("attempt-1", 10_000)
    await ledger.reconcile("attempt-1", None, None, None)

    with pytest.raises(ValueError, match="call_id"):
        await ledger.reserve("attempt-1", 10_000)
    with pytest.raises(KeyError):
        await ledger.reconcile("missing", 1, 0, 1)


async def test_actual_over_reservation_reduces_future_capacity():
    ledger = CostLedger(CostPolicy(hard_limit_usd="0.001"), GPT_5_6_TERRA_PRICING)
    await ledger.reserve("underestimated", 100_000)
    await ledger.reconcile("underestimated", 100, 0, 100)

    assert ledger.actual_nusd == 1_400_000
    assert ledger.remaining_nusd == -400_000
    with pytest.raises(CostLimitExceeded):
        await ledger.reserve("next", 1)


async def test_ledger_enforces_request_limit_including_failed_attempts():
    ledger = CostLedger(
        CostPolicy(max_requests_per_pr=1), GPT_5_6_TERRA_PRICING
    )
    await ledger.reserve("attempt-1", 10_000)
    await ledger.reconcile("attempt-1", None, None, None)

    with pytest.raises(RequestLimitExceeded):
        await ledger.reserve("attempt-2", 10_000)


async def test_partial_usage_is_invalid_and_keeps_reservation_active():
    ledger = CostLedger(CostPolicy(), GPT_5_6_TERRA_PRICING)
    await ledger.reserve("call", 10_000)

    with pytest.raises(ValueError, match="all be present"):
        await ledger.reconcile("call", 1, None, 1)

    assert ledger.reserved_nusd == 10_000
    assert ledger.usage_unknown_nusd == 0


def test_custom_pricing_validates_model_and_rates():
    with pytest.raises(ValueError):
        ModelPricing(
            model="",
            effective_from=date(2026, 1, 1),
            version="v1",
            uncached_input_nusd_per_token=1,
            cached_input_nusd_per_token=1,
            output_nusd_per_token=1,
        )
