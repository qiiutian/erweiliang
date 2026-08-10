"""Pure geometry utilities for algorithm-independent parametric beam curves."""

from __future__ import annotations

from functools import lru_cache
from math import isfinite, nextafter, sqrt
from typing import Mapping


def clamped_uniform_knots(control_count: int, degree: int) -> tuple[float, ...]:
    control_count = int(control_count)
    degree = int(degree)
    if control_count < 2 or not 1 <= degree < control_count:
        raise ValueError("NURBS 次数必须是小于控制点数量的正整数。")
    internal_count = control_count - degree - 1
    return (
        (0.0,) * (degree + 1)
        + tuple(
            index / (internal_count + 1)
            for index in range(1, internal_count + 1)
        )
        + (1.0,) * (degree + 1)
    )


def _curve_data(parameters: Mapping):
    degree = int(parameters["degree"])
    points = tuple(
        tuple(float(value) for value in point)
        for point in parameters["control_points"]
    )
    raw_weights = tuple(float(value) for value in parameters["weights"])
    weight_scale = max(raw_weights)
    weights = tuple(value / weight_scale for value in raw_weights)
    knots = tuple(float(value) for value in parameters["knots"])
    return degree, points, weights, knots


def _basis_and_derivatives(
    control_count: int,
    degree: int,
    knots: tuple[float, ...],
    parameter: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    @lru_cache(maxsize=None)
    def basis(index: int, order: int) -> float:
        if index < 0 or index + order + 1 >= len(knots):
            return 0.0
        if order == 0:
            return 1.0 if knots[index] <= parameter < knots[index + 1] else 0.0
        left_denominator = knots[index + order] - knots[index]
        right_denominator = knots[index + order + 1] - knots[index + 1]
        left = (
            0.0
            if abs(left_denominator) <= 1.0e-15
            else (parameter - knots[index])
            / left_denominator
            * basis(index, order - 1)
        )
        right = (
            0.0
            if abs(right_denominator) <= 1.0e-15
            else (knots[index + order + 1] - parameter)
            / right_denominator
            * basis(index + 1, order - 1)
        )
        return left + right

    values = tuple(basis(index, degree) for index in range(control_count))
    derivatives = []
    for index in range(control_count):
        left_denominator = knots[index + degree] - knots[index]
        right_denominator = knots[index + degree + 1] - knots[index + 1]
        left = (
            0.0
            if abs(left_denominator) <= 1.0e-15
            else degree / left_denominator * basis(index, degree - 1)
        )
        right = (
            0.0
            if abs(right_denominator) <= 1.0e-15
            else degree / right_denominator * basis(index + 1, degree - 1)
        )
        derivatives.append(left - right)
    return values, tuple(derivatives)


def nurbs_point_and_derivative(
    parameters: Mapping,
    local_coordinate: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    degree, points, weights, knots = _curve_data(parameters)
    xi = float(local_coordinate)
    if not isfinite(xi) or not 0.0 <= xi <= 1.0:
        raise ValueError("NURBS 局部坐标必须位于 [0, 1]。")
    domain_start = knots[degree]
    domain_end = knots[-degree - 1]
    domain_span = domain_end - domain_start
    if xi >= 1.0:
        parameter = nextafter(domain_end, domain_start)
    else:
        parameter = domain_start + xi * domain_span
        if parameter >= domain_end:
            parameter = nextafter(domain_end, domain_start)
    basis, derivatives = _basis_and_derivatives(
        len(points),
        degree,
        knots,
        parameter,
    )
    denominator = sum(value * weight for value, weight in zip(basis, weights))
    derivative_denominator = sum(
        value * weight for value, weight in zip(derivatives, weights)
    )
    if abs(denominator) <= 1.0e-15:
        raise ValueError("NURBS 权重组合在当前参数处退化。")
    numerator = tuple(
        sum(
            value * weight * point[axis]
            for value, weight, point in zip(basis, weights, points)
        )
        for axis in range(3)
    )
    derivative_numerator = tuple(
        sum(
            value * weight * point[axis]
            for value, weight, point in zip(derivatives, weights, points)
        )
        for axis in range(3)
    )
    evaluated = tuple(value / denominator for value in numerator)
    derivative = tuple(
        domain_span
        * (derivative_value * denominator - value * derivative_denominator)
        / (denominator * denominator)
        for value, derivative_value in zip(numerator, derivative_numerator)
    )
    if xi >= 1.0:
        evaluated = points[-1]
    elif xi <= 0.0:
        evaluated = points[0]
    return evaluated, derivative


def _nurbs_speed(parameters: Mapping, local_coordinate: float) -> float:
    _point, derivative = nurbs_point_and_derivative(parameters, local_coordinate)
    return sqrt(sum(value * value for value in derivative))


def validate_nurbs_regularity(parameters: Mapping) -> None:
    """Reject curves with a zero-speed cusp before sweep or arc-length use."""

    degree, points, _weights, knots = _curve_data(parameters)
    coordinate_ranges = tuple(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )
    geometry_scale = sqrt(sum(value * value for value in coordinate_ranges))
    if geometry_scale <= 0.0:
        raise ValueError("NURBS 控制点不能全部重合。")
    speed_tolerance = geometry_scale * 1.0e-12

    domain_start = knots[degree]
    domain_end = knots[-degree - 1]
    domain_span = domain_end - domain_start
    breakpoints = [domain_start]
    for knot in knots[degree + 1 : -degree - 1]:
        if knot > breakpoints[-1] and knot < domain_end:
            breakpoints.append(knot)
    breakpoints.append(domain_end)
    xi_breakpoints = [
        (value - domain_start) / domain_span for value in breakpoints
    ]

    for span_start, span_end in zip(xi_breakpoints, xi_breakpoints[1:]):
        sample_count = max(17, degree * 8 + 1)
        coordinates = [
            (
                nextafter(span_end, span_start)
                if index == sample_count - 1
                else span_start
                + (span_end - span_start) * index / (sample_count - 1)
            )
            for index in range(sample_count)
        ]
        speeds = [_nurbs_speed(parameters, value) for value in coordinates]
        if min(speeds) <= speed_tolerance:
            raise ValueError("NURBS 曲线存在零速点或尖点，无法建立稳定局部标架。")

        for index in range(1, sample_count - 1):
            if speeds[index] > min(speeds[index - 1], speeds[index + 1]):
                continue
            left = coordinates[index - 1]
            right = coordinates[index + 1]
            for _iteration in range(40):
                first = (2.0 * left + right) / 3.0
                second = (left + 2.0 * right) / 3.0
                if _nurbs_speed(parameters, first) <= _nurbs_speed(parameters, second):
                    right = second
                else:
                    left = first
            if _nurbs_speed(parameters, 0.5 * (left + right)) <= speed_tolerance:
                raise ValueError(
                    "NURBS 曲线存在零速点或尖点，无法建立稳定局部标架。"
                )


def _simpson_estimate(
    start: float,
    end: float,
    start_speed: float,
    midpoint_speed: float,
    end_speed: float,
) -> float:
    return (end - start) * (
        start_speed + 4.0 * midpoint_speed + end_speed
    ) / 6.0


def _adaptive_simpson_length(
    parameters: Mapping,
    start: float,
    end: float,
    start_speed: float,
    midpoint_speed: float,
    end_speed: float,
    whole: float,
    *,
    tolerance: float,
    depth: int,
) -> float:
    midpoint = 0.5 * (start + end)
    left_midpoint = 0.5 * (start + midpoint)
    right_midpoint = 0.5 * (midpoint + end)
    left_midpoint_speed = _nurbs_speed(parameters, left_midpoint)
    right_midpoint_speed = _nurbs_speed(parameters, right_midpoint)
    left = _simpson_estimate(
        start,
        midpoint,
        start_speed,
        left_midpoint_speed,
        midpoint_speed,
    )
    right = _simpson_estimate(
        midpoint,
        end,
        midpoint_speed,
        right_midpoint_speed,
        end_speed,
    )
    refined = left + right
    error = abs(refined - whole)
    if error <= 15.0 * tolerance:
        return refined + (refined - whole) / 15.0
    if depth <= 0:
        raise ValueError("NURBS 弧长自适应积分未收敛。")
    return _adaptive_simpson_length(
        parameters,
        start,
        midpoint,
        start_speed,
        left_midpoint_speed,
        midpoint_speed,
        left,
        tolerance=tolerance * 0.5,
        depth=depth - 1,
    ) + _adaptive_simpson_length(
        parameters,
        midpoint,
        end,
        midpoint_speed,
        right_midpoint_speed,
        end_speed,
        right,
        tolerance=tolerance * 0.5,
        depth=depth - 1,
    )


def nurbs_arc_length(
    parameters: Mapping,
    start: float = 0.0,
    end: float = 1.0,
) -> float:
    left = float(start)
    right = float(end)
    if not all(isfinite(value) and 0.0 <= value <= 1.0 for value in (left, right)):
        raise ValueError("NURBS 弧长积分区间必须位于 [0, 1]。")
    if right < left:
        left, right = right, left
    if right - left <= 1.0e-15:
        return 0.0

    degree, points, _weights, knots = _curve_data(parameters)
    domain_start = knots[degree]
    domain_end = knots[-degree - 1]
    domain_span = domain_end - domain_start
    breakpoints = {left, right}
    for knot in knots[degree : -degree]:
        xi = (knot - domain_start) / domain_span
        if left < xi < right:
            breakpoints.add(float(xi))
    ordered = sorted(breakpoints)
    coordinate_ranges = tuple(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )
    geometry_scale = max(
        sqrt(sum(value * value for value in coordinate_ranges)),
        1.0e-300,
    )
    length = 0.0
    for segment_start, segment_end in zip(ordered, ordered[1:]):
        midpoint = 0.5 * (segment_start + segment_end)
        start_speed = _nurbs_speed(parameters, segment_start)
        midpoint_speed = _nurbs_speed(parameters, midpoint)
        end_speed = _nurbs_speed(
            parameters,
            nextafter(segment_end, segment_start),
        )
        whole = _simpson_estimate(
            segment_start,
            segment_end,
            start_speed,
            midpoint_speed,
            end_speed,
        )
        length += _adaptive_simpson_length(
            parameters,
            segment_start,
            segment_end,
            start_speed,
            midpoint_speed,
            end_speed,
            whole,
            tolerance=geometry_scale * 1.0e-10,
            depth=60,
        )
    return float(length)


def nurbs_parameter_at_arc_length(
    parameters: Mapping,
    distance: float,
) -> float:
    total = nurbs_arc_length(parameters)
    target = float(distance)
    tolerance = max(total, 1.0) * 1.0e-11
    if not isfinite(target) or target < -tolerance or target > total + tolerance:
        raise ValueError(f"NURBS 局部弧长必须位于 [0, {total:.8g}]。")
    target = min(total, max(0.0, target))
    if target <= tolerance:
        return 0.0
    if total - target <= tolerance:
        return 1.0
    low = 0.0
    high = 1.0
    for _iteration in range(48):
        middle = 0.5 * (low + high)
        current = nurbs_arc_length(parameters, 0.0, middle)
        if current < target:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


__all__ = [
    "clamped_uniform_knots",
    "nurbs_arc_length",
    "nurbs_parameter_at_arc_length",
    "nurbs_point_and_derivative",
    "validate_nurbs_regularity",
]
