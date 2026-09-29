"""One semantic graphite appearance shared by every Qt workspace."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from ifem.ui.workspace_preferences import ReadingPreferences


DEFAULT_THEME_ID = "graphite"
THEME_SETTINGS_KEY = "appearance/theme"
_THEME_PROPERTY = "ifemThemeId"
_THEME_STYLESHEET_PROPERTY = "ifemStylesheetThemeId"


@dataclass(frozen=True)
class ThemeSpec:
    identifier: str
    name: str
    description: str
    colors: dict[str, str]

    def color(self, role: str) -> str:
        try:
            return self.colors[role]
        except KeyError as exc:
            raise KeyError(f"主题 {self.identifier} 缺少颜色令牌：{role}") from exc


THEMES = (
    ThemeSpec(
        identifier=DEFAULT_THEME_ID,
        name="石墨",
        description="暖白底色、石墨层次与低饱和蓝灰，统一所有工作区",
        colors={
            "background": "#F2F3F1",
            "surface": "#FDFDFC",
            "surface_raised": "#FFFFFF",
            "surface_muted": "#ECEFEB",
            "surface_subtle": "#F6F7F4",
            "primary": "#48616F",
            "primary_hover": "#3C535F",
            "primary_pressed": "#31454F",
            "primary_soft": "#E8EDEF",
            "primary_tint": "#DCE5E8",
            "on_primary": "#FDFDFC",
            "text": "#292E31",
            "text_strong": "#23282B",
            "text_secondary": "#515B60",
            "text_muted": "#60696E",
            "border": "#DBDEDC",
            "border_strong": "#BFC7C6",
            "divider": "#E7EAE5",
            "focus": "#587583",
            "sensor": "#B96D50",
            "sensor_hover": "#A95D43",
            "sensor_dark": "#86452F",
            "sensor_soft": "#F5E8E2",
            "success": "#416651",
            "success_soft": "#E9EFE9",
            "warning": "#795F38",
            "warning_soft": "#F3EDDF",
            "danger": "#974D44",
            "danger_soft": "#F6E9E6",
            "beam": "#707E84",
            "beam_fill": "#E7ECEC",
            "node": "#98A4A5",
            "canvas": "#FDFDFC",
            "grid": "#E6EAE8",
            "viewport_start": "#353D40",
            "viewport_end": "#252A2D",
            "viewport_text": "#F0F2EF",
        },
    ),
)
THEMES_BY_ID = {theme.identifier: theme for theme in THEMES}


def resolve_theme(theme_id: str | None) -> ThemeSpec:
    """Normalize current, historical and unknown identifiers to one appearance.

    Old project/application callers may still pass porcelain_blue, mist_sage or
    warm_stone. Compatibility must not recreate a hidden theme selection.
    """
    return THEMES[0]


def _default_settings() -> QSettings:
    return QSettings("iFEM", "iFEM Reconstruction")


def load_theme_id(settings: QSettings | None = None) -> str:
    settings = settings or _default_settings()
    return resolve_theme(settings.value(THEME_SETTINGS_KEY, DEFAULT_THEME_ID)).identifier


def save_theme_id(theme_id: str, settings: QSettings | None = None) -> str:
    identifier = resolve_theme(theme_id).identifier
    settings = settings or _default_settings()
    settings.setValue(THEME_SETTINGS_KEY, identifier)
    settings.sync()
    return identifier


def current_theme_id(app: QApplication | None = None) -> str:
    app = app or QApplication.instance()
    if app is not None:
        value = app.property(_THEME_PROPERTY)
        if value:
            return resolve_theme(str(value)).identifier
    return load_theme_id()


def theme_color(theme_id: str | None, role: str) -> str:
    return resolve_theme(theme_id).color(role)


def application_stylesheet(theme_id: str | None) -> str:
    """Return the semantic color layer shared by all Qt windows."""

    c = resolve_theme(theme_id).colors
    return f"""
