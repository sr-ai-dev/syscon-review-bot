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
