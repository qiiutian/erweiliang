"""Read-only, snapshot-safe linking between result tables and both viewports."""

import copy
import os
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QMessageBox

import gui_qt
from ifem.domain.project import empty_beam_project
from ifem.ui.workspace_preferences import ReadingPreferences
from postprocessing import resolve_thickness_scale
from test_ui_support import isolated_workspace_settings


@isolated_workspace_settings
class ResultProbeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for patcher in (
            patch.object(gui_qt, "apply_application_theme", return_value="graphite"),
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard),
            patch.object(QMessageBox, "critical"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = gui_qt.ReconstructionMainWindow(theme_id="graphite")
        self.addCleanup(self._dispose)
        self.window.resize(1600, 960)
        self.window.show()
        self.app.processEvents()

    def _dispose(self):
        self.window.hide()
        self.window.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _run(self, *, queries="0.375, 1.625", points=120, gauss=3):
        window = self.window
        window.query_xs_edit.setText(queries)
        window.analysis_setup.set_parameter_values({"gauss_n": gauss, "points_per_element": points})
        with patch.object(window, "_show_error") as error:
            window.run_reconstruction()
        error.assert_not_called()
        self.assertIsNotNone(window.current_model)
        self.assertTrue(window.result_link.targets["sample"])
        self.app.processEvents()
        return window.result_link

    def _sample_pixel(self, index):
        window = self.window
        window.canvas.draw()
        scale = resolve_thickness_scale(
            window.current_field, window.current_inputs["plot_options"].get("thickness_scale", "auto")
        )
        gx, gy = window.current_field.display_grid(scale)
        position = ((gx[0, index] + gx[-1, index]) / 2, (gy[0, index] + gy[-1, index]) / 2)
        return window.axes.transData.transform(position)

    def _plot_click(self, point):
        event = SimpleNamespace(button=1, inaxes=self.window.axes, x=float(point[0]), y=float(point[1]))
        self.window.result_link._plot_press(event)
        self.window.result_link._plot_release(event)

    def _representation(self, name):
        combo = self.window.field_representation_combo
        combo.setCurrentIndex(combo.findData(name))

    def test_solver_keeps_live_query_compare_sampling_and_project_entity_ids(self):
        window = self.window
        window.true_point_editor.table.setCurrentCell(0, 3)
        self.assertTrue(window.true_point_editor.paste_text("0.13579"))
        link = self._run(points=173, gauss=4)
        self.assertEqual(window.current_inputs["query_xs"], [0.375, 1.625])
        self.assertEqual(window.current_inputs["gauss_n"], 4)
        self.assertEqual(window.current_inputs["points_per_element"], 173)
        self.assertEqual(window.query_result_table.table.rowCount(), 2)
        self.assertEqual(len(link.targets["query"]), 2)
        self.assertEqual(len(link.targets["compare"]), 2)
        self.assertAlmostEqual(dict((label, value) for label, value, _ in link.targets["compare"][0].values)["v_实测"], 0.13579)
        self.assertEqual(
            {target.source_id for target in link.targets["node"]},
            {node.identifier for node in window.current_project_document.nodes},
        )
        self.assertEqual(window.current_analysis_result.state.project_id, window.current_project_document.identifier)
        self.assertEqual(
            {target.element_id for target in link.targets["sample"]},
            {element.identifier for element in window.current_project_document.elements},
        )

    def test_table_keyboard_updates_exact_target_marker_and_model_highlight(self):
        window = self.window
        link = self._run()
        table = window.node_result_table.table
        window.result_tabs.setCurrentWidget(window.node_result_table)
        table.setCurrentCell(0, 0)
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_Down)
        self.assertEqual((link.selected.kind, link.selected.index), ("node", 1))
        self.assertEqual(window.structure_3d_view._result_selection, ("node", 1))
        self.assertIsNone(window.structure_3d_view._probe_position)
        marker = link._artists[-1]
        self.assertEqual(tuple(marker.get_xdata()), (link.selected.position[0],))
        self.assertEqual(tuple(marker.get_ydata()), (link.selected.position[1],))
        self.assertIn(link.selected.source_id, window.probe_bar.title.toolTip())
        self.assertTrue(window.probe_bar.locate_button.isEnabled())
        self.assertTrue(window.probe_bar.clear_button.isEnabled())

    def test_query_and_comparison_use_interpolated_position_not_mesh_identity(self):
        window = self.window
        link = self._run()
        for kind in ("query", "compare"):
            table = link.tables[kind].table
            table.setCurrentCell(1, 0)
            target = link.selected
            self.assertEqual((target.kind, target.index), (kind, 1))
            self.assertIsNone(window.structure_3d_view._result_selection)
            self.assertEqual(window.structure_3d_view._probe_position, target.position)
            self.assertIsNone(window.node_result_table.table.currentItem())
        self.assertIn("Δv", window.probe_bar.detail.text())

    def test_2d_pick_adds_exact_missing_dense_sample_without_neighbor_substitution(self):
        window = self.window
        link = self._run(points=320)
        table = window.field_result_table.table
        visible = {table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(table.rowCount())}
        self.assertEqual(len(visible), 240)
        # An interior station avoids ambiguous coincident element boundaries.
        index = next(index for index in range(80, 200) if index not in visible)
        point = self._sample_pixel(index)
        picked = link.pick_2d(*point)
        self.assertEqual((picked.kind, picked.index), ("sample", index))
        self._plot_click(point)
        self.assertEqual(link.selected.index, index)
        self.assertEqual(table.currentItem().data(Qt.ItemDataRole.UserRole), index)
        self.assertEqual(table.rowCount(), 241)
        self.assertEqual(table.item(table.currentRow(), 0).text(), str(index + 1))
        self.assertIs(window.result_tabs.currentWidget(), window.field_result_table)
        self.assertEqual(window.structure_3d_view._result_selection, ("sample", index))
        self.assertEqual(len(link._artists), 2)
        # Moving the probe does not grow the visible table indefinitely.
        another = next(value for value in range(index + 1, 220) if value not in visible)
        link.select("sample", another)
        self.assertEqual(table.rowCount(), 241)
        self.assertEqual(table.currentItem().data(Qt.ItemDataRole.UserRole), another)

    def test_shape_click_prefers_node_and_does_not_consume_drag_or_navigation_mode(self):
        window = self.window
        link = self._run()
        window._switch_view("shape")
        window.canvas.draw()
        point = window.axes.transData.transform(link.targets["node"][1].position[:2])
        self.assertEqual(link.pick_2d(*point).kind, "node")
        self._plot_click(point)
        self.assertEqual((link.selected.kind, link.selected.index), ("node", 1))
        link.clear_selection()
        press = SimpleNamespace(button=1, inaxes=window.axes, x=point[0], y=point[1])
        release = SimpleNamespace(button=1, inaxes=window.axes, x=point[0] + 20, y=point[1])
        link._plot_press(press)
        link._plot_release(release)
        self.assertIsNone(link.selected)
        with patch.object(window.canvas, "toolbar", SimpleNamespace(mode="pan/zoom")):
            self._plot_click(point)
        self.assertIsNone(link.selected)

    def test_model_pick_signal_locates_exact_table_identity(self):
        window = self.window
        link = self._run()
        table = window.field_result_table.table
        visible = {table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(table.rowCount())}
        index = next(value for value in range(len(link.targets["sample"])) if value not in visible)
        window.structure_3d_view.result_picked.emit("sample", index)
        self.assertEqual((link.selected.kind, link.selected.index), ("sample", index))
        self.assertIs(window.result_tabs.currentWidget(), window.field_result_table)
        self.assertEqual(table.currentItem().data(Qt.ItemDataRole.UserRole), index)

    def test_new_result_clears_old_probe_and_uses_new_snapshot_identity(self):
        link = self._run()
        link.select("node", 1)
        previous = link.selected
        previous_sequence = link.sequence
        self._run()
        self.assertGreater(link.sequence, previous_sequence)
        self.assertIsNone(link.selected)
        self.assertFalse(link._artists)
        self.assertTrue(all(wrapper.table.currentRow() == -1 for wrapper in link.tables.values()))
        self.assertNotEqual(link.targets["node"][1].entity_id, previous.entity_id)
        self.assertIsNone(self.window.structure_3d_view._result_selection)

    def test_failed_rerun_restores_previous_probe_snapshot_and_marks_it_stale(self):
        window = self.window
        link = self._run()
        link.select("query", 1)
        previous = link.selected
        model, field, sequence = window.current_model, window.current_field, window.result_sequence
        with patch.object(window.analysis_service, "run", side_effect=ValueError("controlled failure")), patch.object(window, "_show_error") as error:
            window.run_reconstruction()
        error.assert_called_once()
        self.assertIs(window.current_model, model)
        self.assertIs(window.current_field, field)
        self.assertEqual(window.result_sequence, sequence)
        self.assertEqual(link.selected, previous)
        self.assertTrue(window.results_stale)
        self.assertIn("已过期", window.probe_bar.title.text())
        self.assertEqual(window.structure_3d_view._probe_position, previous.position)
        self.assertFalse(window._analysis_busy)

    def test_failure_after_new_render_rolls_back_partial_snapshot_and_selection(self):
        window = self.window
        link = self._run()
        link.select("sample", 10)
        previous = link.selected
        model, field, sequence = window.current_model, window.current_field, window.result_sequence
        fill_tables = window._fill_result_tables
        attempts = []

        def fail_once(model, inputs):
            attempts.append(window.result_sequence)
            if len(attempts) == 1:
                raise ValueError("table update failed after new plot rendered")
            return fill_tables(model, inputs)

        with patch.object(window, "_fill_result_tables", side_effect=fail_once), patch.object(window, "_show_error") as error:
            window.run_reconstruction()
        error.assert_called_once()
        self.assertEqual(attempts, [sequence + 1, sequence])
        self.assertIs(window.current_model, model)
        self.assertIs(window.current_field, field)
        self.assertEqual(window.result_sequence, sequence)
        self.assertEqual(link.sequence, sequence)
        self.assertEqual(link.selected, previous)
        self.assertTrue(window.results_stale)
        self.assertEqual(window.field_result_table.table.currentItem().data(Qt.ItemDataRole.UserRole), 10)
        self.assertEqual(window.structure_3d_view._result_selection, ("sample", 10))

    def test_busy_and_stopped_controller_reject_late_pick_without_changing_probe(self):
        window = self.window
        link = self._run()
        link.select("node", 1)
        previous = link.selected
        window._set_analysis_busy(True)
        self.assertFalse(link.select("sample", 10))
        window.structure_3d_view.result_picked.emit("node", 2)
        self.assertEqual(link.selected, previous)
        window._set_analysis_busy(False)
        link.shutdown()
        self.assertFalse(link.select("sample", 10))
        window.structure_3d_view.result_picked.emit("node", 2)
        self.assertEqual(link.selected, previous)

    def test_input_changes_leave_immutable_old_positions_until_rerun(self):
        window = self.window
        link = self._run()
        link.select("node", 1)
        selected = link.selected
        positions = tuple(target.position for target in link.targets["node"])
        window.measurement_editor.table.setCurrentCell(0, 4)
        self.assertTrue(window.measurement_editor.paste_text("0.0008"))
        window.query_xs_edit.setText("0.25, 2.75")
        self.assertTrue(window.results_stale)
        self.assertIs(link.selected, selected)
        self.assertEqual(tuple(target.position for target in link.targets["node"]), positions)
        self.assertEqual(window.current_inputs["query_xs"], [0.375, 1.625])
        with self.assertRaises(FrozenInstanceError):
            selected.position = (0.0, 0.0, 0.0)
        self.assertIn("上一次计算结果", window.probe_bar.title.toolTip())

    def test_field_representation_change_clears_sample_but_preserves_node_and_query(self):
        window = self.window
        link = self._run()
        link.select("sample", 10)
        old = link.selected
        self._representation("raw")
        self.assertIsNone(link.selected)
        self.assertFalse(link._artists)
        self.assertIsNone(window.structure_3d_view._result_selection)
        self.assertNotEqual(link.targets["sample"][10].entity_id, old.entity_id)
        self.assertEqual(link.targets["sample"][10].representation, "raw")
        for kind in ("node", "query"):
            link.select(kind, 1)
            target = link.selected
            self._representation("nodal_average")
            self.assertEqual(link.selected, target)
            self._representation("raw")
            self.assertEqual(link.selected, target)

    def test_missing_elastic_modulus_never_invents_stress_or_stress_pick(self):
        window = self.window
        window.elastic_modulus_edit.clear()
        link = self._run()
        self.assertIsNone(window.current_field.stress)
        self.assertEqual(window.current_view, "strain")
        link.select("sample", 10)
        stress = [value for label, value, _unit in link.selected.values if "应力" in label]
        self.assertEqual(stress, [None, None])
        self.assertIn("未提供", window.probe_bar.detail.text())
        table = window.field_result_table.table
        column = window.field_result_table.columns.index("上表面应力")
        self.assertEqual(table.item(table.currentRow(), column).text(), "--")
        window._switch_view("stress")
        self.assertFalse(link._artists)
        self.assertIsNone(link.pick_2d(100, 100))
        self.assertIsNotNone(link.selected)

    def test_selection_copy_and_clear_do_not_mutate_project_or_undo_history(self):
        window = self.window
        link = self._run()
        before = (
            copy.deepcopy(window.current_project_document.to_dict()), window.project_dirty,
            window.table_undo_stack.count(), window.table_undo_stack.index(),
        )
        before_inputs = copy.deepcopy(window.current_inputs)
        for kind in ("node", "query", "compare", "sample"):
            link.select(kind, 1)
            wrapper = link.tables[kind]
            self.assertEqual(wrapper.table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
            self.assertTrue(wrapper.copy_selected_row())
            self.assertIn("\t", self.app.clipboard().text())
        window.probe_bar.clear_button.click()
        self.assertIsNone(link.selected)
        self.assertTrue(all(wrapper.table.currentRow() == -1 for wrapper in link.tables.values()))
        self.assertFalse(window.probe_bar.clear_button.isEnabled())
        self.assertFalse(window.probe_bar.locate_button.isEnabled())
        self.assertEqual(
            (window.current_project_document.to_dict(), window.project_dirty,
             window.table_undo_stack.count(), window.table_undo_stack.index()),
            before,
        )
        np.testing.assert_equal(window.current_inputs, before_inputs)

    def test_replacing_project_clears_result_identities_tables_and_probe(self):
        window = self.window
        link = self._run()
        link.select("sample", 10)
        window._apply_project_document(empty_beam_project(), dirty=False, status_text="新项目")
        self.assertIsNone(link.selected)
        self.assertEqual(link.targets, {})
        self.assertIsNone(link.sequence)
        self.assertFalse(link._artists)
        self.assertTrue(all(wrapper.table.rowCount() == 0 for wrapper in link.tables.values()))
        self.assertIsNone(window.structure_3d_view.frame)
        self.assertFalse(window.probe_bar.locate_button.isEnabled())

    def test_locate_exits_focus_and_reopens_result_panel_without_changing_probe(self):
        window = self.window
        link = self._run()
        link.select("query", 1)
        target = link.selected
        window.result_toggle.setChecked(False)
        window.focus_mode_button.setChecked(True)
        window.probe_bar.locate_button.click()
        self.assertFalse(window.focus_mode_button.isChecked())
        self.assertTrue(window.result_toggle.isChecked())
        self.assertIs(window.result_tabs.currentWidget(), window.query_result_table)
        self.assertEqual(link.selected, target)
        self.assertEqual(window.query_result_table.table.currentRow(), 1)

    def test_large_comfortable_minimum_layout_keeps_probe_actions_visible(self):
        window = self.window
        link = self._run()
        window.set_reading_preferences(ReadingPreferences(120, "comfortable"))
        window.resize(1180, 760)
        link.select("sample", 100)
        self.app.processEvents()
        QTest.qWait(150)
        window.canvas.draw()
        self.assertEqual((window.width(), window.height()), (1180, 760))
        bar = window.probe_bar
        self.assertTrue(bar.isVisible())
        for widget in (bar.title, bar.detail, bar.locate_button, bar.clear_button):
            rect = QRect(widget.mapTo(bar, QPoint()), widget.size())
            self.assertTrue(bar.rect().contains(rect), f"{widget.objectName()}: {rect} outside {bar.rect()}")
            self.assertGreater(widget.width(), 0)
            self.assertGreater(widget.height(), 0)
        self.assertTrue(window.probe_bar.title.accessibleDescription())
        self.assertTrue(window.probe_bar.detail.accessibleDescription())
        table = window.field_result_table.table
        self.assertGreaterEqual(table.viewport().height(), table.rowHeight(0))
        self.assertGreaterEqual(window.axes.get_window_extent().height, 50)

    def test_first_postprocessing_failure_restores_empty_snapshot(self):
        window = self.window
        with patch.object(window, "_fill_result_tables", side_effect=ValueError("late failure")):
            window.run_reconstruction()
        self.assertIsNone(window.current_model)
        self.assertIsNone(window.current_analysis_result)
        self.assertIsNone(window.current_config)
        self.assertIsNone(window.current_inputs)
        self.assertEqual(window.result_sequence, 0)
        self.assertEqual(window.result_link.targets, {})
        self.assertIsNone(window.result_link.selected)
        self.assertIsNone(window.structure_3d_view.frame)
        self.assertEqual(window.run_status_label.property("state"), "error")

    def test_busy_rejected_picks_restore_table_and_viewport_consistency(self):
        window = self.window
        link = self._run()
        link.select("sample", 100)
        selected = link.selected
        window._set_analysis_busy(True)
        try:
            window.structure_3d_view.set_result_selection("node", 0)
            window.structure_3d_view.result_picked.emit("node", 0)
            self.assertEqual(window.structure_3d_view._result_selection, ("sample", 100))
            window.node_result_table.table.setCurrentCell(1, 0)
            self.assertEqual(window.node_result_table.table.currentRow(), -1)
            self.assertEqual(link.selected, selected)
            table = window.field_result_table.table
            self.assertEqual(table.item(table.currentRow(), 0).data(Qt.ItemDataRole.UserRole), 100)
        finally:
            window._set_analysis_busy(False)


if __name__ == "__main__":
    unittest.main()
