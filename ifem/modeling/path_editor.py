from __future__ import annotations

from dataclasses import dataclass, replace
from math import atan2, ceil, cos, degrees, isfinite, radians, sin, sqrt
from typing import Mapping

from ifem.domain.project import (
    BeamElement,
    BeamGeometryDefinition,
    MaterialDefinition,
    ProjectDocument,
    SectionDefinition,
    SensorAttachment,
    SensorDefinition,
    StructuralNode,
    new_entity_id,
)
from ifem.modeling.section_geometry import section_boundary_point


_GEOMETRY_TOLERANCE = 1.0e-10


def _distance(point_a, point_b) -> float:
    return sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(point_a, point_b)))


def _interpolate(point_a, point_b, parameter: float) -> tuple[float, float, float]:
    return tuple(
        float(a) + float(parameter) * (float(b) - float(a))
        for a, b in zip(point_a, point_b)
    )


def _dot(vector_a, vector_b) -> float:
    return sum(float(a) * float(b) for a, b in zip(vector_a, vector_b))


def _cross(vector_a, vector_b) -> tuple[float, float, float]:
    return (
        float(vector_a[1]) * float(vector_b[2]) - float(vector_a[2]) * float(vector_b[1]),
        float(vector_a[2]) * float(vector_b[0]) - float(vector_a[0]) * float(vector_b[2]),
        float(vector_a[0]) * float(vector_b[1]) - float(vector_a[1]) * float(vector_b[0]),
    )


def _normalize(vector) -> tuple[float, float, float]:
    length = sqrt(_dot(vector, vector))
    if length <= _GEOMETRY_TOLERANCE:
        raise ValueError("方向向量不能为零。")
    return tuple(float(value) / length for value in vector)


def _rotate_about_axis(vector, axis, angle: float) -> tuple[float, float, float]:
    axis = _normalize(axis)
    cosine = cos(angle)
    sine = sin(angle)
    cross = _cross(axis, vector)
    projection = _dot(axis, vector)
    return tuple(
        float(value) * cosine
        + float(cross_value) * sine
        + float(axis_value) * projection * (1.0 - cosine)
        for value, cross_value, axis_value in zip(vector, cross, axis)
    )


@dataclass(frozen=True)
class PathSensorLocation:
    global_position: tuple[float, float, float]
    path_distance: float
    element_index: int
    element_id: str
    local_coordinate: float
    local_distance: float
    element_length: float
    zone_a: float
    zone_b: float

    @property
    def global_x(self) -> float:
        return self.global_position[0]

    @property
    def local_x(self) -> float:
        return self.local_distance


@dataclass(frozen=True)
class PathSensorOrientation:
    centerline_position: tuple[float, float, float]
    tangent: tuple[float, float, float]
    reference_normal: tuple[float, float, float]
    binormal: tuple[float, float, float]
    surface_radial: tuple[float, float, float]
    surface_normal: tuple[float, float, float]
    surface_circumferential: tuple[float, float, float]
    measurement_direction: tuple[float, float, float]


@dataclass(frozen=True)
class BeamSurfaceLocation:
    """Stable beam attachment reconstructed from a rendered surface point."""

    element_index: int
    element_id: str
    local_coordinate: float
    path_distance: float
    centerline_position: tuple[float, float, float]
    global_position: tuple[float, float, float]
    picked_position: tuple[float, float, float]
    surface_angle_degrees: float
    surface_side: str
    tangent: tuple[float, float, float]
    reference_normal: tuple[float, float, float]
    binormal: tuple[float, float, float]
    surface_radial: tuple[float, float, float]
    surface_normal: tuple[float, float, float]
    surface_circumferential: tuple[float, float, float]
    display_scale: float
    snap_distance: float


@dataclass(frozen=True)
class GeometryCapability:
    kind: str
    dimension: int
    total_length: float
    legacy_solver_compatible: bool
    reason: str
    modeling_space: str = "2d"
    geometry_kinds: tuple[str, ...] = ()
    mixed_geometry: bool = False


