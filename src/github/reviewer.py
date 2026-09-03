from collections.abc import Sequence
from html import escape

from src.github.client import GitHubClient
from src.models.review import (
    AdvisoryFinding,
    ArchitectureFinding,
    Decision,
    FindingCategory,
    Mismatch,
    QualityFinding,
    ReviewResult,
    SpecDocFinding,
    SpecStatus,
)
from src.review.decision import compute_decision
from src.review.errors import ReviewInfraCategory, ReviewInfraError


BOT_REVIEW_MARKER = "## 🤖 AI 리뷰"
SPLIT_REQUEST_MARKER_PREFIX = "<!-- syscon-review-bot:split-request head_sha="
MAX_GITHUB_REVIEW_BODY_CHARS = 60_000


def filter_bot_reviews(reviews: list[dict]) -> list[dict]:
    return [r for r in reviews if BOT_REVIEW_MARKER in (r.get("body") or "")]


def has_split_request_for_head(reviews: list[dict], head_sha: str) -> bool:
    safe_sha = "".join(character for character in head_sha if character.isalnum())
    marker = f"{SPLIT_REQUEST_MARKER_PREFIX}{safe_sha} -->"
    return any(marker in (review.get("body") or "") for review in reviews)


def _escape_table_cell(text: str | None) -> str:
    if not text:
        return ""
    text = escape(text, quote=False).replace("`", "&#96;")
    text = text.replace("|", r"\|")
    return " ".join(text.split())


def _format_metric(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.10f}".rstrip("0").rstrip(".")


def _format_inline_code(value: str) -> str:
    # Reason codes and paths are rendered as one line and cannot break the marker/body.
    safe = escape(" ".join(value.split()), quote=False).replace("`", "&#96;")
    return f"`{safe}`"


def format_split_request_body(
    *,
    effective_lines: int | float,
    effective_files: int | float,
    raw_diff_tokens: int,
    max_effective_lines: int | float,
    max_effective_files: int | float,
    max_raw_diff_tokens: int,
    reason_codes: Sequence[str],
    suggested_groups: Sequence[Sequence[str]],
    head_sha: str,
) -> str:
    """Build the policy-only response used when a complete review cannot run."""
    reasons = ", ".join(_format_inline_code(code) for code in reason_codes)
    safe_sha = "".join(character for character in head_sha if character.isalnum())
    lines = [
        BOT_REVIEW_MARKER,
        "",
        "### 판정: 🚫 PR 분할 필요",
        "",
        "> 자동 리뷰 가능 범위를 초과했습니다.",
        "",
        (
            f"측정: 가중 변경량 {_format_metric(effective_lines)}줄 / "
            f"유효 파일 {_format_metric(effective_files)}개 / "
            f"raw diff {_format_metric(raw_diff_tokens)} tokens"
        ),
        (
            f"기준: 가중 변경량 {_format_metric(max_effective_lines)}줄 / "
            f"유효 파일 {_format_metric(max_effective_files)}개 / "
            f"raw diff {_format_metric(max_raw_diff_tokens)} tokens"
        ),
        "",
        f"사유 코드: {reasons}",
    ]

    if suggested_groups:
        lines.extend(["", "권장 분할 그룹:"])
        for index, group in enumerate(suggested_groups, 1):
            paths = ", ".join(_format_inline_code(path) for path in group)
            lines.append(f"- 그룹 {index}: {paths}")

    lines.extend([
        "",
        "기능 또는 독립 배포·롤백 단위로 PR을 분리해주세요.",
        "",
        f"{SPLIT_REQUEST_MARKER_PREFIX}{safe_sha} -->",
    ])
    return "\n".join(lines)


def _format_location(item: AdvisoryFinding | ArchitectureFinding | Mismatch | QualityFinding | SpecDocFinding) -> str:
    if item.file is None:
        return "_전체 PR_"
    safe = _escape_table_cell(item.file)
    if item.line:
        return f"`{safe}:{item.line}`"
    return f"`{safe}`"


def _format_item_with_location(description: str, location: str) -> str:
    return f"{description}<br>위치: {location}"


def _format_item_with_meta(description: str, location: str, confidence: int) -> str:
    return f"{_format_item_with_location(description, location)}<br>신뢰도: {confidence}"


_VERDICT_LABEL = {
    Decision.APPROVE: "✅ (Approved)",
    Decision.REQUEST_CHANGES: "❌ (수정 필요)",
}


_CATEGORY_LABEL = {
    FindingCategory.BUG: "버그",
    FindingCategory.VULNERABILITY: "취약점",
    FindingCategory.SECURITY: "보안",
    FindingCategory.SMELL: "코드 스멜",
    FindingCategory.COMPLEXITY: "복잡도",
}


