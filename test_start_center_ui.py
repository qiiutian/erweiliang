import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(__file__), ".mplconfig"),
)

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

import gui_qt
from ifem.ui.start_center import (
    BeamWorkflowPreview,
    START_NEW,
    START_OPEN,
    START_SAMPLE,
    START_WORKSPACE,
    START_CENTER_HERO_PATH,
    StartCenterDialog,
    StartupRequest,
)
from ifem.ui.theme import DEFAULT_THEME_ID, resolve_theme


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

    def test_start_center_keeps_project_entries_with_two_line_hero(self):
        dialog = StartCenterDialog()

        self.assertFalse(dialog.brand_title.wordWrap())
        self.assertEqual(dialog.windowTitle(), "iFEM")
        self.assertEqual(dialog.brand_title.text(), "iFEM")
        self.assertFalse(dialog.headline.wordWrap())
        self.assertFalse(dialog.action_description.wordWrap())
        self.assertEqual(dialog.headline.text().splitlines(), ["从应变", "重构形态"])
        self.assertFalse(hasattr(dialog, "theme_picker"))
        self.assertFalse(dialog.findChildren(QLabel, "themeLabel"))
        self.assertTrue(START_CENTER_HERO_PATH.is_file())
        self.assertTrue(hasattr(dialog.preview, "set_phase"))
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

    def test_hero_is_valid_self_contained_vector_art(self):
        self.assertEqual(START_CENTER_HERO_PATH.suffix, ".svg")
        source = START_CENTER_HERO_PATH.read_text(encoding="utf-8")
        root = ET.fromstring(source)
        self.assertEqual(root.attrib["viewBox"], "0 0 720 420")
        for element in root.iter():
            self.assertNotIn(
                element.tag.rsplit("}", 1)[-1],
                ("image", "foreignObject", "script"),
            )
            for name, value in element.attrib.items():
                if name.rsplit("}", 1)[-1] == "href":
                    self.assertTrue(value.startswith("#"))
        self.assertNotIn("data:image", source)
        self.assertTrue(QSvgRenderer(str(START_CENTER_HERO_PATH)).isValid())

    def test_animated_hero_and_controls_fit_the_small_window(self):
        dialog = StartCenterDialog(theme_id=DEFAULT_THEME_ID)
        self.addCleanup(dialog.close)
        for width, height in ((900, 590), (1080, 640)):
            dialog.resize(width, height)
            dialog.show()
            self.app.processEvents()
            for widget in (dialog.preview, dialog.motion_button, dialog.new_button):
                origin = widget.mapTo(dialog, QPoint())
                bounds = QRectF(origin.x(), origin.y(), widget.width(), widget.height())
                self.assertTrue(QRectF(dialog.rect()).contains(bounds))
        self.assertIn("不是真实计算结果", dialog.preview.toolTip())

    def test_legacy_theme_requests_use_the_single_theme_without_an_empty_picker(self):
        for identifier in (DEFAULT_THEME_ID, "porcelain_blue", "mist_sage", "warm_stone"):
            with self.subTest(identifier=identifier):
                dialog = StartCenterDialog(theme_id=identifier)
                self.addCleanup(dialog.close)
                self.assertEqual(dialog.preview._theme_id, DEFAULT_THEME_ID)
                self.assertEqual(dialog.theme_id, DEFAULT_THEME_ID)
                self.assertFalse(hasattr(dialog, "theme_picker"))
                self.assertIsNone(dialog.request)
                self.assertIn(resolve_theme(None).color("primary"), dialog.styleSheet())

    def test_start_center_does_not_depend_on_legacy_image_assets(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("No SVG loading")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("No image loading")):
            preview = BeamWorkflowPreview(theme_id=DEFAULT_THEME_ID)
            preview.set_paused(True)
            self.assertFalse(preview.grab().isNull())
            preview.close()

    def test_motion_toggle_is_persistent_and_does_not_select_a_project(self):
        with patch.dict(os.environ, {"IFEM_REDUCED_MOTION": "0"}), \
             patch("ifem.ui.start_center.QSettings") as settings:
            settings.return_value.value.return_value = False
            dialog = StartCenterDialog(theme_id=DEFAULT_THEME_ID)
            self.addCleanup(dialog.close)
            dialog.preview.set_paused(False)
            dialog.motion_button.setChecked(False)
            dialog.motion_button.click()
            self.assertTrue(dialog.preview.is_paused)
            self.assertEqual(dialog.motion_button.text(), "播放演示")
            settings.return_value.setValue.assert_called_with("appearance/startAnimationPaused", True)
            self.assertIsNone(dialog.request)
            dialog.motion_button.click()
            self.assertFalse(dialog.preview.is_paused)
            self.assertEqual(dialog.motion_button.text(), "暂停演示")

    def test_reduced_motion_displays_a_static_non_actionable_status(self):
        with patch.dict(os.environ, {"IFEM_REDUCED_MOTION": "1"}), \
             patch("ifem.ui.start_center.QSettings") as settings:
            settings.return_value.value.return_value = False
            dialog = StartCenterDialog()
            self.addCleanup(dialog.close)
            self.assertTrue(dialog.preview.is_paused)
            self.assertFalse(dialog.motion_button.isEnabled())
            self.assertEqual(dialog.motion_button.text(), "已减少动态")
            settings.return_value.setValue.assert_not_called()
            self.assertTrue(dialog.new_button.isEnabled())
            self.assertTrue(dialog.open_button.isEnabled())

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

    def test_return_activates_only_the_focused_start_action(self):
        names = (
            "new_button", "open_button", "sample_button", "workspace_button",
            "motion_button", "exit_button",
        )
        expected_actions = {
            "new_button": START_NEW,
            "sample_button": START_SAMPLE,
            "workspace_button": START_WORKSPACE,
        }
        for name in names:
            for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                with self.subTest(button=name, key=key), \
                     patch.dict(os.environ, {"IFEM_REDUCED_MOTION": "0"}), \
                     patch("ifem.ui.start_center.QSettings") as settings, \
                     patch("ifem.ui.start_center.ProjectLibraryDialog.choose_project", return_value=None) as chooser:
                    settings.return_value.value.return_value = False
                    dialog = StartCenterDialog()
                    self.addCleanup(dialog.close)
                    clicked = []
                    for candidate in names:
                        getattr(dialog, candidate).clicked.connect(
                            lambda _checked=False, value=candidate: clicked.append(value)
                        )
                    dialog.show()
                    self.app.processEvents()
                    button = getattr(dialog, name)
                    button.setFocus()
                    self.assertTrue(button.hasFocus())
                    QTest.keyClick(button, key)
                    self.assertEqual(clicked, [name])
                    if name in expected_actions:
                        self.assertEqual(dialog.request, StartupRequest(expected_actions[name]))
                        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                    else:
                        self.assertIsNone(dialog.request)
                    self.assertEqual(chooser.call_count, int(name == "open_button"))
                    if name == "motion_button":
                        self.assertTrue(dialog.preview.is_paused)
                        self.assertTrue(dialog.isVisible())
                        settings.return_value.setValue.assert_called_once_with(
                            "appearance/startAnimationPaused", True,
                        )
                    else:
                        settings.return_value.setValue.assert_not_called()
                    if name == "exit_button":
                        self.assertFalse(dialog.isVisible())
                        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                    dialog.close()

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
