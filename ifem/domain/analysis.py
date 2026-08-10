from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from math import isclose, isfinite, sqrt
from threading import Event
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from ifem.domain.project import ProjectDocument


ProgressReporter = Callable[[float, str], None]
LEGACY_RECONSTRUCTION_CONTRACT_VERSION = "0"
RECONSTRUCTION_CONTRACT_VERSION = "1"


class DeformationRegime(str, Enum):
    """Kinematic regime implemented by a reconstruction method."""

    SMALL = "small_deformation"
    LARGE = "large_deformation"


class RotationRepresentation(str, Enum):
    """Representation used for nodal section rotations in a result state."""

    NONE = "none"
    ROTATION_VECTOR = "rotation_vector"
    QUATERNION = "quaternion"
    ROTATION_MATRIX = "rotation_matrix"


def _normalized_choice_tuple(values, *, allowed, field_name):
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name}必须是值列表。")
    normalized = tuple(
        sorted({str(getattr(value, "value", value)).strip().lower() for value in values})
    )
    if not normalized or any(value not in allowed for value in normalized):
        choices = "、".join(sorted(allowed))
        raise ValueError(f"{field_name}必须由 {choices} 中的值组成。")
    return normalized


def _normalized_identifier_tuple(values, *, field_name, allow_empty=False):
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name}必须是标识列表。")
    normalized = tuple(
        sorted({str(value).strip().lower() for value in values})
    )
    if any(not value for value in normalized) or (not normalized and not allow_empty):
        raise ValueError(f"{field_name}不能为空。")
    return normalized


def _finite_rows(values, *, columns: int, field_name: str):
    rows = tuple(tuple(float(value) for value in row) for row in values)
    if any(len(row) != columns for row in rows):
        raise ValueError(f"{field_name}每行必须包含 {columns} 个分量。")
    if any(not isfinite(value) for row in rows for value in row):
        raise ValueError(f"{field_name}必须全部为有限数值。")
    return rows


def _is_rotation_matrix(values, *, tolerance=1.0e-8):
    matrix = tuple(
        tuple(values[3 * row + column] for column in range(3))
        for row in range(3)
    )
    for left in range(3):
        for right in range(3):
            dot = sum(matrix[index][left] * matrix[index][right] for index in range(3))
            target = 1.0 if left == right else 0.0
            if not isclose(dot, target, rel_tol=0.0, abs_tol=tolerance):
                return False
    determinant = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    return isclose(determinant, 1.0, rel_tol=0.0, abs_tol=tolerance)


@dataclass(frozen=True)
class AlgorithmMetadata:
    identifier: str
    display_name: str
    version: str
    description: str = ""
    parameter_schema_version: str = "1"
    contract_version: str = LEGACY_RECONSTRUCTION_CONTRACT_VERSION

    def __post_init__(self):
        identifier = self.identifier.strip()
        display_name = self.display_name.strip()
        version = self.version.strip()
        if not identifier:
            raise ValueError("算法标识不能为空。")
        if not display_name:
            raise ValueError("算法显示名称不能为空。")
        if not version:
            raise ValueError("算法版本不能为空。")
        parameter_schema_version = self.parameter_schema_version
        if (
            not isinstance(parameter_schema_version, str)
            or not parameter_schema_version.strip()
        ):
            raise ValueError("算法参数模式版本不能为空。")
        contract_version = self.contract_version
        if not isinstance(contract_version, str) or not contract_version.strip():
            raise ValueError("重构算法接口版本不能为空。")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "parameter_schema_version",
            parameter_schema_version.strip(),
        )
        object.__setattr__(self, "contract_version", contract_version.strip())