QWidget {{
    color: {c['text']};
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 13px;
}}
QMainWindow, QWidget#appRoot, QDialog#modelerDialog,
QDialog#startCenter,
QDialog#projectLibraryDialog, QDialog#projectNameDialog, QDialog#readingPreferencesDialog {{
    background: {c['background']};
}}
QFrame#topBar, QFrame#startShell, QFrame#startActions, QFrame#modelerToolBar,
QFrame#modelerGenerator, QFrame#modelerInspector,
QFrame#analysisSummary, QFrame#displaySettingsPanel,
QFrame#commandCluster, QFrame#projectLocationBar {{
    background: {c['surface']};
    border-color: {c['border']};
}}
QFrame#startShell {{ border: 1px solid {c['border']}; }}
QFrame#startActions {{
    background: {c['surface_subtle']};
    border: 1px solid {c['border']};
}}
QLabel#brandMark, QLabel#startBrandMark {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary_pressed']};
}}
QLabel#appTitle, QLabel#startBrandTitle, QLabel#startHeadline,
QLabel#modelerTitle, QLabel#sectionTitle, QLabel#emptyTitle,
QLabel#projectDialogTitle,
QLabel#projectEmptyState {{ color: {c['text_strong']}; }}
QLabel#appSubtitle, QLabel#startBrandSubtitle, QLabel#startDescription,
QLabel#startActionHint, QLabel#sectionHint, QLabel#hintLabel,
QLabel#modelerSummary, QLabel#projectDialogHint,
QLabel#projectLibraryMeta, QLabel#projectLibraryFeedback,
QLabel#projectNameStatus {{ color: {c['text_muted']}; }}
QLabel#startEyebrow {{ color: {c['sensor_dark']}; }}
QLabel#startBadge, QLabel#recordBadge, QLabel#statusMeta {{
    color: {c['text_secondary']};
    background: {c['surface_muted']};
    border-color: {c['border']};
}}
QLabel#fieldLabel, QLabel#toolbarLabel, QLabel#metricName,
QLabel#plotContext, QLabel#viewportStatus, QLabel#viewportHint,
QLabel#startFooter, QLabel#startFileHint {{ color: {c['text_secondary']}; }}
QLabel#metricValue, QLabel#algorithmName, QLabel#inspectorTitle {{
    color: {c['text_strong']};
}}
QLabel#algorithmMeta {{ color: {c['text_muted']}; }}
QFrame#sectionAccent, QFrame#startDivider, QFrame#toolbarDivider {{
    background: {c['primary']};
    color: {c['primary']};
}}
QFrame#startActionAccent {{ background: {c['primary']}; }}
QFrame#startDivider {{ background: {c['divider']}; color: {c['divider']}; }}
QFrame#toolbarDivider {{ background: {c['divider']}; color: {c['divider']}; }}
QGroupBox {{
    color: {c['text']};
    background: {c['surface']};
    border-color: {c['border']};
}}
QGroupBox::title {{
    color: {c['text']};
    background: {c['surface']};
}}
QGroupBox#formSection {{ border-top-color: {c['divider']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QPlainTextEdit, QTextEdit {{
    color: {c['text']};
    background: {c['surface']};
    border-color: {c['border_strong']};
    selection-color: {c['on_primary']};
    selection-background-color: {c['primary']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {c['border_strong']};
    background: {c['surface_subtle']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {c['focus']};
    background: {c['surface']};
}}
QLineEdit::placeholder {{ color: {c['text_muted']}; }}
QLineEdit#projectLibraryPath {{
    color: {c['text_secondary']};
    background: transparent;
    border-color: transparent;
}}
QLineEdit#projectNameEdit[validationState="error"] {{ border-color: {c['danger']}; }}
QLabel#projectNameStatus[validationState="error"] {{ color: {c['danger']}; }}
QComboBox QAbstractItemView {{
    color: {c['text']};
    background: {c['surface']};
    border-color: {c['border_strong']};
    selection-color: {c['text_strong']};
    selection-background-color: {c['primary_soft']};
}}
QPushButton {{
    color: {c['text_secondary']};
    background: {c['surface']};
    border-color: {c['border_strong']};
}}
QPushButton:hover {{
    color: {c['text_strong']};
    background: {c['primary_soft']};
    border-color: {c['focus']};
}}
QPushButton:pressed {{ background: {c['primary_tint']}; }}
QPushButton:focus {{ border-color: {c['focus']}; }}
QPushButton:disabled {{
    color: {c['text_muted']};
    background: {c['surface_muted']};
    border-color: {c['divider']};
}}
QPushButton#primaryButton, QPushButton#smallPrimaryButton,
QPushButton#workspacePrimary, QPushButton#startPrimary {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary_pressed']};
}}
QPushButton#primaryButton:hover, QPushButton#smallPrimaryButton:hover,
QPushButton#workspacePrimary:hover, QPushButton#startPrimary:hover {{
    color: {c['on_primary']};
    background: {c['primary_hover']};
    border-color: {c['primary_pressed']};
}}
QPushButton#primaryButton:disabled, QPushButton#smallPrimaryButton:disabled,
QPushButton#workspacePrimary:disabled, QPushButton#startPrimary:disabled {{
    color: {c['text_muted']};
    background: {c['surface_muted']};
    border-color: {c['divider']};
}}
QPushButton#topBarButton {{
    color: {c['text_secondary']};
    background: transparent;
    border-color: transparent;
}}
QPushButton#topBarButton:hover {{
    color: {c['text_strong']};
    background: {c['surface']};
    border-color: {c['border']};
}}
QPushButton#modelerButton {{
    color: {c['primary']};
    background: {c['surface']};
    border-color: {c['focus']};
}}
QPushButton#modelerButton:hover {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary']};
}}
QPushButton#dangerButton, QPushButton#modelerDangerButton {{
    color: {c['danger']};
    background: {c['surface']};
    border-color: {c['danger_soft']};
}}
QPushButton#dangerButton:hover, QPushButton#modelerDangerButton:hover,
QPushButton#dangerGhostButton:hover {{
    color: {c['danger']};
    background: {c['danger_soft']};
    border-color: {c['danger']};
}}
QPushButton#startQuiet {{ color: {c['text_secondary']}; background: transparent; }}
QPushButton#startQuiet:hover {{ color: {c['primary']}; background: transparent; }}
QPushButton#viewModeButton, QPushButton#modelerModeButton {{
    color: {c['text_secondary']};
    background: transparent;
    border-color: transparent;
}}
QPushButton#viewModeButton:hover, QPushButton#modelerModeButton:hover {{
    color: {c['primary']};
    background: {c['primary_soft']};
}}
QPushButton#viewModeButton:checked, QPushButton#modelerModeButton:checked {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary']};
}}
QPushButton#pathKindStart, QPushButton#pathKindEnd {{
    color: {c['text_secondary']};
    background: {c['surface']};
    border-color: {c['border_strong']};
}}
QPushButton#pathKindStart:hover, QPushButton#pathKindEnd:hover {{
    color: {c['primary']};
    background: {c['primary_soft']};
    border-color: {c['focus']};
}}
QPushButton#pathKindStart:checked, QPushButton#pathKindEnd:checked {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary']};
}}
QPushButton#pathKindStart:focus, QPushButton#pathKindEnd:focus {{
    border-color: {c['focus']};
}}
QPushButton#displayModeButton:checked {{
    color: {c['primary']};
    background: {c['primary_soft']};
    border-color: {c['focus']};
}}
QPushButton#modelerToolButton, QPushButton#modelerFileButton,
QPushButton#modelerPathButton, QPushButton#viewportButton {{
    color: {c['text_secondary']};
    background: {c['surface']};
    border-color: {c['border_strong']};
}}
QPushButton#modelerToolButton:hover, QPushButton#modelerFileButton:hover,
QPushButton#modelerPathButton:hover, QPushButton#viewportButton:hover {{
    color: {c['primary']};
    background: {c['primary_soft']};
    border-color: {c['focus']};
}}
QPushButton#modelerPathButton[primaryAction="true"] {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary_pressed']};
}}
QPushButton#modelerPathButton[primaryAction="true"]:hover {{
    color: {c['on_primary']};
    background: {c['primary_hover']};
    border-color: {c['primary_pressed']};
}}
QPushButton#modelerPathButton[primaryAction="true"]:pressed {{
    color: {c['on_primary']};
    background: {c['primary_pressed']};
    border-color: {c['primary_pressed']};
}}
QPushButton#modelerPathButton[primaryAction="true"]:focus {{
    border-color: {c['focus']};
}}
QFrame#viewToolbar, QFrame#viewportToolbar {{
    background: {c['surface_muted']};
    border-color: {c['border']};
}}
QFrame#analysisMethodCard, QFrame#metricCardPrimary {{
    background: {c['primary_soft']};
    border-color: {c['border']};
}}
QFrame#analysisMethodCard {{ border-left-color: {c['primary']}; }}
QFrame#analysisMethodCard:focus {{
    border-color: {c['focus']};
    border-left-color: {c['focus']};
}}
QFrame#metricCard, QFrame#metricCardPrimary {{ border-right-color: {c['divider']}; }}
QFrame#plotMetaBar, QFrame#modelerHeader, QFrame#modelerViewBar {{
    border-bottom-color: {c['divider']};
}}
QFrame#viewportFallback {{
    background: {c['viewport_end']};
    border-color: {c['viewport_start']};
}}
QFrame#viewportFallback QLabel#emptyTitle {{ color: {c['viewport_text']}; }}
QTabWidget::pane, QTabWidget#editorTabs::pane,
QTabWidget#inspectorTabs::pane, QTabWidget#sensorConfigTabs::pane {{
    background: {c['surface']};
    border-color: {c['border']};
}}
QTabBar::tab {{
    color: {c['text_secondary']};
    background: {c['surface_muted']};
    border-color: {c['border']};
}}
QTabBar::tab:hover:!selected {{
    color: {c['primary']};
    background: {c['primary_soft']};
}}
QTabBar::tab:selected {{
    color: {c['primary']};
    background: {c['surface']};
    border: none;
    border-bottom: 3px solid {c['primary']};
}}
QTabWidget#editorTabs QTabBar::tab,
QTabWidget#inspectorTabs QTabBar::tab,
QTabWidget#sensorConfigTabs QTabBar::tab {{ background: transparent; }}
QTabWidget#editorTabs QTabBar::tab:selected,
QTabWidget#inspectorTabs QTabBar::tab:selected,
QTabWidget#sensorConfigTabs QTabBar::tab:selected {{
    color: {c['primary']};
    background: {c['surface_subtle']};
    border: none;
    border-bottom: 2px solid {c['primary']};
}}
QWidget#editorForm, QWidget#inspectorSubpage {{ background: {c['surface_subtle']}; }}
QWidget#inspectorPage, QScrollArea#inspectorScroll,
QScrollArea#inspectorScroll > QWidget > QWidget {{ background: {c['surface']}; }}
QTableWidget {{
    color: {c['text']};
    background: {c['surface']};
    alternate-background-color: {c['surface_subtle']};
    border-color: {c['border']};
    gridline-color: {c['divider']};
    selection-color: {c['text_strong']};
    selection-background-color: {c['primary_soft']};
}}
QTableWidget::item {{ border-bottom-color: {c['divider']}; }}
QTreeWidget#projectLibraryList {{
    color: {c['text']};
    background: {c['surface']};
    alternate-background-color: {c['surface_subtle']};
    border-color: {c['border']};
    selection-color: {c['text_strong']};
    selection-background-color: {c['primary_soft']};
}}
QHeaderView::section {{
    color: {c['text_secondary']};
    background: {c['surface_muted']};
    border-right-color: {c['divider']};
    border-bottom-color: {c['border']};
}}
QSplitter::handle {{ background: {c['divider']}; }}
QScrollBar::handle {{ background: {c['border_strong']}; }}
QScrollBar::handle:hover {{ background: {c['focus']}; }}
QMenu {{
    color: {c['text']};
    background: {c['surface']};
    border-color: {c['border_strong']};
}}
QMenu::item:selected {{ color: {c['primary']}; background: {c['primary_soft']}; }}
QToolTip {{
    color: {c['viewport_text']};
    background: {c['viewport_end']};
    border-color: {c['viewport_start']};
}}
QStatusBar {{ color: {c['text_muted']}; background: {c['background']}; }}
QLabel#statusBadge[state="idle"], QPushButton#inputBadge[state="pending"],
QLabel#algorithmState[state="pending"], QLabel#modelerStatus[state="waiting"] {{
    color: {c['warning']};
    background: {c['warning_soft']};
    border-color: {c['border']};
}}
QLabel#statusBadge[state="running"], QLabel#statusBadge[state="success"],
QPushButton#inputBadge[state="ready"], QLabel#algorithmState[state="ready"],
QLabel#modelerStatus[state="ready"] {{
    color: {c['success']};
    background: {c['success_soft']};
    border-color: {c['border']};
}}
QLabel#statusBadge[state="error"], QLabel#recordBadge[state="error"],
QPushButton#inputBadge[state="error"], QLabel#algorithmState[state="blocked"] {{
    color: {c['danger']};
    background: {c['danger_soft']};
    border-color: {c['border']};
}}
QPushButton#inputBadge:hover, QPushButton#inputBadge:focus {{
    border-color: {c['focus']};
}}
QPushButton#inputBadge:pressed {{
    color: {c['text_strong']};
    background: {c['primary_tint']};
    border-color: {c['primary']};
}}
QLabel#resultFreshness[state="stale"] {{
    color: {c['warning']};
    background: {c['warning_soft']};
    border: 1px solid {c['border']};
}}
QFrame#analysisEmptyState {{
    background: {c['surface']};
    border-color: {c['border']};
}}
QLabel#analysisEmptyEyebrow {{ color: {c['primary']}; }}
QLabel#analysisEmptyTitle {{ color: {c['text_strong']}; }}
QLabel#analysisEmptyDescription {{ color: {c['text_secondary']}; }}
QLabel#analysisEmptyIssue {{ color: {c['text_muted']}; }}
QFrame#analysisWorkflow {{ background: {c['surface_muted']}; }}
QFrame#analysisStep[state="active"] {{
    background: {c['surface']};
    border-color: {c['focus']};
}}
QFrame#analysisStep[state="done"] {{ background: {c['success_soft']}; }}
QLabel#analysisStepMarker {{
    color: {c['text_secondary']};
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
}}
QLabel#analysisStepMarker[state="active"] {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary']};
}}
QLabel#analysisStepMarker[state="done"] {{
    color: {c['success']};
    background: {c['success_soft']};
    border-color: {c['success']};
}}
QLabel#analysisStepLabel {{ color: {c['text_secondary']}; }}
QPushButton#emptyStateAction {{
    color: {c['on_primary']};
    background: {c['primary']};
    border-color: {c['primary_pressed']};
}}
QPushButton#emptyStateAction:hover {{
    color: {c['on_primary']};
    background: {c['primary_hover']};
    border-color: {c['primary_pressed']};
}}
QPushButton#emptyStateAction:focus {{ border-color: {c['focus']}; }}
QPushButton#emptyStateAction:pressed {{
    color: {c['on_primary']};
    background: {c['primary_pressed']};
    border-color: {c['primary_pressed']};
}}
""" + _studio_stylesheet(c)


def _studio_stylesheet(c):
    """Shared desktop geometry and workspace components, after legacy rules."""
    assets = Path(__file__).resolve().parent / "assets"
    down = (assets / "chevron_down.svg").as_posix()
    up = (assets / "chevron_up.svg").as_posix()
    return f"""
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    border: 1px solid {c['border_strong']}; border-radius: 6px;
    padding: 5px 8px; min-height: 22px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['focus']}; background: {c['surface']};
}}
QLineEdit[validationState="error"], QComboBox[validationState="error"],
QSpinBox[validationState="error"], QDoubleSpinBox[validationState="error"] {{
    border-color: {c['danger']}; background: {c['danger_soft']};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {c['text_muted']}; background: {c['surface_muted']}; border-color: {c['divider']};
}}
QComboBox {{ padding-right: 22px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
    width: 22px; border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border;
    subcontrol-position: top right; width: 19px; height: 17px; border: none; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
    subcontrol-position: bottom right; width: 19px; height: 17px; border: none; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 11px; height: 11px; }}
