from src.review.rules.builtin import BUILTIN_RULES


SEVERITY_TERMS = ("critical", "warning", "minor")


def test_every_rule_has_severity_guidance():
    """각 룰은 어떤 위반이 어느 심각도로 분류되는지 GPT에게 가이드해야 한다.
    그래야 동일 이슈가 호출 간 다른 심각도로 흔들리지 않음."""
    for key, text in BUILTIN_RULES.items():
        mentioned = [t for t in SEVERITY_TERMS if t in text]
        assert len(mentioned) >= 2, (
            f"룰 '{key}'에 심각도 가이드 부족 (mentioned={mentioned}). "
            "룰 위반이 어떤 severity로 분류되는지 최소 2개 tier 이상 명시 필요."
        )


def test_security_rule_marks_injection_as_critical():
    """SQL/명령어 인젝션은 무조건 critical이어야 한다."""
    text = BUILTIN_RULES["security"]
    assert "critical" in text
    # critical 가이드 안에 인젝션류가 포함되어야
    critical_section = text[text.index("critical"):]
    assert "인젝션" in critical_section or "injection" in critical_section.lower()


def test_error_handling_rule_can_mark_critical():
    """silent failure / 데이터 손상 가능한 미처리는 critical 가능해야."""
    assert "critical" in BUILTIN_RULES["error_handling"]


def test_documentation_rule_no_critical():
    """문서 누락이 critical일 일은 거의 없음. 과도한 분류 방지."""
    assert "critical" not in BUILTIN_RULES["documentation"]