class InputValidationError(ValueError):
    """An input validation failure tied to a stable field path."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(str(message))
        self.field = field


@dataclass(frozen=True)
class AlgorithmCapabilities:
    model_dimensions: tuple[int, ...]
    element_families: tuple[str, ...]
    measurement_types: tuple[str, ...]
    result_fields: tuple[str, ...]
    supports_transient: bool = False
    modeling_spaces: tuple[str, ...] = ("2d", "3d")
    geometry_kinds: tuple[str, ...] = ("line", "circular_arc")
    supports_mixed_geometry: bool = True
    deformation_regimes: tuple[str, ...] = (DeformationRegime.SMALL.value,)
    rotation_representations: tuple[str, ...] = (
        RotationRepresentation.ROTATION_VECTOR.value,
    )
    required_result_fields: tuple[str, ...] = ()

    def __post_init__(self):
        raw_dimensions = tuple(self.model_dimensions)
        if any(isinstance(value, bool) for value in raw_dimensions):
            raise ValueError("算法模型维度必须是整数。")
        dimensions = tuple(sorted({int(value) for value in raw_dimensions}))
        if any(float(value) != int(value) for value in raw_dimensions):
            raise ValueError("算法模型维度必须是整数。")
        if not dimensions or any(value not in {1, 2, 3} for value in dimensions):
            raise ValueError("算法模型维度必须由 1、2、3 中的值组成。")
        modeling_spaces = tuple(
            sorted({str(value).strip().lower() for value in self.modeling_spaces})
        )
        if not modeling_spaces or any(value not in {"2d", "3d"} for value in modeling_spaces):
            raise ValueError("算法建模空间必须由 2d、3d 中的值组成。")
        geometry_kinds = tuple(
            sorted({str(value).strip().lower() for value in self.geometry_kinds})
        )
        if not geometry_kinds or any(not value for value in geometry_kinds):
            raise ValueError("算法支持的几何类型不能为空。")
        deformation_regimes = _normalized_choice_tuple(
            self.deformation_regimes,
            allowed={item.value for item in DeformationRegime},
            field_name="算法变形制度",
        )
        rotation_representations = _normalized_choice_tuple(
            self.rotation_representations,
            allowed={item.value for item in RotationRepresentation},
            field_name="算法转角表示",
        )
        element_families = _normalized_identifier_tuple(
            self.element_families,
            field_name="算法单元族",
        )
        measurement_types = _normalized_identifier_tuple(
            self.measurement_types,
            field_name="算法测量类型",
            allow_empty=True,
        )
        result_fields = _normalized_identifier_tuple(
            self.result_fields,
            field_name="算法结果字段",
            allow_empty=True,
        )
        required_result_fields = _normalized_identifier_tuple(
            self.required_result_fields,
            field_name="算法必需结果字段",
            allow_empty=True,
        )
        if not set(required_result_fields) <= set(result_fields):
            raise ValueError("算法必需结果字段必须包含在结果能力声明中。")
        object.__setattr__(self, "model_dimensions", dimensions)
        object.__setattr__(self, "element_families", element_families)
        object.__setattr__(self, "measurement_types", measurement_types)
        object.__setattr__(self, "result_fields", result_fields)
        object.__setattr__(self, "required_result_fields", required_result_fields)
        object.__setattr__(self, "modeling_spaces", modeling_spaces)
        object.__setattr__(self, "geometry_kinds", geometry_kinds)
        object.__setattr__(self, "deformation_regimes", deformation_regimes)
        object.__setattr__(
            self,
            "rotation_representations",
            rotation_representations,
        )
        object.__setattr__(
            self,
            "supports_mixed_geometry",
            bool(self.supports_mixed_geometry),
        )
        object.__setattr__(self, "supports_transient", bool(self.supports_transient))


@dataclass(frozen=True)
class ValidationIssue:
    message: str
    field: str | None = None
    severity: str = "error"

    def __post_init__(self):
        message = str(self.message).strip()
        severity = str(self.severity).strip().lower()
        field_value = None if self.field is None else str(self.field).strip()
        if not message:
            raise ValueError("校验问题消息不能为空。")
        if severity not in {"error", "warning", "info"}:
            raise ValueError(f"未知校验问题级别：{severity}")
        if field_value == "":
            field_value = None
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "field", field_value)
        object.__setattr__(self, "severity", severity)


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    def __post_init__(self):
        issues = tuple(self.issues)
        if any(not isinstance(issue, ValidationIssue) for issue in issues):
            raise TypeError("ValidationReport.issues 必须由 ValidationIssue 组成。")
        object.__setattr__(self, "issues", issues)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def error_message(self) -> str:
        errors = [issue.message for issue in self.issues if issue.severity == "error"]
        return "\n".join(errors)

    @classmethod
    def valid(cls) -> "ValidationReport":
        return cls()

    @classmethod
    def invalid(cls, message: str, *, field: str | None = None) -> "ValidationReport":
        return cls((ValidationIssue(str(message), field=field),))


@dataclass(frozen=True)
class AnalysisContext:
    project_config: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    project: ProjectDocument | None = None
    analysis_case_id: str | None = None
    deformation_regime: str | None = None

    def __post_init__(self):
        if not isinstance(self.project_config, Mapping):
            raise TypeError("旧式算法配置必须是映射。")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("算法参数必须是映射。")
        if self.project is not None and not isinstance(self.project, ProjectDocument):
            raise TypeError("算法工程上下文必须是 ProjectDocument。")
        analysis_case_id = self.analysis_case_id
        if analysis_case_id is not None:
            analysis_case_id = str(analysis_case_id).strip()
            if not analysis_case_id:
                raise ValueError("分析工况 ID 不能为空字符串。")
        regime = self.deformation_regime
        if regime is not None:
            regime = str(getattr(regime, "value", regime)).strip().lower()
            if regime not in {item.value for item in DeformationRegime}:
                raise ValueError(f"未知变形制度：{regime}")
        object.__setattr__(self, "project_config", dict(self.project_config))
        object.__setattr__(self, "parameters", copy.deepcopy(dict(self.parameters)))
        object.__setattr__(self, "analysis_case_id", analysis_case_id)
        object.__setattr__(self, "deformation_regime", regime)

    def project_request(self) -> "ProjectAnalysisRequest":
        if self.project is None:
            raise InputValidationError("当前算法需要完整工程模型。", field="/model")
        if self.deformation_regime is None:
            raise InputValidationError(
                "当前分析未明确变形制度。",
                field="/analysis/deformation-regime",
            )
        return ProjectAnalysisRequest(
            project=self.project,
            parameters=self.parameters,
            analysis_case_id=self.analysis_case_id,
            deformation_regime=self.deformation_regime,
        )


@dataclass(frozen=True)
class ProjectAnalysisRequest:
    """Typed, extensible request passed to project-native algorithms."""

    project: ProjectDocument
    parameters: Mapping[str, Any] = field(default_factory=dict)
    analysis_case_id: str | None = None
    deformation_regime: str = DeformationRegime.SMALL.value

    def __post_init__(self):
        if not isinstance(self.project, ProjectDocument):
            raise TypeError("算法工程请求必须包含 ProjectDocument。")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("算法工程请求参数必须是映射。")
        case_id = self.analysis_case_id
        if case_id is not None:
            case_id = str(case_id).strip()
            if not case_id:
                raise ValueError("算法工程请求的工况 ID 不能为空字符串。")
        regime = str(
            getattr(self.deformation_regime, "value", self.deformation_regime)
        ).strip().lower()
        if regime not in {item.value for item in DeformationRegime}:
            raise ValueError(f"未知变形制度：{regime}")
        object.__setattr__(self, "project", copy.deepcopy(self.project))
        object.__setattr__(self, "parameters", copy.deepcopy(dict(self.parameters)))
        object.__setattr__(self, "analysis_case_id", case_id)
        object.__setattr__(self, "deformation_regime", regime)


@dataclass(frozen=True)
class ResultField:
    """Solver-neutral scalar/vector/tensor values associated with stable entities."""

    identifier: str
    association: str
    entity_ids: tuple[str, ...]
    components: tuple[str, ...]
    values: tuple[tuple[float, ...], ...]
    unit: str = ""
    coordinate_system: str = "global"

    def __post_init__(self):
        identifier = str(self.identifier).strip()
        association = str(self.association).strip().lower()
        entity_ids = tuple(str(value).strip() for value in self.entity_ids)
        components = tuple(str(value).strip() for value in self.components)
        if not identifier:
            raise ValueError("结果字段标识不能为空。")
        if association not in {"node", "element", "sensor", "sample", "global"}:
            raise ValueError(f"未知结果字段关联：{association}")
        if not components or any(not value for value in components):
            raise ValueError("结果字段分量不能为空。")
        if any(not value for value in entity_ids) or len(entity_ids) != len(set(entity_ids)):
            raise ValueError("结果字段实体 ID 必须非空且唯一。")
        values = _finite_rows(
            self.values,
            columns=len(components),
            field_name=f"结果字段 {identifier}",
        )
        if len(values) != len(entity_ids):
            raise ValueError("结果字段数值行数必须与实体 ID 数量一致。")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "entity_ids", entity_ids)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "unit", str(self.unit).strip())
        object.__setattr__(
            self,
            "coordinate_system",
            str(self.coordinate_system).strip() or "global",
        )


@dataclass(frozen=True)
class ReconstructionState:
    """Common nodal geometry returned by every reconstruction method.

    Extra physical fields remain in :class:`AnalysisResult.fields`; this state is
    deliberately small so 2D/3D and small/large-deformation solvers share it.
    """

    modeling_space: str
    deformation_regime: str
    node_ids: tuple[str, ...]
    reference_coordinates: tuple[tuple[float, float, float], ...]
    displacements: tuple[tuple[float, float, float], ...]
    reference_frames: tuple[tuple[float, ...], ...]
    element_ids: tuple[str, ...] = ()
    connectivity: tuple[tuple[str, ...], ...] = ()
    rotations: tuple[tuple[float, ...], ...] = ()
    rotation_representation: str = RotationRepresentation.NONE.value
    project_id: str | None = None
    project_revision: int | None = None

    def __post_init__(self):
        modeling_space = str(self.modeling_space).strip().lower()
        if modeling_space not in {"2d", "3d"}:
            raise ValueError("重构结果建模空间必须是 2d 或 3d。")
        regime = str(getattr(self.deformation_regime, "value", self.deformation_regime))
        regime = regime.strip().lower()
        if regime not in {item.value for item in DeformationRegime}:
            raise ValueError(f"未知重构结果变形制度：{regime}")
        node_ids = tuple(str(value).strip() for value in self.node_ids)
        if not node_ids or any(not value for value in node_ids):
            raise ValueError("重构结果节点 ID 不能为空。")
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("重构结果节点 ID 必须唯一。")
        node_id_set = set(node_ids)
        reference_coordinates = _finite_rows(
            self.reference_coordinates,
            columns=3,
            field_name="重构结果参考坐标",
        )
        displacements = _finite_rows(
            self.displacements,
            columns=3,
            field_name="重构结果位移",
        )
        if len(reference_coordinates) != len(node_ids) or len(displacements) != len(node_ids):
            raise ValueError("重构结果节点 ID、参考坐标和位移数量必须一致。")
        reference_frames = _finite_rows(
            self.reference_frames,
            columns=9,
            field_name="重构结果参考标架",
        )
        if len(reference_frames) != len(node_ids):
            raise ValueError("重构结果参考标架数量必须与节点数量一致。")
        if any(not _is_rotation_matrix(values) for values in reference_frames):
            raise ValueError("重构结果参考标架必须是右手正交旋转矩阵。")
        element_ids = tuple(str(value).strip() for value in self.element_ids)
        if any(not value for value in element_ids) or len(element_ids) != len(set(element_ids)):
            raise ValueError("重构结果单元 ID 必须非空且唯一。")
        connectivity = tuple(
            tuple(str(value).strip() for value in row) for row in self.connectivity
        )
        if len(connectivity) != len(element_ids):
            raise ValueError("重构结果连接关系必须与单元 ID 数量一致。")
        if any(len(row) < 2 or any(not value for value in row) for row in connectivity):
            raise ValueError("重构结果每个单元至少需要两个节点。")
        if any(value not in node_id_set for row in connectivity for value in row):
            raise ValueError("重构结果连接关系引用了未知节点 ID。")
        rotation_representation = str(
            getattr(self.rotation_representation, "value", self.rotation_representation)
        ).strip().lower()
        component_counts = {
            RotationRepresentation.NONE.value: 0,
            RotationRepresentation.ROTATION_VECTOR.value: 3,
            RotationRepresentation.QUATERNION.value: 4,
            RotationRepresentation.ROTATION_MATRIX.value: 9,
        }
        if rotation_representation not in component_counts:
            raise ValueError(f"未知转角表示：{rotation_representation}")
        expected_components = component_counts[rotation_representation]
        rotations = tuple(tuple(float(value) for value in row) for row in self.rotations)
        if expected_components == 0:
            if rotations:
                raise ValueError("无转角表示不能携带转角数值。")
        else:
            rotations = _finite_rows(
                rotations,
                columns=expected_components,
                field_name="重构结果转角",
            )
            if len(rotations) != len(node_ids):
                raise ValueError("重构结果转角数量必须与节点数量一致。")
            if rotation_representation == RotationRepresentation.QUATERNION.value:
                if any(
                    not isclose(
                        sqrt(sum(value * value for value in row)),
                        1.0,
                        rel_tol=0.0,
                        abs_tol=1.0e-8,
                    )
                    for row in rotations
                ):
                    raise ValueError("重构结果四元数必须为单位四元数。")
            if rotation_representation == RotationRepresentation.ROTATION_MATRIX.value:
                if any(not _is_rotation_matrix(values) for values in rotations):
                    raise ValueError("重构结果转角矩阵必须属于 SO(3)。")
        project_id = None if self.project_id is None else str(self.project_id).strip()
        if project_id == "":
            raise ValueError("重构结果项目 ID 不能为空字符串。")
        project_revision = self.project_revision
        if project_revision is not None:
            if isinstance(project_revision, bool) or not isinstance(project_revision, int):
                raise ValueError("重构结果项目修订号必须是整数。")
            if project_revision < 0:
                raise ValueError("重构结果项目修订号不能小于 0。")
        object.__setattr__(self, "modeling_space", modeling_space)
        object.__setattr__(self, "deformation_regime", regime)
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "reference_coordinates", reference_coordinates)
        object.__setattr__(self, "displacements", displacements)
        object.__setattr__(self, "reference_frames", reference_frames)
        object.__setattr__(self, "element_ids", element_ids)
        object.__setattr__(self, "connectivity", connectivity)
        object.__setattr__(self, "rotations", rotations)
        object.__setattr__(self, "rotation_representation", rotation_representation)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "project_revision", project_revision)

    @property
    def deformed_coordinates(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(
            tuple(reference + delta for reference, delta in zip(point, displacement))
            for point, displacement in zip(self.reference_coordinates, self.displacements)
        )


@dataclass(frozen=True)
class AnalysisResult:
    algorithm_id: str
    algorithm_version: str
    native_model: Any = None
    inputs: Mapping[str, Any] = field(default_factory=dict)
    fields: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    state: ReconstructionState | None = None

    def __post_init__(self):
        algorithm_id = str(self.algorithm_id).strip()
        algorithm_version = str(self.algorithm_version).strip()
        if not algorithm_id or not algorithm_version:
            raise ValueError("算法结果的算法 ID 和版本不能为空。")
        if self.state is not None and not isinstance(self.state, ReconstructionState):
            raise TypeError("算法结果 state 必须是 ReconstructionState。")
        fields = dict(self.fields)
        object.__setattr__(self, "algorithm_id", algorithm_id)
        object.__setattr__(self, "algorithm_version", algorithm_version)
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class AnalysisCancelled(RuntimeError):
    """Raised when a pending or running analysis is cancelled."""


class CancellationToken:
    def __init__(self):
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self):
        self._event.set()

    def raise_if_cancelled(self):
        if self.is_cancelled:
            raise AnalysisCancelled("分析任务已取消。")


@runtime_checkable
class ReconstructionAlgorithm(Protocol):
    metadata: AlgorithmMetadata
    capabilities: AlgorithmCapabilities

    def parameter_schema(self) -> Mapping[str, Any]: ...

    def validate(self, context: AnalysisContext) -> ValidationReport: ...

    def solve(
        self,
        context: AnalysisContext,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult: ...
