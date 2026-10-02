"""Planner context preparation, bounding, and large PR triage engine.

Transforms raw PullRequestContext and EvidenceModel collections into bounded,
sanitized, and prioritized context for the Planner Agent without exposing secrets
or risking prompt token exhaustion per Section 9, 12, and 13.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.orchestration.errors import EvidenceValidationError
from app.schemas.diff import ParsedDiff
from app.schemas.evidence import EvidenceModel
from app.schemas.github import PullRequestContext

logger = logging.getLogger(__name__)

# Files that should never have their diff content forwarded to the LLM
FORBIDDEN_FILE_PATTERNS = (
    ".env",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    "credentials",
    "secrets.yaml",
    "secrets.json",
)


class PreparedPlannerContext(BaseModel):
    """Strongly typed, bounded context prepared specifically for Planner Agent consumption."""

    model_config = ConfigDict(frozen=True)

    pr_title: str | None = None
    pr_author: str | None = None
    commit_sha: str
    base_sha: str | None = None
    repository_full_name: str
    changed_files: list[str]
    total_files: int
    total_additions: int
    total_deletions: int

    # Large PR triage
    is_large_pr: bool
    chunking_strategy: str | None
    file_chunks: list[list[str]]

    # Evidence Context
    evidence_items: list[dict[str, Any]]
    evidence_summary: dict[str, int]
    evidence_items_total: int
    evidence_items_included: int
    evidence_truncated: bool

    # Diff Context
    formatted_diff: str
    diff_lines_total: int
    diff_lines_included: int
    diff_bytes: int
    diff_truncated: bool

    # Metadata & Provenance
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlannerContextBuilder:
    """Builder responsible for bounding diffs, sanitizing evidence, and identifying large PRs."""

    def __init__(
        self,
        max_diff_lines: int = 400,
        max_diff_bytes: int = 50_000,
        max_evidence_items: int = 50,
        large_pr_loc_threshold: int = 400,
        large_pr_file_threshold: int = 20,
    ) -> None:
        self.max_diff_lines = max_diff_lines
        self.max_diff_bytes = max_diff_bytes
        self.max_evidence_items = max_evidence_items
        self.large_pr_loc_threshold = large_pr_loc_threshold
        self.large_pr_file_threshold = large_pr_file_threshold

    def _is_sensitive_file(self, file_path: str) -> bool:
        """Check if file path matches sensitive credential/secret filenames."""
        lower = file_path.lower()
        return any(pat in lower for pat in FORBIDDEN_FILE_PATTERNS)

    def _partition_files_into_chunks(
        self, changed_files: list[str], max_chunk_size: int = 8
    ) -> list[list[str]]:
        """Partition modified files into module-level chunks for future specialist fan-out."""
        if not changed_files:
            return []

        # Group by top-level or second-level directory
        module_groups: dict[str, list[str]] = defaultdict(list)
        for path_str in changed_files:
            p = PurePosixPath(path_str)
            parts = p.parts
            module_key = "/".join(parts[:2]) if len(parts) > 1 else "root"
            module_groups[module_key].append(path_str)

        chunks: list[list[str]] = []
        for _mod, files in module_groups.items():
            for i in range(0, len(files), max_chunk_size):
                chunks.append(files[i : i + max_chunk_size])

        return chunks

    def build(
        self,
        pr_context: PullRequestContext | dict[str, Any],
        evidence_items: Sequence[EvidenceModel | dict[str, Any]] | None,
        expected_commit_sha: str,
    ) -> PreparedPlannerContext:
        """Construct bounded and verified context for the Planner Agent."""
        expected_sha = expected_commit_sha.strip().lower()

        # 1. Extract and normalize PR context
        base_sha: str | None = None
        if isinstance(pr_context, PullRequestContext):
            repo_name = pr_context.repository_full_name
            pr_sha = pr_context.head_sha.strip().lower()
            base_sha = pr_context.base_sha
            title = pr_context.metadata.title if pr_context.metadata else ""
            author = pr_context.metadata.author if pr_context.metadata else ""
            changed_files = [f.filename for f in pr_context.files]
            parsed_diff = pr_context.parsed_diff
            raw_diff = pr_context.raw_diff
        elif isinstance(pr_context, dict):
            repo_name = str(pr_context.get("repository_full_name", ""))
            pr_sha = str(pr_context.get("head_sha", "")).strip().lower()
            base_sha = (
                str(pr_context["base_sha"]).strip().lower()
                if pr_context.get("base_sha")
                else None
            )
            title = str(pr_context.get("title", ""))
            author = str(pr_context.get("author", ""))
            changed_files = list(pr_context.get("changed_files", []))
            raw_diff = str(pr_context.get("raw_diff", ""))
            raw_parsed = pr_context.get("parsed_diff")
            if isinstance(raw_parsed, ParsedDiff):
                parsed_diff = raw_parsed
            elif isinstance(raw_parsed, dict):
                parsed_diff = ParsedDiff.model_validate(raw_parsed)
            else:
                parsed_diff = None
        else:
            raise TypeError(f"Unsupported pr_context type: {type(pr_context).__name__}")

        # 2. Enforce strict commit SHA alignment
        if pr_sha and pr_sha != expected_sha:
            raise EvidenceValidationError(
                message=(
                    f"Commit SHA mismatch in PR context: expected {expected_sha}, "
                    f"got {pr_sha}"
                ),
                expected_commit_sha=expected_sha,
                actual_commit_sha=pr_sha,
            )

        # 3. Process, validate, and prioritize evidence items
        raw_evidence_list = evidence_items or []
        total_evidence_count = len(raw_evidence_list)
        normalized_evidence: list[EvidenceModel] = []

        for item in raw_evidence_list:
            if isinstance(item, EvidenceModel):
                ev = item
            else:
                ev = EvidenceModel.model_validate(item)

            # Validate commit SHA provenance if recorded in evidence metadata
            if ev.metadata and "commit_sha" in ev.metadata:
                ev_sha = str(ev.metadata["commit_sha"]).strip().lower()
                if ev_sha != expected_sha:
                    raise EvidenceValidationError(
                        message=(
                            f"Evidence item for {ev.file_path}:{ev.start_line} belongs to "
                            f"commit {ev_sha}, but review run expects {expected_sha}"
                        ),
                        expected_commit_sha=expected_sha,
                        actual_commit_sha=ev_sha,
                    )

            normalized_evidence.append(ev)

        # Deduplicate evidence
        seen_evidence_keys: set[tuple[str, int, int, str | None, str | None]] = set()
        deduped_evidence: list[EvidenceModel] = []
        for ev in normalized_evidence:
            key = (
                ev.file_path,
                ev.start_line,
                ev.end_line,
                ev.rule_or_cve_id,
                ev.corroborating_tool,
            )
            if key not in seen_evidence_keys:
                seen_evidence_keys.add(key)
                deduped_evidence.append(ev)

        # Count evidence by tool
        evidence_summary: dict[str, int] = defaultdict(int)
        for ev in deduped_evidence:
            tool = (ev.corroborating_tool or ev.evidence_type.value).lower()
            evidence_summary[tool] += 1

        # Bound evidence items
        evidence_truncated = len(deduped_evidence) > self.max_evidence_items
        bounded_evidence = deduped_evidence[: self.max_evidence_items]
        serialized_evidence = [e.model_dump(by_alias=True) for e in bounded_evidence]

        # 4. Process and bound diff context
        total_additions = 0
        total_deletions = 0
        formatted_diff_lines: list[str] = []
        diff_lines_total = 0
        diff_lines_included = 0
        diff_bytes = 0
        diff_truncated = False

        if parsed_diff:
            total_additions = parsed_diff.total_additions
            total_deletions = parsed_diff.total_deletions
            if not changed_files:
                changed_files = [f.path for f in parsed_diff.files]

            for diff_file in parsed_diff.files:
                target_path = diff_file.path
                if self._is_sensitive_file(target_path):
                    formatted_diff_lines.append(
                        f"--- {target_path} [EXCLUDED: SENSITIVE FILE]"
                    )
                    continue

                formatted_diff_lines.append(
                    f"\n--- a/{diff_file.old_path or target_path}"
                )
                formatted_diff_lines.append(
                    f"+++ b/{diff_file.new_path or target_path}"
                )

                for hunk in diff_file.hunks:
                    hunk_header = (
                        hunk.header
                        if hunk.header
                        else f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@"
                    )
                    formatted_diff_lines.append(hunk_header)

                    for line in hunk.lines:
                        diff_lines_total += 1
                        if diff_lines_included >= self.max_diff_lines:
                            diff_truncated = True
                            continue
                        if diff_bytes >= self.max_diff_bytes:
                            diff_truncated = True
                            continue

                        prefix = (
                            "+" if line.is_added else ("-" if line.is_deleted else " ")
                        )
                        formatted_line = f"{prefix}{line.content}"
                        formatted_diff_lines.append(formatted_line)
                        diff_lines_included += 1
                        diff_bytes += len(formatted_line.encode("utf-8")) + 1

        elif raw_diff:
            for raw_line in raw_diff.splitlines():
                diff_lines_total += 1
                if diff_lines_included >= self.max_diff_lines:
                    diff_truncated = True
                    continue
                if diff_bytes >= self.max_diff_bytes:
                    diff_truncated = True
                    continue

                formatted_diff_lines.append(raw_line)
                diff_lines_included += 1
                diff_bytes += len(raw_line.encode("utf-8")) + 1

        formatted_diff = "\n".join(formatted_diff_lines)

        # 5. Large PR Triage & Chunking Strategy
        total_loc_changed = total_additions + total_deletions
        is_large_pr = (
            total_loc_changed > self.large_pr_loc_threshold
            or len(changed_files) > self.large_pr_file_threshold
        )

        if is_large_pr:
            chunking_strategy = "FILE_MODULE"
            file_chunks = self._partition_files_into_chunks(changed_files)
        else:
            chunking_strategy = "NONE"
            file_chunks = [changed_files] if changed_files else []

        logger.info(
            "Prepared planner context: commit=%s, files=%d, loc=%d, is_large=%s, "
            "diff_lines=%d/%d (trunc=%s), evidence=%d/%d (trunc=%s)",
            expected_sha[:8],
            len(changed_files),
            total_loc_changed,
            is_large_pr,
            diff_lines_included,
            diff_lines_total,
            diff_truncated,
            len(bounded_evidence),
            total_evidence_count,
            evidence_truncated,
        )

        return PreparedPlannerContext(
            pr_title=title,
            pr_author=author,
            commit_sha=expected_sha,
            base_sha=base_sha,
            repository_full_name=repo_name,
            changed_files=changed_files,
            total_files=len(changed_files),
            total_additions=total_additions,
            total_deletions=total_deletions,
            is_large_pr=is_large_pr,
            chunking_strategy=chunking_strategy,
            file_chunks=file_chunks,
            evidence_items=serialized_evidence,
            evidence_summary=dict(evidence_summary),
            evidence_items_total=total_evidence_count,
            evidence_items_included=len(bounded_evidence),
            evidence_truncated=evidence_truncated,
            formatted_diff=formatted_diff,
            diff_lines_total=diff_lines_total,
            diff_lines_included=diff_lines_included,
            diff_bytes=diff_bytes,
            diff_truncated=diff_truncated,
            metadata={
                "large_pr_threshold_loc": self.large_pr_loc_threshold,
                "large_pr_threshold_files": self.large_pr_file_threshold,
            },
        )
