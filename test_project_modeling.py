import tempfile
import unittest
from pathlib import Path

import numpy as np

from config_adapter import get_sample_config, run_reconstruction
from ifem.domain.project import (
    CURRENT_PROJECT_SCHEMA_VERSION,
    ProjectDocument,
    empty_beam_project,
)
from ifem.infrastructure.legacy_project import (
    legacy_config_from_project,
    project_from_legacy_config,
)
from ifem.infrastructure.project_io import load_project, save_project
from ifem.modeling.beam_editor import BeamProjectEditor
from ifem.modeling.path_editor import PathBeamEditor


class ProjectDocumentTests(unittest.TestCase):
    def setUp(self):
        self.config = get_sample_config()
        self.project = project_from_legacy_config(self.config)

    def test_legacy_round_trip_preserves_solver_result(self):
        original_model, _ = run_reconstruction(self.config)
        converted = legacy_config_from_project(self.project)
        converted_model, _ = run_reconstruction(converted)

        np.testing.assert_allclose(converted["node_x"], self.config["node_x"])
        np.testing.assert_allclose(converted_model.U, original_model.U, rtol=1.0e-12, atol=1.0e-14)
        self.assertEqual(
            sum(len(item["measurements"]) for item in converted["elements_sensor_data"]),
            12,
        )

    def test_project_dictionary_and_file_round_trip_keep_ids(self):
        restored = ProjectDocument.from_dict(self.project.to_dict())
        self.assertEqual(restored.identifier, self.project.identifier)
        self.assertEqual(
            [node.identifier for node in restored.nodes],
            [node.identifier for node in self.project.nodes],
        )
        self.assertEqual(
            [sensor.identifier for sensor in restored.sensors],
            [sensor.identifier for sensor in self.project.sensors],
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.ifemproj"
            save_project(path, self.project)
            loaded = load_project(path)
        self.assertEqual(loaded.to_dict(), self.project.to_dict())

    def test_schema_v1_straight_elements_migrate_to_line_geometry(self):
        payload = self.project.to_dict()
        payload["schema_version"] = 1
        for element in payload["elements"]:
            element.pop("geometry", None)

        restored = ProjectDocument.from_dict(payload)

        self.assertEqual(restored.schema_version, CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertTrue(all(element.geometry.kind == "line" for element in restored.elements))

    def test_schema_v2_sensor_surfaces_migrate_to_circumferential_angles(self):
        payload = self.project.to_dict()
        payload["schema_version"] = 2
        expected = []
        for sensor in payload["sensors"]:
            attachment = sensor["attachment"]
            expected.append(0.0 if attachment["surface_side"] == "top" else 180.0)
            attachment.pop("surface_angle_degrees", None)
            attachment.pop("orientation_angle_degrees", None)

        restored = ProjectDocument.from_dict(payload)

        self.assertEqual(restored.schema_version, CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(
            [sensor.attachment.surface_angle_degrees for sensor in restored.sensors],
            expected,
        )
        self.assertTrue(
            all(sensor.attachment.orientation_angle_degrees == 0.0 for sensor in restored.sensors)
        )

    def test_schema_v3_sections_migrate_to_explicit_rectangle_profiles(self):
        payload = self.project.to_dict()
        payload["schema_version"] = 3
        for section in payload["sections"]:
            section.pop("shape", None)
            section.pop("parameters", None)

        restored = ProjectDocument.from_dict(payload)

        section = restored.sections[0]
        self.assertEqual(section.shape, "rectangle")
        self.assertEqual(section.parameters["height"], section.thickness)
        self.assertEqual(section.parameters["width"], section.width)

    def test_schema_v4_projects_infer_the_modeling_space(self):
        payload = self.project.to_dict()
        payload["schema_version"] = 4
        payload.pop("modeling_space", None)

        restored = ProjectDocument.from_dict(payload)

        self.assertEqual(restored.schema_version, CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(restored.modeling_space, "2d")

        spatial = PathBeamEditor.create_circular_arc(
            empty_beam_project(modeling_space="3d"),
            radius=1.5,
            sweep_degrees=90.0,
            plane="xz",
        )
        spatial_payload = spatial.to_dict()
        spatial_payload["schema_version"] = 4
        spatial_payload.pop("modeling_space", None)

        restored_spatial = ProjectDocument.from_dict(spatial_payload)
        self.assertEqual(restored_spatial.modeling_space, "3d")

        planar_3d = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
            axis="x",
        )
        planar_payload = planar_3d.to_dict()
        planar_payload["schema_version"] = 4
        planar_payload.pop("modeling_space", None)

        restored_planar = ProjectDocument.from_dict(planar_payload)
        self.assertEqual(restored_planar.modeling_space, "3d")


class BeamProjectEditorTests(unittest.TestCase):
    def setUp(self):
        self.project = project_from_legacy_config(get_sample_config())

    def test_add_node_remaps_sensors_without_moving_measurement_points(self):
        before = {
            sensor.identifier: BeamProjectEditor.sensor_location(
                self.project, sensor.identifier
            ).global_x
            for sensor in self.project.sensors
        }
        updated = BeamProjectEditor.add_node(self.project, 0.5)

        self.assertEqual(len(updated.nodes), len(self.project.nodes) + 1)
        self.assertEqual(len(updated.elements), len(self.project.elements) + 1)
        self.assertEqual(len(updated.sensors), len(self.project.sensors))
        for sensor in updated.sensors:
            after_x = BeamProjectEditor.sensor_location(updated, sensor.identifier).global_x
            self.assertAlmostEqual(after_x, before[sensor.identifier])

    def test_move_node_keeps_sensor_attached_to_same_element(self):
        nodes = BeamProjectEditor.ordered_nodes(self.project)
        sensor = self.project.sensors[4]
        element_id = sensor.attachment.entity_id
        xi = sensor.attachment.local_coordinates[0]

        updated = BeamProjectEditor.move_node(self.project, nodes[1].identifier, 1.1)
        moved_sensor = next(item for item in updated.sensors if item.identifier == sensor.identifier)

        self.assertEqual(moved_sensor.attachment.entity_id, element_id)
        self.assertAlmostEqual(moved_sensor.attachment.local_coordinates[0], xi)

    def test_uniform_beam_generation_preserves_endpoint_constraints(self):
        updated = BeamProjectEditor.create_uniform_beam(
            self.project,
            length=6.0,
            element_count=6,
        )
        nodes = BeamProjectEditor.ordered_nodes(updated)

        self.assertEqual(len(nodes), 7)
        self.assertEqual(len(updated.elements), 6)
        self.assertEqual(len(updated.sensors), 0)
        self.assertTrue(
            any(boundary.node_id == nodes[0].identifier for boundary in updated.boundary_conditions)
        )
        self.assertTrue(
            any(boundary.node_id == nodes[-1].identifier for boundary in updated.boundary_conditions)
        )

    def test_sensor_add_update_and_delete(self):
        added = BeamProjectEditor.add_sensor(self.project, 1.5, "top")
        sensor = added.sensors[-1]
        location = BeamProjectEditor.sensor_location(added, sensor.identifier)
        self.assertAlmostEqual(location.global_x, 1.5)
        self.assertEqual(sensor.attachment.surface_side, "top")

        updated = BeamProjectEditor.update_sensor(
            added,
            sensor.identifier,
            global_x=1.6,
            surface_side="bottom",
            measured_value=-1.25e-4,
            weight=0.75,
            zone_a=0.4,
            zone_b=0.8,
        )
        changed = next(item for item in updated.sensors if item.identifier == sensor.identifier)
        changed_location = BeamProjectEditor.sensor_location(updated, sensor.identifier)
        self.assertAlmostEqual(changed_location.global_x, 1.6)
        self.assertEqual(changed.attachment.surface_side, "bottom")
        self.assertAlmostEqual(changed.measured_value, -1.25e-4)
        self.assertAlmostEqual(changed.weight, 0.75)

        deleted = BeamProjectEditor.delete_sensor(updated, sensor.identifier)
        self.assertEqual(len(deleted.sensors), len(self.project.sensors))


if __name__ == "__main__":
    unittest.main()
