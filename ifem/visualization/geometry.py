from __future__ import annotations

import numpy as np


def _unit_vector(vector, field_name: str) -> np.ndarray:
    values = np.asarray(tuple(vector), dtype=float)
    if values.shape != (3,) or not np.isfinite(values).all():
        raise ValueError(f"{field_name}必须包含三个有限坐标。")
    length = float(np.linalg.norm(values))
    if length <= 1.0e-12:
        raise ValueError(f"{field_name}不能为零向量。")
    return values / length


def bidirectional_axis_glyph(
    center,
    axis,
    lateral,
    length: float,
    *,
    head_length_ratio: float = 0.22,
    head_width_ratio: float = 0.10,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a double-headed axis glyph where ``axis`` and ``-axis`` are equal."""

    center = np.asarray(tuple(center), dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("测量轴中心必须包含三个有限坐标。")
    axis = _unit_vector(axis, "测量轴")
    lateral = _unit_vector(lateral, "测量轴横向")
    lateral = lateral - float(np.dot(lateral, axis)) * axis
    lateral = _unit_vector(lateral, "测量轴横向")
    length = float(length)
    if not np.isfinite(length) or length <= 0.0:
        raise ValueError("测量轴长度必须大于 0。")
    head_length = length * float(head_length_ratio)
    head_width = length * float(head_width_ratio)
    if not 0.0 < head_length < length * 0.5 or head_width <= 0.0:
        raise ValueError("测量轴箭头比例无效。")

    negative_tip = center - axis * length * 0.5
    positive_tip = center + axis * length * 0.5
    positive_base = positive_tip - axis * head_length
    negative_base = negative_tip + axis * head_length
    points = np.asarray(
        (
            negative_tip,
            positive_tip,
            positive_base + lateral * head_width,
            positive_base - lateral * head_width,
            negative_base + lateral * head_width,
            negative_base - lateral * head_width,
        ),
        dtype=float,
    )
    faces = np.asarray((3, 1, 2, 3, 3, 0, 4, 5), dtype=np.int64)
    lines = np.asarray((2, 0, 1), dtype=np.int64)
    return points, faces, lines


def oriented_surface_patch_glyph(
    center,
    axis,
    surface_normal,
    length: float,
    width: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build a surface patch whose long edge follows the measurement axis."""

    center = np.asarray(tuple(center), dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("测点贴片中心必须包含三个有限坐标。")
    surface_normal = _unit_vector(surface_normal, "测点表面法向")
    axis = _unit_vector(axis, "测量轴")
    axis = axis - float(np.dot(axis, surface_normal)) * surface_normal
    axis = _unit_vector(axis, "表面内测量轴")
    lateral = _unit_vector(np.cross(surface_normal, axis), "测点贴片短边")
    length = float(length)
    width = float(width)
    if not np.isfinite(length) or length <= 0.0:
        raise ValueError("测点贴片长度必须大于 0。")
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("测点贴片宽度必须大于 0。")

    half_length = length * 0.5
    half_width = width * 0.5
    points = np.asarray(
        (
            center - axis * half_length - lateral * half_width,
            center + axis * half_length - lateral * half_width,
            center + axis * half_length + lateral * half_width,
            center - axis * half_length + lateral * half_width,
        ),
        dtype=float,
    )
    faces = np.asarray((4, 0, 1, 2, 3), dtype=np.int64)
    return points, faces, axis, lateral
