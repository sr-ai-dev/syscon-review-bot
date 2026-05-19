import pytest

from src.models.review import (
    FindingCategory, Mismatch, QualityFinding, ReviewResult, SpecStatus,
)
from src.review.postprocess import postprocess


def _result(**kw):
    base = dict(spec_status=SpecStatus.PRESENT, aligned=True, summary="s")
    base.update(kw)
    return ReviewResult(**base)


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


def test_arch_concern_string_preserved():
    r = _result(architecture_concern="단순 framework wiring")
    out = postprocess(r, threshold=70)
    assert out.architecture_concern == "단순 framework wiring"
