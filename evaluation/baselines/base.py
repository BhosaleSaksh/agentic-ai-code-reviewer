"""Abstract base class for all benchmark baselines and ablations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from evaluation.models.case import EvaluationInput
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class BaseBaseline(ABC):
    """Abstract interface implemented by all reviewer architectures under evaluation."""

    def __init__(
        self,
        name: str,
        description: str,
        mode: str = "offline",
    ) -> None:
        self.name = name
        self.description = description
        self.mode = mode.lower()  # "offline" or "real"
        self.execution_mode = "offline_mock" if self.mode == "offline" else "real_llm"
        self.provider_name = (
            "offline_simulator" if self.mode == "offline" else "unknown"
        )
        self.model_name = "deterministic_mock" if self.mode == "offline" else "unknown"

    @abstractmethod
    async def evaluate_case(
        self, case: EvaluationInput
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Execute the reviewer baseline against an evaluation input.

        Args:
            case: Clean EvaluationInput strictly containing only code, diff, and PR context.
                Ground-truth defect specifications are strictly omitted to prevent leakage.

        Returns:
            tuple[list[NormalizedFinding], ResourceUsage]:
                - List of normalized predicted findings emitted by the reviewer
                - Telemetry record of latency, token volumes, and estimated cost
        """
        raise NotImplementedError
