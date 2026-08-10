"""Compatibility exports for the domain-level parametric curve kernel."""

from ifem.domain.parametric_curves import (
    clamped_uniform_knots,
    nurbs_arc_length,
    nurbs_parameter_at_arc_length,
    nurbs_point_and_derivative,
    validate_nurbs_regularity,
)

__all__ = [
    "clamped_uniform_knots",
    "nurbs_arc_length",
    "nurbs_parameter_at_arc_length",
    "nurbs_point_and_derivative",
    "validate_nurbs_regularity",
]