def format_review_body(result: ReviewResult) -> str:
    decision = compute_decision(result)
    lines = [BOT_REVIEW_MARKER, "", _escape_table_cell(result.summary)]

    if result.spec_status == SpecStatus.MISSING:
        lines.extend([
            "",
            "> PR 본문 또는 diff에서 스펙·요구사항을 식별하지 못했습니다.",
            "> 정합성 검토와 스펙 문서 검토는 생략하고, 아키텍처와 코드 품질 위주로 검토했습니다.",
        ])
    else:
        lines.append("")
        lines.append("### 스펙 문서 검토")
        if result.spec_doc_findings:
            lines.append("| # | 항목 | 제안 |")
            lines.append("|---|------|------|")
            for idx, s in enumerate(result.spec_doc_findings, 1):
                desc = _escape_table_cell(s.description)
                sugg = _escape_table_cell(s.suggestion)
                loc = _format_location(s)
                item = _format_item_with_meta(desc, loc, s.confidence)
                lines.append(f"| {idx} | {item} | {sugg} |")
        else:
            lines.append("> 이상 없음")

        if result.mismatches:
            lines.extend([
                "",
                "### 스펙과 불일치",
                "| # | 항목 | 제안 |",
                "|---|------|------|",
            ])
            for idx, m in enumerate(result.mismatches, 1):
                desc = _escape_table_cell(m.description)
                sugg = _escape_table_cell(m.suggestion)
                loc = _format_location(m)
                item = _format_item_with_meta(desc, loc, m.confidence)
                lines.append(f"| {idx} | {item} | {sugg} |")

    if result.prior_resolved:
        partials = [i for i in result.prior_resolved if i.lstrip().startswith("(부분)")]
        fulls = [i for i in result.prior_resolved if i not in partials]
        header_parts = []
        if fulls:
            header_parts.append(f"완전 해결 {len(fulls)}건")
        if partials:
            header_parts.append(f"부분 해결 {len(partials)}건")
        lines.extend([
            "",
            f"### 이전 리뷰 상태 ({', '.join(header_parts)})",
        ])
        for item in fulls:
            lines.append(f"- ✅ 완전 해결: {_escape_table_cell(item)}")
        for item in partials:
            stripped = item.lstrip()
            stripped = stripped[len("(부분)"):].lstrip()
            lines.append(f"- 🔶 부분 해결: {_escape_table_cell(stripped)}")

    lines.append("")
    lines.append("### 아키텍처 검토")
    if result.architecture_findings:
        lines.append("| # | 항목 | 제안 |")
        lines.append("|---|------|------|")
        for idx, a in enumerate(result.architecture_findings, 1):
            desc = _escape_table_cell(a.description)
            sugg = _escape_table_cell(a.suggestion)
            loc = _format_location(a)
            item = _format_item_with_meta(desc, loc, a.confidence)
            lines.append(f"| {idx} | {item} | {sugg} |")
    else:
        lines.append("> 이상 없음")

    lines.append("")
    lines.append("### 코드 품질 검사")
    if result.quality_findings:
        lines.append("| # | 분류 | 항목 | 제안 |")
        lines.append("|---|------|------|------|")
        for idx, f in enumerate(result.quality_findings, 1):
            cat = _CATEGORY_LABEL[f.category]
            desc = _escape_table_cell(f.description)
            sugg = _escape_table_cell(f.suggestion)
            loc = _format_location(f)
            item = _format_item_with_meta(desc, loc, f.confidence)
            lines.append(f"| {idx} | {cat} | {item} | {sugg} |")
    else:
        lines.append("> 이상 없음")

    if result.advisory_findings:
        lines.extend([
            "",
            "### 참고 사항 (Advisory)",
            "> 정상 workflow의 수정 요청 사유가 아닌 선택적 hardening 제안입니다.",
            "| # | 항목 | 제안 |",
            "|---|------|------|",
        ])
        for idx, advisory in enumerate(result.advisory_findings, 1):
            desc = _escape_table_cell(advisory.description)
            sugg = _escape_table_cell(advisory.suggestion)
            loc = _format_location(advisory)
            item = _format_item_with_meta(desc, loc, advisory.confidence)
            lines.append(f"| {idx} | {item} | {sugg} |")

    lines.append("")
    lines.append(f"### 판정: {_VERDICT_LABEL[decision]}")

    return "\n".join(lines)


def _validate_github_body(body: str) -> None:
    if len(body) > MAX_GITHUB_REVIEW_BODY_CHARS:
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Formatted review exceeded the safe GitHub body limit",
        )


async def submit_review(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    result: ReviewResult,
) -> None:
    # 기본 GITHUB_TOKEN은 GitHub 정책상 APPROVE 이벤트를 거부한다(422).
    # 봇의 결정은 본문 라벨로 노출하고, API 이벤트는 항상 COMMENT로 통일.
    body = format_review_body(result)
    _validate_github_body(body)
    await client.post(
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        json_data={"body": body, "event": "COMMENT"},
    )


async def submit_split_request(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    *,
    effective_lines: int | float,
    effective_files: int | float,
    raw_diff_tokens: int,
    max_effective_lines: int | float,
    max_effective_files: int | float,
    max_raw_diff_tokens: int,
    reason_codes: Sequence[str],
    suggested_groups: Sequence[Sequence[str]],
    head_sha: str,
) -> None:
    body = format_split_request_body(
        effective_lines=effective_lines,
        effective_files=effective_files,
        raw_diff_tokens=raw_diff_tokens,
        max_effective_lines=max_effective_lines,
        max_effective_files=max_effective_files,
        max_raw_diff_tokens=max_raw_diff_tokens,
        reason_codes=reason_codes,
        suggested_groups=suggested_groups,
        head_sha=head_sha,
    )
    _validate_github_body(body)
    await client.post(
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        json_data={"body": body, "event": "COMMENT"},
    )


async def submit_spec_gate_review(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    reason: str,
) -> None:
    body = "\n".join([
        BOT_REVIEW_MARKER,
        "",
        "### 판정: 🚫 조건 불충분 — 리뷰 차단",
        "",
        f"> {reason}",
        "",
        "**spec 문서를 추가한 뒤 다시 push 해주세요.** 리뷰는 조건 충족 후 자동 실행됩니다.",
    ])
    await client.post(
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        json_data={"body": body, "event": "COMMENT"},
    )
