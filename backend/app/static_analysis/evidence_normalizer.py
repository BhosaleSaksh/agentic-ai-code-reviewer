"""Evidence normalization layer transforming tool-specific results into canonical EvidenceModels.

Converts SemgrepResult, BanditResult, and PipAuditResult into unified EvidenceModel
instances while preserving complete provenance, line coordinates, and rule metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.enums import EvidenceType
from app.schemas.evidence import EvidenceModel
from app.schemas.static_analysis import (
    BanditResult,
    PipAuditResult,
    SemgrepResult,
    ToolAnalysisSummary,
)
from app.static_analysis.path_utils import normalize_reported_path

logger = logging.getLogger(__name__)


def normalize_semgrep_result(
    result: SemgrepResult,
    commit_sha: str | None = None,
) -> list[EvidenceModel]:
    """Normalize SemgrepResult findings into canonical EvidenceModel instances.

    Args:
        result: Structured Semgrep execution result.
        commit_sha: Commit SHA to enforce in provenance metadata.

    Returns:
        List of verified, strongly-typed EvidenceModel instances.
    """
    evidence_list: list[EvidenceModel] = []
    target_sha = commit_sha or result.workspace_commit_sha

    for finding in result.findings:
        safe_path = normalize_reported_path(finding.file_path)
        start_line = max(1, finding.start_line)
        end_line = max(start_line, finding.end_line)
        snippet = (
            finding.message.strip()
            if finding.message and finding.message.strip()
            else f"Semgrep rule violation: {finding.rule_id}"
        )

        metadata: dict[str, Any] = {
            "analyzer": result.analyzer,
            "analyzer_version": result.analyzer_version,
            "commit_sha": target_sha,
            "severity": finding.severity,
            "rule_id": finding.rule_id,
            "start_col": finding.start_col,
            "end_col": finding.end_col,
            "rule_metadata": finding.metadata,
        }
        if finding.raw_json:
            metadata["raw_json"] = finding.raw_json

        evidence = EvidenceModel(
            evidence_type=EvidenceType.STATIC_ANALYSIS,
            file_path=safe_path,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
            rule_or_cve_id=finding.rule_id[:100],
            corroborating_tool=result.analyzer[:50],
            metadata=metadata,
        )
        evidence_list.append(evidence)

    return evidence_list


def normalize_bandit_result(
    result: BanditResult,
    commit_sha: str | None = None,
) -> list[EvidenceModel]:
    """Normalize BanditResult findings into canonical EvidenceModel instances.

    Args:
        result: Structured Bandit execution result.
        commit_sha: Commit SHA to enforce in provenance metadata.

    Returns:
        List of verified, strongly-typed EvidenceModel instances.
    """
    evidence_list: list[EvidenceModel] = []
    target_sha = commit_sha or result.workspace_commit_sha

    for finding in result.findings:
        safe_path = normalize_reported_path(finding.file_path)

        if finding.line_range and len(finding.line_range) >= 2:
            start_line = max(1, min(finding.line_range))
            end_line = max(start_line, max(finding.line_range))
        else:
            start_line = max(1, finding.line_number)
            end_line = start_line

        if finding.code and finding.code.strip():
            snippet = finding.code.strip()
        else:
            snippet = f"Bandit issue {finding.test_id} ({finding.test_name}): {finding.issue_text.strip()}"

        rule_id = f"bandit.{finding.test_id}"

        metadata: dict[str, Any] = {
            "analyzer": result.analyzer,
            "analyzer_version": result.analyzer_version,
            "commit_sha": target_sha,
            "test_id": finding.test_id,
            "test_name": finding.test_name,
            "severity": finding.severity,
            "confidence": finding.confidence,
            "issue_text": finding.issue_text,
            "more_info": finding.more_info,
        }
        if finding.raw_json:
            metadata["raw_json"] = finding.raw_json

        evidence = EvidenceModel(
            evidence_type=EvidenceType.STATIC_ANALYSIS,
            file_path=safe_path,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
            rule_or_cve_id=rule_id[:100],
            corroborating_tool=result.analyzer[:50],
            metadata=metadata,
        )
        evidence_list.append(evidence)

    return evidence_list


def normalize_pip_audit_result(
    result: PipAuditResult,
    commit_sha: str | None = None,
) -> list[EvidenceModel]:
    """Normalize PipAuditResult findings into canonical EvidenceModel instances.

    Args:
        result: Structured pip-audit execution result.
        commit_sha: Commit SHA to enforce in provenance metadata.

    Returns:
        List of verified, strongly-typed EvidenceModel instances.
    """
    evidence_list: list[EvidenceModel] = []
    target_sha = commit_sha or result.workspace_commit_sha

    for finding in result.findings:
        safe_path = normalize_reported_path(finding.dependency_file)
        start_line = max(1, finding.line_number or 1)
        end_line = start_line

        desc_part = f": {finding.description.strip()}" if finding.description else ""
        snippet = (
            f"Vulnerable dependency: {finding.package_name}=={finding.package_version or 'unknown'} "
            f"({finding.vuln_id}){desc_part}"
        )

        # Prefer standard CVE identifier if available in aliases, otherwise vuln_id
        primary_id = finding.vuln_id
        for alias in finding.aliases:
            if alias.upper().startswith("CVE-"):
                primary_id = alias
                break

        metadata: dict[str, Any] = {
            "analyzer": result.analyzer,
            "analyzer_version": result.analyzer_version,
            "commit_sha": target_sha,
            "package_name": finding.package_name,
            "package_version": finding.package_version,
            "vuln_id": finding.vuln_id,
            "aliases": finding.aliases,
            "fix_versions": finding.fix_versions,
            "description": finding.description,
        }
        if finding.raw_json:
            metadata["raw_json"] = finding.raw_json

        evidence = EvidenceModel(
            evidence_type=EvidenceType.DEPENDENCY,
            file_path=safe_path,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
            rule_or_cve_id=primary_id[:100],
            corroborating_tool=result.analyzer[:50],
            metadata=metadata,
        )
        evidence_list.append(evidence)

    return evidence_list


def normalize_tool_analysis_summary(
    summary: ToolAnalysisSummary,
    max_items: int | None = None,
) -> list[EvidenceModel]:
    """Normalize all tool results in a ToolAnalysisSummary into a unified evidence list.

    Args:
        summary: Aggregated execution results from Semgrep, Bandit, and pip-audit.
        max_items: Optional maximum number of evidence items to retain.

    Returns:
        Consolidated list of canonical EvidenceModel items.
    """
    target_sha = summary.workspace_commit_sha
    all_evidence: list[EvidenceModel] = []

    # 1. Semgrep evidence
    all_evidence.extend(
        normalize_semgrep_result(summary.semgrep, commit_sha=target_sha)
    )

    # 2. Bandit evidence
    all_evidence.extend(normalize_bandit_result(summary.bandit, commit_sha=target_sha))

    # 3. pip-audit evidence (if executed)
    if summary.pip_audit is not None:
        all_evidence.extend(
            normalize_pip_audit_result(summary.pip_audit, commit_sha=target_sha)
        )

    if max_items is not None and len(all_evidence) > max_items:
        logger.warning(
            "Evidence items exceeded limit (%d > %d); truncating with provenance warning",
            len(all_evidence),
            max_items,
        )
        truncated = all_evidence[:max_items]
        return truncated

    return all_evidence