QPushButton {{ border: 1px solid {c['border']}; border-radius: 6px;
    padding: 6px 10px; min-height: 18px; font-weight: 500; }}
QPushButton:focus {{ border-color: {c['focus']}; }}
QPushButton#primaryButton, QPushButton#workspacePrimary {{
    border-radius: 7px; padding: 7px 16px; font-weight: 700;
}}
QPushButton#primaryButton:pressed, QPushButton#workspacePrimary:pressed,
QPushButton#smallPrimaryButton:pressed {{ background: {c['primary_pressed']}; }}
QFrame#topBar {{ border: 1px solid {c['border']}; border-radius: 10px; }}
QLabel#appTitle {{ font-size: 19px; font-weight: 800; }}
QLabel#appSubtitle {{ font-size: 11px; font-weight: 500; }}
QLabel#brandMark {{ border-radius: 10px; font-size: 18px; }}
QFrame#commandCluster {{ background: transparent; border: none; }}
QPushButton#topBarButton {{ padding: 5px 7px; min-width: 34px; }}
QPushButton#commandLauncher {{ background: {c['surface_subtle']};
    border: 1px solid {c['border']}; color: {c['text_muted']};
    padding: 7px 12px; min-width: 144px; border-radius: 7px; font-size: 12px; }}
QPushButton#commandLauncher:hover, QPushButton#commandLauncher:focus {{
    color: {c['primary']}; border-color: {c['focus']}; }}
