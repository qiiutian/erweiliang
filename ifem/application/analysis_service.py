from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ifem.application.parameter_validation import (
    validate_parameter_schema,
    validate_parameters,
)
from ifem.domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    CancellationToken,
    ProgressReporter,
    ReconstructionAlgorithm,
    ValidationIssue,
    ValidationReport,
)


DEFAULT_ALGORITHM_ID = "ifem.beam2d.surface_integral.v1"


class AlgorithmValidationError(ValueError):
    """Raised when project data is incompatible with an algorithm."""

    def __init__(
        self,
        report: ValidationReport | str,
        *,
        preparation: "AnalysisPreparation | None" = None,
    ):
        if isinstance(report, ValidationReport):
            validation_report = report
        else:
            validation_report = ValidationReport.invalid(str(report))
        self.report = validation_report
        self.issues = validation_report.issues
        self.preparation = preparation
        message = validation_report.error_message or "算法输入校验失败。"
        super().__init__(message)


class AlgorithmResolutionStatus(str, Enum):
    READY = "ready"
    MISSING = "missing"
    VERSION_MISMATCH = "version_mismatch"
    SCHEMA_MISMATCH = "schema_mismatch"


@dataclass(frozen=True)
class AlgorithmResolution:
    identifier: str
    expected_version: str | None
    expected_schema_version: str | None
    algorithm: ReconstructionAlgorithm | None
    status: AlgorithmResolutionStatus
    report: ValidationReport = field(default_factory=ValidationReport.valid)

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return self.report.issues

    @property
    def is_ready(self) -> bool:
        return self.status is AlgorithmResolutionStatus.READY

    @property
    def available_version(self) -> str | None:
        if self.algorithm is None:
            return None
        return self.algorithm.metadata.version

    @property
    def available_schema_version(self) -> str | None:
        if self.algorithm is None:
            return None
        value = getattr(self.algorithm.metadata, "parameter_schema_version", None)
        return None if value in (None, "") else str(value)


@dataclass(frozen=True)
class AnalysisPreparation:
    resolution: AlgorithmResolution
    context: AnalysisContext
    effective_parameters: Mapping[str, Any]
    report: ValidationReport

    def __post_init__(self):
        object.__setattr__(self, "effective_parameters", dict(self.effective_parameters))

    @property
    def algorithm(self) -> ReconstructionAlgorithm | None:
        return self.resolution.algorithm

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        return self.report.issues

    @property
    def can_run(self) -> bool:
        return self.resolution.is_ready and self.report.is_valid


class AlgorithmRegistry:
    def __init__(self, algorithms: Iterable[ReconstructionAlgorithm] = ()):
        self._algorithms: dict[str, ReconstructionAlgorithm] = {}
        self._parameter_schemas: dict[str, dict[str, Any]] = {}
        for algorithm in algorithms:
            self.register(algorithm)

    def register(self, algorithm: ReconstructionAlgorithm):
        if not isinstance(algorithm, ReconstructionAlgorithm):
            raise TypeError("算法插件未实现 ReconstructionAlgorithm 协议。")
        identifier = algorithm.metadata.identifier
        if identifier in self._algorithms:
            raise ValueError(f"算法标识已注册：{identifier}")
        schema = validate_parameter_schema(algorithm.parameter_schema())
        self._algorithms[identifier] = algorithm
        self._parameter_schemas[identifier] = schema

    def get(self, identifier: str) -> ReconstructionAlgorithm:
        try:
            return self._algorithms[str(identifier)]
        except KeyError as exc:
            available = "、".join(self._algorithms) or "无"
            raise KeyError(f"未知算法：{identifier}。可用算法：{available}") from exc

    def list(self) -> tuple[ReconstructionAlgorithm, ...]:
        return tuple(self._algorithms.values())

    def parameter_schema(self, identifier: str) -> Mapping[str, Any]:
        self.get(identifier)
        return copy.deepcopy(self._parameter_schemas[str(identifier)])

    def resolve(
        self,
        identifier: str,
        *,
        expected_version: str | None = None,
        expected_schema_version: str | None = None,
    ) -> AlgorithmResolution:
        """Resolve a requested plugin exactly, without choosing a fallback."""
        requested_id = str(identifier or "").strip()
        requested_version = (
            None if expected_version is None else str(expected_version).strip()
        )
        requested_schema_version = (
            None
            if expected_schema_version is None
            else str(expected_schema_version).strip()
        )
        algorithm = self._algorithms.get(requested_id)
        if algorithm is None:
            report = ValidationReport.invalid(
                f"分析算法插件不可用：{requested_id or '未指定'}。",
                field="/analysis/algorithm/id",
            )
            return AlgorithmResolution(
                identifier=requested_id,
                expected_version=requested_version,
                expected_schema_version=requested_schema_version,
                algorithm=None,
                status=AlgorithmResolutionStatus.MISSING,
                report=report,
            )

        issues = []
        available_version = str(algorithm.metadata.version)
        schema_value = getattr(
            algorithm.metadata,
            "parameter_schema_version",
            None,
        )
        available_schema_version = (
            None if schema_value in (None, "") else str(schema_value)
        )
        if requested_version is not None and requested_version != available_version:
            issues.append(
                ValidationIssue(
                    "分析算法版本不匹配："
                    f"项目需要 {requested_version}，当前为 {available_version}。",
                    field="/analysis/algorithm/version",
                )
            )
        if (
            requested_schema_version is not None
            and requested_schema_version != available_schema_version
        ):
            issues.append(
                ValidationIssue(
                    "算法参数模式版本不匹配："
                    f"项目需要 {requested_schema_version}，"
                    f"当前为 {available_schema_version or '未声明'}。",
                    field="/analysis/algorithm/parameter-schema-version",
                )
            )

        if any(issue.field == "/analysis/algorithm/version" for issue in issues):
            status = AlgorithmResolutionStatus.VERSION_MISMATCH
        elif issues:
            status = AlgorithmResolutionStatus.SCHEMA_MISMATCH
        else:
            status = AlgorithmResolutionStatus.READY
        return AlgorithmResolution(
            identifier=requested_id,
            expected_version=requested_version,
            expected_schema_version=requested_schema_version,
            algorithm=algorithm,
            status=status,
            report=ValidationReport(tuple(issues)),
        )

    def __contains__(self, identifier: object) -> bool:
        return identifier in self._algorithms


