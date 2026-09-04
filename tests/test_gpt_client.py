import json
import pytest
import openai
import httpx
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.review.gpt_client import GPTClient
from src.models.review import ReviewResult, SpecStatus
from src.models.review_pipeline import ReviewPartial
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.review.cost import (
    CostLedger,
    CostLimitExceeded,
    CostPolicy,
    GPT_5_4_MINI_PRICING,
)


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
    async def test_internal_review_partial_uses_strict_schema_and_parses_coverage(self):
        gpt = GPTClient(api_key="x")
        payload = json.dumps(
            {
                "unit_id": "shard-1",
                "covered_paths": ["src/a.py"],
                "spec_status": "present",
                "aligned": True,
                "summary": "ok",
                "findings": [],
                "prior_resolved": [],
            }
        )
        response = _mock_msg(content=payload, finish_reason="stop")
        gpt._client = MagicMock()
        gpt._client.chat.completions.create = AsyncMock(return_value=response)

        result = await gpt.review(
            "sys", "usr", response_model=ReviewPartial
        )

        assert isinstance(result, ReviewPartial)
        assert result.covered_paths == ["src/a.py"]
        response_format = gpt._client.chat.completions.create.call_args.kwargs[
            "response_format"
        ]
        assert response_format["json_schema"]["name"] == "review_partial"
        assert response_format["json_schema"]["strict"] is True

    @pytest.mark.asyncio
    async def test_default_client_uses_gpt_5_4_mini(self):
        default_client = GPTClient(api_key="test")
        mock_response = _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop")

        with patch.object(
            default_client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ) as mock_create:
            await default_client.review("sys", "usr")

        assert mock_create.call_args.kwargs["model"] == "gpt-5.4-mini"

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
            with pytest.raises(ReviewInfraError) as exc_info:
                await client.review("sys", "usr")

        assert exc_info.value.category == ReviewInfraCategory.RESPONSE_SCHEMA_ERROR
        assert "not json" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_schema_mismatch_is_typed_without_leaking_content(self, client):
        raw_content = json.dumps({"summary": "sensitive response marker"})
        mock_response = _mock_msg(content=raw_content, finish_reason="stop")

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ):
            with pytest.raises(ReviewInfraError) as exc_info:
                await client.review("sys", "usr")

        assert exc_info.value.category == ReviewInfraCategory.RESPONSE_SCHEMA_ERROR
        assert "sensitive response marker" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_tool_review_uses_strict_schema_once(self, client):
        mock_response = _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop")

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_response,
        ) as mock_create:
            await client.review("sys", "usr")

        assert mock_create.await_count == 1
        response_format = mock_create.call_args.kwargs["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True

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
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            ),
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
            response=httpx.Response(
                401,
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            ),
            body=None,
        )

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, side_effect=auth,
        ) as mock_create:
            with pytest.raises(ReviewInfraError) as exc_info:
                await client.review("sys", "usr")

        assert exc_info.value.category == ReviewInfraCategory.OPENAI_TRANSPORT_ERROR
        assert "bad key" not in str(exc_info.value)
        assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_exhaustion_is_typed_transport_error(self, client):
        rate_limit = openai.RateLimitError(
            message="rate limited",
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            ),
            body=None,
        )

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, side_effect=rate_limit,
        ) as mock_create:
            with pytest.raises(ReviewInfraError) as exc_info:
                await client.review("sys", "usr")

        assert exc_info.value.category == ReviewInfraCategory.OPENAI_TRANSPORT_ERROR
        assert mock_create.call_count == 3


# ---------------------------------------------------------------------------
# Tool-use loop tests
# ---------------------------------------------------------------------------

