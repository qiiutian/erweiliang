from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np

from ifem.domain.project import SectionDefinition
from ifem.modeling.section_geometry import section_profile_loops


def _readonly_array(values, *, dtype=None):
    array = np.array(values, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class StructuralModelData:
    node_coordinates: np.ndarray
    line_elements: np.ndarray
    thickness: float
    section_width: float | None = None
    section_shape: str = "rectangle"
    section_parameters: Mapping[str, float] = field(default_factory=dict)
    source: str = "internal"

    def __post_init__(self):
        nodes = _readonly_array(self.node_coordinates, dtype=float)
        elements = _readonly_array(self.line_elements, dtype=int)
        if nodes.ndim != 2 or nodes.shape[1] != 3 or len(nodes) < 2:
            raise ValueError("结构模型节点必须是至少两个三维坐标。")
        if elements.ndim != 2 or elements.shape[1] != 2:
            raise ValueError("当前结构模型要求二节点线单元连接关系。")
        if np.any(elements < 0) or np.any(elements >= len(nodes)):
            raise ValueError("结构模型的单元连接包含越界节点。")

        thickness = float(self.thickness)
        if not np.isfinite(thickness) or thickness <= 0.0:
            raise ValueError("结构模型厚度必须大于 0。")
        section_width = self.section_width
        if section_width is not None:
            section_width = float(section_width)
            if not np.isfinite(section_width) or section_width <= 0.0:
                raise ValueError("结构模型截面宽度必须大于 0。")
        section_shape = str(self.section_shape).strip().lower()
        section_parameters = {
            str(key): float(value) for key, value in self.section_parameters.items()
        }
        if section_shape != "rectangle" or section_parameters:
            canonical = SectionDefinition(
                "visual_section",
                "结果截面",
                thickness,
                section_width,
                section_shape,
                section_parameters,
            )
            thickness = canonical.thickness
            section_width = canonical.width
            section_shape = canonical.shape
            section_parameters = dict(canonical.parameters)

        object.__setattr__(self, "node_coordinates", nodes)
        object.__setattr__(self, "line_elements", elements)
        object.__setattr__(self, "thickness", thickness)
        object.__setattr__(self, "section_width", section_width)
        object.__setattr__(self, "section_shape", section_shape)
        object.__setattr__(self, "section_parameters", section_parameters)

    @property
    def length(self):
        segments = self.node_coordinates[self.line_elements[:, 1]] - self.node_coordinates[
            self.line_elements[:, 0]
        ]
        return float(np.sum(np.linalg.norm(segments, axis=1)))


@dataclass(frozen=True)
class SensorSample:
    label: str
    element_index: int
    surface: str
    measured_strain: float
    reference_x: float
    section_offset: float
    position: np.ndarray

    def __post_init__(self):
        position = _readonly_array(self.position, dtype=float)
        if position.shape != (3,):
            raise ValueError("测点位置必须是三维坐标。")
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "reference_x", float(self.reference_x))
        object.__setattr__(self, "section_offset", float(self.section_offset))


@dataclass(frozen=True)
class BeamSectionResult:
    element_index: np.ndarray
    x_reference: np.ndarray
    centerline_deformed: np.ndarray
    rotation: np.ndarray
    section_y: np.ndarray
    strain: np.ndarray
    stress: np.ndarray | None
    representation: str
    strain_reference_limit: float
    stress_reference_limit: float | None

    def __post_init__(self):
        element_index = _readonly_array(self.element_index, dtype=int)
        x_reference = _readonly_array(self.x_reference, dtype=float)
        centerline = _readonly_array(self.centerline_deformed, dtype=float)
        rotation = _readonly_array(self.rotation, dtype=float)
        section_y = _readonly_array(self.section_y, dtype=float)
        strain = _readonly_array(self.strain, dtype=float)
        stress = None if self.stress is None else _readonly_array(self.stress, dtype=float)

        point_count = len(x_reference)
        if element_index.shape != (point_count,):
            raise ValueError("单元索引数量与梁场采样点不一致。")
        if centerline.shape != (point_count, 3):
            raise ValueError("梁中心线必须为三维采样坐标。")
        if rotation.shape != (point_count,):
            raise ValueError("梁转角数量与场采样点不一致。")
        expected_field_shape = (len(section_y), point_count)
        if strain.shape != expected_field_shape:
            raise ValueError("梁应变场维度与截面采样不一致。")
        if stress is not None and stress.shape != expected_field_shape:
            raise ValueError("梁应力场维度与截面采样不一致。")
        if self.representation not in {"raw", "nodal_average"}:
            raise ValueError("未知的梁场表示方式。")
        strain_reference_limit = float(self.strain_reference_limit)
        if not np.isfinite(strain_reference_limit) or strain_reference_limit < 0.0:
            raise ValueError("应变场参考范围不合法。")
        stress_reference_limit = self.stress_reference_limit
        if stress_reference_limit is not None:
            stress_reference_limit = float(stress_reference_limit)
            if not np.isfinite(stress_reference_limit) or stress_reference_limit < 0.0:
                raise ValueError("应力场参考范围不合法。")

        object.__setattr__(self, "element_index", element_index)
        object.__setattr__(self, "x_reference", x_reference)
        object.__setattr__(self, "centerline_deformed", centerline)
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "section_y", section_y)
        object.__setattr__(self, "strain", strain)
        object.__setattr__(self, "stress", stress)
        object.__setattr__(self, "strain_reference_limit", strain_reference_limit)
        object.__setattr__(self, "stress_reference_limit", stress_reference_limit)


