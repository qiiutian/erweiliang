from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians, sin
from typing import Iterable

import numpy as np

from ifem.domain.project import SectionDefinition


@dataclass(frozen=True)
class SectionParameterSpec:
    key: str
    label: str


@dataclass(frozen=True)
class SectionBoundaryPoint:
    distance: float
    local_position: tuple[float, float]
    outward_normal: tuple[float, float]
    boundary_tangent: tuple[float, float]


SECTION_SHAPE_LABELS = {
    "rectangle": "矩形",
    "circle": "实心圆",
    "circular_tube": "圆管",
    "box": "矩形管",
    "i_section": "工字形",
}

SECTION_PARAMETER_SPECS = {
    "rectangle": (
        SectionParameterSpec("height", "截面高度 h (m)"),
        SectionParameterSpec("width", "截面宽度 b (m)"),
    ),
    "circle": (SectionParameterSpec("diameter", "直径 d (m)"),),
    "circular_tube": (
        SectionParameterSpec("outer_diameter", "外径 D (m)"),
        SectionParameterSpec("wall_thickness", "壁厚 t (m)"),
    ),
    "box": (
        SectionParameterSpec("outer_height", "外高 H (m)"),
        SectionParameterSpec("outer_width", "外宽 B (m)"),
        SectionParameterSpec("wall_thickness", "壁厚 t (m)"),
    ),
    "i_section": (
        SectionParameterSpec("height", "截面高度 H (m)"),
        SectionParameterSpec("flange_width", "翼缘宽度 B (m)"),
        SectionParameterSpec("flange_thickness", "翼缘厚度 tf (m)"),
        SectionParameterSpec("web_thickness", "腹板厚度 tw (m)"),
    ),
}


def section_shape_label(shape: str) -> str:
    return SECTION_SHAPE_LABELS.get(str(shape), str(shape))


def default_section_parameters(
    shape: str,
    *,
    height: float = 0.1,
    width: float | None = None,
) -> dict[str, float]:
    height = max(float(height), 1.0e-9)
    width = height if width is None else max(float(width), 1.0e-9)
    smaller = min(height, width)
    defaults = {
        "rectangle": {"height": height, "width": width},
        "circle": {"diameter": height},
        "circular_tube": {
            "outer_diameter": height,
            "wall_thickness": height * 0.1,
        },
        "box": {
            "outer_height": height,
            "outer_width": width,
            "wall_thickness": smaller * 0.1,
        },
        "i_section": {
            "height": height,
            "flange_width": width,
            "flange_thickness": height * 0.12,
            "web_thickness": width * 0.12,
        },
    }
    try:
        return defaults[str(shape)]
    except KeyError as exc:
        raise ValueError(f"暂不支持的截面类型：{shape}") from exc


def _circle(radius: float, resolution: int) -> np.ndarray:
    count = max(int(resolution), 12)
    angles = np.linspace(0.0, 2.0 * pi, count, endpoint=False)
    return np.column_stack((radius * np.cos(angles), radius * np.sin(angles)))


def section_profile_loops(
    section: SectionDefinition,
    *,
    resolution: int = 32,
) -> tuple[np.ndarray, ...]:
    """Return closed profile boundaries without repeating their first point.

    Profile coordinates are ``(u, v)`` where ``u`` follows the section's local
    height/normal axis and ``v`` follows its local width/binormal axis.
    """

    parameters = section.parameters
    shape = section.shape
    if shape == "rectangle":
        half_h = parameters["height"] * 0.5
        half_b = parameters["width"] * 0.5
        outer = np.asarray(
            (
                (-half_h, -half_b),
                (half_h, -half_b),
                (half_h, half_b),
                (-half_h, half_b),
            ),
            dtype=float,
        )
        return (outer,)
    if shape == "circle":
        return (_circle(parameters["diameter"] * 0.5, resolution),)
    if shape == "circular_tube":
        outer_radius = parameters["outer_diameter"] * 0.5
        inner_radius = outer_radius - parameters["wall_thickness"]
        return (
            _circle(outer_radius, resolution),
            _circle(inner_radius, resolution),
        )
    if shape == "box":
        half_h = parameters["outer_height"] * 0.5
        half_b = parameters["outer_width"] * 0.5
        wall = parameters["wall_thickness"]
        outer = np.asarray(
            (
                (-half_h, -half_b),
                (half_h, -half_b),
                (half_h, half_b),
                (-half_h, half_b),
            ),
            dtype=float,
        )
        inner = np.asarray(
            (
                (-half_h + wall, -half_b + wall),
                (half_h - wall, -half_b + wall),
                (half_h - wall, half_b - wall),
                (-half_h + wall, half_b - wall),
            ),
            dtype=float,
        )
        return outer, inner
    if shape == "i_section":
        half_h = parameters["height"] * 0.5
        half_b = parameters["flange_width"] * 0.5
        half_web = parameters["web_thickness"] * 0.5
        flange = parameters["flange_thickness"]
        outer = np.asarray(
            (
                (-half_h, -half_b),
                (-half_h, half_b),
                (-half_h + flange, half_b),
                (-half_h + flange, half_web),
                (half_h - flange, half_web),
                (half_h - flange, half_b),
                (half_h, half_b),
                (half_h, -half_b),
                (half_h - flange, -half_b),
                (half_h - flange, -half_web),
                (-half_h + flange, -half_web),
                (-half_h + flange, -half_b),
            ),
            dtype=float,
        )
        return (outer[::-1].copy(),)
    raise ValueError(f"暂不支持的截面类型：{shape}")


