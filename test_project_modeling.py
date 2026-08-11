import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from config_adapter import get_sample_config, run_reconstruction
from ifem.domain.analysis import AlgorithmMetadata, InputValidationError
from ifem.domain.project import (
    CURRENT_PROJECT_SCHEMA_VERSION,
    AnalysisCase,
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

    def test_legacy_projection_uses_element_references_and_preserves_surface_depth(self):
        referenced_section = replace(
            self.project.sections[0],
            identifier="section_referenced",
            thickness=0.25,
            parameters={},
        )
        referenced_material = replace(
            self.project.materials[0],
            identifier="material_referenced",
            elastic_modulus=123.0e9,
        )
        referenced_project = self.project.revised(
            sections=self.project.sections + (referenced_section,),
            materials=self.project.materials + (referenced_material,),
            elements=tuple(
                replace(
                    element,
                    section_id=referenced_section.identifier,
                    material_id=referenced_material.identifier,
                )
                for element in self.project.elements
            ),
        )

        projected = legacy_config_from_project(referenced_project)

        self.assertEqual(projected["thickness"], referenced_section.thickness)
        self.assertEqual(
            projected["material"]["elastic_modulus"],
            referenced_material.elastic_modulus,
        )

        surface_config = copy.deepcopy(self.config)
        half_thickness = float(surface_config["thickness"]) / 2.0
        measurement = surface_config["elements_sensor_data"][0]["measurements"][0]
        measurement["surface"] = "top"
        measurement["y"] = -half_thickness
        surface_project = project_from_legacy_config(surface_config)
        self.assertEqual(surface_project.sensors[0].attachment.surface_side, "bottom")
        self.assertEqual(
            legacy_config_from_project(surface_project)["elements_sensor_data"][0][
                "measurements"
            ][0]["surface"],
            "bot",
        )

        measurement["y"] = half_thickness * 0.4
        with self.assertRaises(InputValidationError) as captured:
            project_from_legacy_config(surface_config)
        self.assertEqual(captured.exception.field, "/measurements/0/y")

    def test_geometry_contract_rejects_disconnected_arcs_and_nurbs_breaks(self):
        arc = PathBeamEditor.create_circular_arc(
            empty_beam_project(modeling_space="2d"),
            radius=1.5,
            sweep_degrees=90.0,
            plane="xy",
        )
        disconnected = arc.to_dict()
        endpoint = disconnected["nodes"][1]["coordinates"]
        disconnected["nodes"][1]["coordinates"] = (
            endpoint[0] + 0.25,
            endpoint[1],
            endpoint[2],
        )
        with self.assertRaisesRegex(ValueError, "几何端点必须与结构节点一致"):
            ProjectDocument.from_dict(disconnected)

        wrong_plane = arc.to_dict()
        wrong_plane["elements"][0]["geometry"]["parameters"]["normal"] = (
            2.0**-0.5,
            0.0,
            2.0**-0.5,
        )
        with self.assertRaisesRegex(ValueError, "法向与 XY 平面不一致"):
            ProjectDocument.from_dict(wrong_plane)

        with self.assertRaisesRegex(ValueError, "内部节点重数"):
            PathBeamEditor.create_nurbs_curve(
                empty_beam_project(modeling_space="3d"),
                control_points=(
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (10.0, 0.0, 0.0),
                    (11.0, 0.0, 0.0),
                ),
                degree=1,
                knots=(0.0, 0.0, 0.5, 0.5, 1.0, 1.0),
            )

        with self.assertRaisesRegex(ValueError, "零速点或尖点"):
            PathBeamEditor.create_nurbs_curve(
                empty_beam_project(modeling_space="3d"),
                control_points=(
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                ),
                degree=3,
            )

        with self.assertRaisesRegex(ValueError, "比例不能超过 1e6"):
            PathBeamEditor.create_nurbs_curve(
                empty_beam_project(modeling_space="3d"),
                control_points=(
                    (0.0, 0.0, 0.0),
                    (1.0, 1.0, 0.0),
                    (2.0, 0.0, 0.0),
                ),
                degree=2,
                weights=(1.0, 1.0e7, 1.0),
            )

        parametric = PathBeamEditor.create_parametric_curve(
            empty_beam_project(modeling_space="3d"),
            expressions={
                "x": "t",
                "y": "0",
                "z": "sin(2*pi*t)",
            },
        )
        disguised_2d = parametric.to_dict()
        disguised_2d["modeling_space"] = "2d"
        with self.assertRaisesRegex(ValueError, "参数曲线必须位于 XY 平面"):
            ProjectDocument.from_dict(disguised_2d)

        disconnected_parametric = parametric.to_dict()
        disconnected_parametric["nodes"][1]["coordinates"] = (2.0, 0.0, 0.0)
        with self.assertRaisesRegex(ValueError, "表达式端点必须与结构节点一致"):
            ProjectDocument.from_dict(disconnected_parametric)

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

    def test_schema_v5_analysis_cases_migrate_without_inferred_plugin_versions(self):
        payload = self.project.to_dict()
        payload["schema_version"] = 5
        for analysis_case in payload["analysis_cases"]:
            analysis_case.pop("algorithm_version", None)
            analysis_case.pop("parameter_schema_version", None)

        restored = ProjectDocument.from_dict(payload)

        self.assertEqual(restored.schema_version, CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(CURRENT_PROJECT_SCHEMA_VERSION, 7)
        self.assertIsNone(restored.analysis_cases[0].algorithm_version)
        self.assertIsNone(restored.analysis_cases[0].parameter_schema_version)
        self.assertEqual(
            restored.analysis_cases[0].parameters,
            self.project.analysis_cases[0].parameters,
        )

    def test_project_schema_and_analysis_case_shapes_fail_before_partial_loading(self):
        payload = self.project.to_dict()
        payload["schema_version"] = 6.9
        with self.assertRaisesRegex(ValueError, "schema_version 必须是整数"):
            ProjectDocument.from_dict(payload)

        payload = self.project.to_dict()
        payload["schema_version"] = CURRENT_PROJECT_SCHEMA_VERSION + 1
        payload["analysis_cases"] = [None]
        with self.assertRaisesRegex(ValueError, "不支持的项目版本"):
            ProjectDocument.from_dict(payload)

        payload = self.project.to_dict()
        payload["analysis_cases"] = [None]
        with self.assertRaisesRegex(ValueError, r"analysis_cases\[0\] 必须是对象"):
            ProjectDocument.from_dict(payload)

        payload = self.project.to_dict()
        payload["vendor_extension"] = {"opaque": True}
        with self.assertRaisesRegex(ValueError, "不支持的字段.*vendor_extension"):
            ProjectDocument.from_dict(payload)

    def test_schema_v6_migrates_to_v7_and_preserves_opaque_parameters(self):
        source_parameters = {
            "gauss_n": 4,
            "plugin_state": {
                "enabled": True,
                "weights": [1, 2.5, None, "原样保留"],
            },
        }
        analysis_case = replace(
            self.project.analysis_cases[0],
            algorithm_version="1.0.0",
            parameter_schema_version="2",
            parameters=source_parameters,
        )
        source_parameters["plugin_state"]["weights"].append("外部修改")
        versioned = self.project.revised(analysis_cases=(analysis_case,))

        self.assertEqual(
            analysis_case.parameters["plugin_state"]["weights"],
            [1, 2.5, None, "原样保留"],
        )
        payload = versioned.to_dict()
        payload["schema_version"] = 6
        migrated = ProjectDocument.from_dict(payload)
        self.assertEqual(migrated.schema_version, 7)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versioned.ifemproj"
            save_project(path, migrated)
            restored = load_project(path)

        self.assertEqual(restored.to_dict(), migrated.to_dict())
        self.assertEqual(restored.analysis_cases[0].algorithm_version, "1.0.0")
        self.assertEqual(restored.analysis_cases[0].parameter_schema_version, "2")

    def test_analysis_case_rejects_non_json_parameter_values(self):
        invalid_parameters = (
            ({1: "non-string-key"}, "对象键必须是字符串"),
            ({"value": float("nan")}, "必须是有限数"),
            ({"value": float("inf")}, "必须是有限数"),
            ({"value": {1, 2}}, "不支持的 JSON 值类型"),
        )
        for parameters, message in invalid_parameters:
            with self.subTest(parameters=parameters):
                with self.assertRaisesRegex(ValueError, message):
                    AnalysisCase(
                        identifier="analysis_invalid",
                        name="非法参数工况",
                        algorithm_id="example.algorithm",
                        parameters=parameters,
                    )

        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaisesRegex(ValueError, "循环引用"):
            AnalysisCase(
                identifier="analysis_cyclic",
                name="循环参数工况",
                algorithm_id="example.algorithm",
                parameters={"value": cyclic},
            )

    def test_save_project_rejects_late_non_finite_values_without_replacing_file(self):
        path_contents = "existing-project"
        self.project.analysis_cases[0].parameters["late_nan"] = float("nan")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.ifemproj"
            path.write_text(path_contents, encoding="utf-8")
            with self.assertRaises(ValueError):
                save_project(path, self.project)
            self.assertEqual(path.read_text(encoding="utf-8"), path_contents)

    def test_analysis_domain_versions_and_field_errors_are_stable(self):
        metadata = AlgorithmMetadata("example.algorithm", "示例算法", "1.2.3")
        self.assertEqual(metadata.parameter_schema_version, "1")
        with self.assertRaisesRegex(ValueError, "参数模式版本不能为空"):
            AlgorithmMetadata(
                "example.algorithm",
                "示例算法",
                "1.2.3",
                parameter_schema_version=" ",
            )

        case = AnalysisCase("case", "示例工况", "  example.algorithm  ")
        self.assertEqual(case.algorithm_id, "example.algorithm")

        error = InputValidationError("输入无效", "sensors[0].measured_value")
        self.assertEqual(str(error), "输入无效")
        self.assertEqual(error.field, "sensors[0].measured_value")

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
