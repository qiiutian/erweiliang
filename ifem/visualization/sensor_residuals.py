"""Sensor diagnostics from the solved field snapshot, never from edited input."""

from math import hypot, isclose, sqrt

from ifem.domain.result_fields import map_result_field
from ifem.visualization.result_link import ResultTarget


def sensor_residual_data(result, sequence=0):
    identifiers = ("sensor_measured_strain", "sensor_reconstructed_strain", "sensor_strain_residual")
    if result is None or not all(identifier in result.fields for identifier in identifiers):
        return [], (), "当前方法未提供测点应变残差。"
    try:
        layers = [map_result_field(result, identifier) for identifier in identifiers]
    except (TypeError, ValueError, KeyError) as exc:
        return [], (), f"测点残差暂不可用：{exc}"
    if len({layer.coordinate_system for layer in layers}) != 1:
        return [], (), "测点残差暂不可用：三个字段的坐标系不一致。"
    measured, predicted, residual = [{record.entity_id: record for record in layer.records} for layer in layers]
    if set(measured) != set(predicted) or set(measured) != set(residual):
        return [], (), "测点残差暂不可用：观测、重构和残差的实体 ID 不一致。"
    if any(not isclose(residual[key].values[0], predicted[key].values[0] - measured[key].values[0],
                       rel_tol=1.0e-9, abs_tol=1.0e-12) for key in residual):
        return [], (), "测点残差暂不可用：字段值不满足“重构 − 观测”，未进行误导性汇总。"
    rows, targets, values = [], [], []
    for index, (identifier, record) in enumerate(residual.items()):
        observed = measured[identifier].values[0] * 1.0e6
        reconstructed = predicted[identifier].values[0] * 1.0e6
        difference = record.values[0] * 1.0e6
        label = record.label or identifier
        values.append(difference)
        rows.append({"测点": label, "x": record.reference_position[0], "观测": observed,
                     "重构": reconstructed, "残差": difference, "_result_index": index})
        targets.append(ResultTarget(
            kind="sensor", index=index, entity_id=f"result-{sequence}:sensor:{identifier}",
            element_id=record.source_entity_id, reference_position=record.reference_position,
            position=record.position, values=(("观测", observed, "με"), ("重构", reconstructed, "με"), ("残差", difference, "με")),
            representation="raw", source_id=identifier,
        ))
    if not values:
        summary = "无已观测测点；未将缺失应变视为零。"
    else:
        summary = (f"{len(values)} 个测点 · RMS {hypot(*values) / sqrt(len(values)):.5g} με"
                   f" · 最大 |残差| {max(abs(value) for value in values):.5g} με")
    return rows, tuple(targets), summary
