import re

from src.models.review import ReviewResult, SpecStatus


_TOKEN_RE = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9_\.]*")
# 한국어 조사·어미 — 토큰 끝에서 제거해 어간 추출
_PARTICLE_RE = re.compile(
    r"(이|가|을|를|은|는|의|에|로|으로|에서|이다|도|과|와|이나|나|이며|며|이고|고|만|"
    r"부터|까지|라|이라|처럼|같이|보다|한테|께|에게|으로서|로서|으로써|로써|에게서|한테서)$"
)
# 일반 한국어 어휘 — 우연 일치를 막기 위해 토큰 매칭 전 제거
_STOPWORDS: set[str] = {
    "처리", "에러", "함수", "변경", "구조", "개선", "수정", "추가",
    "사용", "호출", "필요", "가능", "확인", "검증", "구현", "정의",
    "코드", "파일", "값", "동작", "결과", "방향", "분기", "지원",
}


def _significant_tokens(text: str) -> set[str]:
    """한글/영문 토큰을 추출하고 조사를 제거한 뒤 2글자 이상이며 stopword 아닌 것만 반환."""
    result: set[str] = set()
    for tok in _TOKEN_RE.findall(text):
        normalized = _PARTICLE_RE.sub("", tok)
        if len(normalized) < 2:
            continue
        if normalized in _STOPWORDS:
            continue
        result.add(normalized)
    return result


def _enforce_partial_prefix(
    prior_resolved: list[str],
    finding_texts: list[str],
) -> list[str]:
    """prior_resolved 항목의 주제 토큰이 다른 finding에 등장하면 (부분) prefix 강제.
    이미 prefix 있으면 중복 추가하지 않음.
    """
    all_finding_tokens: set[str] = set()
    for t in finding_texts:
        all_finding_tokens.update(_significant_tokens(t))

    out: list[str] = []
    for item in prior_resolved:
        stripped = item.lstrip()
        if stripped.startswith("(부분)"):
            out.append(item)
            continue
        item_tokens = _significant_tokens(item)
        overlap = item_tokens & all_finding_tokens
        if len(overlap) >= 3:
            out.append(f"(부분) {item}")
        else:
            out.append(item)
    return out


def _location_key(item) -> tuple[str, int] | None:
    """file 또는 line 중 하나라도 None이면 None을 반환 (dedup 후보 아님)."""
    if item.file is None or item.line is None:
        return None
    return (item.file, item.line)


def postprocess(result: ReviewResult, threshold: int = 70) -> ReviewResult:
    """LLM 출력 정리:
    - confidence < threshold finding drop
    - 같은 (file, line) mismatches + quality_findings 중복 → mismatch 우선 유지
      단, file=None or line=None 인 항목은 위치 미확정으로 dedup 스킵
    - mismatches 변화에 따라 aligned 재계산 (spec_status=present 일 때만)
    - prior_resolved 항목의 주제가 다른 섹션에 남아있으면 (부분) prefix 자동 부착
    """
    kept_mismatches = [m for m in result.mismatches if m.confidence >= threshold]
    kept_spec_doc = [
        f for f in result.spec_doc_findings
        if f.confidence >= threshold
    ]

    mismatch_locations: set[tuple[str, int]] = {
        key for m in kept_mismatches
        if (key := _location_key(m)) is not None
    }
    kept_quality = [
        q for q in result.quality_findings
        if q.confidence >= threshold and (
            (key := _location_key(q)) is None or key not in mismatch_locations
        )
    ]
    arch_threshold = max(threshold, 80)
    kept_architecture = [
        a for a in result.architecture_findings
        if a.confidence >= arch_threshold
    ]

    new_aligned = result.aligned
    if result.spec_status == SpecStatus.PRESENT:
        new_aligned = len(kept_mismatches) == 0

    finding_texts = [m.description for m in kept_mismatches]
    finding_texts += [s.description for s in kept_spec_doc]
    finding_texts += [q.description for q in kept_quality]
    finding_texts += [a.description for a in kept_architecture]

    new_prior_resolved = _enforce_partial_prefix(result.prior_resolved, finding_texts)

    return result.model_copy(update={
        "mismatches": kept_mismatches,
        "spec_doc_findings": kept_spec_doc,
        "architecture_findings": kept_architecture,
        "quality_findings": kept_quality,
        "aligned": new_aligned,
        "prior_resolved": new_prior_resolved,
    })
