from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np

from config_adapter import get_sample_config
from ifem.algorithms import ProjectReconstructionAlgorithm
from ifem.application import (
    AlgorithmRegistry,
    AlgorithmValidationError,
    AnalysisService,
    match_project_algorithms,
)
from ifem.application.analysis_service import create_default_analysis_service
from ifem.domain import (
    RECONSTRUCTION_CONTRACT_VERSION,
    AlgorithmCapabilities,
    AlgorithmMetadata,
    AnalysisResult,
    DeformationRegime,
    ReconstructionState,
    ResultField,
    RotationRepresentation,
    ValidationIssue,
    ValidationReport,
    empty_beam_project,
)
from ifem.infrastructure import project_from_legacy_config
from ifem.modeling import PathBeamEditor
from test_algorithm_plugins import EXPECTED_SAMPLE_DISPLACEMENT


class ProbeAlgorithm(ProjectReconstructionAlgorithm):
    """Formula-free plugin used to exercise only the public contract."""

    def __init__(self, modeling_space: str, regime: str):
        suffix = "small" if regime == DeformationRegime.SMALL.value else "large"
        self.metadata = AlgorithmMetadata(
            identifier=f"probe.beam{modeling_space}.{suffix}",
            display_name=f"{modeling_space.upper()} {suffix} probe",
            version="1.0.0",
            contract_version=RECONSTRUCTION_CONTRACT_VERSION,
        )
        is_3d = modeling_space == "3d"
        self.capabilities = AlgorithmCapabilities(
            model_dimensions=(1,),
            modeling_spaces=(modeling_space,),
            deformation_regimes=(regime,),
            element_families=(
                ("beam3d_line", "beam3d_curved")
                if is_3d
                else ("beam2d_euler_bernoulli", "beam2d_curved")
            ),
            measurement_types=("surface_axial_strain",),
            geometry_kinds=(
                "line",
                "circular_arc",
                "nurbs_curve",
                "parametric_curve",
            ),
            supports_mixed_geometry=True,
            rotation_representations=(
                RotationRepresentation.QUATERNION.value
                if is_3d and regime == DeformationRegime.LARGE.value
                else RotationRepresentation.ROTATION_VECTOR.value,
            ),
            result_fields=("quality",),
        )
        self.validate_calls = 0
        self.solve_calls = 0
        self.seen_project = None

    def parameter_schema(self):
        return {
            "type": "object",
            "properties": {
                "max_iterations": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 25,
                }
            },
        }

    def validate_project(
        self,
        request,
    ):
        self.validate_calls += 1
        self.seen_project = request.project
        return ValidationReport.valid()

    def solve_project(
        self,
        request,
        *,
        progress,
        cancellation,
    ):
        project = request.project
        self.solve_calls += 1
        self.seen_project = project
        cancellation.raise_if_cancelled()
        progress(0.5, "probe")
        representation = self.capabilities.rotation_representations[0]
        rotation_size = {
            RotationRepresentation.ROTATION_VECTOR.value: 3,
            RotationRepresentation.QUATERNION.value: 4,
        }[representation]
        rotations = []
        for _node in project.nodes:
            if representation == RotationRepresentation.QUATERNION.value:
                rotations.append((1.0, 0.0, 0.0, 0.0))
            else:
                rotations.append((0.0,) * rotation_size)
        state = ReconstructionState(
            modeling_space=project.modeling_space,
            deformation_regime=request.deformation_regime,
            node_ids=tuple(node.identifier for node in project.nodes),
            reference_coordinates=tuple(node.coordinates for node in project.nodes),
            displacements=((0.0, 0.0, 0.0),) * len(project.nodes),
            reference_frames=(
                (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            )
            * len(project.nodes),
            element_ids=tuple(element.identifier for element in project.elements),
            connectivity=tuple(element.node_ids for element in project.elements),
            rotations=tuple(rotations),
            rotation_representation=representation,
            project_id=project.identifier,
            project_revision=project.revision,
        )
        return AnalysisResult(
            algorithm_id=self.metadata.identifier,
            algorithm_version=self.metadata.version,
            state=state,
        )


class ReconstructionContractTests(unittest.TestCase):
    def setUp(self):
        self.project_2d = project_from_legacy_config(get_sample_config())
        self.project_3d = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=2,
            axis="z",
        )

    @staticmethod
    def _probes():
        return tuple(
            ProbeAlgorithm(space, regime.value)
            for space in ("2d", "3d")
            for regime in (DeformationRegime.SMALL, DeformationRegime.LARGE)
        )

    def test_capability_defaults_to_small_deformation(self):
        capabilities = AlgorithmCapabilities(
            model_dimensions=(1,),
            element_families=("beam2d_euler_bernoulli",),
            measurement_types=("surface_axial_strain",),
            result_fields=("displacement",),
        )

        self.assertEqual(
            capabilities.deformation_regimes,
            (DeformationRegime.SMALL.value,),
        )
        with self.assertRaisesRegex(ValueError, "变形制度"):
            replace(capabilities, deformation_regimes=("moderate",))

    def test_four_method_probes_register_and_match_by_space_and_regime(self):
        probes = self._probes()
        registry = AlgorithmRegistry(probes)

        self.assertEqual(len(registry.list()), 4)
        matches_2d = match_project_algorithms(self.project_2d, probes)
        matches_3d = match_project_algorithms(self.project_3d, probes)
        self.assertEqual(
            {item.algorithm_id for item in matches_2d if item.compatible},
            {"probe.beam2d.small", "probe.beam2d.large"},
        )
        self.assertEqual(
            {item.algorithm_id for item in matches_3d if item.compatible},
            {"probe.beam3d.small", "probe.beam3d.large"},
        )

        large_matches = match_project_algorithms(
            self.project_2d,
            probes,
            required_deformation_regime=DeformationRegime.LARGE,
        )
        self.assertEqual(
            {item.algorithm_id for item in large_matches if item.compatible},
            {"probe.beam2d.large"},
        )
        small_2d = next(
            item for item in large_matches if item.algorithm_id == "probe.beam2d.small"
        )
        self.assertEqual(
            [issue.field for issue in small_2d.issues],
            ["/analysis/deformation-regime"],
        )

    def test_service_rejects_project_capability_mismatch_before_plugin_hooks(self):
        probe = ProbeAlgorithm("3d", DeformationRegime.SMALL.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )

        with self.assertRaises(AlgorithmValidationError) as raised:
            service.run_project(
                self.project_2d,
                algorithm_id=probe.metadata.identifier,
            )

        self.assertEqual(probe.validate_calls, 0)
        self.assertEqual(probe.solve_calls, 0)
        self.assertIn(
            "/model/modeling-space",
            {issue.field for issue in raised.exception.issues},
        )

    def test_service_passes_full_nurbs_project_without_legacy_projection(self):
        project = PathBeamEditor.create_nurbs_curve(
            empty_beam_project(modeling_space="3d"),
            control_points=(
                (0.0, 0.0, 0.0),
                (0.8, 0.4, 0.6),
                (1.5, -0.2, 1.1),
                (2.0, 0.0, 1.5),
            ),
            degree=3,
            weights=(1.0, 0.8, 1.2, 1.0),
        )
        probe = ProbeAlgorithm("3d", DeformationRegime.LARGE.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )

        result = service.run_project(project, parameters={"max_iterations": 12})

        self.assertIsNot(probe.seen_project, project)
        self.assertEqual(probe.seen_project.to_dict(), project.to_dict())
        self.assertEqual(probe.seen_project.elements[0].geometry.kind, "nurbs_curve")
        self.assertEqual(
            probe.seen_project.elements[0].geometry.parameters["weights"],
            (1.0, 0.8, 1.2, 1.0),
        )
        self.assertGreater(probe.seen_project.nodes[-1].coordinates[2], 0.0)
        self.assertEqual(result.state.project_id, project.identifier)
        self.assertEqual(
            result.state.rotation_representation,
            RotationRepresentation.QUATERNION.value,
        )

    def test_parametric_curve_project_reaches_capable_plugin_without_projection(self):
        project = PathBeamEditor.create_parametric_curve(
            empty_beam_project(modeling_space="3d"),
            expressions={
                "x": "R*cos(2*pi*N*t)",
                "y": "R*sin(2*pi*N*t)",
                "z": "H*t",
            },
            constants={"R": 0.5, "N": 1.0, "H": 2.0},
            template="helix",
        )
        probe = ProbeAlgorithm("3d", DeformationRegime.SMALL.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )

        result = service.run_project(project, parameters={"max_iterations": 12})

        self.assertEqual(
            probe.seen_project.elements[0].geometry.parameters["expressions"],
            project.elements[0].geometry.parameters["expressions"],
        )
        self.assertEqual(result.state.project_id, project.identifier)
        default_match = match_project_algorithms(
            project,
            create_default_analysis_service().registry.list(),
        )[0]
        self.assertFalse(default_match.compatible)
        self.assertTrue(
            any(
                issue.field in {"/model/modeling-space", "/model/geometry"}
                for issue in default_match.issues
            )
        )

    def test_project_algorithm_base_rejects_legacy_only_context(self):
        probe = ProbeAlgorithm("2d", DeformationRegime.SMALL.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )

        with self.assertRaises(AlgorithmValidationError) as raised:
            service.run(get_sample_config())

        self.assertEqual(raised.exception.issues[0].field, "/model")
        self.assertEqual(probe.solve_calls, 0)

    def test_multi_regime_plugin_requires_an_explicit_analysis_choice(self):
        probe = ProbeAlgorithm("2d", DeformationRegime.SMALL.value)
        probe.capabilities = replace(
            probe.capabilities,
            deformation_regimes=(
                DeformationRegime.SMALL.value,
                DeformationRegime.LARGE.value,
            ),
        )
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )

        preparation = service.prepare_project(
            self.project_2d,
            algorithm_id=probe.metadata.identifier,
        )

        self.assertFalse(preparation.can_run)
        self.assertEqual(
            [issue.field for issue in preparation.issues],
            ["/analysis/deformation-regime"],
        )
        self.assertEqual(probe.validate_calls, 0)

    def test_validate_project_reports_empty_model_and_missing_case(self):
        service = create_default_analysis_service()
        empty_project = self.project_2d.revised(
            nodes=(),
            elements=(),
            sensors=(),
            boundary_conditions=(),
        )

        empty_report = service.validate_project(empty_project)
        missing_case_report = service.validate_project(
            self.project_2d,
            analysis_case_id="analysis-missing",
        )

        self.assertFalse(empty_report.is_valid)
        self.assertEqual(empty_report.issues[0].field, "/model/geometry")
        self.assertFalse(missing_case_report.is_valid)
        self.assertEqual(missing_case_report.issues[0].field, "/analysis/case/id")

    def test_selected_project_case_and_project_data_are_the_only_solver_source(self):
        first_case = self.project_2d.analysis_cases[0]
        selected_case = replace(
            first_case,
            identifier="analysis-selected",
            name="指定工况",
            parameters={
                **dict(first_case.parameters),
                "gauss_n": 4,
                "points_per_element": 17,
                "query_xs": [0.25, 0.75],
                "true_points": get_sample_config()["true_points"],
            },
        )
        project = self.project_2d.revised(
            analysis_cases=(first_case, selected_case),
            active_analysis_id=first_case.identifier,
        )
        conflicting_legacy = get_sample_config()
        for element in conflicting_legacy["elements_sensor_data"]:
            for measurement in element["measurements"]:
                measurement["strain"] = 0.0

        result = create_default_analysis_service().run_project(
            project,
            analysis_case_id=selected_case.identifier,
            legacy_project_config=conflicting_legacy,
        )

        np.testing.assert_allclose(
            result.native_model.U,
            EXPECTED_SAMPLE_DISPLACEMENT,
            rtol=1.0e-12,
            atol=1.0e-14,
        )
        self.assertEqual(result.inputs["gauss_n"], 4)
        self.assertEqual(result.inputs["points_per_element"], 17)
        self.assertEqual(result.inputs["query_xs"], [0.25, 0.75])
        self.assertEqual(result.inputs["true_points"], get_sample_config()["true_points"])

        overridden = create_default_analysis_service().run_project(
            project,
            analysis_case_id=selected_case.identifier,
            parameters={"query_xs": [0.125], "true_points": []},
        )
        self.assertEqual(overridden.inputs["query_xs"], [0.125])
        self.assertIsNone(overridden.inputs["true_points"])

    def test_project_request_parameters_are_detached_from_project_and_context(self):
        case = self.project_2d.analysis_cases[0]
        case = replace(
            case,
            parameters={
                **dict(case.parameters),
                "plugin_state": {"weights": [1, 2]},
            },
        )
        project = self.project_2d.revised(
            analysis_cases=(case,),
            active_analysis_id=case.identifier,
        )
        preparation = create_default_analysis_service().prepare_project(project)

        request = preparation.context.project_request()
        request.parameters["plugin_state"]["weights"].append(3)
        request.project.view_state["plugin_mutation"] = True

        self.assertEqual(
            project.analysis_cases[0].parameters["plugin_state"]["weights"],
            [1, 2],
        )
        self.assertEqual(
            preparation.context.parameters["plugin_state"]["weights"],
            [1, 2],
        )
        self.assertNotIn("plugin_mutation", project.view_state)

    def test_default_algorithm_runs_from_project_with_same_numeric_baseline(self):
        service = create_default_analysis_service()

        result = service.run_project(self.project_2d)

        np.testing.assert_allclose(
            result.native_model.U,
            EXPECTED_SAMPLE_DISPLACEMENT,
            rtol=1.0e-12,
            atol=1.0e-14,
        )
        self.assertEqual(result.state.modeling_space, "2d")
        self.assertEqual(
            result.state.deformation_regime,
            DeformationRegime.SMALL.value,
        )
        self.assertEqual(len(result.state.node_ids), result.native_model.n_nodes)
        np.testing.assert_allclose(
            np.asarray(result.state.displacements)[:, :2].reshape(-1),
            np.delete(result.native_model.U, np.arange(2, len(result.native_model.U), 3)),
            rtol=0.0,
            atol=0.0,
        )

    def test_service_rejects_undeclared_or_unknown_entity_result_fields(self):
        class BadFieldProbe(ProbeAlgorithm):
            def solve_project(self, project, **kwargs):
                result = super().solve_project(project, **kwargs)
                field = ResultField(
                    identifier="undeclared",
                    association="node",
                    entity_ids=(result.state.node_ids[0],),
                    components=("value",),
                    values=((1.0,),),
                )
                return replace(result, fields={"undeclared": field})

        probe = BadFieldProbe("2d", DeformationRegime.SMALL.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )
        with self.assertRaisesRegex(RuntimeError, "能力声明之外"):
            service.run_project(
                self.project_2d,
                algorithm_id=probe.metadata.identifier,
            )

        class UnknownNodeProbe(ProbeAlgorithm):
            def solve_project(self, request, **kwargs):
                result = super().solve_project(request, **kwargs)
                field = ResultField(
                    identifier="quality",
                    association="node",
                    entity_ids=("missing-node",),
                    components=("value",),
                    values=((1.0,),),
                )
                return replace(result, fields={"quality": field})

        probe = UnknownNodeProbe("2d", DeformationRegime.SMALL.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )
        with self.assertRaisesRegex(RuntimeError, "未知节点"):
            service.run_project(
                self.project_2d,
                algorithm_id=probe.metadata.identifier,
            )

    def test_v1_result_rejects_wrong_reference_geometry_and_missing_required_field(self):
        class WrongGeometryProbe(ProbeAlgorithm):
            def solve_project(self, request, **kwargs):
                result = super().solve_project(request, **kwargs)
                wrong_coordinates = ((0.0, 0.0, 0.0),) * len(result.state.node_ids)
                return replace(
                    result,
                    state=replace(
                        result.state,
                        reference_coordinates=wrong_coordinates,
                    ),
                )

        probe = WrongGeometryProbe("2d", DeformationRegime.SMALL.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )
        with self.assertRaisesRegex(RuntimeError, "参考坐标"):
            service.run_project(
                self.project_2d,
                algorithm_id=probe.metadata.identifier,
            )

        probe = ProbeAlgorithm("2d", DeformationRegime.SMALL.value)
        probe.capabilities = replace(
            probe.capabilities,
            required_result_fields=("quality",),
        )
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )
        with self.assertRaisesRegex(RuntimeError, "要求的结果字段"):
            service.run_project(
                self.project_2d,
                algorithm_id=probe.metadata.identifier,
            )

    def test_rotation_contract_rejects_non_unit_quaternion(self):
        probe = ProbeAlgorithm("3d", DeformationRegime.LARGE.value)
        service = AnalysisService(
            AlgorithmRegistry((probe,)),
            default_algorithm_id=probe.metadata.identifier,
        )
        result = service.run_project(self.project_3d)

        with self.assertRaisesRegex(ValueError, "单位四元数"):
            replace(
                result.state,
                rotations=((2.0, 0.0, 0.0, 0.0),) * len(result.state.node_ids),
            )

    def test_legacy_v0_keeps_positional_native_only_results(self):
        class LegacyAlgorithm:
            metadata = AlgorithmMetadata(
                identifier="legacy.native.only",
                display_name="Legacy native-only",
                version="1.0",
            )
            capabilities = AlgorithmCapabilities(
                model_dimensions=(1,),
                element_families=("beam2d_euler_bernoulli",),
                measurement_types=("surface_axial_strain",),
                result_fields=("legacy_raw",),
                modeling_spaces=("2d",),
                geometry_kinds=("line",),
            )

            def parameter_schema(self):
                return {"type": "object", "properties": {}}

            def validate(self, context):
                return ValidationReport.valid()

            def solve(self, context, *, progress, cancellation):
                return AnalysisResult(
                    self.metadata.identifier,
                    self.metadata.version,
                    object(),
                    {"legacy": True},
                    {"legacy_raw": [1.0]},
                    ("legacy-v0",),
                )

        algorithm = LegacyAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )

        result = service.run(get_sample_config())

        self.assertIsNone(result.state)
        self.assertEqual(result.fields, {"legacy_raw": [1.0]})
        self.assertEqual(result.diagnostics, ("legacy-v0",))

    def test_validation_issue_severity_is_normalized_and_checked(self):
        report = ValidationReport((ValidationIssue("错误", severity=" ERROR "),))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.error_message, "错误")
        with self.assertRaisesRegex(ValueError, "级别"):
            ValidationIssue("错误", severity="fatal")

    def test_registry_rejects_unknown_contract_version(self):
        probe = ProbeAlgorithm("2d", DeformationRegime.SMALL.value)
        probe.metadata = replace(
            probe.metadata,
            contract_version=str(int(RECONSTRUCTION_CONTRACT_VERSION) + 1),
        )

        with self.assertRaisesRegex(ValueError, "接口版本"):
            AlgorithmRegistry((probe,))

if __name__ == "__main__":
    unittest.main()
