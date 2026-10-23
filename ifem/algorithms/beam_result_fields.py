"""Typed result fields for the existing, unchanged planar beam solver.

Strain samples are the raw element field, including both sides of an element
boundary.  Sensor residuals are pointwise ``B_surface @ Ue - observation``;
they are neither the local-integration objective nor a reconstruction-error
estimate.  Display smoothing and amplification never enter these values.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import numpy as np

from ifem.domain.analysis import (
    DeformationRegime,
    ReconstructionState,
    ResultField,
    ResultLocation,
    RotationRepresentation,
)


def _ordered_element_ids(model, state: ReconstructionState) -> tuple[str, ...]:
    """Resolve native element order from geometry/connectivity, never row order."""
    if (
        state.modeling_space != "2d"
        or state.deformation_regime != DeformationRegime.SMALL.value
        or state.rotation_representation != RotationRepresentation.ROTATION_VECTOR.value
    ):
        raise ValueError("当前通用梁字段适配器仅支持二维小变形与转角向量。")
    coordinates = np.asarray(state.reference_coordinates, dtype=float)
    if coordinates.shape != (model.n_nodes, 3):
        raise ValueError("通用梁结果的节点数量与求解模型不一致。")
    order = np.argsort(coordinates[:, 0], kind="stable")
    expected = np.column_stack((model.node_x, np.zeros((model.n_nodes, 2))))
    if not np.allclose(coordinates[order], expected, rtol=0.0, atol=1.0e-12):
        raise ValueError("通用梁结果的参考坐标与求解模型不一致。")
    displacement = np.column_stack((model.U[0::3], model.U[1::3], np.zeros(model.n_nodes)))
    rotations = np.column_stack((np.zeros((model.n_nodes, 2)), model.U[2::3]))
    if not np.allclose(np.asarray(state.displacements)[order], displacement, rtol=1.0e-10, atol=1.0e-12):
        raise ValueError("通用梁结果的位移与求解模型不一致。")
    if not np.allclose(np.asarray(state.rotations)[order], rotations, rtol=1.0e-10, atol=1.0e-12):
        raise ValueError("通用梁结果的转角与求解模型不一致。")
    native_ids = tuple(state.node_ids[int(index)] for index in order)
    by_pair = {
        frozenset(connection): identifier
        for identifier, connection in zip(state.element_ids, state.connectivity)
    }
    if len(by_pair) != model.n_elems or len(state.element_ids) != model.n_elems:
        raise ValueError("通用梁结果的单元数量或连接关系与求解模型不一致。")
    try:
        return tuple(
            by_pair[frozenset((left, right))]
            for left, right in zip(native_ids, native_ids[1:])
        )
    except KeyError as exc:
        raise ValueError("通用梁结果的单元连接关系与求解模型不一致。") from exc


def _point_kinematics(model, element: int, local_x: float, surface_y: float = 0.0):
    """Small-deformation EB position, in metres and without display scaling."""
    length = float(model.node_x[element + 1] - model.node_x[element])
    element_u = model.U[model.element_dofs(element)]
    shape = model.shape_functions(local_x, length)
    derivative = model.dshape_dx(local_x, length)
    axial_u = float(shape[0] * element_u[0] + shape[3] * element_u[3])
    transverse_v = float(
        shape[1] * element_u[1]
        + shape[2] * element_u[2]
        + shape[4] * element_u[4]
        + shape[5] * element_u[5]
    )
    slope = float(
        derivative[1] * element_u[1]
        + derivative[2] * element_u[2]
        + derivative[4] * element_u[4]
        + derivative[5] * element_u[5]
    )
    global_x = float(model.node_x[element] + local_x)
    reference = (global_x, float(surface_y), 0.0)
    position = (global_x + axial_u - surface_y * slope, surface_y + transverse_v, 0.0)
    return reference, position


def _sensor_records(model, project, element_ids, snapshot_id):
    """Yield stable identity and actual solver-local coordinates per observation."""
    if project is not None:
        index_by_id = {identifier: index for index, identifier in enumerate(element_ids)}
        project_elements = {element.identifier: element for element in project.elements}
        project_nodes = {node.identifier: node for node in project.nodes}
        for sensor in project.sensors:
            # Missing observations are absent, not a fabricated zero measurement.
            if sensor.measured_value is None:
                continue
            element_id = sensor.attachment.entity_id
            element = index_by_id[element_id]
            definition = project_elements[element_id]
            first_x = project_nodes[definition.node_ids[0]].coordinates[0]
            last_x = project_nodes[definition.node_ids[-1]].coordinates[0]
            xi = sensor.attachment.local_coordinates[0]
            if first_x > last_x:
                xi = 1.0 - xi
            length = float(model.node_x[element + 1] - model.node_x[element])
            surface_y = model.h if sensor.attachment.surface_side == "top" else -model.h
            yield (
                sensor.identifier,
                sensor.label,
                element,
                float(xi * length),
                float(surface_y),
                float(sensor.measured_value),
            )
    else:
        sequence = 0
        for element in range(model.n_elems):
            _length, measurements = model.parse_element_measurements(element)
            for index, measurement in enumerate(measurements):
                sequence += 1
                yield (
                    f"{snapshot_id}:sensor:{element}:{index}",
                    f"M{sequence}",
                    element,
                    float(measurement["x"]),
                    float(measurement["y"]),
                    float(measurement["strain"]),
                )


def build_beam_result_fields(
    model,
    *,
    inputs: Mapping,
    state: ReconstructionState,
    project=None,
    snapshot_id: str | None = None,
) -> tuple[dict[str, ResultField], tuple[ResultLocation, ...]]:
    """Export immutable SI fields and explicit entity locations from a solved beam."""
    if model.U is None:
        raise RuntimeError("请先完成形状重构。")
    snapshot_id = snapshot_id or f"beam-snapshot:{uuid4().hex}"
    element_ids = _ordered_element_ids(model, state)
    fields = {
        "displacement": ResultField(
            "displacement", "node", state.node_ids, ("x", "y", "z"),
            state.displacements, unit="m",
        ),
        "rotation": ResultField(
            "rotation", "node", state.node_ids, ("x", "y", "z"),
            state.rotations, unit="rad",
        ),
    }
    locations = [
        ResultLocation(
            association="node", entity_id=identifier,
            reference_position=reference, position=position,
            label=f"节点 {index + 1}",
        )
        for index, (identifier, reference, position) in enumerate(zip(
            state.node_ids, state.reference_coordinates, state.deformed_coordinates,
        ))
    ]

    points_per_element = int(inputs.get("points_per_element", 120))
    if points_per_element < 2:
        raise ValueError("每单元场采样点数至少为 2。")
    sample_ids = []
    strains = []
    for element in range(model.n_elems):
        length = float(model.node_x[element + 1] - model.node_x[element])
        element_u = model.U[model.element_dofs(element)]
        for index, local_x in enumerate(np.linspace(0.0, length, points_per_element)):
            identifier = f"{snapshot_id}:raw:{element}:{index}"
            sample_ids.append(identifier)
            strains.append(tuple(
                float(model.B_surface(local_x, length, surface_y) @ element_u)
                for surface_y in (model.h, -model.h)
            ))
            reference, position = _point_kinematics(model, element, float(local_x))
            locations.append(ResultLocation(
                association="sample", entity_id=identifier,
                reference_position=reference, position=position,
                source_entity_id=element_ids[element],
                label=f"单元 {element + 1} · 原始采样 {index + 1}",
            ))
    fields["axial_strain"] = ResultField(
        "axial_strain", "sample", tuple(sample_ids), ("top", "bottom"),
        tuple(strains), unit="1", coordinate_system="local",
    )
    elastic_modulus = inputs.get("material", {}).get("elastic_modulus")
    if elastic_modulus is not None:
        elastic_modulus = float(elastic_modulus)
        if not np.isfinite(elastic_modulus) or elastic_modulus <= 0.0:
            raise ValueError("弹性模量 E 必须大于 0。")
        fields["axial_stress"] = ResultField(
            "axial_stress", "sample", tuple(sample_ids), ("top", "bottom"),
            tuple(tuple(elastic_modulus * value for value in row) for row in strains),
            unit="Pa", coordinate_system="local",
        )

    sensor_ids, observed, reconstructed, residuals = [], [], [], []
    for identifier, label, element, local_x, surface_y, measured in _sensor_records(
        model, project, element_ids, snapshot_id,
    ):
        length = float(model.node_x[element + 1] - model.node_x[element])
        element_u = model.U[model.element_dofs(element)]
        strain = float(model.B_surface(local_x, length, surface_y) @ element_u)
        sensor_ids.append(identifier)
        observed.append((measured,))
        reconstructed.append((strain,))
        residuals.append((strain - measured,))
        reference, position = _point_kinematics(model, element, local_x, surface_y)
        side_label = "上表面" if surface_y > 0.0 else "下表面"
        locations.append(ResultLocation(
            association="sensor", entity_id=identifier,
            reference_position=reference, position=position,
            source_entity_id=element_ids[element], label=f"{label} · {side_label}",
        ))
    if sensor_ids:
        for identifier, values in (
            ("sensor_measured_strain", observed),
            ("sensor_reconstructed_strain", reconstructed),
            ("sensor_strain_residual", residuals),
        ):
            fields[identifier] = ResultField(
                identifier, "sensor", tuple(sensor_ids), ("axial",), tuple(values),
                unit="1", coordinate_system="local",
            )
    return fields, tuple(locations)
