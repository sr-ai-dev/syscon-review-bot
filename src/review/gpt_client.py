import asyncio
import json
from uuid import uuid4

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.models.review import ReviewResult
from src.models.review_pipeline import ReviewPartial
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.review.llm_tools import TOOL_SCHEMAS, dispatch_tool_call
from src.review.structured_output import REVIEW_PARTIAL_RESPONSE_FORMAT, REVIEW_RESPONSE_FORMAT
from src.review.tool_executor import ToolExecutor
from src.review.cost import CostLedger, estimate_request_ceiling_nusd
from src.review.token_counter import count_tokens


RETRYABLE_OPENAI_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class GPTClient:
    def __init__(self, api_key: str, model: str = "gpt-5.4-mini"):
        self._client = AsyncOpenAI(api_key=api_key)
        self._default_model = model

    @property
    def default_model(self) -> str:
        return self._default_model

    @retry(
        retry=retry_if_exception_type(RETRYABLE_OPENAI_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _call_openai(self, **kwargs):
        return await self._client.chat.completions.create(**kwargs)

    async def _request(self, **kwargs):
        try:
            return await self._call_openai(**kwargs)
        except openai.OpenAIError as exc:
            raise ReviewInfraError(
                ReviewInfraCategory.OPENAI_TRANSPORT_ERROR,
                "OpenAI request failed after the configured retry policy",
            ) from exc

    async def _metered_request(
        self,
        *,
        cost_ledger: CostLedger | None,
        cost_stage: str,
        max_completion_tokens: int | None,
        pre_reserved_call_id: str | None = None,
        **kwargs,
    ):
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = max_completion_tokens
        if cost_ledger is None:
            return await self._request(**kwargs)

        input_tokens = count_tokens(
            json.dumps(kwargs, ensure_ascii=False, separators=(",", ":"), default=str)
        )
        output_tokens = max_completion_tokens or cost_ledger.policy.max_completion_tokens_per_call
        ceiling = estimate_request_ceiling_nusd(
            input_tokens,
            output_tokens,
            cost_ledger.pricing,
            margin_bps=cost_ledger.policy.preflight_margin_bps,
        )
        response = None
        for attempt in range(3):
            if attempt == 0 and pre_reserved_call_id is not None:
                call_id = pre_reserved_call_id
                await cost_ledger.require_reservation(call_id, ceiling)
            else:
                call_id = f"{cost_stage}:attempt-{attempt + 1}:{uuid4().hex}"
                await cost_ledger.reserve(call_id, ceiling)
            try:
                response = await self._client.chat.completions.create(**kwargs)
                break
            except asyncio.CancelledError:
                await cost_ledger.reconcile(call_id, None, None, None)
                raise
            except RETRYABLE_OPENAI_ERRORS as exc:
                await cost_ledger.reconcile(call_id, None, None, None)
                if attempt == 2:
                    raise ReviewInfraError(
                        ReviewInfraCategory.OPENAI_TRANSPORT_ERROR,
                        "OpenAI request failed after the configured retry policy",
                    ) from exc
                await asyncio.sleep(min(2 ** (attempt + 1), 30))
            except openai.OpenAIError as exc:
                await cost_ledger.reconcile(call_id, None, None, None)
                raise ReviewInfraError(
                    ReviewInfraCategory.OPENAI_TRANSPORT_ERROR,
                    "OpenAI request failed after the configured retry policy",
                ) from exc
            except BaseException:
                await cost_ledger.reconcile(call_id, None, None, None)
                raise

        if response is None:  # defensive; every branch above returns or raises
            raise RuntimeError("metered request ended without a response")

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(details, "cached_tokens", 0) if usage is not None else None
        if prompt_tokens is None or completion_tokens is None:
            prompt_tokens = cached_tokens = completion_tokens = None
        await cost_ledger.reconcile(
            call_id, prompt_tokens, cached_tokens, completion_tokens
        )
        return response

    async def review(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        tool_executor: ToolExecutor | None = None,
        reasoning_effort: str | None = None,
        max_completion_tokens: int | None = None,
        cost_ledger: CostLedger | None = None,
        cost_stage: str = "review",
        pre_reserved_call_id: str | None = None,
        response_model: type[BaseModel] = ReviewResult,
    ) -> BaseModel:
        chosen_model = model or self._default_model
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # reasoning_effort 사용 시 tool_executor 무시 (chat.completions API 제약)
        use_tools = tool_executor is not None and reasoning_effort is None
        if use_tools and (cost_ledger is None or not cost_ledger.policy.enabled):
            raise ValueError(
                "an enabled cost_ledger is required when repository tools are enabled"
            )
        response_format = (
            REVIEW_PARTIAL_RESPONSE_FORMAT
            if response_model is ReviewPartial
            else REVIEW_RESPONSE_FORMAT
        )

        if not use_tools:
            kwargs = {
                "model": chosen_model,
                "messages": messages,
                "response_format": response_format,
            }
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            else:
                kwargs["temperature"] = 0.1
            response = await self._metered_request(
                cost_ledger=cost_ledger,
                cost_stage=cost_stage,
                max_completion_tokens=max_completion_tokens,
                pre_reserved_call_id=pre_reserved_call_id,
                **kwargs,
            )
            return self._parse_final_response(response, response_model)

        tool_iteration = 0
        while True:
            tool_iteration += 1
            response = await self._metered_request(
                cost_ledger=cost_ledger,
                cost_stage=f"{cost_stage}:tool-{tool_iteration}",
                max_completion_tokens=max_completion_tokens,
                model=chosen_model,
                messages=messages,
                response_format=response_format,
                temperature=0.1,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                parallel_tool_calls=False,
                pre_reserved_call_id=(
                    pre_reserved_call_id if tool_iteration == 1 else None
                ),
            )
            choice, msg = self._choice_and_message(response)
            if not getattr(msg, "tool_calls", None):
                return self._parse_final_message(choice, msg, response_model)
            if len(msg.tool_calls) > 1:
                raise ReviewInfraError(
                    ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
                    "OpenAI returned multiple tool calls when parallel tools were disabled",
                )

            messages.append({
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                result_text = await dispatch_tool_call(
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}},
                    tool_executor,
                    max_tokens=(
                        cost_ledger.policy.max_tool_result_tokens_per_call
                        if cost_ledger is not None
                        else None
                    ),
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

    @staticmethod
    def _choice_and_message(response):
        choices = getattr(response, "choices", None)
        if not choices:
            raise ReviewInfraError(
                ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
                "OpenAI returned no review choice",
            )
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise ReviewInfraError(
                ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
                "OpenAI returned no review message",
            )
        return choice, message

    def _parse_final_response(
        self, response, response_model: type[BaseModel] = ReviewResult
    ) -> BaseModel:
        choice, message = self._choice_and_message(response)
        return self._parse_final_message(choice, message, response_model)

    def _parse_final_message(
        self, choice, message, response_model: type[BaseModel] = ReviewResult
    ) -> BaseModel:
        refusal = getattr(message, "refusal", None)
        if isinstance(refusal, str) and refusal:
            raise ReviewInfraError(
                ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
                "OpenAI refused to produce a review",
            )

        finish_reason = getattr(choice, "finish_reason", None)
        if isinstance(finish_reason, str) and finish_reason != "stop":
            raise ReviewInfraError(
                ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
                "OpenAI did not complete the review response",
            )

        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ReviewInfraError(
                ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
                "OpenAI returned no review content",
            )
        return self._parse(content, response_model)

    def _parse(
        self, content: str, response_model: type[BaseModel] = ReviewResult
    ) -> BaseModel:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ReviewInfraError(
                ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
                "Review response was not valid JSON",
            ) from exc
        if not isinstance(data, dict):
            raise ReviewInfraError(
                ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
                "Review response did not contain a JSON object",
            )
        if response_model is ReviewResult:
            self._normalize_prior_resolved(data)
        try:
            return response_model(**data)
        except ValidationError as exc:
            raise ReviewInfraError(
                ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
                "Review response did not match the required schema",
            ) from exc

    @staticmethod
    def _normalize_prior_resolved(data: dict) -> None:
        prior_resolved = data.get("prior_resolved")
        if not isinstance(prior_resolved, list):
            return

        normalized: list[object] = []
        for entry in prior_resolved:
            if isinstance(entry, str):
                normalized.append(entry)
            elif isinstance(entry, dict):
                normalized.extend(f"{key} → {value}" for key, value in entry.items())
            else:
                normalized.append(entry)
        data["prior_resolved"] = normalized
