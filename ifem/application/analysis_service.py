from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from math import isclose
from typing import Any

from ifem.application.parameter_validation import (
    validate_parameter_schema,
    validate_parameters,
)
from ifem.application.algorithm_matching import assess_project_algorithm
from ifem.domain.analysis import (
    LEGACY_RECONSTRUCTION_CONTRACT_VERSION,
    RECONSTRUCTION_CONTRACT_VERSION,
    AlgorithmCapabilities,
    AlgorithmMetadata,
    AnalysisContext,
    AnalysisResult,
    CancellationToken,
    DeformationRegime,
    InputValidationError,
    ProgressReporter,
    ReconstructionAlgorithm,
    ResultField,
    ValidationIssue,
    ValidationReport,
)
from ifem.domain.project import AnalysisCase, ProjectDocument
from ifem.domain.result_fields import validate_result_fields


DEFAULT_ALGORITHM_ID = "ifem.beam2d.surface_integral.v1"
SUPPORTED_RECONSTRUCTION_CONTRACT_VERSIONS = frozenset(
    {
        LEGACY_RECONSTRUCTION_CONTRACT_VERSION,
        RECONSTRUCTION_CONTRACT_VERSION,
    }
)


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
        object.__setattr__(
            self,
            "effective_parameters",
            copy.deepcopy(dict(self.effective_parameters)),
        )

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
        metadata = algorithm.metadata
        contract_version = str(
            getattr(
                metadata,
                "contract_version",
                LEGACY_RECONSTRUCTION_CONTRACT_VERSION,
            )
        ).strip()
        if contract_version not in SUPPORTED_RECONSTRUCTION_CONTRACT_VERSIONS:
            supported = "、".join(sorted(SUPPORTED_RECONSTRUCTION_CONTRACT_VERSIONS))
            raise ValueError(
                "不支持的重构算法接口版本："
                f"{contract_version}；当前支持 {supported}。"
            )
        if contract_version == RECONSTRUCTION_CONTRACT_VERSION:
            if not isinstance(metadata, AlgorithmMetadata):
                raise TypeError("v1 算法 metadata 必须是 AlgorithmMetadata。")
            if not isinstance(algorithm.capabilities, AlgorithmCapabilities):
                raise TypeError("v1 算法 capabilities 必须是 AlgorithmCapabilities。")
        identifier = str(metadata.identifier)
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
        project: ProjectDocument | None = None,
        analysis_case_id: str | None = None,
        deformation_regime: str | DeformationRegime | None = None,
    ) -> AnalysisPreparation:
        identifier = algorithm_id or self.default_algorithm_id
        resolution = self.registry.resolve(
            identifier,
            expected_version=expected_version,
            expected_schema_version=expected_schema_version,
        )
        effective_parameters = copy.deepcopy(dict(parameters or {}))
        effective_regime = deformation_regime
        declared_regimes = (
            ()
            if resolution.algorithm is None
            else tuple(
                getattr(
                    resolution.algorithm.capabilities,
                    "deformation_regimes",
                    (DeformationRegime.SMALL.value,),
                )
            )
        )
        if (
            effective_regime is None
            and resolution.algorithm is not None
            and len(declared_regimes) == 1
        ):
            effective_regime = declared_regimes[0]
        context = AnalysisContext(
            project_config,
            effective_parameters,
            project=project,
            analysis_case_id=analysis_case_id,
            deformation_regime=effective_regime,
        )
        if not resolution.is_ready:
            return AnalysisPreparation(
                resolution=resolution,
                context=context,
                effective_parameters=effective_parameters,
                report=resolution.report,
            )

        algorithm = resolution.algorithm
        if algorithm is None:  # Defensive; a ready resolution always has an algorithm.
            raise RuntimeError("算法解析状态无效。")
        if context.deformation_regime is None:
            return AnalysisPreparation(
                resolution=resolution,
                context=context,
                effective_parameters=effective_parameters,
                report=ValidationReport.invalid(
                    "当前算法支持多种变形制度，请明确选择本次分析制度。",
                    field="/analysis/deformation-regime",
                ),
            )
        preflight_issues: list[ValidationIssue] = []
        if project is not None:
            capability_report = assess_project_algorithm(
                project,
                algorithm,
                required_deformation_regime=context.deformation_regime,
            )
            preflight_issues.extend(capability_report.issues)
            if not capability_report.is_valid:
                return AnalysisPreparation(
                    resolution=resolution,
                    context=context,
                    effective_parameters=effective_parameters,
                    report=ValidationReport(tuple(preflight_issues)),
                )

        parameter_report = validate_parameters(
            self.registry.parameter_schema(resolution.identifier),
            effective_parameters,
        )
        preflight_issues.extend(parameter_report.issues)
        if not parameter_report.is_valid:
            return AnalysisPreparation(
                resolution=resolution,
                context=context,
                effective_parameters=effective_parameters,
                report=ValidationReport(tuple(preflight_issues)),
            )

        try:
            algorithm_report = algorithm.validate(context)
        except InputValidationError as exc:
            algorithm_report = ValidationReport.invalid(
                str(exc),
                field=exc.field or "/analysis/algorithm/id",
            )
        except Exception as exc:
            algorithm_report = ValidationReport.invalid(
                "重构方法输入校验失败："
                f"{algorithm.metadata.identifier}（{type(exc).__name__}: {exc}）",
                field="/analysis/algorithm/id",
            )
        if not isinstance(algorithm_report, ValidationReport):
            algorithm_report = ValidationReport.invalid(
                "重构方法 validate() 返回了无效结果："
                f"{algorithm.metadata.identifier}（{type(algorithm_report).__name__}）",
                field="/analysis/algorithm/id",
            )
        preflight_issues.extend(algorithm_report.issues)
        return AnalysisPreparation(
            resolution=resolution,
            context=context,
            effective_parameters=effective_parameters,
            report=ValidationReport(tuple(preflight_issues)),
        )

    @staticmethod
    def _project_analysis_case(
        project: ProjectDocument,
        analysis_case_id: str | None,
    ) -> AnalysisCase | None:
        requested_id = analysis_case_id
        if requested_id is not None:
            requested_id = str(requested_id).strip()
            if not requested_id:
                raise KeyError("分析工况 ID 不能为空。")
        if requested_id is None:
            requested_id = project.active_analysis_id
        if requested_id is not None:
            for case in project.analysis_cases:
                if case.identifier == requested_id:
                    return case
            raise KeyError(f"项目中不存在分析工况：{requested_id}")
        return project.analysis_cases[0] if project.analysis_cases else None

    def prepare_project(
        self,
        project: ProjectDocument,
        *,
        analysis_case_id: str | None = None,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        expected_version: str | None = None,
        expected_schema_version: str | None = None,
        deformation_regime: str | DeformationRegime | None = None,
        legacy_project_config: Mapping[str, Any] | None = None,
    ) -> AnalysisPreparation:
        """Prepare a canonical project without projecting it into a 2D config."""

        if not isinstance(project, ProjectDocument):
            raise TypeError("分析工程必须是 ProjectDocument。")
        try:
            case = self._project_analysis_case(project, analysis_case_id)
        except KeyError as exc:
            identifier = algorithm_id or self.default_algorithm_id
            resolution = self.registry.resolve(
                identifier,
                expected_version=expected_version,
                expected_schema_version=expected_schema_version,
            )
            declared_regimes = (
                ()
                if resolution.algorithm is None
                else tuple(
                    getattr(
                        resolution.algorithm.capabilities,
                        "deformation_regimes",
                        (DeformationRegime.SMALL.value,),
                    )
                )
            )
            effective_regime = deformation_regime
            if effective_regime is None and len(declared_regimes) == 1:
                effective_regime = declared_regimes[0]
            context = AnalysisContext(
                legacy_project_config or {},
                parameters or {},
                project=project,
                analysis_case_id=None,
                deformation_regime=effective_regime,
            )
            return AnalysisPreparation(
                resolution=resolution,
                context=context,
                effective_parameters=dict(parameters or {}),
                report=ValidationReport.invalid(
                    str(exc).strip("'"),
                    field="/analysis/case/id",
                ),
            )
        identifier = algorithm_id or (None if case is None else case.algorithm_id)
        uses_case_binding = case is not None and (
            algorithm_id is None or algorithm_id == case.algorithm_id
        )
        if uses_case_binding:
            effective_parameters = copy.deepcopy(dict(case.parameters))
            if parameters is not None:
                effective_parameters.update(copy.deepcopy(dict(parameters)))
        else:
            effective_parameters = parameters
        if expected_version is None and uses_case_binding:
            expected_version = case.algorithm_version
        if expected_schema_version is None and uses_case_binding:
            expected_schema_version = case.parameter_schema_version
        effective_case_id = case.identifier if uses_case_binding else None
        return self.prepare(
            legacy_project_config or {},
            algorithm_id=identifier,
            parameters=effective_parameters,
            expected_version=expected_version,
            expected_schema_version=expected_schema_version,
            project=project,
            analysis_case_id=effective_case_id,
            deformation_regime=deformation_regime,
        )

    def validate(
        self,
        project_config: Mapping[str, Any],
        *,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        expected_version: str | None = None,
        expected_schema_version: str | None = None,
        project: ProjectDocument | None = None,
        analysis_case_id: str | None = None,
        deformation_regime: str | DeformationRegime | None = None,
    ) -> ValidationReport:
        return self.prepare(
            project_config,
            algorithm_id=algorithm_id,
            parameters=parameters,
            expected_version=expected_version,
            expected_schema_version=expected_schema_version,
            project=project,
            analysis_case_id=analysis_case_id,
            deformation_regime=deformation_regime,
        ).report

    def validate_project(
        self,
        project: ProjectDocument,
        **kwargs,
    ) -> ValidationReport:
        return self.prepare_project(project, **kwargs).report

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
        project: ProjectDocument | None = None,
        analysis_case_id: str | None = None,
        deformation_regime: str | DeformationRegime | None = None,
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
            project=project,
            analysis_case_id=analysis_case_id,
            deformation_regime=deformation_regime,
        )
        return self._run_preparation(
            preparation,
            progress=progress,
            cancellation=cancellation,
        )

    def run_project(
        self,
        project: ProjectDocument,
        *,
        progress: ProgressReporter | None = None,
        cancellation: CancellationToken | None = None,
        **kwargs,
    ) -> AnalysisResult:
        progress = progress or _ignore_progress
        cancellation = cancellation or CancellationToken()
        cancellation.raise_if_cancelled()
        preparation = self.prepare_project(project, **kwargs)
        return self._run_preparation(
            preparation,
            progress=progress,
            cancellation=cancellation,
        )

    def _run_preparation(
        self,
        preparation: AnalysisPreparation,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult:
        if not preparation.can_run:
            raise AlgorithmValidationError(
                preparation.report,
                preparation=preparation,
            )
        algorithm = preparation.algorithm
        if algorithm is None:
            raise RuntimeError("算法解析状态无效。")
        progress(0.0, "输入校验完成")
        cancellation.raise_if_cancelled()
        result = algorithm.solve(
            preparation.context,
            progress=progress,
            cancellation=cancellation,
        )
        if not isinstance(result, AnalysisResult):
            raise TypeError("算法 solve() 必须返回 AnalysisResult。")
        if result.algorithm_id != algorithm.metadata.identifier:
            raise RuntimeError("算法返回结果的标识与已注册插件不一致。")
        if result.algorithm_version != algorithm.metadata.version:
            raise RuntimeError("算法返回结果的版本与已注册插件不一致。")
        self._validate_result_contract(result, preparation)
        progress(1.0, "计算完成")
        return result

    @staticmethod
    def _validate_result_contract(
        result: AnalysisResult,
        preparation: AnalysisPreparation,
    ):
        algorithm = preparation.algorithm
        if algorithm is None:
            raise RuntimeError("算法解析状态无效。")
        state = result.state
        contract_version = str(
            getattr(
                algorithm.metadata,
                "contract_version",
                LEGACY_RECONSTRUCTION_CONTRACT_VERSION,
            )
        ).strip()
        if contract_version == LEGACY_RECONSTRUCTION_CONTRACT_VERSION:
            return
        if state is None:
            raise RuntimeError("重构算法接口 v1 要求返回通用 ReconstructionState。")
        capabilities = algorithm.capabilities
        if state.modeling_space not in capabilities.modeling_spaces:
            raise RuntimeError("算法返回结果的建模空间超出能力声明。")
        if state.deformation_regime not in capabilities.deformation_regimes:
            raise RuntimeError("算法返回结果的变形制度超出能力声明。")
        if state.rotation_representation not in capabilities.rotation_representations:
            raise RuntimeError("算法返回结果的转角表示超出能力声明。")
        if (
            preparation.context.deformation_regime is not None
            and state.deformation_regime != preparation.context.deformation_regime
        ):
            raise RuntimeError("算法返回结果的变形制度与分析请求不一致。")
        project = preparation.context.project
        if project is not None:
            if state.project_id != project.identifier:
                raise RuntimeError("算法返回结果的项目 ID 与分析工程不一致。")
            if state.project_revision != project.revision:
                raise RuntimeError("算法返回结果的项目修订号与分析工程不一致。")
            if state.modeling_space != project.modeling_space:
                raise RuntimeError("算法返回结果的建模空间与分析工程不一致。")
            project_node_ids = {item.identifier for item in project.nodes}
            project_element_ids = {item.identifier for item in project.elements}
            if set(state.node_ids) != project_node_ids:
                raise RuntimeError("算法返回结果的节点 ID 与分析工程不一致。")
            if set(state.element_ids) != project_element_ids:
                raise RuntimeError("算法返回结果的单元 ID 与分析工程不一致。")
            result_coordinates = dict(zip(state.node_ids, state.reference_coordinates))
            if any(
                any(
                    not isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-12)
                    for actual, expected in zip(
                        result_coordinates[node.identifier],
                        node.coordinates,
                    )
                )
                for node in project.nodes
            ):
                raise RuntimeError("算法返回结果的参考坐标与分析工程不一致。")
            result_connectivity = dict(zip(state.element_ids, state.connectivity))
            if any(
                tuple(result_connectivity[element.identifier]) != element.node_ids
                for element in project.elements
            ):
                raise RuntimeError("算法返回结果的单元连接关系与分析工程不一致。")
        undeclared_fields = sorted(
            set(result.fields) - set(capabilities.result_fields)
        )
        if undeclared_fields:
            raise RuntimeError(
                "算法返回了能力声明之外的结果字段："
                + "、".join(undeclared_fields)
            )
        missing_fields = sorted(
            set(capabilities.required_result_fields) - set(result.fields)
        )
        if missing_fields:
            raise RuntimeError(
                "算法未返回能力声明要求的结果字段："
                + "、".join(missing_fields)
            )
        if any(not isinstance(value, ResultField) for value in result.fields.values()):
            raise RuntimeError("重构算法接口 v1 的 fields 必须由 ResultField 组成。")
        if any(str(key) != value.identifier for key, value in result.fields.items()):
            raise RuntimeError("结果字段键必须与 ResultField.identifier 一致。")
        node_ids = set(state.node_ids)
        element_ids = set(state.element_ids)
        sensor_ids = set() if project is None else {item.identifier for item in project.sensors}
        for field_value in result.fields.values():
            if field_value.association == "node" and not set(field_value.entity_ids) <= node_ids:
                raise RuntimeError(f"结果字段 {field_value.identifier} 引用了未知节点。")
            if (
                field_value.association == "element"
                and not set(field_value.entity_ids) <= element_ids
            ):
                raise RuntimeError(f"结果字段 {field_value.identifier} 引用了未知单元。")
            if (
                field_value.association == "sensor"
                and project is not None
                and not set(field_value.entity_ids) <= sensor_ids
            ):
                raise RuntimeError(f"结果字段 {field_value.identifier} 引用了未知测点。")
        try:
            validate_result_fields(result)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc


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
