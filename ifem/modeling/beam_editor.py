from __future__ import annotations

from dataclasses import dataclass, replace
from math import isclose

from ifem.domain.project import (
    BeamElement,
    BoundaryCondition,
    ProjectDocument,
    SensorAttachment,
    SensorDefinition,
    StructuralNode,
    new_entity_id,
)


@dataclass(frozen=True)
class SensorLocation:
    global_x: float
    element_index: int
    local_x: float
    element_length: float
    zone_a: float
    zone_b: float


class BeamProjectEditor:
    @staticmethod
    def ordered_nodes(project: ProjectDocument) -> tuple[StructuralNode, ...]:
        nodes = tuple(sorted(project.nodes, key=lambda node: node.coordinates[0]))
        if len(nodes) < 2:
            raise ValueError("二维梁至少需要两个节点。")
        x_values = [node.coordinates[0] for node in nodes]
        if any(right <= left for left, right in zip(x_values, x_values[1:])):
            raise ValueError("二维梁节点 x 坐标必须严格递增。")
        return nodes

    @staticmethod
    def ordered_elements(project: ProjectDocument) -> tuple[BeamElement, ...]:
        nodes = BeamProjectEditor.ordered_nodes(project)
        by_pair = {frozenset(element.node_ids): element for element in project.elements}
        elements = []
        for left, right in zip(nodes, nodes[1:]):
            element = by_pair.get(frozenset((left.identifier, right.identifier)))
            if element is None:
                raise ValueError("梁单元没有依次连接相邻节点。")
            elements.append(element)
        if len(elements) != len(project.elements):
            raise ValueError("交互直梁建模暂不支持分支单元。")
        return tuple(elements)

    @staticmethod
    def node_x(project: ProjectDocument, node_id: str) -> float:
        for node in project.nodes:
            if node.identifier == node_id:
                return float(node.coordinates[0])
        raise KeyError(f"未知节点：{node_id}")

    @staticmethod
    def _element_nodes(project: ProjectDocument, element: BeamElement):
        node_by_id = {node.identifier: node for node in project.nodes}
        return node_by_id[element.node_ids[0]], node_by_id[element.node_ids[1]]

    @staticmethod
    def sensor_location(project: ProjectDocument, sensor_id: str) -> SensorLocation:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        elements = BeamProjectEditor.ordered_elements(project)
        element = next(
            item for item in elements if item.identifier == sensor.attachment.entity_id
        )
        index = elements.index(element)
        node_a, node_b = BeamProjectEditor._element_nodes(project, element)
        x_a = float(node_a.coordinates[0])
        x_b = float(node_b.coordinates[0])
        xi = sensor.attachment.local_coordinates[0]
        bound_a, bound_b = sensor.attachment.integration_bounds
        global_x = x_a + xi * (x_b - x_a)
        zone_x_a = x_a + bound_a * (x_b - x_a)
        zone_x_b = x_a + bound_b * (x_b - x_a)
        left = min(x_a, x_b)
        return SensorLocation(
            global_x=float(global_x),
            element_index=index,
            local_x=float(global_x - left),
            element_length=abs(x_b - x_a),
            zone_a=float(min(zone_x_a, zone_x_b) - left),
            zone_b=float(max(zone_x_a, zone_x_b) - left),
        )

    @staticmethod
    def _find_element(project: ProjectDocument, global_x: float):
        nodes = BeamProjectEditor.ordered_nodes(project)
        elements = BeamProjectEditor.ordered_elements(project)
        x = float(global_x)
        if x < nodes[0].coordinates[0] or x > nodes[-1].coordinates[0]:
            raise ValueError("测点位置超出梁范围。")
        for index, (left, right) in enumerate(zip(nodes, nodes[1:])):
            if x <= right.coordinates[0] or index == len(elements) - 1:
                element = elements[index]
                length = right.coordinates[0] - left.coordinates[0]
                xi_from_left = (x - left.coordinates[0]) / length
                if element.node_ids == (left.identifier, right.identifier):
                    xi = xi_from_left
                else:
                    xi = 1.0 - xi_from_left
                return index, element, float(xi), float(length)
        raise ValueError("无法确定测点所在梁单元。")

    @staticmethod
    def _build_elements(project: ProjectDocument, nodes):
        existing = {frozenset(element.node_ids): element for element in project.elements}
        template = project.elements[0] if project.elements else None
        section_id = template.section_id if template is not None else (
            project.sections[0].identifier if project.sections else None
        )
        material_id = template.material_id if template is not None else (
            project.materials[0].identifier if project.materials else None
        )
        elements = []
        for left, right in zip(nodes, nodes[1:]):
            pair = frozenset((left.identifier, right.identifier))
            element = existing.get(pair)
            if element is None:
                element = BeamElement(
                    identifier=new_entity_id("element"),
                    node_ids=(left.identifier, right.identifier),
                    section_id=section_id,
                    material_id=material_id,
                )
            elif element.node_ids != (left.identifier, right.identifier):
                element = replace(element, node_ids=(left.identifier, right.identifier))
            elements.append(element)
        return tuple(elements)

    @staticmethod
    def _sensor_global_span(project: ProjectDocument, sensor: SensorDefinition):
        location = BeamProjectEditor.sensor_location(project, sensor.identifier)
        nodes = BeamProjectEditor.ordered_nodes(project)
        left_x = nodes[location.element_index].coordinates[0]
        return (
            location.global_x,
            left_x + location.zone_a,
            left_x + location.zone_b,
        )

    @staticmethod
    def _reattach_sensor(
        project: ProjectDocument,
        sensor: SensorDefinition,
        global_x: float,
        zone_start: float,
        zone_end: float,
    ) -> SensorDefinition:
        index, element, xi, length = BeamProjectEditor._find_element(project, global_x)
        nodes = BeamProjectEditor.ordered_nodes(project)
        left_x = nodes[index].coordinates[0]
        element_end = left_x + length
        clipped_start = min(max(zone_start, left_x), element_end)
        clipped_end = min(max(zone_end, left_x), element_end)
        if clipped_end - clipped_start <= max(length * 1.0e-9, 1.0e-12):
            half = max(0.05 * length, 1.0e-9)
            clipped_start = max(left_x, global_x - half)
            clipped_end = min(element_end, global_x + half)
        bounds_from_left = (
            (clipped_start - left_x) / length,
            (clipped_end - left_x) / length,
        )
        if element.node_ids[0] != nodes[index].identifier:
            xi = 1.0 - xi
            bounds = (1.0 - bounds_from_left[1], 1.0 - bounds_from_left[0])
        else:
            bounds = bounds_from_left
        attachment = replace(
            sensor.attachment,
            entity_id=element.identifier,
            local_coordinates=(xi,),
            gauge_length=clipped_end - clipped_start,
            integration_bounds=bounds,
        )
        return replace(sensor, attachment=attachment)

    @staticmethod
    def _rebuild_topology(
        project: ProjectDocument,
        nodes,
        sensor_spans,
        *,
        boundaries=None,
    ) -> ProjectDocument:
        nodes = tuple(sorted(nodes, key=lambda node: node.coordinates[0]))
        elements = BeamProjectEditor._build_elements(project, nodes)
        intermediate = project.revised(
            nodes=nodes,
            elements=elements,
            sensors=(),
            boundary_conditions=(
                project.boundary_conditions if boundaries is None else tuple(boundaries)
            ),
        )
        sensors = tuple(
            BeamProjectEditor._reattach_sensor(intermediate, sensor, *span)
            for sensor, span in sensor_spans
            if nodes[0].coordinates[0] <= span[0] <= nodes[-1].coordinates[0]
        )
        return replace(intermediate, sensors=sensors)

    @staticmethod
    def create_uniform_beam(
        project: ProjectDocument,
        *,
        length: float,
        element_count: int,
        start_x: float = 0.0,
    ) -> ProjectDocument:
        length = float(length)
        element_count = int(element_count)
        start_x = float(start_x)
        if length <= 0.0 or element_count < 1:
            raise ValueError("梁长必须大于 0，单元数至少为 1。")

        old_nodes = BeamProjectEditor.ordered_nodes(project)
        old_start = old_nodes[0].coordinates[0]
        old_length = old_nodes[-1].coordinates[0] - old_start
        nodes = tuple(
            StructuralNode(
                new_entity_id("node"),
                (start_x + length * index / element_count, 0.0, 0.0),
            )
            for index in range(element_count + 1)
        )
        blank = project.revised(nodes=nodes, elements=(), sensors=(), boundary_conditions=())
        elements = BeamProjectEditor._build_elements(blank, nodes)

        boundaries = []
        seen = set()
        for boundary in project.boundary_conditions:
            old_x = BeamProjectEditor.node_x(project, boundary.node_id)
            ratio = 0.0 if old_length <= 0.0 else (old_x - old_start) / old_length
            new_index = min(element_count, max(0, round(ratio * element_count)))
            key = (nodes[new_index].identifier, boundary.dof)
            if key in seen:
                continue
            seen.add(key)
            boundaries.append(replace(boundary, node_id=nodes[new_index].identifier))
        return replace(blank, elements=elements, boundary_conditions=tuple(boundaries))

    @staticmethod
    def add_node(project: ProjectDocument, global_x: float) -> ProjectDocument:
        x = float(global_x)
        nodes = BeamProjectEditor.ordered_nodes(project)
        if any(isclose(x, node.coordinates[0], rel_tol=0.0, abs_tol=1.0e-9) for node in nodes):
            raise ValueError("该位置已经存在节点。")
        if x <= nodes[0].coordinates[0] or x >= nodes[-1].coordinates[0]:
            raise ValueError("新增节点必须位于当前梁范围内部。")
        sensor_spans = [
            (sensor, BeamProjectEditor._sensor_global_span(project, sensor))
            for sensor in project.sensors
        ]
        new_node = StructuralNode(new_entity_id("node"), (x, 0.0, 0.0))
        return BeamProjectEditor._rebuild_topology(
            project,
            nodes + (new_node,),
            sensor_spans,
        )

    @staticmethod
    def move_node(project: ProjectDocument, node_id: str, global_x: float) -> ProjectDocument:
        nodes = list(BeamProjectEditor.ordered_nodes(project))
        index = next(
            (position for position, node in enumerate(nodes) if node.identifier == node_id),
            None,
        )
        if index is None:
            raise KeyError(f"未知节点：{node_id}")
        x = float(global_x)
        if index > 0 and x <= nodes[index - 1].coordinates[0]:
            raise ValueError("节点不能越过左侧相邻节点。")
        if index + 1 < len(nodes) and x >= nodes[index + 1].coordinates[0]:
            raise ValueError("节点不能越过右侧相邻节点。")
        nodes[index] = replace(nodes[index], coordinates=(x, 0.0, 0.0))
        return project.revised(nodes=tuple(nodes))

    @staticmethod
    def delete_node(project: ProjectDocument, node_id: str) -> ProjectDocument:
        nodes = BeamProjectEditor.ordered_nodes(project)
        if len(nodes) <= 2:
            raise ValueError("二维梁至少保留两个节点。")
        if node_id not in {node.identifier for node in nodes}:
            raise KeyError(f"未知节点：{node_id}")
        sensor_spans = [
            (sensor, BeamProjectEditor._sensor_global_span(project, sensor))
            for sensor in project.sensors
        ]
        remaining_nodes = tuple(node for node in nodes if node.identifier != node_id)
        boundaries = tuple(
            boundary
            for boundary in project.boundary_conditions
            if boundary.node_id != node_id
        )
        return BeamProjectEditor._rebuild_topology(
            project,
            remaining_nodes,
            sensor_spans,
            boundaries=boundaries,
        )

    @staticmethod
    def add_sensor(
        project: ProjectDocument,
        global_x: float,
        surface_side: str,
    ) -> ProjectDocument:
        index, element, xi, length = BeamProjectEditor._find_element(project, global_x)
        side = surface_side.strip().lower()
        if side not in {"top", "bottom"}:
            raise ValueError("测点表面必须是 top 或 bottom。")
        nodes = BeamProjectEditor.ordered_nodes(project)
        left_x = nodes[index].coordinates[0]
        xi_from_left = (float(global_x) - left_x) / length
        zone_from_left = (
            max(0.0, xi_from_left - 0.15),
            min(1.0, xi_from_left + 0.15),
        )
        if element.node_ids[0] != nodes[index].identifier:
            bounds = (1.0 - zone_from_left[1], 1.0 - zone_from_left[0])
        else:
            bounds = zone_from_left
        sequence = len(project.sensors) + 1
        sensor = SensorDefinition(
            identifier=new_entity_id("sensor"),
            label=f"M{sequence}",
            measurement_type="surface_axial_strain",
            attachment=SensorAttachment(
                entity_id=element.identifier,
                local_coordinates=(xi,),
                surface_side=side,
                gauge_length=(zone_from_left[1] - zone_from_left[0]) * length,
                integration_bounds=bounds,
            ),
            measured_value=0.0,
            weight=1.0,
        )
        return project.revised(sensors=project.sensors + (sensor,))

    @staticmethod
    def update_sensor(
        project: ProjectDocument,
        sensor_id: str,
        *,
        global_x: float,
        surface_side: str,
        measured_value: float,
        weight: float,
        zone_a: float,
        zone_b: float,
    ) -> ProjectDocument:
        sensor = next(
            (item for item in project.sensors if item.identifier == sensor_id),
            None,
        )
        if sensor is None:
            raise KeyError(f"未知测点：{sensor_id}")
        side = surface_side.strip().lower()
        if side not in {"top", "bottom"}:
            raise ValueError("测点表面必须是 top 或 bottom。")
        index, _element, _xi, length = BeamProjectEditor._find_element(project, global_x)
        if zone_a < 0.0 or zone_b > length or zone_b <= zone_a:
            raise ValueError(f"测点区间必须满足 0 <= a < b <= {length:.6g}。")
        nodes = BeamProjectEditor.ordered_nodes(project)
        left_x = nodes[index].coordinates[0]
        updated = replace(
            sensor,
            attachment=replace(
                sensor.attachment,
                surface_side=side,
                surface_angle_degrees=0.0 if side == "top" else 180.0,
                orientation_angle_degrees=0.0,
                direction=(1.0, 0.0, 0.0),
            ),
            measured_value=float(measured_value),
            weight=float(weight),
        )
        updated = BeamProjectEditor._reattach_sensor(
            project,
            updated,
            float(global_x),
            left_x + float(zone_a),
            left_x + float(zone_b),
        )
        sensors = tuple(updated if item.identifier == sensor_id else item for item in project.sensors)
        return project.revised(sensors=sensors)

    @staticmethod
    def delete_sensor(project: ProjectDocument, sensor_id: str) -> ProjectDocument:
        sensors = tuple(sensor for sensor in project.sensors if sensor.identifier != sensor_id)
        if len(sensors) == len(project.sensors):
            raise KeyError(f"未知测点：{sensor_id}")
        return project.revised(sensors=sensors)
