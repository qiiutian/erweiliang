from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from ifem.domain.analysis import AnalysisResult, ReconstructionState, ResultField, ResultLocation
from ifem.visualization.generic_results import (
    DISCRETE_GEOMETRY_DESCRIPTION, build_result_geometry, build_scalar_points,
)


IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def make_state(*, modeling_space="3d", deformation_regime="large_deformation"):
    return ReconstructionState(
        modeling_space=modeling_space, deformation_regime=deformation_regime,
        node_ids=("c", "a", "b", "isolated"),
        reference_coordinates=((2, 1, 0.5), (0, 0, 0), (1, 0.5, 0.2), (3, 4, 5)),
        displacements=((0.2, -0.3, 0.4), (0, 0, 0), (0.1, 0.2, 0.3), (-1, 2, 3)),
        reference_frames=(IDENTITY,) * 4,
        element_ids=("bc", "ab"), connectivity=(("b", "c"), ("a", "b")),
    )


def make_result(field_value=None, *, locations=(), state=None):
    return AnalysisResult(
        "probe.generic", "1", state=make_state() if state is None else state,
        fields={} if field_value is None else {field_value.identifier: field_value},
        locations=locations,
    )


def custom_field(association, ids, values, *, components=("score",), unit="custom-unit"):
    return ResultField("vendor.field", association, ids, components, values, unit, "vendor-frame")


class GenericResultGeometryTests(unittest.TestCase):
    def test_geometry_joins_declared_connectivity_by_ids_not_node_order(self):
        geometry = build_result_geometry(make_state())
        self.assertEqual(tuple(node.entity_id for node in geometry.nodes), ("c", "a", "b", "isolated"))
        self.assertEqual(tuple(line.node_ids for line in geometry.lines), (("b", "c"), ("a", "b")))
        self.assertEqual(geometry.lines[0].element_id, "bc")
        self.assertEqual(geometry.lines[0].reference_positions, ((1, 0.5, 0.2), (2, 1, 0.5)))
        self.assertEqual(geometry.lines[0].positions, ((1.1, 0.7, 0.5), (2.2, 0.7, 0.9)))

    def test_all_four_regimes_retain_true_coordinates_without_axis_projection(self):
        for space in ("2d", "3d"):
            for regime in ("small_deformation", "large_deformation"):
                with self.subTest(space=space, regime=regime):
                    geometry = build_result_geometry(make_state(modeling_space=space, deformation_regime=regime))
                    self.assertEqual((geometry.modeling_space, geometry.deformation_regime), (space, regime))
                    self.assertEqual(geometry.nodes[0].position, (2.2, 0.7, 0.9))
                    self.assertEqual(len(geometry.nodes), 4)

    def test_discrete_limitation_is_explicit_and_no_extra_samples_appear(self):
        geometry = build_result_geometry(make_state())
        self.assertEqual(geometry.description, DISCRETE_GEOMETRY_DESCRIPTION)
        self.assertIn("不代表连续曲线或实体截面", geometry.description)
        self.assertEqual(len(geometry.nodes), 4)
        self.assertEqual(len(geometry.lines), 2)
        self.assertNotIn("isolated", tuple(identifier for line in geometry.lines for identifier in line.node_ids))

    def test_multi_node_connectivity_only_yields_declared_adjacent_links(self):
        state = replace(make_state(), element_ids=("declared-path",), connectivity=(("a", "c", "b"),))
        geometry = build_result_geometry(state)
        self.assertEqual(tuple(line.node_ids for line in geometry.lines), (("a", "c"), ("c", "b")))
        self.assertEqual(tuple(line.segment_index for line in geometry.lines), (0, 1))
        self.assertEqual(tuple(line.element_id for line in geometry.lines), ("declared-path", "declared-path"))

    def test_no_elements_is_a_valid_node_only_snapshot(self):
        geometry = build_result_geometry(replace(make_state(), element_ids=(), connectivity=()))
        self.assertEqual(geometry.lines, ())
        self.assertEqual(len(geometry.nodes), 4)

    def test_separate_elements_with_coincident_geometry_keep_identity(self):
        state = replace(make_state(), element_ids=("one", "two"), connectivity=(("a", "b"), ("a", "b")))
        geometry = build_result_geometry(state)
        self.assertEqual(len(geometry.lines), 2)
        self.assertEqual(tuple(line.element_id for line in geometry.lines), ("one", "two"))

    def test_duplicate_node_reference_inside_one_element_is_rejected(self):
        for connection in (("a", "a"), ("a", "b", "a")):
            with self.subTest(connection=connection), self.assertRaisesRegex(ValueError, "重复引用同一节点"):
                build_result_geometry(replace(make_state(), element_ids=("bad",), connectivity=(connection,)))

    def test_bad_producer_topology_cannot_silently_truncate_or_guess(self):
        for attribute, value, fragment in (
            ("connectivity", (("a", "missing"), ("a", "b")), "未知节点"),
            ("connectivity", (("a", "b"),), "单元 ID 数量"),
            ("reference_coordinates", ((0, 0, 0),), "数量必须一致"),
            ("node_ids", ("a", "a", "b", "isolated"), "必须唯一"),
        ):
            with self.subTest(attribute=attribute):
                state = make_state()
                object.__setattr__(state, attribute, value)
                with self.assertRaisesRegex(ValueError, fragment):
                    build_result_geometry(state)

    def test_coordinate_overflow_is_rejected_before_rendering(self):
        state = replace(make_state(), reference_coordinates=((1e308, 0, 0),) * 4,
                        displacements=((1e308, 0, 0),) * 4)
        with self.assertRaisesRegex(ValueError, "有限数值"):
            build_result_geometry(state)

    def test_geometry_output_is_immutable(self):
        geometry = build_result_geometry(make_state())
        with self.assertRaises(FrozenInstanceError):
            geometry.nodes[0].position = (0, 0, 0)
        with self.assertRaises(FrozenInstanceError):
            geometry.lines[0].node_ids = ("a", "b")
        self.assertIsInstance(geometry.nodes, tuple)
        self.assertIsInstance(geometry.lines, tuple)

    def test_missing_or_wrong_state_is_explicit(self):
        for value in (None, {}, object()):
            with self.subTest(value=value), self.assertRaises(TypeError):
                build_result_geometry(value)


