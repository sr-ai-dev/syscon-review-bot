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
    async def _call_openai(self, model: str, system_prompt: str, user_prompt: str):
        return await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

    async def review(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> ReviewResult:
        chosen_model = model or self._default_model
        response = await self._call_openai(chosen_model, system_prompt, user_prompt)

        content = response.choices[0].message.content
        try:
            data = json.loads(content)
            return ReviewResult(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Failed to parse GPT response: {e}\nContent: {content}")
