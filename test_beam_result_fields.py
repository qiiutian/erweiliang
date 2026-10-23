from __future__ import annotations

import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from config_adapter import get_sample_config
from ifem.algorithms.beam_result_fields import build_beam_result_fields
from ifem.application.analysis_service import (
    AlgorithmValidationError,
    create_default_analysis_service,
)
from ifem.domain.analysis import ResultField
from ifem.infrastructure import project_from_legacy_config
from test_algorithm_plugins import EXPECTED_SAMPLE_DISPLACEMENT


class BeamResultFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = get_sample_config()
        cls.config["points_per_element"] = 7
        cls.project = project_from_legacy_config(cls.config)
        cls.service = create_default_analysis_service()
        cls.result = cls.service.run_project(cls.project)

    @staticmethod
    def locations(result, association):
        return {
            location.entity_id: location
            for location in result.locations
            if location.association == association
        }

    def test_solver_returns_typed_declared_si_fields_without_numerical_change(self):
        result = self.result
        np.testing.assert_allclose(
            result.native_model.U, EXPECTED_SAMPLE_DISPLACEMENT,
            rtol=1.0e-12, atol=1.0e-14,
        )
        self.assertEqual(set(result.fields), {
            "displacement", "rotation", "axial_strain", "axial_stress",
            "sensor_measured_strain", "sensor_reconstructed_strain", "sensor_strain_residual",
        })
        for field in result.fields.values():
            self.assertIsInstance(field, ResultField)
        self.assertEqual(result.fields["displacement"].unit, "m")
        self.assertEqual(result.fields["rotation"].unit, "rad")
        self.assertEqual(result.fields["axial_strain"].unit, "1")
        self.assertEqual(result.fields["axial_stress"].unit, "Pa")
        self.assertEqual(result.fields["displacement"].values, result.state.displacements)
        self.assertEqual(result.fields["rotation"].values, result.state.rotations)
        self.assertEqual(result.fields["displacement"].entity_ids, result.state.node_ids)

    def test_raw_samples_match_exact_element_kinematics_and_stress(self):
        model = self.result.native_model
        strain = self.result.fields["axial_strain"]
        stress = self.result.fields["axial_stress"]
        locations = self.locations(self.result, "sample")
        self.assertEqual(strain.components, ("top", "bottom"))
        self.assertEqual(strain.entity_ids, stress.entity_ids)
        self.assertEqual(len(strain.entity_ids), model.n_elems * 7)
        cursor = 0
        for element in range(model.n_elems):
            length = float(model.node_x[element + 1] - model.node_x[element])
            element_u = model.U[model.element_dofs(element)]
            for local_x in np.linspace(0.0, length, 7):
                expected = tuple(float(model.B_surface(local_x, length, y) @ element_u)
                                 for y in (model.h, -model.h))
                self.assertEqual(strain.values[cursor], expected)
                np.testing.assert_allclose(stress.values[cursor], np.asarray(expected) * 2.06e11)
                location = locations[strain.entity_ids[cursor]]
                self.assertEqual(location.source_entity_id, self.result.state.element_ids[element])
                self.assertAlmostEqual(location.reference_position[0], model.node_x[element] + local_x)
                cursor += 1

    def test_both_raw_boundary_values_and_identities_are_retained(self):
        field = self.result.fields["axial_strain"]
        locations = self.locations(self.result, "sample")
        for element in range(self.result.native_model.n_elems - 1):
            left = locations[field.entity_ids[(element + 1) * 7 - 1]]
            right = locations[field.entity_ids[(element + 1) * 7]]
            self.assertEqual(left.reference_position, right.reference_position)
            np.testing.assert_allclose(left.position, right.position)
            self.assertNotEqual(left.entity_id, right.entity_id)
            self.assertNotEqual(left.source_entity_id, right.source_entity_id)

    def test_missing_modulus_omits_stress_instead_of_manufacturing_zero(self):
        config = copy.deepcopy(self.config)
        config["material"]["elastic_modulus"] = None
        result = self.service.run(config)
        self.assertIn("axial_strain", result.fields)
        self.assertNotIn("axial_stress", result.fields)

    def test_sensor_values_are_direct_pointwise_reconstructed_minus_measured(self):
        result = self.result
        model = result.native_model
        observed = result.fields["sensor_measured_strain"]
        reconstructed = result.fields["sensor_reconstructed_strain"]
        residual = result.fields["sensor_strain_residual"]
        self.assertEqual(observed.entity_ids, tuple(sensor.identifier for sensor in self.project.sensors))
        self.assertEqual(observed.entity_ids, reconstructed.entity_ids)
        self.assertEqual(observed.entity_ids, residual.entity_ids)
        self.assertEqual(residual.unit, "1")
        self.assertEqual(residual.components, ("axial",))
        locations = self.locations(result, "sensor")
        for index, sensor in enumerate(self.project.sensors):
            element = result.state.element_ids.index(sensor.attachment.entity_id)
            length = float(model.node_x[element + 1] - model.node_x[element])
            local_x = sensor.attachment.local_coordinates[0] * length
            surface_y = model.h if sensor.attachment.surface_side == "top" else -model.h
            expected = float(model.B_surface(local_x, length, surface_y) @ model.U[model.element_dofs(element)])
            self.assertEqual(observed.values[index], (sensor.measured_value,))
            self.assertEqual(reconstructed.values[index], (expected,))
            self.assertEqual(residual.values[index], (expected - sensor.measured_value,))
            location = locations[sensor.identifier]
            self.assertEqual(location.reference_position, (model.node_x[element] + local_x, surface_y, 0.0))
            self.assertEqual(location.source_entity_id, sensor.attachment.entity_id)

    def test_sensor_point_location_includes_true_small_deformation_surface_offset(self):
        model = self.result.native_model
        sensor = self.project.sensors[0]
        element = self.result.state.element_ids.index(sensor.attachment.entity_id)
        length = model.node_x[element + 1] - model.node_x[element]
        local_x = sensor.attachment.local_coordinates[0] * length
        global_x = model.node_x[element] + local_x
        u, v = model.evaluate_displacement_at(global_x)
        derivative = model.dshape_dx(local_x, length)
        element_u = model.U[model.element_dofs(element)]
        slope = sum(derivative[index] * element_u[index] for index in (1, 2, 4, 5))
        y = model.h if sensor.attachment.surface_side == "top" else -model.h
        location = self.locations(self.result, "sensor")[sensor.identifier]
        np.testing.assert_allclose(location.position, (global_x + u - y * slope, y + v, 0.0))

    def test_reordered_sensors_nodes_elements_do_not_change_entity_mapping(self):
        project = replace(
            self.project,
            sensors=tuple(reversed(self.project.sensors)),
            # The existing path editor chooses its first endpoint from this
            # sequence; retain the same start while shuffling interior nodes.
            nodes=(self.project.nodes[0],) + tuple(reversed(self.project.nodes[1:-1])) + (self.project.nodes[-1],),
            elements=tuple(reversed(self.project.elements)),
        )
        result = self.service.run_project(project)
        self.assertEqual(result.fields["sensor_strain_residual"].entity_ids,
                         tuple(sensor.identifier for sensor in project.sensors))
        old = dict(zip(self.result.fields["sensor_strain_residual"].entity_ids,
                       self.result.fields["sensor_strain_residual"].values))
        new = dict(zip(result.fields["sensor_strain_residual"].entity_ids,
                       result.fields["sensor_strain_residual"].values))
        for identifier in old:
            np.testing.assert_allclose(new[identifier], old[identifier], rtol=1.0e-9, atol=1.0e-14)
        for identifier, location in self.locations(self.result, "sensor").items():
            actual = self.locations(result, "sensor")[identifier]
            self.assertEqual(actual.source_entity_id, location.source_entity_id)
            np.testing.assert_allclose(actual.reference_position, location.reference_position)
            np.testing.assert_allclose(actual.position, location.position, rtol=1.0e-9, atol=1.0e-12)

    def test_reversed_element_attachment_uses_solver_local_coordinate(self):
        elements = tuple(replace(element, node_ids=tuple(reversed(element.node_ids)))
                         for element in self.project.elements)
        sensors = tuple(replace(sensor, attachment=replace(
            sensor.attachment,
            local_coordinates=(1.0 - sensor.attachment.local_coordinates[0],),
            integration_bounds=(1.0 - sensor.attachment.integration_bounds[1],
                                1.0 - sensor.attachment.integration_bounds[0]),
        )) for sensor in self.project.sensors)
        result = self.service.run_project(replace(self.project, elements=elements, sensors=sensors))
        for identifier in ("sensor_measured_strain", "sensor_reconstructed_strain", "sensor_strain_residual"):
            np.testing.assert_allclose(result.fields[identifier].values,
                                       self.result.fields[identifier].values, rtol=1.0e-9, atol=1.0e-14)
        for identifier, location in self.locations(self.result, "sensor").items():
            np.testing.assert_allclose(self.locations(result, "sensor")[identifier].reference_position,
                                       location.reference_position)

    def test_sampling_density_and_display_recovery_never_change_residuals(self):
        with patch("postprocessing.recover_continuous_section_field", side_effect=AssertionError("display only")):
            sparse = self.service.run_project(self.project, parameters={"points_per_element": 2})
            dense = self.service.run_project(self.project, parameters={"points_per_element": 19})
        self.assertEqual(sparse.fields["sensor_strain_residual"], dense.fields["sensor_strain_residual"])
        np.testing.assert_array_equal(sparse.native_model.U, dense.native_model.U)

    def test_point_residual_is_not_the_integration_interval_average(self):
        original = self.project.sensors[0]
        moved = replace(original, attachment=replace(
            original.attachment, local_coordinates=(0.1,),
        ))
        project = replace(self.project, sensors=(moved,) + self.project.sensors[1:])
        result = self.service.run_project(project)
        model = result.native_model
        # The observation point is not used as a quadrature point by the
        # established local-integral solver: moving it does not alter U.
        np.testing.assert_array_equal(model.U, self.result.native_model.U)
        element = result.state.element_ids.index(moved.attachment.entity_id)
        length = model.node_x[element + 1] - model.node_x[element]
        element_u = model.U[model.element_dofs(element)]
        surface_y = model.h if moved.attachment.surface_side == "top" else -model.h
        point_value = float(model.B_surface(0.1 * length, length, surface_y) @ element_u)
        interval_midpoint = sum(moved.attachment.integration_bounds) * length / 2.0
        interval_average = float(model.B_surface(interval_midpoint, length, surface_y) @ element_u)
        value = result.fields["sensor_reconstructed_strain"].values[0][0]
        self.assertEqual(value, point_value)
        self.assertGreater(abs(value - interval_average), 1.0e-8)
        self.assertEqual(result.fields["sensor_strain_residual"].values[0],
                         (point_value - moved.measured_value,))

    def test_field_builder_resolves_reordered_state_entities_by_id(self):
        state = self.result.state
        node_order = tuple(reversed(range(len(state.node_ids))))
        element_order = tuple(reversed(range(len(state.element_ids))))
        reordered = replace(
            state,
            **{name: tuple(getattr(state, name)[index] for index in node_order)
               for name in ("node_ids", "reference_coordinates", "displacements", "reference_frames", "rotations")},
            element_ids=tuple(state.element_ids[index] for index in element_order),
            connectivity=tuple(tuple(reversed(state.connectivity[index])) for index in element_order),
        )
        fields, locations = build_beam_result_fields(
            self.result.native_model, inputs=self.result.inputs,
            state=reordered, project=self.project,
        )
        self.assertEqual(fields["displacement"].entity_ids, reordered.node_ids)
        self.assertEqual(fields["sensor_strain_residual"], self.result.fields["sensor_strain_residual"])
        for index, location in enumerate(item for item in locations if item.association == "sample"):
            self.assertEqual(location.source_entity_id, state.element_ids[index // 7])

    def test_field_builder_rejects_state_that_disagrees_with_native_solution(self):
        state = self.result.state
        for name in ("reference_coordinates", "displacements", "rotations"):
            rows = [list(row) for row in getattr(state, name)]
            rows[0][0] += 0.01
            with self.subTest(field=name), self.assertRaises(ValueError):
                build_beam_result_fields(
                    self.result.native_model, inputs=self.result.inputs,
                    state=replace(state, **{name: tuple(tuple(row) for row in rows)}),
                    project=self.project,
                )

    def test_missing_observations_are_not_exported_as_zero(self):
        missing = replace(self.project.sensors[0], measured_value=None)
        project = replace(self.project, sensors=(missing,) + self.project.sensors[1:])
        fields, locations = build_beam_result_fields(
            self.result.native_model, inputs=self.result.inputs,
            state=self.result.state, project=project,
        )
        self.assertNotIn(missing.identifier, fields["sensor_measured_strain"].entity_ids)
        self.assertFalse(any(location.entity_id == missing.identifier for location in locations))

    def test_project_validation_rejects_missing_observations_with_field_path(self):
        missing = replace(self.project.sensors[0], measured_value=None)
        project = replace(self.project, sensors=(missing,) + self.project.sensors[1:])
        report = self.service.validate_project(project)
        self.assertFalse(report.is_valid)
        self.assertIn(f"/sensors/{missing.identifier}/measured_value", {issue.field for issue in report.issues})
        with self.assertRaises(AlgorithmValidationError):
            self.service.run_project(project)

    def test_explicit_zero_observation_is_valid_and_remains_zero(self):
        zero = replace(self.project.sensors[0], measured_value=0.0)
        project = replace(self.project, sensors=(zero,) + self.project.sensors[1:])
        self.assertTrue(self.service.validate_project(project).is_valid)
        result = self.service.run_project(project)
        field = result.fields["sensor_measured_strain"]
        self.assertEqual(field.values[field.entity_ids.index(zero.identifier)], (0.0,))

    def test_legacy_entities_are_explicit_unique_snapshot_ids_with_locations(self):
        first = self.service.run(self.config)
        second = self.service.run(self.config)
        self.assertIsNone(first.state.project_id)
        for association, field_name in (("node", "displacement"), ("sensor", "sensor_strain_residual"), ("sample", "axial_strain")):
            ids = first.fields[field_name].entity_ids
            self.assertTrue(all(identifier.startswith("beam-snapshot:") for identifier in ids))
            self.assertEqual(set(ids), set(self.locations(first, association)))
            self.assertFalse(set(ids) & set(second.fields[field_name].entity_ids))

    def test_exported_fields_and_locations_are_detached_from_native_arrays(self):
        model = copy.deepcopy(self.result.native_model)
        fields, locations = build_beam_result_fields(
            model, inputs=self.result.inputs, state=self.result.state, project=self.project,
        )
        old_fields, old_locations = copy.deepcopy(fields), copy.deepcopy(locations)
        model.U[:] = 123.0
        model.node_x[:] += 456.0
        self.assertEqual(fields, old_fields)
        self.assertEqual(locations, old_locations)


if __name__ == "__main__":
    unittest.main()
