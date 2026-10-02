"""Strongly typed review graph state schema for LangGraph workflow execution.

Corresponds to Section G of the project architecture:
defines the state container passed between graph nodes with strict validation,
tamper-evident commit SHA tracking, and safe isolation from secrets.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.review_plan import ReviewPlan
from app.schemas.verification import VerificationResult


def merge_candidate_findings(
    existing: list[dict[str, Any]] | None,
    new_findings: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer to merge candidate findings from concurrent specialist agents without duplicates."""
    combined: list[dict[str, Any]] = list(existing or [])
    if not new_findings:
        return combined

    seen_ids: set[str] = {
        str(f.get("finding_id") or f.get("id"))
        for f in combined
        if f.get("finding_id") or f.get("id")
    }
    seen_coords: set[tuple[str, Any, str]] = {
        (
            str(f.get("affected_file") or f.get("file_path") or "").strip(),
            f.get("line_number") or f.get("line"),
            str(f.get("title") or "").strip().lower(),
        )
        for f in combined
    }

    for finding in new_findings:
        fid = str(finding.get("finding_id") or finding.get("id"))
        if fid and fid in seen_ids:
            continue

        file_val = str(
            finding.get("affected_file") or finding.get("file_path") or ""
        ).strip()
        line_val = finding.get("line_number") or finding.get("line")
        title_val = str(finding.get("title") or "").strip().lower()
        coord = (file_val, line_val, title_val)

        if file_val and title_val and coord in seen_coords:
            continue

        if fid:
            seen_ids.add(fid)
        seen_coords.add(coord)
        combined.append(finding)
    return combined


