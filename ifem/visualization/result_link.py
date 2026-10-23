"""Snapshot-only links for the existing two-dimensional beam result adapter.

This is deliberately not a general plugin field registry.  Project identifiers
are retained only when a supplied state proves the correspondence with the
native beam result; query and section samples are snapshot entities, not nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral

import numpy as np

from ifem.domain.analysis import DeformationRegime, ReconstructionState


@dataclass(frozen=True)
class ResultTarget:
    kind: str
    index: int
    entity_id: str
    element_id: str | None
    reference_position: tuple[float, float, float]
    position: tuple[float, float, float]
    values: tuple[tuple[str, float | None, str], ...]
    representation: str = ""
    source_id: str = ""

    def __post_init__(self):
        if self.kind not in {"node", "query", "compare", "sample", "sensor"}:
            raise ValueError("未知结果联动目标类型。")
        if isinstance(self.index, bool) or not isinstance(self.index, Integral) or self.index < 0:
            raise ValueError("结果联动目标索引必须为非负整数。")
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise ValueError("结果联动目标必须具有快照实体 ID。")
        for name in ("reference_position", "position"):
            coordinates = np.asarray(getattr(self, name), dtype=float)
            if coordinates.shape != (3,) or not np.isfinite(coordinates).all():
                raise ValueError("结果联动目标位置必须包含三个有限坐标。")
            object.__setattr__(self, name, tuple(float(value) for value in coordinates))
        values = tuple(
            (str(label), None if value is None else float(value), str(unit))
            for label, value, unit in self.values
        )
        if any(not label or (value is not None and not np.isfinite(value)) for label, value, _ in values):
            raise ValueError("结果联动目标数值必须有限；缺失值使用 None。")
        object.__setattr__(self, "index", int(self.index))
        object.__setattr__(self, "values", values)


def visible_sample_indices(count, max_rows=240, include_index=None) -> tuple[int, ...]:
    """Return the table's deterministic sample subset, optionally retaining a pick.

    A picked sample outside the ordinary subset is added without replacing a
    neighboring row.  Thus there are at most ``max_rows + 1`` visible entries.
    """
    if isinstance(count, bool) or not isinstance(count, Integral) or count < 0:
        raise ValueError("采样点数量必须为非负整数。")
    if isinstance(max_rows, bool) or not isinstance(max_rows, Integral) or max_rows < 1:
        raise ValueError("最大采样行数必须为正整数。")
    if include_index is not None:
        if (
            isinstance(include_index, bool)
            or not isinstance(include_index, Integral)
            or not 0 <= include_index < count
        ):
            raise ValueError("选中采样点索引超出范围。")
    if count == 0:
        return ()
    indices = set(int(value) for value in np.linspace(0, count - 1, min(max_rows, count), dtype=int))
    if include_index is not None:
        indices.add(int(include_index))
    return tuple(sorted(indices))


def _finite_array(values, shape, description):
    array = np.asarray(values, dtype=float)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{description}维度或数值无效。")
    return array


def _state_identity(model, state, node_x, displacement, phi):
    if state is None:
        return ("",) * model.n_nodes, (None,) * model.n_elems
    if not isinstance(state, ReconstructionState):
        raise TypeError("结果联动 state 必须是 ReconstructionState。")
    if state.modeling_space != "2d" or state.deformation_regime != DeformationRegime.SMALL.value:
        raise ValueError("当前结果联动适配器仅支持二维小变形梁结果。")
    coordinates = np.asarray(state.reference_coordinates, dtype=float)
    if coordinates.shape != (model.n_nodes, 3):
        raise ValueError("结果状态与原生模型节点数量不一致。")
    order = np.argsort(coordinates[:, 0], kind="stable")
    expected = np.column_stack((node_x, np.zeros((model.n_nodes, 2))))
    if not np.allclose(coordinates[order], expected, rtol=0.0, atol=1.0e-12):
        raise ValueError("结果状态参考坐标与原生模型不一致。")
    if not np.allclose(np.asarray(state.displacements)[order], displacement, rtol=1.0e-10, atol=1.0e-12):
        raise ValueError("结果状态位移与原生模型不一致。")
    if state.rotation_representation == "rotation_vector":
        expected_rotations = np.column_stack((np.zeros((model.n_nodes, 2)), phi))
        if not np.allclose(np.asarray(state.rotations)[order], expected_rotations, rtol=1.0e-10, atol=1.0e-12):
            raise ValueError("结果状态转角与原生模型不一致。")
    elif state.rotation_representation != "none":
        raise ValueError("当前梁结果适配器不支持此转角表示。")
    node_ids = tuple(state.node_ids[int(index)] for index in order)
    if len(state.element_ids) != model.n_elems:
        raise ValueError("结果状态与原生模型单元数量不一致。")
    by_pair = {}
    for identifier, connection in zip(state.element_ids, state.connectivity):
        if len(connection) != 2 or len(set(connection)) != 2:
            raise ValueError("结果状态必须具有二节点梁连接关系。")
        pair = frozenset(connection)
        if pair in by_pair:
            raise ValueError("结果状态存在重复梁连接关系。")
        by_pair[pair] = identifier
    try:
        element_ids = tuple(
            by_pair[frozenset((left, right))]
            for left, right in zip(node_ids, node_ids[1:])
        )
    except KeyError as exc:
        raise ValueError("结果状态连接关系与原生模型不一致。") from exc
    return node_ids, element_ids


def build_result_targets(model, inputs, state, field, sequence) -> dict[str, tuple[ResultTarget, ...]]:
    """Build immutable targets from a solved snapshot, never from live inputs.

    ``index`` is a zero-based native row index for nodes/queries/comparisons and
    the exact current field-array index for every sample, including duplicate
    raw boundary coordinates.  ``position`` is the unexaggerated reconstructed
    centerline position.  Display-space scaling belongs to the view adapter.
    """
    if isinstance(sequence, bool) or not isinstance(sequence, Integral) or sequence < 0:
        raise ValueError("结果快照序号必须为非负整数。")
    prefix = f"result:{int(sequence)}"
    node_x = _finite_array(model.node_x, (model.n_nodes,), "原生模型节点坐标")
    if model.n_nodes < 2 or model.n_elems != model.n_nodes - 1 or np.any(np.diff(node_x) <= 0):
        raise ValueError("当前结果联动适配器要求严格递增的直梁节点。")
    u, v, phi = (
        _finite_array(values, (model.n_nodes,), "原生模型节点结果")
        for values in model.nodal_results()
    )
    displacement = np.column_stack((u, v, np.zeros(model.n_nodes)))
    node_ids, element_ids = _state_identity(model, state, node_x, displacement, phi)
    has_project_identity = state is not None and bool(state.project_id)

    def element_at(x):
        if not np.isfinite(x) or not node_x[0] <= x <= node_x[-1]:
            raise ValueError("结果位置超出梁范围。")
        index = min(int(np.searchsorted(node_x, x, side="right")) - 1, model.n_elems - 1)
        return element_ids[index] if has_project_identity else None

    def at(kind, index, x, x_deformed, y_deformed, values, *, element_id=None,
           source_id="", key=None, representation=""):
        return ResultTarget(
            kind=kind,
            index=index,
            entity_id=f"{prefix}:{kind}:{index if key is None else key}",
            source_id=source_id,
            element_id=element_id,
            reference_position=(float(x), 0.0, 0.0),
            position=(float(x_deformed), float(y_deformed), 0.0),
            values=values,
            representation=representation,
        )

    node_targets = tuple(
        at(
            "node", index, x, x + u[index], v[index],
            (("u", u[index], "m"), ("v", v[index], "m"), ("φ", phi[index], "rad")),
            source_id=node_ids[index] if has_project_identity else "",
            key=node_ids[index] or index,
        )
        for index, x in enumerate(node_x)
    )
    query_targets = tuple(
        at(
            "query", index, row["x"], row["x"] + row["u"], row["v"],
            (("u", row["u"], "m"), ("v", row["v"], "m")),
            element_id=element_at(row["x"]),
        )
        for index, row in enumerate(model.evaluate_displacement_at_points(inputs.get("query_xs", ())))
    )
    compare_targets = tuple(
        at(
            "compare", index, row["x"], row["x"] + row["u_重构"], row["v_重构"],
            (
                ("u", row["u_重构"], "m"), ("v", row["v_重构"], "m"),
                ("u_实测", row["u_实测"], "m"), ("v_实测", row["v_实测"], "m"),
                ("Δu", row["Δu"], "m"), ("Δv", row["Δv"], "m"),
            ),
            element_id=element_at(row["x"]),
        )
        for index, row in enumerate(model.compare_true_points(inputs.get("true_points", ())))
    )
    sample_targets = []
    if field is not None:
        count = len(field.x_reference)
        representation = str(field.representation)
        if representation not in {"raw", "nodal_average"}:
            raise ValueError("未知截面场表示方式。")
        sample_x = _finite_array(field.x_reference, (count,), "截面场参考坐标")
        x_deformed = _finite_array(field.x_deformed, (count,), "截面场重构横坐标")
        y_deformed = _finite_array(field.y_deformed, (count,), "截面场重构纵坐标")
        elements = _finite_array(field.element_index, (count,), "截面场单元索引")
        if np.any(elements != np.floor(elements)) or np.any(elements < 0) or np.any(elements >= model.n_elems):
            raise ValueError("截面场单元索引超出原生模型范围。")
        top = _finite_array(field.top_strain, (count,), "截面场上表面应变")
        bottom = _finite_array(field.bottom_strain, (count,), "截面场下表面应变")
        stress_top = None if field.top_stress is None else _finite_array(field.top_stress, (count,), "截面场上表面应力")
        stress_bottom = None if field.bottom_stress is None else _finite_array(field.bottom_stress, (count,), "截面场下表面应力")
        ordinals = {}
        for index, x in enumerate(sample_x):
            element_index = int(elements[index])
            if x < node_x[element_index] - 1.0e-12 or x > node_x[element_index + 1] + 1.0e-12:
                raise ValueError("截面场采样位置与其单元不一致。")
            ordinal = ordinals.get(element_index, 0)
            ordinals[element_index] = ordinal + 1
            element_key = element_ids[element_index] or f"index-{element_index}"
            sample_targets.append(at(
                "sample", index, x, x_deformed[index], y_deformed[index],
                (
                    ("u", x_deformed[index] - x, "m"), ("v", y_deformed[index], "m"),
                    ("上表面应变", top[index] * 1.0e6, "με"),
                    ("下表面应变", bottom[index] * 1.0e6, "με"),
                    ("上表面应力", None if stress_top is None else stress_top[index] / 1.0e6, "MPa"),
                    ("下表面应力", None if stress_bottom is None else stress_bottom[index] / 1.0e6, "MPa"),
                ),
                element_id=element_ids[element_index] if has_project_identity else None,
                key=f"{representation}:{element_key}:{ordinal}",
                representation=representation,
            ))
    return {"node": node_targets, "query": query_targets, "compare": compare_targets, "sample": tuple(sample_targets)}
