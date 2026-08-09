"""Validation helpers for the supported algorithm-parameter schema subset."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import Any

from ifem.domain.analysis import ValidationIssue, ValidationReport


SUPPORTED_PARAMETER_TYPES = frozenset({"boolean", "integer", "number", "string"})


def _json_pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def parameter_field(name: object) -> str:
    return f"/analysis/parameters/{_json_pointer_token(name)}"


def _is_value_of_type(value: Any, value_type: str) -> bool:
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "integer":
        return isinstance(value, Integral) and not isinstance(value, bool)
    if value_type == "number":
        return isinstance(value, Real) and not isinstance(value, bool)
    if value_type == "string":
        return isinstance(value, str)
    return False


def _is_finite_number(value: Any) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    if isinstance(value, Integral):
        return True
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _validate_property_schema(name: str, schema: Mapping[str, Any]):
    value_type = str(schema.get("type", "string"))
    if value_type not in SUPPORTED_PARAMETER_TYPES:
        supported = "、".join(sorted(SUPPORTED_PARAMETER_TYPES))
        raise ValueError(f"参数 {name} 的 type 必须是 {supported} 之一。")

    enum_values = schema.get("enum")
    if enum_values is not None:
        if (
            not isinstance(enum_values, Sequence)
            or isinstance(enum_values, (str, bytes))
            or not enum_values
        ):
            raise ValueError(f"参数 {name} 的 enum 必须是非空列表。")
        if any(not _is_value_of_type(value, value_type) for value in enum_values):
            raise TypeError(f"参数 {name} 的 enum 值与 type 不一致。")
        if value_type == "number" and any(
            not _is_finite_number(value) for value in enum_values
        ):
            raise ValueError(f"参数 {name} 的 enum 只能包含有限数值。")

    if value_type not in {"integer", "number"} and any(
        bound_name in schema for bound_name in ("minimum", "maximum")
    ):
        raise ValueError(f"参数 {name} 只有数值类型可声明 minimum/maximum。")
    for bound_name in ("minimum", "maximum"):
        if bound_name not in schema:
            continue
        bound = schema[bound_name]
        if not isinstance(bound, Real) or isinstance(bound, bool):
            raise TypeError(f"参数 {name} 的 {bound_name} 必须是数值。")
        if not _is_finite_number(bound):
            raise ValueError(f"参数 {name} 的 {bound_name} 必须是有限数值。")
    if (
        "minimum" in schema
        and "maximum" in schema
        and schema["maximum"] < schema["minimum"]
    ):
        raise ValueError(f"参数 {name} 的 maximum 不能小于 minimum。")

    if "default" in schema:
        default = schema["default"]
        if not _is_value_of_type(default, value_type):
            raise TypeError(f"参数 {name} 的 default 与 type 不一致。")
        if value_type == "number" and not _is_finite_number(default):
            raise ValueError(f"参数 {name} 的 default 必须是有限数值。")
        if enum_values is not None and default not in enum_values:
            raise ValueError(f"参数 {name} 的 default 不在 enum 中。")
        if "minimum" in schema and default < schema["minimum"]:
            raise ValueError(f"参数 {name} 的 default 小于 minimum。")
        if "maximum" in schema and default > schema["maximum"]:
            raise ValueError(f"参数 {name} 的 default 大于 maximum。")


def validate_parameter_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and snapshot the JSON-schema subset understood by the app."""
    if not isinstance(schema, Mapping):
        raise TypeError("算法 parameter_schema() 必须返回映射。")
    if schema.get("type", "object") != "object":
        raise ValueError("算法参数模式的顶层 type 必须是 object。")

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypeError("算法参数模式的 properties 必须是映射。")
    for name, property_schema in properties.items():
        if not isinstance(name, str) or not name:
            raise ValueError("算法参数名称必须是非空字符串。")
        if not isinstance(property_schema, Mapping):
            raise TypeError(f"参数 {name} 的模式必须是映射。")
        _validate_property_schema(name, property_schema)

    required = schema.get("required", ())
    if isinstance(required, (str, bytes)) or not isinstance(required, Sequence):
        raise TypeError("算法参数模式的 required 必须是字符串列表。")
    if any(not isinstance(name, str) or not name for name in required):
        raise ValueError("算法参数模式的 required 只能包含非空字符串。")
    unknown_required = sorted(set(required) - set(properties))
    if unknown_required:
        raise ValueError(
            "算法参数模式的 required 引用了未声明参数："
            + "、".join(unknown_required)
        )
    return copy.deepcopy(dict(schema))


def validate_parameters(
    schema: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> ValidationReport:
    """Validate values without dropping parameters unknown to the current schema."""
    if not isinstance(parameters, Mapping):
        return ValidationReport.invalid(
            "算法参数必须是映射。",
            field="/analysis/parameters",
        )

    properties = schema.get("properties", {})
    issues = []
    for name in schema.get("required", ()):
        if name not in parameters:
            issues.append(
                ValidationIssue(
                    f"缺少必需的算法参数：{name}。",
                    field=parameter_field(name),
                )
            )

    for name, value in parameters.items():
        property_schema = properties.get(name)
        if property_schema is None:
            continue
        value_type = str(property_schema.get("type", "string"))
        field = parameter_field(name)
        if not _is_value_of_type(value, value_type):
            issues.append(
                ValidationIssue(
                    f"算法参数 {name} 的值类型应为 {value_type}。",
                    field=field,
                )
            )
            continue
        if value_type == "number" and not _is_finite_number(value):
            issues.append(
                ValidationIssue(
                    f"算法参数 {name} 必须是有限数值。",
                    field=field,
                )
            )
            continue

        enum_values = property_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            issues.append(
                ValidationIssue(
                    f"算法参数 {name} 必须是 {list(enum_values)} 之一。",
                    field=field,
                )
            )
        if "minimum" in property_schema and value < property_schema["minimum"]:
            issues.append(
                ValidationIssue(
                    f"算法参数 {name} 不能小于 {property_schema['minimum']}。",
                    field=field,
                )
            )
        if "maximum" in property_schema and value > property_schema["maximum"]:
            issues.append(
                ValidationIssue(
                    f"算法参数 {name} 不能大于 {property_schema['maximum']}。",
                    field=field,
                )
            )
    return ValidationReport(tuple(issues))


__all__ = [
    "SUPPORTED_PARAMETER_TYPES",
    "parameter_field",
    "validate_parameter_schema",
    "validate_parameters",
]