def merge_specialist_errors(
    existing: list[dict[str, Any]] | None,
    new_errors: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer to merge error details from concurrent specialist agents."""
    combined: list[dict[str, Any]] = list(existing or [])
    if not new_errors:
        return combined
    combined.extend(new_errors)
    return combined


def merge_error_messages(
    existing: list[str] | None,
    new_messages: list[str] | None,
) -> list[str]:
    """Reducer to merge human-readable error strings."""
    combined: list[str] = list(existing or [])
    if not new_messages:
        return combined
    for msg in new_messages:
        if msg not in combined:
            combined.append(msg)
    return combined


def merge_verification_results(
    existing: list[dict[str, Any]] | None,
    new_results: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Reducer to merge verification decision results without duplicates."""
    combined: list[dict[str, Any]] = list(existing or [])
    if not new_results:
        return combined

    seen_ids: set[str] = {
        str(r.get("finding_id") or r.get("id"))
        for r in combined
        if r.get("finding_id") or r.get("id")
    }
    for res in new_results:
        fid = str(res.get("finding_id") or res.get("id"))
        if fid and fid in seen_ids:
            continue
        if fid:
            seen_ids.add(fid)
        combined.append(res)
    return combined


class ReviewState(TypedDict, total=False):
    """Canonical typed state representation for the LangGraph code review pipeline.

    Nodes in the graph mutate and return partial updates to this dictionary.
    No secrets, tokens, or entire repository files are permitted in this state.
    """

    # --- Identity & Run Context ---
    review_run_id: str
    repository_id: int
    repository_full_name: str
    pr_number: int
    commit_sha: str
    base_sha: str | None

    # --- PR Metadata (Sanitized) ---
    pr_title: str | None
    pr_author: str | None
    pr_metadata: dict[str, Any]

    # --- Workspace Context (Metadata Only - No Raw Files) ---
    workspace_metadata: dict[str, Any]

    # --- Diff Context ---
    parsed_diff: dict[str, Any] | None
    changed_files: list[str]
    diff_context_truncated: bool

    # --- Deterministic Static Analysis Evidence ---
    evidence_items: list[dict[str, Any]]

    # --- Scoping & Review Plan ---
    review_plan: dict[str, Any] | ReviewPlan | None

    # --- Specialist Candidate Findings (Concurrent Reducer) ---
    candidate_findings: Annotated[list[dict[str, Any]], merge_candidate_findings]
    specialist_errors: Annotated[list[dict[str, Any]], merge_specialist_errors]
    error_messages: Annotated[list[str], merge_error_messages]

    # --- Critic Verified & Rejected Findings (Concurrent Reducer) ---
    verified_findings: Annotated[list[dict[str, Any]], merge_candidate_findings]
    rejected_findings: Annotated[list[dict[str, Any]], merge_candidate_findings]
    verification_results: Annotated[list[dict[str, Any]], merge_verification_results]
    verification_errors: Annotated[list[dict[str, Any]], merge_specialist_errors]

    # --- Execution & Lifecycle Status ---
    status: str
    error: str | None
    error_category: str | None
    retry_count: int

    # --- Observability & Telemetry ---
    execution_metadata: dict[str, Any]


# Forbidden key patterns that must never appear in review state
FORBIDDEN_KEY_PATTERNS = (
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"private_key", re.IGNORECASE),
    re.compile(r"api_key", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
)

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def _sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively strip any keys matching forbidden secret patterns."""
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        if any(pattern.search(k) for pattern in FORBIDDEN_KEY_PATTERNS):
            continue
        if isinstance(v, dict):
            sanitized[k] = _sanitize_dict(v)
        elif isinstance(v, list):
            sanitized[k] = [
                _sanitize_dict(item) if isinstance(item, dict) else item for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized


def create_initial_review_state(
    review_run_id: str,
    repository_id: int,
    repository_full_name: str,
    pr_number: int,
    commit_sha: str,
    base_sha: str | None = None,
    pr_title: str | None = None,
    pr_author: str | None = None,
    pr_metadata: dict[str, Any] | None = None,
    workspace_metadata: dict[str, Any] | None = None,
    parsed_diff: dict[str, Any] | None = None,
    changed_files: list[str] | None = None,
    evidence_items: list[EvidenceModel | dict[str, Any]] | None = None,
) -> ReviewState:
    """Create a validated, sanitized initial ReviewState for a review run.

    Enforces commit SHA validity, validates repository references,
    and strips any potentially leaked secret keys.
    """
    if not review_run_id or not review_run_id.strip():
        raise ValueError("review_run_id cannot be blank")

    cleaned_sha = commit_sha.strip().lower()
    if not COMMIT_SHA_PATTERN.match(cleaned_sha):
        raise ValueError(
            f"Invalid commit_sha format: '{commit_sha}'. Must be a 40-character hex string."
        )

    if repository_id <= 0:
        raise ValueError(f"repository_id must be positive, got {repository_id}")

    if not repository_full_name or "/" not in repository_full_name:
        raise ValueError(
            f"repository_full_name must be 'owner/repo', got '{repository_full_name}'"
        )

    if pr_number <= 0:
        raise ValueError(f"pr_number must be positive, got {pr_number}")

    # Serialize and validate evidence items
    serialized_evidence: list[dict[str, Any]] = []
    if evidence_items:
        for item in evidence_items:
            if isinstance(item, EvidenceModel):
                serialized_evidence.append(item.model_dump(by_alias=True))
            elif isinstance(item, dict):
                # Validate against EvidenceModel to guarantee schema conformity
                validated = EvidenceModel.model_validate(item)
                serialized_evidence.append(validated.model_dump(by_alias=True))
            else:
                raise TypeError(
                    f"Expected EvidenceModel or dict for evidence item, got {type(item).__name__}"
                )

    sanitized_pr_meta = _sanitize_dict(pr_metadata or {})
    sanitized_ws_meta = _sanitize_dict(workspace_metadata or {})

    # Ensure no raw file trees or blobs are stored in workspace metadata
    sanitized_ws_meta.pop("files", None)
    sanitized_ws_meta.pop("file_contents", None)
    sanitized_ws_meta.pop("repo_tree", None)

    return ReviewState(
        review_run_id=str(review_run_id).strip(),
        repository_id=repository_id,
        repository_full_name=repository_full_name.strip(),
        pr_number=pr_number,
        commit_sha=cleaned_sha,
        base_sha=base_sha.strip().lower() if base_sha else None,
        pr_title=pr_title.strip() if pr_title else None,
        pr_author=pr_author.strip() if pr_author else None,
        pr_metadata=sanitized_pr_meta,
        workspace_metadata=sanitized_ws_meta,
        parsed_diff=parsed_diff,
        changed_files=changed_files or [],
        diff_context_truncated=False,
        evidence_items=serialized_evidence,
        review_plan=None,
        candidate_findings=[],
        specialist_errors=[],
        error_messages=[],
        verified_findings=[],
        rejected_findings=[],
        verification_results=[],
        verification_errors=[],
        status="PENDING",
        error=None,
        error_category=None,
        retry_count=0,
        execution_metadata={
            "created_at": datetime.now(UTC).isoformat(),
            "total_tokens": 0,
            "durations": {},
        },
    )


def extract_review_plan(state: ReviewState) -> ReviewPlan | None:
    """Helper to deserialize and validate the canonical ReviewPlan from state."""
    raw_plan = state.get("review_plan")
    if raw_plan is None:
        return None
    if isinstance(raw_plan, ReviewPlan):
        return raw_plan
    return ReviewPlan.model_validate(raw_plan)


def extract_candidate_findings(state: ReviewState) -> list[ReviewFinding]:
    """Helper to deserialize and validate canonical ReviewFinding items from state."""
    raw_findings = state.get("candidate_findings", [])
    findings: list[ReviewFinding] = []
    for item in raw_findings:
        if isinstance(item, ReviewFinding):
            findings.append(item)
        elif isinstance(item, dict):
            findings.append(ReviewFinding.model_validate(item))
    return findings


def extract_verified_findings(state: ReviewState) -> list[ReviewFinding]:
    """Helper to deserialize and validate verified ReviewFinding items from state."""
    raw_findings = state.get("verified_findings", [])
    findings: list[ReviewFinding] = []
    for item in raw_findings:
        if isinstance(item, ReviewFinding):
            findings.append(item)
        elif isinstance(item, dict):
            findings.append(ReviewFinding.model_validate(item))
    return findings


def extract_rejected_findings(state: ReviewState) -> list[ReviewFinding]:
    """Helper to deserialize and validate rejected ReviewFinding items from state."""
    raw_findings = state.get("rejected_findings", [])
    findings: list[ReviewFinding] = []
    for item in raw_findings:
        if isinstance(item, ReviewFinding):
            findings.append(item)
        elif isinstance(item, dict):
            findings.append(ReviewFinding.model_validate(item))
    return findings


def extract_verification_results(state: ReviewState) -> list[VerificationResult]:
    """Helper to deserialize and validate VerificationResult items from state."""
    raw_results = state.get("verification_results", [])
    results: list[VerificationResult] = []
    for item in raw_results:
        if isinstance(item, VerificationResult):
            results.append(item)
        elif isinstance(item, dict):
            results.append(VerificationResult.model_validate(item))
    return results
