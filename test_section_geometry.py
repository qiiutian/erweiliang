import unittest

import numpy as np

from ifem.domain.project import SectionDefinition, empty_beam_project
from ifem.modeling.path_editor import PathBeamEditor
from ifem.modeling.section_geometry import (
    section_boundary_point,
    section_outer_radius,
    section_profile_loops,
    sweep_section_mesh,
)


class SectionGeometryTests(unittest.TestCase):
    def test_supported_profiles_have_expected_boundaries(self):
        sections = (
            SectionDefinition("rect", "矩形", 0.2, 0.1),
            SectionDefinition(
                "circle",
                "圆形",
                0.2,
                shape="circle",
                parameters={"diameter": 0.2},
            ),
            SectionDefinition(
                "tube",
                "圆管",
                0.2,
                shape="circular_tube",
                parameters={"outer_diameter": 0.2, "wall_thickness": 0.02},
            ),
            SectionDefinition(
                "box",
                "矩形管",
                0.2,
                0.1,
                "box",
                {"outer_height": 0.2, "outer_width": 0.1, "wall_thickness": 0.01},
            ),
            SectionDefinition(
                "i",
                "工字形",
                0.2,
                0.1,
                "i_section",
                {
                    "height": 0.2,
                    "flange_width": 0.1,
                    "flange_thickness": 0.02,
                    "web_thickness": 0.012,
                },
            ),
        )

        self.assertEqual([len(section_profile_loops(item)) for item in sections], [1, 1, 2, 2, 1])
        self.assertAlmostEqual(section_outer_radius(sections[0], 0.0), 0.1)
        self.assertAlmostEqual(section_outer_radius(sections[0], 90.0), 0.05)
        self.assertAlmostEqual(section_outer_radius(sections[1], 37.0), 0.1, places=3)
        self.assertAlmostEqual(section_outer_radius(sections[-1], 90.0), 0.006)

        rectangle_boundary = section_boundary_point(sections[0], 20.0)
        self.assertEqual(rectangle_boundary.outward_normal, (1.0, 0.0))
        self.assertEqual(rectangle_boundary.boundary_tangent, (-0.0, 1.0))
        circle_boundary = section_boundary_point(sections[1], 37.0)
        self.assertAlmostEqual(
            np.linalg.norm(circle_boundary.outward_normal),
            1.0,
        )

    def test_hollow_section_constraints_are_validated(self):
        with self.assertRaisesRegex(ValueError, "圆管壁厚"):
            SectionDefinition(
                "tube",
                "无效圆管",
                0.1,
                shape="circular_tube",
                parameters={"outer_diameter": 0.1, "wall_thickness": 0.05},
            )
        with self.assertRaisesRegex(ValueError, "矩形管壁厚"):
            SectionDefinition(
                "box",
                "无效矩形管",
                0.1,
                0.08,
                "box",
                {"outer_height": 0.1, "outer_width": 0.08, "wall_thickness": 0.04},
            )

    def test_sweep_mesh_preserves_profile_and_path_stations(self):
        section = SectionDefinition("rect", "矩形", 0.2, 0.1)
        points = np.asarray(((0.0, 0.0, 0.0), (0.5, 0.1, 0.0), (1.0, 0.2, 0.0)))
        normals = np.asarray(((0.0, 1.0, 0.0),) * 3)
        binormals = np.asarray(((0.0, 0.0, 1.0),) * 3)

        mesh_points, mesh_faces = sweep_section_mesh(
            points,
            normals,
            binormals,
            section,
            display_scale=2.0,
        )

        self.assertEqual(mesh_points.shape, (12, 3))
        self.assertGreater(len(mesh_faces), 0)
        self.assertTrue(np.isfinite(mesh_points).all())
        self.assertAlmostEqual(float(np.ptp(mesh_points[:, 2])), 0.2)

    def test_uniform_section_update_assigns_every_element(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(),
            length=3.0,
            element_count=3,
        )
        parameters = {
            "height": 0.24,
            "flange_width": 0.12,
            "flange_thickness": 0.025,
            "web_thickness": 0.014,
        }
        updated = PathBeamEditor.update_primary_properties(
            project,
            thickness=0.24,
            width=0.12,
            elastic_modulus=206.0e9,
            section_shape="i_section",
            section_parameters=parameters,
        )

        section = updated.sections[0]
        self.assertEqual(section.shape, "i_section")
        self.assertEqual(section.parameters, parameters)
        self.assertTrue(
            all(element.section_id == section.identifier for element in updated.elements)
        )


if __name__ == "__main__":
    unittest.main()