QFrame#workspaceRail {{ background: {c['viewport_end']}; border: none; border-radius: 10px; }}
QLabel#railCaption {{ color: {c['viewport_text']}; font-size: 10px; background: transparent; }}
QToolButton#railButton {{ color: {c['viewport_text']}; background: transparent;
    border: 1px solid transparent; border-radius: 8px; padding: 2px; font-size: 11px; }}
QToolButton#railButton:hover {{ background: {c['viewport_start']}; }}
QToolButton#railButton:checked {{ background: {c['primary']}; color: {c['on_primary']}; }}
QToolButton#railButton:focus {{ border-color: {c['viewport_text']}; }}
QToolButton#railButton:pressed {{ background: {c['primary_hover']}; }}
QToolButton#railButton[hasIssue="true"] {{ border-bottom: 2px solid {c['sensor']}; }}
QToolButton#tableEditToolButton {{ color: {c['text_secondary']}; background: {c['surface_subtle']};
    border: 1px solid {c['border']}; border-radius: 5px; padding: 4px 6px;
    min-height: 18px; font-size: 12px; font-weight: 500; }}
QToolButton#tableEditToolButton:hover, QToolButton#tableEditToolButton:focus {{
    color: {c['primary']}; background: {c['primary_soft']}; border-color: {c['focus']}; }}
