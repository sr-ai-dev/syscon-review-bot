from src.review.prompt_builder import build_system_prompt, build_user_prompt
from src.review.diff_parser import FileDiff


class TestBuildSystemPrompt:
    def test_states_role_is_spec_alignment_only(self):
        prompt = build_system_prompt()
        assert "정합성" in prompt
        assert "스펙" in prompt or "요구사항" in prompt
        # 폐기된 채점 체계가 더 이상 없음을 검증
        for dead in ("점수", "score", "rubric", "critical", "warning", "minor"):
            assert dead not in prompt, f"폐기된 키워드 '{dead}'가 프롬프트에 남아있음"

    def test_includes_spec_missing_critical_instruction(self):
        prompt = build_system_prompt()
        assert "missing" in prompt
        assert "PRESENT" in prompt or "present" in prompt

    def test_includes_korean_output_directive(self):
        prompt = build_system_prompt()
        assert "한국어" in prompt or "korean" in prompt.lower()

    def test_includes_json_schema_fields(self):
        prompt = build_system_prompt()
        for field in ("spec_status", "aligned", "summary", "mismatches"):
            assert field in prompt


class TestBuildUserPrompt:
    def _files(self):
        return [FileDiff(path="a.py", patch="+x", additions=1, deletions=0)]

    def test_includes_pr_info(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="로그인 API 추가",
            pr_body="POST /auth/login 구현. 요구사항: ...",
            base_branch="main", head_branch="feat/login",
        )
        assert "로그인 API 추가" in prompt
        assert "POST /auth/login" in prompt
        assert "feat/login" in prompt

    def test_includes_diff_content(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
        )
        assert "a.py" in prompt
        assert "+x" in prompt

    def test_previous_reviews_section_included_when_present(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            previous_reviews=["## 🤖 코드 리뷰\n이전지적"],
        )
        assert "이전 리뷰" in prompt
        assert "이전지적" in prompt

    def test_no_previous_reviews_section_when_empty(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
        )
        assert "이전 리뷰" not in prompt

    def test_large_file_truncated(self):
        large = "\n".join([f"+line {i}" for i in range(600)])
        prompt = build_user_prompt(
            files=[FileDiff(path="big.py", patch=large, additions=600, deletions=0)],
            pr_title="t", pr_body="b", base_branch="m", head_branch="f",
        )
        assert "요약" in prompt or "truncated" in prompt.lower()
