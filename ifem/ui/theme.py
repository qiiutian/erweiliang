"""Shared appearance themes for the Qt desktop interface."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, QSettings, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


DEFAULT_THEME_ID = "porcelain_blue"
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
        name="云瓷蓝",
        description="明亮、克制，突出模型和结果数据",
        colors={
            "background": "#F3F6F8",
            "surface": "#FFFFFF",
            "surface_raised": "#FFFFFF",
            "surface_muted": "#EEF3F6",
            "surface_subtle": "#F8FAFB",
            "primary": "#315D7A",
            "primary_hover": "#274D66",
            "primary_pressed": "#203F54",
            "primary_soft": "#E5EFF5",
            "primary_tint": "#D7E7F0",
            "on_primary": "#FFFFFF",
            "text": "#26343E",
            "text_strong": "#172630",
            "text_secondary": "#53636E",
            "text_muted": "#667680",
            "border": "#D8E1E6",
            "border_strong": "#BBC9D1",
            "divider": "#E5EBEE",
            "focus": "#4F82A3",
            "sensor": "#D76547",
            "sensor_hover": "#BE5338",
            "sensor_dark": "#9C402F",
            "sensor_soft": "#F8E5DE",
            "success": "#39705A",
            "success_soft": "#E2F0E9",
            "warning": "#8A642D",
            "warning_soft": "#F6ECD8",
            "danger": "#A34D46",
            "danger_soft": "#F8E6E3",
            "beam": "#637985",
            "beam_fill": "#E6EDF1",
            "node": "#96A5AE",
            "canvas": "#FFFFFF",
            "grid": "#E7ECEF",
            "viewport_start": "#2B3943",
            "viewport_end": "#151E24",
            "viewport_text": "#EDF3F6",
        },
    ),
    ThemeSpec(
        identifier="mist_sage",
        name="月白青",
        description="柔和自然，适合长时间建模与录入",
        colors={
            "background": "#F3F6F4",
            "surface": "#FFFFFF",
            "surface_raised": "#FFFFFF",
            "surface_muted": "#EEF3EF",
            "surface_subtle": "#F8FAF8",
            "primary": "#426A55",
            "primary_hover": "#355845",
            "primary_pressed": "#2D4B3B",
            "primary_soft": "#E5EEE8",
            "primary_tint": "#D8E7DD",
            "on_primary": "#FFFFFF",
            "text": "#29362F",
            "text_strong": "#1B2921",
            "text_secondary": "#58665E",
            "text_muted": "#68756E",
            "border": "#D9E2DC",
            "border_strong": "#BCCBC1",
            "divider": "#E5EBE7",
            "focus": "#62866F",
            "sensor": "#D06A4E",
            "sensor_hover": "#B9563E",
            "sensor_dark": "#984333",
            "sensor_soft": "#F7E5DF",
            "success": "#39705A",
            "success_soft": "#E2F0E8",
            "warning": "#85632E",
            "warning_soft": "#F5ECD9",
            "danger": "#9D4D44",
            "danger_soft": "#F7E6E2",
            "beam": "#687A70",
            "beam_fill": "#E7EEE9",
            "node": "#99A59E",
            "canvas": "#FFFFFF",
            "grid": "#E8EDE9",
            "viewport_start": "#35443B",
            "viewport_end": "#18201B",
            "viewport_text": "#EEF4F0",
        },
    ),
    ThemeSpec(
        identifier="warm_stone",
        name="暖砂岩",
        description="温和的中性色，弱化工具感与视觉疲劳",
        colors={
            "background": "#F6F4F0",
            "surface": "#FFFFFF",
            "surface_raised": "#FFFFFF",
            "surface_muted": "#F1EEE8",
            "surface_subtle": "#FBFAF7",
            "primary": "#6B5C4E",
            "primary_hover": "#584B40",
            "primary_pressed": "#493E35",
            "primary_soft": "#EEE9E3",
            "primary_tint": "#E5DCD2",
            "on_primary": "#FFFFFF",
            "text": "#39342F",
            "text_strong": "#27231F",
            "text_secondary": "#675F57",
            "text_muted": "#756D65",
            "border": "#E3DDD5",
            "border_strong": "#CEC3B8",
            "divider": "#ECE7E1",
            "focus": "#8A7765",
            "sensor": "#C95F45",
            "sensor_hover": "#AF4D36",
            "sensor_dark": "#913D2E",
            "sensor_soft": "#F6E3DC",
            "success": "#4F715D",
            "success_soft": "#E7EFE9",
            "warning": "#8B642B",
            "warning_soft": "#F6ECD7",
            "danger": "#9F4B43",
            "danger_soft": "#F7E5E2",
            "beam": "#756F68",
            "beam_fill": "#ECE8E2",
            "node": "#AAA198",
            "canvas": "#FFFFFF",
            "grid": "#EEEAE5",
            "viewport_start": "#443E38",
            "viewport_end": "#211E1B",
            "viewport_text": "#F3EFEA",
        },
    ),
)
THEMES_BY_ID = {theme.identifier: theme for theme in THEMES}


def resolve_theme(theme_id: str | None) -> ThemeSpec:
    return THEMES_BY_ID.get(str(theme_id or ""), THEMES_BY_ID[DEFAULT_THEME_ID])


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
QDialog#appearanceDialog, QDialog#startCenter,
QDialog#projectLibraryDialog, QDialog#projectNameDialog {{
    background: {c['background']};
}}
QFrame#topBar, QFrame#startShell, QFrame#startActions, QFrame#modelerToolBar,
QFrame#modelerGenerator, QFrame#modelerInspector,
QFrame#analysisSummary, QFrame#displaySettingsPanel,
QFrame#commandCluster, QFrame#themeChoice, QFrame#projectLocationBar {{
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
QLabel#appearanceTitle, QLabel#projectDialogTitle,
QLabel#projectEmptyState {{ color: {c['text_strong']}; }}
QLabel#appSubtitle, QLabel#startBrandSubtitle, QLabel#startDescription,
QLabel#startActionHint, QLabel#sectionHint, QLabel#hintLabel,
QLabel#modelerSummary, QLabel#appearanceHint, QLabel#projectDialogHint,
QLabel#projectLibraryMeta, QLabel#projectLibraryFeedback,
QLabel#projectNameStatus {{ color: {c['text_muted']}; }}
QLabel#startEyebrow {{ color: {c['sensor']}; }}
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
QFrame#themePicker {{
    background: {c['surface_subtle']};
    border: 1px solid {c['border']};
    border-radius: 8px;
}}
QLabel#themePickerLabel {{ color: {c['text_secondary']}; font-size: 11px; font-weight: 600; }}
QToolButton#themeMenuButton {{
    min-height: 30px;
    padding: 1px 24px 1px 9px;
    color: {c['text_strong']};
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    font-weight: 600;
}}
QToolButton#themeMenuButton:hover,
QToolButton#themeMenuButton:focus {{
    color: {c['primary']};
    background: {c['primary_soft']};
    border-color: {c['focus']};
}}
QToolButton#themeMenuButton::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 7px;
}}
QMenu#themeMenu {{
    color: {c['text']};
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 9px;
    padding: 6px;
}}
QMenu#themeMenu::item {{
    min-width: 148px;
    min-height: 30px;
    padding: 4px 24px 4px 30px;
    border-radius: 6px;
}}
QMenu#themeMenu::item:selected {{
    color: {c['text_strong']};
    background: {c['primary_soft']};
}}
QMenu#themeMenu::indicator {{
    width: 14px;
    height: 14px;
    left: 7px;
}}
QFrame#themeChoice {{ border: 1px solid {c['border']}; border-radius: 9px; }}
QFrame#themeChoice:hover {{ background: {c['surface_subtle']}; border-color: {c['border_strong']}; }}
QFrame#themeChoice[selected="true"] {{ background: {c['primary_soft']}; border-color: {c['focus']}; }}
QRadioButton#themeRadio {{ color: {c['text_strong']}; font-size: 14px; font-weight: 700; spacing: 9px; }}
QLabel#themeDescription {{ color: {c['text_muted']}; font-size: 11px; }}
"""


