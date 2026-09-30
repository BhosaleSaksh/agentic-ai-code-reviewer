"""Base static analyzer runner abstraction.

Defines the common interface and shared behavior for tool-specific static analysis runners,
ensuring consistent workspace validation, container service integration, and path normalization.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.workspace import WorkspaceContext
from app.static_analysis.container_runner import ContainerExecutionService
from app.static_analysis.path_utils import normalize_reported_path

logger = logging.getLogger(__name__)


class BaseStaticAnalyzer(ABC):
    """Abstract base class for containerized static analysis runners."""

    def __init__(
        self,
        container_service: ContainerExecutionService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.container_service = container_service or ContainerExecutionService()

    @property
    @abstractmethod
    def analyzer_name(self) -> str:
        """Return the lowercase canonical name of the analyzer (e.g. 'semgrep', 'bandit')."""
        ...

    @property
    @abstractmethod
    def analyzer_version(self) -> str:
        """Return the pinned version string of the analyzer."""
        ...

    def normalize_path(self, raw_path: str) -> str:
        """Normalize a tool-reported path into a safe workspace-relative POSIX path."""
        return normalize_reported_path(raw_path)

    def validate_workspace(self, workspace_context: WorkspaceContext) -> None:
        """Validate that the workspace context is well-formed and exists on disk.

        Args:
            workspace_context: The verified WorkspaceContext from Phase 1.9.

        Raises:
            FileNotFoundError: If the workspace path does not exist on disk.
        """
        if not workspace_context.workspace_path.is_dir():
            raise FileNotFoundError(
                f"Workspace path does not exist or is not a directory: {workspace_context.workspace_path}"
            )

    @abstractmethod
    async def run(self, workspace_context: WorkspaceContext, **kwargs: Any) -> Any:
        """Execute the static analyzer on the verified workspace.

        Args:
            workspace_context: Verified workspace snapshot.
            **kwargs: Analyzer-specific optional parameters.

        Returns:
            Tool-specific result model.
        """
        ...
