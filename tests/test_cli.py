import json
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.cli import main


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
            exit_code = await main()

        assert exit_code == 0
        mock_review.assert_called_once()
        kwargs = mock_review.call_args.kwargs
        assert kwargs["context"].repo == "owner/repo"
        assert kwargs["context"].pr_number == 5

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
            await main()

        assert mock_review.call_args.kwargs["model_override"] == "gpt-5-mini"
