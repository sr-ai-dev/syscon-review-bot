from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.models.config import ReviewConfig, RulesConfig
from src.review.diff_parser import FileDiff


class TestBuildSystemPrompt:
    def test_includes_role(self):
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        assert "코드 리뷰어" in prompt or "code reviewer" in prompt.lower()

    def test_includes_enabled_rules(self):
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        assert "보안" in prompt

    def test_excludes_disabled_rules(self):
        config = ReviewConfig(rules=RulesConfig(security=False))
        prompt = build_system_prompt(config, languages=[])
        assert "보안" not in prompt

    def test_includes_custom_rules(self):
        config = ReviewConfig(custom_rules=["All APIs need auth"])
        prompt = build_system_prompt(config, languages=[])
        assert "All APIs need auth" in prompt

    def test_includes_json_output_format(self):
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        assert "json" in prompt.lower()

    def test_includes_score_rationale_in_output_schema(self):
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        assert "score_rationale" in prompt

    def test_includes_scoring_rubric(self):
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        assert "점수 기준" in prompt
        # rubric covers full 6~10 spectrum
        for level in ("10", "9", "8", "7", "6"):
            assert level in prompt
        # rubric pegs severity to score so the model has a fixed scale
        assert "critical" in prompt
        assert "warning" in prompt
        assert "minor" in prompt

    def test_scoring_rubric_aligns_with_decision_thresholds(self):
        """Rubric must produce scores consistent with decision.py boundaries:
        critical → <7 (REQUEST_CHANGES), only minor → >=8 (APPROVE possible)."""
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        rubric_section = prompt.split("## 점수 기준", 1)[1]
        # score 8 must mention minor or warning (not critical)
        assert "minor" in rubric_section.split("8", 2)[0] or "minor" in rubric_section.split("8", 2)[1][:200]
        # critical must drop below 7
        below_7 = rubric_section.split("6", 1)[1] if "6" in rubric_section else ""
        # simpler: critical appears in the lower half
        idx_critical = rubric_section.find("critical")
        idx_minor = rubric_section.find("minor")
        assert idx_minor != -1 and idx_critical != -1
        # minor mentioned earlier (higher scores listed first)
        assert idx_minor < idx_critical

    def test_includes_language_section_when_provided(self):
        prompt = build_system_prompt(ReviewConfig(), languages=["Python", "C++"])
        assert "Python" in prompt
        assert "C++" in prompt
        assert "RAII" in prompt  # from C++ hint
        assert "PEP 8" in prompt  # from Python hint

    def test_no_language_section_when_empty(self):
        prompt = build_system_prompt(ReviewConfig(), languages=[])
        assert "언어 컨텍스트" not in prompt


class TestBuildUserPrompt:
    def test_includes_pr_info(self):
        files = [FileDiff(path="x.py", patch="+ new line", additions=1, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="Add feature",
            pr_body="Desc",
            base_branch="main",
            head_branch="feat/x",
        )
        assert "Add feature" in prompt
        assert "feat/x" in prompt

    def test_includes_diff_content(self):
        files = [FileDiff(path="src/main.py", patch="@@ -1 +1 @@\n+hello", additions=1, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="T", pr_body="B",
            base_branch="main", head_branch="feat",
        )
        assert "src/main.py" in prompt
        assert "+hello" in prompt

    def test_large_file_truncated(self):
        large_patch = "\n".join([f"+line {i}" for i in range(600)])
        files = [FileDiff(path="big.py", patch=large_patch, additions=600, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="T", pr_body="B",
            base_branch="main", head_branch="feat",
        )
        assert ("truncated" in prompt.lower() or "요약" in prompt) and len(prompt) < len(large_patch) + 500

    def test_includes_previous_reviews_section(self):
        files = [FileDiff(path="x.py", patch="+x", additions=1, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="T", pr_body="B",
            base_branch="main", head_branch="feat",
            previous_reviews=["## 🤖 코드 리뷰 — 점수: 7/10\nfoo"],
        )
        assert "이전 리뷰" in prompt
        assert "점수: 7/10" in prompt
        assert "일관" in prompt

    def test_omits_previous_reviews_section_when_empty(self):
        files = [FileDiff(path="x.py", patch="+x", additions=1, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="T", pr_body="B",
            base_branch="main", head_branch="feat",
            previous_reviews=[],
        )
        assert "이전 리뷰" not in prompt

    def test_previous_reviews_default_omitted(self):
        files = [FileDiff(path="x.py", patch="+x", additions=1, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="T", pr_body="B",
            base_branch="main", head_branch="feat",
        )
        assert "이전 리뷰" not in prompt

    def test_includes_multiple_previous_reviews_in_order(self):
        files = [FileDiff(path="x.py", patch="+x", additions=1, deletions=0)]
        prompt = build_user_prompt(
            files=files,
            pr_title="T", pr_body="B",
            base_branch="main", head_branch="feat",
            previous_reviews=[
                "## 🤖 코드 리뷰 — 점수: 7/10\nfirst",
                "## 🤖 코드 리뷰 — 점수: 6/10\nsecond",
            ],
        )
        assert prompt.index("first") < prompt.index("second")
