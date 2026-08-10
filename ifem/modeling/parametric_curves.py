"""Evaluation utilities for algorithm-independent parametric beam curves."""

from __future__ import annotations

from functools import lru_cache
from math import isfinite, sqrt
from typing import Mapping


_GAUSS_NODES = (
    -0.9602898564975363,
    -0.7966664774136267,
    -0.5255324099163290,
    -0.1834346424956498,
    0.1834346424956498,
    0.5255324099163290,
    0.7966664774136267,
    0.9602898564975363,
)
_GAUSS_WEIGHTS = (
    0.1012285362903763,
    0.2223810344533745,
    0.3137066458778873,
    0.3626837833783620,
    0.3626837833783620,
    0.3137066458778873,
    0.2223810344533745,
    0.1012285362903763,
)


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
    weights = tuple(float(value) for value in parameters["weights"])
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
        parameter = domain_end - max(abs(domain_span), 1.0) * 1.0e-13
    else:
        parameter = domain_start + xi * domain_span
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

    degree, _points, _weights, knots = _curve_data(parameters)
    domain_start = knots[degree]
    domain_end = knots[-degree - 1]
    domain_span = domain_end - domain_start
    breakpoints = {left, right}
    for knot in knots[degree : -degree]:
        xi = (knot - domain_start) / domain_span
        if left < xi < right:
            breakpoints.add(float(xi))
    ordered = sorted(breakpoints)
    length = 0.0
    for segment_start, segment_end in zip(ordered, ordered[1:]):
        midpoint = 0.5 * (segment_start + segment_end)
        half_span = 0.5 * (segment_end - segment_start)
        for node, weight in zip(_GAUSS_NODES, _GAUSS_WEIGHTS):
            xi = midpoint + half_span * node
            _point, derivative = nurbs_point_and_derivative(parameters, xi)
            speed = sqrt(sum(value * value for value in derivative))
            length += half_span * weight * speed
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
]
