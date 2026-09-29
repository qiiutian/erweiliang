"""Validated, machine-local reading and workspace preferences.

These settings belong to this installation's QSettings, never to an iFEM
project document. Layouts deliberately contain only readable splitter ratios,
optional-panel visibility and window dimensions: no opaque Qt state, position,
full-screen state, selected page or scientific/project data is persisted.

Loading is read-only and independently recovers valid fields from damaged
settings. A future or malformed layout version safely falls back to defaults.
Window controllers remain responsible for their own minimum sizes and fitting
restored dimensions to the currently available screen.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from PySide6.QtCore import QSettings


FONT_SCALE_SETTINGS_KEY = "appearance/font_scale"
DENSITY_SETTINGS_KEY = "appearance/density"
LAYOUT_SETTINGS_PREFIX = "workspace/layout"
LAYOUT_VERSION = 1
_FONT_SCALES = (100, 110, 120)
_DENSITIES = ("compact", "comfortable")
_SURFACES = ("workbench", "modeler")
_MAX_LAYOUT_LENGTH = 16_384
_MAX_RATIO_COUNT = 16
_MAX_RATIO_VALUE = 1_000_000_000
_MIN_RATIO_SHARE = 0.05
_MAX_WINDOW_DIMENSION = 16_384
_RATIO_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


def _font_scale(value: object, *, allow_settings_string: bool = False) -> int:
    # INI-backed QSettings can return canonical integer values as strings after
    # reopening; accept those exact encodings without accepting 110.0 or bool.
    if allow_settings_string and type(value) is str and value in ("100", "110", "120"):
        value = int(value)
    return value if type(value) is int and value in _FONT_SCALES else 100


def _density(value: object) -> str:
    return value if type(value) is str and value in _DENSITIES else "compact"


@dataclass(frozen=True)
class ReadingPreferences:
    """The only supported reading choices; invalid fields use safe defaults."""

    font_scale: int = 100
    density: str = "compact"

    def __post_init__(self) -> None:
        object.__setattr__(self, "font_scale", _font_scale(self.font_scale))
        object.__setattr__(self, "density", _density(self.density))


DEFAULT_READING_PREFERENCES = ReadingPreferences()


def _default_settings() -> QSettings:
    """Return the machine-local settings; an injection point for UI tests."""
    return QSettings("iFEM", "iFEM Reconstruction")


def _valid_ratio(value: object) -> list[int | float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(type(part) not in (int, float) for part in value):
        return None
    # The bounded comparison also rejects huge integers before float conversion.
    if any(not 0 < part <= _MAX_RATIO_VALUE for part in value):
        return None
    if any(not math.isfinite(part) for part in value):
        return None
    total = value[0] + value[1]
    if min(value) / total < _MIN_RATIO_SHARE:
        return None
    return list(value)


def _clean_layout(layout: object) -> dict:
    if not isinstance(layout, dict):
        return {}
    cleaned = {}
    ratios = layout.get("ratios")
    if isinstance(ratios, dict):
        valid_ratios = {}
        for name, value in ratios.items():
            if type(name) is not str or not _RATIO_NAME.fullmatch(name):
                continue
            ratio = _valid_ratio(value)
            if ratio is not None:
                valid_ratios[name] = ratio
                if len(valid_ratios) >= _MAX_RATIO_COUNT:
                    break
        if valid_ratios:
            cleaned["ratios"] = valid_ratios
    visibility = layout.get("visibility")
    if isinstance(visibility, dict):
        valid_visibility = {
            name: visibility[name]
            for name in ("preview", "results")
            if name in visibility and type(visibility[name]) is bool
        }
        if valid_visibility:
            cleaned["visibility"] = valid_visibility
    size = layout.get("window_size")
    if (
        isinstance(size, (list, tuple))
        and len(size) == 2
        and all(type(part) is int and 0 < part <= _MAX_WINDOW_DIMENSION for part in size)
    ):
        cleaned["window_size"] = list(size)
    return cleaned


class WorkspacePreferencesStore:
    """Persist only this feature's local keys, with injectable test settings.

    ``load_layout`` returns sanitized fields without the storage-only version.
    ``save_layout`` accepts those same fields and adds the current JSON version.
    Unknown surface names raise ``ValueError`` rather than creating new keys.
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings if settings is not None else _default_settings()

    def load_reading(self) -> ReadingPreferences:
        return ReadingPreferences(
            font_scale=_font_scale(self.settings.value(FONT_SCALE_SETTINGS_KEY), allow_settings_string=True),
            density=_density(self.settings.value(DENSITY_SETTINGS_KEY)),
        )

    def save_reading(self, preferences: ReadingPreferences) -> ReadingPreferences:
        if not isinstance(preferences, ReadingPreferences):
            raise TypeError("preferences must be ReadingPreferences")
        self.settings.setValue(FONT_SCALE_SETTINGS_KEY, preferences.font_scale)
        self.settings.setValue(DENSITY_SETTINGS_KEY, preferences.density)
        self.settings.sync()
        return preferences

    def reset_reading(self) -> ReadingPreferences:
        self.settings.remove(FONT_SCALE_SETTINGS_KEY)
        self.settings.remove(DENSITY_SETTINGS_KEY)
        self.settings.sync()
        return DEFAULT_READING_PREFERENCES

    @staticmethod
    def _layout_key(surface: str) -> str:
        if type(surface) is not str or surface not in _SURFACES:
            raise ValueError("surface must be 'workbench' or 'modeler'")
        return f"{LAYOUT_SETTINGS_PREFIX}/{surface}"

    def load_layout(self, surface: str) -> dict:
        raw = self.settings.value(self._layout_key(surface))
        if type(raw) is not str or len(raw) > _MAX_LAYOUT_LENGTH:
            return {}
        try:
            layout = json.loads(raw)
        except (ValueError, TypeError, RecursionError, OverflowError):
            return {}
        if not isinstance(layout, dict):
            return {}
        version = layout.get("version")
        if type(version) is not int or version != LAYOUT_VERSION:
            return {}
        return _clean_layout(layout)

    def save_layout(self, surface: str, layout: dict) -> dict:
        key = self._layout_key(surface)
        cleaned = _clean_layout(layout)
        payload = json.dumps({"version": LAYOUT_VERSION, **cleaned}, separators=(",", ":"), allow_nan=False)
        self.settings.setValue(key, payload)
        self.settings.sync()
        return cleaned

    def reset_layout(self, surface: str) -> None:
        self.settings.remove(self._layout_key(surface))
        self.settings.sync()