def section_boundary_point(
    section: SectionDefinition,
    angle_degrees: float,
) -> SectionBoundaryPoint:
    """Intersect a radial placement ray with the actual outer profile."""
    angle = radians(float(angle_degrees))
    direction = np.asarray((cos(angle), sin(angle)), dtype=float)
    if section.shape in {"circle", "circular_tube"}:
        diameter_key = "diameter" if section.shape == "circle" else "outer_diameter"
        distance = float(section.parameters[diameter_key]) * 0.5
        tangent = np.asarray((-direction[1], direction[0]), dtype=float)
        position = direction * distance
        return SectionBoundaryPoint(
            distance=distance,
            local_position=(float(position[0]), float(position[1])),
            outward_normal=(float(direction[0]), float(direction[1])),
            boundary_tangent=(float(tangent[0]), float(tangent[1])),
        )
    outer = section_profile_loops(section)[0]
    intersections = []
    for point_a, point_b in zip(outer, np.roll(outer, -1, axis=0)):
        edge = point_b - point_a
        denominator = direction[0] * edge[1] - direction[1] * edge[0]
        if abs(float(denominator)) <= 1.0e-12:
            continue
        distance = (point_a[0] * edge[1] - point_a[1] * edge[0]) / denominator
        segment_parameter = (
            point_a[0] * direction[1] - point_a[1] * direction[0]
        ) / denominator
        if distance >= -1.0e-12 and -1.0e-12 <= segment_parameter <= 1.0 + 1.0e-12:
            edge_length = float(np.linalg.norm(edge))
            if edge_length <= 1.0e-12:
                continue
            outward = np.asarray((edge[1], -edge[0]), dtype=float) / edge_length
            if float(np.dot(outward, direction)) < 0.0:
                outward *= -1.0
            tangent = np.asarray((-outward[1], outward[0]), dtype=float)
            intersections.append(
                (
                    max(0.0, float(distance)),
                    outward,
                    tangent,
                )
            )
    if not intersections:
        raise ValueError("无法确定测点与截面外轮廓的交点。")
    distance, outward, tangent = min(
        (item for item in intersections if item[0] > 1.0e-12),
        key=lambda item: item[0],
    )
    position = direction * distance
    return SectionBoundaryPoint(
        distance=distance,
        local_position=(float(position[0]), float(position[1])),
        outward_normal=(float(outward[0]), float(outward[1])),
        boundary_tangent=(float(tangent[0]), float(tangent[1])),
    )


def section_outer_radius(section: SectionDefinition, angle_degrees: float) -> float:
    """Distance from the section origin to its outer boundary along a ray."""

    return section_boundary_point(section, angle_degrees).distance


def section_max_dimension(section: SectionDefinition) -> float:
    return max(float(section.thickness), float(section.width or section.thickness))


def sweep_section_mesh(
    center_points: Iterable[Iterable[float]],
    normal_vectors: Iterable[Iterable[float]],
    binormal_vectors: Iterable[Iterable[float]],
    section: SectionDefinition,
    *,
    display_scale: float = 1.0,
    resolution: int = 32,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a polygonal sweep mesh for a uniform cross-section."""

    centers = np.asarray(tuple(center_points), dtype=float)
    normals = np.asarray(tuple(normal_vectors), dtype=float)
    binormals = np.asarray(tuple(binormal_vectors), dtype=float)
    if centers.ndim != 2 or centers.shape[1] != 3 or len(centers) < 2:
        raise ValueError("截面扫掠至少需要两个三维路径点。")
    if normals.shape != centers.shape or binormals.shape != centers.shape:
        raise ValueError("路径点与截面局部坐标系数量不一致。")
    scale = float(display_scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("截面显示倍率必须大于 0。")

    loops = section_profile_loops(section, resolution=resolution)
    point_blocks = []
    faces: list[int] = []
    loop_offsets = []
    point_offset = 0
    for loop in loops:
        transformed = (
            centers[:, None, :]
            + normals[:, None, :] * loop[None, :, 0, None] * scale
            + binormals[:, None, :] * loop[None, :, 1, None] * scale
        )
        point_blocks.append(transformed.reshape(-1, 3))
        loop_offsets.append(point_offset)
        profile_count = len(loop)
        for station in range(len(centers) - 1):
            first = point_offset + station * profile_count
            following = first + profile_count
            for profile_index in range(profile_count):
                next_index = (profile_index + 1) % profile_count
                faces.extend(
                    (
                        4,
                        first + profile_index,
                        following + profile_index,
                        following + next_index,
                        first + next_index,
                    )
                )
        point_offset += len(centers) * profile_count

    if len(loops) == 1:
        profile_count = len(loops[0])
        start = loop_offsets[0]
        end = start + (len(centers) - 1) * profile_count
        faces.extend((profile_count, *reversed(range(start, start + profile_count))))
        faces.extend((profile_count, *range(end, end + profile_count)))
    elif len(loops) == 2 and len(loops[0]) == len(loops[1]):
        profile_count = len(loops[0])
        outer_start, inner_start = loop_offsets
        outer_end = outer_start + (len(centers) - 1) * profile_count
        inner_end = inner_start + (len(centers) - 1) * profile_count
        for index in range(profile_count):
            following = (index + 1) % profile_count
            faces.extend(
                (
                    4,
                    outer_start + following,
                    outer_start + index,
                    inner_start + index,
                    inner_start + following,
                )
            )
            faces.extend(
                (
                    4,
                    outer_end + index,
                    outer_end + following,
                    inner_end + following,
                    inner_end + index,
                )
            )

    return np.vstack(point_blocks), np.asarray(faces, dtype=np.int64)