class PathBeamEditor:
    """Algorithm-independent editor for a single connected beam path."""

    @staticmethod
    def ordered_path(
        project: ProjectDocument,
    ) -> tuple[tuple[StructuralNode, ...], tuple[BeamElement, ...]]:
        if len(project.nodes) < 2:
            raise ValueError("梁路径至少需要两个节点。")
        if len(project.elements) != len(project.nodes) - 1:
            raise ValueError("当前建模器仅支持一条无分支梁路径。")

        node_by_id = {node.identifier: node for node in project.nodes}
        adjacency: dict[str, list[tuple[str, BeamElement]]] = {
            node.identifier: [] for node in project.nodes
        }
        for element in project.elements:
            node_a, node_b = element.node_ids
            adjacency[node_a].append((node_b, element))
            adjacency[node_b].append((node_a, element))

        if any(len(neighbors) > 2 for neighbors in adjacency.values()):
            raise ValueError("当前建模器暂不支持分支梁。")
        endpoints = {node_id for node_id, neighbors in adjacency.items() if len(neighbors) == 1}
        if len(endpoints) != 2:
            raise ValueError("梁单元必须组成一条连续的开放路径。")

        start = next(
            node.identifier for node in project.nodes if node.identifier in endpoints
        )
        ordered_nodes = [node_by_id[start]]
        ordered_elements = []
        previous = None
        current = start
        while True:
            candidates = [item for item in adjacency[current] if item[0] != previous]
            if not candidates:
                break
            if len(candidates) != 1:
                raise ValueError("梁路径存在分支或重复连接。")
            next_id, element = candidates[0]
            ordered_elements.append(element)
            ordered_nodes.append(node_by_id[next_id])
            previous, current = current, next_id

        if len(ordered_nodes) != len(project.nodes):
            raise ValueError("梁模型中存在未连接的节点或单元。")
        return tuple(ordered_nodes), tuple(ordered_elements)

    @staticmethod
    def ordered_nodes(project: ProjectDocument) -> tuple[StructuralNode, ...]:
        return PathBeamEditor.ordered_path(project)[0]

    @staticmethod
    def ordered_elements(project: ProjectDocument) -> tuple[BeamElement, ...]:
        return PathBeamEditor.ordered_path(project)[1]

    @staticmethod
    def element_nodes(
        project: ProjectDocument,
        element: BeamElement,
    ) -> tuple[StructuralNode, StructuralNode]:
        node_by_id = {node.identifier: node for node in project.nodes}
        return node_by_id[element.node_ids[0]], node_by_id[element.node_ids[1]]

    @staticmethod
    def _resolve_element(project: ProjectDocument, element: BeamElement | str) -> BeamElement:
        if isinstance(element, BeamElement):
            return element
        resolved = next(
            (item for item in project.elements if item.identifier == element),
            None,
        )
        if resolved is None:
            raise KeyError("未知梁单元。")
        return resolved

    @staticmethod
    def element_length(project: ProjectDocument, element: BeamElement | str) -> float:
        element = PathBeamEditor._resolve_element(project, element)
        if element.geometry.kind == "circular_arc":
            parameters = element.geometry.parameters
            return float(parameters["radius"]) * abs(radians(parameters["sweep_degrees"]))
        if element.geometry.kind != "line":
            raise ValueError(f"暂不支持的梁几何类型：{element.geometry.kind}")
        node_a, node_b = PathBeamEditor.element_nodes(project, element)
        return _distance(node_a.coordinates, node_b.coordinates)

    @staticmethod
    def total_length(project: ProjectDocument) -> float:
        return sum(
            PathBeamEditor.element_length(project, element)
            for element in PathBeamEditor.ordered_elements(project)
        )

    @staticmethod
    def point_on_element(
        project: ProjectDocument,
        element: BeamElement | str,
        local_coordinate: float,
    ) -> tuple[float, float, float]:
        element = PathBeamEditor._resolve_element(project, element)
        parameter = float(local_coordinate)
        if not 0.0 <= parameter <= 1.0:
            raise ValueError("梁单元局部坐标必须位于 [0, 1]。")
        if element.geometry.kind == "circular_arc":
            parameters = element.geometry.parameters
            angle = radians(parameters["sweep_degrees"]) * parameter
            radius_vector = _rotate_about_axis(
                parameters["start_vector"],
                parameters["normal"],
                angle,
            )
            return tuple(
                float(center) + float(offset)
                for center, offset in zip(parameters["center"], radius_vector)
            )
        if element.geometry.kind != "line":
            raise ValueError(f"暂不支持的梁几何类型：{element.geometry.kind}")
        node_a, node_b = PathBeamEditor.element_nodes(project, element)
        return _interpolate(node_a.coordinates, node_b.coordinates, parameter)

    @staticmethod
    def tangent_on_element(
        project: ProjectDocument,
        element: BeamElement | str,
        local_coordinate: float,
    ) -> tuple[float, float, float]:
        element = PathBeamEditor._resolve_element(project, element)
        parameter = min(1.0, max(0.0, float(local_coordinate)))
        if element.geometry.kind == "circular_arc":
            parameters = element.geometry.parameters
            angle = radians(parameters["sweep_degrees"]) * parameter
            radius_vector = _rotate_about_axis(
                parameters["start_vector"],
                parameters["normal"],
                angle,
            )
            tangent = _cross(parameters["normal"], radius_vector)
            if float(parameters["sweep_degrees"]) < 0.0:
                tangent = tuple(-value for value in tangent)
            return _normalize(tangent)
        node_a, node_b = PathBeamEditor.element_nodes(project, element)
        return _normalize(
            tuple(
                float(right) - float(left)
                for left, right in zip(node_a.coordinates, node_b.coordinates)
            )
        )

    @staticmethod
    def section_frame(
        project: ProjectDocument,
        element: BeamElement | str,
        local_coordinate: float,
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]:
        element = PathBeamEditor._resolve_element(project, element)
        tangent = PathBeamEditor.tangent_on_element(project, element, local_coordinate)
        reference = (
            tuple(float(value) for value in element.geometry.parameters["normal"])
            if element.geometry.kind == "circular_arc"
            else (0.0, 0.0, 1.0)
        )
        normal = _cross(reference, tangent)
        if _dot(normal, normal) <= _GEOMETRY_TOLERANCE**2:
            for fallback in ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0)):
                normal = _cross(fallback, tangent)
                if _dot(normal, normal) > _GEOMETRY_TOLERANCE**2:
                    break
        normal = _normalize(normal)
        binormal = _normalize(_cross(tangent, normal))
        return tangent, normal, binormal

    @staticmethod
    def sensor_orientation(
        project: ProjectDocument,
        sensor: SensorDefinition | str,
    ) -> PathSensorOrientation:
        if isinstance(sensor, str):
            sensor = next(
                (item for item in project.sensors if item.identifier == sensor),
                None,
            )
            if sensor is None:
                raise KeyError("未知测点。")
        element = PathBeamEditor._resolve_element(
            project,
            sensor.attachment.entity_id,
        )
        xi = sensor.attachment.local_coordinates[0]
        centerline = PathBeamEditor.point_on_element(project, element, xi)
        tangent, frame_normal, binormal = PathBeamEditor.section_frame(
            project,
            element,
            xi,
        )
        surface_angle = radians(sensor.attachment.surface_angle_degrees)
        radial = _normalize(
            tuple(
                cos(surface_angle) * normal_value
                + sin(surface_angle) * binormal_value
                for normal_value, binormal_value in zip(frame_normal, binormal)
            )
        )
        section = next(
            (
                item
                for item in project.sections
                if item.identifier == element.section_id
            ),
            project.sections[0] if project.sections else None,
        )
        if section is None:
            surface_normal = radial
            circumferential = _normalize(
                tuple(
                    -sin(surface_angle) * normal_value
                    + cos(surface_angle) * binormal_value
                    for normal_value, binormal_value in zip(frame_normal, binormal)
                )
            )
        else:
            boundary = section_boundary_point(
                section,
                sensor.attachment.surface_angle_degrees,
            )
            surface_normal = _normalize(
                tuple(
                    boundary.outward_normal[0] * normal_value
                    + boundary.outward_normal[1] * binormal_value
                    for normal_value, binormal_value in zip(frame_normal, binormal)
                )
            )
            circumferential = _normalize(
                tuple(
                    boundary.boundary_tangent[0] * normal_value
                    + boundary.boundary_tangent[1] * binormal_value
                    for normal_value, binormal_value in zip(frame_normal, binormal)
                )
            )
        stored_direction = _normalize(sensor.attachment.direction)
        radial_component = _dot(stored_direction, surface_normal)
        surface_direction = tuple(
            value - radial_component * normal_value
            for value, normal_value in zip(stored_direction, surface_normal)
        )
        direction = (
            tangent
            if _dot(surface_direction, surface_direction) <= _GEOMETRY_TOLERANCE**2
            else _normalize(surface_direction)
        )
        return PathSensorOrientation(
            centerline_position=centerline,
            tangent=tangent,
            reference_normal=frame_normal,
            binormal=binormal,
            surface_radial=radial,
            surface_normal=surface_normal,
            surface_circumferential=circumferential,
            measurement_direction=direction,
        )

    @staticmethod
    def sensor_direction_from_angles(
        project: ProjectDocument,
        sensor: SensorDefinition | str,
    ) -> tuple[float, float, float]:
        if isinstance(sensor, str):
            sensor = next(
                (item for item in project.sensors if item.identifier == sensor),
                None,
            )
            if sensor is None:
                raise KeyError("未知测点。")
        orientation = PathBeamEditor.sensor_orientation(project, sensor)
        orientation_angle = radians(sensor.attachment.orientation_angle_degrees)
        return _normalize(
            tuple(
                cos(orientation_angle) * tangent_value
                + sin(orientation_angle) * circumferential_value
                for tangent_value, circumferential_value in zip(
                    orientation.tangent,
                    orientation.surface_circumferential,
                )
            )
        )

    @staticmethod
    def sensor_surface_position(
        project: ProjectDocument,
        sensor: SensorDefinition | str,
    ) -> tuple[float, float, float]:
        if isinstance(sensor, str):
            sensor = next(
                (item for item in project.sensors if item.identifier == sensor),
                None,
            )
            if sensor is None:
                raise KeyError("未知测点。")
        element = PathBeamEditor._resolve_element(project, sensor.attachment.entity_id)
        section = next(
            (
                item
                for item in project.sections
                if item.identifier == element.section_id
            ),
            project.sections[0] if project.sections else None,
        )
        orientation = PathBeamEditor.sensor_orientation(project, sensor)
        if section is None:
            return orientation.centerline_position
        boundary = section_boundary_point(
            section,
            sensor.attachment.surface_angle_degrees,
        )
        return tuple(
            center + boundary.distance * radial
            for center, radial in zip(
                orientation.centerline_position,
                orientation.surface_radial,
            )
        )

    @staticmethod
    def sample_element(
        project: ProjectDocument,
        element: BeamElement | str,
        sample_count: int | None = None,
    ) -> tuple[tuple[float, float, float], ...]:
        element = PathBeamEditor._resolve_element(project, element)
        if element.geometry.kind == "line":
            count = 2
        elif element.geometry.kind == "circular_arc":
            sweep = abs(float(element.geometry.parameters["sweep_degrees"]))
            count = sample_count or min(181, max(17, ceil(sweep / 3.0) + 1))
        else:
            raise ValueError(f"暂不支持的梁几何类型：{element.geometry.kind}")
        count = max(2, int(count))
        return tuple(
            PathBeamEditor.point_on_element(project, element, index / (count - 1))
            for index in range(count)
        )

    @staticmethod
    def sample_project(project: ProjectDocument) -> tuple[tuple[float, float, float], ...]:
        points = []
        nodes, elements = PathBeamEditor.ordered_path(project)
        for path_start, element in zip(nodes, elements):
            samples = PathBeamEditor.sample_element(project, element)
            if element.node_ids[0] != path_start.identifier:
                samples = tuple(reversed(samples))
            points.extend(samples if not points else samples[1:])
        return tuple(points)

    @staticmethod
    def sensor_location(project: ProjectDocument, sensor_id: str) -> PathSensorLocation:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        nodes, elements = PathBeamEditor.ordered_path(project)
        cumulative = 0.0
        for index, (path_start, path_end, element) in enumerate(
            zip(nodes, nodes[1:], elements)
        ):
            length = PathBeamEditor.element_length(project, element)
            if element.identifier != sensor.attachment.entity_id:
                cumulative += length
                continue
            xi = sensor.attachment.local_coordinates[0]
            bounds = sensor.attachment.integration_bounds
            point = PathBeamEditor.point_on_element(project, element, xi)
            if element.node_ids[0] == path_start.identifier:
                path_xi = xi
                path_bounds = bounds
            else:
                path_xi = 1.0 - xi
                path_bounds = (1.0 - bounds[1], 1.0 - bounds[0])
            return PathSensorLocation(
                global_position=point,
                path_distance=cumulative + path_xi * length,
                element_index=index,
                element_id=element.identifier,
                local_coordinate=xi,
                local_distance=path_xi * length,
                element_length=length,
                zone_a=path_bounds[0] * length,
                zone_b=path_bounds[1] * length,
            )
        raise ValueError("测点引用的梁单元不在当前路径中。")

    @staticmethod
    def element_at_path_distance(
        project: ProjectDocument,
        path_distance: float,
    ) -> tuple[int, BeamElement, float]:
        """Resolve an arc-length coordinate to an element and its native parameter."""

        distance = float(path_distance)
        if not isfinite(distance):
            raise ValueError("路径弧长必须是有限数值。")
        nodes, elements = PathBeamEditor.ordered_path(project)
        total = PathBeamEditor.total_length(project)
        tolerance = max(total, 1.0) * 1.0e-10
        if distance < -tolerance or distance > total + tolerance:
            raise ValueError(f"路径弧长必须位于 [0, {total:.8g}] m。")
        distance = min(total, max(0.0, distance))

        cumulative = 0.0
        for index, (path_start, element) in enumerate(zip(nodes, elements)):
            length = PathBeamEditor.element_length(project, element)
            end = cumulative + length
            if distance <= end + tolerance or index == len(elements) - 1:
                path_xi = min(1.0, max(0.0, (distance - cumulative) / length))
                local_xi = (
                    path_xi
                    if element.node_ids[0] == path_start.identifier
                    else 1.0 - path_xi
                )
                return index, element, local_xi
            cumulative = end
        raise ValueError("无法将路径弧长映射到梁实体。")

    @staticmethod
    def nearest_element(
        project: ProjectDocument,
        point,
    ) -> tuple[int, BeamElement, float, float]:
        target = tuple(float(value) for value in point)
        if len(target) != 3 or not all(isfinite(value) for value in target):
            raise ValueError("拾取点必须包含三个有限坐标。")
        elements = PathBeamEditor.ordered_elements(project)
        best = None
        for index, element in enumerate(elements):
            samples = PathBeamEditor.sample_element(project, element, sample_count=121)
            segment_count = len(samples) - 1
            for sample_index, (point_a, point_b) in enumerate(zip(samples, samples[1:])):
                vector = tuple(b - a for a, b in zip(point_a, point_b))
                denominator = sum(value * value for value in vector)
                if denominator <= _GEOMETRY_TOLERANCE**2:
                    continue
                segment_xi = sum(
                    (value - origin) * direction
                    for value, origin, direction in zip(target, point_a, vector)
                ) / denominator
                segment_xi = min(1.0, max(0.0, segment_xi))
                projected = _interpolate(point_a, point_b, segment_xi)
                distance = _distance(target, projected)
                xi = (sample_index + segment_xi) / segment_count
                candidate = (distance, index, element, float(xi))
                if best is None or candidate[0] < best[0]:
                    best = candidate
        if best is None:
            raise ValueError("模型中没有可拾取的梁单元。")
        distance, index, element, xi = best
        if element.geometry.kind != "line":
            search_radius = 1.0 / 120.0
            low = max(0.0, xi - search_radius)
            high = min(1.0, xi + search_radius)
            for _iteration in range(36):
                left = (2.0 * low + high) / 3.0
                right = (low + 2.0 * high) / 3.0
                left_distance = _distance(
                    target,
                    PathBeamEditor.point_on_element(project, element, left),
                )
                right_distance = _distance(
                    target,
                    PathBeamEditor.point_on_element(project, element, right),
                )
                if left_distance <= right_distance:
                    high = right
                else:
                    low = left
            xi = (low + high) * 0.5
            distance = _distance(
                target,
                PathBeamEditor.point_on_element(project, element, xi),
            )
        return index, element, xi, distance

    @staticmethod
    def surface_location_from_point(
        project: ProjectDocument,
        point,
        *,
        display_scale: float = 1.0,
    ) -> BeamSurfaceLocation:
        """Map a point on the rendered sweep back to beam and section parameters.

        The modeler may enlarge thin sections for display. ``display_scale`` removes
        that visual-only scale before the physical attachment point is calculated.
        """

        target = tuple(float(value) for value in point)
        if len(target) != 3 or not all(isfinite(value) for value in target):
            raise ValueError("表面拾取点必须包含三个有限坐标。")
        scale = float(display_scale)
        if not isfinite(scale) or scale <= 0.0:
            raise ValueError("截面显示倍率必须大于 0。")

        element_index, element, xi, _distance_to_axis = PathBeamEditor.nearest_element(
            project,
            target,
        )
        section = next(
            (
                item
                for item in project.sections
                if item.identifier == element.section_id
            ),
            project.sections[0] if project.sections else None,
        )
        if section is None:
            raise ValueError("请先定义梁截面，再在三维表面布置测点。")

        centerline = PathBeamEditor.point_on_element(project, element, xi)
        tangent, frame_normal, binormal = PathBeamEditor.section_frame(
            project,
            element,
            xi,
        )
        offset = tuple(value - center for value, center in zip(target, centerline))
        local_u = _dot(offset, frame_normal) / scale
        local_v = _dot(offset, binormal) / scale
        if local_u * local_u + local_v * local_v <= _GEOMETRY_TOLERANCE**2:
            raise ValueError("拾取位置过于接近梁轴线，无法确定截面环向位置。")

        surface_angle = degrees(atan2(local_v, local_u)) % 360.0
        boundary = section_boundary_point(section, surface_angle)
        global_position = tuple(
            center
            + boundary.local_position[0] * normal_value
            + boundary.local_position[1] * binormal_value
            for center, normal_value, binormal_value in zip(
                centerline,
                frame_normal,
                binormal,
            )
        )
        display_position = tuple(
            center + scale * (surface - center)
            for center, surface in zip(centerline, global_position)
        )
        surface_radial = _normalize(
            tuple(surface - center for surface, center in zip(global_position, centerline))
        )
        surface_normal = _normalize(
            tuple(
                boundary.outward_normal[0] * normal_value
                + boundary.outward_normal[1] * binormal_value
                for normal_value, binormal_value in zip(frame_normal, binormal)
            )
        )
        surface_circumferential = _normalize(
            tuple(
                boundary.boundary_tangent[0] * normal_value
                + boundary.boundary_tangent[1] * binormal_value
                for normal_value, binormal_value in zip(frame_normal, binormal)
            )
        )

        nodes, elements = PathBeamEditor.ordered_path(project)
        cumulative = sum(
            PathBeamEditor.element_length(project, previous)
            for previous in elements[:element_index]
        )
        element_length = PathBeamEditor.element_length(project, element)
        path_xi = (
            xi
            if element.node_ids[0] == nodes[element_index].identifier
            else 1.0 - xi
        )
        surface_side = (
            "top" if surface_angle < 90.0 or surface_angle >= 270.0 else "bottom"
        )
        return BeamSurfaceLocation(
            element_index=element_index,
            element_id=element.identifier,
            local_coordinate=float(xi),
            path_distance=cumulative + path_xi * element_length,
            centerline_position=tuple(float(value) for value in centerline),
            global_position=tuple(float(value) for value in global_position),
            picked_position=target,
            surface_angle_degrees=float(surface_angle),
            surface_side=surface_side,
            tangent=tangent,
            reference_normal=frame_normal,
            binormal=binormal,
            surface_radial=surface_radial,
            surface_normal=surface_normal,
            surface_circumferential=surface_circumferential,
            display_scale=scale,
            snap_distance=_distance(target, display_position),
        )

    @staticmethod
    def _family_for_geometry(modeling_space: str, geometry_kind: str) -> str:
        if modeling_space == "2d":
            return (
                "beam2d_curved"
                if geometry_kind == "circular_arc"
                else "beam2d_euler_bernoulli"
            )
        return "beam3d_curved" if geometry_kind == "circular_arc" else "beam3d_line"

    @staticmethod
    def set_modeling_space(
        project: ProjectDocument,
        modeling_space: str,
    ) -> ProjectDocument:
        modeling_space = str(modeling_space).strip().lower()
        if modeling_space not in {"2d", "3d"}:
            raise ValueError("建模空间必须是 2d 或 3d。")
        if modeling_space == "2d":
            if any(abs(node.coordinates[2]) > _GEOMETRY_TOLERANCE for node in project.nodes):
                raise ValueError("当前模型包含非零 z 坐标，不能直接切换为二维建模。")
            if any(
                element.geometry.kind == "circular_arc"
                and element.geometry.parameters.get("plane") != "xy"
                for element in project.elements
            ):
                raise ValueError("当前模型包含非 XY 圆弧，不能直接切换为二维建模。")
        elements = tuple(
            replace(
                element,
                family=PathBeamEditor._family_for_geometry(
                    modeling_space,
                    element.geometry.kind,
                ),
            )
            for element in project.elements
        )
        return project.revised(
            modeling_space=modeling_space,
            elements=elements,
        )

    @staticmethod
    def _element_template(project: ProjectDocument) -> BeamElement | None:
        return project.elements[0] if project.elements else None

    @staticmethod
    def _new_element(
        project: ProjectDocument,
        node_ids,
        *,
        template: BeamElement | None = None,
        family: str | None = None,
        geometry: BeamGeometryDefinition | None = None,
    ) -> BeamElement:
        template = template or PathBeamEditor._element_template(project)
        geometry = geometry or BeamGeometryDefinition()
        section_id = (
            template.section_id
            if template is not None
            else (project.sections[0].identifier if project.sections else None)
        )
        material_id = (
            template.material_id
            if template is not None
            else (project.materials[0].identifier if project.materials else None)
        )
        return BeamElement(
            identifier=new_entity_id("element"),
            node_ids=tuple(node_ids),
            family=family
            or (
                template.family
                if template is not None
                else PathBeamEditor._family_for_geometry(
                    project.modeling_space,
                    geometry.kind,
                )
            ),
            section_id=section_id,
            material_id=material_id,
            geometry=geometry,
        )

    @staticmethod
    def move_node(
        project: ProjectDocument,
        node_id: str,
        coordinates,
    ) -> ProjectDocument:
        coordinates = tuple(float(value) for value in coordinates)
        if len(coordinates) != 3 or not all(isfinite(value) for value in coordinates):
            raise ValueError("节点坐标必须包含三个有限数值。")
        nodes, elements = PathBeamEditor.ordered_path(project)
        target = next((node for node in nodes if node.identifier == node_id), None)
        if target is None:
            raise KeyError(f"未知节点：{node_id}")
        if any(
            node_id in element.node_ids and element.geometry.kind != "line"
            for element in elements
        ):
            raise ValueError("参数化圆弧端点由圆弧参数控制，请编辑圆弧半径、角度或平面。")
        for node in nodes:
            if node.identifier != node_id and _distance(node.coordinates, coordinates) <= _GEOMETRY_TOLERANCE:
                raise ValueError("两个结构节点不能位于同一位置。")
        for element in elements:
            if node_id not in element.node_ids:
                continue
            other_id = element.node_ids[1] if element.node_ids[0] == node_id else element.node_ids[0]
            other = next(node for node in nodes if node.identifier == other_id)
            if _distance(other.coordinates, coordinates) <= _GEOMETRY_TOLERANCE:
                raise ValueError("移动后会产生零长度梁单元。")
        updated = tuple(
            replace(node, coordinates=coordinates) if node.identifier == node_id else node
            for node in project.nodes
        )
        return project.revised(nodes=updated)

    @staticmethod
    def append_node(
        project: ProjectDocument,
        coordinates,
        *,
        endpoint_id: str | None = None,
    ) -> ProjectDocument:
        coordinates = tuple(float(value) for value in coordinates)
        if len(coordinates) != 3 or not all(isfinite(value) for value in coordinates):
            raise ValueError("新节点坐标必须包含三个有限数值。")
        if project.modeling_space == "2d" and abs(coordinates[2]) > _GEOMETRY_TOLERANCE:
            project = PathBeamEditor.set_modeling_space(project, "3d")
        nodes, elements = PathBeamEditor.ordered_path(project)
        endpoint_ids = {nodes[0].identifier, nodes[-1].identifier}
        endpoint_id = endpoint_id or nodes[-1].identifier
        if endpoint_id not in endpoint_ids:
            raise ValueError("新梁段只能从当前路径端点继续延伸。")
        endpoint = next(node for node in nodes if node.identifier == endpoint_id)
        if _distance(endpoint.coordinates, coordinates) <= _GEOMETRY_TOLERANCE:
            raise ValueError("新梁段长度必须大于零。")
        if any(_distance(node.coordinates, coordinates) <= _GEOMETRY_TOLERANCE for node in nodes):
            raise ValueError("该位置已经存在结构节点。")

        new_node = StructuralNode(new_entity_id("node"), coordinates)
        adjacent = next(element for element in elements if endpoint_id in element.node_ids)
        new_element = PathBeamEditor._new_element(
            project,
            (endpoint_id, new_node.identifier),
            template=adjacent,
            family=PathBeamEditor._family_for_geometry(
                project.modeling_space,
                "line",
            ),
        )
        if endpoint_id == nodes[0].identifier:
            project_nodes = (new_node,) + project.nodes
            project_elements = (new_element,) + project.elements
        else:
            project_nodes = project.nodes + (new_node,)
            project_elements = project.elements + (new_element,)
        return project.revised(nodes=project_nodes, elements=project_elements)

    @staticmethod
    def _path_endpoint_context(
        project: ProjectDocument,
        endpoint_id: str | None = None,
    ) -> tuple[
        tuple[StructuralNode, ...],
        tuple[BeamElement, ...],
        StructuralNode,
        BeamElement,
        tuple[float, float, float],
        bool,
    ]:
        nodes, elements = PathBeamEditor.ordered_path(project)
        endpoint_id = endpoint_id or nodes[-1].identifier
        if endpoint_id == nodes[-1].identifier:
            endpoint = nodes[-1]
            adjacent = elements[-1]
            xi = 1.0 if adjacent.node_ids[1] == endpoint_id else 0.0
            intrinsic = PathBeamEditor.tangent_on_element(project, adjacent, xi)
            outward = (
                intrinsic
                if adjacent.node_ids[1] == endpoint_id
                else tuple(-value for value in intrinsic)
            )
            prepend = False
        elif endpoint_id == nodes[0].identifier:
            endpoint = nodes[0]
            adjacent = elements[0]
            xi = 0.0 if adjacent.node_ids[0] == endpoint_id else 1.0
            intrinsic = PathBeamEditor.tangent_on_element(project, adjacent, xi)
            into_path = (
                intrinsic
                if adjacent.node_ids[0] == endpoint_id
                else tuple(-value for value in intrinsic)
            )
            outward = tuple(-value for value in into_path)
            prepend = True
        else:
            raise ValueError("新梁段只能追加到当前开放路径的端点。")
        return nodes, elements, endpoint, adjacent, _normalize(outward), prepend

    @staticmethod
    def append_straight_segment(
        project: ProjectDocument,
        *,
        length: float,
        direction: str | tuple[float, float, float] = "tangent",
        endpoint_id: str | None = None,
    ) -> ProjectDocument:
        length = float(length)
        if not isfinite(length) or length <= 0.0:
            raise ValueError("追加直线段长度必须大于 0。")
        nodes, _elements, endpoint, adjacent, tangent, prepend = (
            PathBeamEditor._path_endpoint_context(project, endpoint_id)
        )
        if isinstance(direction, str):
            key = direction.strip().lower()
            direction_map = {
                "tangent": tangent,
                "x": (1.0, 0.0, 0.0),
                "+x": (1.0, 0.0, 0.0),
                "-x": (-1.0, 0.0, 0.0),
                "y": (0.0, 1.0, 0.0),
                "+y": (0.0, 1.0, 0.0),
                "-y": (0.0, -1.0, 0.0),
                "z": (0.0, 0.0, 1.0),
                "+z": (0.0, 0.0, 1.0),
                "-z": (0.0, 0.0, -1.0),
            }
            if key not in direction_map:
                raise ValueError("直线段方向必须是切线或全局 ±X/±Y/±Z。")
            direction_vector = direction_map[key]
        else:
            direction_vector = _normalize(direction)
        if project.modeling_space == "2d" and abs(direction_vector[2]) > _GEOMETRY_TOLERANCE:
            raise ValueError("二维建模只能追加位于 XY 平面内的直线段。")
        new_coordinates = tuple(
            coordinate + length * component
            for coordinate, component in zip(endpoint.coordinates, direction_vector)
        )
        if any(
            _distance(node.coordinates, new_coordinates) <= _GEOMETRY_TOLERANCE
            for node in nodes
        ):
            raise ValueError("追加直线段的终点与已有节点重合。")
        new_node = StructuralNode(new_entity_id("node"), new_coordinates)
        new_element = PathBeamEditor._new_element(
            project,
            (endpoint.identifier, new_node.identifier),
            template=adjacent,
            family=PathBeamEditor._family_for_geometry(
                project.modeling_space,
                "line",
            ),
        )
        if prepend:
            return project.revised(
                nodes=(new_node,) + project.nodes,
                elements=(new_element,) + project.elements,
            )
        return project.revised(
            nodes=project.nodes + (new_node,),
            elements=project.elements + (new_element,),
        )

    @staticmethod
    def _oriented_circular_arc_geometry(
        *,
        start,
        tangent,
        radius: float,
        sweep_degrees: float,
        plane: str,
    ) -> tuple[BeamGeometryDefinition, tuple[float, float, float]]:
        radius = float(radius)
        sweep_degrees = float(sweep_degrees)
        plane = str(plane).strip().lower()
        if not isfinite(radius) or radius <= 0.0:
            raise ValueError("圆弧半径必须大于 0。")
        if (
            not isfinite(sweep_degrees)
            or abs(sweep_degrees) <= 1.0e-9
            or abs(sweep_degrees) >= 360.0
        ):
            raise ValueError("圆弧圆心角必须满足 0 < |角度| < 360°。")
        normals = {
            "xy": (0.0, 0.0, 1.0),
            "xz": (0.0, -1.0, 0.0),
            "yz": (1.0, 0.0, 0.0),
        }
        if plane not in normals:
            raise ValueError("圆弧平面必须是 XY、XZ 或 YZ。")
        start = tuple(float(value) for value in start)
        tangent = _normalize(tangent)
        normal = normals[plane]
        if abs(_dot(tangent, normal)) > 1.0e-8:
            raise ValueError("所选圆弧平面必须包含当前路径末端切线。")
        turn_sign = 1.0 if sweep_degrees > 0.0 else -1.0
        start_vector = tuple(
            turn_sign * radius * value
            for value in _cross(tangent, normal)
        )
        center = tuple(
            coordinate - offset
            for coordinate, offset in zip(start, start_vector)
        )
        geometry = BeamGeometryDefinition(
            kind="circular_arc",
            parameters={
                "radius": radius,
                "sweep_degrees": sweep_degrees,
                "plane": plane,
                "center": center,
                "normal": normal,
                "start_vector": start_vector,
            },
        )
        end_vector = _rotate_about_axis(
            start_vector,
            normal,
            radians(sweep_degrees),
        )
        end = tuple(
            center_value + offset
            for center_value, offset in zip(center, end_vector)
        )
        return geometry, end

    @staticmethod
    def append_circular_arc(
        project: ProjectDocument,
        *,
        radius: float,
        sweep_degrees: float,
        plane: str | None = None,
        endpoint_id: str | None = None,
    ) -> ProjectDocument:
        plane = "xy" if project.modeling_space == "2d" else str(plane or "xy").lower()
        if project.modeling_space == "2d" and plane != "xy":
            raise ValueError("二维建模只能追加 XY 平面圆弧。")
        nodes, _elements, endpoint, adjacent, tangent, prepend = (
            PathBeamEditor._path_endpoint_context(project, endpoint_id)
        )
        geometry, end = PathBeamEditor._oriented_circular_arc_geometry(
            start=endpoint.coordinates,
            tangent=tangent,
            radius=radius,
            sweep_degrees=sweep_degrees,
            plane=plane,
        )
        if any(
            _distance(node.coordinates, end) <= _GEOMETRY_TOLERANCE
            for node in nodes
        ):
            raise ValueError("追加圆弧的终点与已有节点重合。")
        new_node = StructuralNode(new_entity_id("node"), end)
        new_element = PathBeamEditor._new_element(
            project,
            (endpoint.identifier, new_node.identifier),
            template=adjacent,
            family=PathBeamEditor._family_for_geometry(
                project.modeling_space,
                "circular_arc",
            ),
            geometry=geometry,
        )
        if prepend:
            return project.revised(
                nodes=(new_node,) + project.nodes,
                elements=(new_element,) + project.elements,
            )
        return project.revised(
            nodes=project.nodes + (new_node,),
            elements=project.elements + (new_element,),
        )

    @staticmethod
    def _remap_sensor_after_split(
        sensor: SensorDefinition,
        first: BeamElement,
        second: BeamElement,
        split: float,
        first_length: float,
        second_length: float,
    ) -> SensorDefinition:
        xi = sensor.attachment.local_coordinates[0]
        bound_a, bound_b = sensor.attachment.integration_bounds
        if xi <= split:
            target = first
            scale_start, scale_end = 0.0, split
            target_length = first_length
        else:
            target = second
            scale_start, scale_end = split, 1.0
            target_length = second_length
        span = scale_end - scale_start
        new_xi = (xi - scale_start) / span
        clipped_a = max(bound_a, scale_start)
        clipped_b = min(bound_b, scale_end)
        if clipped_b - clipped_a <= 1.0e-9:
            half = min(0.15, 0.45 * span)
            clipped_a = max(scale_start, xi - half * span)
            clipped_b = min(scale_end, xi + half * span)
        bounds = (
            max(0.0, (clipped_a - scale_start) / span),
            min(1.0, (clipped_b - scale_start) / span),
        )
        attachment = replace(
            sensor.attachment,
            entity_id=target.identifier,
            local_coordinates=(min(1.0, max(0.0, new_xi)),),
            integration_bounds=bounds,
            gauge_length=(bounds[1] - bounds[0]) * target_length,
        )
        return replace(sensor, attachment=attachment)

    @staticmethod
    def insert_node(
        project: ProjectDocument,
        element_id: str,
        local_coordinate: float,
    ) -> ProjectDocument:
        split = float(local_coordinate)
        if not 1.0e-6 < split < 1.0 - 1.0e-6:
            raise ValueError("插入节点不能与已有端点重合。")
        original = next(
            (element for element in project.elements if element.identifier == element_id),
            None,
        )
        if original is None:
            raise KeyError(f"未知梁单元：{element_id}")
        if original.geometry.kind != "line":
            raise ValueError("参数化圆弧保持为单个几何实体，不在建模阶段拆分为梁段。")
        point = PathBeamEditor.point_on_element(project, original, split)
        new_node = StructuralNode(new_entity_id("node"), point)
        first = replace(
            original,
            node_ids=(original.node_ids[0], new_node.identifier),
        )
        second = PathBeamEditor._new_element(
            project,
            (new_node.identifier, original.node_ids[1]),
            template=original,
        )
        original_length = PathBeamEditor.element_length(project, original)
        sensors = tuple(
            PathBeamEditor._remap_sensor_after_split(
                sensor,
                first,
                second,
                split,
                original_length * split,
                original_length * (1.0 - split),
            )
            if sensor.attachment.entity_id == original.identifier
            else sensor
            for sensor in project.sensors
        )
        element_index = project.elements.index(original)
        elements = (
            project.elements[:element_index]
            + (first, second)
            + project.elements[element_index + 1 :]
        )
        return project.revised(
            nodes=project.nodes + (new_node,),
            elements=elements,
            sensors=sensors,
        )

    @staticmethod
    def delete_node(project: ProjectDocument, node_id: str) -> ProjectDocument:
        nodes, elements = PathBeamEditor.ordered_path(project)
        if len(nodes) <= 2:
            raise ValueError("梁路径至少保留两个节点。")
        try:
            node_index = next(
                index for index, node in enumerate(nodes) if node.identifier == node_id
            )
        except StopIteration as exc:
            raise KeyError(f"未知节点：{node_id}") from exc

        removed_element_ids = set()
        sensors = list(project.sensors)
        if node_index in {0, len(nodes) - 1}:
            adjacent_index = 0 if node_index == 0 else len(elements) - 1
            removed = elements[adjacent_index]
            removed_element_ids.add(removed.identifier)
            remaining_elements = tuple(
                element for element in project.elements if element.identifier != removed.identifier
            )
            sensors = [
                sensor
                for sensor in sensors
                if sensor.attachment.entity_id != removed.identifier
            ]
        else:
            left_element = elements[node_index - 1]
            right_element = elements[node_index]
            if any(
                element.geometry.kind != "line"
                for element in (left_element, right_element)
            ):
                raise ValueError("不能通过删除节点合并参数化圆弧，请直接编辑圆弧参数。")
            removed_element_ids.update((left_element.identifier, right_element.identifier))
            left_node = nodes[node_index - 1]
            right_node = nodes[node_index + 1]
            left_length = PathBeamEditor.element_length(project, left_element)
            right_length = PathBeamEditor.element_length(project, right_element)
            old_total = left_length + right_length
            merged = replace(
                left_element,
                node_ids=(left_node.identifier, right_node.identifier),
                family=(
                    left_element.family
                    if left_element.family == right_element.family
                    else "beam3d_line"
                ),
            )
            merged_length = _distance(left_node.coordinates, right_node.coordinates)
            if merged_length <= _GEOMETRY_TOLERANCE:
                raise ValueError("删除该节点会产生零长度梁单元。")

            remapped = []
            for sensor in sensors:
                if sensor.attachment.entity_id not in removed_element_ids:
                    remapped.append(sensor)
                    continue
                location = PathBeamEditor.sensor_location(project, sensor.identifier)
                segment_offset = 0.0 if location.element_index == node_index - 1 else left_length
                center = segment_offset + location.local_distance
                zone_start = segment_offset + location.zone_a
                zone_end = segment_offset + location.zone_b
                bounds = (
                    min(1.0, max(0.0, zone_start / old_total)),
                    min(1.0, max(0.0, zone_end / old_total)),
                )
                if bounds[1] - bounds[0] <= 1.0e-9:
                    bounds = (max(0.0, center / old_total - 0.05), min(1.0, center / old_total + 0.05))
                attachment = replace(
                    sensor.attachment,
                    entity_id=merged.identifier,
                    local_coordinates=(min(1.0, max(0.0, center / old_total)),),
                    integration_bounds=bounds,
                    gauge_length=(bounds[1] - bounds[0]) * merged_length,
                )
                remapped.append(replace(sensor, attachment=attachment))
            sensors = remapped
            first_index = project.elements.index(left_element)
            second_index = project.elements.index(right_element)
            low, high = sorted((first_index, second_index))
            remaining_elements = (
                project.elements[:low] + (merged,) + project.elements[high + 1 :]
            )

        remaining_nodes = tuple(node for node in project.nodes if node.identifier != node_id)
        boundaries = tuple(
            boundary
            for boundary in project.boundary_conditions
            if boundary.node_id != node_id
        )
        return project.revised(
            nodes=remaining_nodes,
            elements=remaining_elements,
            sensors=tuple(sensors),
            boundary_conditions=boundaries,
        )

    @staticmethod
    def add_sensor(
        project: ProjectDocument,
        element_id: str,
        local_coordinate: float,
        surface_side: str,
        *,
        surface_angle_degrees: float | None = None,
        orientation_angle_degrees: float = 0.0,
    ) -> ProjectDocument:
        element = next(
            (item for item in project.elements if item.identifier == element_id),
            None,
        )
        if element is None:
            raise KeyError(f"未知梁单元：{element_id}")
        xi = float(local_coordinate)
        if not 0.0 <= xi <= 1.0:
            raise ValueError("测点局部坐标必须位于 [0, 1]。")
        side = str(surface_side).strip().lower()
        if side not in {"top", "bottom"}:
            raise ValueError("测点表面必须是 top 或 bottom。")
        surface_angle = (
            0.0 if side == "top" else 180.0
        ) if surface_angle_degrees is None else float(surface_angle_degrees)
        bound_a = max(0.0, xi - 0.15)
        bound_b = min(1.0, xi + 0.15)
        length = PathBeamEditor.element_length(project, element)
        label = PathBeamEditor._next_sensor_label(project)
        attachment = SensorAttachment(
            entity_id=element.identifier,
            local_coordinates=(xi,),
            surface_side=side,
            gauge_length=(bound_b - bound_a) * length,
            integration_bounds=(bound_a, bound_b),
            surface_angle_degrees=surface_angle,
            orientation_angle_degrees=orientation_angle_degrees,
        )
        provisional = SensorDefinition(
            identifier=new_entity_id("sensor"),
            label=label,
            measurement_type="surface_axial_strain",
            attachment=attachment,
            measured_value=0.0,
            weight=1.0,
        )
        direction = PathBeamEditor.sensor_direction_from_angles(
            replace(project, sensors=project.sensors + (provisional,)),
            provisional,
        )
        sensor = replace(
            provisional,
            attachment=replace(provisional.attachment, direction=direction),
        )
        return project.revised(sensors=project.sensors + (sensor,))

    @staticmethod
    def _next_sensor_label(
        project: ProjectDocument,
        reserved: set[str] | None = None,
    ) -> str:
        labels = {sensor.label for sensor in project.sensors}
        labels.update(reserved or ())
        sequence = 1
        while f"M{sequence}" in labels:
            sequence += 1
        return f"M{sequence}"

    @staticmethod
    def _relocated_attachment(
        project: ProjectDocument,
        sensor: SensorDefinition,
        element: BeamElement,
        local_coordinate: float,
        surface_angle_degrees: float,
    ) -> SensorAttachment:
        xi = float(local_coordinate)
        if not 0.0 <= xi <= 1.0:
            raise ValueError("测点局部坐标必须位于 [0, 1]。")
        angle = float(surface_angle_degrees) % 360.0
        source_length = PathBeamEditor.element_length(
            project,
            sensor.attachment.entity_id,
        )
        target_length = PathBeamEditor.element_length(project, element)
        source_a, source_b = sensor.attachment.integration_bounds
        source_xi = sensor.attachment.local_coordinates[0]
        source_span = max((source_b - source_a) * source_length, 0.0)
        if source_a <= source_xi <= source_b and source_span > _GEOMETRY_TOLERANCE:
            left_fraction = (source_xi - source_a) / (source_b - source_a)
        else:
            left_fraction = 0.5
        left_length = source_span * left_fraction
        right_length = source_span - left_length
        bound_a = max(0.0, xi - left_length / target_length)
        bound_b = min(1.0, xi + right_length / target_length)
        if bound_b - bound_a <= 1.0e-9:
            half_span = min(0.15, max(1.0e-6, source_span / target_length * 0.5))
            bound_a = max(0.0, xi - half_span)
            bound_b = min(1.0, xi + half_span)
        side = "top" if angle < 90.0 or angle >= 270.0 else "bottom"
        return replace(
            sensor.attachment,
            entity_id=element.identifier,
            local_coordinates=(xi,),
            surface_side=side,
            gauge_length=(bound_b - bound_a) * target_length,
            integration_bounds=(bound_a, bound_b),
            surface_angle_degrees=angle,
        )

    @staticmethod
    def _sensor_with_resolved_direction(
        project: ProjectDocument,
        sensor: SensorDefinition,
    ) -> SensorDefinition:
        direction = PathBeamEditor.sensor_direction_from_angles(
            replace(project, sensors=(sensor,)),
            sensor,
        )
        return replace(sensor, attachment=replace(sensor.attachment, direction=direction))

    @staticmethod
    def move_sensor_to_surface(
        project: ProjectDocument,
        sensor_id: str,
        location: BeamSurfaceLocation,
    ) -> ProjectDocument:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        if not isinstance(location, BeamSurfaceLocation):
            raise TypeError("三维表面定位信息无效。")
        element = PathBeamEditor._resolve_element(project, location.element_id)
        attachment = PathBeamEditor._relocated_attachment(
            project,
            sensor,
            element,
            location.local_coordinate,
            location.surface_angle_degrees,
        )
        moved = PathBeamEditor._sensor_with_resolved_direction(
            project,
            replace(sensor, attachment=attachment),
        )
        sensors = tuple(
            moved if item.identifier == sensor.identifier else item
            for item in project.sensors
        )
        return project.revised(sensors=sensors)

    @staticmethod
    def duplicate_sensor(project: ProjectDocument, sensor_id: str) -> ProjectDocument:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        duplicate = replace(
            sensor,
            identifier=new_entity_id("sensor"),
            label=PathBeamEditor._next_sensor_label(project),
            measured_value=0.0,
            channel_id=None,
        )
        return project.revised(sensors=project.sensors + (duplicate,))

    @staticmethod
    def add_opposite_sensor(project: ProjectDocument, sensor_id: str) -> ProjectDocument:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        element = PathBeamEditor._resolve_element(project, sensor.attachment.entity_id)
        attachment = PathBeamEditor._relocated_attachment(
            project,
            sensor,
            element,
            sensor.attachment.local_coordinates[0],
            sensor.attachment.surface_angle_degrees + 180.0,
        )
        opposite = replace(
            sensor,
            identifier=new_entity_id("sensor"),
            label=PathBeamEditor._next_sensor_label(project),
            attachment=attachment,
            measured_value=0.0,
            channel_id=None,
        )
        opposite = PathBeamEditor._sensor_with_resolved_direction(project, opposite)
        return project.revised(sensors=project.sensors + (opposite,))

    @staticmethod
    def array_sensor(
        project: ProjectDocument,
        sensor_id: str,
        *,
        count: int,
        spacing: float,
        direction: int = 1,
    ) -> ProjectDocument:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        count = int(count)
        spacing = float(spacing)
        direction = int(direction)
        if count < 1 or count > 500:
            raise ValueError("阵列新增数量必须位于 [1, 500]。")
        if not isfinite(spacing) or spacing <= 0.0:
            raise ValueError("阵列间距必须大于 0。")
        if direction not in {-1, 1}:
            raise ValueError("阵列方向必须朝路径起点或末端。")

        source = PathBeamEditor.sensor_location(project, sensor_id)
        targets = tuple(
            source.path_distance + direction * spacing * index
            for index in range(1, count + 1)
        )
        total = PathBeamEditor.total_length(project)
        if min(targets) < -1.0e-10 or max(targets) > total + 1.0e-10:
            available = source.path_distance if direction < 0 else total - source.path_distance
            raise ValueError(
                f"阵列超出梁路径；当前方向最多可用 {available:.8g} m。"
            )

        labels: set[str] = set()
        additions = []
        for target in targets:
            _index, element, xi = PathBeamEditor.element_at_path_distance(project, target)
            attachment = PathBeamEditor._relocated_attachment(
                project,
                sensor,
                element,
                xi,
                sensor.attachment.surface_angle_degrees,
            )
            label = PathBeamEditor._next_sensor_label(project, labels)
            labels.add(label)
            clone = replace(
                sensor,
                identifier=new_entity_id("sensor"),
                label=label,
                attachment=attachment,
                measured_value=0.0,
                channel_id=None,
            )
            additions.append(PathBeamEditor._sensor_with_resolved_direction(project, clone))
        return project.revised(sensors=project.sensors + tuple(additions))

    @staticmethod
    def update_sensor(
        project: ProjectDocument,
        sensor_id: str,
        *,
        element_id: str,
        local_coordinate: float,
        surface_side: str,
        direction,
        measured_value: float,
        weight: float,
        zone_a: float,
        zone_b: float,
        label: str | None = None,
        surface_angle_degrees: float | None = None,
        orientation_angle_degrees: float | None = None,
    ) -> ProjectDocument:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        element = next(
            (item for item in project.elements if item.identifier == element_id),
            None,
        )
        if element is None:
            raise KeyError(f"未知梁单元：{element_id}")
        xi = float(local_coordinate)
        bound_a = float(zone_a)
        bound_b = float(zone_b)
        if not 0.0 <= xi <= 1.0:
            raise ValueError("测点局部坐标必须位于 [0, 1]。")
        if bound_a < 0.0 or bound_b > 1.0 or bound_b <= bound_a:
            raise ValueError("测点积分区间必须满足 0 <= a < b <= 1。")
        side = str(surface_side).strip().lower()
        if side not in {"top", "bottom"}:
            raise ValueError("测点表面必须是 top 或 bottom。")
        if surface_angle_degrees is None:
            surface_angle = sensor.attachment.surface_angle_degrees
            if side != sensor.attachment.surface_side:
                surface_angle = 0.0 if side == "top" else 180.0
        else:
            surface_angle = float(surface_angle_degrees)
        orientation_angle = (
            sensor.attachment.orientation_angle_degrees
            if orientation_angle_degrees is None
            else float(orientation_angle_degrees)
        )
        length = PathBeamEditor.element_length(project, element)
        attachment = SensorAttachment(
            entity_id=element.identifier,
            local_coordinates=(xi,),
            surface_side=side,
            direction=tuple(float(value) for value in direction),
            gauge_length=(bound_b - bound_a) * length,
            integration_bounds=(bound_a, bound_b),
            surface_angle_degrees=surface_angle,
            orientation_angle_degrees=orientation_angle,
        )
        provisional = replace(
            sensor,
            label=(label or sensor.label).strip(),
            attachment=attachment,
            measured_value=float(measured_value),
            weight=float(weight),
        )
        if surface_angle_degrees is not None or orientation_angle_degrees is not None:
            direction = PathBeamEditor.sensor_direction_from_angles(
                replace(project, sensors=(provisional,)),
                provisional,
            )
            provisional = replace(
                provisional,
                attachment=replace(provisional.attachment, direction=direction),
            )
        updated = provisional
        sensors = tuple(updated if item.identifier == sensor_id else item for item in project.sensors)
        return project.revised(sensors=sensors)

    @staticmethod
    def delete_sensor(project: ProjectDocument, sensor_id: str) -> ProjectDocument:
        sensors = tuple(sensor for sensor in project.sensors if sensor.identifier != sensor_id)
        if len(sensors) == len(project.sensors):
            raise KeyError(f"未知测点：{sensor_id}")
        return project.revised(sensors=sensors)

    @staticmethod
    def update_element(
        project: ProjectDocument,
        element_id: str,
        *,
        family: str,
        section_id: str | None,
        material_id: str | None,
    ) -> ProjectDocument:
        if not any(element.identifier == element_id for element in project.elements):
            raise KeyError(f"未知梁单元：{element_id}")
        elements = tuple(
            replace(
                element,
                family=str(family),
                section_id=section_id,
                material_id=material_id,
            )
            if element.identifier == element_id
            else element
            for element in project.elements
        )
        return project.revised(elements=elements)

    @staticmethod
    def update_primary_properties(
        project: ProjectDocument,
        *,
        thickness: float,
        width: float | None,
        elastic_modulus: float | None,
        section_shape: str | None = None,
        section_parameters: Mapping[str, float] | None = None,
    ) -> ProjectDocument:
        thickness = float(thickness)
        width = None if width in {None, ""} else float(width)
        elastic_modulus = (
            None if elastic_modulus in {None, ""} else float(elastic_modulus)
        )
        current_section = project.sections[0] if project.sections else None
        shape = (
            str(section_shape).strip().lower()
            if section_shape is not None
            else current_section.shape if current_section is not None else "rectangle"
        )
        if section_parameters is None:
            parameters = (
                dict(current_section.parameters)
                if current_section is not None and current_section.shape == shape
                else {}
            )
            if shape == "rectangle":
                parameters.update({"height": thickness, "width": width or thickness})
            elif shape == "circle":
                parameters["diameter"] = thickness
            elif shape == "circular_tube":
                parameters["outer_diameter"] = thickness
            elif shape == "box":
                parameters.update(
                    {"outer_height": thickness, "outer_width": width or thickness}
                )
            elif shape == "i_section":
                parameters.update(
                    {"height": thickness, "flange_width": width or thickness}
                )
        else:
            parameters = {
                str(key): float(value) for key, value in section_parameters.items()
            }
        section_id = (
            current_section.identifier
            if current_section is not None
            else new_entity_id("section")
        )
        section_name = (
            current_section.name if current_section is not None else "统一截面"
        )
        primary_section = SectionDefinition(
            section_id,
            section_name,
            thickness,
            width,
            shape,
            parameters,
        )
        if project.sections:
            sections = (primary_section,) + project.sections[1:]
        else:
            sections = (primary_section,)
        if project.materials:
            materials = (
                replace(project.materials[0], elastic_modulus=elastic_modulus),
            ) + project.materials[1:]
        else:
            materials = (
                MaterialDefinition(new_entity_id("material"), "默认材料", elastic_modulus),
            )
        section_id = primary_section.identifier
        material_id = materials[0].identifier
        elements = tuple(
            replace(
                element,
                section_id=section_id,
                material_id=element.material_id or material_id,
            )
            for element in project.elements
        )
        updated = project.revised(
            sections=sections,
            materials=materials,
            elements=elements,
        )
        sensors = tuple(
            replace(
                sensor,
                attachment=replace(
                    sensor.attachment,
                    direction=PathBeamEditor.sensor_direction_from_angles(
                        updated,
                        sensor,
                    ),
                ),
            )
            for sensor in updated.sensors
        )
        return replace(updated, sensors=sensors)

    @staticmethod
    def create_polyline(
        project: ProjectDocument,
        coordinates,
        *,
        family: str | None = None,
    ) -> ProjectDocument:
        points = tuple(tuple(float(value) for value in point) for point in coordinates)
        if len(points) < 2:
            raise ValueError("梁路径至少需要两个节点。")
        if any(len(point) != 3 or not all(isfinite(value) for value in point) for point in points):
            raise ValueError("每个节点都必须包含三个有限坐标。")
        if any(_distance(left, right) <= _GEOMETRY_TOLERANCE for left, right in zip(points, points[1:])):
            raise ValueError("相邻节点不能重合。")
        if (
            project.modeling_space == "2d"
            and (
                any(abs(point[2]) > _GEOMETRY_TOLERANCE for point in points)
                or (family is not None and str(family).startswith("beam3d"))
            )
        ):
            project = PathBeamEditor.set_modeling_space(project, "3d")
        family = family or PathBeamEditor._family_for_geometry(
            project.modeling_space,
            "line",
        )
        nodes = tuple(StructuralNode(new_entity_id("node"), point) for point in points)
        blank = project.revised(
            nodes=nodes,
            elements=(),
            sensors=(),
            boundary_conditions=(),
        )
        elements = tuple(
            PathBeamEditor._new_element(
                blank,
                (left.identifier, right.identifier),
                family=family,
            )
            for left, right in zip(nodes, nodes[1:])
        )
        return replace(blank, elements=elements)

    @staticmethod
    def create_straight_beam(
        project: ProjectDocument,
        *,
        length: float,
        element_count: int,
        axis: str = "x",
    ) -> ProjectDocument:
        length = float(length)
        element_count = int(element_count)
        axis = str(axis).strip().lower()
        if length <= 0.0 or element_count < 1:
            raise ValueError("梁长必须大于 0，单元数至少为 1。")
        if axis not in {"x", "+x", "-x", "y", "+y", "-y", "z", "+z", "-z"}:
            raise ValueError("直梁方向必须是全局 ±X、±Y 或 ±Z。")
        sign = -1.0 if axis.startswith("-") else 1.0
        axis_name = axis[-1]
        axis_index = {"x": 0, "y": 1, "z": 2}[axis_name]
        points = []
        for index in range(element_count + 1):
            point = [0.0, 0.0, 0.0]
            point[axis_index] = sign * length * index / element_count
            points.append(tuple(point))
        return PathBeamEditor.create_polyline(project, points)

    @staticmethod
    def create_circular_arc(
        project: ProjectDocument,
        *,
        radius: float,
        sweep_degrees: float,
        plane: str = "xy",
    ) -> ProjectDocument:
        radius = float(radius)
        sweep_degrees = float(sweep_degrees)
        plane = str(plane).lower()
        if project.modeling_space == "2d" and plane != "xy":
            project = PathBeamEditor.set_modeling_space(project, "3d")
        geometry, start, end = PathBeamEditor._circular_arc_geometry(
            radius=radius,
            sweep_degrees=sweep_degrees,
            plane=plane,
            start=(0.0, 0.0, 0.0),
        )
        nodes = (
            StructuralNode(new_entity_id("node"), start),
            StructuralNode(new_entity_id("node"), end),
        )
        blank = project.revised(
            nodes=nodes,
            elements=(),
            sensors=(),
            boundary_conditions=(),
        )
        element = PathBeamEditor._new_element(
            blank,
            (nodes[0].identifier, nodes[1].identifier),
            family=PathBeamEditor._family_for_geometry(
                project.modeling_space,
                "circular_arc",
            ),
            geometry=geometry,
        )
        return replace(blank, elements=(element,))

    @staticmethod
    def _circular_arc_geometry(
        *,
        radius: float,
        sweep_degrees: float,
        plane: str,
        start,
    ) -> tuple[BeamGeometryDefinition, tuple[float, float, float], tuple[float, float, float]]:
        radius = float(radius)
        sweep_degrees = float(sweep_degrees)
        plane = str(plane).lower()
        start = tuple(float(value) for value in start)
        basis = {
            "xy": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            "xz": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "yz": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        }
        if plane not in basis:
            raise ValueError("圆弧平面必须是 XY、XZ 或 YZ。")
        _tangent_axis, radial_axis = basis[plane]
        center = tuple(
            coordinate + radius * axis_value
            for coordinate, axis_value in zip(start, radial_axis)
        )
        start_vector = tuple(-radius * axis_value for axis_value in radial_axis)
        normal = _cross(basis[plane][0], radial_axis)
        geometry = BeamGeometryDefinition(
            kind="circular_arc",
            parameters={
                "radius": radius,
                "sweep_degrees": sweep_degrees,
                "plane": plane,
                "center": center,
                "normal": normal,
                "start_vector": start_vector,
            },
        )
        rotated = _rotate_about_axis(
            start_vector,
            normal,
            radians(sweep_degrees),
        )
        end = tuple(center_value + offset for center_value, offset in zip(center, rotated))
        return geometry, start, end

    @staticmethod
    def update_circular_arc(
        project: ProjectDocument,
        element_id: str,
        *,
        radius: float,
        sweep_degrees: float,
        plane: str,
    ) -> ProjectDocument:
        if project.modeling_space == "2d" and str(plane).lower() != "xy":
            project = PathBeamEditor.set_modeling_space(project, "3d")
        element = PathBeamEditor._resolve_element(project, element_id)
        if element.geometry.kind != "circular_arc":
            raise ValueError("所选梁单元不是参数化圆弧。")
        node_a, node_b = PathBeamEditor.element_nodes(project, element)
        has_connected_entry = any(
            candidate.identifier != element_id
            and node_a.identifier in candidate.node_ids
            for candidate in project.elements
        )
        if has_connected_entry:
            start_tangent = PathBeamEditor.tangent_on_element(project, element, 0.0)
            geometry, end = PathBeamEditor._oriented_circular_arc_geometry(
                start=node_a.coordinates,
                tangent=start_tangent,
                radius=radius,
                sweep_degrees=sweep_degrees,
                plane=plane,
            )
        else:
            geometry, _start, end = PathBeamEditor._circular_arc_geometry(
                radius=radius,
                sweep_degrees=sweep_degrees,
                plane=plane,
                start=node_a.coordinates,
            )
        updated_element = replace(
            element,
            geometry=geometry,
            family=PathBeamEditor._family_for_geometry(
                project.modeling_space,
                "circular_arc",
            ),
        )

        # Removing the edited arc splits the open path into two components. Move
        # the component attached to the arc end so every downstream entity stays
        # geometrically connected while retaining its own shape and orientation.
        adjacency: dict[str, set[str]] = {
            node.identifier: set() for node in project.nodes
        }
        for candidate in project.elements:
            if candidate.identifier == element_id:
                continue
            left_id, right_id = candidate.node_ids
            adjacency[left_id].add(right_id)
            adjacency[right_id].add(left_id)
        moved_node_ids = set()
        pending = [node_b.identifier]
        while pending:
            node_id = pending.pop()
            if node_id in moved_node_ids:
                continue
            moved_node_ids.add(node_id)
            pending.extend(adjacency[node_id] - moved_node_ids)

        translation = tuple(
            new_value - old_value
            for new_value, old_value in zip(end, node_b.coordinates)
        )
        nodes = tuple(
            replace(
                node,
                coordinates=tuple(
                    value + offset
                    for value, offset in zip(node.coordinates, translation)
                ),
            )
            if node.identifier in moved_node_ids
            else node
            for node in project.nodes
        )
        elements = []
        for candidate in project.elements:
            if candidate.identifier == element_id:
                elements.append(updated_element)
                continue
            if (
                candidate.geometry.kind == "circular_arc"
                and set(candidate.node_ids).issubset(moved_node_ids)
            ):
                parameters = dict(candidate.geometry.parameters)
                parameters["center"] = tuple(
                    value + offset
                    for value, offset in zip(parameters["center"], translation)
                )
                candidate = replace(
                    candidate,
                    geometry=BeamGeometryDefinition(
                        kind="circular_arc",
                        parameters=parameters,
                    ),
                )
            elements.append(candidate)
        intermediate = project.revised(
            nodes=nodes,
            elements=tuple(elements),
        )
        length = PathBeamEditor.element_length(intermediate, updated_element)
        provisional_sensors = []
        for sensor in intermediate.sensors:
            if sensor.attachment.entity_id != element_id:
                provisional_sensors.append(sensor)
                continue
            bounds = sensor.attachment.integration_bounds
            attachment = replace(
                sensor.attachment,
                gauge_length=(bounds[1] - bounds[0]) * length,
            )
            provisional_sensors.append(replace(sensor, attachment=attachment))
        intermediate = replace(intermediate, sensors=tuple(provisional_sensors))
        sensors = tuple(
            replace(
                sensor,
                attachment=replace(
                    sensor.attachment,
                    direction=PathBeamEditor.sensor_direction_from_angles(
                        intermediate,
                        sensor,
                    ),
                ),
            )
            for sensor in intermediate.sensors
        )
        return replace(intermediate, sensors=sensors)

    @staticmethod
    def capability(project: ProjectDocument) -> GeometryCapability:
        _nodes, elements = PathBeamEditor.ordered_path(project)
        points = list(PathBeamEditor.sample_project(project))
        total_length = PathBeamEditor.total_length(project)
        modeling_space = project.modeling_space
        dimension = 2 if modeling_space == "2d" else 3
        geometry_kinds = tuple(sorted({element.geometry.kind for element in elements}))
        has_curves = any(kind != "line" for kind in geometry_kinds)
        mixed_geometry = len(geometry_kinds) > 1
        x_values = [point[0] for point in points]
        on_x_axis = all(
            abs(point[1]) <= _GEOMETRY_TOLERANCE
            and abs(point[2]) <= _GEOMETRY_TOLERANCE
            for point in points
        )
        increasing_x = all(right > left for left, right in zip(x_values, x_values[1:]))
        geometry_compatible = not has_curves and on_x_axis and increasing_x
        sensor_configuration_compatible = all(
            min(
                abs(sensor.attachment.surface_angle_degrees),
                abs(sensor.attachment.surface_angle_degrees - 180.0),
                abs(sensor.attachment.surface_angle_degrees - 360.0),
            )
            <= 1.0e-8
            and abs(
                (sensor.attachment.orientation_angle_degrees + 90.0) % 180.0
                - 90.0
            )
            <= 1.0e-8
            and abs(abs(sensor.attachment.direction[0]) - 1.0) <= 1.0e-8
            and abs(sensor.attachment.direction[1]) <= 1.0e-8
            and abs(sensor.attachment.direction[2]) <= 1.0e-8
            for sensor in project.sensors
        )
        compatible = (
            modeling_space == "2d"
            and geometry_compatible
            and sensor_configuration_compatible
        )

        vectors = [
            tuple(right[axis] - left[axis] for axis in range(3))
            for left, right in zip(points, points[1:])
        ]
        first = vectors[0]
        collinear = all(
            sqrt(
                (first[1] * vector[2] - first[2] * vector[1]) ** 2
                + (first[2] * vector[0] - first[0] * vector[2]) ** 2
                + (first[0] * vector[1] - first[1] * vector[0]) ** 2
            )
            <= _GEOMETRY_TOLERANCE * max(_distance((0.0, 0.0, 0.0), first), 1.0)
            for vector in vectors[1:]
        )
        if modeling_space == "2d" and geometry_compatible:
            kind = "二维直梁"
            reason = (
                "可直接使用当前二维直梁算法"
                if sensor_configuration_compatible
                else "当前算法仅接受上下表面的轴向应变测点"
            )
        else:
            if modeling_space == "2d":
                if mixed_geometry:
                    kind = "二维直线/圆弧组合梁"
                elif has_curves:
                    kind = "二维圆弧梁" if len(elements) == 1 else "二维曲梁"
                elif collinear:
                    kind = "二维直梁"
                else:
                    kind = "二维折线梁"
                reason = (
                    "等待二维曲梁算法插件"
                    if has_curves
                    else "当前算法仅接受全局 X 轴直梁"
                )
            else:
                if mixed_geometry:
                    kind = "三维直线/圆弧组合梁"
                elif has_curves:
                    kind = "三维曲梁"
                elif collinear:
                    kind = "三维直梁"
                else:
                    kind = "三维折线梁"
                reason = "等待三维梁算法插件"
        return GeometryCapability(
            kind,
            dimension,
            total_length,
            compatible,
            reason,
            modeling_space,
            geometry_kinds,
            mixed_geometry,
        )
