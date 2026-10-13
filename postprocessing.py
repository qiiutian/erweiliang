from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ifem.visualization.result_link import visible_sample_indices


@dataclass(frozen=True)
class BeamSectionField:
    element_index: np.ndarray
    x_reference: np.ndarray
    x_deformed: np.ndarray
    y_deformed: np.ndarray
    rotation: np.ndarray
    axial_strain: np.ndarray
    curvature: np.ndarray
    section_y: np.ndarray
    strain: np.ndarray
    stress: np.ndarray | None
    thickness: float
    elastic_modulus: float | None
    representation: str = "raw"

    @property
    def top_strain(self):
        return self.strain[-1]

    @property
    def bottom_strain(self):
        return self.strain[0]

    @property
    def top_stress(self):
        return None if self.stress is None else self.stress[-1]

    @property
    def bottom_stress(self):
        return None if self.stress is None else self.stress[0]

    def display_grid(self, thickness_scale):
        scale = float(thickness_scale)
        if not np.isfinite(scale) or scale <= 0.0:
            raise ValueError("厚度显示倍率必须大于 0。")

        offsets = self.section_y[:, None] * scale
        sin_theta = np.sin(self.rotation)[None, :]
        cos_theta = np.cos(self.rotation)[None, :]
        x_grid = self.x_deformed[None, :] - offsets * sin_theta
        y_grid = self.y_deformed[None, :] + offsets * cos_theta
        return x_grid, y_grid


def reconstruct_section_field(
    model,
    *,
    points_per_element=100,
    elastic_modulus=None,
    through_thickness_points=9,
):
    if model.U is None:
        raise RuntimeError("请先完成形状重构。")

    points_per_element = int(points_per_element)
    through_thickness_points = int(through_thickness_points)
    if points_per_element < 2:
        raise ValueError("每单元场采样点数至少为 2。")
    if through_thickness_points < 2:
        raise ValueError("厚度方向场采样点数至少为 2。")

    if elastic_modulus in (None, ""):
        elastic_modulus = None
    else:
        elastic_modulus = float(elastic_modulus)
        if not np.isfinite(elastic_modulus) or elastic_modulus <= 0.0:
            raise ValueError("弹性模量 E 必须大于 0。")

    x_reference_parts = []
    element_index_parts = []
    x_deformed_parts = []
    y_deformed_parts = []
    rotation_parts = []
    axial_strain_parts = []
    curvature_parts = []

    for element in range(model.n_elems):
        x_start = float(model.node_x[element])
        length = float(model.node_x[element + 1] - model.node_x[element])
        element_u = model.U[model.element_dofs(element)]
        local_xs = np.linspace(0.0, length, points_per_element)

        x_reference = x_start + local_xs
        axial_u = np.empty_like(local_xs)
        transverse_v = np.empty_like(local_xs)
        rotation = np.empty_like(local_xs)
        axial_strain = np.empty_like(local_xs)
        curvature = np.empty_like(local_xs)

        for index, local_x in enumerate(local_xs):
            shape = model.shape_functions(local_x, length)
            dshape = model.dshape_dx(local_x, length)

            axial_u[index] = shape[0] * element_u[0] + shape[3] * element_u[3]
            transverse_v[index] = (
                shape[1] * element_u[1]
                + shape[2] * element_u[2]
                + shape[4] * element_u[4]
                + shape[5] * element_u[5]
            )

            du_dx = dshape[0] * element_u[0] + dshape[3] * element_u[3]
            dv_dx = (
                dshape[1] * element_u[1]
                + dshape[2] * element_u[2]
                + dshape[4] * element_u[4]
                + dshape[5] * element_u[5]
            )
            rotation[index] = np.arctan2(dv_dx, 1.0 + du_dx)
            axial_strain[index] = model.Bb(local_x, length) @ element_u
            curvature[index] = model.Bm(local_x, length) @ element_u

        x_reference_parts.append(x_reference)
        element_index_parts.append(np.full(local_xs.shape, element, dtype=int))
        x_deformed_parts.append(x_reference + axial_u)
        y_deformed_parts.append(transverse_v)
        rotation_parts.append(rotation)
        axial_strain_parts.append(axial_strain)
        curvature_parts.append(curvature)

    x_reference = np.concatenate(x_reference_parts)
    element_index = np.concatenate(element_index_parts)
    x_deformed = np.concatenate(x_deformed_parts)
    y_deformed = np.concatenate(y_deformed_parts)
    rotation = np.concatenate(rotation_parts)
    axial_strain = np.concatenate(axial_strain_parts)
    curvature = np.concatenate(curvature_parts)

    section_y = np.linspace(-model.h, model.h, through_thickness_points)
    strain = axial_strain[None, :] - section_y[:, None] * curvature[None, :]
    stress = None if elastic_modulus is None else elastic_modulus * strain

    return BeamSectionField(
        element_index=element_index,
        x_reference=x_reference,
        x_deformed=x_deformed,
        y_deformed=y_deformed,
        rotation=rotation,
        axial_strain=axial_strain,
        curvature=curvature,
        section_y=section_y,
        strain=strain,
        stress=stress,
        thickness=float(model.thickness),
        elastic_modulus=elastic_modulus,
    )


