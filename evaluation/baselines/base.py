"""Abstract base class for all benchmark baselines and ablations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from evaluation.models.case import EvaluationCase
from evaluation.models.finding import NormalizedFinding
from evaluation.models.metrics import ResourceUsage


class BaseBaseline(ABC):
    """Abstract interface implemented by all reviewer architectures under evaluation."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    @abstractmethod
    async def evaluate_case(
        self, case: EvaluationCase
    ) -> tuple[list[NormalizedFinding], ResourceUsage]:
        """Execute the reviewer baseline against an evaluation case.

        Args:
            case: Authoritative EvaluationCase containing source code/diff under review.

        Returns:
            tuple[list[NormalizedFinding], ResourceUsage]:
                - List of normalized predicted findings emitted by the reviewer
                - Telemetry record of latency, token volumes, and estimated cost
        """
        raise NotImplementedError
