import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from config_adapter import get_sample_config
from ifem.infrastructure import project_from_legacy_config, save_project
from ifem.modeling import BeamProjectEditor
from ifem.ui.modeler import BeamModelCanvas, BeamModelerDialog
from ifem.ui.modeler_3d import BeamGeometry3DView
from test_ui_support import isolated_workspace_settings


@isolated_workspace_settings
class ModelerExitSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, *, changed=False):
        project = project_from_legacy_config(get_sample_config())
        dialog = BeamModelerDialog(project, theme_id="porcelain_blue")
        self.addCleanup(dialog.shutdown)
        self.addCleanup(dialog.hide)
        if changed:
            after = BeamProjectEditor.add_node(project, 0.5)
            dialog._commit_project(project, after, "新增节点")
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_unchanged_close_does_not_ask(self):
        dialog = self.dialog()
        with patch.object(QMessageBox, "question") as question:
            self.assertTrue(dialog.close())
        question.assert_not_called()
        self.assertFalse(dialog.isVisible())

    def test_cancel_button_keeps_changes_and_view_alive(self):
        dialog = self.dialog(changed=True)
        current = dialog.project.to_dict()
        cancel = dialog.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Cancel
        )
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question, patch.object(dialog, "shutdown") as shutdown:
            cancel.click()
        question.assert_called_once()
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
        shutdown.assert_not_called()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.project.to_dict(), current)

    def test_window_close_can_be_cancelled_then_explicitly_discarded_once(self):
        dialog = self.dialog(changed=True)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question, patch.object(dialog, "shutdown") as shutdown:
            self.assertFalse(dialog.close())
        question.assert_called_once()
        shutdown.assert_not_called()
        self.assertTrue(dialog.isVisible())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard) as question, patch.object(dialog, "shutdown") as shutdown:
            self.assertTrue(dialog.close())
        question.assert_called_once()
        shutdown.assert_called_once()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_escape_in_selection_mode_does_not_silently_discard(self):
        dialog = self.dialog(changed=True)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        question.assert_called_once()
        self.assertTrue(dialog.isVisible())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard) as question:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        question.assert_called_once()
        self.assertFalse(dialog.isVisible())

    def test_first_escape_exits_tool_mode_without_exit_confirmation(self):
        dialog = self.dialog(changed=True)
        for mode in (
            BeamModelCanvas.MODE_ADD_NODE,
            BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR,
        ):
            with self.subTest(mode=mode):
                # Exercise both state machines even on a headless 3D fallback.
                dialog._set_mode(mode)
                with patch.object(QMessageBox, "question") as question:
                    QTest.keyClick(dialog, Qt.Key.Key_Escape)
                question.assert_not_called()
                self.assertEqual(dialog.canvas.mode, BeamModelCanvas.MODE_SELECT)
                self.assertEqual(dialog.geometry_3d_view.mode, BeamGeometry3DView.MODE_SELECT)
                self.assertTrue(dialog.isVisible())

    def test_undo_to_initial_model_does_not_ask(self):
        dialog = self.dialog(changed=True)
        dialog.undo_stack.undo()
        with patch.object(QMessageBox, "question") as question:
            dialog.reject()
        question.assert_not_called()
        self.assertFalse(dialog.isVisible())

    def test_revision_only_change_does_not_ask(self):
        dialog = self.dialog()
        dialog._apply_project(dialog.project.revised())
        with patch.object(QMessageBox, "question") as question:
            dialog.reject()
        question.assert_not_called()
        self.assertFalse(dialog.isVisible())

    def test_changed_content_is_detected_even_when_revision_is_equal(self):
        dialog = self.dialog()
        dialog._apply_project(
            dialog.project.revised(name="另一个模型", revision=dialog.project.revision)
        )
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            dialog.reject()
        question.assert_called_once()
        self.assertTrue(dialog.isVisible())

    def test_apply_to_workspace_is_accepted_without_discard_question(self):
        dialog = self.dialog(changed=True)
        current = dialog.project.to_dict()
        with patch.object(QMessageBox, "question") as question:
            dialog.apply_to_workspace_button.click()
        question.assert_not_called()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.project.to_dict(), current)
        self.assertFalse(dialog.isVisible())

    def test_saved_file_still_requires_workspace_application(self):
        dialog = self.dialog(changed=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "saved.ifem.json"
            save_project(path, dialog.project)
            dialog.set_project_storage(None, path, project_is_saved=True)
            saved_bytes = path.read_bytes()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
                dialog.reject()
            question.assert_called_once()
            self.assertIn("已保存到项目库", question.call_args.args[2])
            self.assertIn("尚未应用到工作台", question.call_args.args[2])
            self.assertTrue(dialog.isVisible())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                dialog.reject()
            self.assertEqual(path.read_bytes(), saved_bytes)
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_direct_rejected_done_is_guarded(self):
        dialog = self.dialog(changed=True)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            dialog.done(QDialog.DialogCode.Rejected)
        question.assert_called_once()
        self.assertTrue(dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
