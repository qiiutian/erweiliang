import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

import gui_qt
from ifem.ui import theme as theme_module
from ifem.ui.start_center import StartCenterDialog
from ifem.ui.theme import (
    DEFAULT_THEME_ID,
    THEMES,
    THEMES_BY_ID,
    apply_application_theme,
    application_stylesheet,
    current_theme_id,
    load_theme_id,
    resolve_theme,
    save_theme_id,
)


def _contrast(foreground, background):
    def luminance(value):
        color = QColor(value)
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [channel / 12.92 if channel <= 0.04045 else
                  ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class _ApplicationThemeState:
    """Exercise application caching without repolishing unrelated Qt windows."""

    def __init__(self):
        self.properties = {}
        self.stylesheet = ""
        self.stylesheet_calls = 0

    def property(self, name):
        return self.properties.get(name)

    def setProperty(self, name, value):
        self.properties[name] = value

    def styleSheet(self):
        return self.stylesheet

    def setStyleSheet(self, stylesheet):
        self.stylesheet = stylesheet
        self.stylesheet_calls += 1


class ThemeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = []
        self.original_state = (
            self.app.property("ifemThemeId"),
        )
        # Window integration is checked with each window's real local QSS. The
        # global cache contract is independently exercised on a small state
        # object; never trigger a global repolish of earlier tests' Qt widgets.
        self.application_patch = patch.object(
            gui_qt,
            "apply_application_theme",
            side_effect=lambda theme_id, **_kwargs: apply_application_theme(
                theme_id, app=self.app, update_stylesheet=False
            ),
        )
        self.application_patch.start()
        self.question_patch = patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard
        )
        self.question_patch.start()

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        if self.windows:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.setProperty("ifemThemeId", self.original_state[0])
        self.application_patch.stop()
        self.question_patch.stop()

    def test_only_graphite_exists_and_historical_identifiers_normalize(self):
        self.assertEqual(DEFAULT_THEME_ID, "graphite")
        self.assertEqual(len(THEMES), 1)
        self.assertEqual(set(THEMES_BY_ID), {"graphite"})
        self.assertEqual(THEMES[0].name, "石墨")
        for identifier in (None, "", "graphite", "porcelain_blue", "mist_sage", "warm_stone", "missing"):
            with self.subTest(identifier=identifier):
                self.assertIs(resolve_theme(identifier), THEMES[0])
                self.assertEqual(application_stylesheet(identifier), application_stylesheet("graphite"))

    def test_all_existing_semantic_roles_are_preserved(self):
        expected = {
            "background", "surface", "surface_raised", "surface_muted", "surface_subtle",
            "primary", "primary_hover", "primary_pressed", "primary_soft", "primary_tint",
            "on_primary", "text", "text_strong", "text_secondary", "text_muted", "border",
            "border_strong", "divider", "focus", "sensor", "sensor_hover", "sensor_dark",
            "sensor_soft", "success", "success_soft", "warning", "warning_soft", "danger",
            "danger_soft", "beam", "beam_fill", "node", "canvas", "grid", "viewport_start",
            "viewport_end", "viewport_text",
        }
        self.assertEqual(set(THEMES[0].colors), expected)
        for role, value in THEMES[0].colors.items():
            with self.subTest(role=role):
                self.assertTrue(QColor(value).isValid())
        with self.assertRaises(KeyError):
            THEMES[0].color("nonexistent_role")

    def test_loading_old_preferences_is_read_only_and_saving_normalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "appearance.ini"), QSettings.Format.IniFormat)
            self.assertEqual(load_theme_id(settings), DEFAULT_THEME_ID)
            self.assertFalse(settings.contains("appearance/theme"))
            for legacy in ("porcelain_blue", "mist_sage", "warm_stone", "removed-theme"):
                with self.subTest(legacy=legacy):
                    settings.setValue("appearance/theme", legacy)
                    settings.sync()
                    before = Path(settings.fileName()).read_bytes()
                    self.assertEqual(load_theme_id(settings), DEFAULT_THEME_ID)
                    self.assertEqual(settings.value("appearance/theme"), legacy)
                    self.assertEqual(Path(settings.fileName()).read_bytes(), before)
                    self.assertEqual(save_theme_id(legacy, settings), DEFAULT_THEME_ID)
                    self.assertEqual(settings.value("appearance/theme"), DEFAULT_THEME_ID)

    def test_old_application_properties_resolve_and_apply_without_persisting(self):
        app = _ApplicationThemeState()
        app.setProperty("ifemThemeId", "warm_stone")
        app.setProperty("ifemStylesheetThemeId", "mist_sage")
        self.assertEqual(current_theme_id(app), DEFAULT_THEME_ID)
        self.assertEqual(app.property("ifemThemeId"), "warm_stone")
        with patch("ifem.ui.theme.save_theme_id") as save:
            self.assertEqual(apply_application_theme("porcelain_blue", app=app), DEFAULT_THEME_ID)
            self.assertEqual(app.property("ifemThemeId"), DEFAULT_THEME_ID)
            self.assertEqual(app.property("ifemStylesheetThemeId"), DEFAULT_THEME_ID)
            save.assert_not_called()
            apply_application_theme("unknown", app=app, persist=True)
            save.assert_called_once_with(DEFAULT_THEME_ID)

    def test_repeated_apply_does_not_repolish_application_or_recreate_stylesheets(self):
        app = _ApplicationThemeState()
        apply_application_theme(DEFAULT_THEME_ID, app=app)
        initial_stylesheet = app.styleSheet()
        for identifier in ("graphite", "porcelain_blue", "mist_sage", "warm_stone", None):
            apply_application_theme(identifier, app=app)
        self.assertEqual(app.stylesheet_calls, 1)
        self.assertEqual(app.styleSheet(), initial_stylesheet)

    def test_theme_selection_classes_and_styles_are_removed(self):
        for name in ("ThemePicker", "AppearanceDialog", "ThemeSwatchStrip", "_ThemeChoiceRow"):
            self.assertFalse(hasattr(theme_module, name))
        for selector in ("themePicker", "themeMenu", "themeChoice", "themeRadio", "appearanceDialog"):
            self.assertNotIn(selector, application_stylesheet(DEFAULT_THEME_ID))

    def test_start_center_and_views_normalize_historical_theme_arguments(self):
        dialog = StartCenterDialog(theme_id="warm_stone")
        self.windows.append(dialog)
        self.assertEqual(dialog.theme_id, DEFAULT_THEME_ID)
        self.assertEqual(dialog.preview._theme_id, DEFAULT_THEME_ID)
        self.assertFalse(hasattr(dialog, "theme_picker"))

        window = gui_qt.ReconstructionMainWindow(theme_id="porcelain_blue")
        self.windows.append(window)
        self.assertEqual(window.findChild(QLabel, "appTitle").text(), "iFEM")
        window.apply_theme("mist_sage", persist=False)
        self.assertEqual(window.current_theme_id, DEFAULT_THEME_ID)
        self.assertEqual(window.measurement_preview.MARK_FILL.name().upper(), THEMES[0].color("sensor"))
        self.assertEqual(window.structure_3d_view._theme_id, DEFAULT_THEME_ID)
        self.assertIn(THEMES[0].color("primary"), window.styleSheet())

    def test_repeated_apply_preserves_project_results_plot_size_and_scientific_colormap(self):
        window = gui_qt.ReconstructionMainWindow(theme_id=DEFAULT_THEME_ID)
        self.windows.append(window)
        window.run_reconstruction()
        project = window.current_project_document.to_dict()
        model = window.current_model
        frame_data = json.dumps(asdict(window.current_result_frame), default=lambda array: array.tolist())
        initial_size = tuple(window.figure.get_size_inches())
        initial_dirty = window.project_dirty
        sequence = window.result_sequence
        for _index in range(3):
            for identifier in ("warm_stone", "mist_sage", "porcelain_blue", DEFAULT_THEME_ID):
                window.apply_theme(identifier, persist=False)
        self.assertEqual(window.current_project_document.to_dict(), project)
        self.assertEqual(window.project_dirty, initial_dirty)
        self.assertEqual(window.result_sequence, sequence)
        self.assertIs(window.current_model, model)
        self.assertEqual(
            json.dumps(asdict(window.current_result_frame), default=lambda array: array.tolist()),
            frame_data,
        )
        self.assertEqual(tuple(window.figure.get_size_inches()), initial_size)
        self.assertLessEqual(len(window.figure.axes), 2)
        scientific_maps = [collection.cmap.name for collection in window.axes.collections
                           if collection.get_array() is not None]
        self.assertTrue(scientific_maps)
        self.assertEqual(set(scientific_maps), {"coolwarm"})

    def test_normal_text_and_status_pairs_meet_aa_contrast(self):
        colors = THEMES[0].colors
        for foreground in ("text", "text_strong", "text_secondary", "text_muted"):
            for background in ("background", "surface", "surface_raised", "surface_subtle",
                               "surface_muted", "primary_soft"):
                with self.subTest(foreground=foreground, background=background):
                    self.assertGreaterEqual(_contrast(colors[foreground], colors[background]), 4.5)
        for foreground, background in (
            ("on_primary", "primary"), ("on_primary", "primary_hover"),
            ("on_primary", "primary_pressed"), ("viewport_text", "viewport_start"),
            ("viewport_text", "viewport_end"), ("success", "success_soft"),
            ("warning", "warning_soft"), ("danger", "danger_soft"),
            ("sensor_dark", "sensor_soft"),
        ):
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(_contrast(colors[foreground], colors[background]), 4.5)


if __name__ == "__main__":
    unittest.main()
