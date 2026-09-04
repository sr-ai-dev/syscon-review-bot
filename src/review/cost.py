"""Exact pricing, preflight estimation, and per-PR cost accounting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Iterable


NANO_USD_PER_USD = 1_000_000_000
_BASIS_POINTS = 10_000


class UnknownModelPricing(LookupError):
    """Raised when cost control has no trusted price for a model."""


class CostLimitExceeded(RuntimeError):
    """Raised when a reservation would exceed the per-PR hard limit."""

    def __init__(self, requested_nusd: int, available_nusd: int):
        self.requested_nusd = requested_nusd
        self.available_nusd = available_nusd
        super().__init__(
            "cost reservation exceeds hard limit: "
            f"requested={requested_nusd} nUSD, available={available_nusd} nUSD"
        )


class ReservationInvariantExceeded(CostLimitExceeded):
    """Actual provider usage exceeded the reserved worst-case envelope.

    The request has already been charged, so reconciliation records the actual
    spend before raising. Callers must stop new work; they cannot undo the
    overrun by retaining only the smaller reservation.
    """

    def __init__(self, reserved_nusd: int, actual_nusd: int):
        self.reserved_nusd = reserved_nusd
        self.actual_nusd = actual_nusd
        super().__init__(actual_nusd, reserved_nusd)
        self.args = (
            "actual usage exceeded worst-case reservation: "
            f"actual={actual_nusd} nUSD, reserved={reserved_nusd} nUSD",
        )


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_int(value: object, name: str) -> int:
    result = _nonnegative_int(value, name)
    if result == 0:
        raise ValueError(f"{name} must be positive")
    return result


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{name} must be a string, integer, or Decimal")
    if not isinstance(value, (str, int, Decimal)):
        raise TypeError(f"{name} must be a string, integer, or Decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return result


@dataclass(frozen=True, slots=True)
class ModelPricing:
    model: str
    effective_from: date
    version: str
    uncached_input_nusd_per_token: int
    cached_input_nusd_per_token: int
    output_nusd_per_token: int

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be a non-empty string")
        if not isinstance(self.effective_from, date):
            raise TypeError("effective_from must be a date")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version must be a non-empty string")
        for field_name in (
            "uncached_input_nusd_per_token",
            "cached_input_nusd_per_token",
            "output_nusd_per_token",
        ):
            _positive_int(getattr(self, field_name), field_name)
        if self.cached_input_nusd_per_token > self.uncached_input_nusd_per_token:
            raise ValueError("cached input price cannot exceed uncached input price")


GPT_5_4_MINI_PRICING = ModelPricing(
    model="gpt-5.4-mini",
    effective_from=date(2026, 9, 4),
    version="2026-09-04",
    uncached_input_nusd_per_token=750,
    cached_input_nusd_per_token=75,
    output_nusd_per_token=4_500,
)

MODEL_PRICING: dict[str, ModelPricing] = {
    GPT_5_4_MINI_PRICING.model: GPT_5_4_MINI_PRICING,
}


def get_model_pricing(model: str) -> ModelPricing:
    try:
        return MODEL_PRICING[model]
    except KeyError as exc:
        raise UnknownModelPricing(f"no trusted pricing for model: {model}") from exc


def calculate_usage_cost_nusd(
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
    pricing: ModelPricing,
) -> int:
    """Calculate actual cost from API usage without floating point arithmetic."""

    prompt = _nonnegative_int(prompt_tokens, "prompt_tokens")
    cached = _nonnegative_int(cached_tokens, "cached_tokens")
    completion = _nonnegative_int(completion_tokens, "completion_tokens")
    if cached > prompt:
        raise ValueError("cached_tokens cannot exceed prompt_tokens")
    return (
        (prompt - cached) * pricing.uncached_input_nusd_per_token
        + cached * pricing.cached_input_nusd_per_token
        + completion * pricing.output_nusd_per_token
    )


def _with_margin(cost_nusd: int, margin_bps: int) -> int:
    margin = _nonnegative_int(margin_bps, "margin_bps")
    numerator = cost_nusd * (_BASIS_POINTS + margin)
    return (numerator + _BASIS_POINTS - 1) // _BASIS_POINTS


def estimate_request_ceiling_nusd(
    input_tokens: int,
    output_tokens: int,
    pricing: ModelPricing,
    margin_bps: int = 0,
) -> int:
    """Estimate one request conservatively; all input is charged uncached."""

    input_count = _nonnegative_int(input_tokens, "input_tokens")
    output_count = _nonnegative_int(output_tokens, "output_tokens")
    base = (
        input_count * pricing.uncached_input_nusd_per_token
        + output_count * pricing.output_nusd_per_token
    )
    return _with_margin(base, margin_bps)


def estimate_preflight_nusd(
    requests: Iterable[tuple[int, int]],
    pricing: ModelPricing,
    margin_bps: int = 1_500,
) -> int:
    """Estimate a complete plan, applying its margin once after summation."""

    total = 0
    for index, request in enumerate(requests):
        try:
            input_tokens, output_tokens = request
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"request {index} must contain input and output token counts"
            ) from exc
        total += estimate_request_ceiling_nusd(
            input_tokens, output_tokens, pricing, margin_bps=0
        )
    return _with_margin(total, margin_bps)


@dataclass(frozen=True, slots=True)
class CostPolicy:
    enabled: bool = True
    hard_limit_usd: Decimal | str | int = Decimal("1.00")
    warning_ratio: Decimal | str | int = Decimal("0.80")
    preflight_margin_bps: int = 1_500
    allowed_models: tuple[str, ...] = ("gpt-5.4-mini",)
    max_completion_tokens_per_call: int = 4096
    max_tool_result_tokens_per_call: int = 4096
    max_history_tokens: int = 12000
    hard_limit_nusd: int = field(init=False)
    warning_nusd: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")

        hard_limit = _decimal(self.hard_limit_usd, "hard_limit_usd")
        if hard_limit <= 0:
            raise ValueError("hard_limit_usd must be positive")
        if hard_limit > Decimal("1.00"):
            raise ValueError("hard_limit_usd cannot exceed 1.00")
        hard_limit_nusd_decimal = hard_limit * NANO_USD_PER_USD
        if hard_limit_nusd_decimal != hard_limit_nusd_decimal.to_integral_value():
            raise ValueError("hard_limit_usd cannot have precision below one nano-USD")

        warning_ratio = _decimal(self.warning_ratio, "warning_ratio")
        if warning_ratio < 0 or warning_ratio > 1:
            raise ValueError("warning_ratio must be between 0 and 1")

        margin = _nonnegative_int(self.preflight_margin_bps, "preflight_margin_bps")
        if margin > _BASIS_POINTS:
            raise ValueError("preflight_margin_bps cannot exceed 10000")

        if isinstance(self.allowed_models, str):
            raise TypeError("allowed_models must be a sequence of model names")
        models = tuple(self.allowed_models)
        if not models or any(not isinstance(item, str) or not item for item in models):
            raise ValueError("allowed_models must contain non-empty model names")
        if len(models) != len(set(models)):
            raise ValueError("allowed_models cannot contain duplicates")

        for field_name in (
            "max_completion_tokens_per_call",
            "max_tool_result_tokens_per_call",
            "max_history_tokens",
        ):
            _positive_int(getattr(self, field_name), field_name)

        hard_nusd = int(hard_limit_nusd_decimal)
        warning_nusd = int(
            (Decimal(hard_nusd) * warning_ratio).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        object.__setattr__(self, "hard_limit_usd", hard_limit)
        object.__setattr__(self, "warning_ratio", warning_ratio)
        object.__setattr__(self, "preflight_margin_bps", margin)
        object.__setattr__(self, "allowed_models", models)
        object.__setattr__(self, "hard_limit_nusd", hard_nusd)
        object.__setattr__(self, "warning_nusd", warning_nusd)

    def pricing_for(self, model: str) -> ModelPricing:
        if model not in self.allowed_models:
            raise UnknownModelPricing(f"model is not allowed by cost policy: {model}")
        return get_model_pricing(model)

    def restricted_by(self, repository_policy: object | None) -> CostPolicy:
        """Apply only repository-owned limits that are stricter than this policy."""

        if repository_policy is None:
            return self

        def narrower(field_name: str, trusted_value):
            candidate = getattr(repository_policy, field_name, None)
            return trusted_value if candidate is None else min(trusted_value, candidate)

        return CostPolicy(
            enabled=self.enabled,
            hard_limit_usd=narrower("hard_limit_usd", self.hard_limit_usd),
            warning_ratio=self.warning_ratio,
            preflight_margin_bps=self.preflight_margin_bps,
            allowed_models=self.allowed_models,
            max_completion_tokens_per_call=narrower(
                "max_completion_tokens_per_call",
                self.max_completion_tokens_per_call,
            ),
            max_tool_result_tokens_per_call=narrower(
                "max_tool_result_tokens_per_call",
                self.max_tool_result_tokens_per_call,
            ),
            max_history_tokens=narrower(
                "max_history_tokens", self.max_history_tokens
            ),
        )


@dataclass(frozen=True, slots=True)
class CostReservation:
    call_id: str
    worst_case_nusd: int


@dataclass(frozen=True, slots=True)
class CostReconciliation:
    call_id: str
    reserved_nusd: int
    actual_nusd: int | None
    usage_unknown: bool


class CostLedger:
    """Concurrency-safe cost ledger shared by every reviewer for one PR."""

    def __init__(self, policy: CostPolicy, pricing: ModelPricing):
        if pricing.model not in policy.allowed_models:
            raise UnknownModelPricing(
                f"model is not allowed by cost policy: {pricing.model}"
            )
        self.policy = policy
        self.pricing = pricing
        self._lock = asyncio.Lock()
        self._reservations: dict[str, int] = {}
        self._finalized_call_ids: set[str] = set()
        self._actual_nusd = 0
        self._usage_unknown_nusd = 0

    @property
    def actual_nusd(self) -> int:
        return self._actual_nusd

    @property
    def usage_unknown_nusd(self) -> int:
        return self._usage_unknown_nusd

    @property
    def reserved_nusd(self) -> int:
        return sum(self._reservations.values())

    @property
    def committed_nusd(self) -> int:
        return self.actual_nusd + self.usage_unknown_nusd + self.reserved_nusd

    @property
    def remaining_nusd(self) -> int:
        return self.policy.hard_limit_nusd - self.committed_nusd

    async def reserve(self, call_id: str, worst_case_nusd: int) -> CostReservation:
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("call_id must be a non-empty string")
        requested = _nonnegative_int(worst_case_nusd, "worst_case_nusd")
        async with self._lock:
            if call_id in self._reservations or call_id in self._finalized_call_ids:
                raise ValueError(f"call_id has already been used: {call_id}")
            available = self.remaining_nusd
            if self.policy.enabled and requested > available:
                error = CostLimitExceeded(requested, available)
                error.accounted_nusd = self.actual_nusd + self.usage_unknown_nusd
                raise error
            self._reservations[call_id] = requested
            return CostReservation(call_id, requested)

    async def require_reservation(
        self, call_id: str, minimum_nusd: int
    ) -> CostReservation:
        """Validate that a planned reservation covers a request before sending it."""

        required = _nonnegative_int(minimum_nusd, "minimum_nusd")
        async with self._lock:
            if call_id not in self._reservations:
                raise KeyError(f"no active reservation for call_id: {call_id}")
            reserved = self._reservations[call_id]
            if required > reserved:
                raise CostLimitExceeded(required, reserved)
            return CostReservation(call_id, reserved)

    async def cancel_reservation(self, call_id: str, *, missing_ok: bool = False) -> int:
        """Release a planned reservation when its request was never sent."""

        async with self._lock:
            if call_id not in self._reservations:
                if missing_ok:
                    return 0
                raise KeyError(f"no active reservation for call_id: {call_id}")
            return self._reservations.pop(call_id)

    async def reconcile(
        self,
        call_id: str,
        prompt_tokens: int | None,
        cached_tokens: int | None,
        completion_tokens: int | None,
    ) -> CostReconciliation:
        async with self._lock:
            if call_id not in self._reservations:
                raise KeyError(f"no active reservation for call_id: {call_id}")
            reserved = self._reservations[call_id]
            usage = (prompt_tokens, cached_tokens, completion_tokens)
            if any(item is None for item in usage) and not all(
                item is None for item in usage
            ):
                raise ValueError("usage fields must all be present or all be absent")
            if all(item is None for item in usage):
                self._reservations.pop(call_id)
                self._finalized_call_ids.add(call_id)
                self._usage_unknown_nusd += reserved
                return CostReconciliation(call_id, reserved, None, True)

            actual = calculate_usage_cost_nusd(
                prompt_tokens,
                cached_tokens,
                completion_tokens,
                self.pricing,
            )
            self._reservations.pop(call_id)
            self._finalized_call_ids.add(call_id)
            self._actual_nusd += actual
            if actual > reserved:
                error = ReservationInvariantExceeded(reserved, actual)
                error.accounted_nusd = self.actual_nusd + self.usage_unknown_nusd
                raise error
            return CostReconciliation(call_id, reserved, actual, False)
