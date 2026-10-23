"""Native-model-free geometry and scalar points for generic result views.

This module exposes only solved analysis nodes, their declared connectivity, and
explicit field locations. The lines are discrete analysis-node links: they are
not a reconstructed curve, an element shape-function interpolation, or a solid
section. Renderers must keep that distinction visible to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

from ifem.domain.analysis import AnalysisResult, ReconstructionState
from ifem.domain.result_fields import map_result_field


Position = tuple[float, float, float]
DISCRETE_GEOMETRY_DESCRIPTION = "仅显示分析节点及其离散连线；不代表连续曲线或实体截面。"


@dataclass(frozen=True)
class ResultGeometryNode:
    entity_id: str
    reference_position: Position
    position: Position


@dataclass(frozen=True)
class ResultGeometryLine:
    element_id: str
    segment_index: int
    node_ids: tuple[str, str]
    reference_positions: tuple[Position, Position]
    positions: tuple[Position, Position]


@dataclass(frozen=True)
class ResultGeometry:
    modeling_space: str
    deformation_regime: str
    nodes: tuple[ResultGeometryNode, ...]
    lines: tuple[ResultGeometryLine, ...]
    description: str = DISCRETE_GEOMETRY_DESCRIPTION


@dataclass(frozen=True)
class ScalarResultRecord:
    entity_id: str
    value: float
    reference_position: Position | None
    position: Position | None
    source_entity_id: str | None = None
    label: str = ""


@dataclass(frozen=True)
class ScalarPointLayer:
    identifier: str
    label: str
    association: str
    component: str
    unit: str
    coordinate_system: str
    known: bool
    points: tuple[ScalarResultRecord, ...]
    unlocated_records: tuple[ScalarResultRecord, ...]


def build_result_geometry(state: ReconstructionState) -> ResultGeometry:
    """Join connectivity to reference/deformed nodes by their stable IDs.

    A connectivity row with more than two nodes yields adjacent discrete links
    in exactly its declared order. No topology, curve shape, center point, local
    section frame, or intermediate sample is inferred. Separate elements remain
    separate even if their endpoints or geometry coincide.
    """
    if not isinstance(state, ReconstructionState):
        raise TypeError("通用结果几何需要 ReconstructionState。")
    # Revalidate a detached snapshot. This also prevents silently truncating zip
    # when a third-party producer has bypassed the frozen dataclass guarantees.
    snapshot = replace(state)
    nodes = tuple(
        ResultGeometryNode(identifier, reference, position)
        for identifier, reference, position in zip(
            snapshot.node_ids,
            snapshot.reference_coordinates,
            snapshot.deformed_coordinates,
        )
    )
    if any(not isfinite(value) for node in nodes for value in node.position):
        raise ValueError("通用结果几何的重构节点位置必须为有限数值。")
    by_id = {node.entity_id: node for node in nodes}
    lines = []
    for element_id, connection in zip(snapshot.element_ids, snapshot.connectivity):
        if len(connection) != len(set(connection)):
            raise ValueError(f"结果单元 {element_id} 的连接关系不能重复引用同一节点。")
        for index, (left_id, right_id) in enumerate(zip(connection, connection[1:])):
            left, right = by_id[left_id], by_id[right_id]
            lines.append(ResultGeometryLine(
                element_id=element_id,
                segment_index=index,
                node_ids=(left_id, right_id),
                reference_positions=(left.reference_position, right.reference_position),
                positions=(left.position, right.position),
            ))
    return ResultGeometry(
        modeling_space=snapshot.modeling_space,
        deformation_regime=snapshot.deformation_regime,
        nodes=nodes,
        lines=tuple(lines),
    )


def build_scalar_points(
    result: AnalysisResult,
    field_id: str,
    component: str | None = None,
) -> ScalarPointLayer:
    """Select one declared component without interpolation or unit conversion.

    ``component=None`` selects the first component explicitly declared by the
    producer; it does not calculate a norm or infer a preferred physical axis.
    Entities without a location are retained as ``unlocated_records`` for the
    table, never assigned a guessed center or a zero position for plotting.
    """
    layer = map_result_field(result, field_id)
    if component is None:
        component = layer.components[0]
    elif not isinstance(component, str):
        raise TypeError("结果字段分量必须使用声明的名称。")
    try:
        component_index = layer.components.index(component)
    except ValueError as exc:
        raise ValueError(f"结果字段 {field_id} 未声明分量：{component}。") from exc
    points = []
    unlocated = []
    for record in layer.records:
        value = ScalarResultRecord(
            entity_id=record.entity_id,
            value=record.values[component_index],
            reference_position=record.reference_position,
            position=record.position,
            source_entity_id=record.source_entity_id,
            label=record.label,
        )
        if value.reference_position is None or value.position is None:
            unlocated.append(value)
        else:
            points.append(value)
    return ScalarPointLayer(
        identifier=layer.identifier,
        label=layer.label,
        association=layer.association,
        component=component,
        unit=layer.unit,
        coordinate_system=layer.coordinate_system,
        known=layer.known,
        points=tuple(points),
        unlocated_records=tuple(unlocated),
    )
