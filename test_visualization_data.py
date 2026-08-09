import unittest

import numpy as np

from config_adapter import get_sample_config, run_reconstruction
from ifem.domain.project import SectionDefinition
from ifem.visualization import bidirectional_axis_glyph, oriented_surface_patch_glyph
from postprocessing import reconstruct_section_field, recover_continuous_section_field
from visualization_data import (
    build_surface_blocks,
    result_frame_from_beam,
    structural_model_from_beam,
)


class VisualizationDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = get_sample_config()
        cls.model, cls.inputs = run_reconstruction(config)
        cls.raw_field = reconstruct_section_field(
            cls.model,
            points_per_element=9,
            elastic_modulus=2.06e11,
            through_thickness_points=7,
        )
        cls.model_data = structural_model_from_beam(cls.model)

    def test_structural_model_keeps_beam_topology(self):
        self.assertEqual(self.model_data.node_coordinates.shape, (self.model.n_nodes, 3))
        self.assertEqual(self.model_data.line_elements.shape, (self.model.n_elems, 2))
        self.assertAlmostEqual(self.model_data.length, 3.0)
        self.assertFalse(self.model_data.node_coordinates.flags.writeable)

    def test_result_frame_maps_nodes_and_measurements(self):
        frame = result_frame_from_beam(
            self.model,
            self.raw_field,
            elements_sensor_data=self.inputs["elements_sensor_data"],
            sequence=12,
            time_value=0.25,
        )

        self.assertEqual(frame.sequence, 12)
        self.assertAlmostEqual(frame.time_value, 0.25)
        self.assertEqual(frame.deformed_nodes.shape, (self.model.n_nodes, 3))
        self.assertEqual(len(frame.sensors), 12)
        self.assertEqual({sensor.surface for sensor in frame.sensors}, {"top", "bottom"})
        self.assertTrue(all(np.isfinite(sensor.position).all() for sensor in frame.sensors))

    def test_raw_field_builds_one_surface_block_per_element(self):
        frame = result_frame_from_beam(self.model, self.raw_field)
        blocks = build_surface_blocks(self.model_data, frame, thickness_scale=10.0)

        self.assertEqual(len(blocks), self.model.n_elems)
        for block in blocks:
            self.assertEqual(block.points.shape, (9, 7, 2, 3))
            self.assertEqual(block.axial_strain.shape, (9, 7, 2))
            self.assertEqual(block.axial_stress.shape, (9, 7, 2))

    def test_recovered_field_builds_one_continuous_surface(self):
        recovered = recover_continuous_section_field(self.raw_field)
        frame = result_frame_from_beam(
            self.model,
            recovered,
            reference_field=self.raw_field,
        )
        blocks = build_surface_blocks(self.model_data, frame, thickness_scale=10.0)

        self.assertEqual(len(blocks), 1)
        expected_points = self.model.n_elems * 9 - self.model.n_elems + 1
        self.assertEqual(blocks[0].points.shape, (expected_points, 7, 2, 3))
        self.assertGreater(float(np.ptp(blocks[0].points[..., 2])), 0.0)
        self.assertAlmostEqual(
            frame.section.stress_reference_limit,
            float(np.max(np.abs(self.raw_field.stress))),
        )

    def test_frame_without_elastic_modulus_keeps_strain_surface(self):
        strain_only = reconstruct_section_field(
            self.model,
            points_per_element=5,
            elastic_modulus=None,
            through_thickness_points=5,
        )
        frame = result_frame_from_beam(self.model, strain_only)
        blocks = build_surface_blocks(self.model_data, frame, thickness_scale=5.0)

        self.assertIsNone(frame.section.stress_reference_limit)
        self.assertTrue(all(block.axial_stress is None for block in blocks))
        self.assertTrue(all(np.isfinite(block.axial_strain).all() for block in blocks))

    def test_defined_circular_tube_builds_outer_and_inner_result_surfaces(self):
        section = SectionDefinition(
            "tube",
            "圆管",
            self.model.thickness,
            shape="circular_tube",
            parameters={
                "outer_diameter": self.model.thickness,
                "wall_thickness": self.model.thickness * 0.12,
            },
        )
        model_data = structural_model_from_beam(self.model, section=section)
        frame = result_frame_from_beam(self.model, self.raw_field)
        blocks = build_surface_blocks(model_data, frame, thickness_scale=10.0)

        self.assertEqual(len(blocks), self.model.n_elems * 2)
        for block in blocks:
            self.assertEqual(block.points.shape, (9, 37, 3))
            self.assertEqual(block.axial_strain.shape, (9, 37))
            self.assertEqual(block.axial_stress.shape, (9, 37))
            self.assertTrue(np.isfinite(block.points).all())

    def test_bidirectional_axis_glyph_is_centered_and_sign_invariant(self):
        center = np.asarray((1.0, 2.0, 3.0))
        points, faces, lines = bidirectional_axis_glyph(
            center,
            axis=(1.0, 0.0, 0.0),
            lateral=(0.0, 0.0, 1.0),
            length=2.0,
        )
        reversed_points, reversed_faces, reversed_lines = bidirectional_axis_glyph(
            center,
            axis=(-1.0, 0.0, 0.0),
            lateral=(0.0, 0.0, 1.0),
            length=2.0,
        )

        np.testing.assert_allclose((points[0] + points[1]) * 0.5, center)
        np.testing.assert_allclose(
            points[np.lexsort(points.T[::-1])],
            reversed_points[np.lexsort(reversed_points.T[::-1])],
        )
        np.testing.assert_array_equal(faces, reversed_faces)
        np.testing.assert_array_equal(lines, reversed_lines)
        np.testing.assert_array_equal(lines, np.asarray((2, 0, 1)))
        self.assertEqual(faces.shape, (8,))

    def test_surface_patch_long_edge_follows_measurement_axis(self):
        center = np.asarray((1.0, -0.5, 2.0))
        root_half = np.sqrt(0.5)
        surface_normal = np.asarray((0.0, root_half, root_half))
        circumferential = np.asarray((0.0, -root_half, root_half))
        angle = np.deg2rad(37.0)
        measurement_axis = (
            np.cos(angle) * np.asarray((1.0, 0.0, 0.0))
            + np.sin(angle) * circumferential
        )
        points, faces, axis, lateral = oriented_surface_patch_glyph(
            center,
            measurement_axis,
            surface_normal,
            length=1.2,
            width=0.3,
        )
        reversed_points, _faces, _axis, _lateral = oriented_surface_patch_glyph(
            center,
            -measurement_axis,
            surface_normal,
            length=1.2,
            width=0.3,
        )

        np.testing.assert_allclose(points[1] - points[0], axis * 1.2)
        np.testing.assert_allclose(points[3] - points[0], lateral * 0.3)
        np.testing.assert_allclose((points - center) @ surface_normal, 0.0, atol=1e-12)
        np.testing.assert_allclose(
            points[np.lexsort(points.T[::-1])],
            reversed_points[np.lexsort(reversed_points.T[::-1])],
        )
        np.testing.assert_array_equal(faces, np.asarray((4, 0, 1, 2, 3)))


if __name__ == "__main__":
    unittest.main()
