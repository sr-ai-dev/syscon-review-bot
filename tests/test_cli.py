import json
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.cli import main
from src.models.review import Decision
from src.review.engine import ReviewRunResult
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.models.review_pipeline import ReviewRoute


class TestCli:
    @pytest.fixture
    def event_payload(self):
        return {
            "action": "opened",
            "number": 5,
            "pull_request": {
                "number": 5,
                "title": "T",
                "head": {"ref": "feat"},
                "base": {"ref": "main"},
            },
            "repository": {"full_name": "owner/repo"},
        }

    @pytest.fixture
    def event_file(self, tmp_path, event_payload):
        path = tmp_path / "event.json"
        path.write_text(json.dumps(event_payload))
        return path

    @pytest.mark.asyncio
    async def test_pull_request_event_triggers_review(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(Decision.APPROVE)
            exit_code = await main()

        assert exit_code == 0
        mock_review.assert_called_once()
        kwargs = mock_review.call_args.kwargs
        assert kwargs["context"].repo == "owner/repo"
        assert kwargs["context"].pr_number == 5

    @pytest.mark.asyncio
    async def test_pull_request_request_changes_does_not_fail_ci(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(Decision.REQUEST_CHANGES)
            exit_code = await main()

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_spec_gate_failure_returns_error(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(
                Decision.REQUEST_CHANGES, spec_gate_passed=False
            )
            exit_code = await main()

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_review_infra_error_writes_safe_summary(
        self, event_file, monkeypatch, tmp_path, caplog
    ):
        summary_path = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

        error = ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Review response did not match the required schema",
        )
        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.side_effect = error
            exit_code = await main()

        summary = summary_path.read_text()
        assert exit_code == 1
        assert "REVIEW_INFRA_ERROR" in summary
        assert "RESPONSE_SCHEMA_ERROR" in summary
        assert "Code finding produced: no" in summary
        assert "sk-test" not in summary
        assert "sk-test" not in caplog.text

    @pytest.mark.asyncio
    async def test_non_pr_event_skipped(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            exit_code = await main()

        assert exit_code == 0
        mock_review.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_required_env_returns_error(self, event_file, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        exit_code = await main()
        assert exit_code != 0

    @pytest.mark.asyncio
    async def test_dry_run_env_propagates_to_review_pr(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("REVIEW_DRY_RUN", "1")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(Decision.APPROVE)
            await main()

        assert mock_review.call_args.kwargs["dry_run"] is True

    @pytest.mark.asyncio
    async def test_dry_run_default_false(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("REVIEW_DRY_RUN", raising=False)

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(Decision.APPROVE)
            await main()

        assert mock_review.call_args.kwargs.get("dry_run", False) is False

    @pytest.mark.asyncio
    async def test_model_override_env_takes_precedence(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("REVIEW_MODEL_OVERRIDE", "gpt-5-mini")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(Decision.APPROVE)
            await main()

        assert mock_review.call_args.kwargs["model_override"] == "gpt-5-mini"

    @pytest.mark.asyncio
    async def test_trusted_cost_inputs_propagate_to_review_pr(self, event_file, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("REVIEW_MAX_COST_USD", "2.50")
        monkeypatch.setenv("REVIEW_MAX_REQUESTS", "7")
        monkeypatch.setenv("REVIEW_MAX_COMPLETION_TOKENS", "2048")

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(
                Decision.APPROVE, route=ReviewRoute.SINGLE, cost_nusd=125_000_000
            )
            assert await main() == 0

        policy = mock_review.call_args.kwargs["cost_policy"]
        assert str(policy.hard_limit_usd) == "2.50"
        assert policy.max_requests_per_pr == 7
        assert policy.max_completion_tokens_per_call == 2048

    @pytest.mark.asyncio
    async def test_review_summary_contains_route_and_cost(self, event_file, monkeypatch, tmp_path):
        summary_path = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

        with patch("src.cli.review_pr", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = ReviewRunResult(
                Decision.APPROVE, route=ReviewRoute.MULTI, cost_nusd=125_000_000
            )
            assert await main() == 0

        summary = summary_path.read_text()
        assert "multi" in summary
        assert "$0.125000" in summary