QToolButton#tableEditToolButton:pressed {{ background: {c['primary_tint']}; }}
QToolButton#tableEditToolButton:disabled {{ color: {c['text_muted']};
    background: {c['surface']}; border-color: {c['divider']}; }}
QToolButton#tableEditToolButton::menu-indicator {{ image: url("{down}");
    subcontrol-origin: padding; subcontrol-position: bottom right; width: 9px; height: 9px; }}
QLabel#tableEditStatus {{ color: {c['text_muted']}; font-size: 11px; background: transparent;
    padding: 3px 5px; border-left: 2px solid transparent; }}
QLabel#tableEditStatus[validationState="error"] {{ color: {c['danger']};
    background: {c['danger_soft']}; border-left-color: {c['danger']}; }}
QFrame#inputInspector {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QLabel#sectionTitle {{ font-size: 17px; font-weight: 700; }}
QLabel#sectionHint {{ font-size: 11px; color: {c['text_muted']}; }}
QTabWidget#inputPages::pane {{ border: none; background: {c['surface']}; }}
QGroupBox#formSection {{ border: none; border-top: 1px solid {c['divider']};
    border-radius: 0; margin-top: 16px; padding-top: 14px; }}
QGroupBox#formSection::title {{ subcontrol-origin: margin; left: 0; top: 0;
    padding: 0 8px 0 0; font-size: 12px; font-weight: 700; }}
