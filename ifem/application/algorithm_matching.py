from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ifem.domain.analysis import (
    DeformationRegime,
    InputValidationError,
    ReconstructionAlgorithm,
    ValidationIssue,
    ValidationReport,
)
from ifem.domain.project import ProjectDocument


@dataclass(frozen=True)
class ModelFeatureProfile:
    topological_dimension: int
    modeling_space: str
    geometry_kinds: tuple[str, ...]
    element_families: tuple[str, ...]
    measurement_types: tuple[str, ...]
    mixed_geometry: bool


@dataclass(frozen=True)
class AlgorithmMatch:
    algorithm_id: str
    display_name: str
    compatible: bool
    reasons: tuple[str, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def reason_text(self) -> str:
        return "可用于当前模型" if self.compatible else "；".join(self.reasons)


def profile_project(project: ProjectDocument) -> ModelFeatureProfile:
    geometry_kinds = tuple(
        sorted({element.geometry.kind for element in project.elements})
    )
    return ModelFeatureProfile(
        topological_dimension=1,
        modeling_space=project.modeling_space,
        geometry_kinds=geometry_kinds,
        element_families=tuple(
            sorted({element.family for element in project.elements})
        ),
        measurement_types=tuple(
            sorted({sensor.measurement_type for sensor in project.sensors})
        ),
        mixed_geometry=len(geometry_kinds) > 1,
    )


def _normalize_required_regime(value: str | DeformationRegime | None) -> str | None:
    if value is None:
        return None
    normalized = str(getattr(value, "value", value)).strip().lower()
    if normalized not in {item.value for item in DeformationRegime}:
        raise ValueError(f"未知变形制度：{normalized}")
    return normalized


def assess_project_algorithm(
    project: ProjectDocument,
    algorithm: ReconstructionAlgorithm,
    *,
    required_deformation_regime: str | DeformationRegime | None = None,
) -> ValidationReport:
    """Assess one plugin without relying on a GUI-side compatibility gate."""

    profile = profile_project(project)
    capabilities = algorithm.capabilities
    required_regime = _normalize_required_regime(required_deformation_regime)
    issues = []

    def add_capability_issue(message, field):
        issues.append(ValidationIssue(message, field=field))

    if profile.topological_dimension not in capabilities.model_dimensions:
        add_capability_issue("模型拓扑维度不受支持", "/model/topological-dimension")
    if profile.modeling_space not in capabilities.modeling_spaces:
        add_capability_issue(
            f"不支持{profile.modeling_space.upper()}建模空间",
            "/model/modeling-space",
        )

    unsupported_geometry = sorted(
        set(profile.geometry_kinds) - set(capabilities.geometry_kinds)
    )
    if unsupported_geometry:
        add_capability_issue(
            f"不支持几何类型：{', '.join(unsupported_geometry)}",
            "/model/geometry",
        )
    if profile.mixed_geometry and not capabilities.supports_mixed_geometry:
        add_capability_issue("不支持直线与曲线混合路径", "/model/geometry")

    unsupported_families = sorted(
        set(profile.element_families) - set(capabilities.element_families)
    )
    if unsupported_families:
        add_capability_issue(
            f"不支持单元族：{', '.join(unsupported_families)}",
            "/model/element-families",
        )
    unsupported_measurements = sorted(
        set(profile.measurement_types) - set(capabilities.measurement_types)
    )
    if unsupported_measurements:
        add_capability_issue(
            f"不支持测量类型：{', '.join(unsupported_measurements)}",
            "/model/measurements",
        )
    if (
        required_regime is not None
        and required_regime
        not in getattr(
            capabilities,
            "deformation_regimes",
            (DeformationRegime.SMALL.value,),
        )
    ):
        label = "小变形" if required_regime == DeformationRegime.SMALL.value else "大变形"
        add_capability_issue(
            f"不支持{label}重构",
            "/analysis/deformation-regime",
        )

    assessor = getattr(algorithm, "assess_project", None)
    if not any(issue.severity == "error" for issue in issues) and callable(assessor):
        try:
            report = assessor(project)
        except InputValidationError as exc:
            report = ValidationReport.invalid(
                str(exc),
                field=exc.field or "/model/geometry",
            )
        except (KeyError, ValueError) as exc:
            report = ValidationReport.invalid(
                str(exc),
                field="/model/geometry",
            )
        if not isinstance(report, ValidationReport):
            raise TypeError("算法项目能力评估必须返回 ValidationReport。")
        issues.extend(report.issues)
    return ValidationReport(tuple(issues))


def match_project_algorithms(
    project: ProjectDocument,
    algorithms: Iterable[ReconstructionAlgorithm],
    *,
    required_deformation_regime: str | DeformationRegime | None = None,
) -> tuple[AlgorithmMatch, ...]:
    matches = []
    for algorithm in algorithms:
        report = assess_project_algorithm(
            project,
            algorithm,
            required_deformation_regime=required_deformation_regime,
        )
        reasons = tuple(
            dict.fromkeys(
                issue.message for issue in report.issues if issue.severity == "error"
            )
        )

        matches.append(
            AlgorithmMatch(
                algorithm_id=algorithm.metadata.identifier,
                display_name=algorithm.metadata.display_name,
                compatible=report.is_valid,
                reasons=reasons,
                issues=report.issues,
            )
        )
    return tuple(matches)
