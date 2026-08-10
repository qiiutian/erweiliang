from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from ifem.domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    CancellationToken,
    InputValidationError,
    ProjectAnalysisRequest,
    ProgressReporter,
    ValidationReport,
)


class ProjectReconstructionAlgorithm(ABC):
    """Base class for algorithms that consume the canonical project model.

    New reconstruction methods should subclass this type.  It keeps the legacy
    configuration dictionary out of new solvers while preserving the public
    ``ReconstructionAlgorithm`` protocol used by the registry and service.
    """

    def parameter_schema(self) -> Mapping[str, Any]:
        return {"type": "object", "properties": {}}

    def validate(self, context: AnalysisContext) -> ValidationReport:
        if context.project is None:
            return ValidationReport.invalid(
                "当前算法需要完整工程模型。",
                field="/model",
            )
        return self.validate_project(context.project_request())

    def validate_project(
        self,
        request: ProjectAnalysisRequest,
    ) -> ValidationReport:
        return ValidationReport.valid()

    def solve(
        self,
        context: AnalysisContext,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult:
        if context.project is None:
            raise InputValidationError(
                "当前算法需要完整工程模型。",
                field="/model",
            )
        return self.solve_project(
            context.project_request(),
            progress=progress,
            cancellation=cancellation,
        )

    @abstractmethod
    def solve_project(
        self,
        request: ProjectAnalysisRequest,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult:
        """Solve one project without importing Qt or a legacy config adapter."""
