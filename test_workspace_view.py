"""Machine-local workspace choices must never become scientific/project state."""

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).parent / ".mplconfig"))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea, QTableWidget

import gui_qt
from ifem.domain.project import empty_beam_project
from ifem.ui.modeler import BeamModelerDialog
from ifem.ui.workspace_preferences import ReadingPreferences, WorkspacePreferencesStore
from ifem.ui.workspace_view import ReadingPreferencesDialog


class WorkspaceViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ifem-workspace-view-")
        self.addCleanup(self.directory.cleanup)
        self.settings = QSettings(str(Path(self.directory.name) / "preferences.ini"), QSettings.Format.IniFormat)
        self.store = WorkspacePreferencesStore(self.settings)
        self.addCleanup(self.settings.sync)
        self.widgets = []
        # Exercise real per-window styles without repolishing older Qt objects
        # or touching the application's real theme preferences.
        for patcher in (
            patch.object(gui_qt, "apply_application_theme", return_value="graphite"),
            patch("ifem.ui.modeler_3d.MODEL_3D_AVAILABLE", False),
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.dispose)

    def dispose(self):
        # Do not close/reject during cleanup: those are persistence operations
        # whose behavior is asserted explicitly in the individual tests.
        for widget in reversed(self.widgets):
            widget.hide()
            if hasattr(widget, "shutdown"):
                widget.shutdown()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def show_widget(self, widget, size):
        self.widgets.append(widget)
        widget.resize(*size)
        widget.show()
        self.app.processEvents()
        QTest.qWait(35)
        return widget

    def window(self, size=(1640, 960)):
        return self.show_widget(gui_qt.ReconstructionMainWindow(
            theme_id="graphite", preferences_store=self.store,
        ), size)

    def modeler(self, parent=None, size=(1280, 820)):
        arguments = {"theme_id": "graphite"}
        if parent is None:
            arguments["preferences_store"] = self.store
        return self.show_widget(BeamModelerDialog(empty_beam_project(), parent, **arguments), size)

    def assert_ratio_close(self, actual, expected, delta=0.015):
        self.assertGreater(min(actual), 0)
        self.assertAlmostEqual(actual[0] / sum(actual), expected[0] / sum(expected), delta=delta)

    def assert_contained(self, widget, container):
        rectangle = QRect(widget.mapTo(container, QPoint(0, 0)), widget.size())
        self.assertTrue(container.rect().contains(rectangle),
                        f"{widget.objectName() or type(widget).__name__}: {rectangle} outside {container.rect()}")

    def set_normal_splitters(self, window):
        window.main_split.setSizes([590, 900])
        window.left_split.setSizes([430, 230])
        window.right_split.setSizes([450, 260])
        window.layout_preferences.capture()
        return copy.deepcopy(window.layout_preferences._ratios)

    def test_reading_changes_preserve_models_undo_drafts_and_nonaccumulating_rows(self):
        window = self.window()
        dialog = self.modeler(window)
        self.assertIs(dialog.preferences_store, self.store)
        window.measurement_editor.table.item(0, 1).setText("0.123")
        window.thickness_edit.setText("1e-")
        dialog._selection_changed("node", dialog.project.nodes[0].identifier)
        dialog.node_y_edit.setText("1e-")
        before = (window.current_project_document.to_dict(), window.project_dirty,
                  window.table_undo_stack.count(), window.table_undo_stack.index(),
                  dialog.project.to_dict(), dialog.undo_stack.count(), dialog.undo_stack.index(),
                  copy.deepcopy(dialog.property_drafts.pending))
        tables = window.findChildren(QTableWidget)
        baseline = [table.verticalHeader().defaultSectionSize() for table in tables]
        original_font_size = window.thickness_edit.font().pixelSize()
        original_control_height = window.thickness_edit.sizeHint().height()
        larger = ReadingPreferences(120, "comfortable")
        window.set_reading_preferences(larger)
        self.assertGreater(window.thickness_edit.font().pixelSize(), original_font_size)
        self.assertGreater(window.thickness_edit.sizeHint().height(), original_control_height)
        first = [table.verticalHeader().defaultSectionSize() for table in tables]
        self.assertTrue(any(after > prior for after, prior in zip(first, baseline)))
        for _ in range(3):
            window.set_reading_preferences(larger)
        self.assertEqual([table.verticalHeader().defaultSectionSize() for table in tables], first)
        self.assertEqual(dialog.reading_preferences, larger)
        self.assertEqual(self.store.load_reading(), ReadingPreferences())
        window.set_reading_preferences(ReadingPreferences())
        self.assertEqual([table.verticalHeader().defaultSectionSize() for table in tables], baseline)
        self.assertEqual(window.thickness_edit.font().pixelSize(), original_font_size)
        self.assertEqual(window.thickness_edit.sizeHint().height(), original_control_height)
        after = (window.current_project_document.to_dict(), window.project_dirty,
                 window.table_undo_stack.count(), window.table_undo_stack.index(),
                 dialog.project.to_dict(), dialog.undo_stack.count(), dialog.undo_stack.index(),
                 copy.deepcopy(dialog.property_drafts.pending))
        self.assertEqual(after, before)
        self.assertEqual(window.thickness_edit.text(), "1e-")
        self.assertEqual(dialog.node_y_edit.text(), "1e-")

    def test_density_changes_control_room_without_changing_font_scale(self):
        window = self.window()
        window.set_reading_preferences(ReadingPreferences(110, "compact"))
        font_size = window.thickness_edit.font().pixelSize()
        compact_height = window.thickness_edit.sizeHint().height()
        table = window.measurement_editor.table
        compact_row = table.verticalHeader().defaultSectionSize()
        window.set_reading_preferences(ReadingPreferences(110, "comfortable"))
        self.assertEqual(window.thickness_edit.font().pixelSize(), font_size)
        self.assertGreater(window.thickness_edit.sizeHint().height(), compact_height)
        self.assertEqual(table.verticalHeader().defaultSectionSize(), compact_row + 8)
        window.set_reading_preferences(ReadingPreferences(110, "compact"))
        self.assertEqual(window.thickness_edit.sizeHint().height(), compact_height)
        self.assertEqual(table.verticalHeader().defaultSectionSize(), compact_row)

    def test_persisted_reading_is_loaded_by_new_window_and_inherited_by_modeler(self):
        first = self.window()
        expected = ReadingPreferences(110, "comfortable")
        first.set_reading_preferences(expected, persist=True)
        self.assertEqual(self.store.load_reading(), expected)
        second = self.window()
        self.assertEqual(second.reading_preferences, expected)
        second.set_reading_preferences(ReadingPreferences(120, "compact"), persist=False)
        child = self.modeler(second)
        self.assertEqual(child.reading_preferences, ReadingPreferences(120, "compact"))
        self.assertEqual(self.store.load_reading(), expected)

    def test_normal_layout_restores_across_instances_after_show(self):
        first = self.window()
        expected = self.set_normal_splitters(first)
        first.close()
        saved = self.store.load_layout("workbench")
        self.assertEqual(saved["visibility"], {"preview": True, "results": True})
        self.assertEqual(saved["window_size"], [first.width(), first.height()])
        second = self.window()
        for key, splitter in second.layout_preferences.splitters.items():
            with self.subTest(splitter=key):
                self.assert_ratio_close(splitter.sizes(), expected[key])
        modeler = self.modeler()
        modeler.workspace_splitter.setSizes([700, 540])
        modeler.layout_preferences.capture()
        expected_modeler = modeler.workspace_splitter.sizes()
        modeler.reject()
        reopened = self.modeler()
        self.assert_ratio_close(reopened.workspace_splitter.sizes(), expected_modeler)

    def test_focus_mode_does_not_replace_normal_ratios_or_persist_focus(self):
        window = self.window()
        expected = self.set_normal_splitters(window)
        window.focus_mode_button.setChecked(True)
        self.app.processEvents()
        self.assertTrue(window.left_panel.isHidden())
        self.assertTrue(window.result_group.isHidden())
        window.layout_preferences.save()
        saved = self.store.load_layout("workbench")
        self.assertEqual(saved["ratios"], expected)
        self.assertEqual(saved["visibility"], {"preview": True, "results": True})
        self.assertNotIn("focus", saved)
        reopened = self.window()
        self.assertFalse(reopened.focus_mode_button.isChecked())
        self.assertFalse(reopened.left_panel.isHidden())
        for key, splitter in reopened.layout_preferences.splitters.items():
            self.assert_ratio_close(splitter.sizes(), expected[key])

    def test_collapsed_panels_restore_and_reexpand_with_healthy_ratios(self):
        first = self.window()
        expected = self.set_normal_splitters(first)
        first.preview_toggle.setChecked(False)
        first.result_toggle.setChecked(False)
        first.focus_mode_button.setChecked(True)
        first.focus_mode_button.setChecked(False)
        first.close()
        self.assertEqual(self.store.load_layout("workbench")["visibility"], {"preview": False, "results": False})
        reopened = self.window()
        self.assertTrue(reopened.preview_group.isHidden())
        self.assertTrue(reopened.result_group.isHidden())
        self.assertFalse(reopened.preview_toggle.isChecked())
        self.assertFalse(reopened.result_toggle.isChecked())
        reopened.preview_toggle.click()
        reopened.result_toggle.click()
        QTest.qWait(35)
        self.assertFalse(reopened.preview_group.isHidden())
        self.assertFalse(reopened.result_group.isHidden())
        self.assert_ratio_close(reopened.left_split.sizes(), expected["input"])
        self.assert_ratio_close(reopened.right_split.sizes(), expected["result"])

    def test_main_close_cancel_and_failed_save_do_not_persist_layout(self):
        window = self.window()
        window.project_dirty = True
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        self.assertEqual(self.store.load_layout("workbench"), {})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
                patch.object(window, "save_current_project", return_value=False):
            self.assertFalse(window.close())
        self.assertEqual(self.store.load_layout("workbench"), {})
        self.assertFalse(window._is_shut_down)
        self.assertTrue(window.close())
        self.assertIn("ratios", self.store.load_layout("workbench"))
        self.assertTrue(window._is_shut_down)

    def test_modeler_cancel_and_invalid_draft_do_not_persist_but_valid_exit_does(self):
        dialog = self.modeler()
        dialog._selection_changed("node", dialog.project.nodes[0].identifier)
        dialog.node_y_edit.setText("1e-")
        before = dialog.project.to_dict()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(dialog.close())
        self.assertEqual(self.store.load_layout("modeler"), {})
        dialog.accept()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog._is_shut_down)
        self.assertEqual(self.store.load_layout("modeler"), {})
        self.assertEqual(dialog.project.to_dict(), before)
        dialog.node_y_edit.setText("0.3")
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(dialog.isVisible())
        self.assertIn("ratios", self.store.load_layout("modeler"))
        self.assertEqual(dialog.project.nodes[0].coordinates[1], 0.3)

    def test_old_modeler_shutdown_does_not_overwrite_newer_layout(self):
        older = self.modeler()
        older.workspace_splitter.setSizes([900, 330])
        newer = self.modeler()
        newer.workspace_splitter.setSizes([700, 540])
        newer.reject()
        saved = self.store.load_layout("modeler")
        self.assertIn("ratios", saved)
        older.shutdown()
        older.shutdown()
        self.assertEqual(self.store.load_layout("modeler"), saved)

    def test_finished_child_modeler_never_restarts_layout_when_parent_reading_changes(self):
        window = self.window()
        older = self.modeler(window)
        older.workspace_splitter.setSizes([700, 540])
        original_reading = older.reading_preferences
        original_stylesheet = older.styleSheet()
        older.layout_preferences.restore_later()
        self.assertTrue(older.layout_preferences._timer.isActive())
        older.reject()
        self.assertTrue(older._finished)
        self.assertTrue(older._is_shut_down)
        self.assertIn(older, window.findChildren(BeamModelerDialog))
        self.assertFalse(older.layout_preferences._timer.isActive())
        saved = self.store.load_layout("modeler")
        self.assertIn("ratios", saved)

        window.set_reading_preferences(ReadingPreferences(120, "comfortable"), persist=True)
        self.assertFalse(older.layout_preferences._timer.isActive())
        self.assertEqual(older.reading_preferences, original_reading)
        self.assertEqual(older.styleSheet(), original_stylesheet)
        self.assertEqual(self.store.load_layout("modeler"), saved)

        older.layout_preferences.restore_later()
        self.assertFalse(older.layout_preferences._timer.isActive())
        QTest.qWait(35)
        self.assertFalse(older.layout_preferences._timer.isActive())
        self.assertEqual(self.store.load_layout("modeler"), saved)

    def test_reset_is_scoped_and_preserves_reading_project_history_and_drafts(self):
        preferences = ReadingPreferences(110, "comfortable")
        self.store.save_reading(preferences)
        window = self.window()
        dialog = self.modeler(window)
        dialog._selection_changed("node", dialog.project.nodes[0].identifier)
        dialog.node_y_edit.setText("1e-")
        before = (window.current_project_document.to_dict(), window.project_dirty,
                  dialog.project.to_dict(), dialog.undo_stack.count(), copy.deepcopy(dialog.property_drafts.pending))
        window.preview_toggle.setChecked(False)
        window.result_toggle.setChecked(False)
        window.layout_preferences.save()
        dialog.layout_preferences.save()
        saved_modeler = self.store.load_layout("modeler")
        window.reset_workspace_layout()
        self.assertEqual(self.store.load_layout("workbench"), {})
        self.assertEqual(self.store.load_layout("modeler"), saved_modeler)
        self.assertTrue(window.preview_toggle.isChecked())
        self.assertTrue(window.result_toggle.isChecked())
        window.layout_preferences.save()
        saved_workbench = self.store.load_layout("workbench")
        dialog.reset_workspace_layout()
        self.assertEqual(self.store.load_layout("modeler"), {})
        self.assertEqual(self.store.load_layout("workbench"), saved_workbench)
        self.assertEqual(self.store.load_reading(), preferences)
        after = (window.current_project_document.to_dict(), window.project_dirty,
                 dialog.project.to_dict(), dialog.undo_stack.count(), copy.deepcopy(dialog.property_drafts.pending))
        self.assertEqual(after, before)
        self.assertEqual(dialog.node_y_edit.text(), "1e-")

    def test_reading_dialog_cancel_and_reset_are_staged_until_apply(self):
        preferences = ReadingPreferences(120, "comfortable")
        self.store.save_reading(preferences)
        window = self.window()
        before = Path(self.settings.fileName()).read_bytes()
        dialog = ReadingPreferencesDialog(preferences, window)
        dialog.show()
        QTest.qWait(35)
        dialog.font_scale_combo.setCurrentIndex(dialog.font_scale_combo.findData(110))
        dialog.density_combo.setCurrentIndex(dialog.density_combo.findData("compact"))
        self.assertEqual(dialog.preferences, ReadingPreferences(110, "compact"))
        dialog.reset_button.click()
        self.assertEqual(dialog.preferences, ReadingPreferences())
        self.assertEqual(window.reading_preferences, preferences)
        self.assertEqual(Path(self.settings.fileName()).read_bytes(), before)
        dialog.reject()
        with patch("gui_qt.ReadingPreferencesDialog", return_value=dialog), \
                patch.object(dialog, "exec", return_value=QDialog.DialogCode.Rejected):
            window.show_reading_preferences()
        self.assertEqual(window.reading_preferences, preferences)
        self.assertEqual(self.store.load_reading(), preferences)
        self.assertEqual(Path(self.settings.fileName()).read_bytes(), before)

    def test_context_buttons_preserve_invalid_text_selection_and_outline_search(self):
        dialog = self.modeler()
        identifier = dialog.project.nodes[0].identifier
        dialog._selection_changed("node", identifier)
        dialog.node_y_edit.setText("1e-")
        self.assertFalse(dialog.property_drafts.apply_all())
        dialog.model_outline.search.setText(identifier)
        before = dialog.project.to_dict()
        pending = copy.deepcopy(dialog.property_drafts.pending)
        for _ in range(3):
            dialog.context_outline_button.click()
            self.assertEqual(dialog.inspector_tabs.currentIndex(), 2)
            self.assertEqual(dialog.model_outline.search.text(), identifier)
            self.assertEqual(dialog.selected_id, identifier)
            self.assertIs(dialog.model_outline.tree.currentItem(), dialog.model_outline._items[identifier])
            dialog.context_edit_button.click()
            self.assertEqual(dialog.inspector_tabs.currentIndex(), 1)
            self.assertEqual(dialog.node_y_edit.text(), "1e-")
            self.assertEqual(dialog.node_y_edit.property("validationState"), "error")
        self.assertEqual(dialog.project.to_dict(), before)
        self.assertEqual(dialog.property_drafts.pending, pending)
        self.assertEqual(dialog.undo_stack.count(), 0)

    def test_large_comfortable_reading_fits_real_minimum_workbench(self):
        self.store.save_reading(ReadingPreferences(120, "comfortable"))
        window = self.window((1180, 760))
        self.assertEqual((window.width(), window.height()), (1180, 760))
        for button in (window.run_button, window.modeler_button, window.more_button,
                       window.command_button, window.preview_toggle, window.result_toggle):
            with self.subTest(button=button.text()):
                self.assertTrue(button.isVisibleTo(window))
                self.assert_contained(button, window)
                self.assert_contained(button, button.parentWidget())
                self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
        window._focus_input_tab(0)
        scroll = window.left_tabs.widget(0).findChild(QScrollArea)
        scroll.ensureWidgetVisible(window.thickness_edit)
        QTest.qWait(35)
        self.assertGreaterEqual(scroll.viewport().height(), window.thickness_edit.height())
        self.assert_contained(window.thickness_edit, scroll.viewport())

    def test_large_comfortable_reading_fits_real_minimum_modeler_and_error_field(self):
        self.store.save_reading(ReadingPreferences(120, "comfortable"))
        dialog = self.modeler(size=(1040, 680))
        self.assertEqual((dialog.width(), dialog.height()), (1040, 680))
        dialog._selection_changed("node", dialog.project.nodes[0].identifier)
        dialog.node_y_edit.setText("1e-")
        self.assertFalse(dialog.property_drafts.apply_all())
        QTest.qWait(40)
        self.assertEqual((dialog.width(), dialog.height()), (1040, 680))
        for button in (dialog.apply_to_workspace_button, dialog.save_project_button,
                       dialog.reset_layout_button, dialog.context_edit_button,
                       dialog.context_outline_button, dialog.draft_apply_all,
                       dialog.draft_discard_all, dialog.spatial_curve_button,
                       dialog.generate_button, dialog.append_button):
            with self.subTest(button=button.text()):
                self.assertTrue(button.isVisibleTo(dialog))
                self.assert_contained(button, dialog)
                self.assert_contained(button, button.parentWidget())
                self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
        viewport = dialog.inspector_tabs.widget(1).viewport()
        self.assertGreaterEqual(viewport.height(), dialog.node_y_edit.height())
        self.assert_contained(dialog.node_y_edit, viewport)


if __name__ == "__main__":
    unittest.main()
