"""Static analysis evidence matcher correlating candidate findings with deterministic tool findings."""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.evidence import EvidenceModel
from app.schemas.finding import ReviewFinding
from app.schemas.verification import EvidenceMatch

logger = logging.getLogger(__name__)


class StaticEvidenceMatcher:
    """Matches and correlates candidate findings with deterministic static analysis evidence."""

    def __init__(self, line_proximity_window: int = 3) -> None:
        self.proximity_window = line_proximity_window

    def match_finding_evidence(
        self,
        finding: ReviewFinding,
        available_evidence: list[EvidenceModel] | list[dict[str, Any]] | None,
    ) -> list[EvidenceMatch]:
        """Correlate a candidate finding with all available static analysis evidence items."""
        matches: list[EvidenceMatch] = []
        if not available_evidence or not finding.affected_file:
            return matches

        clean_file = finding.affected_file.replace("\\", "/").strip().lstrip("./")

        for item in available_evidence:
            ev_model: EvidenceModel
            if isinstance(item, EvidenceModel):
                ev_model = item
            elif isinstance(item, dict):
                try:
                    ev_model = EvidenceModel.model_validate(item)
                except Exception:
                    continue
            else:
                continue

            ev_file = (ev_model.file_path or "").replace("\\", "/").strip().lstrip("./")
            if not self._is_file_path_match(clean_file, ev_file):
                continue

            # Check coordinate alignment
            s_line = ev_model.start_line
            e_line = ev_model.end_line
            finding_line = finding.line_number

            is_direct = s_line <= finding_line <= e_line
            is_proximate = (
                abs(s_line - finding_line) <= self.proximity_window
                or abs(e_line - finding_line) <= self.proximity_window
            )

            if not (is_direct or is_proximate):
                continue

            # Check correlation or contradiction
            contradicts = self._check_contradiction(finding, ev_model)
            note = (
                f"Exact match on {ev_model.corroborating_tool or 'tool'} rule {ev_model.rule_or_cve_id or 'unknown'}"
                if is_direct
                else f"Proximate match within {self.proximity_window} lines of {ev_model.corroborating_tool or 'tool'}"
            )

            match = EvidenceMatch(
                evidence_type=ev_model.evidence_type,
                file_path=ev_model.file_path,
                start_line=ev_model.start_line,
                end_line=ev_model.end_line,
                snippet=ev_model.snippet,
                corroborating_tool=ev_model.corroborating_tool,
                rule_or_cve_id=ev_model.rule_or_cve_id,
                is_direct_match=is_direct,
                contradicts=contradicts,
                notes=note,
            )
            matches.append(match)

        return matches

    def extract_correlated_evidence_models(
        self,
        finding: ReviewFinding,
        available_evidence: list[EvidenceModel] | list[dict[str, Any]],
    ) -> list[EvidenceModel]:
        """Return the actual EvidenceModel objects that correlate with the finding."""
        matches = self.match_finding_evidence(finding, available_evidence)
        correlated: list[EvidenceModel] = []
        for m in matches:
            if not m.contradicts:
                correlated.append(
                    EvidenceModel(
                        evidence_type=m.evidence_type,
                        file_path=m.file_path,
                        start_line=m.start_line,
                        end_line=m.end_line,
                        snippet=m.snippet,
                        rule_or_cve_id=m.rule_or_cve_id,
                        corroborating_tool=m.corroborating_tool,
                        metadata={
                            "matched_by": "StaticEvidenceMatcher",
                            "is_direct": m.is_direct_match,
                        },
                    )
                )
        return correlated

    def _is_file_path_match(self, path1: str, path2: str) -> bool:
        """Check if two normalized file paths refer to the same file."""
        return (
            path1 == path2 or path1.endswith("/" + path2) or path2.endswith("/" + path1)
        )

    def _check_contradiction(
        self, _finding: ReviewFinding, evidence: EvidenceModel
    ) -> bool:
        """Check if an evidence item explicitly contradicts the candidate finding.

        For instance, if evidence shows a linter suppressed or marked safe, or if
        the rule clearly pertains to an opposite domain.
        """
        # Contradiction flag in metadata if tool output says clean
        return bool(evidence.metadata and evidence.metadata.get("is_safe") is True)