def recover_continuous_section_field(field):
    element_ids = np.unique(field.element_index)
    if len(element_ids) < 1:
        raise ValueError("原始截面场不包含单元数据。")

    element_ranges = []
    element_lengths = []
    for element in element_ids:
        indices = np.flatnonzero(field.element_index == element)
        if len(indices) < 2:
            raise ValueError(f"第 {int(element)} 个单元的场采样点不足。")
        element_ranges.append(indices)
        element_lengths.append(float(field.x_reference[indices[-1]] - field.x_reference[indices[0]]))

    node_axial_strain = np.empty(len(element_ids) + 1, dtype=float)
    node_curvature = np.empty(len(element_ids) + 1, dtype=float)
    node_axial_strain[0] = field.axial_strain[element_ranges[0][0]]
    node_curvature[0] = field.curvature[element_ranges[0][0]]
    node_axial_strain[-1] = field.axial_strain[element_ranges[-1][-1]]
    node_curvature[-1] = field.curvature[element_ranges[-1][-1]]

    for node in range(1, len(element_ids)):
        left_indices = element_ranges[node - 1]
        right_indices = element_ranges[node]
        left_weight = element_lengths[node - 1]
        right_weight = element_lengths[node]
        weight_sum = left_weight + right_weight
        node_axial_strain[node] = (
            left_weight * field.axial_strain[left_indices[-1]]
            + right_weight * field.axial_strain[right_indices[0]]
        ) / weight_sum
        node_curvature[node] = (
            left_weight * field.curvature[left_indices[-1]]
            + right_weight * field.curvature[right_indices[0]]
        ) / weight_sum

    element_index_parts = []
    x_reference_parts = []
    x_deformed_parts = []
    y_deformed_parts = []
    rotation_parts = []
    axial_strain_parts = []
    curvature_parts = []

    for position, (element, indices) in enumerate(zip(element_ids, element_ranges)):
        x_values = field.x_reference[indices]
        length = element_lengths[position]
        ratio = (x_values - x_values[0]) / length
        recovered_axial = (1.0 - ratio) * node_axial_strain[position] + ratio * node_axial_strain[position + 1]
        recovered_curvature = (1.0 - ratio) * node_curvature[position] + ratio * node_curvature[position + 1]

        if position > 0:
            indices = indices[1:]
            x_values = x_values[1:]
            recovered_axial = recovered_axial[1:]
            recovered_curvature = recovered_curvature[1:]

        element_index_parts.append(np.full(len(indices), int(element), dtype=int))
        x_reference_parts.append(x_values)
        x_deformed_parts.append(field.x_deformed[indices])
        y_deformed_parts.append(field.y_deformed[indices])
        rotation_parts.append(field.rotation[indices])
        axial_strain_parts.append(recovered_axial)
        curvature_parts.append(recovered_curvature)

    x_reference = np.concatenate(x_reference_parts)
    axial_strain = np.concatenate(axial_strain_parts)
    curvature = np.concatenate(curvature_parts)
    strain = axial_strain[None, :] - field.section_y[:, None] * curvature[None, :]
    stress = None if field.elastic_modulus is None else field.elastic_modulus * strain

    return BeamSectionField(
        element_index=np.concatenate(element_index_parts),
        x_reference=x_reference,
        x_deformed=np.concatenate(x_deformed_parts),
        y_deformed=np.concatenate(y_deformed_parts),
        rotation=np.concatenate(rotation_parts),
        axial_strain=axial_strain,
        curvature=curvature,
        section_y=field.section_y.copy(),
        strain=strain,
        stress=stress,
        thickness=field.thickness,
        elastic_modulus=field.elastic_modulus,
        representation="nodal_average",
    )


def element_boundary_jumps(field):
    element_ids = np.unique(field.element_index)
    rows = []
    for position in range(len(element_ids) - 1):
        left_indices = np.flatnonzero(field.element_index == element_ids[position])
        right_indices = np.flatnonzero(field.element_index == element_ids[position + 1])
        left_index = left_indices[-1]
        right_index = right_indices[0]
        rows.append(
            {
                "x": float(field.x_reference[left_index]),
                "axial_strain_jump": float(field.axial_strain[right_index] - field.axial_strain[left_index]),
                "curvature_jump": float(field.curvature[right_index] - field.curvature[left_index]),
                "top_strain_jump": float(field.top_strain[right_index] - field.top_strain[left_index]),
                "bottom_strain_jump": float(field.bottom_strain[right_index] - field.bottom_strain[left_index]),
                "top_stress_jump": (
                    None
                    if field.top_stress is None
                    else float(field.top_stress[right_index] - field.top_stress[left_index])
                ),
                "bottom_stress_jump": (
                    None
                    if field.bottom_stress is None
                    else float(field.bottom_stress[right_index] - field.bottom_stress[left_index])
                ),
            }
        )
    return rows


def resolve_thickness_scale(field, setting="auto"):
    if setting in (None, "", "auto"):
        beam_length = max(float(np.ptp(field.x_reference)), 1e-12)
        target_thickness = 0.05 * beam_length
        return max(1.0, target_thickness / field.thickness)

    scale = float(setting)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("厚度显示倍率必须大于 0。")
    return scale


def section_field_rows(field, max_rows=240, *, include_index=None):
    point_count = len(field.x_reference)
    if point_count == 0:
        return []

    indices = visible_sample_indices(point_count, max_rows=max_rows, include_index=include_index)
    rows = []
    for sequence, index in enumerate(indices, start=1):
        rows.append(
            {
                "sequence": sequence,
                "sample_index": int(index),
                "element_index": int(field.element_index[index]),
                "x": float(field.x_reference[index]),
                "strain_top": float(field.top_strain[index]),
                "strain_bottom": float(field.bottom_strain[index]),
                "stress_top": None if field.top_stress is None else float(field.top_stress[index]),
                "stress_bottom": None if field.bottom_stress is None else float(field.bottom_stress[index]),
            }
        )
    return rows
