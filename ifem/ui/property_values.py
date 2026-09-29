"""Qt-independent property form values and field-addressable validation.

Callers merge draft deltas into values from the *current* project before
applying them. The adapter delegates model changes to ``PathBeamEditor`` and
never mutates a document, including when a later field fails validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from math import isfinite

from ifem.domain.project import ProjectDocument
from ifem.modeling.path_editor import PathBeamEditor
from ifem.modeling.section_geometry import (
    SECTION_PARAMETER_SPECS,
    default_section_parameters,
)


GLOBAL_KEY = ("primary", "")


class PropertyInputError(ValueError):
    """An actionable validation message attached to one form field."""

    def __init__(self, field: str, message: str):
        self.field = str(field)
        super().__init__(message)


def _entity(project, key):
    kind, identifier = key
    collections = {
        "node": project.nodes,
        "element": project.elements,
        "sensor": project.sensors,
    }
    if kind not in collections:
        raise KeyError(f"未知属性对象：{key}")
    for entity in collections[kind]:
        if entity.identifier == identifier:
            return entity
    raise KeyError(f"属性对象已不存在：{identifier}")


def _text(value):
    return f"{float(value):.12g}"


def property_values(project: ProjectDocument, key: tuple[str, str]) -> dict:
    """Return strings for numeric fields and stable IDs for combo fields."""
    if key == GLOBAL_KEY:
        section = project.sections[0] if project.sections else None
        material = project.materials[0] if project.materials else None
        shape = section.shape if section is not None else "rectangle"
        defaults = default_section_parameters(
            shape,
            height=section.thickness if section is not None else 0.1,
            width=section.width if section is not None else None,
        )
        parameters = section.parameters if section is not None else defaults
        values = {"shape": shape, **{f"parameter_{i}": "" for i in range(4)}}
        for index, spec in enumerate(SECTION_PARAMETER_SPECS[shape]):
            values[f"parameter_{index}"] = _text(parameters.get(spec.key, defaults[spec.key]))
        values["modulus"] = (
            "" if material is None or material.elastic_modulus is None
            else _text(material.elastic_modulus / 1.0e9)
        )
        return values
    entity = _entity(project, key)
    if key[0] == "node":
        return dict(zip(("x", "y", "z"), map(_text, entity.coordinates)))
    if key[0] == "element":
        values = {
            "family": entity.family,
            "section": entity.section_id,
            "material": entity.material_id,
        }
        if entity.geometry.kind == "circular_arc":
            parameters = entity.geometry.parameters
            values.update(
                radius=_text(parameters["radius"]),
                sweep=_text(parameters["sweep_degrees"]),
                plane=parameters["plane"],
            )
        return values
    attachment = entity.attachment
    angle = attachment.surface_angle_degrees
    if min(abs(angle), abs(angle - 360.0)) <= 1.0e-8:
        surface = "top"
    elif abs(angle - 180.0) <= 1.0e-8:
        surface = "bottom"
    else:
        surface = "custom"
    return {
        "label": entity.label,
        "element": attachment.entity_id,
        "xi": _text(attachment.local_coordinates[0]),
        "surface": surface,
        "surface_angle": _text(angle),
        "orientation_angle": _text(attachment.orientation_angle_degrees),
        "strain": "" if entity.measured_value is None else _text(entity.measured_value),
        "weight": _text(entity.weight),
        "zone_a": _text(attachment.integration_bounds[0]),
        "zone_b": _text(attachment.integration_bounds[1]),
    }


def _required(values, field, label):
    if field not in values:
        raise PropertyInputError(field, f"请填写或选择{label}。")
    return values[field]


def _number(values, field, label, *, current=None, positive=False):
    raw = _required(values, field, label)
    try:
        if isinstance(raw, bool):
            raise ValueError
        number = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PropertyInputError(field, f"请为{label}输入有效数字。") from exc
    if not isfinite(number):
        raise PropertyInputError(field, f"{label}必须是有限数值，请勿输入 NaN 或无穷大。")
    if positive and number <= 0.0:
        raise PropertyInputError(field, f"{label}必须大于 0，请输入正数。")
    # Formatting is display-only: editing another property must not round an
    # untouched coordinate, angle, or dimension to the form's 12-digit display.
    if current is not None and isinstance(raw, str) and raw.strip() == _text(current):
        return current
    return number


def _reference(values, field, label, entities, *, allow_none=False):
    identifier = _required(values, field, label)
    if identifier is None and allow_none:
        return None
    if not any(item.identifier == identifier for item in entities):
        raise PropertyInputError(field, f"所选{label}已不存在，请重新选择。")
    return identifier


def _apply_primary(project, values):
    shape = _required(values, "shape", "截面类型")
    if not isinstance(shape, str) or shape not in SECTION_PARAMETER_SPECS:
        raise PropertyInputError("shape", "请选择有效的截面类型。")
    section = project.sections[0] if project.sections else None
    old = section.parameters if section is not None and section.shape == shape else {}
    parameters = {
        spec.key: _number(
            values, f"parameter_{index}", spec.label,
            current=old.get(spec.key), positive=True,
        )
        for index, spec in enumerate(SECTION_PARAMETER_SPECS[shape])
    }
    if shape == "rectangle":
        height, width = parameters["height"], parameters["width"]
    elif shape == "circle":
        height = width = parameters["diameter"]
    elif shape == "circular_tube":
        height = width = parameters["outer_diameter"]
        if parameters["wall_thickness"] * 2.0 >= height:
            raise PropertyInputError("parameter_1", "请减小圆管壁厚，使其小于外径的一半。")
    elif shape == "box":
        height, width = parameters["outer_height"], parameters["outer_width"]
        if parameters["wall_thickness"] * 2.0 >= min(height, width):
            raise PropertyInputError("parameter_2", "请减小矩形管壁厚，使其小于外高和外宽的一半。")
    else:
        height, width = parameters["height"], parameters["flange_width"]
        if parameters["flange_thickness"] * 2.0 >= height:
            raise PropertyInputError("parameter_2", "请减小翼缘厚度，使其小于截面高度的一半。")
        if parameters["web_thickness"] >= width:
            raise PropertyInputError("parameter_3", "请减小腹板厚度，使其小于翼缘宽度。")
    raw_modulus = _required(values, "modulus", "弹性模量")
    modulus = None
    if not isinstance(raw_modulus, str) or raw_modulus.strip():
        modulus = _number(values, "modulus", "弹性模量", positive=True) * 1.0e9
        if not isfinite(modulus):
            raise PropertyInputError("modulus", "弹性模量过大，请检查 GPa 单位与数量级。")
        material = project.materials[0] if project.materials else None
        if (
            material is not None and material.elastic_modulus is not None
            and isinstance(raw_modulus, str)
            and raw_modulus.strip() == _text(material.elastic_modulus / 1.0e9)
        ):
            modulus = material.elastic_modulus
    return PathBeamEditor.update_primary_properties(
        project, thickness=height, width=width, elastic_modulus=modulus,
        section_shape=shape, section_parameters=parameters,
    )


def _apply_element(project, element, values):
    family = _required(values, "family", "单元族")
    if not isinstance(family, str) or not family.strip():
        raise PropertyInputError("family", "请选择有效的几何 / 单元族。")
    if element.geometry.kind != "line" and family != element.family:
        raise PropertyInputError("family", "曲线单元族由几何定义决定，请保留当前单元族。")
    section_id = _reference(values, "section", "截面", project.sections, allow_none=True)
    material_id = _reference(values, "material", "材料", project.materials, allow_none=True)
    arc = None
    if element.geometry.kind == "circular_arc":
        old = element.geometry.parameters
        radius = _number(values, "radius", "圆弧半径", current=old["radius"], positive=True)
        sweep = _number(values, "sweep", "圆心角", current=old["sweep_degrees"])
        if not 1.0e-9 < abs(sweep) < 360.0:
            raise PropertyInputError("sweep", "圆心角绝对值须大于 1e-9° 且小于 360°，负值表示反向圆弧。")
        plane = _required(values, "plane", "圆弧平面")
        if plane not in ("xy", "xz", "yz", "custom"):
            raise PropertyInputError("plane", "请选择 XY、XZ、YZ 或保留当前任意空间平面。")
        if (radius, sweep, plane) != (old["radius"], old["sweep_degrees"], old["plane"]):
            arc = {"radius": radius, "sweep_degrees": sweep, "plane": plane}
    updated = PathBeamEditor.update_element(
        project, element.identifier, family=family,
        section_id=section_id, material_id=material_id,
    )
    if arc is not None:
        try:
            updated = PathBeamEditor.update_circular_arc(updated, element.identifier, **arc)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise PropertyInputError("plane", str(exc)) from exc
    return updated


def _apply_sensor(project, sensor, values):
    attachment = sensor.attachment
    element_id = _reference(values, "element", "附着梁段", project.elements)
    label = _required(values, "label", "测点名称")
    if not isinstance(label, str) or not label.strip():
        raise PropertyInputError("label", "请填写非空的测点名称。")
    xi = _number(values, "xi", "局部坐标 ξ", current=attachment.local_coordinates[0])
    if not 0.0 <= xi <= 1.0:
        raise PropertyInputError("xi", "请将局部坐标 ξ 设置在 0 到 1 之间。")
    surface_angle = _number(values, "surface_angle", "环向角 θ", current=attachment.surface_angle_degrees) % 360.0
    orientation_angle = _number(values, "orientation_angle", "测量轴角 α", current=attachment.orientation_angle_degrees)
    raw_strain = _required(values, "strain", "应变 ε")
    strain = (
        None if isinstance(raw_strain, str) and not raw_strain.strip()
        else _number(values, "strain", "应变 ε", current=sensor.measured_value)
    )
    weight = _number(values, "weight", "测点权重", current=sensor.weight, positive=True)
    zone_a = _number(values, "zone_a", "局部积分起点 a", current=attachment.integration_bounds[0])
    zone_b = _number(values, "zone_b", "局部积分终点 b", current=attachment.integration_bounds[1])
    if not 0.0 <= zone_a < 1.0:
        raise PropertyInputError("zone_a", "积分起点 a 须大于等于 0 且小于 1。")
    if not zone_a < zone_b <= 1.0:
        raise PropertyInputError("zone_b", "积分终点 b 须大于起点 a 且不超过 1。")
    resolved_label = sensor.label if label == sensor.label else label.strip()
    updated = PathBeamEditor.update_sensor(
        project, sensor.identifier, element_id=element_id, local_coordinate=xi,
        surface_side="top" if surface_angle < 90.0 or surface_angle >= 270.0 else "bottom",
        direction=attachment.direction, measured_value=0.0 if strain is None else strain, weight=weight,
        zone_a=zone_a, zone_b=zone_b, label=resolved_label,
        surface_angle_degrees=surface_angle, orientation_angle_degrees=orientation_angle,
    )
    same_placement = (
        element_id == attachment.entity_id
        and xi == attachment.local_coordinates[0]
        and surface_angle == attachment.surface_angle_degrees
        and orientation_angle == attachment.orientation_angle_degrees
    )
    # Data-only changes must not reinterpret a valid imported measurement axis.
    # Relocating the sensor or editing either angle still resolves a fresh axis.
    if same_placement:
        updated = replace(updated, sensors=tuple(
            replace(item, label=resolved_label, attachment=(
                attachment if (zone_a, zone_b) == attachment.integration_bounds
                else replace(item.attachment, direction=attachment.direction)
            )) if item.identifier == sensor.identifier else item
            for item in updated.sensors
        ))
    # The editor's numeric API uses a provisional zero, but a blank form means
    # no measurement. An explicit "0" remains an actual zero-valued reading.
    if strain is None:
        updated = replace(updated, sensors=tuple(
            replace(item, measured_value=None) if item.identifier == sensor.identifier else item
            for item in updated.sensors
        ))
    return updated


def apply_property_values(
    project: ProjectDocument,
    key: tuple[str, str],
    values: Mapping,
) -> ProjectDocument:
    """Validate and apply one complete current-state form without mutation.

    Missing entities raise ``KeyError`` so draft managers can prune stale keys;
    invalid user inputs raise ``PropertyInputError`` to focus the exact field.
    The ``surface`` preset is only a UI summary; ``surface_angle`` is authoritative.
    """
    entity = None if key == GLOBAL_KEY else _entity(project, key)
    fallback = {"node": "x", "element": "family", "sensor": "xi", "primary": "parameter_0"}[key[0]]
    try:
        if key == GLOBAL_KEY:
            return _apply_primary(project, values)
        if key[0] == "element":
            return _apply_element(project, entity, values)
        if key[0] == "sensor":
            return _apply_sensor(project, entity, values)
        coordinates = tuple(
            _number(values, field, f"{field} 坐标", current=current)
            for field, current in zip(("x", "y", "z"), entity.coordinates)
        )
        if project.modeling_space == "2d" and abs(coordinates[2]) > 1.0e-10:
            raise PropertyInputError("z", "二维模型的 z 坐标须为 0；如需空间坐标，请先切换到三维建模。")
        return PathBeamEditor.move_node(project, entity.identifier, coordinates)
    except PropertyInputError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PropertyInputError(fallback, str(exc)) from exc
