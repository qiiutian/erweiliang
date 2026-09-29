"""Workbench contracts for atomic table transactions and session-wide history."""

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea, QTableWidgetSelectionRange

import gui_qt
from config_adapter import config_to_json, get_sample_config
from ifem.domain.project import empty_beam_project
from ifem.infrastructure import load_project, save_project
from ifem.modeling import PathBeamEditor
from ifem.ui.theme import application_stylesheet
from test_ui_support import isolated_workspace_settings


@isolated_workspace_settings
class TableWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        question = patch.object(
            gui_qt.QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard
        )
        question.start()
        self.addCleanup(question.stop)
        critical = patch.object(gui_qt.QMessageBox, "critical")
        critical.start()
        self.addCleanup(critical.stop)
        self.window = gui_qt.ReconstructionMainWindow()
        self.addCleanup(self._dispose_window)

    def _dispose_window(self):
        if getattr(self, "_window_disposed", False):
            return
        self._window_disposed = True
        self.window.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    @staticmethod
    def _select(editor, top, left, bottom=None, right=None):
        bottom = top if bottom is None else bottom
        right = left if right is None else right
        editor.table.setCurrentCell(top, left)
        editor.table.clearSelection()
        editor.table.setRangeSelected(
            QTableWidgetSelectionRange(top, left, bottom, right), True
        )

    @staticmethod
    def _selection(editor):
        return sorted((item.row(), item.column()) for item in editor.table.selectedIndexes())

    def _change_strain(self, text="0.00042"):
        self._select(self.window.measurement_editor, 0, 4)
        self.assertTrue(self.window.measurement_editor.paste_text(text))

    def _add_measurement(self):
        editor = self.window.measurement_editor
        editor.set_form_values({
            "element": "0", "x": "0.1", "surface": "top", "y": "",
            "strain": "0.0001", "weight": "1", "zone_a": "0.05", "zone_b": "0.15",
        })
        count = len(editor.get_rows())
        editor.add_row()
        self.assertEqual(len(editor.get_rows()), count + 1)
        return editor.get_rows()[-1]["_entity_id"]

    def test_single_column_paste_is_one_atomic_command_and_preserves_hidden_fields(self):
        editor = self.window.measurement_editor
        before = editor.get_rows()
        self._select(editor, 0, 4, 2, 4)
        self.assertTrue(editor.paste_text("0.0001\n0.0002\n0.0003"))
        after = editor.get_rows()
        self.assertEqual([row["strain"] for row in after[:3]], ["0.0001", "0.0002", "0.0003"])
        for old, new in zip(before, after):
            for key in ("_entity_id", "y", "weight", "zone_a", "zone_b"):
                self.assertEqual(old.get(key), new.get(key))
        self.assertEqual(self.window.table_undo_stack.count(), 1)
        self.assertTrue(self.window.project_dirty)
        self.window.table_undo_stack.undo()
        self.assertEqual(editor.get_rows(), before)
        self.window.table_undo_stack.redo()
        self.assertEqual(editor.get_rows(), after)

    def test_rectangular_visible_column_paste_skips_hidden_y_column(self):
        editor = self.window.measurement_editor
        before = editor.get_rows()
        self._select(editor, 0, 0, 1, 4)
        self.assertTrue(editor.paste_text("0\t0.2\ttop\t0.0001\n0\t0.3\tbot\t0.0002"))
        after = editor.get_rows()
        self.assertEqual(after[0]["x"], "0.2")
        self.assertEqual(after[1]["surface"], "bot")
        self.assertEqual(after[1]["strain"], "0.0002")
        self.assertEqual(after[0]["y"], before[0]["y"])
        self.assertEqual(after[1]["zone_a"], before[1]["zone_a"])

    def test_invalid_batch_changes_neither_rows_selection_history_clipboard_nor_project(self):
        editor = self.window.measurement_editor
        self._select(editor, 0, 4, 2, 4)
        before_rows = editor.get_rows()
        before_selection = self._selection(editor)
        before_project = self.window.current_project_document.to_dict()
        self.app.clipboard().setText("external clipboard must survive")
        self.assertFalse(editor.paste_text("0.0001\nnot-a-number\n0.0003"))
        self.assertEqual(editor.get_rows(), before_rows)
        self.assertEqual(self._selection(editor), before_selection)
        self.assertEqual(self.window.table_undo_stack.count(), 0)
        self.assertEqual(self.window.current_project_document.to_dict(), before_project)
        self.assertFalse(self.window.project_dirty)
        self.assertEqual(self.app.clipboard().text(), "external clipboard must survive")

    def test_boundary_duplicate_rejects_entire_rectangular_paste(self):
        editor = self.window.boundary_editor
        before = editor.get_rows()
        self._select(editor, 0, 0, 1, 2)
        self.assertFalse(editor.paste_text("0\tu\t0.1\n0\tu\t0.2"))
        self.assertEqual(editor.get_rows(), before)
        self.assertEqual(self.window.table_undo_stack.count(), 0)

    def test_three_tables_share_chronological_undo_and_redo(self):
        editors = (
            self.window.measurement_editor, self.window.boundary_editor, self.window.true_point_editor
        )
        before = [editor.get_rows() for editor in editors]
        for editor, column, value in zip(editors, (4, 2, 3), ("0.0004", "0.01", "0.12")):
            self.assertIs(editor.undo_stack, self.window.table_undo_stack)
            self._select(editor, 0, column)
            self.assertTrue(editor.paste_text(value))
        after = [editor.get_rows() for editor in editors]
        self.assertEqual(self.window.table_undo_stack.count(), 3)
        for index in (2, 1, 0):
            self.window.table_undo_stack.undo()
            self.assertEqual(editors[index].get_rows(), before[index])
            for previous in range(index):
                self.assertEqual(editors[previous].get_rows(), after[previous])
        for index in (0, 1, 2):
            self.window.table_undo_stack.redo()
            self.assertEqual(editors[index].get_rows(), after[index])

    def test_copy_selected_rectangle_exports_visible_columns_only(self):
        editor = self.window.measurement_editor
        self._select(editor, 0, 0, 1, 4)
        text = editor.copy_selected()
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(len(line.split("\t")) == 4 for line in lines))
        self.assertEqual(self.app.clipboard().text(), text)
        self.assertNotIn("sensor-", text)
        self.assertEqual(self.window.table_undo_stack.count(), 0)
        self.assertFalse(self.window.project_dirty)

    def test_fill_down_is_a_single_transaction(self):
        editor = self.window.measurement_editor
        before = editor.get_rows()
        self._select(editor, 0, 4, 2, 4)
        self.assertTrue(editor.fill_down())
        self.assertEqual([row["strain"] for row in editor.get_rows()[:3]], [before[0]["strain"]] * 3)
        self.assertEqual(self.window.table_undo_stack.count(), 1)
        self.window.table_undo_stack.undo()
        self.assertEqual(editor.get_rows(), before)

    def test_fill_down_cannot_create_duplicate_boundary_constraints(self):
        editor = self.window.boundary_editor
        before = editor.get_rows()
        self._select(editor, 0, 0, 1, 1)
        self.assertFalse(editor.fill_down())
        self.assertEqual(editor.get_rows(), before)
        self.assertEqual(self.window.table_undo_stack.count(), 0)

    def test_multirow_delete_is_one_undoable_transaction(self):
        editor = self.window.measurement_editor
        before = editor.get_rows()
        self._select(editor, 1, 0, 3, 4)
        editor.delete_selected()
        self.assertEqual(editor.get_rows(), before[:1] + before[4:])
        self.assertEqual(self.window.table_undo_stack.count(), 1)
        self.window.table_undo_stack.undo()
        self.assertEqual(editor.get_rows(), before)

    def test_delete_save_undo_save_restores_sensor_identity_label_and_channel(self):
        project = self.window.current_project_document
        original = replace(project.sensors[0], label="SG-keep-label", channel_id="channel-keep")
        project = project.revised(sensors=(original, *project.sensors[1:]))
        self.window._apply_project_document(project, dirty=False, status_text="测试项目已载入")
        editor = self.window.measurement_editor
        editor.table.selectRow(0)
        editor.delete_selected()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensor-history.ifemproj"
            self.assertTrue(self.window._save_project_to(path))
            self.assertNotIn(original.identifier, {sensor.identifier for sensor in load_project(path).sensors})
            self.window.table_undo_stack.undo()
            self.assertEqual(editor.get_rows()[0]["_entity_id"], original.identifier)
            self.assertTrue(self.window._save_project_to(path))
            restored = next(sensor for sensor in load_project(path).sensors if sensor.identifier == original.identifier)
        self.assertEqual(restored.label, "SG-keep-label")
        self.assertEqual(restored.channel_id, "channel-keep")

    def test_new_sensor_identity_exists_before_save_and_survives_saved_undo_redo(self):
        identifier = self._add_measurement()
        self.assertTrue(identifier)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new-sensor-history.ifemproj"
            self.assertTrue(self.window._save_project_to(path))
            self.assertIn(identifier, {sensor.identifier for sensor in load_project(path).sensors})
            self.window.table_undo_stack.undo()
            self.assertTrue(self.window._save_project_to(path))
            self.window.table_undo_stack.redo()
            self.assertEqual(self.window.measurement_editor.get_rows()[-1]["_entity_id"], identifier)
            self.assertTrue(self.window._save_project_to(path))
            self.assertIn(identifier, {sensor.identifier for sensor in load_project(path).sensors})

    def test_new_boundary_identity_survives_saved_undo_redo(self):
        editor = self.window.boundary_editor
        editor.set_form_values({"node": "1", "dof": "phi", "value": "0"})
        editor.add_row()
        identifier = editor.get_rows()[-1]["_entity_id"]
        self.assertTrue(identifier)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new-boundary-history.ifemproj"
            self.assertTrue(self.window._save_project_to(path))
            self.window.table_undo_stack.undo()
            self.assertTrue(self.window._save_project_to(path))
            self.window.table_undo_stack.redo()
            self.assertTrue(self.window._save_project_to(path))
            self.assertEqual(editor.get_rows()[-1]["_entity_id"], identifier)
            self.assertIn(identifier, {item.identifier for item in load_project(path).boundary_conditions})

    def _check_identical_replacement_uses_new_identity(self, editor, collection):
        before_rows = editor.get_rows()
        before_config = self.window._build_form_config()
        original_id = before_rows[-1]["_entity_id"]
        identical_fields = {
            key: value for key, value in before_rows[-1].items() if key != "_entity_id"
        }
        editor.table.selectRow(len(before_rows) - 1)
        editor.delete_selected()
        editor.set_form_values(identical_fields)
        editor.add_row()
        replacement_id = editor.get_rows()[-1]["_entity_id"]
        self.assertNotEqual(replacement_id, original_id)
        self.assertEqual(self.window._build_form_config(), before_config)
        self.assertEqual(self.window.table_undo_stack.count(), 2)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identical-row-replacement.ifemproj"
            self.assertTrue(self.window._save_project_to(path))
            saved_ids = {item.identifier for item in getattr(load_project(path), collection)}
            self.assertIn(replacement_id, saved_ids)
            self.assertNotIn(original_id, saved_ids)
            self.assertEqual(editor.get_rows()[-1]["_entity_id"], replacement_id)

            self.window.table_undo_stack.undo()  # Remove the newly added entity.
            self.window.table_undo_stack.undo()  # Restore the deleted entity.
            self.assertEqual(editor.get_rows(), before_rows)
            self.assertTrue(self.window._save_project_to(path))
            restored_ids = {item.identifier for item in getattr(load_project(path), collection)}
            self.assertIn(original_id, restored_ids)
            self.assertNotIn(replacement_id, restored_ids)

    def test_identical_sensor_replacement_is_not_lost_to_config_equality(self):
        self._check_identical_replacement_uses_new_identity(
            self.window.measurement_editor, "sensors"
        )

    def test_identical_boundary_replacement_is_not_lost_to_config_equality(self):
        self._check_identical_replacement_uses_new_identity(
            self.window.boundary_editor, "boundary_conditions"
        )

    def test_load_project_path_discards_history_from_previous_document(self):
        self._change_strain()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loaded.ifemproj"
            save_project(path, self.window.current_project_document)
            self.assertTrue(self.window.load_project_path(path))
        self.assertEqual(self.window.table_undo_stack.count(), 0)
        self.assertFalse(self.window.project_dirty)

    def test_json_import_and_sample_replacement_reset_history(self):
        self._change_strain()
        self.window.json_text.setPlainText(config_to_json(get_sample_config()))
        self.window.import_json_to_form()
        self.assertEqual(self.window.table_undo_stack.count(), 0)
        self._change_strain()
        self.assertTrue(self.window.load_sample_data())
        self.assertEqual(self.window.table_undo_stack.count(), 0)

    def test_modeler_accept_resets_history_but_reject_keeps_it(self):
        self._change_strain()
        before = self.window.measurement_editor.get_rows()

        class RejectedModeler:
            def __init__(self, project, parent=None):
                self.project = project

            def exec(self):
                return QDialog.DialogCode.Rejected

        class AcceptedModeler(RejectedModeler):
            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch.object(gui_qt, "BeamModelerDialog", RejectedModeler):
            self.window.open_interactive_modeler()
        self.assertEqual(self.window.table_undo_stack.count(), 1)
        self.assertEqual(self.window.measurement_editor.get_rows(), before)
        with patch.object(gui_qt, "BeamModelerDialog", AcceptedModeler):
            self.window.open_interactive_modeler()
        self.assertEqual(self.window.table_undo_stack.count(), 0)

    def test_geometry_change_resets_index_based_table_history(self):
        self._change_strain()
        self.window.node_x_edit.setText("0, 1, 2, 4")
        self.assertEqual(self.window.table_undo_stack.count(), 0)

    def test_busy_state_blocks_direct_table_mutation_and_undo_action(self):
        editor = self.window.measurement_editor
        self._change_strain()
        before = editor.get_rows()
        self.window._set_analysis_busy(True)
        try:
            self.assertFalse(editor.paste_text("0.0009"))
            self.assertFalse(editor.undo_action.isEnabled())
            editor.undo_action.trigger()
            self.assertEqual(editor.get_rows(), before)
            self.assertEqual(self.window.table_undo_stack.index(), 1)
        finally:
            self.window._set_analysis_busy(False)
        self.assertTrue(editor.undo_action.isEnabled())

    def test_spatial_document_clears_tables_and_cannot_be_modified_through_paste(self):
        self._change_strain()
        project = PathBeamEditor.create_circular_arc(
            empty_beam_project(modeling_space="3d"), radius=2.0, sweep_degrees=90.0, plane="xz"
        )
        self.window._apply_project_document(project, dirty=False, status_text="空间项目已载入")
        self.assertEqual(self.window.table_undo_stack.count(), 0)
        for editor in (self.window.measurement_editor, self.window.boundary_editor, self.window.true_point_editor):
            self.assertEqual(editor.get_rows(), [])
            self.assertFalse(editor.paste_text("0\t0\t0\t0"))
            self.assertEqual(editor.get_rows(), [])
        self.assertEqual(self.window.current_project_document.to_dict(), project.to_dict())

    def test_plugin_recovery_blocks_true_points_without_blocking_measurement_repair(self):
        project = self.window.current_project_document
        case = replace(project.analysis_cases[0], algorithm_id="vendor.missing.table-test")
        self.window._apply_project_document(
            project.revised(analysis_cases=(case,)), dirty=False, status_text="插件待恢复"
        )
        self.assertTrue(self.window.analysis_setup.should_preserve_saved_case)
        editor = self.window.true_point_editor
        before = editor.get_rows()
        self._select(editor, 0, 3)
        self.assertFalse(editor.paste_text("0.12"))
        self.assertEqual(editor.get_rows(), before)
        self._change_strain()
        self.assertEqual(self.window.table_undo_stack.count(), 1)

    def test_unrelated_invalid_parameters_do_not_block_measurement_repair(self):
        self.window.query_xs_edit.setText("not a coordinate")
        self.window.y_min_edit.setText("invalid plot setting")
        self.window.analysis_setup.parameter_editor("gauss_n").setCurrentText("2")
        editor = self.window.boundary_editor
        rows = editor.get_rows()
        rows[0]["value"] = "bad boundary value"
        editor.set_rows(rows)
        self._change_strain()
        self.assertEqual(self.window.measurement_editor.get_rows()[0]["strain"], "0.00042")
        self.assertFalse(self.window.run_button.isEnabled())

    def test_window_disposal_does_not_emit_late_history_signal_errors(self):
        self._change_strain()
        with patch("sys.excepthook") as uncaught:
            self._dispose_window()
        self.assertFalse(uncaught.called, "Shared history callbacks outlived their Qt stack")

    def test_invalid_boundary_paste_reveals_feedback_in_small_window_without_selection_change(self):
        self.window.resize(1180, 760)
        self.window.show()
        self.window._focus_input_tab(2)
        self.app.processEvents()
        editor = self.window.boundary_editor
        self._select(editor, 0, 0, 1, 2)
        selection = self._selection(editor)
        self.assertFalse(editor.paste_text("0\tu\t0.1\n0\tu\t0.2"))
        self.app.processEvents()
        QTest.qWait(30)
        self.app.processEvents()

        scroll_area = editor.status_label.parentWidget()
        while scroll_area is not None and not isinstance(scroll_area, QScrollArea):
            scroll_area = scroll_area.parentWidget()
        self.assertIsNotNone(scroll_area)
        viewport = scroll_area.viewport()
        feedback_rect = QRect(
            editor.status_label.mapTo(viewport, QPoint(0, 0)), editor.status_label.size()
        )
        self.assertTrue(editor.status_label.isVisible())
        self.assertTrue(
            viewport.rect().contains(feedback_rect),
            f"Feedback {feedback_rect} must be fully inside scroll viewport {viewport.rect()}",
        )
        self.assertEqual(self._selection(editor), selection)

    def test_wrapped_measurement_error_is_fully_visible_after_theme_layout_settles(self):
        # Wrapping changes the feedback height after the paste callback. A
        # zero-delay scroll can reveal its old one-line height and crop line 2.
        self.window.setStyleSheet(application_stylesheet("graphite"))
        self.window.resize(1180, 760)
        self.window.show()
        self.window._focus_input_tab(1)
        self.app.processEvents()
        editor = self.window.measurement_editor
        self._select(editor, 0, 4, 2, 4)
        selection = self._selection(editor)
        self.assertFalse(editor.paste_text("0.0001\ninvalid\n0.0003"))
        self.app.processEvents()
        QTest.qWait(30)
        self.app.processEvents()
        scroll_area = editor.status_label.parentWidget()
        while not isinstance(scroll_area, QScrollArea):
            scroll_area = scroll_area.parentWidget()
            self.assertIsNotNone(scroll_area)
        viewport = scroll_area.viewport()
        feedback_rect = QRect(
            editor.status_label.mapTo(viewport, QPoint(0, 0)), editor.status_label.size()
        )
        self.assertTrue(viewport.rect().contains(feedback_rect))
        self.assertEqual(self._selection(editor), selection)

    def test_cross_table_undo_and_redo_identify_the_changed_table_in_current_feedback(self):
        target = self.window.measurement_editor
        source = self.window.boundary_editor
        before = target.get_rows()
        self._change_strain()
        after = target.get_rows()
        self.window._focus_input_tab(2)

        source.undo()
        self.assertEqual(target.get_rows(), before)
        self.assertIn(target.title, source.status_label.text())
        source.redo()
        self.assertEqual(target.get_rows(), after)
        self.assertIn(target.title, source.status_label.text())

    def test_padded_uppercase_boundary_dof_saves_and_keeps_raw_undo_history(self):
        editor = self.window.boundary_editor
        before = editor.get_rows()
        self._select(editor, 0, 1)
        self.assertTrue(editor.paste_text(" U "))
        self.assertEqual(editor.get_rows()[0]["dof"], " U ")
        self.assertTrue(self.window._table_identities_match(self.window.current_project_document))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "padded-boundary.ifemproj"
            self.assertTrue(self.window._save_project_to(path))
            saved = load_project(path)
            self.assertEqual(saved.boundary_conditions[0].identifier, before[0]["_entity_id"])
            self.assertEqual(saved.boundary_conditions[0].dof, "u")
            self.assertEqual(editor.get_rows()[0]["dof"], " U ")
            self.assertTrue(editor.undo())
            self.assertEqual(editor.get_rows(), before)
            self.assertTrue(editor.redo())
            self.assertEqual(editor.get_rows()[0]["dof"], " U ")
            self.assertTrue(self.window._save_project_to(path))
            self.assertEqual(editor.get_rows()[0]["_entity_id"], before[0]["_entity_id"])


if __name__ == "__main__":
    unittest.main()
