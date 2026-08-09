import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(__file__), ".mplconfig"),
)

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel

import gui_qt
from ifem.ui.start_center import StartCenterDialog
from ifem.ui.theme import (
    DEFAULT_THEME_ID,
    THEMES,
    AppearanceDialog,
    ThemePicker,
    load_theme_id,
    resolve_theme,
    save_theme_id,
)


class ThemeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_theme_is_the_first_polished_style(self):
        self.assertEqual(THEMES[0].identifier, DEFAULT_THEME_ID)
        self.assertEqual(THEMES[0].name, "云瓷蓝")
        self.assertEqual(resolve_theme("missing").identifier, DEFAULT_THEME_ID)

    def test_theme_preference_round_trip_and_invalid_value_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory) / "appearance.ini"),
                QSettings.Format.IniFormat,
            )
            self.assertEqual(load_theme_id(settings), DEFAULT_THEME_ID)
            self.assertEqual(save_theme_id("warm_stone", settings), "warm_stone")
            self.assertEqual(load_theme_id(settings), "warm_stone")
            settings.setValue("appearance/theme", "removed-theme")
            self.assertEqual(load_theme_id(settings), DEFAULT_THEME_ID)

    def test_picker_and_appearance_dialog_emit_explicit_theme_ids(self):
        picker = ThemePicker(DEFAULT_THEME_ID)
        picked = []
        picker.theme_changed.connect(picked.append)
        picker.actions["mist_sage"].trigger()
        self.assertEqual(picker.theme_id, "mist_sage")
        self.assertEqual(picked, ["mist_sage"])
        self.assertEqual(picker.button.text(), "月白青")
        self.assertTrue(picker.actions["mist_sage"].isChecked())
        self.assertIn("当前", picker.actions["mist_sage"].text())
        self.assertNotIn("当前", picker.actions[DEFAULT_THEME_ID].text())
        self.assertEqual(len(picker.menu.actions()), len(THEMES))

        dialog = AppearanceDialog(DEFAULT_THEME_ID)
        previewed = []
        dialog.theme_previewed.connect(previewed.append)
        dialog.choice_rows["warm_stone"].radio.setChecked(True)
        self.assertEqual(dialog.selected_theme_id, "warm_stone")
        self.assertEqual(previewed[-1], "warm_stone")
        self.assertTrue(dialog.choice_rows["warm_stone"].property("selected"))
        dialog.close()

    def test_start_center_switches_preview_without_rebuilding_dialog(self):
        dialog = StartCenterDialog(theme_id=DEFAULT_THEME_ID)
        with patch(
            "ifem.ui.start_center.apply_application_theme",
            side_effect=lambda theme_id, **_kwargs: resolve_theme(theme_id).identifier,
        ):
            dialog.theme_picker.actions["warm_stone"].trigger()
        self.assertEqual(dialog.theme_id, "warm_stone")
        self.assertEqual(dialog.preview._theme_id, "warm_stone")
        self.assertIn(
            resolve_theme("warm_stone").color("primary"),
            dialog.styleSheet(),
        )
        dialog.close()

    def test_main_window_applies_theme_to_painted_and_3d_views(self):
        window = gui_qt.ReconstructionMainWindow(theme_id=DEFAULT_THEME_ID)
        self.assertEqual(window.findChild(QLabel, "appTitle").text(), "iFEM")
        self.assertNotIn("重构软件", window.windowTitle())
        with patch.object(gui_qt, "apply_application_theme", return_value="warm_stone"):
            window.apply_theme("warm_stone", persist=False)

        theme = resolve_theme("warm_stone")
        self.assertEqual(window.current_theme_id, "warm_stone")
        self.assertEqual(
            window.measurement_preview.MARK_FILL.name().upper(),
            theme.color("sensor"),
        )
        self.assertEqual(window.structure_3d_view._theme_id, "warm_stone")
        self.assertIn(theme.color("primary"), window.styleSheet())
        window.close()

    def test_repeated_theme_switches_do_not_shrink_or_stack_plot_axes(self):
        window = gui_qt.ReconstructionMainWindow(theme_id=DEFAULT_THEME_ID)
        window.run_reconstruction()
        initial_size = tuple(window.figure.get_size_inches())

        for _index in range(3):
            for theme_id in ("warm_stone", "mist_sage", DEFAULT_THEME_ID):
                window.apply_theme(theme_id, persist=False)

        self.assertEqual(tuple(window.figure.get_size_inches()), initial_size)
        self.assertLessEqual(len(window.figure.axes), 2)
        window.close()


if __name__ == "__main__":
    unittest.main()
