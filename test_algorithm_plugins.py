import copy
import unittest
from dataclasses import replace

import numpy as np

from config_adapter import get_sample_config, run_reconstruction
from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm
from ifem.application.analysis_service import (
    DEFAULT_ALGORITHM_ID,
    AlgorithmResolutionStatus,
    AlgorithmRegistry,
    AlgorithmValidationError,
    AnalysisService,
    create_default_analysis_service,
)
from ifem.application.algorithm_matching import match_project_algorithms
from ifem.domain.analysis import (
    AnalysisCancelled,
    AlgorithmMetadata,
    CancellationToken,
    ValidationIssue,
    ValidationReport,
)
from ifem.domain.project import empty_beam_project
from ifem.infrastructure import project_from_legacy_config
from ifem.modeling import PathBeamEditor


EXPECTED_SAMPLE_DISPLACEMENT = np.array(
    [
        0.0,
        0.0,
        4.2904438541666828e-01,
        -4.9999999999782759e-09,
        2.8372251041666779e-01,
        4.1550635416667252e-02,
        -8.2499999999749574e-09,
        1.6987431770833433e-01,
        -1.8292592708333413e-01,
        -8.4999999999891441e-09,
        0.0,
        -1.6204136458333446e-01,
    ]
)


class AlgorithmPluginTests(unittest.TestCase):
    def setUp(self):
        self.service = create_default_analysis_service()

    def test_default_registry_exposes_algorithm_capabilities(self):
        algorithms = self.service.registry.list()

        self.assertEqual(len(algorithms), 1)
        algorithm = algorithms[0]
        self.assertEqual(algorithm.metadata.identifier, DEFAULT_ALGORITHM_ID)
        self.assertEqual(algorithm.metadata.display_name, "局部积分 ASP-iFEM")
        self.assertEqual(algorithm.metadata.contract_version, "1")
        self.assertEqual(algorithm.capabilities.model_dimensions, (1,))
        self.assertIn("surface_axial_strain", algorithm.capabilities.measurement_types)
        self.assertIn("axial_stress", algorithm.capabilities.result_fields)
        self.assertFalse(algorithm.capabilities.supports_transient)
        self.assertEqual(algorithm.capabilities.modeling_spaces, ("2d",))
        self.assertEqual(algorithm.capabilities.geometry_kinds, ("line",))
        self.assertFalse(algorithm.capabilities.supports_mixed_geometry)
        self.assertEqual(
            algorithm.capabilities.deformation_regimes,
            ("small_deformation",),
        )

    def test_local_integral_method_reports_rank_deficiency_before_solve(self):
        config = copy.deepcopy(get_sample_config())
        for element in config["elements_sensor_data"]:
            for measurement in element["measurements"]:
                measurement["surface"] = "top"

        report = self.service.validate(config)

        self.assertFalse(report.is_valid)
        issue = next(
            issue
            for issue in report.issues
            if issue.field == "/analysis/solvability"
        )
        self.assertIn("不可求解", issue.message)
        self.assertIn("秩", issue.message)
        with self.assertRaises(AlgorithmValidationError) as raised:
            self.service.run(config)
        self.assertIn(
            "/analysis/solvability",
            {item.field for item in raised.exception.issues},
        )

    def test_local_integral_method_checks_boundary_observability(self):
        unconstrained = copy.deepcopy(get_sample_config())
        unconstrained["prescribed_dofs"] = {}
        report = self.service.validate(unconstrained)
        self.assertFalse(report.is_valid)
        self.assertIn(
            "/analysis/solvability",
            {issue.field for issue in report.issues},
        )

        fully_prescribed = copy.deepcopy(get_sample_config())
        fully_prescribed["prescribed_dofs"] = {
            index: 0.0 for index in range(len(fully_prescribed["node_x"]) * 3)
        }
        self.assertTrue(self.service.validate(fully_prescribed).is_valid)

    def test_local_integral_method_rejects_nonfinite_trial_solution(self):
        config = copy.deepcopy(get_sample_config())
        config["thickness"] = 1.0e-150
        for element in config["elements_sensor_data"]:
            for measurement in element["measurements"]:
                measurement["strain"] = 1.0e308
        config["prescribed_dofs"] = {
            index: 0.0 for index in (0, 1, 3, 6, 9, 10)
        }

        report = self.service.validate(config)

        self.assertFalse(report.is_valid)
        issue = next(
            issue
            for issue in report.issues
            if issue.field == "/analysis/solvability"
        )
        self.assertIn("非有限位移", issue.message)
        with self.assertRaises(AlgorithmValidationError):
            self.service.run(config)

    def test_local_integral_numerical_choices_remain_user_controlled(self):
        displacements = []
        for gauss_n, points_per_element in ((2, 11), (3, 37), (4, 83)):
            config = copy.deepcopy(get_sample_config())
            config["gauss_n"] = gauss_n
            config["points_per_element"] = points_per_element
            config["elements_sensor_data"][0]["measurements"][0]["zone"] = [
                0.05,
                0.45,
            ]

            result = self.service.run(config)

            self.assertEqual(result.inputs["gauss_n"], gauss_n)
            self.assertEqual(result.inputs["points_per_element"], points_per_element)
            self.assertEqual(
                result.inputs["elements_sensor_data"][0]["measurements"][0]["zone"],
                [0.05, 0.45],
            )
            displacements.append(result.native_model.U)

        np.testing.assert_allclose(
            displacements[0],
            displacements[1],
            rtol=1.0e-11,
            atol=1.0e-13,
        )
        np.testing.assert_allclose(
            displacements[1],
            displacements[2],
            rtol=1.0e-11,
            atol=1.0e-13,
        )

    def test_algorithm_matching_uses_space_geometry_and_project_constraints(self):
        algorithm = self.service.registry.list()[0]
        straight = project_from_legacy_config(get_sample_config())
        straight_match = match_project_algorithms(straight, (algorithm,))[0]
        self.assertTrue(straight_match.compatible)

        mixed = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="2d"),
            length=2.0,
            element_count=1,
        )
        mixed = PathBeamEditor.append_circular_arc(
            mixed,
            radius=1.0,
            sweep_degrees=60.0,
            plane="xy",
        )
        mixed_match = match_project_algorithms(mixed, (algorithm,))[0]
        self.assertFalse(mixed_match.compatible)
        self.assertTrue(
            any("几何类型" in reason for reason in mixed_match.reasons)
        )
        self.assertTrue(
            any("混合路径" in reason for reason in mixed_match.reasons)
        )

        spatial = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
            axis="x",
        )
        spatial_match = match_project_algorithms(spatial, (algorithm,))[0]
        self.assertFalse(spatial_match.compatible)
        self.assertTrue(
            any("3D建模空间" in reason for reason in spatial_match.reasons)
        )

        alternate_section = replace(
            straight.sections[0],
            identifier="section_mixed",
            thickness=0.25,
            parameters={},
        )
        mixed_sections = straight.revised(
            sections=straight.sections + (alternate_section,),
            elements=(
                replace(
                    straight.elements[0],
                    section_id=alternate_section.identifier,
                ),
            )
            + straight.elements[1:],
        )
        section_match = match_project_algorithms(mixed_sections, (algorithm,))[0]
        self.assertFalse(section_match.compatible)
        self.assertTrue(any("同一截面" in reason for reason in section_match.reasons))

    def test_default_service_preserves_sample_numeric_baseline(self):
        progress_events = []
        result = self.service.run(
            get_sample_config(),
            progress=lambda fraction, message: progress_events.append((fraction, message)),
        )

        self.assertEqual(result.algorithm_id, DEFAULT_ALGORITHM_ID)
        self.assertEqual(result.algorithm_version, "1.0.0")
        np.testing.assert_allclose(
            result.native_model.U,
            EXPECTED_SAMPLE_DISPLACEMENT,
            rtol=1.0e-12,
            atol=1.0e-14,
        )
        self.assertEqual(progress_events[0][0], 0.0)
        self.assertEqual(progress_events[-1][0], 1.0)
        self.assertTrue(
            all(
                left[0] <= right[0]
                for left, right in zip(progress_events, progress_events[1:])
            )
        )

    def test_algorithm_parameters_override_matching_legacy_config_fields(self):
        result = self.service.run(
            get_sample_config(),
            parameters={"gauss_n": 4, "points_per_element": 64},
        )

        self.assertEqual(result.inputs["gauss_n"], 4)
        self.assertEqual(result.inputs["points_per_element"], 64)

    def test_legacy_entrypoint_keeps_model_inputs_tuple(self):
        model, inputs = run_reconstruction(get_sample_config())

        np.testing.assert_allclose(
            model.U,
            EXPECTED_SAMPLE_DISPLACEMENT,
            rtol=1.0e-12,
            atol=1.0e-14,
        )
        self.assertEqual(inputs["gauss_n"], 3)
        self.assertEqual(inputs["points_per_element"], 120)

    def test_invalid_project_is_rejected_before_solve(self):
        invalid = copy.deepcopy(get_sample_config())
        invalid["node_x"] = [0.0, 1.0, 1.0]

        with self.assertRaisesRegex(AlgorithmValidationError, "严格递增"):
            self.service.run(invalid)

    def test_cancelled_request_does_not_enter_solver(self):
        token = CancellationToken()
        token.cancel()

        with self.assertRaises(AnalysisCancelled):
            self.service.run(get_sample_config(), cancellation=token)

    def test_registry_rejects_duplicate_algorithm_ids(self):
        algorithm = BeamSurfaceIntegralAlgorithm()
        registry = AlgorithmRegistry((algorithm,))

        with self.assertRaisesRegex(ValueError, "已注册"):
            registry.register(BeamSurfaceIntegralAlgorithm())

    def test_registry_resolve_reports_missing_version_and_schema_without_fallback(self):
        algorithm = self.service.registry.get(DEFAULT_ALGORITHM_ID)

        missing = self.service.registry.resolve("vendor.missing")
        self.assertEqual(missing.status, AlgorithmResolutionStatus.MISSING)
        self.assertIsNone(missing.algorithm)
        self.assertEqual(missing.issues[0].field, "/analysis/algorithm/id")

        version_mismatch = self.service.registry.resolve(
            DEFAULT_ALGORITHM_ID,
            expected_version="0.0.0",
        )
        self.assertEqual(
            version_mismatch.status,
            AlgorithmResolutionStatus.VERSION_MISMATCH,
        )
        self.assertIs(version_mismatch.algorithm, algorithm)
        self.assertEqual(
            version_mismatch.issues[0].field,
            "/analysis/algorithm/version",
        )

        schema_version = str(
            getattr(algorithm.metadata, "parameter_schema_version", "1")
        )
        schema_mismatch = self.service.registry.resolve(
            DEFAULT_ALGORITHM_ID,
            expected_schema_version=f"{schema_version}.mismatch",
        )
        self.assertEqual(
            schema_mismatch.status,
            AlgorithmResolutionStatus.SCHEMA_MISMATCH,
        )
        self.assertEqual(
            schema_mismatch.issues[0].field,
            "/analysis/algorithm/parameter-schema-version",
        )

    def test_metadata_version_is_normalized_before_resolution(self):
        class SpacedVersionAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier=DEFAULT_ALGORITHM_ID,
                display_name="  空格版本测试  ",
                version=" 1.0.0 ",
                parameter_schema_version=" 1 ",
            )

        algorithm = SpacedVersionAlgorithm()
        registry = AlgorithmRegistry((algorithm,))
        resolution = registry.resolve(
            DEFAULT_ALGORITHM_ID,
            expected_version="1.0.0",
            expected_schema_version="1",
        )

        self.assertEqual(algorithm.metadata.display_name, "空格版本测试")
        self.assertEqual(algorithm.metadata.version, "1.0.0")
        self.assertTrue(resolution.is_ready)

    def test_registry_rejects_malformed_parameter_schema(self):
        class InvalidSchemaAlgorithm(BeamSurfaceIntegralAlgorithm):
            def parameter_schema(self):
                return {"type": "array", "properties": {}}

        with self.assertRaisesRegex(ValueError, "顶层 type"):
            AlgorithmRegistry((InvalidSchemaAlgorithm(),))

    def test_registry_rejects_nonfinite_parameter_schema_numbers(self):
        invalid_properties = (
            {"type": "number", "minimum": float("nan")},
            {"type": "number", "maximum": float("inf")},
            {"type": "number", "default": float("nan")},
            {"type": "number", "enum": [1.0, float("inf")]},
        )
        for property_schema in invalid_properties:
            with self.subTest(property_schema=property_schema):
                class NonfiniteSchemaAlgorithm(BeamSurfaceIntegralAlgorithm):
                    def parameter_schema(self):
                        return {
                            "type": "object",
                            "properties": {"gain": property_schema},
                        }

                with self.assertRaisesRegex(ValueError, "有限数值"):
                    AlgorithmRegistry((NonfiniteSchemaAlgorithm(),))

    def test_service_structurally_validates_parameter_schema_subset(self):
        class SchemaAlgorithm(BeamSurfaceIntegralAlgorithm):
            def parameter_schema(self):
                return {
                    "type": "object",
                    "required": ["count", "mode"],
                    "properties": {
                        "count": {
                            "type": "integer",
                            "minimum": 2,
                            "maximum": 4,
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["fast", "precise"],
                        },
                        "ratio": {"type": "number", "maximum": 1.0},
                        "enabled": {"type": "boolean"},
                    },
                }

        algorithm = SchemaAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )
        report = service.validate(
            get_sample_config(),
            parameters={"mode": "unknown", "ratio": 2.0, "enabled": "yes"},
        )

        self.assertFalse(report.is_valid)
        self.assertEqual(
            {issue.field for issue in report.issues},
            {
                "/analysis/parameters/count",
                "/analysis/parameters/mode",
                "/analysis/parameters/ratio",
                "/analysis/parameters/enabled",
            },
        )

        minimum_report = service.validate(
            get_sample_config(),
            parameters={
                "count": 1,
                "mode": "fast",
                "ratio": 0.5,
                "enabled": True,
            },
        )
        self.assertFalse(minimum_report.is_valid)
        self.assertEqual(
            [issue.field for issue in minimum_report.issues],
            ["/analysis/parameters/count"],
        )

    def test_invalid_dynamic_parameter_is_rejected_before_solve(self):
        progress_events = []
        preparation = self.service.prepare(
            get_sample_config(),
            parameters={"gauss_n": 99, "future_parameter": 42},
        )

        self.assertFalse(preparation.can_run)
        self.assertEqual(
            [issue.field for issue in preparation.issues],
            ["/analysis/parameters/gauss_n"],
        )
        self.assertEqual(preparation.effective_parameters["future_parameter"], 42)

        with self.assertRaisesRegex(AlgorithmValidationError, "gauss_n") as raised:
            self.service.run(
                get_sample_config(),
                parameters={"gauss_n": 99, "future_parameter": 42},
                progress=lambda fraction, message: progress_events.append(
                    (fraction, message)
                ),
            )
        self.assertEqual(progress_events, [])
        self.assertIs(raised.exception.report, raised.exception.preparation.report)
        self.assertEqual(
            raised.exception.issues[0].field,
            "/analysis/parameters/gauss_n",
        )

    def test_nonfinite_dynamic_parameter_is_rejected_with_exact_field(self):
        class NumberParameterAlgorithm(BeamSurfaceIntegralAlgorithm):
            def parameter_schema(self):
                return {
                    "type": "object",
                    "properties": {"gain": {"type": "number"}},
                }

        algorithm = NumberParameterAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )

        report = service.validate(
            get_sample_config(),
            parameters={"gain": float("nan")},
        )

        self.assertFalse(report.is_valid)
        self.assertEqual(
            [issue.field for issue in report.issues],
            ["/analysis/parameters/gain"],
        )
        with self.assertRaises(AlgorithmValidationError) as raised:
            service.run(
                get_sample_config(),
                parameters={"gain": float("inf")},
            )
        self.assertEqual(
            raised.exception.issues[0].field,
            "/analysis/parameters/gain",
        )

    def test_unknown_parameters_are_preserved_without_rejection(self):
        preparation = self.service.prepare(
            get_sample_config(),
            parameters={"future_parameter": {"nested": True}},
        )

        self.assertTrue(preparation.can_run)
        self.assertEqual(
            preparation.effective_parameters["future_parameter"],
            {"nested": True},
        )

    def test_service_preserves_plugin_validation_report_on_error(self):
        class FieldFailingAlgorithm(BeamSurfaceIntegralAlgorithm):
            def validate(self, context):
                return ValidationReport.invalid(
                    "高斯点数校验失败。",
                    field="/analysis/parameters/gauss_n",
                )

        algorithm = FieldFailingAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )

        report = service.validate(get_sample_config())
        self.assertEqual(report.issues[0].field, "/analysis/parameters/gauss_n")
        with self.assertRaisesRegex(AlgorithmValidationError, "高斯点数") as raised:
            service.run(get_sample_config())
        self.assertEqual(raised.exception.report.issues[0], report.issues[0])

        class BrokenValidationAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = replace(
                BeamSurfaceIntegralAlgorithm.metadata,
                identifier="ifem.test.broken-validation",
            )

            def validate(self, context):
                raise RuntimeError("third-party validation failed")

        broken = BrokenValidationAlgorithm()
        broken_service = AnalysisService(
            AlgorithmRegistry((broken,)),
            default_algorithm_id=broken.metadata.identifier,
        )
        broken_report = broken_service.validate(get_sample_config())
        self.assertFalse(broken_report.is_valid)
        self.assertEqual(broken_report.issues[0].field, "/analysis/algorithm/id")
        self.assertIn("RuntimeError", broken_report.error_message)
        with self.assertRaises(AlgorithmValidationError):
            broken_service.run(get_sample_config())

    def test_service_rejects_result_with_wrong_algorithm_version(self):
        class WrongResultVersionAlgorithm(BeamSurfaceIntegralAlgorithm):
            def solve(self, context, *, progress, cancellation):
                result = super().solve(
                    context,
                    progress=progress,
                    cancellation=cancellation,
                )
                return replace(result, algorithm_version="0.0.0")

        algorithm = WrongResultVersionAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )

        with self.assertRaisesRegex(RuntimeError, "版本"):
            service.run(get_sample_config())

    def test_algorithm_match_preserves_assessor_validation_issues(self):
        class AssessedAlgorithm(BeamSurfaceIntegralAlgorithm):
            def assess_project(self, project):
                return ValidationReport(
                    (
                        ValidationIssue(
                            "路径配置不受支持",
                            field="/model/path",
                        ),
                        ValidationIssue(
                            "兼容模式提示",
                            field="/model/path",
                            severity="warning",
                        ),
                    )
                )

        project = project_from_legacy_config(get_sample_config())
        match = match_project_algorithms(project, (AssessedAlgorithm(),))[0]

        self.assertFalse(match.compatible)
        self.assertEqual(match.reasons, ("路径配置不受支持",))
        self.assertEqual(
            [(issue.message, issue.field, issue.severity) for issue in match.issues],
            [
                ("路径配置不受支持", "/model/path", "error"),
                ("兼容模式提示", "/model/path", "warning"),
            ],
        )

        class BrokenAssessmentAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = replace(
                BeamSurfaceIntegralAlgorithm.metadata,
                identifier="ifem.test.broken-assessment",
                display_name="损坏的候选方法",
            )

            def assess_project(self, project):
                raise RuntimeError("third-party assessor failed")

        matches = match_project_algorithms(
            project,
            (BrokenAssessmentAlgorithm(), BeamSurfaceIntegralAlgorithm()),
        )
        self.assertEqual(len(matches), 2)
        self.assertFalse(matches[0].compatible)
        self.assertEqual(matches[0].issues[0].field, "/analysis/algorithm/id")
        self.assertIn("RuntimeError", matches[0].reason_text)
        self.assertTrue(matches[1].compatible)


if __name__ == "__main__":
    unittest.main()
