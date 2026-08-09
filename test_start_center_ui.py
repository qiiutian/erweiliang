import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(__file__), ".mplconfig"),
)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

import gui_qt
from ifem.ui.start_center import (
    START_NEW,
    START_OPEN,
    START_SAMPLE,
    START_WORKSPACE,
    START_CENTER_HERO_PATH,
    StartCenterDialog,
    StartupRequest,
)


class StartCenterUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_startup_request_rejects_inconsistent_paths(self):
        with self.assertRaises(ValueError):
            StartupRequest(START_OPEN)
        with self.assertRaises(ValueError):
            StartupRequest(START_NEW, Path("unexpected.ifemproj"))
        with self.assertRaises(ValueError):
            StartupRequest("unknown")

    def test_dialog_minimum_layout_keeps_primary_controls_visible(self):
        dialog = StartCenterDialog()
        dialog.resize(dialog.minimumSize())
        dialog.show()
        self.app.processEvents()

        self.assertGreaterEqual(dialog.width(), 900)
        self.assertGreaterEqual(dialog.height(), 590)
        self.assertGreaterEqual(dialog.preview.width(), 430)
        self.assertGreaterEqual(dialog.preview.height(), 390)
        self.assertEqual(dialog.new_button.shortcut().toString(), "Ctrl+N")
        self.assertEqual(dialog.open_button.shortcut().toString(), "Ctrl+O")

        for button in (
            dialog.new_button,
            dialog.open_button,
            dialog.sample_button,
            dialog.workspace_button,
            dialog.exit_button,
        ):
            top_left = button.mapTo(dialog, QPoint(0, 0))
            bottom_right = button.mapTo(
                dialog,
                QPoint(button.width(), button.height()),
            )
            self.assertGreaterEqual(top_left.x(), 0)
            self.assertGreaterEqual(top_left.y(), 0)
            self.assertLessEqual(bottom_right.x(), dialog.width())
            self.assertLessEqual(bottom_right.y(), dialog.height())
            self.assertTrue(button.toolTip())
        dialog.close()

    def test_start_center_uses_compact_single_line_copy(self):
        dialog = StartCenterDialog()

        self.assertFalse(dialog.brand_title.wordWrap())
        self.assertEqual(dialog.windowTitle(), "iFEM")
        self.assertEqual(dialog.brand_title.text(), "iFEM")
        self.assertFalse(dialog.headline.wordWrap())
        self.assertFalse(dialog.action_description.wordWrap())
        self.assertNotIn("\n", dialog.headline.text())
        self.assertIsNone(dialog.theme_picker.swatches)
        self.assertEqual(dialog.theme_picker.label.text(), "外观")
        self.assertTrue(START_CENTER_HERO_PATH.is_file())
        self.assertTrue(dialog.preview.has_hero_image)
        for removed_label in (
            "startBrandSubtitle",
            "startBadge",
            "startEyebrow",
            "startActionHint",
            "startFooter",
        ):
            self.assertFalse(dialog.findChildren(QLabel, removed_label))
        for button in (
            dialog.new_button,
            dialog.open_button,
            dialog.sample_button,
            dialog.workspace_button,
            dialog.exit_button,
        ):
            self.assertNotIn("\n", button.text())
        dialog.close()

    def test_dialog_actions_return_explicit_requests(self):
        actions = (
            ("sample_button", START_SAMPLE),
            ("workspace_button", START_WORKSPACE),
            ("new_button", START_NEW),
        )
        for button_name, expected_action in actions:
            with self.subTest(action=expected_action):
                dialog = StartCenterDialog()
                dialog.show()
                self.app.processEvents()
                QTest.mouseClick(
                    getattr(dialog, button_name),
                    Qt.MouseButton.LeftButton,
                )
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.request, StartupRequest(expected_action))

    def test_open_action_keeps_dialog_open_on_cancel_and_returns_path(self):
        dialog = StartCenterDialog()
        dialog.show()
        self.app.processEvents()

        with patch(
            "ifem.ui.start_center.ProjectLibraryDialog.choose_project",
            return_value=None,
        ):
            dialog.open_button.click()
        self.assertIsNone(dialog.request)
        self.assertEqual(dialog.result(), 0)

        project_path = Path("/tmp/example.ifemproj")
        with patch(
            "ifem.ui.start_center.ProjectLibraryDialog.choose_project",
            return_value=project_path,
        ):
            dialog.open_button.click()
        self.assertEqual(
            dialog.request,
            StartupRequest(START_OPEN, project_path),
        )
        dialog.close()

    def test_launcher_cancel_does_not_construct_workspace(self):
        class RejectedStartCenter:
            request = None

            def exec(self):
                return QDialog.DialogCode.Rejected

        with patch.object(gui_qt, "StartCenterDialog", RejectedStartCenter), patch.object(
            gui_qt,
            "ReconstructionMainWindow",
        ) as main_window:
            self.assertEqual(gui_qt.launch_app(), 0)
        main_window.assert_not_called()

    def test_launcher_dispatches_selected_action_after_show(self):
        calls = []

        class SampleStartCenter:
            request = StartupRequest(START_SAMPLE)

            def exec(self):
                return QDialog.DialogCode.Accepted

        class FakeWindow:
            def show(self):
                calls.append("show")

            def load_sample_data(self, *, initial=False):
                calls.append(("sample", initial))

        with patch.object(gui_qt, "StartCenterDialog", SampleStartCenter), patch.object(
            gui_qt,
            "ReconstructionMainWindow",
            FakeWindow,
        ):
            self.assertEqual(gui_qt.launch_app(), 0)
            self.app.processEvents()

        self.assertEqual(calls, ["show", ("sample", False)])

    def test_workspace_action_creates_a_clean_unconfigured_project(self):
        applied = {}

        class FakeWindow:
            current_project_path = Path("old.ifemproj")

            def _apply_project_document(self, project, *, dirty, status_text):
                applied.update(
                    project=project,
                    dirty=dirty,
                    status_text=status_text,
                )

        window = FakeWindow()
        gui_qt._apply_startup_request(window, StartupRequest(START_WORKSPACE))

        self.assertIsNone(window.current_project_path)
        self.assertFalse(applied["dirty"])
        self.assertEqual(len(applied["project"].nodes), 2)
        self.assertEqual(len(applied["project"].sensors), 0)
        self.assertEqual(applied["status_text"], "空白工作台 · 待配置")


if __name__ == "__main__":
    unittest.main()
