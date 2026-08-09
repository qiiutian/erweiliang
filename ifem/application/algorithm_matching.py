from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ifem.domain.analysis import (
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


def match_project_algorithms(
    project: ProjectDocument,
    algorithms: Iterable[ReconstructionAlgorithm],
) -> tuple[AlgorithmMatch, ...]:
    profile = profile_project(project)
    matches = []
    for algorithm in algorithms:
        capabilities = algorithm.capabilities
        reasons = []
        issues = []

        def add_capability_issue(message, field):
            reasons.append(message)
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

        assessor = getattr(algorithm, "assess_project", None)
        if not reasons and callable(assessor):
            report = assessor(project)
            if not isinstance(report, ValidationReport):
                raise TypeError("算法项目能力评估必须返回 ValidationReport。")
            issues.extend(report.issues)
            reasons.extend(issue.message for issue in report.issues if issue.severity == "error")

        matches.append(
            AlgorithmMatch(
                algorithm_id=algorithm.metadata.identifier,
                display_name=algorithm.metadata.display_name,
                compatible=not reasons,
                reasons=tuple(dict.fromkeys(reasons)),
                issues=tuple(issues),
            )
        )
    return tuple(matches)