QGroupBox#workspaceGroup {{ border: 1px solid {c['border']}; border-radius: 9px;
    margin-top: 0; padding-top: 0; }}
QGroupBox#workspaceGroup::title {{ padding: 0 6px; font-size: 11px; color: {c['text_muted']}; }}
QFrame#analysisSummary {{ border: 1px solid {c['border']}; border-radius: 9px; }}
QFrame#metricCardPrimary {{ background: transparent; border-radius: 0;
    border: none; border-right: 1px solid {c['divider']}; }}
QLabel#metricName {{ font-size: 10px; font-weight: 500; }}
QLabel#metricValue {{ font-size: 13px; font-weight: 700; min-height: 22px; }}
QFrame#viewToolbar {{ background: {c['surface_subtle']}; border: none; border-radius: 7px; }}
QPushButton#viewModeButton, QPushButton#displayModeButton {{ padding: 5px 9px; min-width: 20px; }}
QFrame#plotCanvas {{ border: none; background: {c['canvas']}; }}
QFrame#analysisEmptyState {{ border: none; background: {c['surface']}; }}
QLabel#analysisEmptyTitle {{ font-size: 23px; font-weight: 700; }}
QLabel#analysisEmptyDescription {{ font-size: 13px; }}
QLabel#analysisEmptyEyebrow {{ font-size: 11px; letter-spacing: 2px; }}
QFrame#analysisMethodCard {{ border: 1px solid {c['border']};
    border-left: 3px solid {c['primary']}; border-radius: 8px; }}
QLabel#algorithmName {{ font-size: 15px; font-weight: 700; }}
QLabel#algorithmMeta {{ font-size: 10px; }}
QPushButton#panelToggle {{ border: 1px solid transparent; border-radius: 6px;
    background: transparent; color: {c['text_secondary']}; font-size: 11px; padding: 5px 7px; }}
QPushButton#panelToggle:hover, QPushButton#panelToggle:focus {{
    background: {c['primary_soft']}; border-color: {c['focus']}; }}
QPushButton#panelToggle:checked {{ color: {c['primary']}; background: {c['primary_soft']}; }}
QPushButton#panelToggle:pressed {{ background: {c['primary_tint']}; }}
QTabBar::tab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 8px 11px; min-height: 18px; font-size: 12px; }}
QTabBar::tab:selected {{ background: {c['surface']}; border-bottom: 2px solid {c['primary']}; }}
QTabBar::tab:focus {{ background: {c['primary_soft']}; }}
QTabWidget#resultTabs::pane {{ border: none; }}
QTabWidget#inspectorTabs QTabBar::tab {{ min-width: 0; padding: 8px 8px; font-size: 12px; }}
QTabWidget#sensorConfigTabs QTabBar::tab {{ min-width: 0; padding: 7px 9px; }}
QHeaderView::section {{ border: none; border-bottom: 1px solid {c['border']};
    padding: 7px 8px; font-size: 11px; font-weight: 600; }}
