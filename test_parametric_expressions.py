import unittest
from math import pi, sqrt

from ifem.domain.parametric_expressions import (
    PARAMETRIC_EXPRESSION_LANGUAGE,
    evaluate_math_expression,
    normalize_parametric_curve,
    parametric_arc_length,
    parametric_curve_is_xy,
    parametric_parameter_at_arc_length,
    parametric_point_and_derivative,
    parametric_recommended_sample_count,
    validate_parametric_regularity,
)


class ParametricExpressionTests(unittest.TestCase):
    def setUp(self):
        self.helix = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {
                    "x": "R*cos(2*pi*N*t)",
                    "y": "R*sin(2*pi*N*t)",
                    "z": "H*t",
                },
                "constants": {"R": 0.5, "N": 2.0, "H": 3.0},
                "template": "helix",
            }
        )

    def test_safe_expression_returns_analytic_derivative(self):
        value, derivative = evaluate_math_expression(
            "A*sin(2*pi*t) + t**3",
            0.25,
            {"A": 2.0},
        )

        self.assertAlmostEqual(value, 2.0 + 0.25**3, places=12)
        self.assertAlmostEqual(derivative, 3.0 * 0.25**2, places=12)

    def test_unsafe_or_excessive_expression_syntax_is_rejected(self):
        invalid = (
            "__import__('os').system('id')",
            "t.__class__",
            "[value for value in (t,)]",
            "t if t > 0 else 0",
            "unknown + t",
            "sin + t",
            "tan(t)",
            "tanh(1e8*sin(2*pi*32*t))",
            "sqrt(1-2*exp(-1e10*(t-0.5005)**2))",
            "1/(t-0.5)",
            "t**0.5",
            "t**65",
            "9" * 500,
        )
        for expression in invalid:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                evaluate_math_expression(expression, 0.5)

    def test_curve_definition_normalizes_json_safe_values(self):
        normalized = normalize_parametric_curve(
            {
                "domain": ["-1", "2"],
                "expressions": {"x": " L*t ", "y": "0", "z": "0"},
                "constants": {"L": "3.5"},
            }
        )

        self.assertEqual(normalized["domain"], (-1.0, 2.0))
        self.assertEqual(normalized["expressions"]["x"], "L*t")
        self.assertEqual(normalized["constants"], {"L": 3.5})
        self.assertEqual(normalized["template"], "custom")
        self.assertEqual(normalized["language"], PARAMETRIC_EXPRESSION_LANGUAGE)
        self.assertTrue(parametric_curve_is_xy(normalized))

    def test_invalid_domain_constants_and_expression_shape_are_rejected(self):
        base = {
            "domain": (0.0, 1.0),
            "expressions": {"x": "t", "y": "0", "z": "0"},
            "constants": {},
        }
        invalid = (
            {**base, "domain": (1.0, 1.0)},
            {**base, "domain": (0.0, float("inf"))},
            {**base, "constants": {"sin": 1.0}},
            {**base, "constants": {"bad-name": 1.0}},
            {**base, "constants": {"L": float("nan")}},
            {**base, "constants": {" L": 1.0, "L": 2.0}},
            {**base, "expressions": {"x": "t", "y": "0"}},
            {**base, "language": "arbitrary-python"},
            {**base, "langauge": "ifem-math-v1"},
            {**base, 1: "unknown"},
        )
        for parameters in invalid:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                normalize_parametric_curve(parameters)

    def test_helix_point_derivative_and_arc_length_are_exact(self):
        point, derivative = parametric_point_and_derivative(self.helix, 0.25)

        self.assertAlmostEqual(point[0], -0.5, places=12)
        self.assertAlmostEqual(point[1], 0.0, places=12)
        self.assertAlmostEqual(point[2], 0.75, places=12)
        self.assertAlmostEqual(derivative[0], 0.0, places=11)
        self.assertAlmostEqual(derivative[1], -2.0 * pi, places=11)
        self.assertAlmostEqual(derivative[2], 3.0, places=12)

        expected = sqrt((2.0 * pi) ** 2 + 3.0**2)
        self.assertAlmostEqual(parametric_arc_length(self.helix), expected, places=9)
        self.assertAlmostEqual(
            parametric_parameter_at_arc_length(self.helix, expected / 2.0),
            0.5,
            places=9,
        )

    def test_zero_speed_curve_is_rejected_before_geometry_use(self):
        cusp = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {
                    "x": "(t - 0.5)**3",
                    "y": "0",
                    "z": "0",
                },
                "constants": {},
            }
        )

        with self.assertRaisesRegex(ValueError, "零速点或尖点"):
            validate_parametric_regularity(cusp)

        aliased = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {
                    "x": "t + sin(2*pi*N*t)/(2*pi*N)",
                    "y": "0",
                    "z": "0",
                },
                "constants": {"N": 512.0},
            }
        )
        with self.assertRaisesRegex(ValueError, "谐波过快"):
            validate_parametric_regularity(aliased)

    def test_xy_classification_does_not_alias_spatial_oscillation(self):
        spatial = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {
                    "x": "t",
                    "y": "0",
                    "z": "sin(2*pi*32*t)",
                },
                "constants": {},
            }
        )

        self.assertFalse(parametric_curve_is_xy(spatial))
        self.assertAlmostEqual(
            parametric_arc_length(spatial),
            128.011382626,
            places=6,
        )

    def test_v1_harmonic_and_curvature_budget_prevents_undersampling(self):
        non_affine_phase = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {"x": "t", "y": "sin(t**2)", "z": "0"},
                "constants": {},
            }
        )
        with self.assertRaisesRegex(ValueError, "仿射"):
            validate_parametric_regularity(non_affine_phase)

        excessive_harmonic = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {
                    "x": "t",
                    "y": "sin(2*pi*32*t)**2",
                    "z": "0",
                },
                "constants": {},
            }
        )
        with self.assertRaisesRegex(ValueError, "有效三角谐波"):
            validate_parametric_regularity(excessive_harmonic)

        sharp_turn = normalize_parametric_curve(
            {
                "domain": (0.0, 1.0),
                "expressions": {
                    "x": "t",
                    "y": "A*sin(2*pi*t+0.137)",
                    "z": "0",
                },
                "constants": {"A": 100.0},
            }
        )
        self.assertEqual(parametric_recommended_sample_count(sharp_turn), 513)
        with self.assertRaisesRegex(ValueError, "可靠分辨率"):
            validate_parametric_regularity(sharp_turn)

    def test_internal_pole_is_rejected_as_non_regular_geometry(self):
        with self.assertRaises(ValueError):
            normalize_parametric_curve(
                {
                    "domain": (0.0, 1.0),
                    "expressions": {
                        "x": "t",
                        "y": "1/(t-a)",
                        "z": "0",
                    },
                    "constants": {"a": 0.123456},
                }
            )

    def test_nonfinite_or_singular_evaluation_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_math_expression("log(t)", -1.0)
        with self.assertRaises(ValueError):
            evaluate_math_expression("exp(t)", 1.0e3)


if __name__ == "__main__":
    unittest.main()
