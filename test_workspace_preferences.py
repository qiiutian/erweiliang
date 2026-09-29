import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings

from ifem.ui.workspace_preferences import (
    DEFAULT_READING_PREFERENCES,
    DENSITY_SETTINGS_KEY,
    FONT_SCALE_SETTINGS_KEY,
    LAYOUT_SETTINGS_PREFIX,
    ReadingPreferences,
    WorkspacePreferencesStore,
)


class WorkspacePreferencesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = Path(self.directory.name) / "workspace.ini"
        self.settings = QSettings(str(self.filename), QSettings.Format.IniFormat)
        self.addCleanup(self.settings.sync)
        self.store = WorkspacePreferencesStore(self.settings)

    def _write_layout(self, payload, surface="workbench"):
        self.settings.setValue(f"{LAYOUT_SETTINGS_PREFIX}/{surface}", payload)
        self.settings.sync()

    def test_missing_settings_load_defaults_without_creating_keys_or_file(self):
        self.assertEqual(self.store.load_reading(), DEFAULT_READING_PREFERENCES)
        for surface in ("workbench", "modeler"):
            self.assertEqual(self.store.load_layout(surface), {})
        self.assertEqual(self.settings.allKeys(), [])
        self.assertFalse(self.filename.exists())

    def test_default_settings_factory_can_be_isolated_by_ui_tests(self):
        with patch("ifem.ui.workspace_preferences._default_settings", return_value=self.settings) as factory:
            store = WorkspacePreferencesStore()
            self.assertIs(store.settings, self.settings)
            factory.assert_called_once_with()
            explicit_store = WorkspacePreferencesStore(self.settings)
            self.assertIs(explicit_store.settings, self.settings)
            factory.assert_called_once_with()

    def test_reading_preferences_are_frozen_and_sanitize_each_field(self):
        preferences = ReadingPreferences(120, "comfortable")
        with self.assertRaises(FrozenInstanceError):
            preferences.font_scale = 110
        for scale in (None, True, 0, 99, 101, 130, 110.0, "110", [], {}):
            with self.subTest(scale=scale):
                self.assertEqual(ReadingPreferences(scale, "comfortable"), ReadingPreferences(100, "comfortable"))
        for density in (None, True, "COMPACT", "", "wide", [], {}):
            with self.subTest(density=density):
                self.assertEqual(ReadingPreferences(120, density), ReadingPreferences(120, "compact"))

    def test_every_reading_choice_round_trips_through_ini(self):
        for scale in (100, 110, 120):
            for density in ("compact", "comfortable"):
                with self.subTest(scale=scale, density=density):
                    expected = ReadingPreferences(scale, density)
                    self.assertEqual(self.store.save_reading(expected), expected)
                    reopened = WorkspacePreferencesStore(QSettings(str(self.filename), QSettings.Format.IniFormat))
                    self.assertEqual(reopened.load_reading(), expected)

    def test_reading_load_recovers_fields_independently_and_is_read_only(self):
        self.settings.setValue(FONT_SCALE_SETTINGS_KEY, "not-a-number")
        self.settings.setValue(DENSITY_SETTINGS_KEY, "comfortable")
        self.settings.setValue("appearance/theme", "graphite")
        self.settings.sync()
        before = self.filename.read_bytes()
        self.assertEqual(self.store.load_reading(), ReadingPreferences(100, "comfortable"))
        self.assertEqual(self.filename.read_bytes(), before)
        self.settings.setValue(FONT_SCALE_SETTINGS_KEY, "120")
        self.settings.setValue(DENSITY_SETTINGS_KEY, "corrupt")
        self.assertEqual(self.store.load_reading(), ReadingPreferences(120, "compact"))
        for scale in (True, "110.0", "110%", " 110", "1e2", [], {}, 110.0):
            with self.subTest(scale=scale):
                self.settings.setValue(FONT_SCALE_SETTINGS_KEY, scale)
                self.assertEqual(self.store.load_reading().font_scale, 100)

    def test_layout_round_trip_is_readable_versioned_and_surface_specific(self):
        workbench = {
            "ratios": {"workspace": [340, 1060], "lower": [0.6, 0.4]},
            "visibility": {"preview": False, "results": True},
            "window_size": [1440, 900],
        }
        modeler = {"ratios": {"editor": [2, 3]}, "window_size": [1200, 800]}
        self.assertEqual(self.store.save_layout("workbench", workbench), workbench)
        self.store.save_layout("modeler", modeler)
        reopened = WorkspacePreferencesStore(QSettings(str(self.filename), QSettings.Format.IniFormat))
        self.assertEqual(reopened.load_layout("workbench"), workbench)
        self.assertEqual(reopened.load_layout("modeler"), modeler)
        raw = self.settings.value(f"{LAYOUT_SETTINGS_PREFIX}/workbench")
        self.assertEqual(json.loads(raw), {"version": 1, **workbench})
        before = self.filename.read_bytes()
        self.store.load_layout("workbench")
        self.assertEqual(self.filename.read_bytes(), before)

    def test_bad_layout_envelopes_are_ignored_without_writes(self):
        for payload in (None, 42, {}, "{bad", "[]", "null", "{}", '{"version":2}',
                        '{"version":"1"}', '{"version":true}', '{"version":1.0}',
                        " " * 16385, "[" * 2000 + "]" * 2000):
            with self.subTest(payload=str(payload)[:60]):
                self._write_layout(payload)
                before = self.filename.read_bytes()
                self.assertEqual(self.store.load_layout("workbench"), {})
                self.assertEqual(self.filename.read_bytes(), before)

    def test_layout_recovers_valid_fields_and_individual_ratio_entries(self):
        self._write_layout(json.dumps({
            "version": 1,
            "ratios": {"good": [1, 2], "bad": [0, 0], "unknown_valid": [3, 2]},
            "visibility": {"preview": False, "results": "true", "scientific": True},
            "window_size": ["1440", 900],
            "fullscreen": True,
            "selected_page": "results",
            "project": {"dirty": True},
        }))
        self.assertEqual(self.store.load_layout("workbench"), {
            "ratios": {"good": [1, 2], "unknown_valid": [3, 2]},
            "visibility": {"preview": False},
        })

    def test_ratios_reject_nonfinite_nonpositive_extreme_and_malformed_values(self):
        invalid_ratios = ([0, 1], [-1, 2], [1, 20], [20, 1], [1, float("nan")],
                          [1, float("inf")], [1, -float("inf")], [True, 2], ["1", 2],
                          [1], [1, 2, 3], "1,2", None, [10**1000, 1])
        for ratio in invalid_ratios:
            with self.subTest(ratio=str(ratio)[:60]):
                cleaned = self.store.save_layout("workbench", {
                    "ratios": {"damaged": ratio, "good": [1, 19]},
                    "window_size": [1200, 800],
                })
                self.assertEqual(cleaned, {"ratios": {"good": [1, 19]}, "window_size": [1200, 800]})
                self.assertEqual(self.store.load_layout("workbench"), cleaned)

    def test_ratio_names_and_count_are_bounded(self):
        ratios = {"": [1, 1], "x" * 65: [1, 1], "../../page": [1, 1], 1: [1, 1]}
        ratios.update({f"splitter_{index}": [1, 1] for index in range(30)})
        cleaned = self.store.save_layout("modeler", {"ratios": ratios})
        self.assertEqual(len(cleaned["ratios"]), 16)
        self.assertTrue(all(name.startswith("splitter_") for name in cleaned["ratios"]))

    def test_window_size_is_bounded_but_does_not_impose_controller_minimum(self):
        for size in ([0, 900], [-1, 900], [16385, 900], [1440.0, 900],
                     [True, 900], [1440], [1440, 900, 10], "1440x900"):
            with self.subTest(size=size):
                self.assertEqual(self.store.save_layout("workbench", {"window_size": size}), {})
        self.assertEqual(self.store.save_layout("workbench", {"window_size": (1, 16384)}),
                         {"window_size": [1, 16384]})

    def test_save_filters_project_state_and_does_not_mutate_input(self):
        layout = {"ratios": {"main": (1, 2)}, "visibility": {"preview": True},
                  "window_size": (1200, 900), "geometry": "opaque", "fullscreen": True,
                  "selected_page": 2, "results": [1, 2, 3], "version": 99}
        self.store.save_layout("workbench", layout)
        self.assertEqual(layout["ratios"]["main"], (1, 2))
        self.assertEqual(layout["version"], 99)
        raw = json.loads(self.settings.value(f"{LAYOUT_SETTINGS_PREFIX}/workbench"))
        self.assertEqual(set(raw), {"version", "ratios", "visibility", "window_size"})
        self.assertEqual(raw["version"], 1)

    def test_reset_is_scoped_and_preserves_other_local_settings(self):
        unrelated = {"appearance/theme": "graphite", "projects/recent": "project.ifem",
                     "workspace/other": "keep", "appearance/other": "keep"}
        for key, value in unrelated.items():
            self.settings.setValue(key, value)
        self.store.save_reading(ReadingPreferences(120, "comfortable"))
        self.store.save_layout("workbench", {"window_size": [1400, 900]})
        self.store.save_layout("modeler", {"window_size": [1200, 800]})
        self.store.reset_layout("workbench")
        self.assertEqual(self.store.load_layout("workbench"), {})
        self.assertEqual(self.store.load_layout("modeler"), {"window_size": [1200, 800]})
        self.assertEqual(self.store.load_reading(), ReadingPreferences(120, "comfortable"))
        self.assertEqual(self.store.reset_reading(), DEFAULT_READING_PREFERENCES)
        self.assertEqual(self.store.load_reading(), DEFAULT_READING_PREFERENCES)
        self.assertEqual(self.store.load_layout("modeler"), {"window_size": [1200, 800]})
        for key, value in unrelated.items():
            self.assertEqual(self.settings.value(key), value)
        self.assertFalse(self.settings.contains(FONT_SCALE_SETTINGS_KEY))
        self.assertFalse(self.settings.contains(DENSITY_SETTINGS_KEY))

    def test_unknown_surfaces_cannot_read_write_or_clear_other_settings(self):
        self.settings.setValue("unrelated", "keep")
        for surface in ("", "other", "../theme", None, []):
            with self.subTest(surface=surface):
                for operation in (self.store.load_layout, self.store.reset_layout):
                    with self.assertRaises(ValueError):
                        operation(surface)
                with self.assertRaises(ValueError):
                    self.store.save_layout(surface, {})
        self.assertEqual(self.settings.allKeys(), ["unrelated"])


if __name__ == "__main__":
    unittest.main()