def _mock_msg(content=None, tool_calls=None, finish_reason=None, refusal=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    if refusal is not None:
        msg.refusal = refusal
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)]
    )


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
    ledger = CostLedger(CostPolicy(), GPT_5_4_MINI_PRICING)

    result = await gpt.review(
        "sys", "usr", tool_executor=executor, cost_ledger=ledger
    )

    assert call_counter["n"] == 2
    executor.read_file.assert_awaited_once_with("a.py")
    assert result.summary == "ok"

    for call in gpt._client.chat.completions.create.await_args_list:
        response_format = call.kwargs["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_tool_use_loop_has_no_fixed_iteration_limit():
    gpt = GPTClient(api_key="x")
    call_counter = {"n": 0}

    async def nine_tools_then_final(**kwargs):
        call_counter["n"] += 1
        if call_counter["n"] <= 9:
            tc = _mock_tool_call(f"c{call_counter['n']}", "read_file", {"path": "a.py"})
            return _mock_msg(content=None, tool_calls=[tc])
        return _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop")

    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=nine_tools_then_final)

    executor = AsyncMock()
    executor.read_file.return_value = "x"
    ledger = CostLedger(CostPolicy(), GPT_5_4_MINI_PRICING)

    result = await gpt.review(
        "sys", "usr", tool_executor=executor, cost_ledger=ledger
    )

    assert result.summary == "스펙 일부 누락"
    assert gpt._client.chat.completions.create.await_count == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ledger",
    [None, CostLedger(CostPolicy(enabled=False), GPT_5_4_MINI_PRICING)],
)
async def test_tool_use_requires_enabled_cost_ledger(ledger):
    gpt = GPTClient(api_key="x")
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock()

    with pytest.raises(ValueError, match="cost_ledger"):
        await gpt.review(
            "sys", "usr", tool_executor=AsyncMock(), cost_ledger=ledger
        )

    gpt._client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_loop_stops_before_request_that_exceeds_cost_limit():
    gpt = GPTClient(api_key="x")
    tool_response = _mock_msg(
        content=None,
        tool_calls=[_mock_tool_call("c1", "read_file", {"path": "a.py"})],
    )
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(return_value=tool_response)
    executor = AsyncMock()
    executor.read_file.return_value = "x"
    ledger = CostLedger(CostPolicy(hard_limit_usd="0.03"), GPT_5_4_MINI_PRICING)

    with pytest.raises(CostLimitExceeded):
        await gpt.review(
            "sys",
            "usr",
            tool_executor=executor,
            cost_ledger=ledger,
            max_completion_tokens=4096,
        )

    assert gpt._client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_each_tool_turn_reserves_for_growing_message_payload():
    gpt = GPTClient(api_key="x")
    responses = [
        _mock_msg(
            content=None,
            tool_calls=[_mock_tool_call("c1", "read_file", {"path": "a.py"})],
        ),
        _mock_msg(
            content=None,
            tool_calls=[_mock_tool_call("c2", "grep", {"pattern": "needle"})],
        ),
        _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop"),
    ]
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=responses)
    executor = AsyncMock()
    executor.read_file.return_value = "file body"
    executor.grep.return_value = "a.py:1:needle"
    ledger = CostLedger(CostPolicy(), GPT_5_4_MINI_PRICING)
    ledger.reserve = AsyncMock(wraps=ledger.reserve)

    await gpt.review(
        "sys",
        "usr",
        tool_executor=executor,
        cost_ledger=ledger,
        max_completion_tokens=128,
    )

    ceilings = [call.args[1] for call in ledger.reserve.await_args_list]
    assert len(ceilings) == 3
    assert ceilings[0] < ceilings[1] < ceilings[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
async def test_incomplete_finish_reason_is_typed(finish_reason):
    gpt = GPTClient(api_key="x")
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(
        return_value=_mock_msg(
            content=MOCK_GPT_RESPONSE,
            finish_reason=finish_reason,
        )
    )

    with pytest.raises(ReviewInfraError) as exc_info:
        await gpt.review("sys", "usr")

    assert exc_info.value.category == ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE


@pytest.mark.asyncio
async def test_refusal_is_typed_without_leaking_response():
    gpt = GPTClient(api_key="x")
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(
        return_value=_mock_msg(
            content=None,
            finish_reason="stop",
            refusal="sensitive refusal body",
        )
    )

    with pytest.raises(ReviewInfraError) as exc_info:
        await gpt.review("sys", "usr")

    assert exc_info.value.category == ReviewInfraCategory.OPENAI_RESPONSE_INCOMPLETE
    assert "sensitive refusal body" not in str(exc_info.value)


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


@pytest.mark.asyncio
async def test_metered_retry_reserves_each_physical_request(monkeypatch):
    gpt = GPTClient(api_key="x")
    rate_limit = openai.RateLimitError(
        message="rate limited",
        response=httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        ),
        body=None,
    )
    success = _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop")
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(
        side_effect=[rate_limit, success]
    )
    monkeypatch.setattr("src.review.gpt_client.asyncio.sleep", AsyncMock())
    ledger = CostLedger(CostPolicy(hard_limit_usd="1"), GPT_5_4_MINI_PRICING)

    await gpt.review(
        "sys",
        "usr",
        cost_ledger=ledger,
        max_completion_tokens=32,
    )

    assert gpt._client.chat.completions.create.await_count == 2
    assert ledger.usage_unknown_nusd > 0