def compose_stylesheet(base_stylesheet: str, theme_id: str | None) -> str:
    return f"{base_stylesheet}\n{application_stylesheet(theme_id)}"


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


class ThemeSwatchStrip(QWidget):
    def __init__(self, theme_id: str | None = None, parent=None):
        super().__init__(parent)
        self._theme_id = resolve_theme(theme_id).identifier
        self.setFixedSize(76, 18)
        self.setAccessibleName("当前界面风格配色预览")

    def set_theme(self, theme_id: str | None):
        self._theme_id = resolve_theme(theme_id).identifier
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        theme = resolve_theme(self._theme_id)
        roles = ("primary", "primary_soft", "sensor", "surface_muted")
        gap = 3.0
        width = (self.width() - gap * (len(roles) - 1)) / len(roles)
        for index, role in enumerate(roles):
            x = index * (width + gap)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.color(role)))
            painter.drawRoundedRect(x, 2.0, width, self.height() - 4.0, 3.0, 3.0)


class ThemePicker(QFrame):
    theme_changed = Signal(str)

    def __init__(
        self,
        theme_id: str | None = None,
        parent=None,
        *,
        compact=False,
        show_swatches=True,
        label_text="风格",
    ):
        super().__init__(parent)
        self.setObjectName("themePicker")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        self.label = QLabel(label_text)
        self.label.setObjectName("themePickerLabel")
        layout.addWidget(self.label)

        self.button = QToolButton()
        self.button.setObjectName("themeMenuButton")
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setIconSize(QSize(22, 16))
        self.button.setMinimumWidth(112 if compact else 160)
        self.menu = QMenu(self.button)
        self.menu.setObjectName("themeMenu")
        self.menu.setMinimumWidth(184)
        self.action_group = QActionGroup(self)
        self.action_group.setExclusive(True)
        self.actions = {}
        for theme in THEMES:
            action = self.menu.addAction(self._theme_icon(theme), theme.name)
            action.setCheckable(True)
            action.setData(theme.identifier)
            action.setToolTip(theme.description)
            action.triggered.connect(
                lambda _checked=False, identifier=theme.identifier: (
                    self._action_triggered(identifier)
                )
            )
            self.action_group.addAction(action)
            self.actions[theme.identifier] = action
        self.button.setMenu(self.menu)
        layout.addWidget(self.button)
        self.swatches = ThemeSwatchStrip(theme_id) if show_swatches else None
        if self.swatches is not None:
            layout.addWidget(self.swatches)
        self.set_theme(theme_id, emit=False)
        self.setToolTip("切换整个软件的界面风格，选择会自动保存")

    @property
    def theme_id(self) -> str:
        return self._theme_id

    @staticmethod
    def _theme_icon(theme: ThemeSpec):
        pixmap = QPixmap(22, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.color("sensor")))
        painter.drawRoundedRect(9, 2, 12, 12, 3, 3)
        painter.setBrush(QColor(theme.color("primary")))
        painter.drawRoundedRect(1, 2, 12, 12, 3, 3)
        painter.end()
        return QIcon(pixmap)

    def set_theme(self, theme_id: str | None, *, emit=False):
        theme = resolve_theme(theme_id)
        identifier = theme.identifier
        self._theme_id = identifier
        self.button.setText(theme.name)
        self.button.setIcon(self._theme_icon(theme))
        self.button.setAccessibleName(f"界面风格：{theme.name}")
        self.button.setToolTip(theme.description)
        for candidate in THEMES:
            action = self.actions[candidate.identifier]
            selected = candidate.identifier == identifier
            action.setText(f"{candidate.name}\t当前" if selected else candidate.name)
            action.setChecked(selected)
        if self.swatches is not None:
            self.swatches.set_theme(identifier)
        if emit:
            self.theme_changed.emit(identifier)

    def _action_triggered(self, theme_id):
        identifier = resolve_theme(theme_id).identifier
        if identifier == self._theme_id:
            return
        self.set_theme(identifier, emit=True)


