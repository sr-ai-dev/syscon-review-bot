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
from src.review.llm_tools import TOOL_SCHEMAS, dispatch_tool_call
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
                "response_format": {"type": "json_object"},
            }
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            else:
                kwargs["temperature"] = 0.1
            response = await self._call_openai(**kwargs)
            return self._parse(response.choices[0].message.content)

        for _ in range(max_tool_iterations):
            response = await self._call_openai(
                model=chosen_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
            msg = response.choices[0].message
            if not getattr(msg, "tool_calls", None):
                return self._parse(msg.content)

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

        raise ValueError(
            f"GPT exhausted max_tool_iterations={max_tool_iterations} without producing a final response"
        )

    def _parse(self, content: str) -> ReviewResult:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = self._extract_last_json_object(content)
        self._normalize_prior_resolved(data)
        try:
            return ReviewResult(**data)
        except ValidationError as e:
            raise ValueError(f"Failed to parse GPT response: {e}\nContent: {content}")

    @staticmethod
    def _normalize_prior_resolved(data: dict) -> None:
        prior_resolved = data.get("prior_resolved")
        if not isinstance(prior_resolved, list):
            return

        normalized: list[str] = []
        for entry in prior_resolved:
            if isinstance(entry, str):
                normalized.append(entry)
            elif isinstance(entry, dict):
                normalized.extend(f"{key} → {value}" for key, value in entry.items())
            else:
                normalized.append(str(entry))
        data["prior_resolved"] = normalized

    @staticmethod
    def _extract_last_json_object(text: str) -> dict:
        """Stream에 여러 JSON 객체가 있으면 마지막 객체 반환 (reasoning 모델이 부수 출력하는 경우)."""
        decoder = json.JSONDecoder()
        pos = 0
        last = None
        n = len(text)
        while pos < n:
            while pos < n and text[pos].isspace():
                pos += 1
            if pos >= n:
                break
            try:
                obj, end = decoder.raw_decode(text, pos)
                if isinstance(obj, dict):
                    last = obj
                pos = end
            except json.JSONDecodeError:
                pos += 1
        if last is None:
            raise ValueError(f"Failed to parse GPT response: no JSON object found\nContent: {text}")
        return last