class GenericScalarPointTests(unittest.TestCase):
    def test_node_subset_joins_field_ids_independently_of_state_and_topology(self):
        field_value = custom_field("node", ("b", "a"), ((-3, 8), (7, 9)), components=("left", "right"))
        layer = build_scalar_points(make_result(field_value), field_value.identifier, "right")
        self.assertEqual(tuple(point.entity_id for point in layer.points), ("b", "a"))
        self.assertEqual(tuple(point.value for point in layer.points), (8, 9))
        self.assertEqual(layer.points[0].position, (1.1, 0.7, 0.5))
        self.assertEqual(layer.points[1].position, (0, 0, 0))
        self.assertEqual(layer.unlocated_records, ())

    def test_all_four_regimes_can_show_fields_without_a_native_model(self):
        field_value = custom_field("node", ("c",), ((1,),))
        for space in ("2d", "3d"):
            for regime in ("small_deformation", "large_deformation"):
                with self.subTest(space=space, regime=regime):
                    result = make_result(field_value, state=make_state(modeling_space=space, deformation_regime=regime))
                    self.assertIsNone(result.native_model)
                    layer = build_scalar_points(result, field_value.identifier)
                    self.assertEqual(layer.points[0].position, (2.2, 0.7, 0.9))

    def test_unknown_field_preserves_unit_component_and_frame_metadata(self):
        field_value = custom_field("node", ("a",), ((-12.5,),))
        layer = build_scalar_points(make_result(field_value), field_value.identifier)
        self.assertEqual((layer.identifier, layer.label, layer.unit, layer.component, layer.coordinate_system, layer.known),
                         ("vendor.field", "vendor.field", "custom-unit", "score", "vendor-frame", False))
        self.assertEqual(layer.points[0].value, -12.5)

    def test_default_component_is_only_first_declared_not_a_vector_norm(self):
        field_value = custom_field("node", ("a",), ((3, 4),), components=("alpha", "beta"))
        layer = build_scalar_points(make_result(field_value), field_value.identifier)
        self.assertEqual((layer.component, layer.points[0].value), ("alpha", 3))

    def test_unknown_component_or_numeric_index_is_rejected(self):
        field_value = custom_field("node", ("a",), ((1,),))
        result = make_result(field_value)
        with self.assertRaisesRegex(ValueError, "未声明分量"):
            build_scalar_points(result, field_value.identifier, "magnitude")
        with self.assertRaises(TypeError):
            build_scalar_points(result, field_value.identifier, 0)

    def test_explicit_sensor_and_sample_locations_are_not_projected_to_nodes(self):
        for association in ("sensor", "sample"):
            with self.subTest(association=association):
                field_value = custom_field(association, ("q",), ((0.0123,),))
                location = ResultLocation(association, "q", (0.25, 0.075, 0.03), (0.29, 0.11, 0.04), "ab", "表面")
                layer = build_scalar_points(make_result(field_value, locations=(location,)), field_value.identifier)
                self.assertEqual(layer.points[0].reference_position, location.reference_position)
                self.assertEqual(layer.points[0].position, location.position)
                self.assertEqual((layer.points[0].source_entity_id, layer.points[0].label), ("ab", "表面"))

    def test_duplicate_boundary_coordinates_remain_two_distinct_points(self):
        field_value = custom_field("sample", ("right", "left"), ((7,), (-3,)))
        locations = (
            ResultLocation("sample", "left", (1, 0, 0), (1.1, 0.2, 0), "ab", "左值"),
            ResultLocation("sample", "right", (1, 0, 0), (1.1, 0.2, 0), "bc", "右值"),
        )
        layer = build_scalar_points(make_result(field_value, locations=locations), field_value.identifier)
        self.assertEqual(len(layer.points), 2)
        self.assertEqual(tuple(point.entity_id for point in layer.points), ("right", "left"))
        self.assertEqual(tuple(point.value for point in layer.points), (7, -3))
        self.assertEqual(tuple(point.source_entity_id for point in layer.points), ("bc", "ab"))

    def test_element_without_location_stays_table_only_no_centroid_guess(self):
        field_value = custom_field("element", ("ab", "bc"), ((3,), (8,)))
        location = ResultLocation("element", "bc", (1.7, 0.8, 0.4), (1.8, 0.9, 0.5))
        layer = build_scalar_points(make_result(field_value, locations=(location,)), field_value.identifier)
        self.assertEqual(tuple(point.entity_id for point in layer.points), ("bc",))
        self.assertEqual(tuple(point.entity_id for point in layer.unlocated_records), ("ab",))
        self.assertEqual(layer.unlocated_records[0].value, 3)
        self.assertIsNone(layer.unlocated_records[0].reference_position)
        self.assertIsNone(layer.unlocated_records[0].position)

    def test_global_without_location_stays_table_only(self):
        field_value = custom_field("global", ("model",), ((0.875,),), unit="1")
        layer = build_scalar_points(make_result(field_value), field_value.identifier)
        self.assertEqual(layer.points, ())
        self.assertEqual(len(layer.unlocated_records), 1)
        self.assertEqual(layer.unlocated_records[0].value, 0.875)

    def test_strain_stress_do_not_convert_units_smooth_or_infer_a_measure(self):
        location = ResultLocation("sample", "p", (0.3, 0, 0), (0.4, 0.1, 0), "ab")
        for identifier, unit, values in (("axial_strain", "1", (-2e-6, 7e-6)),
                                         ("axial_stress", "Pa", (-4e6, 6e6))):
            with self.subTest(identifier=identifier):
                field_value = ResultField(identifier, "sample", ("p",), ("top", "bottom"), (values,), unit, "local")
                layer = build_scalar_points(make_result(field_value, locations=(location,)), identifier, "bottom")
                self.assertEqual(layer.points[0].value, values[1])
                self.assertEqual(layer.unit, unit)

    def test_absent_fields_do_not_prevent_geometry_and_are_not_fabricated(self):
        result = make_result()
        self.assertEqual(len(build_result_geometry(result.state).nodes), 4)
        with self.assertRaises(KeyError):
            build_scalar_points(result, "displacement")

    def test_empty_field_has_no_dummy_zero_point(self):
        field_value = custom_field("node", (), ())
        layer = build_scalar_points(make_result(field_value), field_value.identifier)
        self.assertEqual(layer.points, ())
        self.assertEqual(layer.unlocated_records, ())

    def test_missing_sensor_location_remains_contract_error_not_zero_fallback(self):
        field_value = custom_field("sensor", ("q",), ((1,),))
        with self.assertRaisesRegex(ValueError, "缺少显式结果位置"):
            build_scalar_points(make_result(field_value), field_value.identifier)

    def test_scalar_output_is_immutable_and_detached_from_field_mapping(self):
        field_value = custom_field("node", ("a",), ((1,),))
        result = make_result(field_value)
        layer = build_scalar_points(result, field_value.identifier)
        result.fields.clear()
        self.assertEqual(layer.points[0].value, 1)
        with self.assertRaises(FrozenInstanceError):
            layer.points[0].value = 3
        with self.assertRaises(FrozenInstanceError):
            layer.component = "other"


if __name__ == "__main__":
    unittest.main()
