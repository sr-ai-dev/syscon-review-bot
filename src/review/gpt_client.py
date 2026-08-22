import json

import openai
from openai import AsyncOpenAI
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.models.review import ReviewResult
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.review.llm_tools import TOOL_SCHEMAS, dispatch_tool_call
from src.review.structured_output import REVIEW_RESPONSE_FORMAT
from src.review.tool_executor import ToolExecutor


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

    async def review(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        tool_executor: ToolExecutor | None = None,
        max_tool_iterations: int = 8,
        reasoning_effort: str | None = None,
    ) -> ReviewResult:
        chosen_model = model or self._default_model
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # reasoning_effort 사용 시 tool_executor 무시 (chat.completions API 제약)
        use_tools = tool_executor is not None and reasoning_effort is None

        if not use_tools:
            kwargs = {
                "model": chosen_model,
                "messages": messages,
                "response_format": REVIEW_RESPONSE_FORMAT,
            }
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            else:
                kwargs["temperature"] = 0.1
            response = await self._request(**kwargs)
            return self._parse_final_response(response)

        for _ in range(max_tool_iterations):
            response = await self._request(
                model=chosen_model,
                messages=messages,
                response_format=REVIEW_RESPONSE_FORMAT,
                temperature=0.1,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
            choice, msg = self._choice_and_message(response)
            if not getattr(msg, "tool_calls", None):
                return self._parse_final_message(choice, msg)

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
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        raise ReviewInfraError(
            ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE,
            "OpenAI did not produce a final review within the tool iteration limit",
        )

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

    def _parse_final_response(self, response) -> ReviewResult:
        choice, message = self._choice_and_message(response)
        return self._parse_final_message(choice, message)

    def _parse_final_message(self, choice, message) -> ReviewResult:
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
        return self._parse(content)

    def _parse(self, content: str) -> ReviewResult:
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
        self._normalize_prior_resolved(data)
        try:
            return ReviewResult(**data)
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
