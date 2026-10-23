from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from ifem.application.analysis_service import AlgorithmRegistry, AnalysisService
from ifem.domain.analysis import (
    AlgorithmCapabilities, AlgorithmMetadata, AnalysisResult, ReconstructionState,
    ResultField, ResultLocation, ValidationReport,
)
from ifem.domain.result_fields import (
    RESULT_FIELD_DEFINITIONS, map_result_field, validate_result_field,
    validate_result_fields,
)


IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def state_for(*, space="2d", regime="small_deformation"):
    return ReconstructionState(
        modeling_space=space, deformation_regime=regime,
        node_ids=("right", "left"), reference_coordinates=((5.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        displacements=((0.01, 0.02, 0.03), (0.0, 0.0, 0.0)),
        reference_frames=(IDENTITY, IDENTITY), element_ids=("beam",),
        connectivity=(("left", "right"),),
    )


def displacement():
    return ResultField(
        "displacement", "node", ("left", "right"), ("x", "y", "z"),
        ((0.0, 0.0, 0.0), (0.01, 0.02, 0.03)), "m", "global",
    )


def result_with(field_value=None, *, locations=(), state=None):
    return AnalysisResult(
        "probe.fields", "1", state=state or state_for(),
        fields={} if field_value is None else {field_value.identifier: field_value},
        locations=locations,
    )


class StaticFieldsAlgorithm:
    metadata = AlgorithmMetadata("probe.fields", "Fields probe", "1", contract_version="1")

    def __init__(self, result, *, required=()):
        self.result = result
        self.capabilities = AlgorithmCapabilities(
            model_dimensions=(1,), element_families=("beam2d_euler_bernoulli",),
            measurement_types=(), result_fields=tuple(result.fields),
            required_result_fields=required, rotation_representations=("none",),
        )

    def parameter_schema(self):
        return {"type": "object", "properties": {}}

    def validate(self, context):
        return ValidationReport.valid()

    def solve(self, context, *, progress, cancellation):
        return self.result


class ResultFieldMappingTests(unittest.TestCase):
    def test_legacy_positional_result_construction_remains_valid(self):
        result = AnalysisResult("legacy", "1", object(), {}, {"raw": [1]}, (), None)
        self.assertEqual(result.locations, ())
        self.assertEqual(result.fields, {"raw": [1]})

    def test_locations_are_immutable_normalized_and_detached(self):
        reference = [1, 2, 3]
        location = ResultLocation(" Sample ", " point ", reference, [2, 3, 4], " beam ", " A ")
        reference[0] = 99
        self.assertEqual(location.reference_position, (1.0, 2.0, 3.0))
        self.assertEqual((location.association, location.entity_id, location.source_entity_id, location.label),
                         ("sample", "point", "beam", "A"))
        with self.assertRaises(FrozenInstanceError):
            location.label = "B"

    def test_location_rejects_invalid_coordinates_and_identifiers(self):
        for kwargs in (
            {"association": "row"}, {"entity_id": " "},
            {"reference_position": (0, 1)}, {"position": (0, float("nan"), 2)},
            {"source_entity_id": ""},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                arguments = dict(association="sample", entity_id="p", reference_position=(0, 0, 0), position=(0, 0, 0))
                arguments.update(kwargs)
                ResultLocation(**arguments)

    def test_location_key_is_association_and_id_not_position(self):
        sample = ResultLocation("sample", "same", (1, 0, 0), (1, 0, 0))
        sensor = replace(sample, association="sensor")
        result = result_with(locations=(sample, sensor))
        self.assertEqual(len(result.locations), 2)
        with self.assertRaisesRegex(ValueError, "组合必须唯一"):
            result_with(locations=(sample, sample))
        with self.assertRaises(TypeError):
            result_with(locations=({"entity_id": "same"},))

    def test_node_mapping_joins_reordered_ids_without_native_model(self):
        result = result_with(displacement())
        layer = map_result_field(result, "displacement")
        self.assertIsNone(result.native_model)
        self.assertEqual(layer.records[0].entity_id, "left")
        self.assertEqual(layer.records[0].reference_position, (0.0, 0.0, 0.0))
        self.assertEqual(layer.records[1].position, (5.01, 0.02, 0.03))
        self.assertEqual(layer.records[1].values, (0.01, 0.02, 0.03))
        self.assertEqual((layer.label, layer.unit, layer.known), ("位移", "m", True))

    def test_layer_records_are_immutable_snapshot_values(self):
        result = result_with(displacement())
        layer = map_result_field(result, "displacement")
        result.fields.clear()
        self.assertEqual(layer.records[1].values, (0.01, 0.02, 0.03))
        with self.assertRaises(FrozenInstanceError):
            layer.records[1].values = (99, 99, 99)
        with self.assertRaises(TypeError):
            RESULT_FIELD_DEFINITIONS["custom"] = None

    def test_all_four_regimes_map_without_solver_specific_assumptions(self):
        for space in ("2d", "3d"):
            for regime in ("small_deformation", "large_deformation"):
                with self.subTest(space=space, regime=regime):
                    layer = map_result_field(result_with(displacement(), state=state_for(space=space, regime=regime)), "displacement")
                    self.assertEqual(layer.records[1].position, (5.01, 0.02, 0.03))

    def test_sample_join_preserves_duplicate_boundary_coordinates(self):
        field_value = ResultField("axial_strain", "sample", ("right-side", "left-side"),
                                  ("top", "bottom"), ((4e-6, 5e-6), (1e-6, 2e-6)), "1", "local")
        locations = (
            ResultLocation("sample", "left-side", (1, 0, 0), (1.1, 0.2, 0), "beam-left", "左值"),
            ResultLocation("sample", "right-side", (1, 0, 0), (1.1, 0.2, 0), "beam-right", "右值"),
        )
        layer = map_result_field(result_with(field_value, locations=locations), "axial_strain")
        self.assertEqual(len(layer.records), 2)
        self.assertEqual(layer.records[0].source_entity_id, "beam-right")
        self.assertEqual(layer.records[0].label, "右值")
        self.assertEqual(layer.records[0].values, (4e-6, 5e-6))

    def test_sample_and_sensor_locations_are_required_and_association_specific(self):
        for association in ("sensor", "sample"):
            field_value = ResultField("custom", association, ("p",), ("v",), ((1,),), "1")
            wrong = ResultLocation("sample" if association == "sensor" else "sensor", "p", (1, 0, 0), (1, 0, 0))
            with self.subTest(association=association), self.assertRaisesRegex(ValueError, "缺少显式结果位置"):
                map_result_field(result_with(field_value, locations=(wrong,)), "custom")

    def test_sensor_residual_keeps_signed_si_values(self):
        field_value = ResultField("sensor_strain_residual", "sensor", ("s",), ("axial",), ((-2e-6,),), "1", "local")
        location = ResultLocation("sensor", "s", (1, 0.1, 0), (1.01, 0.2, 0), "beam", "上表面")
        layer = map_result_field(result_with(field_value, locations=(location,)), field_value.identifier)
        self.assertEqual(layer.records[0].values, (-2e-6,))
        self.assertEqual(layer.unit, "1")
        self.assertIn("重构 − 实测", layer.label)

    def test_unknown_field_preserves_actual_metadata_without_implied_semantics(self):
        field_value = ResultField("vendor.quality", "node", ("right",), ("score",), ((73.2,),), "points", "vendor-frame")
        layer = map_result_field(result_with(field_value), "vendor.quality")
        self.assertEqual((layer.label, layer.unit, layer.coordinate_system, layer.known),
                         ("vendor.quality", "points", "vendor-frame", False))
        self.assertEqual(layer.components, ("score",))

    def test_element_global_positions_are_not_invented(self):
        for association, identifier in (("element", "beam"), ("global", "model")):
            with self.subTest(association=association):
                field_value = ResultField("custom", association, (identifier,), ("v",), ((1,),), "1")
                record = map_result_field(result_with(field_value), "custom").records[0]
                self.assertIsNone(record.reference_position)
                self.assertIsNone(record.position)

    def test_unknown_state_entity_is_not_matched_by_row(self):
        for association in ("node", "element"):
            field_value = ResultField("custom", association, ("missing",), ("v",), ((1,),), "1")
            location = ResultLocation(association, "missing", (0, 0, 0), (0, 0, 0))
            with self.subTest(association=association), self.assertRaisesRegex(ValueError, "未知"):
                map_result_field(result_with(field_value, locations=(location,)), "custom")

    def test_conflicting_explicit_node_position_is_rejected(self):
        location = ResultLocation("node", "right", (5, 0, 0), (5, 0, 0))
        with self.assertRaisesRegex(ValueError, "不一致"):
            map_result_field(result_with(displacement(), locations=(location,)), "displacement")
        valid = replace(location, position=(5.01, 0.02, 0.03))
        self.assertEqual(map_result_field(result_with(displacement(), locations=(valid,)), "displacement").records[1].position,
                         valid.position)

    def test_registered_fields_reject_wrong_unit_association_components_or_frame(self):
        for changes, fragment in (
            ({"unit": "mm"}, "单位"), ({"association": "sensor"}, "关联"),
            ({"components": ("a", "b", "c")}, "分量"),
            ({"coordinate_system": "screen"}, "坐标系"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, fragment):
                validate_result_field(replace(displacement(), **changes))

    def test_node_position_overflow_cannot_reach_spatial_view(self):
        state = replace(state_for(), reference_coordinates=((1e308, 0, 0), (0, 0, 0)),
                        displacements=((1e308, 0, 0), (0, 0, 0)))
        field_value = ResultField("custom", "node", ("right",), ("v",), ((1,),), "1")
        with self.assertRaisesRegex(ValueError, "位置必须为有限"):
            map_result_field(result_with(field_value, state=state), "custom")

    def test_large_coordinates_do_not_relax_explicit_position_identity(self):
        state = replace(state_for(), reference_coordinates=((1e10, 0, 0), (0, 0, 0)),
                        displacements=((0, 0, 0), (0, 0, 0)))
        field_value = ResultField("custom", "node", ("right",), ("v",), ((1,),), "1")
        location = ResultLocation("node", "right", (1e10 + 0.1, 0, 0), (1e10, 0, 0))
        with self.assertRaisesRegex(ValueError, "不一致"):
            map_result_field(result_with(field_value, state=state, locations=(location,)), "custom")

    def test_rotation_representations_have_explicit_components_and_units(self):
        for components, unit, values in (
            (("x", "y", "z"), "rad", (0, 0, 1)),
            (("w", "x", "y", "z"), "1", (1, 0, 0, 0)),
            (("xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"), "1", IDENTITY),
        ):
            with self.subTest(components=components):
                field_value = ResultField("rotation", "node", ("left",), components, (values,), unit)
                validate_result_field(field_value)
                wrong_unit = "rad" if unit == "1" else "1"
                with self.assertRaisesRegex(ValueError, "单位"):
                    validate_result_field(replace(field_value, unit=wrong_unit))

    def test_missing_or_wrong_field_payload_is_explicit(self):
        result = result_with()
        with self.assertRaises(KeyError):
            map_result_field(result, "displacement")
        with self.assertRaises(TypeError):
            map_result_field(replace(result, fields={"raw": [1]}), "raw")
        with self.assertRaisesRegex(ValueError, "字段键"):
            map_result_field(replace(result, fields={"other": displacement()}), "other")
        validate_result_fields(result)

    def test_duplicate_component_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "分量必须唯一"):
            ResultField("custom", "node", ("left",), ("x", "x"), ((1, 2),))

    def test_v1_service_checks_registered_semantics_before_return(self):
        algorithm = StaticFieldsAlgorithm(result_with(replace(displacement(), unit="mm")))
        service = AnalysisService(AlgorithmRegistry((algorithm,)), default_algorithm_id=algorithm.metadata.identifier)
        with self.assertRaisesRegex(RuntimeError, "单位必须为 m"):
            service.run({})

    def test_v1_service_requires_explicit_sample_location(self):
        field_value = ResultField("axial_strain", "sample", ("sample",), ("top", "bottom"), ((0, 0),), "1")
        algorithm = StaticFieldsAlgorithm(result_with(field_value))
        service = AnalysisService(AlgorithmRegistry((algorithm,)), default_algorithm_id=algorithm.metadata.identifier)
        with self.assertRaisesRegex(RuntimeError, "缺少显式结果位置"):
            service.run({})

    def test_v1_legacy_input_snapshot_sensor_is_valid_without_project(self):
        field_value = ResultField("sensor_measured_strain", "sensor", ("snapshot:s",), ("axial",), ((0,),), "1")
        location = ResultLocation("sensor", "snapshot:s", (1, 0.1, 0), (1, 0.1, 0))
        result = result_with(field_value, locations=(location,))
        algorithm = StaticFieldsAlgorithm(result)
        service = AnalysisService(AlgorithmRegistry((algorithm,)), default_algorithm_id=algorithm.metadata.identifier)
        self.assertIs(service.run({}), result)

    def test_v1_does_not_require_optional_standard_fields(self):
        result = result_with()
        algorithm = StaticFieldsAlgorithm(result)
        algorithm.capabilities = replace(algorithm.capabilities, result_fields=("displacement",))
        service = AnalysisService(AlgorithmRegistry((algorithm,)), default_algorithm_id=algorithm.metadata.identifier)
        self.assertIs(service.run({}), result)

    def test_legacy_service_keeps_untyped_result_compatibility(self):
        result = replace(result_with(), fields={"raw": [1]}, state=None)
        algorithm = StaticFieldsAlgorithm(result)
        algorithm.metadata = replace(algorithm.metadata, contract_version="0")
        service = AnalysisService(AlgorithmRegistry((algorithm,)), default_algorithm_id=algorithm.metadata.identifier)
        self.assertIs(service.run({}), result)


if __name__ == "__main__":
    unittest.main()