class _ThemeChoiceRow(QFrame):
    def __init__(self, theme: ThemeSpec, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("themeChoice")
        self.setProperty("selected", False)
        self.setMinimumHeight(72)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(12)
        self.radio = QRadioButton(theme.name)
        self.radio.setObjectName("themeRadio")
        self.radio.setProperty("themeId", theme.identifier)
        layout.addWidget(self.radio)
        text = QVBoxLayout()
        text.setSpacing(1)
        description = QLabel(theme.description)
        description.setObjectName("themeDescription")
        text.addWidget(description)
        text.addWidget(ThemeSwatchStrip(theme.identifier))
        layout.addLayout(text, 1)

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
        super().mouseReleaseEvent(event)


class AppearanceDialog(QDialog):
    theme_previewed = Signal(str)

    def __init__(self, theme_id: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("appearanceDialog")
        self.setWindowTitle("界面风格")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.resize(520, 390)
        self._theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self.setStyleSheet(application_stylesheet(self._theme_id))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(13)
        title = QLabel("界面风格")
        title.setObjectName("appearanceTitle")
        title.setStyleSheet("font-size: 19px; font-weight: 700;")
        layout.addWidget(title)
        hint = QLabel("选择更适合当前工作环境的浅色主题，预览会立即应用。")
        hint.setObjectName("appearanceHint")
        layout.addWidget(hint)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.choice_rows = {}
        for theme in THEMES:
            row = _ThemeChoiceRow(theme)
            self.choice_rows[theme.identifier] = row
            self.button_group.addButton(row.radio)
            row.radio.toggled.connect(
                lambda checked, identifier=theme.identifier: checked
                and self._select_theme(identifier)
            )
            layout.addWidget(row)

        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("使用此风格")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.choice_rows[self._theme_id].radio.setChecked(True)

    @property
    def selected_theme_id(self) -> str:
        return self._theme_id

    def _select_theme(self, theme_id: str):
        self._theme_id = resolve_theme(theme_id).identifier
        self.setStyleSheet(application_stylesheet(self._theme_id))
        for identifier, row in self.choice_rows.items():
            row.set_selected(identifier == self._theme_id)
        self.theme_previewed.emit(self._theme_id)


__all__ = [
    "AppearanceDialog",
    "DEFAULT_THEME_ID",
    "THEMES",
    "THEMES_BY_ID",
    "ThemePicker",
    "ThemeSpec",
    "application_stylesheet",
    "apply_application_theme",
    "compose_stylesheet",
    "current_theme_id",
    "load_theme_id",
    "resolve_theme",
    "save_theme_id",
    "theme_color",
]
