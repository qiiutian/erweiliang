from __future__ import annotations

from typing import Any, Mapping

from config_adapter import (
    global_dof_to_pair,
    make_global_dof,
    normalize_config,
    validate_config,
)
from ifem.application.analysis_service import DEFAULT_ALGORITHM_ID
from ifem.domain.project import (
    AnalysisCase,
    BeamElement,
    BoundaryCondition,
    MaterialDefinition,
    ProjectDocument,
    SectionDefinition,
    SensorAttachment,
    SensorDefinition,
    StructuralNode,
    new_entity_id,
)


def _surface_side(measurement: Mapping[str, Any]) -> str:
    surface = str(measurement.get("surface", "")).strip().lower()
    if surface in {"top", "upper", "up", "上", "上表面"}:
        return "top"
    if surface in {"bot", "bottom", "lower", "down", "下", "下表面"}:
        return "bottom"
    return "top" if float(measurement.get("y", 0.0)) > 0.0 else "bottom"


def project_from_legacy_config(
    config: Mapping[str, Any],
    *,
    project_name: str | None = None,
) -> ProjectDocument:
    normalized = normalize_config(config)
    validate_config(normalized, require_measurements=False)
    node_x = normalized["node_x"]
    if len(node_x) < 2 or any(right <= left for left, right in zip(node_x, node_x[1:])):
        raise ValueError("项目转换要求 node_x 至少包含两个严格递增坐标。")

    material = MaterialDefinition(
        identifier=new_entity_id("material"),
        name="线弹性材料",
        elastic_modulus=normalized["material"].get("elastic_modulus"),
    )
    section = SectionDefinition(
        identifier=new_entity_id("section"),
        name="梁截面",
        thickness=normalized["thickness"],
    )
    nodes = tuple(
        StructuralNode(new_entity_id("node"), (float(x), 0.0, 0.0)) for x in node_x
    )
    elements = tuple(
        BeamElement(
            identifier=new_entity_id("element"),
            node_ids=(nodes[index].identifier, nodes[index + 1].identifier),
            section_id=section.identifier,
            material_id=material.identifier,
        )
        for index in range(len(nodes) - 1)
    )

    sensors = []
    sequence = 1
    element_sensor_data = normalized.get("elements_sensor_data", [])
    for element_index, element in enumerate(elements):
        if element_index >= len(element_sensor_data):
            continue
        length = float(node_x[element_index + 1] - node_x[element_index])
        for measurement in element_sensor_data[element_index].get("measurements", []):
            local_x = float(measurement["x"])
            zone_a, zone_b = (float(value) for value in measurement["zone"])
            if not 0.0 <= local_x <= length:
                raise ValueError("测点局部坐标超出梁单元范围。")
            if zone_a < 0.0 or zone_b > length or zone_b <= zone_a:
                raise ValueError("测点积分区间超出梁单元范围。")
            sensors.append(
                SensorDefinition(
                    identifier=new_entity_id("sensor"),
                    label=str(measurement.get("label") or f"M{sequence}"),
                    measurement_type="surface_axial_strain",
                    attachment=SensorAttachment(
                        entity_id=element.identifier,
                        local_coordinates=(local_x / length,),
                        surface_side=_surface_side(measurement),
                        gauge_length=zone_b - zone_a,
                        integration_bounds=(zone_a / length, zone_b / length),
                    ),
                    measured_value=float(measurement.get("strain", 0.0)),
                    weight=float(measurement.get("weight", 1.0)),
                    channel_id=measurement.get("channel_id"),
                )
            )
            sequence += 1

    boundaries = []
    for global_dof, value in normalized.get("prescribed_dofs", {}).items():
        node_index, dof = global_dof_to_pair(global_dof)
        if node_index < 0 or node_index >= len(nodes):
            raise ValueError("边界条件节点超出项目范围。")
        boundaries.append(
            BoundaryCondition(
                identifier=new_entity_id("boundary"),
                node_id=nodes[node_index].identifier,
                dof=dof,
                value=float(value),
            )
        )

    analysis = AnalysisCase(
        identifier=new_entity_id("analysis"),
        name="二维梁重构工况",
        algorithm_id=DEFAULT_ALGORITHM_ID,
        parameters={
            "gauss_n": normalized.get("gauss_n", 3),
            "points_per_element": normalized.get("points_per_element", 120),
            "query_xs": list(normalized.get("query_xs", [])),
            "true_points": list(normalized.get("true_points", [])),
        },
    )
    title = normalized.get("plot_options", {}).get("title", "二维梁重构形态")
    return ProjectDocument(
        identifier=new_entity_id("project"),
        name=project_name or str(title),
        nodes=nodes,
        elements=elements,
        sensors=tuple(sensors),
        boundary_conditions=tuple(boundaries),
        materials=(material,),
        sections=(section,),
        analysis_cases=(analysis,),
        active_analysis_id=analysis.identifier,
        view_state=dict(normalized.get("plot_options", {})),
    )