@dataclass(frozen=True)
class ResultFrame:
    sequence: int
    time_value: float
    deformed_nodes: np.ndarray
    nodal_displacement: np.ndarray
    section: BeamSectionResult
    sensors: tuple[SensorSample, ...] = ()

    def __post_init__(self):
        deformed_nodes = _readonly_array(self.deformed_nodes, dtype=float)
        displacement = _readonly_array(self.nodal_displacement, dtype=float)
        if deformed_nodes.ndim != 2 or deformed_nodes.shape[1] != 3:
            raise ValueError("结果帧节点坐标必须是三维数组。")
        if displacement.shape != deformed_nodes.shape:
            raise ValueError("结果帧节点位移与节点坐标维度不一致。")
        object.__setattr__(self, "sequence", int(self.sequence))
        object.__setattr__(self, "time_value", float(self.time_value))
        object.__setattr__(self, "deformed_nodes", deformed_nodes)
        object.__setattr__(self, "nodal_displacement", displacement)
        object.__setattr__(self, "sensors", tuple(self.sensors))


@dataclass(frozen=True)
class SurfaceBlock:
    element_index: int | None
    points: np.ndarray
    displacement_magnitude: np.ndarray
    axial_strain: np.ndarray
    axial_stress: np.ndarray | None


def structural_model_from_beam(model, *, section=None, section_width=None):
    nodes = np.column_stack(
        [
            np.asarray(model.node_x, dtype=float),
            np.zeros(model.n_nodes, dtype=float),
            np.zeros(model.n_nodes, dtype=float),
        ]
    )
    elements = np.column_stack(
        [np.arange(model.n_elems, dtype=int), np.arange(1, model.n_nodes, dtype=int)]
    )
    if section is not None and not isinstance(section, SectionDefinition):
        raise TypeError("结果可视化截面必须是 SectionDefinition。")
    return StructuralModelData(
        node_coordinates=nodes,
        line_elements=elements,
        thickness=float(model.thickness),
        section_width=(section.width if section is not None else section_width),
        section_shape=(section.shape if section is not None else "rectangle"),
        section_parameters=(section.parameters if section is not None else {}),
        source="iFEM beam2d",
    )


def _measurement_offset(measurement, half_thickness):
    surface = str(measurement.get("surface", "")).strip().lower()
    if surface in {"top", "上"}:
        return float(half_thickness), "top"
    if surface in {"bot", "bottom", "下"}:
        return -float(half_thickness), "bottom"

    y_value = float(measurement.get("y", 0.0))
    return y_value, "top" if y_value >= 0.0 else "bottom"


def _sensor_samples(model, section, elements_sensor_data):
    sensors = []
    sequence = 1
    for element_index, element_data in enumerate(elements_sensor_data or []):
        indices = np.flatnonzero(section.element_index == element_index)
        if len(indices) < 2:
            continue
        x_values = section.x_reference[indices]
        centerline = section.centerline_deformed[indices]
        rotation = section.rotation[indices]
        for measurement in element_data.get("measurements", []):
            global_x = float(model.node_x[element_index]) + float(measurement["x"])
            center_x = float(np.interp(global_x, x_values, centerline[:, 0]))
            center_y = float(np.interp(global_x, x_values, centerline[:, 1]))
            angle = float(np.interp(global_x, x_values, rotation))
            offset, surface = _measurement_offset(measurement, model.h)
            position = np.array(
                [
                    center_x - offset * np.sin(angle),
                    center_y + offset * np.cos(angle),
                    0.0,
                ],
                dtype=float,
            )
            sensors.append(
                SensorSample(
                    label=f"M{sequence}",
                    element_index=element_index,
                    surface=surface,
                    measured_strain=float(measurement["strain"]),
                    reference_x=global_x,
                    section_offset=offset,
                    position=position,
                )
            )
            sequence += 1
    return tuple(sensors)


