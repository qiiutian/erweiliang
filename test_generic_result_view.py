from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

import numpy as np
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton

from ifem.domain.analysis import AnalysisResult, ReconstructionState, ResultField, ResultLocation
from ifem.ui.generic_result_view import GenericResultView
from ifem.ui.studio import ElidingLabel
from ifem.ui.theme import compose_stylesheet, resolve_theme
from ifem.ui.workspace_preferences import ReadingPreferences


IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def make_result(*, space="3d", regime="small_deformation", include_fields=True):
    reference = ((1.0, 0.2, 2.0), (0.0, 0.0, 0.0), (3.0, 2.0, 4.0))
    displacement = ((0.1, 0.2, 0.3), (0.0, 0.0, 0.0), (0.3, -0.1, 0.4))
    if space == "2d":
        reference = tuple((x, y, 0.0) for x, y, _z in reference)
        displacement = tuple((x, y, 0.0) for x, y, _z in displacement)
    state = ReconstructionState(
        modeling_space=space, deformation_regime=regime,
        node_ids=("b", "a", "c"), reference_coordinates=reference,
        displacements=displacement, reference_frames=(IDENTITY,) * 3,
        element_ids=("ab", "bc"), connectivity=(("a", "b"), ("b", "c")),
    )
    field = ResultField("displacement", "node", ("c", "a", "b"), ("x", "y", "z"),
                        (displacement[2], displacement[1], displacement[0]), "m", "global")
    return AnalysisResult("test.generic", "1", state=state,
                          fields={field.identifier: field} if include_fields else {})


def slender_result():
    result = make_result()
    reference = ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 3.0))
    displacements = ((0.004, -0.008, 0.02), (0.0, 0.0, 0.0), (0.012, -0.024, 0.06))
    state = replace(result.state, reference_coordinates=reference, displacements=displacements)
    field = replace(result.fields["displacement"], values=(displacements[2], displacements[1], displacements[0]))
    return replace(result, state=state, fields={"displacement": field})


class GenericResultViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = GenericResultView()
        self.view.resize(720, 470)
        self.view.show()
        self.app.processEvents()
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.shutdown)

    def render(self, result=None):
        self.view.set_result(result or make_result())
        self.app.processEvents()
        self.view.canvas.draw()

    def click_record(self, index, *, move=0):
        self.view.canvas.draw()
        x, y = self.view._screen_positions()[index]
        self.view._on_press(SimpleNamespace(button=1, inaxes=self.view.axes, x=x, y=y))
        self.view._on_release(SimpleNamespace(button=1, inaxes=self.view.axes, x=x + move, y=y))

    def test_all_four_method_families_render_without_native_model(self):
        for space in ("2d", "3d"):
            for regime in ("small_deformation", "large_deformation"):
                with self.subTest(space=space, regime=regime):
                    result = make_result(space=space, regime=regime)
                    self.view.clear()
                    self.render(result)
                    self.assertIsNone(result.native_model)
                    self.assertEqual(self.view.geometry.modeling_space, space)
                    self.assertEqual(len(self.view.geometry.nodes), 3)
                    self.assertEqual(len(self.view.geometry.lines), 2)
                    self.assertEqual(self.view.projection, "3d" if space == "3d" else "xy")
                    self.assertIn("非曲梁精确几何", self.view.description.text())
                    self.assertIn("变形不放大", self.view.description.text())

    def test_3d_uses_actual_xyz_connectivity_not_projected_or_row_order(self):
        self.render()
        self.assertEqual(self.view.axes.name, "3d")
        lines = self.view.axes.lines
        reference = tuple(np.asarray(values) for values in lines[0].get_data_3d())
        deformed = tuple(np.asarray(values) for values in lines[1].get_data_3d())
        np.testing.assert_array_equal(np.column_stack(reference), ((0, 0, 0), (1, 0.2, 2)))
        np.testing.assert_allclose(np.column_stack(deformed), ((0, 0, 0), (1.1, 0.4, 2.3)))

    def test_projections_are_explicit_and_use_correct_axes(self):
        self.render()
        for key, dimensions in (("xy", (0, 1)), ("xz", (0, 2)), ("yz", (1, 2))):
            with self.subTest(projection=key):
                self.view.set_projection(key)
                self.view.canvas.draw()
                self.assertNotEqual(self.view.axes.name, "3d")
                self.assertIn(f"{key.upper()} 二维投影", self.view.description.text())
                x, y = self.view.axes.lines[1].get_data()
                expected = np.asarray(((0, 0, 0), (1.1, 0.4, 2.3)))[:, dimensions]
                np.testing.assert_allclose(np.column_stack((x, y)), expected)
                self.assertEqual(self.view.axes.get_xlabel(), f"{'xyz'[dimensions[0]]} / m")
                self.assertEqual(self.view.axes.get_ylabel(), f"{'xyz'[dimensions[1]]} / m")
        with self.assertRaises(ValueError):
            self.view.set_projection("fake")

    def test_field_component_colorbar_keeps_si_values_and_no_interpolation(self):
        self.render()
        self.view.set_field("displacement")
        self.view.set_component("z")
        self.view.canvas.draw()
        self.assertEqual(self.view.component, "z")
        self.assertEqual(self.view.scalar_layer.unit, "m")
        np.testing.assert_array_equal(self.view._point_artist.get_array(), (0.4, 0.0, 0.3))
        self.assertIn("z / m", self.view.colorbar.ax.get_ylabel())
        self.assertIn("离散原值，非连续场", self.view.description.text())
        self.assertEqual(len(self.view.scalar_layer.points), 3)

    def test_unlocated_field_is_explained_not_invented_as_zero_position(self):
        result = make_result()
        custom = ResultField("energy", "global", ("system",), ("value",), ((7.1,),), "J", "global")
        self.render(replace(result, fields={custom.identifier: custom}))
        self.view.set_field("energy")
        self.assertIsNone(self.view.colorbar)
        self.assertIsNone(self.view._point_artist)
        self.assertEqual(len(self.view.scalar_layer.unlocated_records), 1)
        self.assertIn("无空间位置", self.view.description.text())
        self.assertTrue(self.view.highlight_record("energy", "system"))
        self.assertIsNone(self.view._selection_artist)
        self.assertIn("无空间位置", self.view.selection_label.text())
        self.assertIn("7.1 J", self.view.selection_label.text())

    def test_invalid_legacy_payload_does_not_interrupt_other_views(self):
        result = replace(make_result(), fields={"legacy.raw": [1, 2, 3]})
        self.render(result)
        self.assertTrue(self.view.set_field("legacy.raw"))
        self.assertIn("此字段不可绘制", self.view.description.text())
        self.assertIsNotNone(self.view.geometry)
        self.assertIsNone(self.view.scalar_layer)
        self.assertTrue(self.view.set_field(None))
        self.assertNotIn("此字段不可绘制", self.view.description.text())

    def test_unknown_field_preserves_declared_unit_and_component(self):
        custom = ResultField("vendor.health", "sample", ("q",), ("score",), ((73.2,),), "points", "vendor-frame")
        location = ResultLocation("sample", "q", (2, 1, 3), (2.2, 1.2, 3.2), "ab", "Q")
        self.render(replace(make_result(), fields={custom.identifier: custom}, locations=(location,)))
        self.view.set_field("vendor.health")
        self.assertEqual((self.view.component, self.view.scalar_layer.unit), ("score", "points"))
        self.assertEqual(self.view.scalar_layer.points[0].position, (2.2, 1.2, 3.2))
        self.assertTrue(self.view.highlight_record("vendor.health", "q"))
        self.assertIn("73.2 points", self.view.selection_label.text())

    def test_record_highlight_is_by_id_and_emits_no_pick_loop(self):
        self.render()
        picked, changed = [], []
        self.view.record_selected.connect(lambda *args: picked.append(args))
        self.view.view_changed.connect(lambda: changed.append(True))
        self.assertTrue(self.view.highlight_record("displacement", "b"))
        self.assertEqual(self.view.selected_record, ("displacement", "b"))
        self.assertEqual(self.view._selected_point().value, 0.1)
        self.assertIsNone(self.view.selected_node)
        self.assertEqual(picked, [])
        self.assertEqual(len(changed), 1)
        self.assertTrue(self.view.highlight_record("displacement", "b"))
        self.assertEqual(len(changed), 1)
        self.assertFalse(self.view.highlight_record("displacement", "unknown"))

    def test_point_click_emits_actual_entity_in_2d_and_3d(self):
        for projection in ("xy", "3d"):
            with self.subTest(projection=projection):
                self.render()
                self.view.set_field("displacement")
                self.view.set_projection(projection)
                picked = []
                callback = lambda *args: picked.append(args)
                self.view.record_selected.connect(callback)
                self.click_record(0)
                self.assertEqual(picked, [("displacement", "c")])
                self.view.record_selected.disconnect(callback)

    def test_drag_rotation_does_not_pick_a_record(self):
        self.render()
        self.view.set_field("displacement")
        picked = []
        self.view.record_selected.connect(lambda *args: picked.append(args))
        self.click_record(0, move=20)
        self.assertEqual(picked, [])
        self.assertIsNone(self.view.selected_record)

    def test_shape_node_pick_and_highlight_are_not_fake_result_fields(self):
        self.render(make_result(include_fields=False))
        nodes, records = [], []
        self.view.node_selected.connect(nodes.append)
        self.view.record_selected.connect(lambda *args: records.append(args))
        self.click_record(0)
        self.assertEqual(nodes, ["b"])
        self.assertEqual(records, [])
        self.assertEqual(self.view.selected_node, "b")
        self.assertIsNone(self.view.selected_record)
        self.assertIn("节点 b", self.view.selection_label.text())
        self.assertFalse(self.view.highlight_node("missing"))

    def test_node_and_field_selection_are_mutually_exclusive(self):
        self.render()
        self.view.highlight_record("displacement", "b")
        self.view.highlight_node("a")
        self.assertIsNone(self.view.selected_record)
        self.assertEqual(self.view.selected_node, "a")
        self.assertIsNone(self.view.field_id)
        self.view.highlight_record("displacement", "c")
        self.assertIsNone(self.view.selected_node)
        self.assertEqual(self.view.selected_record, ("displacement", "c"))

    def test_projection_and_component_changes_preserve_record_identity(self):
        self.render()
        self.view.highlight_record("displacement", "b")
        self.view.set_projection("xz")
        self.view.set_component("y")
        self.assertEqual(self.view.selected_record, ("displacement", "b"))
        self.assertAlmostEqual(self.view._selected_point().value, 0.2)
        self.assertIn("y = 0.2 m", self.view.selection_label.text())

    def test_field_change_matches_identity_only_with_same_association(self):
        result = make_result()
        other = ResultField("quality", "node", ("b", "a"), ("q",), ((8,), (9,)), "1")
        self.render(replace(result, fields={**result.fields, "quality": other}))
        self.view.highlight_record("displacement", "b")
        self.view.set_field("quality")
        self.assertEqual(self.view.selected_record, ("quality", "b"))
        self.assertEqual(self.view._selected_point().value, 8)
        self.view.set_field(None)
        self.assertIsNone(self.view.selected_record)

    def test_set_result_clear_are_silent_and_discard_old_selection(self):
        self.render()
        self.view.highlight_record("displacement", "b")
        changed = []
        self.view.view_changed.connect(lambda: changed.append(True))
        self.view.set_result(make_result())
        self.assertIsNone(self.view.selected_record)
        self.assertIsNone(self.view.selected_node)
        self.view.clear()
        self.assertEqual(changed, [])
        self.assertIsNone(self.view.result)
        self.assertIsNone(self.view.geometry)
        self.assertIsNone(self.view.scalar_layer)
        self.assertFalse(self.view.field_selector.isEnabled())

    def test_theme_uses_existing_semantic_graphite_tokens(self):
        self.render()
        self.view.apply_theme("old-other-theme")
        from matplotlib.colors import to_rgba
        theme = resolve_theme("graphite")
        self.assertEqual(self.view.figure.get_facecolor(), to_rgba(theme.color("canvas")))
        self.assertEqual(self.view.axes.lines[1].get_color(), theme.color("primary"))

    def test_largest_text_short_widget_keeps_controls_and_canvas_reachable(self):
        self.view.setFont(QFont("Arial", 16))
        self.view.setStyleSheet("QWidget { font-size: 18px; }")
        self.view.resize(520, 360)
        self.render()
        self.view.set_field("displacement")
        self.view.set_component("z")
        self.app.processEvents()
        self.view.canvas.draw()
        for widget in (self.view.field_selector, self.view.component_selector, self.view.projection_selector,
                       self.view.canvas, self.view.selection_label):
            self.assertGreater(widget.width(), 10)
            self.assertGreater(widget.height(), 10)
            self.assertLessEqual(widget.geometry().right(), self.view.width())
            self.assertLessEqual(widget.geometry().bottom(), self.view.height())

    def test_compact_toolbar_leaves_canvas_space_with_focus_button_and_large_reading(self):
        self.view.setStyleSheet(compose_stylesheet("", "graphite", preferences=ReadingPreferences(120, "comfortable")))
        focus = QPushButton("专注", self.view)
        focus.setFixedWidth(70)
        self.view.toolbar_layout.addWidget(focus)
        self.view.resize(630, 230)
        self.render(slender_result())
        self.view.highlight_record("displacement", "b")
        self.app.processEvents()
        self.view.canvas.draw()
        controls = (self.view.field_selector, self.view.component_selector, self.view.projection_selector, focus)
        centers = [widget.geometry().center().y() for widget in controls]
        self.assertLessEqual(max(centers) - min(centers), 1)
        self.assertLessEqual(self.view.height(), 230)
        self.assertGreaterEqual(self.view.canvas.height(), 110)
        self.assertLess(self.view.field_selector.geometry().bottom(), self.view.description.geometry().top())
        self.assertLess(self.view.description.geometry().bottom(), self.view.canvas.geometry().top())
        self.assertLess(self.view.canvas.geometry().bottom(), self.view.selection_label.geometry().top())
        self.assertLessEqual(self.view.selection_label.geometry().bottom(), self.view.height())

    def test_single_line_descriptions_preserve_full_content_in_tooltips(self):
        self.render()
        self.view.highlight_record("displacement", "b")
        for label in (self.view.description, self.view.selection_label):
            self.assertIsInstance(label, ElidingLabel)
            self.assertFalse(label.wordWrap())
            self.assertLessEqual(label.height(), label.fontMetrics().height() + 4)
            self.assertTrue(label.toolTip())
        self.assertIn("非曲梁精确几何", self.view.description.toolTip())
        self.assertIn("实体 ID：b", self.view.selection_label.toolTip())
        self.assertIn("原值：", self.view.selection_label.toolTip())

    def test_slender_3d_hides_crowded_short_axis_ticks_without_changing_geometry(self):
        result = slender_result()
        self.render(result)
        self.assertEqual(len(self.view.axes.get_xticks()), 0)
        self.assertEqual(len(self.view.axes.get_yticks()), 0)
        self.assertEqual(len(self.view.axes.get_zticks()), 0)
        self.assertIn("短轴刻度略去", self.view.description.toolTip())
        self.assertIn("坐标单位 m", self.view.description.toolTip())
        self.assertTrue(any("z：0 … 3.06 m" in text.get_text() for text in self.view.axes.texts))
        np.testing.assert_array_equal([node.position for node in self.view.geometry.nodes], result.state.deformed_coordinates)
        spans = np.ptp(np.asarray(result.state.reference_coordinates + result.state.deformed_coordinates), axis=0)
        aspect = np.asarray(self.view.axes.get_box_aspect())
        np.testing.assert_allclose(aspect / aspect[-1], spans / spans[-1])
        self.view.set_projection("xz")
        self.assertGreater(len(self.view.axes.get_xticks()), 0)
        self.assertEqual(self.view.axes.get_xlabel(), "x / m")

    def test_compact_3d_legend_and_units_remain_within_canvas(self):
        self.view.resize(630, 230)
        self.render(slender_result())
        self.view.set_field("displacement")
        self.view.set_component("z")
        self.app.processEvents()
        self.view.canvas.draw()
        renderer = self.view.canvas.get_renderer()
        legend = self.view.axes.get_legend()
        bounds = legend.get_window_extent(renderer)
        self.assertGreaterEqual(bounds.y0, 0)
        self.assertLessEqual(bounds.y1, self.view.figure.bbox.height + 1)
        self.assertGreaterEqual(bounds.x0, 0)
        self.assertLessEqual(bounds.x1, self.view.figure.bbox.width + 1)
        self.assertTrue(self.view.colorbar.ax.get_ylabel().endswith("/ m"))

    def test_compact_selectors_keep_full_field_and_component_tooltips(self):
        custom = ResultField("vendor.health", "node", ("b",), ("score",), ((1,),), "points")
        self.render(replace(make_result(), fields={"vendor.health": custom}))
        self.view.set_field("vendor.health")
        self.assertGreaterEqual(self.view.component_selector.minimumContentsLength(), 4)
        self.assertEqual(self.view.component_selector.toolTip(), "score")
        self.assertIn("vendor.health", self.view.field_selector.toolTip())
        self.assertEqual(self.view.projection_selector.toolTip(), "三维 XYZ")

    def test_shutdown_stops_selection_and_redraw_callbacks(self):
        self.render()
        self.view.shutdown()
        changed = []
        self.view.view_changed.connect(lambda: changed.append(True))
        self.assertFalse(self.view.highlight_node("a"))
        self.assertFalse(self.view.highlight_record("displacement", "b"))
        self.view.set_projection("xy")
        self.view.clear()
        self.assertEqual(changed, [])
        self.assertIsNotNone(self.view.result)


if __name__ == "__main__":
    unittest.main()