def _ordered_beam(project: ProjectDocument):
    if any(element.geometry.kind != "line" for element in project.elements):
        raise ValueError("当前二维梁算法不支持参数化曲线几何。")
    nodes = sorted(project.nodes, key=lambda node: node.coordinates[0])
    if len(nodes) < 2:
        raise ValueError("二维梁项目至少需要两个节点。")
    if any(
        abs(node.coordinates[1]) > 1.0e-12 or abs(node.coordinates[2]) > 1.0e-12
        for node in nodes
    ):
        raise ValueError("当前二维梁算法仅支持位于全局 x 轴上的节点。")
    node_x = [node.coordinates[0] for node in nodes]
    if any(right <= left for left, right in zip(node_x, node_x[1:])):
        raise ValueError("二维梁节点 x 坐标必须严格递增。")

    element_by_pair = {
        frozenset(element.node_ids): element for element in project.elements
    }
    ordered_elements = []
    for left, right in zip(nodes, nodes[1:]):
        element = element_by_pair.get(frozenset((left.identifier, right.identifier)))
        if element is None:
            raise ValueError("二维梁单元必须依次连接相邻节点。")
        ordered_elements.append(element)
    if len(ordered_elements) != len(project.elements):
        raise ValueError("当前二维梁算法不支持分支或重复梁单元。")
    return nodes, tuple(ordered_elements)


def legacy_config_from_project(
    project: ProjectDocument,
    *,
    include_analysis_parameters: bool = True,
) -> dict[str, Any]:
    if project.modeling_space != "2d":
        raise ValueError("当前二维梁算法不支持三维建模空间。")
    nodes, elements = _ordered_beam(project)
    node_index = {node.identifier: index for index, node in enumerate(nodes)}
    element_index = {element.identifier: index for index, element in enumerate(elements)}
    node_x = [float(node.coordinates[0]) for node in nodes]

    section = project.sections[0] if project.sections else None
    if section is None:
        raise ValueError("项目缺少梁截面。")
    material = project.materials[0] if project.materials else None
    elastic_modulus = None if material is None else material.elastic_modulus

    elements_sensor_data = [{"measurements": []} for _ in elements]
    for sensor in project.sensors:
        surface_angle = sensor.attachment.surface_angle_degrees
        orientation_angle = sensor.attachment.orientation_angle_degrees
        on_supported_surface = min(
            abs(surface_angle),
            abs(surface_angle - 180.0),
            abs(surface_angle - 360.0),
        ) <= 1.0e-8
        axial_orientation = abs((orientation_angle + 90.0) % 180.0 - 90.0) <= 1.0e-8
        direction = sensor.attachment.direction
        aligned_with_x = (
            abs(abs(direction[0]) - 1.0) <= 1.0e-8
            and abs(direction[1]) <= 1.0e-8
            and abs(direction[2]) <= 1.0e-8
        )
        if not (on_supported_surface and axial_orientation and aligned_with_x):
            raise ValueError("当前二维梁算法仅支持上下表面的轴向应变测点。")
        index = element_index[sensor.attachment.entity_id]
        element = elements[index]
        left_node = nodes[index]
        right_node = nodes[index + 1]
        length = node_x[index + 1] - node_x[index]
        xi = sensor.attachment.local_coordinates[0]
        bounds = sensor.attachment.integration_bounds
        if element.node_ids == (right_node.identifier, left_node.identifier):
            xi = 1.0 - xi
            bounds = (1.0 - bounds[1], 1.0 - bounds[0])
        measurement = {
            "x": float(xi * length),
            "surface": "top" if sensor.attachment.surface_side == "top" else "bot",
            "strain": float(sensor.measured_value or 0.0),
            "weight": float(sensor.weight),
            "zone": [float(bounds[0] * length), float(bounds[1] * length)],
        }
        if sensor.channel_id:
            measurement["channel_id"] = sensor.channel_id
        elements_sensor_data[index]["measurements"].append(measurement)

    prescribed_dofs = {}
    for boundary in project.boundary_conditions:
        prescribed_dofs[make_global_dof(node_index[boundary.node_id], boundary.dof)] = float(
            boundary.value
        )

    analysis = None
    if project.active_analysis_id is not None:
        analysis = next(
            item for item in project.analysis_cases if item.identifier == project.active_analysis_id
        )
    elif project.analysis_cases:
        analysis = project.analysis_cases[0]
    parameters = {} if analysis is None else dict(analysis.parameters)
    if not include_analysis_parameters:
        parameters = {}

    config = {
        "node_x": node_x,
        "thickness": float(section.thickness),
        "material": {"elastic_modulus": elastic_modulus},
        "gauss_n": int(parameters.get("gauss_n", 3)),
        "points_per_element": int(parameters.get("points_per_element", 120)),
        "elements_sensor_data": elements_sensor_data,
        "prescribed_dofs": prescribed_dofs,
        "query_xs": list(parameters.get("query_xs", [])),
        "true_points": list(parameters.get("true_points", [])),
        "plot_options": dict(project.view_state),
    }
    normalized = normalize_config(config)
    validate_config(normalized, require_measurements=False)
    return normalized
