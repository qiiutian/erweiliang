import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from gui_qt import ReconstructionMainWindow
from config_adapter import get_sample_config
from ifem.infrastructure import project_from_legacy_config
from ifem.ui.modeler import BeamModelerDialog
from ifem.ui.studio import CommandPalette, StudioCommand


class StudioInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard)
        patcher.start()
        self.addCleanup(patcher.stop)

    def window(self):
        window = ReconstructionMainWindow(theme_id="porcelain_blue")
        self.addCleanup(window.close)
        window.resize(1180, 760)
        window.show()
        self.app.processEvents()
        return window

    def test_rail_navigation_reveals_input_and_tracks_validation(self):
        window = self.window()
        window.focus_mode_button.setChecked(True)
        QTest.mouseClick(window.workspace_rail.buttons[1], Qt.MouseButton.LeftButton)
        self.assertFalse(window.focus_mode_button.isChecked())
        self.assertEqual(window.left_tabs.currentIndex(), 1)
        self.assertTrue(window.measurement_editor.table.hasFocus())
        window.thickness_edit.setText("invalid")
        window._refresh_input_readiness()
        button = window.workspace_rail.buttons[0]
        self.assertTrue(button.property("hasIssue"))
        self.assertIn("厚度", button.toolTip())
        window.focus_mode_button.setChecked(True)
        window.input_status_label.click()
        self.assertFalse(window.focus_mode_button.isChecked())
        self.assertTrue(button.isChecked())
        self.assertTrue(window.thickness_edit.hasFocus())
        window.thickness_edit.setText("0.0016")
        window._refresh_input_readiness()
        self.assertFalse(button.property("hasIssue"))
        window.focus_mode_button.setChecked(True)
        window.show_data_exchange()
        self.assertFalse(window.focus_mode_button.isChecked())
        self.assertEqual(window.left_tabs.currentIndex(), 4)

    def test_collapsed_panels_survive_focus_mode_and_reset_is_non_mutating(self):
        window = self.window()
        project = window.current_project_document.to_dict()
        before = window.plot_content_stack.height()
        window.result_toggle.click()
        window.preview_toggle.click()
        self.app.processEvents()
        self.assertGreater(window.plot_content_stack.height(), before + 80)
        window.focus_mode_button.click()
        window.focus_mode_button.click()
        self.assertTrue(window.result_group.isHidden())
        self.assertTrue(window.preview_group.isHidden())
        window.reset_workspace_layout()
        self.assertFalse(window.result_group.isHidden())
        self.assertFalse(window.preview_group.isHidden())
        self.assertEqual(window.current_project_document.to_dict(), project)

    def test_single_style_has_no_theme_switch_entries_or_empty_settings(self):
        window = self.window()
        self.assertFalse(hasattr(window.workspace_rail, "appearance_button"))
        self.assertFalse(hasattr(window.workspace_rail, "appearance_requested"))
        menu_titles = [action.text() for action in window.more_button.menu().actions()]
        self.assertIn("重置工作区布局", menu_titles)
        self.assertIn("打开数据交换", menu_titles)
        self.assertFalse(any("风格" in title or "外观" in title for title in menu_titles))
        with patch("gui_qt.CommandPalette") as palette:
            palette.return_value.exec.return_value = QDialog.DialogCode.Rejected
            window.show_command_palette()
        commands = palette.call_args.args[0]
        titles = [command.title for command in commands]
        self.assertFalse(any("风格" in title or "外观" in title for title in titles))
        for title in ("交互建模", "运行重构", "保存项目", "重置工作区布局"):
            self.assertIn(title, titles)
        self.assertEqual(len(window.workspace_rail.buttons), 5)
        self.assertTrue(window.workspace_rail.search_button.isEnabled())

    def test_command_search_executes_only_enabled_explicit_selection(self):
        called = []
        commands = [
            StudioCommand("运行重构", "输入不完整", lambda: called.append("run"), False),
            StudioCommand("打开测点工作区", "Alt+2", lambda: called.append("sensors")),
        ]
        palette = CommandPalette(commands, theme_id="porcelain_blue")
        palette.show()
        self.app.processEvents()
        palette.search.setText("运行")
        QTest.keyClick(palette.search, Qt.Key.Key_Return)
        self.assertIsNone(palette.selected_command)
        self.assertEqual(called, [])
        palette.search.setText("测点")
        QTest.keyClick(palette.search, Qt.Key.Key_Return)
        self.assertIs(palette.selected_command, commands[1])
        palette.selected_command.callback()
        self.assertEqual(called, ["sensors"])
        palette.close()

    def test_command_escape_and_no_match_leave_project_untouched(self):
        window = self.window()
        project = window.current_project_document.to_dict()
        palette = CommandPalette([StudioCommand("保存", "Ctrl+S", window.save_current_project)], window)
        palette.show()
        self.app.processEvents()
        palette.search.setText("no such command")
        self.assertFalse(palette.empty.isHidden())
        QTest.keyClick(palette.search, Qt.Key.Key_Escape)
        self.assertIsNone(palette.selected_command)
        self.assertEqual(window.current_project_document.to_dict(), project)

    def test_outline_search_selection_delete_and_undo_keep_entity_identity(self):
        project = project_from_legacy_config(get_sample_config())
        dialog = BeamModelerDialog(project, theme_id="porcelain_blue")
        self.addCleanup(dialog.reject)
        dialog.resize(1040, 680)
        dialog.show()
        self.app.processEvents()
        dialog._focus_outline()
        sensor_id = project.sensors[0].identifier
        outline = dialog.model_outline
        outline.search.setText(sensor_id)
        item = outline._items[sensor_id]
        self.assertFalse(item.isHidden())
        QTest.keyClick(outline.search, Qt.Key.Key_Return)
        self.assertEqual(dialog.selected_id, sensor_id)
        self.assertEqual(dialog.canvas.selected_id, sensor_id)
        self.assertEqual(dialog.inspector_tabs.currentIndex(), 2)
        QTest.keyClick(outline.tree, Qt.Key.Key_Return)
        self.assertEqual(dialog.inspector_tabs.currentIndex(), 1)
        dialog.delete_button.click()
        self.assertNotIn(sensor_id, outline._items)
        dialog.undo_button.click()
        self.assertIn(sensor_id, outline._items)
        self.assertEqual(dialog.project.to_dict(), project.to_dict())
        dialog._focus_outline()
        outline.search.setText("no matching model object")
        QTest.keyClick(outline.search, Qt.Key.Key_Return)
        self.assertIn("没有匹配对象", outline.hint.text())
        self.assertEqual(dialog.project.to_dict(), project.to_dict())


if __name__ == "__main__":
    unittest.main()
