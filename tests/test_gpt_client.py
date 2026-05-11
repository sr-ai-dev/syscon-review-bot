import json
import pytest
import openai
from unittest.mock import AsyncMock, patch

from src.review.gpt_client import GPTClient
from src.models.review import ReviewResult, Decision


MOCK_GPT_RESPONSE = json.dumps({
    "score": 8,
    "summary": "Overall clean",
    "decision": "comment",
    "issues": [
        {
            "severity": "warning",
            "category": "code_quality",
            "file": "src/main.py",
            "line": 10,
            "description": "Duplicated logic",
            "suggestion": "Extract helper",
        }
    ],
    "good_points": ["Good naming"],
})


@pytest.fixture(autouse=True)
def fast_retry():
    """Make tenacity retry sleeps instant for fast tests."""
    async def no_sleep(*args, **kwargs):
        return None
    GPTClient._call_openai.retry.sleep = no_sleep
    yield


@pytest.fixture
def client():
    return GPTClient(api_key="test", model="gpt-5.4-mini")


class TestGPTClient:
    @pytest.mark.asyncio
    async def test_review_returns_review_result(self, client):
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = MOCK_GPT_RESPONSE

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ):
            result = await client.review("sys", "usr")

        assert isinstance(result, ReviewResult)
        assert result.score == 8
        assert result.decision == Decision.COMMENT

    @pytest.mark.asyncio
    async def test_invalid_json_raises_value_error(self, client):
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "not json"

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ):
            with pytest.raises(ValueError, match="Failed to parse"):
                await client.review("sys", "usr")

    @pytest.mark.asyncio
    async def test_model_override(self, client):
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = MOCK_GPT_RESPONSE

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ) as mock_create:
            await client.review("sys", "usr", model="gpt-5-mini")

        assert mock_create.call_args.kwargs["model"] == "gpt-5-mini"

    @pytest.mark.asyncio
    async def test_uses_default_model_when_no_override(self, client):
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = MOCK_GPT_RESPONSE

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ) as mock_create:
            await client.review("sys", "usr")

        assert mock_create.call_args.kwargs["model"] == "gpt-5.4-mini"


class TestGPTClientRetry:
    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self, client):
        success = AsyncMock()
        success.choices = [AsyncMock()]
        success.choices[0].message.content = MOCK_GPT_RESPONSE

        rate_limit = openai.RateLimitError(
            message="rate limited",
            response=AsyncMock(status_code=429),
            body=None,
        )

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock,
            side_effect=[rate_limit, rate_limit, success],
        ) as mock_create:
            result = await client.review("sys", "usr")

        assert result.score == 8
        assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self, client):
        auth = openai.AuthenticationError(
            message="bad key",
            response=AsyncMock(status_code=401),
            body=None,
        )

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, side_effect=auth,
        ) as mock_create:
            with pytest.raises(openai.AuthenticationError):
                await client.review("sys", "usr")

        assert mock_create.call_count == 1