QTableWidget {{ border: 1px solid {c['divider']}; border-radius: 6px; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {c['primary_tint']}; }}
QScrollBar:vertical {{ width: 8px; margin: 0; background: transparent; }}
QScrollBar::handle:vertical {{ min-height: 26px; border-radius: 4px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QDialog#commandPalette {{ background: {c['surface']}; }}
QLineEdit#commandSearch {{ font-size: 16px; padding: 12px; border: 1px solid {c['focus']}; }}
QListWidget#commandResults {{ border: none; outline: none; background: {c['surface']}; }}
QListWidget#commandResults::item {{ padding: 4px 12px; border-radius: 7px;
    border: 1px solid transparent; color: {c['text_secondary']}; }}
QListWidget#commandResults::item:selected {{ color: {c['primary']};
    background: {c['primary_soft']}; border-color: {c['border_strong']}; }}
QListWidget#commandResults::item:disabled {{ color: {c['text_muted']}; background: {c['surface_subtle']}; }}
QFrame#modelerHeader {{ background: {c['viewport_end']}; border: none; border-radius: 9px; }}
QLabel#modelerTitle {{ color: {c['viewport_text']}; font-size: 20px; font-weight: 700; }}
QLabel#modelerSummary {{ color: {c['viewport_text']}; font-size: 11px; }}
QFrame#modelerHeader QPushButton {{ background: {c['viewport_start']};
    color: {c['viewport_text']}; border-color: {c['viewport_start']}; }}
QFrame#modelerHeader QPushButton:hover, QFrame#modelerHeader QPushButton:focus {{
    border-color: {c['viewport_text']}; }}
QFrame#modelerToolBar {{ border: none; border-bottom: 1px solid {c['border']};
    background: transparent; border-radius: 0; }}
QFrame#modelerInspector {{ border: 1px solid {c['border']}; border-radius: 9px; }}
QFrame#modelerGenerator {{ border: 1px solid {c['border']}; border-radius: 9px; }}
QLabel#inspectorTitle {{ font-size: 15px; font-weight: 700; }}
QTreeWidget#modelOutline {{ border: none; background: {c['surface']}; outline: none; }}
QTreeWidget#modelOutline::item {{ padding: 7px 5px; border: 1px solid transparent; }}
QTreeWidget#modelOutline::item:selected {{ color: {c['primary']}; background: {c['primary_soft']};
    border-color: {c['border']}; border-radius: 5px; }}