def _ignore_progress(_fraction: float, _message: str):
    return None


class AnalysisService:
    def __init__(self, registry: AlgorithmRegistry, *, default_algorithm_id: str):
        if default_algorithm_id not in registry:
            raise KeyError(f"默认算法尚未注册：{default_algorithm_id}")
        self.registry = registry
        self.default_algorithm_id = default_algorithm_id

    def prepare(
        self,
        project_config: Mapping[str, Any],
        *,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        expected_version: str | None = None,
        expected_schema_version: str | None = None,
    ) -> AnalysisPreparation:
        identifier = algorithm_id or self.default_algorithm_id
        resolution = self.registry.resolve(
            identifier,
            expected_version=expected_version,
            expected_schema_version=expected_schema_version,
        )
        effective_parameters = dict(parameters or {})
        context = AnalysisContext(project_config, effective_parameters)
        if not resolution.is_ready:
            return AnalysisPreparation(
                resolution=resolution,
                context=context,
                effective_parameters=effective_parameters,
                report=resolution.report,
            )

        parameter_report = validate_parameters(
            self.registry.parameter_schema(resolution.identifier),
            effective_parameters,
        )
        if not parameter_report.is_valid:
            return AnalysisPreparation(
                resolution=resolution,
                context=context,
                effective_parameters=effective_parameters,
                report=parameter_report,
            )

        algorithm = resolution.algorithm
        if algorithm is None:  # Defensive; a ready resolution always has an algorithm.
            raise RuntimeError("算法解析状态无效。")
        algorithm_report = algorithm.validate(context)
        if not isinstance(algorithm_report, ValidationReport):
            raise TypeError("算法 validate() 必须返回 ValidationReport。")
        return AnalysisPreparation(
            resolution=resolution,
            context=context,
            effective_parameters=effective_parameters,
            report=algorithm_report,
        )

    def validate(
        self,
        project_config: Mapping[str, Any],
        *,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        expected_version: str | None = None,
        expected_schema_version: str | None = None,
    ) -> ValidationReport:
        return self.prepare(
            project_config,
            algorithm_id=algorithm_id,
            parameters=parameters,
            expected_version=expected_version,
            expected_schema_version=expected_schema_version,
        ).report

    def run(
        self,
        project_config: Mapping[str, Any],
        *,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        expected_version: str | None = None,
        expected_schema_version: str | None = None,
        progress: ProgressReporter | None = None,
        cancellation: CancellationToken | None = None,
    ) -> AnalysisResult:
        progress = progress or _ignore_progress
        cancellation = cancellation or CancellationToken()

        cancellation.raise_if_cancelled()
        preparation = self.prepare(
            project_config,
            algorithm_id=algorithm_id,
            parameters=parameters,
            expected_version=expected_version,
            expected_schema_version=expected_schema_version,
        )
        if not preparation.can_run:
            raise AlgorithmValidationError(
                preparation.report,
                preparation=preparation,
            )
        algorithm = preparation.algorithm
        if algorithm is None:  # Defensive; can_run implies a resolved algorithm.
            raise RuntimeError("算法解析状态无效。")

        progress(0.0, "输入校验完成")
        cancellation.raise_if_cancelled()
        result = algorithm.solve(
            preparation.context,
            progress=progress,
            cancellation=cancellation,
        )
        if result.algorithm_id != algorithm.metadata.identifier:
            raise RuntimeError("算法返回结果的标识与已注册插件不一致。")
        if result.algorithm_version != algorithm.metadata.version:
            raise RuntimeError("算法返回结果的版本与已注册插件不一致。")
        progress(1.0, "计算完成")
        return result


def create_default_analysis_service() -> AnalysisService:
    from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm

    registry = AlgorithmRegistry((BeamSurfaceIntegralAlgorithm(),))
    return AnalysisService(registry, default_algorithm_id=DEFAULT_ALGORITHM_ID)


_default_service: AnalysisService | None = None


def get_default_analysis_service() -> AnalysisService:
    global _default_service
    if _default_service is None:
        _default_service = create_default_analysis_service()
    return _default_service
