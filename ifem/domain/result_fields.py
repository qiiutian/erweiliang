"""Native-model-free physical field definitions and immutable display layers.

The registry gives known identifiers explicit meanings without making them
mandatory for old plugins. Unknown identifiers keep their declared metadata.
No unit conversion, smoothing, interpolation, row-based identity inference, or
view exaggeration happens here. Positions and registered physical values use SI.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from types import MappingProxyType

from ifem.domain.analysis import AnalysisResult, ResultField


@dataclass(frozen=True)
class ResultFieldDefinition:
    identifier: str
    label: str
    associations: tuple[str, ...]
    component_units: tuple[tuple[tuple[str, ...], str], ...]
    coordinate_systems: tuple[str, ...] = ("global", "local")


_VECTOR = (("x", "y"), ("x", "y", "z"))
_AXIAL = (("axial",), ("top", "bottom"))
_SENSOR_IDS = (
    ("sensor_measured_strain", "实测应变"),
    ("sensor_reconstructed_strain", "重构应变"),
    ("sensor_strain_residual", "应变残差（重构 − 实测）"),
)
RESULT_FIELD_DEFINITIONS = MappingProxyType({
    value.identifier: value for value in (
        ResultFieldDefinition(
            "displacement", "位移", ("node", "sample"),
            tuple((components, "m") for components in _VECTOR),
        ),
        ResultFieldDefinition(
            "rotation", "转角", ("node", "sample"),
            (
                (("x", "y", "z"), "rad"),
                (("w", "x", "y", "z"), "1"),
                (("xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"), "1"),
            ),
        ),
        ResultFieldDefinition(
            "axial_strain", "轴向应变", ("node", "element", "sample"),
            tuple((components, "1") for components in _AXIAL),
        ),
        ResultFieldDefinition(
            "axial_stress", "轴向应力", ("node", "element", "sample"),
            tuple((components, "Pa") for components in _AXIAL),
        ),
        *(ResultFieldDefinition(identifier, label, ("sensor",), ((("axial",), "1"),))
          for identifier, label in _SENSOR_IDS),
    )
})


@dataclass(frozen=True)
class ResultFieldRecord:
    entity_id: str
    values: tuple[float, ...]
    reference_position: tuple[float, float, float] | None
    position: tuple[float, float, float] | None
    source_entity_id: str | None = None
    label: str = ""


@dataclass(frozen=True)
class ResultFieldLayer:
    identifier: str
    label: str
    association: str
    components: tuple[str, ...]
    unit: str
    coordinate_system: str
    known: bool
    records: tuple[ResultFieldRecord, ...]


def validate_result_field(field_value: ResultField) -> None:
    """Validate registered semantics; unknown plugins retain actual metadata."""
    if not isinstance(field_value, ResultField):
        raise TypeError("通用结果字段必须是 ResultField。")
    definition = RESULT_FIELD_DEFINITIONS.get(field_value.identifier)
    if definition is None:
        return
    if field_value.association not in definition.associations:
        raise ValueError(f"结果字段 {field_value.identifier} 的实体关联不符合定义。")
    if field_value.coordinate_system not in definition.coordinate_systems:
        raise ValueError(f"结果字段 {field_value.identifier} 的坐标系不符合定义。")
    supported_units = dict(definition.component_units)
    if field_value.components not in supported_units:
        raise ValueError(f"结果字段 {field_value.identifier} 的分量不符合定义。")
    if field_value.unit != supported_units[field_value.components]:
        raise ValueError(
            f"结果字段 {field_value.identifier} 的单位必须为 "
            f"{supported_units[field_value.components]}（SI 原值）。"
        )


def _same_position(left, right):
    return all(isclose(a, b, rel_tol=0.0, abs_tol=1.0e-12) for a, b in zip(left, right))


def map_result_field(result: AnalysisResult, field_id: str) -> ResultFieldLayer:
    """Join one field to its immutable snapshot locations by association + ID.

    Nodes use state coordinates, independently of the field's row order. Samples
    and sensors always need explicit locations; element/global custom metadata
    can be shown without a spatial location and must not be invented by a view.
    """
    if not isinstance(result, AnalysisResult):
        raise TypeError("通用结果映射需要 AnalysisResult。")
    try:
        field_value = result.fields[field_id]
    except KeyError as exc:
        raise KeyError(f"结果未提供字段：{field_id}") from exc
    validate_result_field(field_value)
    if field_value.identifier != field_id:
        raise ValueError("结果字段键必须与 ResultField.identifier 一致。")
    state = result.state
    node_positions = {} if state is None else {
        identifier: (reference, position)
        for identifier, reference, position in zip(
            state.node_ids, state.reference_coordinates, state.deformed_coordinates,
        )
    }
    element_ids = set() if state is None else set(state.element_ids)
    locations = {(value.association, value.entity_id): value for value in result.locations}
    records = []
    for identifier, values in zip(field_value.entity_ids, field_value.values):
        location = locations.get((field_value.association, identifier))
        reference = None if location is None else location.reference_position
        position = None if location is None else location.position
        if field_value.association == "node":
            if identifier not in node_positions:
                raise ValueError(f"结果字段 {field_id} 引用了未知节点：{identifier}。")
            node_reference, node_position = node_positions[identifier]
            if location is not None and (
                not _same_position(reference, node_reference)
                or not _same_position(position, node_position)
            ):
                raise ValueError(f"结果节点 {identifier} 的显式位置与重构状态不一致。")
            reference, position = node_reference, node_position
        elif field_value.association == "element" and identifier not in element_ids:
            raise ValueError(f"结果字段 {field_id} 引用了未知单元：{identifier}。")
        elif field_value.association in {"sensor", "sample"} and location is None:
            raise ValueError(f"结果字段 {field_id} 的实体 {identifier} 缺少显式结果位置。")
        if position is not None and not all(isfinite(value) for value in position):
            raise ValueError(f"结果实体 {identifier} 的重构位置必须为有限数值。")
        records.append(ResultFieldRecord(
            entity_id=identifier,
            values=values,
            reference_position=reference,
            position=position,
            source_entity_id=None if location is None else location.source_entity_id,
            label="" if location is None else location.label,
        ))
    definition = RESULT_FIELD_DEFINITIONS.get(field_id)
    return ResultFieldLayer(
        identifier=field_id,
        label=field_id if definition is None else definition.label,
        association=field_value.association,
        components=field_value.components,
        unit=field_value.unit,
        coordinate_system=field_value.coordinate_system,
        known=definition is not None,
        records=tuple(records),
    )


def validate_result_fields(result: AnalysisResult) -> None:
    """Check all typed fields without requiring optional fields to be present."""
    for field_id in result.fields:
        map_result_field(result, field_id)
