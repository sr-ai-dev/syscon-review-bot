from src.github.client import GitHubClient
from src.models.review import Decision, Issue, ReviewResult


BOT_REVIEW_MARKER = "## 🤖 코드 리뷰"


def filter_bot_reviews(reviews: list[dict]) -> list[dict]:
    return [r for r in reviews if BOT_REVIEW_MARKER in (r.get("body") or "")]


def _escape_table_cell(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("|", r"\|")
    text = " ".join(text.split())
    return text


def _format_location(issue: Issue) -> str:
    if issue.file is None:
        return "_전체 PR_"
    safe_file = _escape_table_cell(issue.file)
    if issue.line:
        return f"`{safe_file}:{issue.line}`"
    return f"`{safe_file}`"


def _format_issue_table(issues: list[Issue], header: str) -> list[str]:
    lines = ["", header, "| # | 이슈 | 파일 | 제안 |", "|---|------|------|------|"]
    for idx, issue in enumerate(issues, 1):
        desc = _escape_table_cell(issue.description)
        sugg = _escape_table_cell(issue.suggestion)
        loc = _format_location(issue)
        lines.append(f"| {idx} | {desc} | {loc} | {sugg} |")
    return lines


def format_review_body(result: ReviewResult) -> str:
    lines = [
        f"{BOT_REVIEW_MARKER} — 점수: {result.score}/10",
        "",
        result.summary,
        "",
        "---",
    ]

    critical = [i for i in result.issues if i.severity == "critical"]
    warnings = [i for i in result.issues if i.severity == "warning"]
    minor = [i for i in result.issues if i.severity == "minor"]

    if critical:
        lines.extend(_format_issue_table(critical, "### 🔴 필수 수정"))
    if warnings:
        lines.extend(_format_issue_table(warnings, "### 🟡 권고"))
    if minor:
        lines.extend(_format_issue_table(minor, "### 🔵 마이너"))

    if result.good_points:
        lines.append("")
        lines.append("### 👍 잘된 점")
        for point in result.good_points:
            lines.append(f"- {point}")

    decision_label = {
        Decision.APPROVE: "✅ Approve",
        Decision.COMMENT: "💬 Comment",
        Decision.REQUEST_CHANGES: "❌ Request Changes",
    }[result.decision]
    lines.append("")
    lines.append(f"### 판정: {decision_label}")

    return "\n".join(lines)


async def submit_review(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    result: ReviewResult,
) -> None:
    body = format_review_body(result)
    event = {
        Decision.APPROVE: "APPROVE",
        Decision.COMMENT: "COMMENT",
        Decision.REQUEST_CHANGES: "REQUEST_CHANGES",
    }[result.decision]

    await client.post(
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        json_data={"body": body, "event": event},
    )
