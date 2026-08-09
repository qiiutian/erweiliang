import copy
import json
import unittest

from config_adapter import (
    boundary_rows_from_prescribed_dofs,
    build_config_from_form_data,
    get_sample_config,
    load_config_from_json,
    measurement_rows_from_config,
    normalize_config,
    true_point_rows_from_config,
    validate_config,
)
from ifem.domain.analysis import InputValidationError


class StructuredConfigValidationTests(unittest.TestCase):
    def test_model_validation_exposes_stable_node_field(self):
        config = get_sample_config()
        config["node_x"] = [0.0, 1.0, 1.0]

        with self.assertRaises(InputValidationError) as captured:
            validate_config(config)

        self.assertEqual(captured.exception.field, "/model/node_x")
        self.assertIn("严格递增", str(captured.exception))

    def test_measurement_validation_exposes_row_and_column(self):
        config = get_sample_config()
        config["elements_sensor_data"][0]["measurements"][0]["x"] = 99.0

        with self.assertRaises(InputValidationError) as captured:
            validate_config(config)

        self.assertEqual(captured.exception.field, "/measurements/0/x")

    def test_view_validation_exposes_specific_setting(self):
        config = get_sample_config()
        config["plot_options"]["thickness_scale"] = "invalid"

        with self.assertRaises(InputValidationError) as captured:
            normalize_config(config)

        self.assertEqual(captured.exception.field, "/view_state/thickness_scale")

    def test_form_validation_exposes_specific_table_editor(self):
        config = get_sample_config()
        measurement_rows = measurement_rows_from_config(config)
        measurement_rows[2]["strain"] = "invalid"

        with self.assertRaises(InputValidationError) as captured:
            build_config_from_form_data(
                node_x_text=", ".join(str(value) for value in config["node_x"]),
                thickness_text=str(config["thickness"]),
                gauss_n_text=str(config["gauss_n"]),
                points_per_element_text=str(config["points_per_element"]),
                query_xs_text="",
                measurement_rows=measurement_rows,
                boundary_rows=boundary_rows_from_prescribed_dofs(
                    config["prescribed_dofs"]
                ),
                true_point_rows=true_point_rows_from_config(config),
                plot_options=copy.deepcopy(config["plot_options"]),
            )

        self.assertEqual(captured.exception.field, "/measurements/2/strain")

    def test_nonfinite_and_fractional_values_are_rejected_without_coercion(self):
        cases = (
            ("node", "/model/node_x", lambda config: config["node_x"].__setitem__(1, float("nan"))),
            ("thickness", "/sections/active/thickness", lambda config: config.__setitem__("thickness", float("inf"))),
            ("gauss", "/analysis/parameters/gauss_n", lambda config: config.__setitem__("gauss_n", 2.9)),
        )
        for name, field, mutate in cases:
            with self.subTest(name=name):
                config = get_sample_config()
                mutate(config)
                with self.assertRaises(InputValidationError) as captured:
                    normalize_config(config)
                self.assertEqual(captured.exception.field, field)

    def test_measurement_scalar_validation_targets_each_column(self):
        cases = (
            ("strain", "bad", "/measurements/0/strain"),
            ("weight", 0.0, "/measurements/0/weight"),
            ("surface", "sideways", "/measurements/0/surface"),
        )
        for key, value, field in cases:
            with self.subTest(key=key):
                config = get_sample_config()
                config["elements_sensor_data"][0]["measurements"][0][key] = value
                with self.assertRaises(InputValidationError) as captured:
                    validate_config(config)
                self.assertEqual(captured.exception.field, field)

        config = get_sample_config()
        measurement = config["elements_sensor_data"][0]["measurements"][0]
        measurement.pop("surface")
        measurement["y"] = 0.0
        with self.assertRaises(InputValidationError) as captured:
            validate_config(config)
        self.assertEqual(captured.exception.field, "/measurements/0/y")

    def test_invalid_container_shapes_keep_a_field_path(self):
        cases = (
            ("plot", "/view_state", lambda config: config.__setitem__("plot_options", None)),
            (
                "measurement group",
                "/measurements",
                lambda config: config["elements_sensor_data"].__setitem__(0, None),
            ),
            ("true point", "/true_points/0", lambda config: config.__setitem__("true_points", [None])),
        )
        for name, field, mutate in cases:
            with self.subTest(name=name):
                config = get_sample_config()
                mutate(config)
                with self.assertRaises(InputValidationError) as captured:
                    validate_config(config)
                self.assertEqual(captured.exception.field, field)

    def test_unsorted_measurement_rows_keep_source_row_index(self):
        config = get_sample_config()
        rows = measurement_rows_from_config(config)
        unsorted_rows = [rows[8], rows[0]]
        unsorted_rows[1]["x"] = "99"

        with self.assertRaises(InputValidationError) as captured:
            build_config_from_form_data(
                node_x_text=", ".join(str(value) for value in config["node_x"]),
                thickness_text=str(config["thickness"]),
                gauss_n_text=str(config["gauss_n"]),
                points_per_element_text=str(config["points_per_element"]),
                query_xs_text="",
                measurement_rows=unsorted_rows,
                boundary_rows=boundary_rows_from_prescribed_dofs(
                    config["prescribed_dofs"]
                ),
                true_point_rows=true_point_rows_from_config(config),
                plot_options=copy.deepcopy(config["plot_options"]),
                require_measurements=False,
            )

        self.assertEqual(captured.exception.field, "/measurements/1/x")

    def test_json_import_runs_full_measurement_validation(self):
        config = get_sample_config()
        config["elements_sensor_data"][0]["measurements"][0]["surface"] = "sideways"

        with self.assertRaises(InputValidationError) as captured:
            load_config_from_json(json.dumps(config))

        self.assertEqual(captured.exception.field, "/measurements/0/surface")

    def test_duplicate_boundary_keys_are_rejected_before_normalization(self):
        config = get_sample_config()
        config["prescribed_dofs"] = {"01": 1.0, "1": 2.0}

        with self.assertRaises(InputValidationError) as captured:
            normalize_config(config)

        self.assertEqual(captured.exception.field, "/boundary_conditions/1/dof")

    def test_boolean_floats_and_invalid_plot_scalars_are_rejected(self):
        cases = (
            ("thickness", "/sections/active/thickness", lambda config: config.__setitem__("thickness", True)),
            (
                "strain",
                "/measurements/0/strain",
                lambda config: config["elements_sensor_data"][0]["measurements"][0].__setitem__("strain", True),
            ),
            (
                "figsize",
                "/view_state/figsize/0",
                lambda config: config["plot_options"].__setitem__("figsize", [float("nan"), 4]),
            ),
            (
                "label offset",
                "/view_state/label_offset_scale",
                lambda config: config["plot_options"].__setitem__("label_offset_scale", "bad"),
            ),
        )
        for name, field, mutate in cases:
            with self.subTest(name=name):
                config = get_sample_config()
                mutate(config)
                with self.assertRaises(InputValidationError) as captured:
                    validate_config(config)
                self.assertEqual(captured.exception.field, field)


if __name__ == "__main__":
    unittest.main()
