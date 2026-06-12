from src.review.judge_prompt import build_judge_system_prompt


def test_judge_prompt_mentions_dedup_and_prior_resolved():
    s = build_judge_system_prompt()
    assert "중복" in s
    assert "prior_resolved" in s
    assert "JSON" in s


def test_judge_prompt_mentions_aligned_rule():
    s = build_judge_system_prompt()
    assert "aligned" in s
    assert "mismatches" in s


def test_judge_prompt_mentions_spec_doc_findings():
    s = build_judge_system_prompt()
    assert "spec_doc_findings" in s
