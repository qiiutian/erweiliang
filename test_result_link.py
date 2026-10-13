from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace
import unittest

import numpy as np

from config_adapter import get_sample_config
from ifem.application.analysis_service import create_default_analysis_service
from ifem.infrastructure import project_from_legacy_config
from ifem.visualization.result_link import (
    ResultTarget,
    build_result_targets,
    visible_sample_indices,
)
from postprocessing import reconstruct_section_field, recover_continuous_section_field


class ResultLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = get_sample_config()
        config["query_xs"] = [0.0, 0.5, 0.5, 3.0]
        cls.project = project_from_legacy_config(config)
        cls.result = create_default_analysis_service().run(
            config,
            project=cls.project,
            parameters={
                name: config[name]
                for name in ("query_xs", "true_points", "gauss_n", "points_per_element")
                if name in config
            },
        )
        cls.model = cls.result.native_model
        cls.inputs = cls.result.inputs
        cls.state = cls.result.state
        cls.raw = reconstruct_section_field(cls.model, points_per_element=9, elastic_modulus=2.06e11)

    def targets(self, **kwargs):
        arguments = dict(model=self.model, inputs=self.inputs, state=self.state, field=self.raw, sequence=7)
        arguments.update(kwargs)
        return build_result_targets(**arguments)

    @staticmethod
    def values(target):
        return {label: (value, unit) for label, value, unit in target.values}

    def test_real_nodes_retain_project_ids_and_native_values(self):
        targets = self.targets()
        self.assertEqual(set(targets), {"node", "query", "compare", "sample"})
        for index, target in enumerate(targets["node"]):
            self.assertEqual(target.index, index)
            self.assertEqual(target.source_id, self.state.node_ids[index])
            self.assertIn(self.state.node_ids[index], target.entity_id)
            self.assertIsNone(target.element_id)
            self.assertEqual(target.reference_position, self.state.reference_coordinates[index])
            np.testing.assert_allclose(target.position, self.state.deformed_coordinates[index])
            values = self.values(target)
            self.assertEqual(values["u"], (self.state.displacements[index][0], "m"))
            self.assertEqual(values["φ"], (self.state.rotations[index][2], "rad"))

    def test_reordered_nodes_and_elements_map_by_geometry_and_connectivity(self):
        order = tuple(reversed(range(len(self.state.node_ids))))
        element_order = tuple(reversed(range(len(self.state.element_ids))))
        state = replace(
            self.state,
            node_ids=tuple(self.state.node_ids[index] for index in order),
            reference_coordinates=tuple(self.state.reference_coordinates[index] for index in order),
            displacements=tuple(self.state.displacements[index] for index in order),
            reference_frames=tuple(self.state.reference_frames[index] for index in order),
            rotations=tuple(self.state.rotations[index] for index in order),
            element_ids=tuple(self.state.element_ids[index] for index in element_order),
            connectivity=tuple(tuple(reversed(self.state.connectivity[index])) for index in element_order),
        )
        self.assertEqual(self.targets(state=state), self.targets())

    def test_mismatched_state_reference_displacement_rotation_are_rejected(self):
        for field_name, message in (("reference_coordinates", "参考坐标"), ("displacements", "位移"), ("rotations", "转角")):
            values = [list(row) for row in getattr(self.state, field_name)]
            values[0][0] += 0.1
            with self.subTest(field=field_name), self.assertRaisesRegex(ValueError, message):
                self.targets(state=replace(self.state, **{field_name: tuple(tuple(row) for row in values)}))

    def test_mismatched_element_connections_are_rejected(self):
        connections = list(self.state.connectivity)
        connections[0] = (self.state.node_ids[0], self.state.node_ids[2])
        with self.assertRaisesRegex(ValueError, "连接关系"):
            self.targets(state=replace(self.state, connectivity=tuple(connections)))

    def test_queries_are_true_evaluations_and_duplicate_locations_remain_distinct(self):
        targets = self.targets()["query"]
        self.assertEqual(len(targets), 4)
        self.assertEqual(targets[1].position, targets[2].position)
        self.assertNotEqual(targets[1].entity_id, targets[2].entity_id)
        for target, row in zip(targets, self.model.evaluate_displacement_at_points(self.inputs["query_xs"])):
            self.assertEqual(target.position, (row["x"] + row["u"], row["v"], 0.0))
            self.assertEqual(self.values(target)["v"], (row["v"], "m"))
            self.assertEqual(target.source_id, "")
            self.assertIn(target.element_id, self.state.element_ids)

    def test_comparison_residuals_are_real_native_values(self):
        targets = self.targets()["compare"]
        expected = self.model.compare_true_points(self.inputs["true_points"])
        self.assertEqual(len(targets), len(expected))
        self.assertGreater(len(targets), 0)
        for target, row in zip(targets, expected):
            values = self.values(target)
            self.assertEqual(values["Δu"], (row["Δu"], "m"))
            self.assertEqual(values["Δv"], (row["Δv"], "m"))
            self.assertEqual(values["u_实测"], (row["u_实测"], "m"))
            self.assertEqual(target.position, (row["x"] + row["u_重构"], row["v_重构"], 0.0))

    def test_raw_samples_keep_boundary_sides_and_exact_array_indices(self):
        targets = self.targets()["sample"]
        self.assertEqual(len(targets), len(self.raw.x_reference))
        self.assertEqual([target.index for target in targets], list(range(len(targets))))
        duplicates = np.flatnonzero(np.diff(self.raw.x_reference) == 0.0)
        self.assertGreater(len(duplicates), 0)
        for index in duplicates:
            left, right = targets[index:index + 2]
            self.assertEqual(left.reference_position, right.reference_position)
            self.assertNotEqual(left.element_id, right.element_id)
            self.assertNotEqual(left.entity_id, right.entity_id)
        for index, target in enumerate(targets):
            self.assertEqual(target.element_id, self.state.element_ids[self.raw.element_index[index]])
            self.assertEqual(target.position, (self.raw.x_deformed[index], self.raw.y_deformed[index], 0.0))
            self.assertEqual(self.values(target)["上表面应变"], (self.raw.top_strain[index] * 1.0e6, "με"))
            self.assertEqual(self.values(target)["下表面应力"], (self.raw.bottom_stress[index] / 1.0e6, "MPa"))

    def test_representation_changes_use_different_snapshot_sample_keys(self):
        recovered = recover_continuous_section_field(self.raw)
        raw_targets = self.targets()["sample"]
        recovered_targets = self.targets(field=recovered)["sample"]
        self.assertEqual(len(recovered_targets), len(recovered.x_reference))
        self.assertTrue(all(target.representation == "nodal_average" for target in recovered_targets))
        self.assertFalse({target.entity_id for target in raw_targets} & {target.entity_id for target in recovered_targets})
        self.assertEqual(self.targets(field=recovered)["node"], self.targets()["node"])

    def test_absent_modulus_remains_missing_stress_not_zero(self):
        field = reconstruct_section_field(self.model, points_per_element=4, elastic_modulus=None)
        for target in self.targets(field=field)["sample"]:
            self.assertEqual(self.values(target)["上表面应力"], (None, "MPa"))
            self.assertEqual(self.values(target)["下表面应力"], (None, "MPa"))

    def test_legacy_and_unbound_state_never_claim_project_identity(self):
        for state in (None, replace(self.state, project_id=None, project_revision=None)):
            with self.subTest(state_present=state is not None):
                for targets in self.targets(state=state).values():
                    for target in targets:
                        self.assertEqual(target.source_id, "")
                        self.assertIsNone(target.element_id)
                        self.assertTrue(target.entity_id.startswith("result:7:"))

    def test_new_snapshot_identity_does_not_reuse_old_targets(self):
        old = self.targets(sequence=7)
        new = self.targets(sequence=8)
        for kind in old:
            self.assertFalse({target.entity_id for target in old[kind]} & {target.entity_id for target in new[kind]})
            self.assertEqual([target.position for target in old[kind]], [target.position for target in new[kind]])

    def test_targets_do_not_retain_mutable_inputs_or_arrays(self):
        inputs = copy.deepcopy(self.inputs)
        field = copy.deepcopy(self.raw)
        targets = self.targets(inputs=inputs, field=field)
        old_query = targets["query"][0]
        old_sample = targets["sample"][0]
        inputs["query_xs"][0] = 0.25
        field.x_deformed[0] = 900.0
        self.assertEqual(targets["query"][0], old_query)
        self.assertEqual(targets["sample"][0], old_sample)
        with self.assertRaises(FrozenInstanceError):
            old_sample.index = 2

    def test_empty_optional_results_and_field_are_empty_tuples(self):
        targets = self.targets(inputs={}, field=None)
        self.assertEqual(targets["query"], ())
        self.assertEqual(targets["compare"], ())
        self.assertEqual(targets["sample"], ())
        self.assertEqual(len(targets["node"]), self.model.n_nodes)

    def test_invalid_sample_element_reference_and_nan_are_rejected(self):
        field = copy.deepcopy(self.raw)
        field.element_index[0] = self.model.n_elems
        with self.assertRaisesRegex(ValueError, "单元索引"):
            self.targets(field=field)
        field = copy.deepcopy(self.raw)
        field.x_reference[0] = self.model.node_x[-1]
        with self.assertRaisesRegex(ValueError, "采样位置"):
            self.targets(field=field)
        field = copy.deepcopy(self.raw)
        field.strain[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "应变"):
            self.targets(field=field)

    def test_target_constructor_freezes_nested_data_and_rejects_nonfinite(self):
        target = ResultTarget("query", 0, "result:0:query:0", None, [0, 0, 0], [0, 0, 0], [["u", 0, "m"]])
        self.assertIsInstance(target.reference_position, tuple)
        self.assertEqual(target.values, (("u", 0.0, "m"),))
        with self.assertRaisesRegex(ValueError, "有限"):
            replace(target, values=(("u", float("nan"), "m"),))