def result_frame_from_beam(
    model,
    field,
    *,
    elements_sensor_data=None,
    sequence=0,
    time_value=0.0,
    reference_field=None,
):
    u_node, v_node, _rotation_node = model.nodal_results()
    reference_nodes = np.column_stack(
        [
            np.asarray(model.node_x, dtype=float),
            np.zeros(model.n_nodes, dtype=float),
            np.zeros(model.n_nodes, dtype=float),
        ]
    )
    nodal_displacement = np.column_stack(
        [u_node, v_node, np.zeros(model.n_nodes, dtype=float)]
    )
    deformed_nodes = reference_nodes + nodal_displacement
    reference_field = field if reference_field is None else reference_field
    section = BeamSectionResult(
        element_index=field.element_index,
        x_reference=field.x_reference,
        centerline_deformed=np.column_stack(
            [
                field.x_deformed,
                field.y_deformed,
                np.zeros(len(field.x_reference), dtype=float),
            ]
        ),
        rotation=field.rotation,
        section_y=field.section_y,
        strain=field.strain,
        stress=field.stress,
        representation=field.representation,
        strain_reference_limit=float(np.max(np.abs(reference_field.strain))),
        stress_reference_limit=(
            None
            if reference_field.stress is None
            else float(np.max(np.abs(reference_field.stress)))
        ),
    )
    return ResultFrame(
        sequence=sequence,
        time_value=time_value,
        deformed_nodes=deformed_nodes,
        nodal_displacement=nodal_displacement,
        section=section,
        sensors=_sensor_samples(model, section, elements_sensor_data),
    )


def build_surface_blocks(model_data, frame, thickness_scale):
    scale = float(thickness_scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("三维视图厚度倍率必须大于 0。")

    section = frame.section
    if section.representation == "raw":
        index_groups = [
            (int(element), np.flatnonzero(section.element_index == element))
            for element in np.unique(section.element_index)
        ]
    else:
        index_groups = [(None, np.arange(len(section.x_reference), dtype=int))]

    has_defined_profile = bool(model_data.section_parameters)
    if has_defined_profile:
        display_section = SectionDefinition(
            "visual_section",
            "结果截面",
            model_data.thickness,
            model_data.section_width,
            model_data.section_shape,
            model_data.section_parameters,
        )
        profile_loops = section_profile_loops(display_section, resolution=36)
    else:
        display_width = model_data.section_width
        if display_width is None:
            display_width = max(0.045 * model_data.length, model_data.thickness * scale)
        z_values = np.array([-0.5 * display_width, 0.5 * display_width], dtype=float)

    blocks = []
    for element_index, indices in index_groups:
        centerline = section.centerline_deformed[indices]
        rotation = section.rotation[indices]
        displacement = np.linalg.norm(
            centerline
            - np.column_stack(
                [
                    section.x_reference[indices],
                    np.zeros(len(indices), dtype=float),
                    np.zeros(len(indices), dtype=float),
                ]
            ),
            axis=1,
        )
        if has_defined_profile:
            for profile in profile_loops:
                closed_profile = np.vstack((profile, profile[0]))
                section_u = closed_profile[:, 0]
                displayed_u = section_u * scale
                displayed_v = closed_profile[:, 1] * scale
                points = np.empty((len(indices), len(closed_profile), 3), dtype=float)
                points[..., 0] = (
                    centerline[:, 0, None]
                    - np.sin(rotation)[:, None] * displayed_u[None, :]
                )
                points[..., 1] = (
                    centerline[:, 1, None]
                    + np.cos(rotation)[:, None] * displayed_u[None, :]
                )
                points[..., 2] = displayed_v[None, :]

                strain_field = np.asarray(
                    [
                        np.interp(
                            section_u,
                            section.section_y,
                            section.strain[:, sample_index],
                        )
                        for sample_index in indices
                    ],
                    dtype=float,
                )
                stress_field = (
                    None
                    if section.stress is None
                    else np.asarray(
                        [
                            np.interp(
                                section_u,
                                section.section_y,
                                section.stress[:, sample_index],
                            )
                            for sample_index in indices
                        ],
                        dtype=float,
                    )
                )
                blocks.append(
                    SurfaceBlock(
                        element_index=element_index,
                        points=points,
                        displacement_magnitude=np.broadcast_to(
                            displacement[:, None], points.shape[:-1]
                        ).copy(),
                        axial_strain=strain_field,
                        axial_stress=stress_field,
                    )
                )
            continue

        offsets = section.section_y[:, None] * scale
        x_section = centerline[:, 0][None, :] - offsets * np.sin(rotation)[None, :]
        y_section = centerline[:, 1][None, :] + offsets * np.cos(rotation)[None, :]

        shape = (len(indices), len(section.section_y), len(z_values))
        points = np.empty(shape + (3,), dtype=float)
        points[..., 0] = np.repeat(x_section.T[:, :, None], len(z_values), axis=2)
        points[..., 1] = np.repeat(y_section.T[:, :, None], len(z_values), axis=2)
        points[..., 2] = np.broadcast_to(z_values, shape)

        displacement_field = np.broadcast_to(
            displacement[:, None, None], shape
        ).copy()
        strain_field = np.repeat(section.strain[:, indices].T[:, :, None], 2, axis=2)
        stress_field = (
            None
            if section.stress is None
            else np.repeat(section.stress[:, indices].T[:, :, None], 2, axis=2)
        )
        blocks.append(
            SurfaceBlock(
                element_index=element_index,
                points=points,
                displacement_magnitude=displacement_field,
                axial_strain=strain_field,
                axial_stress=stress_field,
            )
        )
    return blocks
