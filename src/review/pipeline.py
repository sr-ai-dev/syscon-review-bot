"""Internal single/multi review orchestration with one shared cost budget."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from pydantic import BaseModel

from src.models.review import ReviewResult
from src.models.review_pipeline import ReviewPartial, ReviewPlan, ReviewRoute, ScopedFinding
from src.review.cost import (
    CostLedger,
    CostPolicy,
    estimate_preflight_nusd,
    estimate_request_ceiling_nusd,
)
from src.review.diff_parser import FileDiff
from src.review.errors import ReviewInfraCategory, ReviewInfraError
from src.review.prompt_builder import build_user_prompt
from src.review.token_counter import count_tokens
from src.review.tool_executor import ToolExecutor


class PreflightCostExceeded(RuntimeError):
    def __init__(self, estimated_nusd: int, limit_nusd: int):
        self.estimated_nusd = estimated_nusd
        self.limit_nusd = limit_nusd
        super().__init__(
            f"review preflight cost exceeds limit: estimated={estimated_nusd}, limit={limit_nusd}"
        )


@dataclass(frozen=True)
class PipelineOutcome:
    result: ReviewResult
    ledger: CostLedger


def _trim_history(history: list[str] | None, max_tokens: int) -> list[str]:
    kept: list[str] = []
    used = 0
    for item in reversed(history or []):
        item_tokens = count_tokens(item)
        if used + item_tokens > max_tokens:
            continue
        kept.append(item)
        used += item_tokens
    return list(reversed(kept))


def _scoped_prompt(base_prompt: str, unit_id: str, paths: list[str]) -> str:
    scope = "\n".join(f"- {path}" for path in paths)
    return (
        f"## 내부 검토 범위\nunit: {unit_id}\n담당 파일:\n{scope}\n\n"
        "담당 파일의 상세 결함을 검토하라. 다른 파일은 관계 확인에만 사용하라. "
        f"unit_id는 {unit_id}, covered_paths는 위 담당 파일 전체를 그대로 반환하라. "
        "finding category는 mismatch/spec_doc/architecture/bug/vulnerability/security/"
        "smell/complexity/advisory 중 하나를 사용하라. "
        "GitHub 게시용 문구를 만들지 말고 ReviewPartial JSON만 반환하라.\n\n"
        f"{base_prompt}"
    )


def _global_prompt(
    *,
    pr_title: str,
    pr_body: str,
    base_branch: str,
    head_branch: str,
    paths: list[str],
    conversation_history: list[str] | None,
) -> str:
    manifest = "\n".join(f"- {path}" for path in paths)
    history = "\n\n".join(conversation_history or [])
    return (
        "## 전역 검토\n"
        f"제목: {pr_title}\n설명: {pr_body}\n브랜치: {head_branch} → {base_branch}\n\n"
        f"전체 변경 파일:\n{manifest}\n\n"
        "모듈 경계, API/DB 호환성, 권한, transaction, 동시성, 스펙 문서와 이전 리뷰 상태를 검토하라. "
        "unit_id는 global, covered_paths는 전체 변경 파일을 그대로 반환하라. "
        "finding category는 mismatch/spec_doc/architecture/bug/vulnerability/security/"
        "smell/complexity/advisory 중 하나를 사용하라. "
        "필요한 본문은 read_file/grep으로 확인하라. 근거 없는 finding은 만들지 마라.\n\n"
        f"이전 리뷰와 대화:\n{history}"
    )


def _synthesis_prompts(results: list[BaseModel], paths: list[str]) -> tuple[str, str]:
    system = (
        "너는 PR 리뷰 통합기다. 입력된 내부 리뷰 결과만 병합하라. "
        "새 finding을 만들거나 기존 finding을 제거·재작성하지 마라. "
        "file, line, category, description, spec_status, aligned를 그대로 유지하라. "
        "category mismatch/spec_doc/architecture/advisory는 각 동명 결과 목록으로, "
        "bug/vulnerability/security/smell/complexity는 quality_findings로 옮겨라. "
        "최종 출력은 요구된 ReviewResult JSON schema를 정확히 지켜라. 한국어로 작성하라."
    )
    payload = "\n\n".join(
        f"### 내부 결과 {index}\n{result.model_dump_json(indent=2)}"
        for index, result in enumerate(results, 1)
    )
    manifest = "\n".join(f"- {path}" for path in paths)
    user = f"## 전체 변경 파일\n{manifest}\n\n## 병합 대상\n{payload}"
    return system, user


def _normalized_description(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def reduce_review_results(
    results: list[ReviewResult], paths: list[str]
) -> ReviewResult:
    """Deterministically deduplicate and order internal results before synthesis."""
    path_index = {path: index for index, path in enumerate(paths)}
    fields = (
        "mismatches",
        "spec_doc_findings",
        "architecture_findings",
        "quality_findings",
        "advisory_findings",
    )
    reduced: dict[str, list] = {}
    active_descriptions: set[str] = set()
    for field_name in fields:
        unique: dict[tuple, object] = {}
        for result in results:
            for finding in getattr(result, field_name):
                category = getattr(finding, "category", field_name)
                key = (
                    finding.file,
                    finding.line,
                    str(category),
                    _normalized_description(finding.description),
                )
                current = unique.get(key)
                if current is None or finding.confidence > current.confidence:
                    unique[key] = finding
        ordered = sorted(
            unique.values(),
            key=lambda finding: (
                path_index.get(finding.file, len(path_index)),
                finding.line or 0,
                str(getattr(finding, "category", field_name)),
                _normalized_description(finding.description),
            ),
        )
        reduced[field_name] = ordered
        active_descriptions.update(
            _normalized_description(finding.description) for finding in ordered
        )

    summaries = list(dict.fromkeys(result.summary.strip() for result in results if result.summary.strip()))
    prior_resolved = list(
        dict.fromkeys(
            item
            for result in results
            for item in result.prior_resolved
            if _normalized_description(item) not in active_descriptions
        )
    )
    return ReviewResult(
        spec_status=(
            "present" if any(result.spec_status.value == "present" for result in results) else "missing"
        ),
        aligned=all(result.aligned for result in results),
        summary=" / ".join(summaries),
        prior_resolved=prior_resolved,
        **reduced,
    )


def _validate_result_scope(result: ReviewResult, allowed_paths: set[str]) -> None:
    fields = (
        "mismatches",
        "spec_doc_findings",
        "architecture_findings",
        "quality_findings",
        "advisory_findings",
    )
    unexpected = sorted(
        {
            finding.file
            for field_name in fields
            for finding in getattr(result, field_name)
            if finding.file is not None and finding.file not in allowed_paths
        }
    )
    if unexpected:
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Internal reviewer returned findings outside its assigned file scope",
        )


def _validate_partial(
    partial: ReviewPartial, expected_unit_id: str, expected_paths: list[str]
) -> None:
    if partial.unit_id != expected_unit_id:
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Internal reviewer returned the wrong unit id",
        )
    if len(partial.covered_paths) != len(set(partial.covered_paths)) or set(
        partial.covered_paths
    ) != set(expected_paths):
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Internal reviewer did not attest complete file coverage",
        )
    allowed_paths = set(expected_paths)
    allowed_categories = {
        "mismatch",
        "spec_doc",
        "architecture",
        "bug",
        "vulnerability",
        "security",
        "smell",
        "complexity",
        "advisory",
    }
    if any(finding.category.casefold() not in allowed_categories for finding in partial.findings):
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Internal reviewer returned an unsupported finding category",
        )
    if any(
        finding.file is not None and finding.file not in allowed_paths
        for finding in partial.findings
    ):
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Internal reviewer returned findings outside its assigned file scope",
        )


def _finding_key(category: str, finding: object) -> tuple:
    return (
        category,
        finding.file,
        finding.line,
        _normalized_description(finding.description),
    )


def _validate_synthesis_result(
    result: ReviewResult, partial: ReviewPartial
) -> None:
    expected = {
        _finding_key(finding.category.casefold(), finding)
        for finding in partial.findings
    }
    actual = {
        *(_finding_key("mismatch", finding) for finding in result.mismatches),
        *(_finding_key("spec_doc", finding) for finding in result.spec_doc_findings),
        *(_finding_key("architecture", finding) for finding in result.architecture_findings),
        *(_finding_key(finding.category.value, finding) for finding in result.quality_findings),
        *(_finding_key("advisory", finding) for finding in result.advisory_findings),
    }
    if actual != expected:
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Synthesis changed the reviewed finding set",
        )
    if result.spec_status is not partial.spec_status or result.aligned != partial.aligned:
        raise ReviewInfraError(
            ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
            "Synthesis changed the deterministic review status",
        )


def reduce_review_partials(
    partials: list[ReviewPartial], paths: list[str]
) -> ReviewPartial:
    path_index = {path: index for index, path in enumerate(paths)}
    severity_rank = {
        "critical": 5,
        "high": 4,
        "medium": 3,
        "low": 2,
        "advisory": 1,
    }
    unique: dict[tuple, ScopedFinding] = {}
    for partial in partials:
        for finding in partial.findings:
            key = (
                finding.file,
                finding.line,
                finding.category.casefold(),
                _normalized_description(finding.description),
            )
            current = unique.get(key)
            score = (severity_rank.get(finding.severity.casefold(), 0), finding.confidence)
            current_score = (
                severity_rank.get(current.severity.casefold(), 0),
                current.confidence,
            ) if current is not None else (-1, -1)
            if current is None or score > current_score:
                unique[key] = finding
    findings = sorted(
        unique.values(),
        key=lambda finding: (
            path_index.get(finding.file, len(path_index)),
            finding.line or 0,
            finding.category.casefold(),
            _normalized_description(finding.description),
        ),
    )
    summaries = list(
        dict.fromkeys(
            partial.summary.strip() for partial in partials if partial.summary.strip()
        )
    )
    active = {_normalized_description(finding.description) for finding in findings}
    prior_resolved = list(
        dict.fromkeys(
            item
            for partial in partials
            for item in partial.prior_resolved
            if _normalized_description(item) not in active
        )
    )
    return ReviewPartial(
        unit_id="reduced",
        covered_paths=paths,
        spec_status=(
            "present"
            if any(partial.spec_status.value == "present" for partial in partials)
            else "missing"
        ),
        aligned=all(partial.aligned for partial in partials),
        summary=" / ".join(summaries),
        findings=findings,
        prior_resolved=prior_resolved,
    )


def _request_envelopes(
    prompts: list[tuple[str, str]],
    *,
    output_cap: int,
    tool_turns: int,
    tool_result_cap: int,
    include_synthesis: bool,
) -> list[tuple[int, int]]:
    requests: list[tuple[int, int]] = []
    for system, user in prompts:
        base = count_tokens(system) + count_tokens(user) + 256
        for turn in range(tool_turns):
            growth = turn * (output_cap + tool_result_cap + 128)
            requests.append((base + growth, output_cap))
    if include_synthesis:
        synthesis_input = (
            sum(count_tokens(system) + count_tokens(user) for system, user in prompts)
            + len(prompts) * output_cap
            + 512
        )
        requests.append((synthesis_input, output_cap))
    return requests


async def run_review_pipeline(
    *,
    plan: ReviewPlan,
    files: list[FileDiff],
    gpt_client,
    system_prompt: str,
    pr_title: str,
    pr_body: str,
    base_branch: str,
    head_branch: str,
    model: str,
    cost_policy: CostPolicy,
    conversation_history: list[str] | None = None,
    tool_executor: ToolExecutor | None = None,
    max_tool_iterations: int = 8,
    reasoning_effort: str | None = None,
    include_judge: bool = False,
) -> PipelineOutcome:
    if plan.route is ReviewRoute.SPLIT_REQUEST:
        raise ValueError("split-request plans cannot execute the review pipeline")

    pricing = cost_policy.pricing_for(model)
    ledger = CostLedger(cost_policy, pricing)
    output_cap = cost_policy.max_completion_tokens_per_call
    conversation_history = _trim_history(
        conversation_history, cost_policy.max_history_tokens
    )
    by_path = {changed_file.path: changed_file for changed_file in files}

    if plan.route is ReviewRoute.SINGLE:
        user_prompt = build_user_prompt(
            files=files,
            pr_title=pr_title,
            pr_body=pr_body,
            base_branch=base_branch,
            head_branch=head_branch,
            conversation_history=conversation_history,
        )
        prompts = [(system_prompt, user_prompt)]
        use_tools = tool_executor is not None and reasoning_effort is None
        tool_turns = max_tool_iterations if use_tools else 1
        include_synthesis = False
    else:
        shared_docs = [
            changed_file
            for changed_file in files
            if changed_file.path.endswith((".md", ".mdx", ".rst"))
        ]
        prompts = []
        for unit in plan.units:
            owned = [by_path[path] for path in unit.paths]
            scoped_files = list({item.path: item for item in [*shared_docs, *owned]}.values())
            base_prompt = build_user_prompt(
                files=scoped_files,
                pr_title=pr_title,
                pr_body=pr_body,
                base_branch=base_branch,
                head_branch=head_branch,
            )
            prompts.append(
                (system_prompt, _scoped_prompt(base_prompt, unit.unit_id, unit.paths))
            )
        prompts.append(
            (
                system_prompt,
                _global_prompt(
                    pr_title=pr_title,
                    pr_body=pr_body,
                    base_branch=base_branch,
                    head_branch=head_branch,
                    paths=plan.coverage.required_paths,
                    conversation_history=conversation_history,
                ),
            )
        )
        use_tools = tool_executor is not None and reasoning_effort is None
        tool_turns = max_tool_iterations if use_tools else 1
        include_synthesis = True

    requests = _request_envelopes(
        prompts,
        output_cap=output_cap,
        tool_turns=tool_turns,
        tool_result_cap=cost_policy.max_tool_result_tokens_per_call,
        include_synthesis=include_synthesis,
    )
    if include_judge:
        requests.append((output_cap + 512, output_cap))
    if len(requests) > cost_policy.max_requests_per_pr:
        raise PreflightCostExceeded(cost_policy.hard_limit_nusd + 1, cost_policy.hard_limit_nusd)
    estimate = estimate_preflight_nusd(
        requests, pricing, margin_bps=cost_policy.preflight_margin_bps
    )
    if cost_policy.enabled and estimate > cost_policy.hard_limit_nusd:
        raise PreflightCostExceeded(estimate, cost_policy.hard_limit_nusd)

    if plan.route is ReviewRoute.SINGLE:
        result = await gpt_client.review(
            prompts[0][0],
            prompts[0][1],
            model=model,
            tool_executor=tool_executor,
            max_tool_iterations=tool_turns,
            reasoning_effort=reasoning_effort,
            max_completion_tokens=output_cap,
            cost_ledger=ledger,
            cost_stage="single",
        )
        return PipelineOutcome(result=result, ledger=ledger)

    synthesis_input, synthesis_output = requests[-(2 if include_judge else 1)]
    synthesis_ceiling = estimate_request_ceiling_nusd(
        synthesis_input,
        synthesis_output,
        pricing,
        margin_bps=cost_policy.preflight_margin_bps,
    )
    synthesis_reservation_id = "synthesis:planned"
    await ledger.reserve(synthesis_reservation_id, synthesis_ceiling)

    async def analyze(index: int, prompt: tuple[str, str]) -> ReviewPartial:
        expected_unit_id = (
            plan.units[index - 1].unit_id
            if index <= len(plan.units)
            else "global"
        )
        expected_paths = (
            plan.units[index - 1].paths
            if index <= len(plan.units)
            else plan.coverage.required_paths
        )
        partial = await gpt_client.review(
            prompt[0],
            prompt[1],
            model=model,
            tool_executor=tool_executor,
            max_tool_iterations=tool_turns,
            reasoning_effort=reasoning_effort,
            max_completion_tokens=output_cap,
            cost_ledger=ledger,
            cost_stage=f"analysis-{index}",
            response_model=ReviewPartial,
        )
        if not isinstance(partial, ReviewPartial):
            raise ReviewInfraError(
                ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
                "Internal reviewer did not return ReviewPartial",
            )
        _validate_partial(partial, expected_unit_id, expected_paths)
        return partial

    tasks = [
        asyncio.create_task(analyze(index, prompt))
        for index, prompt in enumerate(prompts, 1)
    ]
    try:
        partials = await asyncio.gather(*tasks)
        reduced = reduce_review_partials(list(partials), plan.coverage.required_paths)
        synthesis_system, synthesis_user = _synthesis_prompts(
            [reduced], plan.coverage.required_paths
        )
        final = await gpt_client.review(
            synthesis_system,
            synthesis_user,
            model=model,
            tool_executor=None,
            max_tool_iterations=1,
            reasoning_effort=reasoning_effort,
            max_completion_tokens=output_cap,
            cost_ledger=ledger,
            cost_stage="synthesis",
            pre_reserved_call_id=synthesis_reservation_id,
        )
        if not isinstance(final, ReviewResult):
            raise ReviewInfraError(
                ReviewInfraCategory.RESPONSE_SCHEMA_ERROR,
                "Synthesis did not return ReviewResult",
            )
        _validate_synthesis_result(final, reduced)
        return PipelineOutcome(result=final, ledger=ledger)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ledger.cancel_reservation(synthesis_reservation_id, missing_ok=True)
        raise