@pytest.mark.asyncio
async def test_cost_policy_caps_tool_result_tokens():
    gpt = GPTClient(api_key="x")
    first = _mock_msg(
        content=None,
        tool_calls=[_mock_tool_call("c1", "read_file", {"path": "a.py"})],
    )
    final = _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop")
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=[first, final])
    executor = AsyncMock()
    executor.read_file.return_value = "large body " * 100
    ledger = CostLedger(
        CostPolicy(hard_limit_usd="1", max_tool_result_tokens_per_call=8),
        GPT_5_4_MINI_PRICING,
    )

    await gpt.review(
        "sys",
        "usr",
        tool_executor=executor,
        max_completion_tokens=32,
        cost_ledger=ledger,
    )

    second_messages = gpt._client.chat.completions.create.await_args_list[1].kwargs["messages"]
    tool_content = next(item["content"] for item in second_messages if item["role"] == "tool")
    from src.review.token_counter import count_tokens
    assert count_tokens(tool_content) <= 8


def test_parse_rejects_extra_objects_outside_strict_json():
    gpt = GPTClient(api_key="x")
    content = (
        '{"path":"a.py"}\n'
        '{"path":"b.py"}\n'
        '{"spec_status":"present","aligned":true,"summary":"ok"}'
    )
    with pytest.raises(ReviewInfraError) as exc_info:
        gpt._parse(content)

    assert exc_info.value.category == ReviewInfraCategory.RESPONSE_SCHEMA_ERROR


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
    with pytest.raises(ReviewInfraError) as exc_info:
        gpt._parse("not json at all just text")

    assert exc_info.value.category == ReviewInfraCategory.RESPONSE_SCHEMA_ERROR


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


@pytest.mark.asyncio
async def test_review_caps_output_and_records_usage_in_shared_ledger():
    gpt = GPTClient(api_key="x")
    response = _mock_msg(content=json.dumps({
        "spec_status": "present", "aligned": True, "summary": "ok",
    }))
    response.usage = SimpleNamespace(
        prompt_tokens=1_000,
        completion_tokens=100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=250),
    )
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(return_value=response)
    ledger = CostLedger(CostPolicy(), GPT_5_4_MINI_PRICING)

    await gpt.review(
        "sys",
        "usr",
        max_completion_tokens=2048,
        cost_ledger=ledger,
        cost_stage="single",
    )

    kwargs = gpt._client.chat.completions.create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 2048
    assert ledger.actual_nusd == 1_031_250
    assert ledger.reserved_nusd == 0


@pytest.mark.asyncio
async def test_pre_reserved_request_consumes_reservation_and_retry_reserves_again(monkeypatch):
    gpt = GPTClient(api_key="x")
    rate_limit = openai.RateLimitError(
        message="rate limited",
        response=httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        ),
        body=None,
    )
    success = _mock_msg(content=MOCK_GPT_RESPONSE, finish_reason="stop")
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(side_effect=[rate_limit, success])
    monkeypatch.setattr("src.review.gpt_client.asyncio.sleep", AsyncMock())
    ledger = CostLedger(CostPolicy(hard_limit_usd="1"), GPT_5_4_MINI_PRICING)
    await ledger.reserve("synthesis-planned", 100_000_000)

    await gpt.review(
        "sys",
        "usr",
        cost_ledger=ledger,
        max_completion_tokens=32,
        pre_reserved_call_id="synthesis-planned",
    )

    assert gpt._client.chat.completions.create.await_count == 2
    assert ledger.reserved_nusd == 0
    assert ledger.usage_unknown_nusd > 100_000_000
    assert ledger.actual_nusd == 0  # mock response has no usage


@pytest.mark.asyncio
async def test_tool_request_disables_parallel_tool_calls_and_rejects_multiple_calls():
    gpt = GPTClient(api_key="x")
    response = _mock_msg(
        content=None,
        tool_calls=[
            _mock_tool_call("c1", "read_file", {"path": "a.py"}),
            _mock_tool_call("c2", "read_file", {"path": "b.py"}),
        ],
    )
    gpt._client = MagicMock()
    gpt._client.chat.completions.create = AsyncMock(return_value=response)
    executor = AsyncMock()
    ledger = CostLedger(CostPolicy(), GPT_5_4_MINI_PRICING)

    with pytest.raises(ReviewInfraError):
        await gpt.review(
            "sys", "usr", tool_executor=executor, cost_ledger=ledger
        )

    kwargs = gpt._client.chat.completions.create.call_args.kwargs
    assert kwargs["parallel_tool_calls"] is False
    executor.read_file.assert_not_awaited()
