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

    def test_spec_sources_include_doc_files_in_diff(self):
        """스펙 위치 둘 다 인식: PR 본문 + diff에 포함된 문서 파일."""
        prompt = build_system_prompt()
        # PR 본문 출처
        assert "본문" in prompt
        # diff 안의 문서 파일 출처 (.md 같은)
        assert ("문서 파일" in prompt or "doc" in prompt.lower())
        assert ".md" in prompt or "변경 사항" in prompt

    def test_includes_korean_output_directive(self):
        prompt = build_system_prompt()
        assert "한국어" in prompt or "korean" in prompt.lower()

    def test_includes_json_schema_fields(self):
        prompt = build_system_prompt()
        for field in ("spec_status", "aligned", "summary", "mismatches"):
            assert field in prompt

    def test_includes_brief_architecture_check(self):
        """스펙 정합성이 주이지만 명백한 아키텍처 문제는 별도 한 줄로 보고."""
        prompt = build_system_prompt()
        assert "아키텍처" in prompt
        assert "architecture_concern" in prompt

    def test_includes_quality_findings_schema(self):
        prompt = build_system_prompt()
        assert "quality_findings" in prompt

    def test_includes_sonarqube_categories(self):
        prompt = build_system_prompt()
        for cat in ("bug", "vulnerability", "security", "smell", "complexity"):
            assert cat in prompt

    def test_quality_check_section_present(self):
        prompt = build_system_prompt()
        assert ("코드 품질" in prompt or "SonarQube" in prompt)

    def test_includes_language_awareness_directive(self):
        prompt = build_system_prompt()
        assert "언어" in prompt and "프레임워크" in prompt
        assert "컨벤션" in prompt

    def test_includes_bundling_instruction(self):
        prompt = build_system_prompt()
        assert ("묶" in prompt or "1개로" in prompt or "여러 파일에 적용" in prompt)


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

    def test_previous_reviews_marked_as_reference_not_truth(self):
        """현재 PR 본문/코드가 진리. 이전 리뷰는 참고만."""
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            previous_reviews=["## 🤖 코드 리뷰\nold"],
        )
        # 우선순위 명시
        assert "참고" in prompt
        # 본문/코드 갱신 시 결론 갱신 가능 명시
        assert ("갱신" in prompt or "최신" in prompt or "변경" in prompt)
        # 일관성 강제하는 옛 표현은 빠져야
        assert "일관성을 유지하라" not in prompt

    def test_previous_reviews_instruct_no_duplicate_findings(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            previous_reviews=["## 🤖 스펙 정합성 리뷰\n이전지적"],
        )
        assert "동일" in prompt or "다시 적지" in prompt or "재지적" in prompt
        assert ("신규" in prompt or "새로 생긴" in prompt or "변경" in prompt)

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

    def test_human_comments_section_when_present(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            human_comments=["@alice (src/x.py:10): 이건 의도된 동작입니다"],
        )
        assert "사람 코멘트" in prompt
        assert "이건 의도된 동작" in prompt

    def test_human_comments_respect_directive(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
            human_comments=["@alice: 거부"],
        )
        assert "의도" in prompt
        assert ("거부" in prompt or "won't fix" in prompt or "다시 지적하지" in prompt)

    def test_no_human_comments_section_when_empty(self):
        prompt = build_user_prompt(
            files=self._files(),
            pr_title="t", pr_body="b",
            base_branch="main", head_branch="f",
        )
        assert "사람 코멘트" not in prompt
