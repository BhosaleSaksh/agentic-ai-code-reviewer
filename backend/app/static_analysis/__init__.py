"""Static code analysis subsystem for Phase 2.1 & Phase 2.2.

Exports containerized analyzers (Semgrep, Bandit, pip-audit), container execution service,
path safety utilities, static analysis orchestrator, and evidence normalizer.
"""

from app.schemas.static_analysis import (
    BanditFinding,
    BanditResult,
    PipAuditFinding,
    PipAuditResult,
    SemgrepFinding,
    SemgrepResult,
    StaticAnalysisExecutionStatus,
    ToolAnalysisSummary,
)
from app.static_analysis.bandit_runner import BanditRunner
from app.static_analysis.base_runner import BaseStaticAnalyzer
from app.static_analysis.container_runner import (
    ContainerExecutionConfig,
    ContainerExecutionResult,
    ContainerExecutionService,
)
from app.static_analysis.evidence_normalizer import (
    normalize_bandit_result,
    normalize_pip_audit_result,
    normalize_semgrep_result,
    normalize_tool_analysis_summary,
)
from app.static_analysis.path_utils import (
    PathTraversalSecurityError,
    normalize_reported_path,
)
from app.static_analysis.pip_audit_runner import (
    PipAuditRunner,
    find_dependency_line,
)
from app.static_analysis.semgrep_runner import SemgrepRunner
from app.static_analysis.service import StaticAnalysisService

__all__ = [
    # Schemas
    "StaticAnalysisExecutionStatus",
    "SemgrepFinding",
    "SemgrepResult",
    "BanditFinding",
    "BanditResult",
    "PipAuditFinding",
    "PipAuditResult",
    "ToolAnalysisSummary",
    # Infrastructure & runners
    "ContainerExecutionConfig",
    "ContainerExecutionResult",
    "ContainerExecutionService",
    "BaseStaticAnalyzer",
    "SemgrepRunner",
    "BanditRunner",
    "PipAuditRunner",
    "StaticAnalysisService",
    # Normalization
    "normalize_semgrep_result",
    "normalize_bandit_result",
    "normalize_pip_audit_result",
    "normalize_tool_analysis_summary",
    # Utilities
    "normalize_reported_path",
    "PathTraversalSecurityError",
    "find_dependency_line",
]
