import os
import re
import unittest
from dataclasses import dataclass
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QTabBar

from ifem.ui.theme import (
    DEFAULT_THEME_ID,
    THEMES,
    apply_reading_preferences,
    application_stylesheet,
    compose_stylesheet,
)


@dataclass(frozen=True)
class _Preferences:
    """Exercise the pure style API without loading a preference store."""

    font_scale: int = 100
    density: str = "compact"


class ReadingStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_and_explicit_compact_are_byte_for_byte_compatible(self):
        baseline = "QLabel { font-size: 12px; padding: 2px 5px; }"
        expected = baseline + "\n" + application_stylesheet(DEFAULT_THEME_ID)
        self.assertEqual(compose_stylesheet(baseline, DEFAULT_THEME_ID), expected)
        self.assertEqual(compose_stylesheet(baseline, DEFAULT_THEME_ID, preferences=None), expected)
        self.assertEqual(
            compose_stylesheet(baseline, DEFAULT_THEME_ID, preferences=_Preferences()), expected
        )
        self.assertIs(apply_reading_preferences(baseline), baseline)
        self.assertIs(apply_reading_preferences(baseline, _Preferences()), baseline)

    def test_font_scaling_preserves_units_families_colors_and_non_font_dimensions(self):
        baseline = '''QLabel { font-family: "Avenir Next"; font-size: 13px;
            color: #292E31; width: 100px; min-height: 22px; padding: 5px 8px; }
            QPushButton { font-size: 10.5pt; font-weight: 500; }
            QLabel#relative { font-size: 1.2em; }
            /* A historical font-size: 10px; is not an active declaration. */'''
        for scale, px_size, pt_size in ((110, "14.3", "11.55"), (120, "15.6", "12.6")):
            with self.subTest(scale=scale):
                adjusted = apply_reading_preferences(baseline, _Preferences(font_scale=scale))
                expected = baseline.replace("font-size: 13px", f"font-size: {px_size}px")
                expected = expected.replace("font-size: 10.5pt", f"font-size: {pt_size}pt")
                self.assertEqual(adjusted, expected)

    def test_repeated_composition_from_baseline_does_not_accumulate_scale_or_density(self):
        baseline = "QPushButton { font-size: 10px; padding: 5px 8px; }"
        comfortable = _Preferences(font_scale=120, density="comfortable")
        expected = compose_stylesheet(baseline, DEFAULT_THEME_ID, preferences=comfortable)
        expected_local = apply_reading_preferences(baseline, comfortable)
        for _index in range(4):
            self.assertEqual(
                compose_stylesheet(baseline, DEFAULT_THEME_ID, preferences=comfortable), expected
            )
            self.assertEqual(
                apply_reading_preferences(baseline, comfortable),
                expected_local,
            )
            compact = compose_stylesheet(baseline, DEFAULT_THEME_ID, preferences=_Preferences())
            self.assertEqual(compact, compose_stylesheet(baseline, DEFAULT_THEME_ID))
        self.assertIn("font-size: 12px; padding: 7px 8px", expected)
        self.assertEqual(baseline, "QPushButton { font-size: 10px; padding: 5px 8px; }")

    def test_density_changes_only_vertical_control_padding(self):
        baseline = '''
QLineEdit, QComboBox { padding: 5px 8px; min-width: 30px; min-height: 22px; }
QPushButton { padding: 6px; }
QToolButton#tool { padding: 1px 2px 3px; }
QHeaderView::section { padding: 1px 2px 3px 4px; }
QTabWidget#editor QTabBar::tab:selected { padding: 0 9px; }
QPlainTextEdit { padding-top: 3px; padding-bottom: 4px; padding-right: 7px; }
QTextEdit { padding: 0; }
QLabel { padding: 5px 8px; }
QFrame#plotCanvas { padding: 7px; width: 100px; height: 200px; }
QTableWidget::item { padding: 3px 5px; }
QComboBox::drop-down { padding: 1px; width: 22px; }
QToolButton::menu-indicator { padding: 1px; width: 9px; }
'''
        adjusted = apply_reading_preferences(baseline, _Preferences(density="comfortable"))
        for rule in (
            "QLineEdit, QComboBox { padding: 7px 8px; min-width: 30px; min-height: 22px; }",
            "QPushButton { padding: 8px 6px; }",
            "QToolButton#tool { padding: 3px 2px 5px; }",
            "QHeaderView::section { padding: 3px 2px 5px 4px; }",
            "QTabWidget#editor QTabBar::tab:selected { padding: 2px 9px; }",
            "QPlainTextEdit { padding-top: 5px; padding-bottom: 6px; padding-right: 7px; }",
            "QTextEdit { padding: 2px 0; }",
            "QLabel { padding: 5px 8px; }",
            "QFrame#plotCanvas { padding: 7px; width: 100px; height: 200px; }",
            "QTableWidget::item { padding: 3px 5px; }",
            "QComboBox::drop-down { padding: 1px; width: 22px; }",
            "QToolButton::menu-indicator { padding: 1px; width: 9px; }",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, adjusted)

    def test_mixed_label_button_selector_does_not_expand_the_label(self):
        baseline = 'QLabel#badge, QPushButton#badge[state="ready"] { padding: 3px 9px; }'
        adjusted = apply_reading_preferences(baseline, _Preferences(density="comfortable"))
        self.assertIn("QLabel#badge{ padding: 3px 9px; }", adjusted)
        self.assertIn('QPushButton#badge[state="ready"] { padding: 5px 9px; }', adjusted)

    def test_real_theme_keeps_colors_and_horizontal_geometry(self):
        baseline = application_stylesheet(DEFAULT_THEME_ID)
        colors = re.findall(r"#[\da-fA-F]{6}\b", baseline)
        dimensions = re.findall(r"(?:min-|max-)?(?:width|height):[^;]+;", baseline)
        families = re.findall(r"font-family:[^;]+;", baseline)
        for scale in (100, 110, 120):
            for density in ("compact", "comfortable"):
                with self.subTest(scale=scale, density=density):
                    adjusted = apply_reading_preferences(baseline, _Preferences(scale, density))
                    self.assertEqual(re.findall(r"#[\da-fA-F]{6}\b", adjusted), colors)
                    self.assertEqual(re.findall(r"(?:min-|max-)?(?:width|height):[^;]+;", adjusted), dimensions)
                    self.assertEqual(re.findall(r"font-family:[^;]+;", adjusted), families)
        self.assertEqual([theme.identifier for theme in THEMES], ["graphite"])

    def test_preferences_are_explicit_and_do_not_read_or_write_settings(self):
        with patch("ifem.ui.theme._default_settings", side_effect=AssertionError("settings access")):
            for identifier in (DEFAULT_THEME_ID, "warm_stone", None):
                result = compose_stylesheet(
                    "QLabel { font-size: 10px; }", identifier,
                    preferences=_Preferences(120, "comfortable"),
                )
                self.assertIn("font-size: 12px", result)

    def test_qt_accepts_fractional_font_sizes_and_leaves_application_font_alone(self):
        original_font = self.app.font()
        label = QLabel("阅读字号")
        try:
            label.setStyleSheet(apply_reading_preferences(
                "QLabel { font-size: 13px; }", _Preferences(font_scale=120)
            ))
            label.ensurePolished()
            self.assertEqual(label.font().pixelSize(), 16)
            self.assertEqual(self.app.font(), original_font)
        finally:
            label.deleteLater()

    def test_qt_density_adds_four_pixels_height_without_increasing_control_width(self):
        baseline = '''QPushButton, QLineEdit { padding: 5px 8px; font-size: 13px; }
            QTabBar::tab { padding: 6px 9px; font-size: 13px; }'''
        adjusted = apply_reading_preferences(baseline, _Preferences(density="comfortable"))
        controls = [QPushButton("Example"), QLineEdit("Example"), QTabBar()]
        controls[-1].addTab("Example")
        try:
            for control in controls:
                with self.subTest(control=type(control).__name__):
                    control.setStyleSheet(baseline)
                    control.ensurePolished()
                    original = control.sizeHint()
                    control.setStyleSheet(adjusted)
                    control.ensurePolished()
                    self.assertEqual(control.sizeHint().width(), original.width())
                    self.assertEqual(control.sizeHint().height(), original.height() + 4)
        finally:
            for control in controls:
                control.deleteLater()


if __name__ == "__main__":
    unittest.main()
