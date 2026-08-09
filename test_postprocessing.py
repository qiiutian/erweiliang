import unittest

import numpy as np

from config_adapter import get_sample_config, normalize_config, run_reconstruction
from postprocessing import (
    element_boundary_jumps,
    reconstruct_section_field,
    recover_continuous_section_field,
    resolve_thickness_scale,
)


class BeamSectionFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, _inputs = run_reconstruction(get_sample_config())

    def test_surface_strain_matches_solver_kinematics(self):
        points_per_element = 7
        field = reconstruct_section_field(
            self.model,
            points_per_element=points_per_element,
            elastic_modulus=2.06e11,
        )

        cursor = 0
        for element in range(self.model.n_elems):
            length = self.model.node_x[element + 1] - self.model.node_x[element]
            element_u = self.model.U[self.model.element_dofs(element)]
            for local_x in np.linspace(0.0, length, points_per_element):
                expected_top = self.model.B_surface(local_x, length, self.model.h) @ element_u
                expected_bottom = self.model.B_surface(local_x, length, -self.model.h) @ element_u
                self.assertAlmostEqual(field.top_strain[cursor], expected_top)
                self.assertAlmostEqual(field.bottom_strain[cursor], expected_bottom)
                cursor += 1

    def test_stress_and_element_boundaries_are_preserved(self):
        elastic_modulus = 2.06e11
        field = reconstruct_section_field(
            self.model,
            points_per_element=5,
            elastic_modulus=elastic_modulus,
        )

        self.assertTrue(np.allclose(field.stress, elastic_modulus * field.strain))
        self.assertEqual(len(field.x_reference), self.model.n_elems * 5)
        repeated_boundaries = np.count_nonzero(np.isclose(np.diff(field.x_reference), 0.0))
        self.assertEqual(repeated_boundaries, self.model.n_elems - 1)
        self.assertGreaterEqual(resolve_thickness_scale(field, "auto"), 1.0)

    def test_nodal_average_recovery_removes_only_display_discontinuities(self):
        elastic_modulus = 2.06e11
        raw_field = reconstruct_section_field(
            self.model,
            points_per_element=7,
            elastic_modulus=elastic_modulus,
        )
        recovered_field = recover_continuous_section_field(raw_field)

        self.assertEqual(recovered_field.representation, "nodal_average")
        self.assertEqual(
            len(recovered_field.x_reference),
            len(raw_field.x_reference) - self.model.n_elems + 1,
        )
        self.assertFalse(np.any(np.isclose(np.diff(recovered_field.x_reference), 0.0)))
        self.assertTrue(
            np.allclose(recovered_field.stress, elastic_modulus * recovered_field.strain)
        )

        jumps = element_boundary_jumps(raw_field)
        self.assertEqual(len(jumps), self.model.n_elems - 1)
        self.assertEqual([row["x"] for row in jumps], list(self.model.node_x[1:-1]))

    def test_legacy_config_gets_postprocess_defaults(self):
        legacy = get_sample_config()
        legacy.pop("material", None)
        legacy["plot_options"].pop("thickness_scale", None)

        normalized = normalize_config(legacy)
        self.assertIsNone(normalized["material"]["elastic_modulus"])
        self.assertEqual(normalized["plot_options"]["thickness_scale"], "auto")
        self.assertEqual(
            normalized["plot_options"]["field_representation"],
            "nodal_average",
        )


if __name__ == "__main__":
    unittest.main()