class VisibleSampleTests(unittest.TestCase):
    def test_empty_and_small_fields_keep_all_rows(self):
        self.assertEqual(visible_sample_indices(0), ())
        self.assertEqual(visible_sample_indices(5), (0, 1, 2, 3, 4))

    def test_default_subset_matches_existing_table_sampling(self):
        for count in (1, 239, 240, 241, 480, 4000):
            expected = tuple(int(value) for value in np.unique(np.linspace(0, count - 1, min(240, count), dtype=int)))
            self.assertEqual(visible_sample_indices(count), expected)

    def test_pick_outside_subset_adds_exact_sample_without_displacing_rows(self):
        original = visible_sample_indices(1000)
        missing = next(index for index in range(1000) if index not in original)
        expanded = visible_sample_indices(1000, include_index=missing)
        self.assertEqual(len(expanded), 241)
        self.assertEqual(set(expanded), set(original) | {missing})
        self.assertEqual(visible_sample_indices(1000, include_index=original[3]), original)

    def test_invalid_count_limit_and_pick_are_rejected(self):
        for args in ((-1,), (True,), (1.5,), (5, 0), (5, 3, 5), (0, 240, 0), (5, 3, -1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                visible_sample_indices(*args)


if __name__ == "__main__":
    unittest.main()
