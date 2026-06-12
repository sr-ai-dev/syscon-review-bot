import pytest

from src.models.review import (
    ArchitectureFinding, FindingCategory, Mismatch, QualityFinding, ReviewResult,
    SpecDocFinding, SpecStatus,
)
from src.review.postprocess import postprocess


def _result(**kw):
    base = dict(spec_status=SpecStatus.PRESENT, aligned=True, summary="s")
    base.update(kw)
    return ReviewResult(**base)


def _arch(description: str, confidence: int = 85) -> ArchitectureFinding:
    return ArchitectureFinding(description=description, suggestion="s", confidence=confidence)


def test_filters_low_confidence_mismatches():
    r = _result(
        mismatches=[
            Mismatch(file="a.py", line=1, description="확실", suggestion="s", confidence=85),
            Mismatch(file="b.py", line=2, description="약함", suggestion="s", confidence=40),
        ],
    )
    out = postprocess(r, threshold=70)
    paths = [m.file for m in out.mismatches]
    assert paths == ["a.py"]


def test_filters_low_confidence_quality_findings():
    r = _result(
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="a.py", line=1,
                description="확실", suggestion="s", confidence=75,
            ),
            QualityFinding(
                category=FindingCategory.SMELL, file="b.py", line=2,
                description="모호", suggestion="s", confidence=50,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert [q.file for q in out.quality_findings] == ["a.py"]


def test_filters_low_confidence_spec_doc_findings():
    r = _result(
        spec_doc_findings=[
            SpecDocFinding(
                file="spec/a/requirements.md", line=1,
                description="확실한 문서 결함", suggestion="s", confidence=75,
            ),
            SpecDocFinding(
                file="spec/a/design.md", line=2,
                description="약한 문서 의심", suggestion="s", confidence=50,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert [f.file for f in out.spec_doc_findings] == ["spec/a/requirements.md"]


def test_dedups_same_file_line_across_mismatches_and_quality_keeping_mismatch():
    r = _result(
        mismatches=[
            Mismatch(file="a.py", line=10, description="스펙 위반", suggestion="s", confidence=80),
        ],
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="a.py", line=10,
                description="같은 위치 버그", suggestion="s", confidence=80,
            ),
            QualityFinding(
                category=FindingCategory.SMELL, file="b.py", line=5,
                description="다른 위치", suggestion="s", confidence=80,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert len(out.mismatches) == 1
    assert len(out.quality_findings) == 1
    assert out.quality_findings[0].file == "b.py"


def test_aligned_recomputed_when_mismatches_changed():
    r = _result(
        aligned=True,
        mismatches=[
            Mismatch(file="a.py", line=1, description="d", suggestion="s", confidence=85),
        ],
    )
    out = postprocess(r, threshold=70)
    assert out.aligned is False


def test_aligned_recomputed_when_all_mismatches_filtered_out():
    r = _result(
        aligned=False,
        spec_status=SpecStatus.PRESENT,
        mismatches=[
            Mismatch(file="a.py", line=1, description="약한", suggestion="s", confidence=30),
        ],
    )
    out = postprocess(r, threshold=70)
    assert out.mismatches == []
    assert out.aligned is True


def test_filters_low_confidence_architecture_findings():
    r = _result(architecture_findings=[
        _arch("확실한 레이어 역참조", confidence=85),
        _arch("약한 구조 의심", confidence=70),
    ])
    out = postprocess(r, threshold=70)
    assert [a.description for a in out.architecture_findings] == ["확실한 레이어 역참조"]


def test_prior_resolved_gets_partial_prefix_when_topic_still_in_findings():
    r = _result(
        prior_resolved=["그룹 패널 책임 → helper 분리로 일부 완화"],
        architecture_findings=[
            _arch("그룹 패널이 책임 분산 없이 멤버 수집·집계·Command 실행 직접 담당"),
        ],
    )
    out = postprocess(r, threshold=70)
    assert out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_keeps_full_when_topic_not_in_findings():
    r = _result(
        prior_resolved=["필드 초기값 → 생성자에서 보정"],
        architecture_findings=[_arch("다른 주제")],
    )
    out = postprocess(r, threshold=70)
    assert not out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_partial_prefix_already_present_kept():
    r = _result(
        prior_resolved=["(부분) 그룹 패널 책임 → 일부 완화"],
        architecture_findings=[_arch("그룹 패널 책임 잔존")],
    )
    out = postprocess(r, threshold=70)
    assert out.prior_resolved[0].count("(부분)") == 1


def test_prior_resolved_topic_match_uses_findings_after_filtering():
    """confidence 필터 후 남은 findings 기준으로 prefix 결정."""
    r = _result(
        prior_resolved=["그룹 패널 책임 → helper 분리"],
        quality_findings=[
            QualityFinding(
                category=FindingCategory.SMELL, file=None, line=None,
                description="그룹 패널 책임 집중", suggestion="s", confidence=40,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    # quality_findings 필터됨 → 주제 매칭 없음 → prefix 추가 안 함
    assert not out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_gets_partial_prefix_from_spec_doc_findings():
    r = _result(
        prior_resolved=["requirements tasks 범위 불일치 → 일부 정리"],
        spec_doc_findings=[
            SpecDocFinding(
                description="requirements와 tasks의 범위 불일치가 남아 있음",
                suggestion="s",
                confidence=80,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_keeps_full_when_only_common_words_overlap():
    """일반 어휘 ("처리", "에러", "함수") 2개 겹쳐도 prefix 부착 금지."""
    r = _result(
        prior_resolved=["로그 처리 에러 핸들링 → 수정 완료"],
        architecture_findings=[_arch("요청 처리 시 에러 발생 가능")],
    )
    out = postprocess(r, threshold=70)
    # 일반 어휘만 겹침 → 다른 주제로 간주 → prefix 없어야
    assert not out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_keeps_full_when_only_two_meaningful_tokens_overlap():
    """의미 토큰 2개만 겹치면 prefix 부착 안 함 (>=3 임계)."""
    r = _result(
        prior_resolved=["LocationPort 기본값 보정 → 완료"],
        architecture_findings=[_arch("LocationPort 생성자에서 기본값 적용")],
    )
    out = postprocess(r, threshold=70)
    # "LocationPort", "기본값" 2개 매칭 — but 임계 3 미만 → 부착 안 함
    assert not out.prior_resolved[0].startswith("(부분)")


def test_prior_resolved_adds_partial_when_three_or_more_tokens_overlap():
    """3개 이상 매칭이면 부착."""
    r = _result(
        prior_resolved=["그룹 패널의 멤버 수집 책임 → 분리 완료"],
        architecture_findings=[_arch("그룹 패널이 멤버 location 수집 책임 직접 담당")],
    )
    out = postprocess(r, threshold=70)
    # "그룹", "패널", "멤버", "수집", "책임" 등 충분히 매칭
    assert out.prior_resolved[0].startswith("(부분)")


def test_dedup_does_not_collide_on_none_location_keys():
    """file=None, line=None 인 묶음 finding 2개가 mismatch와 quality에 동시 있어도
    quality 측이 silent drop되면 안 된다."""
    r = _result(
        mismatches=[
            Mismatch(
                file=None, line=None,
                description="여러 파일 공통 스펙 위반",
                suggestion="s", confidence=80,
            ),
        ],
        quality_findings=[
            QualityFinding(
                category=FindingCategory.SMELL, file=None, line=None,
                description="다른 주제의 여러 파일 공통 중복 코드",
                suggestion="s", confidence=80,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert len(out.mismatches) == 1
    assert len(out.quality_findings) == 1  # 위치 키 None이라 dedup 스킵, 보존


def test_dedup_still_removes_same_concrete_location():
    """구체 (file, line) 일치는 여전히 dedup."""
    r = _result(
        mismatches=[
            Mismatch(file="a.py", line=10, description="d", suggestion="s", confidence=80),
        ],
        quality_findings=[
            QualityFinding(
                category=FindingCategory.BUG, file="a.py", line=10,
                description="같은 위치", suggestion="s", confidence=80,
            ),
        ],
    )
    out = postprocess(r, threshold=70)
    assert len(out.mismatches) == 1
    assert len(out.quality_findings) == 0


def test_prior_resolved_no_prefix_when_overlap_exactly_one():
    """1개 토큰만 일치하면 부착 안 함 (>=3 임계)."""
    r = _result(
        prior_resolved=["그룹 멤버 책임 분리 → 완료"],
        architecture_findings=[_arch("완전 다른 주제의 데이터 흐름 문제")],
    )
    out = postprocess(r, threshold=70)
    assert not out.prior_resolved[0].startswith("(부분)")


def test_aligned_not_recomputed_when_spec_missing():
    """spec_status=MISSING이면 aligned 재계산 안 함 (false 유지)."""
    r = ReviewResult(
        spec_status=SpecStatus.MISSING, aligned=False, summary="s",
        mismatches=[],
    )
    out = postprocess(r, threshold=70)
    assert out.aligned is False  # MISSING은 항상 False, 재계산 안 됨
    assert out.spec_status == SpecStatus.MISSING


def test_significant_tokens_strips_korean_particles():
    """조사 제거 검증."""
    from src.review.postprocess import _significant_tokens
    tokens = _significant_tokens("패널이 책임을 떠안고 있다")
    # 조사 제거 후 "패널", "책임", "떠안" 남아야
    assert "패널" in tokens
    assert "책임" in tokens


def test_significant_tokens_excludes_stopwords():
    """stopword 제외 검증."""
    from src.review.postprocess import _significant_tokens
    tokens = _significant_tokens("에러 처리 함수 추가")
    # 모두 stopword라 빈 set
    assert tokens == set()
