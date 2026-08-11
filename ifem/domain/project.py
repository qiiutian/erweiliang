from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from math import cos, isfinite, radians, sin, sqrt
from typing import Any
from uuid import uuid4

from ifem.domain.parametric_expressions import (
    normalize_parametric_curve,
    parametric_curve_is_xy,
    parametric_point_and_derivative,
    validate_parametric_regularity,
)
from ifem.domain.parametric_curves import validate_nurbs_regularity


CURRENT_PROJECT_SCHEMA_VERSION = 7


def _normalize_json_value(
    value: Any,
    *,
    field_path: str,
    active_containers: set[int] | None = None,
) -> Any:
    """Return a detached JSON-safe value or raise with its field path."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{field_path} 必须是有限数。")
        return value

    if active_containers is None:
        active_containers = set()
    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError(f"{field_path} 不能包含循环引用。")
        active_containers.add(container_id)
        try:
            normalized = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{field_path} 的对象键必须是字符串。")
                normalized[key] = _normalize_json_value(
                    item,
                    field_path=f"{field_path}.{key}",
                    active_containers=active_containers,
                )
            return normalized
        finally:
            active_containers.remove(container_id)
    if isinstance(value, list):
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError(f"{field_path} 不能包含循环引用。")
        active_containers.add(container_id)
        try:
            return [
                _normalize_json_value(
                    item,
                    field_path=f"{field_path}[{index}]",
                    active_containers=active_containers,
                )
                for index, item in enumerate(value)
            ]
        finally:
            active_containers.remove(container_id)
    raise ValueError(
        f"{field_path} 包含不支持的 JSON 值类型：{type(value).__name__}。"
    )


def new_entity_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _finite_tuple(values, *, size: int, field_name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != size or not all(isfinite(value) for value in result):
        raise ValueError(f"{field_name} 必须包含 {size} 个有限数值。")
    return result


def _rotate_about_axis(vector, axis, angle_degrees):
    angle = radians(float(angle_degrees))
    cosine = cos(angle)
    sine = sin(angle)
    dot = sum(left * right for left, right in zip(axis, vector))
    cross = (
        axis[1] * vector[2] - axis[2] * vector[1],
        axis[2] * vector[0] - axis[0] * vector[2],
        axis[0] * vector[1] - axis[1] * vector[0],
    )
    return tuple(
        cosine * value + sine * cross_value + (1.0 - cosine) * dot * axis_value
        for value, cross_value, axis_value in zip(vector, cross, axis)
    )


def _point_distance(left, right) -> float:
    return sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


@dataclass(frozen=True)
class StructuralNode:
    identifier: str
    coordinates: tuple[float, float, float]

    def __post_init__(self):
        if not self.identifier.strip():
            raise ValueError("节点 ID 不能为空。")
        object.__setattr__(
            self,
            "coordinates",
            _finite_tuple(self.coordinates, size=3, field_name="节点坐标"),
        )


@dataclass(frozen=True)
class BeamGeometryDefinition:
    kind: str = "line"
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        kind = str(self.kind).strip().lower()
        if not kind:
            raise ValueError("梁几何类型不能为空。")
        parameters = dict(self.parameters)
        if kind == "line":
            parameters = {}
        elif kind == "circular_arc":
            radius = float(parameters.get("radius", 0.0))
            sweep_degrees = float(parameters.get("sweep_degrees", 0.0))
            center = _finite_tuple(
                parameters.get("center", ()),
                size=3,
                field_name="圆弧圆心",
            )
            normal = _finite_tuple(
                parameters.get("normal", ()),
                size=3,
                field_name="圆弧平面法向",
            )
            start_vector = _finite_tuple(
                parameters.get("start_vector", ()),
                size=3,
                field_name="圆弧起始半径向量",
            )
            plane = str(parameters.get("plane", "")).strip().lower()
            if not isfinite(radius) or radius <= 0.0:
                raise ValueError("圆弧半径必须大于 0。")
            if (
                not isfinite(sweep_degrees)
                or abs(sweep_degrees) <= 1.0e-9
                or abs(sweep_degrees) >= 360.0
            ):
                raise ValueError("圆弧圆心角必须满足 0 < |角度| < 360°。")
            if plane not in {"xy", "xz", "yz", "custom"}:
                raise ValueError("圆弧平面必须是 XY、XZ、YZ 或 custom。")
            normal_length = sqrt(sum(value * value for value in normal))
            start_length = sqrt(sum(value * value for value in start_vector))
            if normal_length <= 0.0 or start_length <= 0.0:
                raise ValueError("圆弧法向和起始半径向量不能为零。")
            normal = tuple(value / normal_length for value in normal)
            if abs(start_length - radius) > max(radius, 1.0) * 1.0e-8:
                raise ValueError("圆弧起始半径向量长度必须等于半径。")
            if abs(sum(a * b for a, b in zip(normal, start_vector))) > radius * 1.0e-8:
                raise ValueError("圆弧起始半径向量必须位于圆弧平面内。")
            plane_normal = {
                "xy": (0.0, 0.0, 1.0),
                "xz": (0.0, 1.0, 0.0),
                "yz": (1.0, 0.0, 0.0),
            }.get(plane)
            if plane_normal is not None and (
                abs(abs(sum(a * b for a, b in zip(normal, plane_normal))) - 1.0)
                > 1.0e-8
            ):
                raise ValueError(
                    f"圆弧法向与 {plane.upper()} 平面不一致；任意平面圆弧必须标记为 custom。"
                )
            parameters.update(
                {
                    "radius": radius,
                    "sweep_degrees": sweep_degrees,
                    "center": center,
                    "normal": normal,
                    "start_vector": start_vector,
                    "plane": plane,
                }
            )
        elif kind == "parametric_curve":
            parameters = normalize_parametric_curve(parameters)
            validate_parametric_regularity(parameters)
        elif kind == "nurbs_curve":
            raw_points = parameters.get("control_points", ())
            if not isinstance(raw_points, (list, tuple)):
                raise ValueError("NURBS 控制点必须是坐标列表。")
            control_points = tuple(
                _finite_tuple(point, size=3, field_name=f"NURBS 控制点 {index + 1}")
                for index, point in enumerate(raw_points)
            )
            if len(control_points) < 2:
                raise ValueError("NURBS 曲线至少需要两个控制点。")
            raw_degree = parameters.get("degree", min(3, len(control_points) - 1))
            if isinstance(raw_degree, bool):
                raise ValueError("NURBS 次数必须是整数。")
            try:
                degree = int(raw_degree)
                numeric_degree = float(raw_degree)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("NURBS 次数必须是整数。") from exc
            if (
                not isfinite(numeric_degree)
                or numeric_degree != degree
                or not 1 <= degree < len(control_points)
            ):
                raise ValueError("NURBS 次数必须是小于控制点数量的正整数。")

            raw_weights = parameters.get("weights", (1.0,) * len(control_points))
            if not isinstance(raw_weights, (list, tuple)):
                raise ValueError("NURBS 权重必须是数值列表。")
            try:
                weights = tuple(float(value) for value in raw_weights)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("NURBS 权重必须是数值列表。") from exc
            if (
                len(weights) != len(control_points)
                or not all(isfinite(value) and value > 0.0 for value in weights)
            ):
                raise ValueError("NURBS 权重必须与控制点一一对应且全部大于 0。")
            if max(weights) / min(weights) > 1.0e6:
                raise ValueError(
                    "NURBS 权重最大值与最小值的比例不能超过 1e6。"
                )

            expected_knot_count = len(control_points) + degree + 1
            raw_knots = parameters.get("knots")
            if raw_knots is None:
                internal_count = len(control_points) - degree - 1
                knots = (
                    (0.0,) * (degree + 1)
                    + tuple(
                        index / (internal_count + 1)
                        for index in range(1, internal_count + 1)
                    )
                    + (1.0,) * (degree + 1)
                )
            else:
                if not isinstance(raw_knots, (list, tuple)):
                    raise ValueError("NURBS 节点向量必须是数值列表。")
                try:
                    knots = tuple(float(value) for value in raw_knots)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("NURBS 节点向量必须是数值列表。") from exc
            if len(knots) != expected_knot_count or not all(
                isfinite(value) for value in knots
            ):
                raise ValueError(
                    f"NURBS 节点向量必须包含 {expected_knot_count} 个有限数值。"
                )
            if any(right < left for left, right in zip(knots, knots[1:])):
                raise ValueError("NURBS 节点向量必须单调不减。")
            domain_start = knots[degree]
            domain_end = knots[-degree - 1]
            if domain_end - domain_start <= 1.0e-12:
                raise ValueError("NURBS 有效参数区间不能为空。")
            if any(abs(value - domain_start) > 1.0e-10 for value in knots[: degree + 1]):
                raise ValueError("NURBS 起点必须使用夹持节点向量。")
            if any(abs(value - domain_end) > 1.0e-10 for value in knots[-degree - 1 :]):
                raise ValueError("NURBS 终点必须使用夹持节点向量。")
            knot_tolerance = max(abs(domain_end - domain_start), 1.0) * 1.0e-12
            group_start = 0
            while group_start < len(knots):
                group_end = group_start + 1
                while (
                    group_end < len(knots)
                    and abs(knots[group_end] - knots[group_start]) <= knot_tolerance
                ):
                    group_end += 1
                knot = knots[group_start]
                if (
                    domain_start + knot_tolerance < knot < domain_end - knot_tolerance
                    and group_end - group_start >= degree
                ):
                    raise ValueError(
                        "NURBS 内部节点重数必须小于次数，以保持切向连续。"
                    )
                group_start = group_end
            if sqrt(
                sum(
                    (right - left) ** 2
                    for left, right in zip(control_points[0], control_points[1])
                )
            ) <= 1.0e-12 or sqrt(
                sum(
                    (right - left) ** 2
                    for left, right in zip(control_points[-2], control_points[-1])
                )
            ) <= 1.0e-12:
                raise ValueError("NURBS 首尾控制边不能退化为零长度。")
            parameters.update(
                {
                    "degree": degree,
                    "control_points": control_points,
                    "weights": weights,
                    "knots": knots,
                }
            )
            validate_nurbs_regularity(parameters)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class BeamElement:
    identifier: str
    node_ids: tuple[str, str]
    family: str = "beam2d_euler_bernoulli"
    section_id: str | None = None
    material_id: str | None = None
    geometry: BeamGeometryDefinition = field(default_factory=BeamGeometryDefinition)

    def __post_init__(self):
        node_ids = tuple(str(value) for value in self.node_ids)
        if not self.identifier.strip() or len(node_ids) != 2 or node_ids[0] == node_ids[1]:
            raise ValueError("梁单元必须具有唯一 ID 和两个不同节点。")
        geometry = self.geometry
        if isinstance(geometry, Mapping):
            geometry = BeamGeometryDefinition(**dict(geometry))
        if not isinstance(geometry, BeamGeometryDefinition):
            raise TypeError("梁几何定义类型不合法。")
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "geometry", geometry)


@dataclass(frozen=True)
class MaterialDefinition:
    identifier: str
    name: str
    elastic_modulus: float | None = None

    def __post_init__(self):
        if not self.identifier.strip() or not self.name.strip():
            raise ValueError("材料 ID 和名称不能为空。")
        if self.elastic_modulus is not None:
            value = float(self.elastic_modulus)
            if not isfinite(value) or value <= 0.0:
                raise ValueError("弹性模量必须大于 0。")
            object.__setattr__(self, "elastic_modulus", value)


@dataclass(frozen=True)
class SectionDefinition:
    identifier: str
    name: str
    thickness: float
    width: float | None = None
    shape: str = "rectangle"
    parameters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        thickness = float(self.thickness)
        if not self.identifier.strip() or not self.name.strip():
            raise ValueError("截面 ID 和名称不能为空。")
        if not isfinite(thickness) or thickness <= 0.0:
            raise ValueError("截面厚度必须大于 0。")
        width = thickness if self.width is None else float(self.width)
        if not isfinite(width) or width <= 0.0:
            raise ValueError("截面宽度必须大于 0。")
        shape = str(self.shape).strip().lower()
        parameters = {str(key): float(value) for key, value in self.parameters.items()}
        if not all(isfinite(value) and value > 0.0 for value in parameters.values()):
            raise ValueError("截面尺寸必须全部为大于 0 的有限数值。")

        if shape == "rectangle":
            height = parameters.get("height", thickness)
            section_width = parameters.get("width", width)
            parameters = {"height": height, "width": section_width}
        elif shape == "circle":
            diameter = parameters.get("diameter", thickness)
            height = section_width = diameter
            parameters = {"diameter": diameter}
        elif shape == "circular_tube":
            outer_diameter = parameters.get("outer_diameter", thickness)
            wall_thickness = parameters.get("wall_thickness", outer_diameter * 0.1)
            if wall_thickness * 2.0 >= outer_diameter:
                raise ValueError("圆管壁厚必须小于外径的一半。")
            height = section_width = outer_diameter
            parameters = {
                "outer_diameter": outer_diameter,
                "wall_thickness": wall_thickness,
            }
        elif shape == "box":
            outer_height = parameters.get("outer_height", thickness)
            outer_width = parameters.get("outer_width", width)
            wall_thickness = parameters.get(
                "wall_thickness",
                min(outer_height, outer_width) * 0.1,
            )
            if wall_thickness * 2.0 >= min(outer_height, outer_width):
                raise ValueError("矩形管壁厚必须小于外高和外宽的一半。")
            height = outer_height
            section_width = outer_width
            parameters = {
                "outer_height": outer_height,
                "outer_width": outer_width,
                "wall_thickness": wall_thickness,
            }
        elif shape == "i_section":
            height = parameters.get("height", thickness)
            flange_width = parameters.get("flange_width", width)
            flange_thickness = parameters.get("flange_thickness", height * 0.1)
            web_thickness = parameters.get("web_thickness", flange_width * 0.1)
            if flange_thickness * 2.0 >= height:
                raise ValueError("工字形翼缘厚度必须小于截面高度的一半。")
            if web_thickness >= flange_width:
                raise ValueError("工字形腹板厚度必须小于翼缘宽度。")
            section_width = flange_width
            parameters = {
                "height": height,
                "flange_width": flange_width,
                "flange_thickness": flange_thickness,
                "web_thickness": web_thickness,
            }
        else:
            raise ValueError(f"暂不支持的截面类型：{shape}")

        object.__setattr__(self, "thickness", float(height))
        object.__setattr__(self, "width", float(section_width))
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class SensorAttachment:
    entity_id: str
    local_coordinates: tuple[float, ...]
    surface_side: str
    direction: tuple[float, float, float] = (1.0, 0.0, 0.0)
    gauge_length: float = 0.0
    integration_bounds: tuple[float, float] = (0.0, 1.0)
    surface_angle_degrees: float | None = None
    orientation_angle_degrees: float = 0.0

    def __post_init__(self):
        local_coordinates = tuple(float(value) for value in self.local_coordinates)
        if len(local_coordinates) != 1 or not 0.0 <= local_coordinates[0] <= 1.0:
            raise ValueError("梁测点局部坐标必须是 [0, 1] 内的单个参数。")
        side = self.surface_side.strip().lower()
        if side not in {"top", "bottom"}:
            raise ValueError("梁测点表面必须是 top 或 bottom。")
        surface_angle = self.surface_angle_degrees
        if surface_angle is None:
            surface_angle = 0.0 if side == "top" else 180.0
        surface_angle = float(surface_angle)
        orientation_angle = float(self.orientation_angle_degrees)
        if not isfinite(surface_angle) or not isfinite(orientation_angle):
            raise ValueError("测点环向位置角和测量轴角必须是有限数值。")
        surface_angle %= 360.0
        orientation_angle = (orientation_angle + 180.0) % 360.0 - 180.0
        side = "top" if surface_angle < 90.0 or surface_angle >= 270.0 else "bottom"
        direction = _finite_tuple(self.direction, size=3, field_name="测点测量轴")
        norm = sqrt(sum(value * value for value in direction))
        if norm <= 0.0:
            raise ValueError("测点测量轴不能为零向量。")
        direction = tuple(value / norm for value in direction)
        gauge_length = float(self.gauge_length)
        if not isfinite(gauge_length) or gauge_length < 0.0:
            raise ValueError("测点量长不能小于 0。")
        bounds = _finite_tuple(self.integration_bounds, size=2, field_name="积分区间")
        if bounds[0] < 0.0 or bounds[1] > 1.0 or bounds[1] <= bounds[0]:
            raise ValueError("归一化积分区间必须满足 0 <= a < b <= 1。")
        object.__setattr__(self, "local_coordinates", local_coordinates)
        object.__setattr__(self, "surface_side", side)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "gauge_length", gauge_length)
        object.__setattr__(self, "integration_bounds", bounds)
        object.__setattr__(self, "surface_angle_degrees", surface_angle)
        object.__setattr__(self, "orientation_angle_degrees", orientation_angle)


@dataclass(frozen=True)
class SensorDefinition:
    identifier: str
    label: str
    measurement_type: str
    attachment: SensorAttachment
    measured_value: float | None = None
    weight: float = 1.0
    channel_id: str | None = None

    def __post_init__(self):
        if not self.identifier.strip() or not self.label.strip():
            raise ValueError("测点 ID 和名称不能为空。")
        if not self.measurement_type.strip():
            raise ValueError("测点测量类型不能为空。")
        if self.measured_value is not None:
            value = float(self.measured_value)
            if not isfinite(value):
                raise ValueError("测点数值必须是有限数。")
            object.__setattr__(self, "measured_value", value)
        weight = float(self.weight)
        if not isfinite(weight) or weight <= 0.0:
            raise ValueError("测点权重必须大于 0。")
        object.__setattr__(self, "weight", weight)


@dataclass(frozen=True)
class BoundaryCondition:
    identifier: str
    node_id: str
    dof: str
    value: float = 0.0

    def __post_init__(self):
        dof = self.dof.strip().lower()
        if dof not in {"u", "v", "phi"}:
            raise ValueError("二维梁自由度必须是 u、v 或 phi。")
        value = float(self.value)
        if not isfinite(value):
            raise ValueError("边界条件值必须是有限数。")
        object.__setattr__(self, "dof", dof)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class AnalysisCase:
    identifier: str
    name: str
    algorithm_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    algorithm_version: str | None = None
    parameter_schema_version: str | None = None

    def __post_init__(self):
        if not self.identifier.strip() or not self.name.strip() or not self.algorithm_id.strip():
            raise ValueError("分析工况 ID、名称和算法 ID 不能为空。")
        object.__setattr__(self, "algorithm_id", self.algorithm_id.strip())
        if self.algorithm_version is not None:
            if not isinstance(self.algorithm_version, str) or not self.algorithm_version.strip():
                raise ValueError("分析工况算法版本不能为空字符串。")
            object.__setattr__(self, "algorithm_version", self.algorithm_version.strip())
        if self.parameter_schema_version is not None:
            if (
                not isinstance(self.parameter_schema_version, str)
                or not self.parameter_schema_version.strip()
            ):
                raise ValueError("分析工况参数模式版本不能为空字符串。")
            object.__setattr__(
                self,
                "parameter_schema_version",
                self.parameter_schema_version.strip(),
            )
        if not isinstance(self.parameters, Mapping):
            raise ValueError("analysis_case.parameters 必须是 JSON 对象。")
        object.__setattr__(
            self,
            "parameters",
            _normalize_json_value(
                self.parameters,
                field_path="analysis_case.parameters",
            ),
        )


def _infer_modeling_space(
    nodes: tuple[StructuralNode, ...],
    elements: tuple[BeamElement, ...],
) -> str:
    if any(element.family.startswith("beam3d") for element in elements):
        return "3d"
    if any(abs(node.coordinates[2]) > 1.0e-10 for node in nodes):
        return "3d"
    if any(
        element.geometry.kind == "circular_arc"
        and element.geometry.parameters.get("plane") != "xy"
        for element in elements
    ):
        return "3d"
    if any(
        element.geometry.kind == "nurbs_curve"
        and any(
            abs(point[2]) > 1.0e-10
            for point in element.geometry.parameters.get("control_points", ())
        )
        for element in elements
    ):
        return "3d"
    if any(
        element.geometry.kind == "parametric_curve"
        and not parametric_curve_is_xy(element.geometry.parameters)
        for element in elements
    ):
        return "3d"
    return "2d"


@dataclass(frozen=True)
class ProjectDocument:
    identifier: str
    name: str
    nodes: tuple[StructuralNode, ...]
    elements: tuple[BeamElement, ...]
    modeling_space: str = "2d"
    sensors: tuple[SensorDefinition, ...] = ()
    boundary_conditions: tuple[BoundaryCondition, ...] = ()
    materials: tuple[MaterialDefinition, ...] = ()
    sections: tuple[SectionDefinition, ...] = ()
    analysis_cases: tuple[AnalysisCase, ...] = ()
    active_analysis_id: str | None = None
    view_state: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = CURRENT_PROJECT_SCHEMA_VERSION
    revision: int = 0

    def __post_init__(self):
        if not self.identifier.strip() or not self.name.strip():
            raise ValueError("项目 ID 和名称不能为空。")
        if int(self.schema_version) != CURRENT_PROJECT_SCHEMA_VERSION:
            raise ValueError(f"不支持的项目版本：{self.schema_version}")
        modeling_space = str(self.modeling_space).strip().lower()
        if modeling_space not in {"2d", "3d"}:
            raise ValueError("建模空间必须是 2d 或 3d。")
        nodes = tuple(self.nodes)
        elements = tuple(self.elements)
        sensors = tuple(self.sensors)
        boundaries = tuple(self.boundary_conditions)
        materials = tuple(self.materials)
        sections = tuple(self.sections)
        analyses = tuple(self.analysis_cases)
        all_entities = nodes + elements + sensors + boundaries + materials + sections + analyses
        identifiers = [entity.identifier for entity in all_entities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("项目实体 ID 必须全局唯一。")
        if modeling_space == "2d":
            if any(abs(node.coordinates[2]) > 1.0e-10 for node in nodes):
                raise ValueError("二维模型的全部节点必须位于 XY 平面。")
            if any(
                element.geometry.kind == "circular_arc"
                and element.geometry.parameters.get("plane") != "xy"
                for element in elements
            ):
                raise ValueError("二维模型中的圆弧必须位于 XY 平面。")
            if any(
                element.geometry.kind == "nurbs_curve"
                and any(
                    abs(point[2]) > 1.0e-10
                    for point in element.geometry.parameters.get("control_points", ())
                )
                for element in elements
            ):
                raise ValueError("二维模型中的 NURBS 控制点必须位于 XY 平面。")
            if any(
                element.geometry.kind == "parametric_curve"
                and not parametric_curve_is_xy(element.geometry.parameters)
                for element in elements
            ):
                raise ValueError("二维模型中的参数曲线必须位于 XY 平面。")

        node_ids = {node.identifier for node in nodes}
        nodes_by_id = {node.identifier: node for node in nodes}
        element_ids = {element.identifier for element in elements}
        material_ids = {material.identifier for material in materials}
        section_ids = {section.identifier for section in sections}
        for element in elements:
            if any(node_id not in node_ids for node_id in element.node_ids):
                raise ValueError(f"梁单元 {element.identifier} 引用了不存在的节点。")
            if element.geometry.kind == "circular_arc":
                parameters = element.geometry.parameters
                start_point = tuple(
                    center + offset
                    for center, offset in zip(
                        parameters["center"],
                        parameters["start_vector"],
                    )
                )
                end_vector = _rotate_about_axis(
                    parameters["start_vector"],
                    parameters["normal"],
                    parameters["sweep_degrees"],
                )
                end_point = tuple(
                    center + offset
                    for center, offset in zip(parameters["center"], end_vector)
                )
                tolerance = max(float(parameters["radius"]), 1.0) * 1.0e-8
                if any(
                    _point_distance(nodes_by_id[node_id].coordinates, expected)
                    > tolerance
                    for node_id, expected in zip(
                        element.node_ids,
                        (start_point, end_point),
                    )
                ):
                    raise ValueError(
                        f"圆弧梁单元 {element.identifier} 的几何端点必须与结构节点一致。"
                    )
            if element.geometry.kind == "nurbs_curve":
                control_points = element.geometry.parameters["control_points"]
                endpoint_pairs = zip(
                    element.node_ids,
                    (control_points[0], control_points[-1]),
                )
                if any(
                    sqrt(
                        sum(
                            (actual - expected) ** 2
                            for actual, expected in zip(
                                nodes_by_id[node_id].coordinates,
                                control_point,
                            )
                        )
                    )
                    > 1.0e-8
                    for node_id, control_point in endpoint_pairs
                ):
                    raise ValueError(
                        f"NURBS 梁单元 {element.identifier} 的控制曲线端点必须与结构节点一致。"
                    )
            if element.geometry.kind == "parametric_curve":
                curve_endpoints = (
                    parametric_point_and_derivative(
                        element.geometry.parameters,
                        0.0,
                    )[0],
                    parametric_point_and_derivative(
                        element.geometry.parameters,
                        1.0,
                    )[0],
                )
                scale = max(
                    _point_distance(curve_endpoints[0], curve_endpoints[1]),
                    1.0,
                )
                if any(
                    _point_distance(nodes_by_id[node_id].coordinates, endpoint)
                    > scale * 1.0e-8
                    for node_id, endpoint in zip(element.node_ids, curve_endpoints)
                ):
                    raise ValueError(
                        f"参数曲线梁单元 {element.identifier} 的表达式端点必须与结构节点一致。"
                    )
            if element.material_id is not None and element.material_id not in material_ids:
                raise ValueError(f"梁单元 {element.identifier} 引用了不存在的材料。")
            if element.section_id is not None and element.section_id not in section_ids:
                raise ValueError(f"梁单元 {element.identifier} 引用了不存在的截面。")
        for sensor in sensors:
            if sensor.attachment.entity_id not in element_ids:
                raise ValueError(f"测点 {sensor.label} 引用了不存在的梁单元。")
        for boundary in boundaries:
            if boundary.node_id not in node_ids:
                raise ValueError("边界条件引用了不存在的节点。")
        analysis_ids = {analysis.identifier for analysis in analyses}
        if self.active_analysis_id is not None and self.active_analysis_id not in analysis_ids:
            raise ValueError("当前分析工况 ID 不存在。")

        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "elements", elements)
        object.__setattr__(self, "modeling_space", modeling_space)
        object.__setattr__(self, "sensors", sensors)
        object.__setattr__(self, "boundary_conditions", boundaries)
        object.__setattr__(self, "materials", materials)
        object.__setattr__(self, "sections", sections)
        object.__setattr__(self, "analysis_cases", analyses)
        object.__setattr__(self, "view_state", dict(self.view_state))
        object.__setattr__(self, "schema_version", int(self.schema_version))
        object.__setattr__(self, "revision", int(self.revision))

    def revised(self, **changes) -> "ProjectDocument":
        changes.setdefault("revision", self.revision + 1)
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProjectDocument":
        data = dict(payload)
        allowed_fields = {
            "identifier",
            "name",
            "nodes",
            "elements",
            "modeling_space",
            "sensors",
            "boundary_conditions",
            "materials",
            "sections",
            "analysis_cases",
            "active_analysis_id",
            "view_state",
            "schema_version",
            "revision",
        }
        unknown_fields = sorted(set(data) - allowed_fields)
        if unknown_fields:
            raise ValueError(
                "项目文件包含当前版本不支持的字段："
                + "、".join(unknown_fields)
            )
        raw_version = data.get("schema_version", 1)
        if isinstance(raw_version, bool):
            raise ValueError("项目 schema_version 必须是整数。")
        if isinstance(raw_version, int):
            source_version = raw_version
        elif isinstance(raw_version, str) and raw_version.strip().lstrip("+-").isdigit():
            source_version = int(raw_version.strip())
        else:
            raise ValueError("项目 schema_version 必须是整数。")
        if source_version < 1 or source_version > CURRENT_PROJECT_SCHEMA_VERSION:
            raise ValueError(f"不支持的项目版本：{source_version}")
        if source_version in {1, 2, 3, 4, 5, 6}:
            data["schema_version"] = CURRENT_PROJECT_SCHEMA_VERSION
        nodes = tuple(StructuralNode(**item) for item in data.get("nodes", []))
        elements = tuple(BeamElement(**item) for item in data.get("elements", []))
        modeling_space = data.get("modeling_space")
        if modeling_space is None:
            modeling_space = _infer_modeling_space(nodes, elements)
        raw_analysis_cases = data.get("analysis_cases", [])
        if not isinstance(raw_analysis_cases, (list, tuple)):
            raise ValueError("analysis_cases 必须是列表。")
        analysis_cases = []
        for index, item in enumerate(raw_analysis_cases):
            if not isinstance(item, Mapping):
                raise ValueError(f"analysis_cases[{index}] 必须是对象。")
            try:
                analysis_cases.append(AnalysisCase(**item))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"analysis_cases[{index}] 无效：{exc}") from exc

        return cls(
            identifier=str(data["identifier"]),
            name=str(data["name"]),
            nodes=nodes,
            elements=elements,
            modeling_space=modeling_space,
            sensors=tuple(
                SensorDefinition(
                    identifier=item["identifier"],
                    label=item["label"],
                    measurement_type=item["measurement_type"],
                    attachment=SensorAttachment(**item["attachment"]),
                    measured_value=item.get("measured_value"),
                    weight=item.get("weight", 1.0),
                    channel_id=item.get("channel_id"),
                )
                for item in data.get("sensors", [])
            ),
            boundary_conditions=tuple(
                BoundaryCondition(**item) for item in data.get("boundary_conditions", [])
            ),
            materials=tuple(MaterialDefinition(**item) for item in data.get("materials", [])),
            sections=tuple(SectionDefinition(**item) for item in data.get("sections", [])),
            analysis_cases=tuple(analysis_cases),
            active_analysis_id=data.get("active_analysis_id"),
            view_state=data.get("view_state", {}),
            schema_version=data.get("schema_version", CURRENT_PROJECT_SCHEMA_VERSION),
            revision=data.get("revision", 0),
        )


def empty_beam_project(
    name: str = "未命名项目",
    *,
    modeling_space: str = "2d",
) -> ProjectDocument:
    modeling_space = str(modeling_space).strip().lower()
    if modeling_space not in {"2d", "3d"}:
        raise ValueError("建模空间必须是 2d 或 3d。")
    material = MaterialDefinition(new_entity_id("material"), "默认材料")
    section = SectionDefinition(new_entity_id("section"), "默认矩形截面", 0.001)
    node_a = StructuralNode(new_entity_id("node"), (0.0, 0.0, 0.0))
    node_b = StructuralNode(new_entity_id("node"), (1.0, 0.0, 0.0))
    element = BeamElement(
        new_entity_id("element"),
        (node_a.identifier, node_b.identifier),
        family=(
            "beam2d_euler_bernoulli"
            if modeling_space == "2d"
            else "beam3d_line"
        ),
        section_id=section.identifier,
        material_id=material.identifier,
    )
    return ProjectDocument(
        identifier=new_entity_id("project"),
        name=name,
        nodes=(node_a, node_b),
        elements=(element,),
        modeling_space=modeling_space,
        materials=(material,),
        sections=(section,),
    )
