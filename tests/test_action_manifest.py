"""Composite action dependency pinning contract."""

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FULL_SHA_REFERENCE = re.compile(r"[^@\s]+@[0-9a-f]{40}")
SETUP_PYTHON_V5_REFERENCE = (
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
)


def test_composite_action_dependencies_use_full_commit_sha() -> None:
    action_manifest = (REPOSITORY_ROOT / "action.yml").read_text(encoding="utf-8")
    references = [
        line.split("uses:", 1)[1].split("#", 1)[0].strip()
        for line in action_manifest.splitlines()
        if "uses:" in line
    ]

    assert references
    assert all(FULL_SHA_REFERENCE.fullmatch(reference) for reference in references), references
    assert SETUP_PYTHON_V5_REFERENCE in references


def test_composite_action_exposes_trusted_cost_controls() -> None:
    action_manifest = (REPOSITORY_ROOT / "action.yml").read_text(encoding="utf-8")
    assert "max-review-cost-usd:" in action_manifest
    assert "max-review-requests:" in action_manifest
    assert "max-completion-tokens:" in action_manifest
    assert "REVIEW_MAX_COST_USD:" in action_manifest
    assert "REVIEW_MAX_REQUESTS:" in action_manifest
    assert "REVIEW_MAX_COMPLETION_TOKENS:" in action_manifest
