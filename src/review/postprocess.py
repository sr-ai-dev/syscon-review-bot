from src.models.review import ReviewResult, SpecStatus


def postprocess(result: ReviewResult, threshold: int = 70) -> ReviewResult:
    """LLM 출력 정리:
    - confidence < threshold finding drop
    - 같은 (file, line) mismatches + quality_findings 중복 → mismatch 우선 유지
    - mismatches 변화에 따라 aligned 재계산 (spec_status=present 일 때만)
    """
    kept_mismatches = [m for m in result.mismatches if m.confidence >= threshold]

    mismatch_locations: set[tuple[str | None, int | None]] = {
        (m.file, m.line) for m in kept_mismatches
    }
    kept_quality = [
        q for q in result.quality_findings
        if q.confidence >= threshold and (q.file, q.line) not in mismatch_locations
    ]

    new_aligned = result.aligned
    if result.spec_status == SpecStatus.PRESENT:
        new_aligned = len(kept_mismatches) == 0

    return result.model_copy(update={
        "mismatches": kept_mismatches,
        "quality_findings": kept_quality,
        "aligned": new_aligned,
    })
