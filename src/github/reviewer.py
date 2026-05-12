from src.github.client import GitHubClient
from src.models.review import Decision, Mismatch, ReviewResult, SpecStatus
from src.review.decision import compute_decision


BOT_REVIEW_MARKER = "## 🤖 스펙 정합성 리뷰"


def filter_bot_reviews(reviews: list[dict]) -> list[dict]:
    return [r for r in reviews if BOT_REVIEW_MARKER in (r.get("body") or "")]


def _escape_table_cell(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("|", r"\|")
    return " ".join(text.split())


def _format_location(m: Mismatch) -> str:
    if m.file is None:
        return "_전체 PR_"
    safe = _escape_table_cell(m.file)
    if m.line:
        return f"`{safe}:{m.line}`"
    return f"`{safe}`"


_VERDICT_LABEL = {
    Decision.APPROVE: "✅ 스펙 부합 (Approve)",
    Decision.REQUEST_CHANGES: "❌ 수정 필요 (Request Changes)",
    Decision.COMMENT: "💬 Comment",
}


def format_review_body(result: ReviewResult) -> str:
    decision = compute_decision(result)
    lines = [BOT_REVIEW_MARKER, "", result.summary]

    if result.spec_status == SpecStatus.MISSING:
        lines.extend([
            "",
            "> PR 본문에 스펙·요구사항 문서가 첨부되지 않아 코드 변경의 의도 정합성을 검증할 수 없습니다.",
            "> 요구사항을 인라인으로 추가하거나, 스펙 문서/티켓 링크를 PR 본문에 포함시켜주세요.",
        ])
    elif result.mismatches:
        lines.extend([
            "",
            "### 스펙과 불일치",
            "| # | 항목 | 위치 | 제안 |",
            "|---|------|------|------|",
        ])
        for idx, m in enumerate(result.mismatches, 1):
            desc = _escape_table_cell(m.description)
            sugg = _escape_table_cell(m.suggestion)
            loc = _format_location(m)
            lines.append(f"| {idx} | {desc} | {loc} | {sugg} |")

    if result.architecture_concern:
        lines.extend([
            "",
            "### 아키텍처 우려",
            f"> {result.architecture_concern}",
        ])

    lines.append("")
    lines.append(f"### 판정: {_VERDICT_LABEL[decision]}")

    return "\n".join(lines)


async def submit_review(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    result: ReviewResult,
) -> None:
    # 기본 GITHUB_TOKEN은 GitHub 정책상 APPROVE 이벤트를 거부한다(422).
    # 봇의 결정은 본문 라벨로 노출하고, API 이벤트는 항상 COMMENT로 통일.
    body = format_review_body(result)
    await client.post(
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        json_data={"body": body, "event": "COMMENT"},
    )
