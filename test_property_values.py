"""Property form adapters are exercised without constructing any Qt widgets."""

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ifem.domain.project import (
    MaterialDefinition,
    ProjectDocument,
    SectionDefinition,
    empty_beam_project,
)
from ifem.modeling.path_editor import PathBeamEditor
from ifem.ui.property_values import (
    GLOBAL_KEY,
    PropertyInputError,
    apply_property_values,
    property_values,
)


class PropertyValuesTests(unittest.TestCase):
    def setUp(self):
        self.project = empty_beam_project()
        self.node_key = ("node", self.project.nodes[-1].identifier)
        self.element_key = ("element", self.project.elements[0].identifier)
        self.sensor_project = PathBeamEditor.add_sensor(
            self.project, self.element_key[1], 0.5, "top",
        )
        self.sensor_key = ("sensor", self.sensor_project.sensors[0].identifier)

    def assert_field_error(self, project, key, field, value):
        original = project.to_dict()
        values = property_values(project, key)
        values[field] = value
        with self.assertRaises(PropertyInputError) as caught:
            apply_property_values(project, key, values)
        self.assertEqual(caught.exception.field, field)
        self.assertTrue(str(caught.exception))
        self.assertEqual(project.to_dict(), original)

    def test_read_formats_match_forms_and_hidden_parameters_are_empty(self):
        self.assertEqual(property_values(self.project, self.node_key), {"x": "1", "y": "0", "z": "0"})
        self.assertEqual(property_values(self.project, self.element_key), {
            "family": "beam2d_euler_bernoulli",
            "section": self.project.sections[0].identifier,
            "material": self.project.materials[0].identifier,
        })
        self.assertEqual(property_values(self.project, GLOBAL_KEY), {
            "shape": "rectangle", "parameter_0": "0.001", "parameter_1": "0.001",
            "parameter_2": "", "parameter_3": "", "modulus": "",
        })

    def test_empty_project_uses_form_defaults(self):
        project = ProjectDocument("empty", "空项目", nodes=(), elements=())
        values = property_values(project, GLOBAL_KEY)
        self.assertEqual(values["parameter_0"], "0.1")
        self.assertEqual(values["parameter_1"], "0.1")
        updated = apply_property_values(project, GLOBAL_KEY, values)
        self.assertEqual(updated.sections[0].thickness, 0.1)
        self.assertEqual(project.sections, ())

    def test_missing_entity_is_not_a_user_field_error(self):
        for key in (("node", "gone"), ("element", "gone"), ("sensor", "gone"), ("other", "")):
            with self.subTest(key=key):
                with self.assertRaises(KeyError):
                    property_values(self.project, key)
                with self.assertRaises(KeyError):
                    apply_property_values(self.project, key, {})

    def test_node_edit_is_immutable_and_preserves_unedited_precision(self):
        node = replace(self.project.nodes[-1], coordinates=(1.1234567890123456, 0.0, 0.0))
        project = self.project.revised(nodes=(self.project.nodes[0], node))
        values = property_values(project, self.node_key)
        values["y"] = "0.2"
        updated = apply_property_values(project, self.node_key, values)
        self.assertEqual(updated.nodes[-1].coordinates, (node.coordinates[0], 0.2, 0.0))
        self.assertEqual(project.nodes[-1].coordinates, node.coordinates)

    def test_node_finite_and_two_dimensional_validation(self):
        for field, value in (("x", "NaN"), ("y", "inf"), ("x", ""), ("z", "1")):
            with self.subTest(field=field, value=value):
                self.assert_field_error(self.project, self.node_key, field, value)
        project = PathBeamEditor.set_modeling_space(self.project, "3d")
        values = property_values(project, self.node_key)
        values["z"] = "2"
        self.assertEqual(apply_property_values(project, self.node_key, values).nodes[-1].coordinates[2], 2)

    def test_node_domain_error_stays_field_addressable(self):
        self.assert_field_error(self.project, self.node_key, "x", "0")

    def test_element_reference_validation_and_extension_family(self):
        for field in ("section", "material"):
            self.assert_field_error(self.project, self.element_key, field, "missing")
        self.assert_field_error(self.project, self.element_key, "family", "")
        values = property_values(self.project, self.element_key)
        values.update(family="plugin_beam", section=None, material=None)
        updated = apply_property_values(self.project, self.element_key, values)
        self.assertEqual(updated.elements[0].family, "plugin_beam")
        self.assertIsNone(updated.elements[0].section_id)

    def test_arc_material_change_does_not_rebuild_geometry(self):
        project = PathBeamEditor.create_circular_arc(
            self.project, radius=2.123456789012345, sweep_degrees=37.123456789012345,
        )
        key = ("element", project.elements[0].identifier)
        values = property_values(project, key)
        values["material"] = None
        with patch.object(PathBeamEditor, "update_circular_arc", side_effect=AssertionError("unexpected rebuild")):
            updated = apply_property_values(project, key, values)
        self.assertEqual(updated.nodes, project.nodes)
        self.assertEqual(updated.elements[0].geometry, project.elements[0].geometry)

    def test_arc_validation_and_actual_edit(self):
        project = PathBeamEditor.create_circular_arc(self.project, radius=2.0, sweep_degrees=90.0)
        key = ("element", project.elements[0].identifier)
        for field, value in (("radius", "0"), ("sweep", "360"), ("sweep", "0"), ("plane", "invalid"), ("family", "beam3d_line")):
            with self.subTest(field=field, value=value):
                self.assert_field_error(project, key, field, value)
        values = property_values(project, key)
        values.update(radius="3", sweep="-45", plane="xz")
        updated = apply_property_values(project, key, values)
        self.assertEqual(updated.modeling_space, "3d")
        self.assertEqual(updated.elements[0].geometry.parameters["radius"], 3.0)
        self.assertEqual(updated.elements[0].geometry.parameters["sweep_degrees"], -45.0)
        self.assertEqual(project.modeling_space, "2d")

    def test_sensor_read_presets_and_authoritative_angle(self):
        values = property_values(self.sensor_project, self.sensor_key)
        self.assertEqual(values["surface"], "top")
        values.update(surface="top", surface_angle="540", orientation_angle="390")
        updated = apply_property_values(self.sensor_project, self.sensor_key, values)
        self.assertEqual(updated.sensors[0].attachment.surface_angle_degrees, 180)
        self.assertEqual(updated.sensors[0].attachment.orientation_angle_degrees, 30)
        self.assertEqual(property_values(updated, self.sensor_key)["surface"], "bottom")
        values = property_values(updated, self.sensor_key)
        values["surface_angle"] = "75"
        updated = apply_property_values(updated, self.sensor_key, values)
        self.assertEqual(property_values(updated, self.sensor_key)["surface"], "custom")

    def test_sensor_field_validation(self):
        cases = (
            ("label", "   "), ("element", "missing"), ("xi", "1.1"),
            ("surface_angle", "NaN"), ("orientation_angle", "inf"),
            ("strain", "abc"), ("weight", "0"), ("zone_a", "-0.1"),
            ("zone_b", "1.1"), ("zone_b", "0.1"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                self.assert_field_error(self.sensor_project, self.sensor_key, field, value)

    def test_sensor_data_edit_keeps_original_direction_and_precise_values(self):
        sensor = self.sensor_project.sensors[0]
        sensor = replace(sensor, measured_value=1.234567890123456e-4, attachment=replace(
            sensor.attachment, direction=(0.0, 1.0, 0.0),
        ))
        project = self.sensor_project.revised(sensors=(sensor,))
        values = property_values(project, self.sensor_key)
        values["label"] = "新名称"
        updated = apply_property_values(project, self.sensor_key, values)
        self.assertEqual(updated.sensors[0].measured_value, sensor.measured_value)
        self.assertEqual(updated.sensors[0].attachment.direction, sensor.attachment.direction)
        self.assertEqual(project.sensors[0], sensor)

    def test_sensor_missing_measurement_is_not_populated_by_label_edit(self):
        project = self.sensor_project.revised(sensors=(replace(
            self.sensor_project.sensors[0], measured_value=None,
        ),))
        values = property_values(project, self.sensor_key)
        self.assertEqual(values["strain"], "")
        values["label"] = "尚未采集"
        self.assertIsNone(apply_property_values(project, self.sensor_key, values).sensors[0].measured_value)

    def test_sensor_explicit_zero_is_a_measurement_not_missing_data(self):
        project = self.sensor_project.revised(sensors=(replace(
            self.sensor_project.sensors[0], measured_value=None,
        ),))
        values = property_values(project, self.sensor_key)
        self.assertEqual(values["strain"], "")
        values["strain"] = "0"
        updated = apply_property_values(project, self.sensor_key, values)
        self.assertEqual(updated.sensors[0].measured_value, 0.0)
        self.assertEqual(property_values(updated, self.sensor_key)["strain"], "0")
        self.assertIsNone(project.sensors[0].measured_value)

    def test_sensor_clearing_measurement_restores_missing_state(self):
        project = self.sensor_project.revised(sensors=(replace(
            self.sensor_project.sensors[0], measured_value=0.004,
        ),))
        for blank in ("", "   "):
            with self.subTest(blank=blank):
                values = property_values(project, self.sensor_key)
                values["strain"] = blank
                updated = apply_property_values(project, self.sensor_key, values)
                self.assertIsNone(updated.sensors[0].measured_value)
                self.assertEqual(property_values(updated, self.sensor_key)["strain"], "")
                self.assertEqual(project.sensors[0].measured_value, 0.004)

    def test_sensor_integration_bounds_recalculate_physical_gauge_length(self):
        values = property_values(self.sensor_project, self.sensor_key)
        values.update(zone_a="0.1", zone_b="0.9", weight="2")
        updated = apply_property_values(self.sensor_project, self.sensor_key, values)
        self.assertEqual(updated.sensors[0].attachment.integration_bounds, (0.1, 0.9))
        self.assertAlmostEqual(updated.sensors[0].attachment.gauge_length, 0.8)
        self.assertEqual(updated.sensors[0].weight, 2)

    def test_primary_all_shape_constraints_pin_the_affected_dimension(self):
        cases = (
            ("circle", ("-1",), "parameter_0"),
            ("circular_tube", ("1", "0.5"), "parameter_1"),
            ("box", ("1", "1", "0.5"), "parameter_2"),
            ("i_section", ("1", "1", "0.5", "0.1"), "parameter_2"),
            ("i_section", ("1", "1", "0.1", "1"), "parameter_3"),
        )
        for shape, dimensions, error_field in cases:
            with self.subTest(shape=shape, error_field=error_field):
                values = property_values(self.project, GLOBAL_KEY)
                values.update(shape=shape, **{f"parameter_{i}": value for i, value in enumerate(dimensions)})
                with self.assertRaises(PropertyInputError) as caught:
                    apply_property_values(self.project, GLOBAL_KEY, values)
                self.assertEqual(caught.exception.field, error_field)

    def test_primary_modulus_units_blank_and_overflow(self):
        values = property_values(self.project, GLOBAL_KEY)
        values["modulus"] = "210"
        updated = apply_property_values(self.project, GLOBAL_KEY, values)
        self.assertEqual(updated.materials[0].elastic_modulus, 210e9)
        self.assertEqual(property_values(updated, GLOBAL_KEY)["modulus"], "210")
        values["modulus"] = " "
        self.assertIsNone(apply_property_values(updated, GLOBAL_KEY, values).materials[0].elastic_modulus)
        for raw in ("-1", "NaN", "1e308"):
            self.assert_field_error(self.project, GLOBAL_KEY, "modulus", raw)

    def test_primary_keeps_existing_dimension_and_modulus_precision(self):
        section = SectionDefinition(self.project.sections[0].identifier, "精确截面", 0.1234567890123456)
        material = MaterialDefinition(self.project.materials[0].identifier, "精确材料", 123456789012.34567)
        project = self.project.revised(sections=(section,), materials=(material,))
        values = property_values(project, GLOBAL_KEY)
        values["parameter_1"] = "0.2"
        updated = apply_property_values(project, GLOBAL_KEY, values)
        self.assertEqual(updated.sections[0].thickness, section.thickness)
        self.assertEqual(updated.materials[0].elastic_modulus, material.elastic_modulus)

    def test_merged_current_values_keep_unrelated_latest_changes(self):
        latest = PathBeamEditor.update_sensor(
            self.sensor_project, self.sensor_key[1],
            element_id=self.element_key[1], local_coordinate=0.6,
            surface_side="bottom", direction=(1.0, 0.0, 0.0),
            measured_value=0.004, weight=3, zone_a=0.3, zone_b=0.8,
            surface_angle_degrees=180, orientation_angle_degrees=10,
        )
        values = {**property_values(latest, self.sensor_key), "label": "草稿名称"}
        updated = apply_property_values(latest, self.sensor_key, values)
        self.assertEqual(updated.sensors[0].label, "草稿名称")
        self.assertEqual(updated.sensors[0].weight, 3)
        self.assertEqual(updated.sensors[0].attachment.local_coordinates, (0.6,))
        self.assertEqual(updated.sensors[0].measured_value, 0.004)


if __name__ == "__main__":
    unittest.main()
