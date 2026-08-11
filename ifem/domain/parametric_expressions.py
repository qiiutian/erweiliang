"""Safe analytic parameter-curve evaluation for project geometry."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from math import ceil, cos, e, isfinite, pi, sin, sqrt
import re
from typing import Mapping


_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_EXPRESSION_LENGTH = 256
_MAX_AST_NODES = 64
_MAX_AST_DEPTH = 16
_MAX_CONSTANTS = 32
_MAX_POWER = 16
_MAX_TRIG_CYCLES = 32.0
_MAX_TRIG_PHASE_RATE = 2.0 * pi * _MAX_TRIG_CYCLES
_MIN_RENDER_TANGENT_ALIGNMENT = cos(pi / 12.0)
_MIN_VALID_TANGENT_ALIGNMENT = cos(pi / 6.0)
_COORDINATE_NAMES = ("x", "y", "z")
_CONSTANT_VALUES = {"pi": pi, "e": e}
_FUNCTION_NAMES = {"sin", "cos"}
_RESERVED_NAMES = {"t", *_CONSTANT_VALUES, *_FUNCTION_NAMES}
PARAMETRIC_EXPRESSION_LANGUAGE = "ifem-math-v1"
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


@dataclass(frozen=True)
class _Dual:
    value: float
    derivative: float


def _finite_dual(value: float, derivative: float, *, source: str) -> _Dual:
    value = float(value)
    derivative = float(derivative)
    if not isfinite(value) or not isfinite(derivative):
        raise ValueError(f"参数表达式产生了非有限数值：{source}")
    return _Dual(value, derivative)


def _depends_on_parameter(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Name) and item.id == "t"
        for item in ast.walk(node)
    )


def _validate_ast(node: ast.AST, *, allowed_names: set[str], depth: int = 0) -> int:
    if depth > _MAX_AST_DEPTH:
        raise ValueError("参数表达式嵌套过深。")
    if isinstance(node, ast.Expression):
        return 1 + _validate_ast(node.body, allowed_names=allowed_names, depth=depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("参数表达式只允许有限数值常量。")
        try:
            numeric_value = float(node.value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("参数表达式只允许有限数值常量。") from exc
        if not isfinite(numeric_value):
            raise ValueError("参数表达式只允许有限数值常量。")
        return 1
    if isinstance(node, ast.Name):
        if node.id not in allowed_names:
            raise ValueError(f"参数表达式包含未知名称：{node.id}")
        return 1
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return 1 + _validate_ast(node.operand, allowed_names=allowed_names, depth=depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(
        node.op,
        (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow),
    ):
        if isinstance(node.op, ast.Div) and _depends_on_parameter(node.right):
            raise ValueError("ifem-math-v1 只允许除以不依赖 t 的常量表达式。")
        if isinstance(node.op, ast.Pow) and _depends_on_parameter(node.right):
            raise ValueError("ifem-math-v1 的幂指数不能依赖 t。")
        return (
            1
            + _validate_ast(node.left, allowed_names=allowed_names, depth=depth + 1)
            + _validate_ast(node.right, allowed_names=allowed_names, depth=depth + 1)
        )
    if isinstance(node, ast.Call):
        if (
            not isinstance(node.func, ast.Name)
            or node.func.id not in _FUNCTION_NAMES
            or node.keywords
            or len(node.args) != 1
        ):
            raise ValueError("参数表达式只允许白名单中的单参数数学函数。")
        return 1 + _validate_ast(node.args[0], allowed_names=allowed_names, depth=depth + 1)
    raise ValueError("参数表达式包含不允许的语法。")


@lru_cache(maxsize=256)
def _compile_expression(source: str, constant_names: tuple[str, ...]) -> ast.AST:
    text = str(source).strip()
    if not text:
        raise ValueError("参数表达式不能为空。")
    if len(text) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("参数表达式长度不能超过 256 个字符。")
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"参数表达式语法错误：{exc.msg}") from exc
    count = _validate_ast(
        parsed,
        allowed_names={"t", *_CONSTANT_VALUES, *constant_names},
    )
    if count > _MAX_AST_NODES:
        raise ValueError("参数表达式过于复杂。")
    return parsed.body


def _power(left: _Dual, right: _Dual, *, source: str) -> _Dual:
    exponent = right.value
    if right.derivative != 0.0 or not exponent.is_integer():
        raise ValueError("ifem-math-v1 只允许 0 到 16 的整数常量幂。")
    integer_exponent = int(exponent)
    if not 0 <= integer_exponent <= _MAX_POWER:
        raise ValueError("ifem-math-v1 只允许 0 到 16 的整数常量幂。")
    if integer_exponent == 0:
        return _Dual(1.0, 0.0)
    if left.value == 0.0:
        derivative = left.derivative if integer_exponent == 1 else 0.0
        return _finite_dual(0.0, derivative, source=source)
    value = left.value**integer_exponent
    derivative = (
        integer_exponent
        * left.value ** (integer_exponent - 1)
        * left.derivative
    )
    return _finite_dual(value, derivative, source=source)


def _call_function(name: str, argument: _Dual, *, source: str) -> _Dual:
    value = argument.value
    derivative = argument.derivative
    if name == "sin":
        return _finite_dual(sin(value), cos(value) * derivative, source=source)
    if name == "cos":
        return _finite_dual(cos(value), -sin(value) * derivative, source=source)
    raise ValueError(f"不支持的数学函数：{name}")


def _evaluate_node(
    node: ast.AST,
    *,
    parameter: float,
    constants: Mapping[str, float],
    source: str,
) -> _Dual:
    if isinstance(node, ast.Constant):
        return _Dual(float(node.value), 0.0)
    if isinstance(node, ast.Name):
        if node.id == "t":
            return _Dual(parameter, 1.0)
        if node.id in _CONSTANT_VALUES:
            return _Dual(_CONSTANT_VALUES[node.id], 0.0)
        return _Dual(float(constants[node.id]), 0.0)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate_node(
            node.operand,
            parameter=parameter,
            constants=constants,
            source=source,
        )
        if isinstance(node.op, ast.USub):
            return _Dual(-value.value, -value.derivative)
        return value
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(
            node.left,
            parameter=parameter,
            constants=constants,
            source=source,
        )
        right = _evaluate_node(
            node.right,
            parameter=parameter,
            constants=constants,
            source=source,
        )
        if isinstance(node.op, ast.Add):
            return _finite_dual(
                left.value + right.value,
                left.derivative + right.derivative,
                source=source,
            )
        if isinstance(node.op, ast.Sub):
            return _finite_dual(
                left.value - right.value,
                left.derivative - right.derivative,
                source=source,
            )
        if isinstance(node.op, ast.Mult):
            return _finite_dual(
                left.value * right.value,
                left.derivative * right.value + left.value * right.derivative,
                source=source,
            )
        if isinstance(node.op, ast.Div):
            if right.value == 0.0:
                raise ValueError("参数表达式发生除零。")
            return _finite_dual(
                left.value / right.value,
                (
                    left.derivative * right.value
                    - left.value * right.derivative
                )
                / (right.value * right.value),
                source=source,
            )
        return _power(left, right, source=source)
    if isinstance(node, ast.Call):
        argument = _evaluate_node(
            node.args[0],
            parameter=parameter,
            constants=constants,
            source=source,
        )
        return _call_function(node.func.id, argument, source=source)
    raise ValueError("参数表达式包含不允许的语法。")


def _normalize_constants(values) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise ValueError("参数曲线常量必须是名称到数值的对象。")
    if len(values) > _MAX_CONSTANTS:
        raise ValueError("参数曲线最多允许 32 个用户常量。")
    normalized = {}
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip()
        if not _NAME_PATTERN.fullmatch(name) or name in _RESERVED_NAMES:
            raise ValueError(f"参数曲线常量名称无效或已保留：{name}")
        if isinstance(raw_value, bool):
            raise ValueError(f"参数曲线常量 {name} 必须是有限数值。")
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"参数曲线常量 {name} 必须是有限数值。") from exc
        if not isfinite(value):
            raise ValueError(f"参数曲线常量 {name} 必须是有限数值。")
        if name in normalized:
            raise ValueError(f"参数曲线常量名称规范化后重复：{name}")
        normalized[name] = value
    return normalized


def normalize_parametric_curve(parameters: Mapping) -> dict:
    """Normalize and compile-check a persisted analytic curve definition."""

    if not isinstance(parameters, Mapping):
        raise ValueError("参数曲线定义必须是对象。")
    allowed_keys = {"language", "domain", "expressions", "constants", "template"}
    unknown_keys = sorted(
        (str(key) for key in parameters if key not in allowed_keys),
        key=str,
    )
    if unknown_keys:
        raise ValueError(
            "参数曲线包含不支持的字段：" + "、".join(str(key) for key in unknown_keys)
        )
    language = str(
        parameters.get("language", PARAMETRIC_EXPRESSION_LANGUAGE)
    ).strip().lower()
    if language != PARAMETRIC_EXPRESSION_LANGUAGE:
        raise ValueError(f"不支持的参数表达式语言：{language}")
    raw_domain = parameters.get("domain", (0.0, 1.0))
    if not isinstance(raw_domain, (list, tuple)) or len(raw_domain) != 2:
        raise ValueError("参数曲线定义域必须包含起点和终点。")
    if any(isinstance(value, bool) for value in raw_domain):
        raise ValueError("参数曲线定义域必须是有限数值。")
    try:
        domain = tuple(float(value) for value in raw_domain)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("参数曲线定义域必须是有限数值。") from exc
    if not all(isfinite(value) for value in domain) or domain[1] <= domain[0]:
        raise ValueError("参数曲线定义域必须满足有限的 t₀ < t₁。")

    raw_expressions = parameters.get("expressions")
    if not isinstance(raw_expressions, Mapping):
        raise ValueError("参数曲线必须定义 x(t)、y(t) 和 z(t)。")
    if set(raw_expressions) != set(_COORDINATE_NAMES):
        raise ValueError("参数曲线表达式必须且只能包含 x、y、z。")
    expressions = {
        name: str(raw_expressions[name]).strip()
        for name in _COORDINATE_NAMES
    }
    constants = _normalize_constants(parameters.get("constants", {}))
    constant_names = tuple(sorted(constants))
    for name, expression in expressions.items():
        try:
            _compile_expression(expression, constant_names)
        except ValueError as exc:
            raise ValueError(f"{name}(t) 无效：{exc}") from exc
    template = str(parameters.get("template", "custom")).strip().lower() or "custom"
    if len(template) > 64:
        raise ValueError("参数曲线模板标识过长。")
    return {
        "language": PARAMETRIC_EXPRESSION_LANGUAGE,
        "domain": domain,
        "expressions": expressions,
        "constants": constants,
        "template": template,
    }


def evaluate_math_expression(
    source: str,
    parameter: float,
    constants: Mapping[str, float] | None = None,
) -> tuple[float, float]:
    """Return expression value and analytic derivative with respect to ``t``."""

    values = _normalize_constants(constants or {})
    t = float(parameter)
    if not isfinite(t):
        raise ValueError("参数 t 必须是有限数值。")
    text = str(source).strip()
    node = _compile_expression(text, tuple(sorted(values)))
    try:
        result = _evaluate_node(
            node,
            parameter=t,
            constants=values,
            source=text,
        )
    except (ArithmeticError, OverflowError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"参数表达式无法求值：{exc}") from exc
    return result.value, result.derivative


@dataclass(frozen=True)
class _CurveEvaluator:
    domain: tuple[float, float]
    constants: tuple[tuple[str, float], ...]
    sources: tuple[str, str, str]
    nodes: tuple[ast.AST, ast.AST, ast.AST]

    def evaluate(self, local_coordinate: float):
        xi = float(local_coordinate)
        if not isfinite(xi) or not 0.0 <= xi <= 1.0:
            raise ValueError("参数曲线局部坐标必须位于 [0, 1]。")
        domain_start, domain_end = self.domain
        domain_span = domain_end - domain_start
        parameter = domain_start + xi * domain_span
        constants = dict(self.constants)
        evaluated = []
        for coordinate, source, node in zip(
            _COORDINATE_NAMES,
            self.sources,
            self.nodes,
        ):
            try:
                value = _evaluate_node(
                    node,
                    parameter=parameter,
                    constants=constants,
                    source=source,
                )
            except (ArithmeticError, ValueError) as exc:
                raise ValueError(f"{coordinate}(t) 无效：{exc}") from exc
            evaluated.append(value)
        return (
            tuple(value.value for value in evaluated),
            tuple(value.derivative * domain_span for value in evaluated),
        )


@lru_cache(maxsize=128)
def _compiled_curve(
    domain: tuple[float, float],
    sources: tuple[str, str, str],
    constants: tuple[tuple[str, float], ...],
) -> _CurveEvaluator:
    constant_names = tuple(name for name, _value in constants)
    return _CurveEvaluator(
        domain=domain,
        constants=constants,
        sources=sources,
        nodes=tuple(_compile_expression(source, constant_names) for source in sources),
    )


def _curve_evaluator(parameters: Mapping) -> _CurveEvaluator:
    domain = tuple(float(value) for value in parameters["domain"])
    sources = tuple(str(parameters["expressions"][name]) for name in _COORDINATE_NAMES)
    constants = tuple(
        sorted((str(name), float(value)) for name, value in parameters["constants"].items())
    )
    return _compiled_curve(domain, sources, constants)


@lru_cache(maxsize=128)
def _cached_trigonometric_phase_rate(
    domain: tuple[float, float],
    sources: tuple[str, str, str],
    constant_items: tuple[tuple[str, float], ...],
) -> float:
    """Bound the effective harmonic rate of the v1 expression grammar."""

    evaluator = _compiled_curve(domain, sources, constant_items)
    constants = dict(evaluator.constants)
    domain_span = evaluator.domain[1] - evaluator.domain[0]

    def affine(node: ast.AST) -> tuple[float, float]:
        """Return ``a, b`` for an expression certified as ``a*t + b``."""

        if isinstance(node, ast.Constant):
            return 0.0, float(node.value)
        if isinstance(node, ast.Name):
            if node.id == "t":
                return 1.0, 0.0
            if node.id in _CONSTANT_VALUES:
                return 0.0, _CONSTANT_VALUES[node.id]
            return 0.0, float(constants[node.id])
        if isinstance(node, ast.UnaryOp):
            coefficient, offset = affine(node.operand)
            if isinstance(node.op, ast.USub):
                return -coefficient, -offset
            return coefficient, offset
        if isinstance(node, ast.BinOp):
            left_a, left_b = affine(node.left)
            right_a, right_b = affine(node.right)
            if isinstance(node.op, ast.Add):
                return left_a + right_a, left_b + right_b
            if isinstance(node.op, ast.Sub):
                return left_a - right_a, left_b - right_b
            if isinstance(node.op, ast.Mult):
                if left_a != 0.0 and right_a != 0.0:
                    raise ValueError("三角函数相位必须是 t 的仿射表达式。")
                return (
                    left_a * right_b + right_a * left_b,
                    left_b * right_b,
                )
            if isinstance(node.op, ast.Div):
                if right_a != 0.0 or right_b == 0.0:
                    raise ValueError("三角函数相位只能除以非零常量。")
                return left_a / right_b, left_b / right_b
            exponent_a, exponent_b = right_a, right_b
            if exponent_a != 0.0 or not exponent_b.is_integer():
                raise ValueError("三角函数相位中的幂必须是整数常量。")
            exponent = int(exponent_b)
            if exponent == 0:
                return 0.0, 1.0
            if exponent == 1:
                return left_a, left_b
            if left_a != 0.0:
                raise ValueError("三角函数相位必须是 t 的仿射表达式。")
            return 0.0, left_b**exponent
        raise ValueError("三角函数相位必须是 t 的仿射表达式且不能嵌套函数。")

    def harmonic_rate(node: ast.AST) -> float:
        if isinstance(node, (ast.Constant, ast.Name)):
            return 0.0
        if isinstance(node, ast.UnaryOp):
            return harmonic_rate(node.operand)
        if isinstance(node, ast.BinOp):
            left_rate = harmonic_rate(node.left)
            right_rate = harmonic_rate(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return max(left_rate, right_rate)
            if isinstance(node.op, ast.Mult):
                return left_rate + right_rate
            if isinstance(node.op, ast.Div):
                denominator_a, denominator_value = affine(node.right)
                if denominator_a != 0.0 or denominator_value == 0.0:
                    raise ValueError("只允许除以非零常量表达式。")
                return left_rate
            exponent_a, exponent_value = affine(node.right)
            if (
                exponent_a != 0.0
                or not exponent_value.is_integer()
                or not 0 <= exponent_value <= _MAX_POWER
            ):
                raise ValueError("只允许 0 到 16 的整数常量幂。")
            return left_rate * int(exponent_value)
        if isinstance(node, ast.Call):
            coefficient, _offset = affine(node.args[0])
            return abs(coefficient * domain_span)
        raise ValueError("参数表达式包含不允许的语法。")

    maximum_rate = 0.0
    for coordinate, source, root in zip(
        _COORDINATE_NAMES,
        evaluator.sources,
        evaluator.nodes,
    ):
        try:
            rate = harmonic_rate(root)
        except (ArithmeticError, ValueError) as exc:
            raise ValueError(f"{coordinate}(t) 无效：{exc}") from exc
        maximum_rate = max(maximum_rate, rate)
        if rate > _MAX_TRIG_PHASE_RATE:
            raise ValueError(
                f"{coordinate}(t) 无效：有效三角谐波过快；"
                "单个定义域最多允许约 32 个周期。"
            )
    return maximum_rate


def _trigonometric_phase_rate(parameters: Mapping) -> float:
    evaluator = _curve_evaluator(parameters)
    return _cached_trigonometric_phase_rate(
        evaluator.domain,
        evaluator.sources,
        evaluator.constants,
    )


@lru_cache(maxsize=128)
def _cached_recommended_sample_count(
    domain: tuple[float, float],
    sources: tuple[str, str, str],
    constant_items: tuple[tuple[str, float], ...],
) -> int:
    cycles = _cached_trigonometric_phase_rate(
        domain,
        sources,
        constant_items,
    ) / (2.0 * pi)
    count = max(129, min(513, int(cycles * 16.0) + 1))
    evaluator = _compiled_curve(domain, sources, constant_items)
    while True:
        derivatives = tuple(
            evaluator.evaluate(index / (count - 1))[1]
            for index in range(count)
        )
        speeds = tuple(
            sqrt(sum(value * value for value in derivative))
            for derivative in derivatives
        )
        alignments = tuple(
            sum(left * right for left, right in zip(first, second))
            / (first_speed * second_speed)
            if first_speed > 0.0 and second_speed > 0.0
            else -1.0
            for first, second, first_speed, second_speed in zip(
                derivatives,
                derivatives[1:],
                speeds,
                speeds[1:],
            )
        )
        if (
            not alignments
            or min(alignments) >= _MIN_RENDER_TANGENT_ALIGNMENT
            or count >= 513
        ):
            return count
        count = min(513, 2 * (count - 1) + 1)


def parametric_recommended_sample_count(parameters: Mapping) -> int:
    evaluator = _curve_evaluator(parameters)
    return _cached_recommended_sample_count(
        evaluator.domain,
        evaluator.sources,
        evaluator.constants,
    )


def expression_depends_on_parameter(
    source: str,
    constants: Mapping[str, float] | None = None,
) -> bool:
    values = _normalize_constants(constants or {})
    node = _compile_expression(str(source).strip(), tuple(sorted(values)))
    return any(isinstance(item, ast.Name) and item.id == "t" for item in ast.walk(node))


def parametric_curve_is_xy(parameters: Mapping, tolerance: float = 1.0e-10) -> bool:
    """Return true only when z is provably parameter-independent and numerically zero."""

    source = str(parameters["expressions"]["z"])
    constants = parameters["constants"]
    if expression_depends_on_parameter(source, constants):
        return False
    domain_start = float(parameters["domain"][0])
    value, derivative = evaluate_math_expression(source, domain_start, constants)
    return abs(value) <= tolerance and derivative == 0.0


def parametric_point_and_derivative(
    parameters: Mapping,
    local_coordinate: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return _curve_evaluator(parameters).evaluate(local_coordinate)


def _speed(parameters: Mapping, local_coordinate: float) -> float:
    _point, derivative = parametric_point_and_derivative(parameters, local_coordinate)
    return sqrt(sum(value * value for value in derivative))


def _sample_curve(parameters: Mapping, count: int = 65):
    return tuple(
        parametric_point_and_derivative(parameters, index / (count - 1))
        for index in range(count)
    )


def validate_parametric_regularity(parameters: Mapping) -> None:
    """Require a finite C1-like regular curve with nonzero tangent everywhere."""

    _trigonometric_phase_rate(parameters)
    samples = _sample_curve(parameters, 513)
    points = tuple(point for point, _derivative in samples)
    coordinate_ranges = tuple(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )
    geometry_scale = sqrt(sum(value * value for value in coordinate_ranges))
    if geometry_scale <= 0.0:
        raise ValueError("参数曲线不能退化为单个点。")
    tolerance = geometry_scale * 1.0e-12
    speeds = tuple(
        sqrt(sum(value * value for value in derivative))
        for _point, derivative in samples
    )
    if min(speeds) <= tolerance:
        raise ValueError("参数曲线存在零速点或尖点，无法建立稳定局部标架。")

    step = 1.0 / (len(samples) - 1)
    for index, ((point_a, derivative_a), (point_b, derivative_b)) in enumerate(
        zip(samples, samples[1:])
    ):
        speed_a = speeds[index]
        speed_b = speeds[index + 1]
        alignment = sum(
            left * right for left, right in zip(derivative_a, derivative_b)
        ) / (speed_a * speed_b)
        chord = sqrt(
            sum((right - left) ** 2 for left, right in zip(point_a, point_b))
        )
        if alignment < _MIN_VALID_TANGENT_ALIGNMENT or chord > (
            4.0 * step * max(speed_a, speed_b) + tolerance
        ):
            raise ValueError(
                "参数曲线局部变化超过 ifem-math-v1 的可靠分辨率；"
                "请降低频率、幅值或拆分曲线。"
            )

    coordinates = tuple(index / (len(samples) - 1) for index in range(len(samples)))
    speed_scale = max(speeds)
    for index in range(1, len(samples) - 1):
        neighbor_minimum = min(speeds[index - 1], speeds[index + 1])
        if neighbor_minimum - speeds[index] <= max(
            tolerance,
            speed_scale * 1.0e-9,
        ):
            continue
        left = coordinates[index - 1]
        right = coordinates[index + 1]
        for _iteration in range(40):
            first = (2.0 * left + right) / 3.0
            second = (left + 2.0 * right) / 3.0
            if _speed(parameters, first) <= _speed(parameters, second):
                right = second
            else:
                left = first
        if _speed(parameters, 0.5 * (left + right)) <= tolerance:
            raise ValueError("参数曲线存在零速点或尖点，无法建立稳定局部标架。")
    # A project-valid curve must also have a convergent finite arc length, and
    # integration may never be shorter than a polygonal lower bound.
    integrated_length = parametric_arc_length(parameters)
    polygonal_length = sum(
        sqrt(sum((right - left) ** 2 for left, right in zip(first, second)))
        for first, second in zip(points, points[1:])
    )
    length_tolerance = max(geometry_scale, integrated_length, 1.0) * 1.0e-6
    if integrated_length + length_tolerance < polygonal_length:
        raise ValueError(
            "参数曲线弧长积分低于离散几何下界；请降低曲线复杂度。"
        )


def _composite_gauss_length(
    parameters: Mapping,
    start: float,
    end: float,
    panel_count: int,
) -> float:
    length = 0.0
    span = end - start
    for panel in range(panel_count):
        panel_start = start + span * panel / panel_count
        panel_end = start + span * (panel + 1) / panel_count
        midpoint = 0.5 * (panel_start + panel_end)
        half_span = 0.5 * (panel_end - panel_start)
        for node, weight in zip(_GAUSS_NODES, _GAUSS_WEIGHTS):
            length += half_span * weight * _speed(
                parameters,
                midpoint + half_span * node,
            )
    return float(length)


def parametric_arc_length(
    parameters: Mapping,
    start: float = 0.0,
    end: float = 1.0,
) -> float:
    left = float(start)
    right = float(end)
    if not all(isfinite(value) and 0.0 <= value <= 1.0 for value in (left, right)):
        raise ValueError("参数曲线弧长区间必须位于 [0, 1]。")
    if right < left:
        left, right = right, left
    if right - left <= 1.0e-15:
        return 0.0
    samples = _sample_curve(parameters, 65)
    points = tuple(point for point, _derivative in samples)
    coordinate_ranges = tuple(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )
    geometry_scale = max(
        sqrt(sum(value * value for value in coordinate_ranges)),
        1.0e-300,
    )
    phase_rate = _trigonometric_phase_rate(parameters)
    estimated_cycles = phase_rate * (right - left) / (2.0 * pi)
    panels = max(1, min(1024, ceil(estimated_cycles * 4.0)))
    coarse = _composite_gauss_length(parameters, left, right, panels)
    tolerance = geometry_scale * 1.0e-6
    for _refinement in range(6):
        panels *= 2
        refined = _composite_gauss_length(parameters, left, right, panels)
        if not isfinite(refined):
            raise ValueError("参数曲线弧长积分产生了非有限数值。")
        if abs(refined - coarse) <= tolerance:
            if refined <= 0.0:
                raise ValueError("参数曲线弧长必须大于 0。")
            return float(refined)
        coarse = refined
    raise ValueError("参数曲线弧长积分未收敛；请检查表达式是否连续。")


def parametric_parameter_at_arc_length(parameters: Mapping, distance: float) -> float:
    total = parametric_arc_length(parameters)
    target = float(distance)
    tolerance = max(total, 1.0) * 1.0e-11
    if not isfinite(target) or target < -tolerance or target > total + tolerance:
        raise ValueError(f"参数曲线局部弧长必须位于 [0, {total:.8g}]。")
    target = min(total, max(0.0, target))
    if target <= tolerance:
        return 0.0
    if total - target <= tolerance:
        return 1.0
    low = 0.0
    high = 1.0
    parameter = target / total
    for _iteration in range(18):
        current = parametric_arc_length(parameters, 0.0, parameter)
        residual = current - target
        if abs(residual) <= tolerance:
            return min(1.0, max(0.0, parameter))
        if residual < 0.0:
            low = parameter
        else:
            high = parameter
        speed = _speed(parameters, parameter)
        candidate = parameter - residual / speed if speed > 0.0 else float("nan")
        if not isfinite(candidate) or not low < candidate < high:
            candidate = 0.5 * (low + high)
        parameter = candidate
    return 0.5 * (low + high)


__all__ = [
    "PARAMETRIC_EXPRESSION_LANGUAGE",
    "evaluate_math_expression",
    "expression_depends_on_parameter",
    "normalize_parametric_curve",
    "parametric_arc_length",
    "parametric_curve_is_xy",
    "parametric_parameter_at_arc_length",
    "parametric_point_and_derivative",
    "parametric_recommended_sample_count",
    "validate_parametric_regularity",
]