QTreeWidget#modelOutline::item:hover {{ background: {c['surface_muted']}; }}
"""


_FONT_SIZE_RE = re.compile(
    r"(?P<comment>/\*.*?\*/)"
    r"|(?P<prefix>(?<![\w-])font-size\s*:\s*)"
    r"(?P<size>\d+(?:\.\d+)?)(?P<unit>px|pt)\b",
    re.IGNORECASE | re.DOTALL,
)
_QSS_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
_QSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SELECTOR_QUALIFIER = r'(?:#[\w-]+|\[[^\]]+\]|:(?!:)[!\w-]+)*'
_DENSITY_TARGET_RE = re.compile(
    r"(?:^|[\s>+~])(?:"
    r"(?:QLineEdit|QComboBox|QSpinBox|QDoubleSpinBox|QPlainTextEdit|QTextEdit|"
    r"QPushButton|QToolButton)" + _SELECTOR_QUALIFIER
    + r"|QHeaderView" + _SELECTOR_QUALIFIER + r"::section" + _SELECTOR_QUALIFIER
    + r"|QTabBar" + _SELECTOR_QUALIFIER + r"::tab" + _SELECTOR_QUALIFIER
    + r")\s*$"
)
_PADDING_RE = re.compile(
    r"(?P<comment>/\*.*?\*/)"
    r"|(?P<prefix>(?<![\w-])padding(?P<side>-(?:top|bottom))?\s*:\s*)"
    r"(?P<values>[^;{}]+)",
    re.IGNORECASE | re.DOTALL,
)
_PIXEL_PADDING_RE = re.compile(r"(?:\d+(?:\.\d+)?px|0)", re.IGNORECASE)
_COMFORTABLE_PADDING_FALLBACK = """
/* Reading density: only vertical control spacing; original widths stay intact. */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit,
QPushButton, QToolButton, QHeaderView::section, QTabBar::tab {
    padding-top: 2px; padding-bottom: 2px;
}
"""


def _qss_number(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _comfortable_padding(match: re.Match[str]) -> str:
    if match.group("comment") is not None:
        return match.group(0)
    values = match.group("values").split()
    if not 1 <= len(values) <= 4 or any(
        _PIXEL_PADDING_RE.fullmatch(value) is None for value in values
    ):
        return match.group(0)

    def increased(value: str) -> str:
        return f"{_qss_number(Decimal(value.lower().removesuffix('px')) + 2)}px"

    if match.group("side"):
        if len(values) != 1:
            return match.group(0)
        values[0] = increased(values[0])
    else:
        # A one-value shorthand applies to both axes. Expand it so the
        # horizontal spacing remains exactly the original value.
        if len(values) == 1:
            values.append(values[0])
        values[0] = increased(values[0])
        if len(values) >= 3:
            values[2] = increased(values[2])
    return match.group("prefix") + " ".join(values)


def _comfortable_rule(match: re.Match[str]) -> str:
    selectors = match.group("selectors")
    body = match.group("body")
    selector_parts = selectors.split(",")
    targets = [bool(_DENSITY_TARGET_RE.search(_QSS_COMMENT_RE.sub("", selector)))
               for selector in selector_parts]
    if not any(targets):
        return match.group(0)
    adjusted_body = _PADDING_RE.sub(_comfortable_padding, body)
    if adjusted_body == body:
        return match.group(0)
    if all(targets):
        return selectors + "{" + adjusted_body + "}"
    # Shared label/button rules must not increase spacing on ordinary labels.
    unchanged = ",".join(selector for selector, target in zip(selector_parts, targets) if not target)
    adjusted = ",".join(selector for selector, target in zip(selector_parts, targets) if target)
    return unchanged + "{" + body + "}\n" + adjusted + "{" + adjusted_body + "}"


def apply_reading_preferences(
    stylesheet: str, preferences: ReadingPreferences | None = None
) -> str:
    """Derive a local reading style from an unmodified source stylesheet.

    Call this with the baseline, never with a widget's already-adjusted QSS.
    No application font, theme, settings, data or plotting state is changed.
    Qt rounds fractional pixel font sizes when resolving the widget's font;
    point sizes retain their precision. Density adds two pixels per vertical
    side and leaves horizontal spacing and geometry constraints unchanged.
    """
    if preferences is None:
        return stylesheet
    font_scale = preferences.font_scale
    if font_scale not in (100, 110, 120):
        font_scale = 100
    if font_scale != 100:
        def scaled_font(match: re.Match[str]) -> str:
            if match.group("comment") is not None:
                return match.group(0)
            size = Decimal(match.group("size")) * Decimal(font_scale) / 100
            return match.group("prefix") + _qss_number(size) + match.group("unit")

        stylesheet = _FONT_SIZE_RE.sub(scaled_font, stylesheet)
    if preferences.density == "comfortable":
        stylesheet = _COMFORTABLE_PADDING_FALLBACK + _QSS_RULE_RE.sub(
            _comfortable_rule, stylesheet
        )
    return stylesheet


def compose_stylesheet(
    base_stylesheet: str,
    theme_id: str | None,
    *,
    preferences: ReadingPreferences | None = None,
) -> str:
    stylesheet = f"{base_stylesheet}\n{application_stylesheet(theme_id)}"
    return apply_reading_preferences(stylesheet, preferences)


def apply_application_theme(
    theme_id: str | None,
    *,
    app: QApplication | None = None,
    persist: bool = False,
    update_stylesheet: bool = True,
) -> str:
    theme = resolve_theme(theme_id)
    app = app or QApplication.instance()
    if app is not None:
        app.setProperty(_THEME_PROPERTY, theme.identifier)
        stylesheet_theme_id = app.property(_THEME_STYLESHEET_PROPERTY)
        if update_stylesheet and (
            str(stylesheet_theme_id or "") != theme.identifier
            or not app.styleSheet()
        ):
            app.setStyleSheet(application_stylesheet(theme.identifier))
            app.setProperty(_THEME_STYLESHEET_PROPERTY, theme.identifier)
    if persist:
        save_theme_id(theme.identifier)
    return theme.identifier


__all__ = [
    "DEFAULT_THEME_ID",
    "THEMES",
    "THEMES_BY_ID",
    "ThemeSpec",
    "application_stylesheet",
    "apply_application_theme",
    "apply_reading_preferences",
    "compose_stylesheet",
    "current_theme_id",
    "load_theme_id",
    "resolve_theme",
    "save_theme_id",
    "theme_color",
]
