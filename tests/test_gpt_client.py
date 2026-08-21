import json
import pytest
import openai
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.review.gpt_client import GPTClient
from src.models.review import ReviewResult, SpecStatus


MOCK_GPT_RESPONSE = json.dumps({
    "spec_status": "present",
    "aligned": False,
    "summary": "스펙 일부 누락",
    "mismatches": [
        {
            "file": "src/auth.py",
            "line": 12,
            "description": "스펙의 로그아웃 엔드포인트 누락",
            "suggestion": "POST /auth/logout 추가",
        }
    ],
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
        assert result.spec_status == SpecStatus.PRESENT
        assert result.aligned is False
        assert len(result.mismatches) == 1

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

        assert result.spec_status == SpecStatus.PRESENT
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


# ---------------------------------------------------------------------------
# Tool-use loop tests
# ---------------------------------------------------------------------------

def _mock_msg(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _mock_tool_call(id_, name, args):
    func = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=id_, type="function", function=func)


@pytest.mark.asyncio
async def test_tool_use_loop_dispatches_then_returns_final():
    gpt = GPTClient(api_key="x")
    call_counter = {"n": 0}

    async def fake_create(**kwargs):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            tc = _mock_tool_call("c1", "read_file", {"path": "a.py"})
            return _mock_msg(content=None, tool_calls=[tc])
        return _mock_msg(content=json.dumps({
            "spec_status": "present",
            "aligned": True,
            "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    executor = AsyncMock()
    executor.read_file.return_value = "file body"

    result = await gpt.review("sys", "usr", tool_executor=executor)

    assert call_counter["n"] == 2
    executor.read_file.assert_awaited_once_with("a.py")
    assert result.summary == "ok"


@pytest.mark.asyncio
async def test_tool_use_loop_respects_max_iterations():
    gpt = GPTClient(api_key="x")

    async def always_tool(**kwargs):
        tc = _mock_tool_call("c1", "read_file", {"path": "a.py"})
        return _mock_msg(content=None, tool_calls=[tc])

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=always_tool)

    executor = AsyncMock()
    executor.read_file.return_value = "x"

    with pytest.raises(ValueError, match="max_tool_iterations"):
        await gpt.review("sys", "usr", tool_executor=executor, max_tool_iterations=3)

    assert gpt._client.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_review_without_tool_executor_keeps_old_behavior():
    gpt = GPTClient(api_key="x")

    async def respond_json(**kwargs):
        assert "tools" not in kwargs
        return _mock_msg(content=json.dumps({
            "spec_status": "present", "aligned": True, "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=respond_json)

    result = await gpt.review("sys", "usr")
    assert result.summary == "ok"


def test_parse_extracts_last_json_when_reasoning_model_emits_extra():
    """Reasoning model이 응답 앞에 부수 텍스트/객체 출력해도 마지막 valid JSON 추출."""
    gpt = GPTClient(api_key="x")
    content = (
        '{"path":"a.py"}\n'
        '{"path":"b.py"}\n'
        '{"spec_status":"present","aligned":true,"summary":"ok"}'
    )
    result = gpt._parse(content)
    assert result.summary == "ok"
    assert result.aligned is True


def test_parse_handles_clean_json_unchanged():
    gpt = GPTClient(api_key="x")
    content = '{"spec_status":"present","aligned":true,"summary":"clean"}'
    result = gpt._parse(content)
    assert result.summary == "clean"


def test_parse_normalizes_object_prior_resolved_to_human_readable_string():
    gpt = GPTClient(api_key="x")
    content = json.dumps({
        "spec_status": "present",
        "aligned": True,
        "summary": "normalized",
        "prior_resolved": [{"(부분) 기존 지적": "일부 수정, 남은 문제는 아래 참조"}],
    })

    result = gpt._parse(content)

    assert result.prior_resolved == ["(부분) 기존 지적 → 일부 수정, 남은 문제는 아래 참조"]


def test_parse_raises_on_no_valid_json():
    gpt = GPTClient(api_key="x")
    with pytest.raises(ValueError, match="Failed to parse"):
        gpt._parse("not json at all just text")


# ---------------------------------------------------------------------------
# reasoning_effort tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_review_passes_reasoning_effort_and_strips_temperature():
    gpt = GPTClient(api_key="x")
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _mock_msg(content=json.dumps({
            "spec_status": "present", "aligned": True, "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    await gpt.review("sys", "usr", reasoning_effort="high")

    assert captured.get("reasoning_effort") == "high"
    assert "temperature" not in captured


@pytest.mark.asyncio
async def test_reasoning_ignores_tool_executor():
    """reasoning_effort 사용 시 tool_executor는 무시 (chat completions 한계)."""
    gpt = GPTClient(api_key="x")
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _mock_msg(content=json.dumps({
            "spec_status": "present", "aligned": True, "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    executor = AsyncMock()
    await gpt.review("sys", "usr", reasoning_effort="high", tool_executor=executor)

    # tools 키워드 전달 안 됨
    assert "tools" not in captured
    # executor 도구 호출 안 됨
    executor.read_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_no_reasoning_keeps_temperature():
    gpt = GPTClient(api_key="x")
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _mock_msg(content=json.dumps({
            "spec_status": "present", "aligned": True, "summary": "ok",
        }))

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=fake_create)

    await gpt.review("sys", "usr")

    assert captured.get("temperature") == 0.1
    assert "reasoning_effort" not in captured
