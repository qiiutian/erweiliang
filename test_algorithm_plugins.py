import copy
import unittest

import numpy as np

from config_adapter import get_sample_config, run_reconstruction
from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm
from ifem.application.analysis_service import (
    DEFAULT_ALGORITHM_ID,
    AlgorithmRegistry,
    AlgorithmValidationError,
    create_default_analysis_service,
)
from ifem.application.algorithm_matching import match_project_algorithms
from ifem.domain.analysis import AnalysisCancelled, CancellationToken
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
        self.assertEqual(algorithm.capabilities.model_dimensions, (1,))
        self.assertIn("surface_axial_strain", algorithm.capabilities.measurement_types)
        self.assertIn("axial_stress", algorithm.capabilities.result_fields)
        self.assertFalse(algorithm.capabilities.supports_transient)
        self.assertEqual(algorithm.capabilities.modeling_spaces, ("2d",))
        self.assertEqual(algorithm.capabilities.geometry_kinds, ("line",))
        self.assertFalse(algorithm.capabilities.supports_mixed_geometry)

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


if __name__ == "__main__":
    unittest.main()
