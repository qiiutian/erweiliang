import unittest
from dataclasses import replace
from math import pi, sqrt

import numpy as np

from config_adapter import get_sample_config
from ifem.domain.project import ProjectDocument, empty_beam_project
from ifem.infrastructure import legacy_config_from_project, project_from_legacy_config
from ifem.modeling import PathBeamEditor
from ifem.modeling.section_geometry import section_boundary_point


class PathBeamEditorTests(unittest.TestCase):
    def setUp(self):
        self.project = project_from_legacy_config(get_sample_config())

    @staticmethod
    def _rendered_surface_point(project, element, xi, angle_degrees, display_scale):
        centerline = np.asarray(
            PathBeamEditor.point_on_element(project, element, xi),
            dtype=float,
        )
        _tangent, normal, binormal = PathBeamEditor.section_frame(
            project,
            element,
            xi,
        )
        section = next(
            item for item in project.sections if item.identifier == element.section_id
        )
        boundary = section_boundary_point(section, angle_degrees)
        physical = (
            centerline
            + np.asarray(normal) * boundary.local_position[0]
            + np.asarray(binormal) * boundary.local_position[1]
        )
        rendered = centerline + (physical - centerline) * display_scale
        return rendered, physical

    def test_circular_arc_is_saved_as_algorithm_independent_geometry(self):
        arc = PathBeamEditor.create_circular_arc(
            self.project,
            radius=2.0,
            sweep_degrees=90.0,
            plane="xy",
        )
        capability = PathBeamEditor.capability(arc)

        self.assertEqual(len(arc.nodes), 2)
        self.assertEqual(len(arc.elements), 1)
        self.assertEqual(len(arc.sensors), 0)
        self.assertEqual(arc.elements[0].geometry.kind, "circular_arc")
        self.assertEqual(arc.elements[0].geometry.parameters["plane"], "xy")
        self.assertEqual(capability.kind, "二维圆弧梁")
        self.assertEqual(capability.modeling_space, "2d")
        self.assertEqual(capability.geometry_kinds, ("circular_arc",))
        self.assertFalse(capability.legacy_solver_compatible)
        self.assertAlmostEqual(capability.total_length, pi, places=12)

        midpoint = PathBeamEditor.point_on_element(arc, arc.elements[0], 0.5)
        self.assertAlmostEqual(midpoint[0], sqrt(2.0), places=12)
        self.assertAlmostEqual(midpoint[1], 2.0 - sqrt(2.0), places=12)
        self.assertAlmostEqual(midpoint[2], 0.0, places=12)

        restored = ProjectDocument.from_dict(arc.to_dict())
        self.assertEqual(len(restored.nodes), 2)
        self.assertEqual(len(restored.elements), 1)
        self.assertEqual(restored.elements[0].geometry, arc.elements[0].geometry)

    def test_2d_path_can_combine_straight_and_analytic_arc_segments(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="2d"),
            length=2.0,
            element_count=1,
        )
        project = PathBeamEditor.append_circular_arc(
            project,
            radius=1.0,
            sweep_degrees=90.0,
            plane="xy",
        )
        project = PathBeamEditor.append_straight_segment(
            project,
            length=1.0,
            direction="tangent",
        )

        elements = PathBeamEditor.ordered_elements(project)
        capability = PathBeamEditor.capability(project)
        self.assertEqual(project.modeling_space, "2d")
        self.assertEqual(
            [element.geometry.kind for element in elements],
            ["line", "circular_arc", "line"],
        )
        self.assertEqual(
            [element.family for element in elements],
            ["beam2d_euler_bernoulli", "beam2d_curved", "beam2d_euler_bernoulli"],
        )
        self.assertEqual(capability.kind, "二维直线/圆弧组合梁")
        self.assertTrue(capability.mixed_geometry)
        self.assertFalse(capability.legacy_solver_compatible)
        self.assertAlmostEqual(capability.total_length, 3.0 + pi / 2.0, places=12)
        np.testing.assert_allclose(
            PathBeamEditor.tangent_on_element(project, elements[0], 1.0),
            PathBeamEditor.tangent_on_element(project, elements[1], 0.0),
            atol=1.0e-12,
        )
        np.testing.assert_allclose(
            PathBeamEditor.tangent_on_element(project, elements[1], 1.0),
            PathBeamEditor.tangent_on_element(project, elements[2], 0.0),
            atol=1.0e-12,
        )

    def test_3d_path_can_combine_straight_and_analytic_arc_segments(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
            axis="x",
        )
        project = PathBeamEditor.append_circular_arc(
            project,
            radius=1.25,
            sweep_degrees=90.0,
            plane="xz",
        )
        project = PathBeamEditor.append_straight_segment(
            project,
            length=0.75,
            direction="tangent",
        )

        elements = PathBeamEditor.ordered_elements(project)
        capability = PathBeamEditor.capability(project)
        self.assertEqual(project.modeling_space, "3d")
        self.assertEqual(
            [element.geometry.kind for element in elements],
            ["line", "circular_arc", "line"],
        )
        self.assertEqual(
            [element.family for element in elements],
            ["beam3d_line", "beam3d_curved", "beam3d_line"],
        )
        self.assertEqual(capability.kind, "三维直线/圆弧组合梁")
        self.assertEqual(capability.dimension, 3)
        self.assertTrue(capability.mixed_geometry)
        self.assertGreater(PathBeamEditor.ordered_nodes(project)[-1].coordinates[2], 0.0)
        np.testing.assert_allclose(
            PathBeamEditor.tangent_on_element(project, elements[0], 1.0),
            PathBeamEditor.tangent_on_element(project, elements[1], 0.0),
            atol=1.0e-12,
        )

    def test_straight_path_supports_signed_global_axes(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.5,
            element_count=2,
            axis="-z",
        )

        nodes = PathBeamEditor.ordered_nodes(project)
        self.assertEqual(nodes[0].coordinates, (0.0, 0.0, 0.0))
        self.assertEqual(nodes[-1].coordinates, (0.0, 0.0, -2.5))
        self.assertEqual(PathBeamEditor.capability(project).kind, "三维直梁")

    def test_spatial_geometry_cannot_be_reclassified_as_2d(self):
        project = PathBeamEditor.create_circular_arc(
            empty_beam_project(modeling_space="3d"),
            radius=2.0,
            sweep_degrees=75.0,
            plane="yz",
        )

        with self.assertRaisesRegex(ValueError, "非零 z|非 XY 圆弧"):
            PathBeamEditor.set_modeling_space(project, "2d")

        planar_spatial = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
            axis="x",
        )
        with self.assertRaisesRegex(ValueError, "三维建模空间"):
            legacy_config_from_project(planar_spatial)

    def test_arc_parameters_update_without_creating_polyline_elements(self):
        arc = PathBeamEditor.create_circular_arc(
            self.project,
            radius=1.5,
            sweep_degrees=120.0,
            plane="xy",
        )
        element = arc.elements[0]
        arc = PathBeamEditor.add_sensor(
            arc,
            element.identifier,
            0.5,
            "top",
            surface_angle_degrees=90.0,
            orientation_angle_degrees=25.0,
        )
        endpoint = PathBeamEditor.ordered_nodes(arc)[-1]

        with self.assertRaisesRegex(ValueError, "圆弧参数控制"):
            PathBeamEditor.move_node(
                arc,
                endpoint.identifier,
                (endpoint.coordinates[0], endpoint.coordinates[1], 0.4),
            )

        updated = PathBeamEditor.update_circular_arc(
            arc,
            element.identifier,
            radius=3.0,
            sweep_degrees=-90.0,
            plane="xz",
        )

        self.assertEqual(len(updated.nodes), 2)
        self.assertEqual(len(updated.elements), 1)
        self.assertEqual(updated.elements[0].geometry.parameters["radius"], 3.0)
        self.assertEqual(updated.elements[0].geometry.parameters["sweep_degrees"], -90.0)
        self.assertEqual(updated.elements[0].geometry.parameters["plane"], "xz")
        self.assertAlmostEqual(PathBeamEditor.total_length(updated), 1.5 * pi, places=12)
        self.assertAlmostEqual(
            updated.sensors[0].attachment.gauge_length,
            0.45 * pi,
            places=12,
        )
        self.assertEqual(updated.sensors[0].attachment.surface_angle_degrees, 90.0)
        self.assertEqual(updated.sensors[0].attachment.orientation_angle_degrees, 25.0)
        expected_direction = PathBeamEditor.sensor_direction_from_angles(
            updated,
            updated.sensors[0],
        )
        for actual, expected in zip(
            updated.sensors[0].attachment.direction,
            expected_direction,
        ):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_editing_an_internal_arc_keeps_the_downstream_path_connected(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="2d"),
            length=2.0,
            element_count=1,
        )
        project = PathBeamEditor.append_circular_arc(
            project,
            radius=1.0,
            sweep_degrees=90.0,
            plane="xy",
        )
        project = PathBeamEditor.append_straight_segment(
            project,
            length=1.25,
            direction="tangent",
        )
        arc = project.elements[1]
        tail = project.elements[2]
        tail_length = PathBeamEditor.element_length(project, tail)

        updated = PathBeamEditor.update_circular_arc(
            project,
            arc.identifier,
            radius=1.6,
            sweep_degrees=65.0,
            plane="xy",
        )

        node_by_id = {node.identifier: node for node in updated.nodes}
        updated_arc = next(
            element for element in updated.elements if element.identifier == arc.identifier
        )
        updated_tail = next(
            element for element in updated.elements if element.identifier == tail.identifier
        )
        np.testing.assert_allclose(
            PathBeamEditor.point_on_element(updated, updated_arc, 1.0),
            node_by_id[updated_arc.node_ids[1]].coordinates,
            atol=1.0e-12,
        )
        np.testing.assert_allclose(
            PathBeamEditor.point_on_element(updated, updated_tail, 0.0),
            node_by_id[updated_tail.node_ids[0]].coordinates,
            atol=1.0e-12,
        )
        self.assertAlmostEqual(
            PathBeamEditor.element_length(updated, updated_tail),
            tail_length,
            places=12,
        )

    def test_splitting_element_preserves_sensor_global_position(self):
        project = empty_beam_project()
        project = PathBeamEditor.create_straight_beam(
            project,
            length=3.0,
            element_count=3,
        )
        element = PathBeamEditor.ordered_elements(project)[1]
        project = PathBeamEditor.add_sensor(project, element.identifier, 0.35, "top")
        sensor = project.sensors[-1]
        before = PathBeamEditor.sensor_location(project, sensor.identifier)

        split = PathBeamEditor.insert_node(project, element.identifier, 0.5)
        after = PathBeamEditor.sensor_location(split, sensor.identifier)

        self.assertEqual(len(split.nodes), 5)
        self.assertEqual(len(split.elements), 4)
        for actual, expected in zip(after.global_position, before.global_position):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(after.path_distance, before.path_distance)

    def test_new_sensor_direction_follows_spatial_element_tangent(self):
        project = PathBeamEditor.create_polyline(
            empty_beam_project(),
            ((0.0, 0.0, 0.0), (0.0, 3.0, 4.0)),
        )
        element = project.elements[0]
        project = PathBeamEditor.add_sensor(project, element.identifier, 0.5, "top")

        self.assertEqual(project.sensors[-1].attachment.direction, (0.0, 0.6, 0.8))

    def test_sensor_circumferential_position_and_orientation_use_local_frame(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(),
            length=2.0,
            element_count=1,
        )
        project = PathBeamEditor.add_sensor(
            project,
            project.elements[0].identifier,
            0.5,
            "top",
            surface_angle_degrees=90.0,
            orientation_angle_degrees=30.0,
        )
        sensor = project.sensors[0]
        orientation = PathBeamEditor.sensor_orientation(project, sensor)

        self.assertEqual(sensor.attachment.surface_angle_degrees, 90.0)
        self.assertEqual(sensor.attachment.orientation_angle_degrees, 30.0)
        for actual, expected in zip(orientation.surface_radial, (0.0, 0.0, 1.0)):
            self.assertAlmostEqual(actual, expected, places=12)
        expected_direction = (sqrt(3.0) / 2.0, -0.5, 0.0)
        for actual, expected in zip(sensor.attachment.direction, expected_direction):
            self.assertAlmostEqual(actual, expected, places=12)

        capability = PathBeamEditor.capability(project)
        self.assertFalse(capability.legacy_solver_compatible)
        self.assertIn("轴向应变测点", capability.reason)
        with self.assertRaisesRegex(ValueError, "轴向应变测点"):
            legacy_config_from_project(project)

    def test_sensor_copy_and_opposite_placement_use_new_clean_channels(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
        )
        project = PathBeamEditor.add_sensor(
            project,
            project.elements[0].identifier,
            0.4,
            "top",
            surface_angle_degrees=35.0,
            orientation_angle_degrees=25.0,
        )
        source = replace(project.sensors[0], measured_value=2.5e-4, channel_id="CH-01")
        project = project.revised(sensors=(source,))

        copied = PathBeamEditor.duplicate_sensor(project, source.identifier)
        duplicate = copied.sensors[-1]
        self.assertNotEqual(duplicate.identifier, source.identifier)
        self.assertNotEqual(duplicate.label, source.label)
        self.assertEqual(duplicate.attachment, source.attachment)
        self.assertEqual(duplicate.measured_value, 0.0)
        self.assertIsNone(duplicate.channel_id)

        opposite_project = PathBeamEditor.add_opposite_sensor(project, source.identifier)
        opposite = opposite_project.sensors[-1]
        self.assertNotEqual(opposite.identifier, source.identifier)
        self.assertAlmostEqual(opposite.attachment.local_coordinates[0], 0.4)
        self.assertAlmostEqual(opposite.attachment.surface_angle_degrees, 215.0)
        self.assertEqual(opposite.attachment.surface_side, "bottom")
        self.assertAlmostEqual(opposite.attachment.orientation_angle_degrees, 25.0)
        self.assertEqual(opposite.measured_value, 0.0)
        self.assertIsNone(opposite.channel_id)

    def test_sensor_array_keeps_equal_arc_length_spacing_across_mixed_path(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=1.0,
            element_count=1,
        )
        project = PathBeamEditor.append_circular_arc(
            project,
            radius=1.0,
            sweep_degrees=90.0,
            plane="xy",
        )
        project = PathBeamEditor.append_straight_segment(
            project,
            length=1.0,
            direction="tangent",
        )
        first = PathBeamEditor.ordered_elements(project)[0]
        project = PathBeamEditor.add_sensor(
            project,
            first.identifier,
            0.25,
            "top",
            surface_angle_degrees=72.0,
            orientation_angle_degrees=-20.0,
        )
        source = project.sensors[0]

        arrayed = PathBeamEditor.array_sensor(
            project,
            source.identifier,
            count=4,
            spacing=0.75,
            direction=1,
        )

        distances = [
            PathBeamEditor.sensor_location(arrayed, sensor.identifier).path_distance
            for sensor in arrayed.sensors
        ]
        self.assertEqual(len(arrayed.sensors), 5)
        for left, right in zip(distances, distances[1:]):
            self.assertAlmostEqual(right - left, 0.75, places=10)
        self.assertEqual(len({sensor.identifier for sensor in arrayed.sensors}), 5)
        for sensor in arrayed.sensors[1:]:
            self.assertAlmostEqual(sensor.attachment.surface_angle_degrees, 72.0)
            self.assertAlmostEqual(sensor.attachment.orientation_angle_degrees, -20.0)
            self.assertEqual(sensor.measured_value, 0.0)

        with self.assertRaisesRegex(ValueError, "超出梁路径"):
            PathBeamEditor.array_sensor(
                project,
                source.identifier,
                count=10,
                spacing=0.75,
                direction=1,
            )

    def test_sensor_surface_move_preserves_identity_and_updates_full_attachment(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=2,
        )
        project = PathBeamEditor.update_primary_properties(
            project,
            thickness=0.16,
            width=0.10,
            elastic_modulus=70.0e9,
        )
        first, second = PathBeamEditor.ordered_elements(project)
        project = PathBeamEditor.add_sensor(
            project,
            first.identifier,
            0.25,
            "top",
            surface_angle_degrees=15.0,
            orientation_angle_degrees=32.0,
        )
        source = replace(
            project.sensors[0],
            measured_value=1.2e-4,
            channel_id="CH-MOVE",
        )
        project = project.revised(sensors=(source,))
        rendered, physical = self._rendered_surface_point(
            project,
            second,
            0.7,
            245.0,
            3.0,
        )
        location = PathBeamEditor.surface_location_from_point(
            project,
            rendered,
            display_scale=3.0,
        )

        moved_project = PathBeamEditor.move_sensor_to_surface(
            project,
            source.identifier,
            location,
        )
        moved = moved_project.sensors[0]

        self.assertEqual(moved.identifier, source.identifier)
        self.assertEqual(moved.label, source.label)
        self.assertEqual(moved.measured_value, source.measured_value)
        self.assertEqual(moved.channel_id, source.channel_id)
        self.assertEqual(moved.attachment.entity_id, second.identifier)
        self.assertAlmostEqual(moved.attachment.local_coordinates[0], 0.7, places=10)
        self.assertAlmostEqual(moved.attachment.surface_angle_degrees, 245.0, places=8)
        self.assertAlmostEqual(moved.attachment.orientation_angle_degrees, 32.0)
        np.testing.assert_allclose(
            PathBeamEditor.sensor_surface_position(moved_project, moved),
            physical,
            atol=1.0e-10,
        )

    def test_extending_path_and_deleting_internal_node_remain_valid(self):
        project = empty_beam_project()
        extended = PathBeamEditor.append_node(project, (1.5, 0.5, 0.25))
        self.assertEqual(len(extended.nodes), 3)
        self.assertEqual(len(extended.elements), 2)

        middle = PathBeamEditor.ordered_nodes(extended)[1]
        merged = PathBeamEditor.delete_node(extended, middle.identifier)
        nodes, elements = PathBeamEditor.ordered_path(merged)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(elements), 1)

    def test_section_and_material_properties_are_model_data(self):
        updated = PathBeamEditor.update_primary_properties(
            self.project,
            thickness=0.02,
            width=0.08,
            elastic_modulus=70.0e9,
        )

        self.assertAlmostEqual(updated.sections[0].thickness, 0.02)
        self.assertAlmostEqual(updated.sections[0].width, 0.08)
        self.assertAlmostEqual(updated.materials[0].elastic_modulus, 70.0e9)

    def test_rectangular_section_uses_actual_face_normal_for_angled_sensor(self):
        project = PathBeamEditor.update_primary_properties(
            self.project,
            thickness=0.2,
            width=0.1,
            elastic_modulus=70.0e9,
        )
        element = PathBeamEditor.ordered_elements(project)[0]
        project = PathBeamEditor.add_sensor(
            project,
            element.identifier,
            0.5,
            "top",
            surface_angle_degrees=20.0,
            orientation_angle_degrees=25.0,
        )
        orientation = PathBeamEditor.sensor_orientation(project, project.sensors[-1])

        np.testing.assert_allclose(orientation.surface_normal, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(
            float(np.dot(orientation.surface_normal, orientation.measurement_direction)),
            0.0,
            places=12,
        )

    def test_surface_pick_recovers_straight_beam_and_actual_rectangle_face(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(),
            length=2.0,
            element_count=1,
        )
        project = PathBeamEditor.update_primary_properties(
            project,
            thickness=0.2,
            width=0.1,
            elastic_modulus=70.0e9,
        )
        element = project.elements[0]
        rendered, physical = self._rendered_surface_point(
            project,
            element,
            0.37,
            28.0,
            4.0,
        )

        location = PathBeamEditor.surface_location_from_point(
            project,
            rendered,
            display_scale=4.0,
        )

        self.assertEqual(location.element_id, element.identifier)
        self.assertAlmostEqual(location.local_coordinate, 0.37, places=10)
        self.assertAlmostEqual(location.path_distance, 0.74, places=10)
        self.assertAlmostEqual(location.surface_angle_degrees, 28.0, places=10)
        self.assertEqual(location.surface_side, "top")
        np.testing.assert_allclose(location.global_position, physical, atol=1.0e-12)
        np.testing.assert_allclose(location.surface_normal, (0.0, 0.0, 1.0))
        self.assertAlmostEqual(location.snap_distance, 0.0, places=12)

    def test_surface_pick_recovers_arc_and_sensor_surface_position(self):
        project = PathBeamEditor.create_circular_arc(
            empty_beam_project(),
            radius=2.0,
            sweep_degrees=105.0,
            plane="xz",
        )
        project = PathBeamEditor.update_primary_properties(
            project,
            thickness=0.12,
            width=0.08,
            elastic_modulus=206.0e9,
            section_shape="circle",
            section_parameters={"diameter": 0.12},
        )
        element = project.elements[0]
        rendered, physical = self._rendered_surface_point(
            project,
            element,
            0.63,
            214.0,
            2.5,
        )

        location = PathBeamEditor.surface_location_from_point(
            project,
            rendered,
            display_scale=2.5,
        )
        project = PathBeamEditor.add_sensor(
            project,
            location.element_id,
            location.local_coordinate,
            location.surface_side,
            surface_angle_degrees=location.surface_angle_degrees,
        )

        self.assertEqual(location.element_id, element.identifier)
        self.assertAlmostEqual(location.local_coordinate, 0.63, places=4)
        self.assertAlmostEqual(location.surface_angle_degrees, 214.0, places=3)
        np.testing.assert_allclose(location.global_position, physical, atol=2.0e-5)
        np.testing.assert_allclose(
            PathBeamEditor.sensor_surface_position(project, project.sensors[-1]),
            location.global_position,
            atol=2.0e-5,
        )
        restored = ProjectDocument.from_dict(project.to_dict())
        np.testing.assert_allclose(
            PathBeamEditor.sensor_surface_position(restored, restored.sensors[-1]),
            location.global_position,
            atol=2.0e-5,
        )

    def test_surface_pick_identifies_correct_spatial_path_segment(self):
        project = PathBeamEditor.create_polyline(
            empty_beam_project(),
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.5, 0.75)),
        )
        project = PathBeamEditor.update_primary_properties(
            project,
            thickness=0.08,
            width=0.05,
            elastic_modulus=70.0e9,
        )
        element = PathBeamEditor.ordered_elements(project)[1]
        rendered, _physical = self._rendered_surface_point(
            project,
            element,
            0.42,
            305.0,
            3.0,
        )

        location = PathBeamEditor.surface_location_from_point(
            project,
            rendered,
            display_scale=3.0,
        )

        self.assertEqual(location.element_index, 1)
        self.assertEqual(location.element_id, element.identifier)
        self.assertAlmostEqual(location.local_coordinate, 0.42, places=10)
        self.assertGreater(location.path_distance, 1.0)
        self.assertAlmostEqual(location.surface_angle_degrees, 305.0, places=10)

    def test_surface_pick_supports_every_uniform_section_shape(self):
        cases = (
            ("rectangle", {"height": 0.2, "width": 0.1}, 28.0),
            ("circle", {"diameter": 0.16}, 73.0),
            (
                "circular_tube",
                {"outer_diameter": 0.18, "wall_thickness": 0.02},
                142.0,
            ),
            (
                "box",
                {"outer_height": 0.2, "outer_width": 0.12, "wall_thickness": 0.015},
                224.0,
            ),
            (
                "i_section",
                {
                    "height": 0.22,
                    "flange_width": 0.13,
                    "flange_thickness": 0.025,
                    "web_thickness": 0.014,
                },
                318.0,
            ),
        )
        for shape, parameters, angle in cases:
            with self.subTest(shape=shape):
                project = PathBeamEditor.create_straight_beam(
                    empty_beam_project(),
                    length=1.5,
                    element_count=1,
                )
                if shape in {"circle", "circular_tube"}:
                    thickness = (
                        parameters["diameter"]
                        if shape == "circle"
                        else parameters["outer_diameter"]
                    )
                    width = thickness
                elif shape == "box":
                    thickness = parameters["outer_height"]
                    width = parameters["outer_width"]
                else:
                    thickness = parameters["height"]
                    width = parameters.get("width", parameters.get("flange_width"))
                project = PathBeamEditor.update_primary_properties(
                    project,
                    thickness=thickness,
                    width=width,
                    elastic_modulus=206.0e9,
                    section_shape=shape,
                    section_parameters=parameters,
                )
                element = project.elements[0]
                rendered, physical = self._rendered_surface_point(
                    project,
                    element,
                    0.58,
                    angle,
                    3.5,
                )

                location = PathBeamEditor.surface_location_from_point(
                    project,
                    rendered,
                    display_scale=3.5,
                )

                self.assertAlmostEqual(location.local_coordinate, 0.58, places=10)
                self.assertAlmostEqual(location.surface_angle_degrees, angle, places=10)
                np.testing.assert_allclose(location.global_position, physical, atol=1.0e-12)


if __name__ == "__main__":
    unittest.main()
