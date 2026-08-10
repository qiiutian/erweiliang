import re
import sys
from dataclasses import replace
from math import ceil, floor
from pathlib import Path

import matplotlib
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QDoubleSpinBox,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from config_adapter import (
    build_config_from_form_data,
    boundary_rows_from_prescribed_dofs,
    config_to_json,
    get_sample_config,
    load_config_from_json,
    measurement_rows_from_config,
    true_point_rows_from_config,
)
from ifem.application import get_default_analysis_service, match_project_algorithms
from ifem.application.parameter_validation import (
    parameter_field,
    validate_parameters,
)
from ifem.domain.analysis import InputValidationError, ValidationIssue
from ifem.domain.project import AnalysisCase, empty_beam_project, new_entity_id
from ifem.infrastructure import ProjectLibrary, load_project, save_project
from ifem.infrastructure.legacy_project import (
    legacy_config_from_project,
    project_from_legacy_config,
)
from ifem.modeling.path_editor import PathBeamEditor
from ifem.ui.modeler import BeamModelerDialog
from ifem.ui.project_library import ProjectLibraryDialog, ProjectNameDialog
from ifem.ui.start_center import (
    START_NEW,
    START_OPEN,
    START_SAMPLE,
    START_WORKSPACE,
    StartCenterDialog,
    StartupRequest,
)
from ifem.ui.theme import (
    AppearanceDialog,
    apply_application_theme,
    compose_stylesheet,
    current_theme_id,
    load_theme_id,
    resolve_theme,
)
from layout_preview import build_measurement_preview
from postprocessing import (
    element_boundary_jumps,
    reconstruct_section_field,
    recover_continuous_section_field,
    resolve_thickness_scale,
    section_field_rows,
)
from visualization_3d import Structure3DView
from visualization_data import result_frame_from_beam, structural_model_from_beam


matplotlib.rcParams["font.sans-serif"] = [
    "Hiragino Sans GB",
    "Arial Unicode MS",
    "Microsoft YaHei",
    "SimHei",
]
matplotlib.rcParams["axes.unicode_minus"] = False


APP_STYLESHEET = """
QWidget {
    color: #1b2a36;
    font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 13px;
}
QMainWindow, QWidget#appRoot {
    background: #f3f6f8;
}
QFrame#topBar {
    background: #123247;
    border: 1px solid #123247;
    border-radius: 10px;
}
QLabel#appTitle {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
}
QLabel#appSubtitle {
    color: #bfd0db;
    font-size: 12px;
}
QLabel#sectionTitle {
    color: #102a3a;
    font-size: 16px;
    font-weight: 700;
}
QLabel#sectionHint, QLabel#hintLabel {
    color: #6b7d89;
    font-size: 12px;
}
QLabel#fieldLabel {
    color: #405461;
    font-weight: 600;
}
QLabel#recordBadge {
    color: #45616f;
    background: #edf3f5;
    border: 1px solid #d8e3e8;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 12px;
}
QLabel#statusBadge {
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusBadge[state="idle"] {
    color: #4f6572;
    background: #e8eef1;
    border: 1px solid #d4dfe4;
}
QLabel#statusBadge[state="running"] {
    color: #155e75;
    background: #cffafe;
    border: 1px solid #a5f3fc;
}
QLabel#statusBadge[state="success"] {
    color: #166534;
    background: #dcfce7;
    border: 1px solid #bbf7d0;
}
QLabel#statusBadge[state="stale"] {
    color: #92400e;
    background: #fef3c7;
    border: 1px solid #fde68a;
}
QLabel#statusBadge[state="error"] {
    color: #991b1b;
    background: #fee2e2;
    border: 1px solid #fecaca;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #d9e2e7;
    border-radius: 8px;
    margin-top: 13px;
    padding-top: 9px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #1b3545;
    background: #f3f6f8;
}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
    color: #172733;
    background: #ffffff;
    border: 1px solid #cbd7de;
    border-radius: 5px;
    padding: 5px 8px;
    selection-background-color: #16758f;
}
QLineEdit, QComboBox {
    min-height: 24px;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid #16758f;
}
QLineEdit::placeholder {
    color: #9aa9b2;
}
QPushButton {
    min-height: 34px;
    padding: 0 14px;
    color: #29404e;
    background: #ffffff;
    border: 1px solid #c8d5dc;
    border-radius: 6px;
    font-weight: 600;
}
QPushButton:hover {
    background: #edf4f6;
    border-color: #93aab6;
}
QPushButton:pressed {
    background: #e3ecef;
}
QPushButton#primaryButton, QPushButton#smallPrimaryButton {
    color: #ffffff;
    background: #16758f;
    border-color: #16758f;
}
QPushButton#primaryButton:hover, QPushButton#smallPrimaryButton:hover {
    background: #115f75;
    border-color: #115f75;
}
QPushButton#primaryButton {
    min-width: 104px;
}
QPushButton#dangerButton {
    color: #b4232f;
    background: #fff7f7;
    border-color: #f2c7ca;
}
QPushButton#dangerButton:hover {
    background: #feecec;
    border-color: #e7a5aa;
}
QPushButton#topBarButton {
    color: #e8f0f4;
    background: #21475d;
    border-color: #3b5f72;
}
QPushButton#topBarButton:hover {
    color: #ffffff;
    background: #2c586f;
    border-color: #5b7d8e;
}
QFrame#viewToolbar {
    background: #f5f8f9;
    border: 1px solid #dbe4e8;
    border-radius: 6px;
}
QFrame#analysisSummary {
    background: #ffffff;
    border: 1px solid #d9e3e8;
    border-radius: 7px;
}
QFrame#metricCard {
    background: transparent;
    border: none;
    border-right: 1px solid #e5ecef;
}
QLabel#metricName {
    color: #7a8d98;
    font-size: 11px;
}
QLabel#metricValue {
    color: #183646;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#viewModeButton {
    min-height: 30px;
    padding: 0 12px;
    color: #526875;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
}
QPushButton#viewModeButton:hover {
    color: #174f63;
    background: #e7f0f3;
}
QPushButton#viewModeButton:checked {
    color: #ffffff;
    background: #16758f;
    border-color: #16758f;
}
QPushButton#displayModeButton {
    min-height: 28px;
    padding: 0 10px;
    color: #526875;
    background: #ffffff;
    border: 1px solid #d2dee4;
    border-radius: 5px;
}
QPushButton#displayModeButton:hover {
    color: #174f63;
    background: #edf4f6;
}
QPushButton#displayModeButton:checked {
    color: #0f6076;
    background: #dff0f4;
    border-color: #8bbdca;
    font-weight: 700;
}
QFrame#toolbarDivider {
    color: #d6e0e5;
    background: #d6e0e5;
    max-width: 1px;
    margin: 4px 7px;
}
QFrame#viewportToolbar {
    background: #edf3f5;
    border: 1px solid #d5e1e6;
    border-radius: 6px;
}
QLabel#viewportStatus {
    color: #54707f;
    font-size: 11px;
    padding-right: 6px;
}
QPushButton#viewportButton {
    min-height: 27px;
    padding: 0 9px;
    color: #365564;
    background: #ffffff;
    border: 1px solid #cedce2;
    border-radius: 4px;
}
QPushButton#viewportButton:hover {
    color: #0f6076;
    background: #f8fbfc;
    border-color: #8fb9c5;
}
QFrame#viewportFallback {
    background: #0b1d28;
    border: 1px solid #274757;
    border-radius: 6px;
}
QFrame#viewportFallback QLabel#sectionHint {
    color: #91a8b5;
}
QLabel#emptyTitle {
    color: #e7f2f6;
    font-size: 17px;
    font-weight: 700;
}
QLabel#viewMeta {
    color: #667b87;
    font-size: 12px;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #d7e0e5;
    border-radius: 7px;
    top: -1px;
}
QTabBar::tab {
    min-width: 64px;
    min-height: 34px;
    padding: 0 8px;
    color: #536a77;
    background: #e9eef1;
    border: 1px solid #d4dee3;
    border-bottom: none;
}
QTabBar::tab:first {
    border-top-left-radius: 6px;
}
QTabBar::tab:last {
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    color: #0f6076;
    background: #ffffff;
    border-top: 3px solid #16758f;
    font-weight: 700;
}
QTabBar::tab:hover:!selected {
    background: #f1f5f6;
}
QTableWidget {
    color: #213440;
    background: #ffffff;
    alternate-background-color: #f7fafb;
    border: 1px solid #d8e2e7;
    border-radius: 5px;
    gridline-color: #edf1f3;
    selection-background-color: #dceff4;
    selection-color: #123247;
}
QTableWidget::item {
    padding: 5px 7px;
    border-bottom: 1px solid #edf1f3;
}
QHeaderView::section {
    color: #39515f;
    background: #edf3f5;
    border: none;
    border-right: 1px solid #d9e2e7;
    border-bottom: 1px solid #d1dde3;
    padding: 7px 8px;
    font-weight: 700;
}
QCheckBox {
    spacing: 7px;
}
QSplitter::handle {
    background: #dbe4e8;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}
QFrame#plotCanvas {
    background: #ffffff;
    border: 1px solid #dce4e8;
    border-radius: 6px;
}
QScrollArea {
    background: transparent;
    border: none;
}
QToolTip {
    color: #f8fbfc;
    background: #17394c;
    border: 1px solid #2b5368;
    border-radius: 5px;
    padding: 7px;
}
QStatusBar {
    color: #607480;
    background: #f3f6f8;
}
"""


# The base stylesheet keeps older Qt versions usable. This final layer is the
# workbench design system: one UI accent, consistent radii, and dense data clarity.
STUDIO_THEME = """
QWidget {
    color: #23302a;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 13px;
}
QMainWindow, QWidget#appRoot {
    background: #f4f6f4;
}
QFrame#topBar {
    background: #ffffff;
    border: 1px solid #d9e1db;
    border-radius: 12px;
}
QLabel#brandMark {
    color: #ffffff;
    background: #365b49;
    border: 1px solid #2e4e3e;
    border-radius: 8px;
    font-family: "Avenir Next";
    font-size: 16px;
    font-weight: 700;
}
QLabel#appTitle {
    color: #1f2c25;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 19px;
    font-weight: 700;
}
QLabel#appSubtitle {
    color: #69756e;
    font-size: 11px;
}
QLabel#sectionTitle {
    color: #243229;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 16px;
    font-weight: 700;
}
QFrame#sectionAccent {
    background: #365b49;
    border: none;
    border-radius: 1px;
}
QLabel#sectionHint, QLabel#hintLabel {
    color: #637067;
    font-size: 12px;
}
QLabel#fieldLabel {
    color: #4d5c53;
    font-weight: 600;
}
QLabel#recordBadge {
    color: #526158;
    background: #edf2ee;
    border: 1px solid #d4ded7;
    border-radius: 8px;
    padding: 3px 9px;
}
QLabel#recordBadge[state="error"] {
    color: #934b3d;
    background: #f6e3de;
    border-color: #e9c6bc;
}
QLabel#statusBadge {
    border-radius: 12px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusBadge[state="idle"] {
    color: #5d6962;
    background: #eef1ef;
    border: 1px solid #d7ddd9;
}
QLabel#statusBadge[state="running"] {
    color: #2f5b47;
    background: #e2eee7;
    border: 1px solid #c2d8ca;
}
QLabel#statusBadge[state="success"] {
    color: #2f5b47;
    background: #e1eee5;
    border: 1px solid #bfd6c6;
}
QLabel#statusBadge[state="stale"] {
    color: #86602c;
    background: #f5ead3;
    border: 1px solid #e8d4ab;
}
QLabel#statusBadge[state="error"] {
    color: #934b3d;
    background: #f6e3de;
    border: 1px solid #e9c6bc;
}
QPushButton#inputBadge {
    min-height: 26px;
    border-radius: 10px;
    padding: 1px 10px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#inputBadge[state="ready"] {
    color: #315b46;
    background: #e1eee5;
    border: 1px solid #bfd6c6;
}
QPushButton#inputBadge[state="pending"] {
    color: #796334;
    background: #f5edd9;
    border: 1px solid #e5d6ae;
}
QPushButton#inputBadge[state="error"] {
    color: #934b3d;
    background: #f6e3de;
    border: 1px solid #e9c6bc;
}
QPushButton#inputBadge:hover, QPushButton#inputBadge:focus {
    border-width: 2px;
    padding: 0 9px;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dbe3dd;
    border-radius: 10px;
    margin-top: 17px;
    padding-top: 11px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 1px;
    padding: 0 6px;
    color: #334239;
    background: #ffffff;
}
QGroupBox#formSection {
    background: transparent;
    border: none;
    border-top: 1px solid #e2e8e3;
    border-radius: 0;
    margin-top: 18px;
    padding-top: 9px;
}
QGroupBox#formSection::title {
    left: 0;
    color: #34443a;
    background: #ffffff;
    padding: 0 8px 0 0;
}
QGroupBox#workspaceGroup {
    border: 1px solid #d9e2dc;
    border-radius: 10px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    color: #24312a;
    background: #ffffff;
    border: 1px solid #ccd7d0;
    border-radius: 7px;
    padding: 5px 9px;
    selection-color: #ffffff;
    selection-background-color: #365b49;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 26px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid #537862;
    background: #fbfdfb;
}
QLineEdit[validationState="error"], QComboBox[validationState="error"],
QSpinBox[validationState="error"], QDoubleSpinBox[validationState="error"] {
    color: #7f3f35;
    background: #fff9f7;
    border: 1px solid #c97666;
}
QLineEdit::placeholder {
    color: #6d7871;
}
QComboBox::drop-down {
    width: 24px;
    border: none;
}
QComboBox QAbstractItemView {
    color: #24312a;
    background: #ffffff;
    border: 1px solid #ccd7d0;
    selection-background-color: #e4eee8;
    selection-color: #24312a;
}
QPushButton {
    min-height: 34px;
    padding: 0 13px;
    color: #3e4d44;
    background: #ffffff;
    border: 1px solid #ccd7d0;
    border-radius: 7px;
    font-weight: 600;
}
QPushButton:hover {
    color: #27372e;
    background: #f1f5f2;
    border-color: #9fafa4;
}
QPushButton:pressed {
    background: #e5ebe7;
}
QPushButton:focus {
    border-color: #365b49;
}
QPushButton:disabled {
    color: #99a29c;
    background: #eef1ef;
    border-color: #dce2de;
}
QPushButton#primaryButton, QPushButton#smallPrimaryButton {
    color: #ffffff;
    background: #365b49;
    border-color: #2f503f;
}
QPushButton#primaryButton:hover, QPushButton#smallPrimaryButton:hover {
    background: #2d4e3e;
    border-color: #284638;
}
QPushButton#dangerButton {
    color: #98473d;
    background: #fff8f6;
    border-color: #e4c8c2;
}
QPushButton#dangerButton:hover {
    background: #f6e7e0;
    border-color: #d5aa9c;
}
QPushButton#dangerGhostButton {
    color: #8c574c;
    background: transparent;
    border-color: transparent;
}
QPushButton#dangerGhostButton:hover {
    color: #934b3d;
    background: #f8ece8;
    border-color: #e4c8c2;
}
QPushButton#topBarButton {
    color: #536158;
    background: #f8faf8;
    border-color: #d9e1db;
}
QPushButton#topBarButton:hover {
    color: #2e4035;
    background: #eef3ef;
    border-color: #b7c5bc;
}
QFrame#commandCluster {
    background: #f2f5f3;
    border: 1px solid #dce4de;
    border-radius: 8px;
}
QFrame#commandCluster QPushButton#topBarButton {
    min-height: 32px;
    padding: 0 10px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
}
QFrame#commandCluster QPushButton#topBarButton:hover {
    color: #2f493a;
    background: #ffffff;
    border-color: #d6e0d9;
}
QMenu {
    color: #2f3d34;
    background: #ffffff;
    border: 1px solid #cfd9d2;
    padding: 5px;
}
QMenu::item {
    min-width: 170px;
    padding: 7px 22px 7px 10px;
    border-radius: 5px;
}
QMenu::item:selected {
    color: #294235;
    background: #e7efe9;
}
QPushButton#modelerButton {
    color: #2f5945;
    background: #ffffff;
    border: 1px solid #7f9b89;
}
QPushButton#modelerButton:hover {
    color: #ffffff;
    background: #4b705c;
    border-color: #4b705c;
}
QFrame#viewToolbar {
    background: #f1f4f2;
    border: 1px solid #d9e1db;
    border-radius: 8px;
}
QFrame#displaySettingsPanel {
    background: #f8faf8;
    border: 1px solid #d9e2dc;
    border-radius: 8px;
}
QFrame#plotMetaBar {
    background: transparent;
    border: none;
    border-bottom: 1px solid #e4e9e5;
}
QLabel#resultFreshness {
    min-height: 22px;
    padding: 0 8px;
    border-radius: 9px;
    font-size: 11px;
    font-weight: 700;
}
QFrame#analysisEmptyState {
    border: 1px solid #dce4de;
    border-radius: 8px;
}
QLabel#analysisEmptyEyebrow {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#analysisEmptyTitle {
    font-size: 20px;
    font-weight: 700;
}
QLabel#analysisEmptyDescription, QLabel#analysisEmptyIssue {
    font-size: 12px;
}
QFrame#analysisWorkflow {
    border: none;
    border-radius: 9px;
}
QFrame#analysisStep {
    border: 1px solid transparent;
    border-radius: 7px;
}
QLabel#analysisStepMarker {
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#analysisStepLabel {
    font-size: 11px;
    font-weight: 600;
}
QPushButton#emptyStateAction {
    min-height: 36px;
    padding: 0 18px;
    font-weight: 700;
}
QLabel#plotContext {
    color: #31463a;
    font-size: 12px;
    font-weight: 700;
}
QFrame#analysisSummary {
    background: #f8faf8;
    border: 1px solid #d9e2dc;
    border-radius: 8px;
}
QFrame#analysisMethodCard {
    background: #f5f8f5;
    border: 1px solid #d4dfd7;
    border-left: 4px solid #4f705c;
    border-radius: 8px;
}
QFrame#analysisMethodCard:focus {
    border-color: #6e94ae;
    border-left-color: #2d6f91;
}
QLabel#algorithmName {
    color: #26372d;
    font-size: 14px;
    font-weight: 700;
}
QLabel#algorithmMeta {
    color: #6a766e;
    font-size: 11px;
}
QLabel#algorithmState {
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#algorithmState[state="ready"] {
    color: #315b46;
    background: #e1eee5;
    border: 1px solid #bfd6c6;
}
QLabel#algorithmState[state="pending"] {
    color: #796334;
    background: #f5edd9;
    border: 1px solid #e5d6ae;
}
QLabel#algorithmState[state="blocked"] {
    color: #934b3d;
    background: #f6e3de;
    border: 1px solid #e9c6bc;
}
QFrame#algorithmSelectorRow {
    background: transparent;
    border: none;
}
QFrame#algorithmParameters {
    background: transparent;
    border: none;
}
QFrame#metricCardPrimary {
    background: #edf4ef;
    border: none;
    border-right: 1px solid #d6e1da;
    border-radius: 6px;
}
QFrame#metricCard {
    background: transparent;
    border: none;
    border-right: 1px solid #dfe6e1;
}
QFrame#metricCardLast {
    background: transparent;
    border: none;
}
QLabel#metricName {
    color: #637067;
    font-size: 11px;
}
QLabel#metricValue {
    color: #2d3d33;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#viewModeButton {
    min-height: 31px;
    padding: 0 13px;
    color: #5f6b64;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
}
QPushButton#viewModeButton:hover {
    color: #30493b;
    background: #e6ede8;
}
QPushButton#viewModeButton:checked {
    color: #ffffff;
    background: #365b49;
    border-color: #365b49;
}
QPushButton#displayModeButton {
    min-height: 29px;
    padding: 0 11px;
    color: #5e6b63;
    background: #ffffff;
    border: 1px solid #d0dad3;
    border-radius: 6px;
}
QPushButton#displayModeButton:hover {
    color: #2f5945;
    background: #edf3ef;
}
QPushButton#displayModeButton:checked {
    color: #2f5945;
    background: #e3eee7;
    border-color: #91aa9a;
    font-weight: 700;
}
QFrame#toolbarDivider {
    color: #d7dfd9;
    background: #d7dfd9;
}
QFrame#viewportToolbar {
    background: #f2f5f3;
    border: 1px solid #d8e1da;
    border-radius: 8px;
}
QFrame#viewportOptions {
    background: transparent;
    border: none;
}
QFrame#viewportOptions QCheckBox {
    spacing: 8px;
    padding-right: 6px;
}
QLabel#viewportStatus {
    color: #627068;
    font-size: 11px;
}
QLabel#viewportHint {
    color: #748078;
    font-size: 11px;
}
QPushButton#viewportButton {
    min-height: 28px;
    padding: 0 10px;
    color: #46564c;
    background: #ffffff;
    border: 1px solid #ccd7d0;
    border-radius: 6px;
}
QPushButton#viewportButton:hover {
    color: #2f5945;
    background: #e8efe9;
    border-color: #9caf9f;
}
QFrame#viewportFallback {
    background: #1b201c;
    border: 1px solid #414a42;
    border-radius: 10px;
}
QFrame#viewportFallback QLabel#sectionHint {
    color: #bbb8ae;
}
QLabel#emptyTitle {
    color: #f2ede4;
    font-size: 17px;
    font-weight: 700;
}
QLabel#viewMeta {
    color: #68746c;
    font-size: 11px;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #d9e2dc;
    border-radius: 9px;
    top: -1px;
}
QTabBar::tab {
    min-width: 52px;
    min-height: 36px;
    padding: 0 10px;
    margin-right: 2px;
    color: #68746c;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
}
QTabBar::tab:selected {
    color: #2f5945;
    background: #ffffff;
    border-top: none;
    border-left: none;
    border-right: none;
    border-bottom: 3px solid #365b49;
    font-weight: 700;
}
QTabBar::tab:hover:!selected {
    color: #36483d;
    background: #edf2ee;
}
QTabWidget#resultTabs QTabBar::tab {
    min-width: 0;
    min-height: 30px;
    padding: 0 9px;
}
QTableWidget {
    color: #2c3931;
    background: #ffffff;
    alternate-background-color: #f7f9f7;
    border: 1px solid #d9e2dc;
    border-radius: 7px;
    gridline-color: #e8ede9;
    selection-background-color: #dfeae3;
    selection-color: #23302a;
    font-family: "Menlo", "PingFang SC", "Noto Sans CJK SC";
    font-size: 12px;
}
QTableWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #e8ede9;
}
QHeaderView::section {
    color: #4d5c53;
    background: #eef3ef;
    border: none;
    border-right: 1px solid #dce4de;
    border-bottom: 1px solid #d5dfd8;
    padding: 7px 8px;
    font-weight: 700;
}
QSplitter::handle {
    background: transparent;
}
QSplitter::handle:hover {
    background: #dfe6e1;
}
QSplitter::handle:horizontal {
    width: 10px;
}
QSplitter::handle:vertical {
    height: 9px;
}
QFrame#plotCanvas {
    background: #ffffff;
    border: 1px solid #dce4de;
    border-radius: 8px;
}
QScrollArea {
    background: transparent;
    border: none;
}
QWidget#tabPage, QWidget#tabContent,
QScrollArea#tabScroll, QScrollArea#tabScroll > QWidget > QWidget {
    background: #ffffff;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px 1px;
}
QScrollBar::handle:vertical {
    background: #bdc8c0;
    min-height: 34px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #96a69b;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0;
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 1px 3px;
}
QScrollBar::handle:horizontal {
    background: #bdc8c0;
    min-width: 34px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    width: 0;
    background: transparent;
}
QToolTip {
    color: #ffffff;
    background: #2d3d33;
    border: 1px solid #506158;
    border-radius: 6px;
    padding: 8px;
}
QStatusBar {
    color: #68746c;
    background: #f4f6f4;
    border-top: 1px solid #dfe5e1;
}
QLabel#statusMeta {
    color: #637067;
    background: #eef2ef;
    border: 1px solid #d9e1db;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
}
QWidget#sensorEditor QGroupBox {
    border-color: #d8e1da;
    border-radius: 9px;
}
QWidget#sensorEditor QTableWidget {
    font-size: 12px;
}
QTabWidget#editorTabs::pane {
    background: #f8faf8;
    border: 1px solid #dce4de;
    border-radius: 7px;
    top: -1px;
}
QTabWidget#editorTabs QTabBar::tab {
    min-width: 64px;
    min-height: 30px;
    padding: 0 12px;
    margin-right: 2px;
    color: #68746c;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabWidget#editorTabs QTabBar::tab:selected {
    color: #2f5945;
    background: #f8faf8;
    border-bottom: 2px solid #365b49;
    font-weight: 700;
}
QWidget#editorForm {
    background: #f8faf8;
}
QPlainTextEdit#jsonEditor {
    font-family: "Menlo", "Noto Sans Mono CJK SC";
    font-size: 12px;
}
"""


class NoWheelComboBox(QComboBox):
    """Keep form scrolling from changing an action-style selection."""

    def wheelEvent(self, event):
        event.ignore()


class EditableTable(QWidget):
    ENTITY_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(
        self,
        title,
        field_specs,
        parent=None,
        on_change=None,
        description="",
        form_columns=2,
        stretch_columns=True,
        table_columns=None,
        form_sections=None,
        table_min_height=210,
        record_noun="条记录",
        header_action=None,
    ):
        super().__init__(parent)
        self.title = title
        self.field_specs = field_specs
        self.inputs = {}
        self.on_change = on_change
        self.form_columns = max(1, int(form_columns))
        self.record_noun = record_noun

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        group = QGroupBox(title)
        layout.addWidget(group)

        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 14, 12, 12)
        group_layout.setSpacing(10)

        meta_bar = QHBoxLayout()
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("hintLabel")
            description_label.setWordWrap(True)
            meta_bar.addWidget(description_label, 1)
        else:
            meta_bar.addStretch(1)
        self.count_label = QLabel("0 条记录")
        self.count_label.setObjectName("recordBadge")
        meta_bar.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignTop)
        if header_action:
            action_text, action_callback = header_action
            self.header_action_button = QPushButton(action_text)
            self.header_action_button.setObjectName("modelerButton")
            self.header_action_button.setToolTip("进入交互建模器，在梁模型表面布置和调整测点")
            self.header_action_button.clicked.connect(action_callback)
            meta_bar.addWidget(self.header_action_button, 0, Qt.AlignmentFlag.AlignTop)
        group_layout.addLayout(meta_bar)

        self.table = QTableWidget(0, len(field_specs))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.setMinimumHeight(table_min_height)

        headers = [spec.get("table_label", spec["label"]) for spec in field_specs]
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(58)
        visible_keys = set(
            table_columns or [spec["key"] for spec in self.field_specs]
        )
        visible_columns = []
        for column, spec in enumerate(self.field_specs):
            visible = spec["key"] in visible_keys
            self.table.setColumnHidden(column, not visible)
            if visible:
                visible_columns.append(column)
        if table_columns:
            self.table.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        if stretch_columns:
            for column in visible_columns:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        else:
            for column in visible_columns:
                header.setSectionResizeMode(
                    column,
                    QHeaderView.ResizeMode.ResizeToContents,
                )
            if visible_columns:
                header.setSectionResizeMode(
                    visible_columns[-1],
                    QHeaderView.ResizeMode.Stretch,
                )
            header.setStretchLastSection(False)
        group_layout.addWidget(self.table)

        if form_sections:
            self.editor_tabs = QTabWidget()
            self.editor_tabs.setObjectName("editorTabs")
            specs_by_key = {spec["key"]: spec for spec in self.field_specs}
            for section_title, section_keys in form_sections:
                section_specs = [specs_by_key[key] for key in section_keys]
                self.editor_tabs.addTab(
                    self._build_form(section_specs),
                    section_title,
                )
            group_layout.addWidget(self.editor_tabs)
        else:
            group_layout.addWidget(self._build_form(self.field_specs))

        button_bar = QHBoxLayout()
        self.add_button = QPushButton("新增")
        self.update_button = QPushButton("更新选中")
        self.delete_button = QPushButton("删除选中")
        self.clear_button = QPushButton("清空全部")
        self.add_button.setObjectName("smallPrimaryButton")
        self.delete_button.setObjectName("dangerButton")
        self.clear_button.setObjectName("dangerGhostButton")
        self.add_button.setToolTip("将填写的数据加入表格")
        self.update_button.setToolTip("用当前数据覆盖选中记录")
        self.delete_button.setToolTip("删除当前选中的记录")
        self.clear_button.setToolTip("清空当前表格的全部记录")
        self.add_button.clicked.connect(self.add_row)
        self.update_button.clicked.connect(self.update_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.clear_button.clicked.connect(self.confirm_clear_rows)

        button_bar.addWidget(self.add_button)
        button_bar.addWidget(self.update_button)
        button_bar.addWidget(self.delete_button)
        button_bar.addWidget(self.clear_button)
        button_bar.addStretch(1)
        group_layout.addLayout(button_bar)
        self._update_count()

    def _build_form(self, specs):
        form = QWidget()
        form.setObjectName("editorForm")
        form_layout = QGridLayout(form)
        form_layout.setContentsMargins(8, 8, 8, 8)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(8)
        for index, spec in enumerate(specs):
            row = index // self.form_columns
            col = (index % self.form_columns) * 2
            label = QLabel(spec["label"])
            label.setObjectName("fieldLabel")
            form_layout.addWidget(label, row, col)
            widget = self._create_input(spec)
            self.inputs[spec["key"]] = widget
            form_layout.addWidget(widget, row, col + 1)
            form_layout.setColumnStretch(col + 1, 1)
        return form

    def _create_input(self, spec):
        choices = spec.get("choices")
        if choices:
            widget = QComboBox()
            widget.addItems(choices)
            widget.setEditable(False)
            if spec.get("tooltip"):
                widget.setToolTip(spec["tooltip"])
            return widget
        widget = QLineEdit()
        widget.setClearButtonEnabled(True)
        widget.setPlaceholderText(spec.get("placeholder", ""))
        if spec.get("tooltip"):
            widget.setToolTip(spec["tooltip"])
        return widget

    def _get_widget_value(self, widget):
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return widget.text().strip()

    def _table_item(self, spec, value):
        raw_value = "" if value is None else str(value)
        display_map = spec.get("table_display", {})
        item = QTableWidgetItem(display_map.get(raw_value, raw_value))
        item.setData(Qt.ItemDataRole.UserRole, raw_value)
        alignment = spec.get("table_align")
        if alignment == "right":
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        elif alignment == "center":
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _row_entity_id(self, row):
        item = self.table.item(row, 0)
        if item is None:
            return ""
        return str(item.data(self.ENTITY_ID_ROLE) or "")

    def _set_row_entity_id(self, row, entity_id):
        item = self.table.item(row, 0)
        if item is not None:
            item.setData(
                self.ENTITY_ID_ROLE,
                str(entity_id) if entity_id else None,
            )

    def set_row_entity_ids(self, entity_ids):
        if len(entity_ids) != self.table.rowCount():
            raise ValueError(f"{self.title}行数与实体 ID 数量不一致。")
        for row, entity_id in enumerate(entity_ids):
            self._set_row_entity_id(row, entity_id)

    @staticmethod
    def _table_item_value(item):
        if item is None:
            return ""
        raw_value = item.data(Qt.ItemDataRole.UserRole)
        return item.text() if raw_value is None else str(raw_value)

    def _set_widget_value(self, widget, value):
        text = "" if value is None else str(value)
        if isinstance(widget, QComboBox):
            index = widget.findText(text)
            if index >= 0:
                widget.setCurrentIndex(index)
            else:
                widget.setCurrentText(text)
        else:
            widget.setText(text)

    def get_form_values(self):
        return {spec["key"]: self._get_widget_value(self.inputs[spec["key"]]) for spec in self.field_specs}

    def set_form_values(self, values):
        for spec in self.field_specs:
            self._set_widget_value(self.inputs[spec["key"]], values.get(spec["key"], ""))

    def clear_form(self):
        for spec in self.field_specs:
            self._set_widget_value(self.inputs[spec["key"]], "")

    def add_row(self):
        values = self.get_form_values()
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, spec in enumerate(self.field_specs):
            self.table.setItem(
                row,
                col,
                self._table_item(spec, values[spec["key"]]),
            )
        self.clear_form()
        self._update_count()
        self._emit_change()

    def update_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        entity_id = self._row_entity_id(row)
        values = self.get_form_values()
        for col, spec in enumerate(self.field_specs):
            self.table.setItem(
                row,
                col,
                self._table_item(spec, values[spec["key"]]),
            )
        self._set_row_entity_id(row, entity_id)
        self._emit_change()

    def delete_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._update_count()
            self._emit_change()

    def clear_rows(self):
        self.table.setRowCount(0)
        self.clear_form()
        self._update_count()
        self._emit_change()

    def confirm_clear_rows(self):
        if self.table.rowCount() == 0:
            return
        answer = QMessageBox.question(
            self,
            f"清空{self.title}",
            "确定清空全部记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_rows()

    def on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            return
        values = {}
        for col, spec in enumerate(self.field_specs):
            item = self.table.item(row, col)
            values[spec["key"]] = self._table_item_value(item)
        self.set_form_values(values)

    def get_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            payload = {}
            for col, spec in enumerate(self.field_specs):
                item = self.table.item(row, col)
                payload[spec["key"]] = self._table_item_value(item)
            entity_id = self._row_entity_id(row)
            if entity_id:
                payload["_entity_id"] = entity_id
            rows.append(payload)
        return rows

    def set_rows(self, rows):
        self.table.setRowCount(0)
        for payload in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, spec in enumerate(self.field_specs):
                self.table.setItem(
                    row,
                    col,
                    self._table_item(spec, payload.get(spec["key"], "")),
                )
            self._set_row_entity_id(row, payload.get("_entity_id", ""))
        self.clear_form()
        self._update_count()
        self._emit_change()

    def _update_count(self):
        self.count_label.setText(f"{self.table.rowCount()} {self.record_noun}")

    def set_validation_state(self, state="", message=""):
        self.count_label.setProperty("state", state)
        self.count_label.setToolTip(message or f"{self.title}状态")
        style = self.count_label.style()
        style.unpolish(self.count_label)
        style.polish(self.count_label)
        self.count_label.update()

    def focus_validation_issue(self, message="", *, field_path=None):
        """Reveal the exact row/field when a stable path is available."""
        text = str(message or "")
        field_path = str(field_path or "")
        path_parts = [part for part in field_path.strip("/").split("/") if part]
        row = -1
        field_key = None
        if len(path_parts) >= 2:
            row_token = path_parts[1].replace("~1", "/").replace("~0", "~")
            if row_token.isdigit():
                row = int(row_token)
            else:
                for candidate, payload in enumerate(self.get_rows()):
                    if str(payload.get("_entity_id", "")) == row_token:
                        row = candidate
                        break
            tail = path_parts[2:]
            field_key = self._field_key_from_path(tail)

        if row < 0:
            row_match = re.search(r"第\s*(\d+)\s*(?:条|个)", text)
            row = (
                int(row_match.group(1)) - 1
                if row_match
                else self.table.currentRow()
            )
        if not 0 <= row < self.table.rowCount():
            row = 0 if self.table.rowCount() else -1
        if row >= 0:
            self.table.selectRow(row)
            self.on_selection_changed()

        if field_key not in self.inputs:
            field_terms = (
                ("局部积分起点", "zone_a"),
                ("局部积分终点", "zone_b"),
                ("量长起点", "zone_a"),
                ("量长终点", "zone_b"),
                ("单元号", "element"),
                ("节点号", "node"),
                ("自由度", "dof"),
                ("约束值", "value"),
                ("截面 y", "y"),
                ("surface", "surface"),
                ("应变", "strain"),
                ("权重", "weight"),
                ("的 u", "u"),
                ("的 v", "v"),
                ("的 x", "x"),
            )
            field_key = next(
                (
                    key
                    for term, key in field_terms
                    if term in text and key in self.inputs
                ),
                None,
            )
        if field_key is None:
            field_key = next(iter(self.inputs), None)
        target = self.inputs.get(field_key)
        if target is None:
            self.table.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if hasattr(self, "editor_tabs"):
            form_page = target.parentWidget()
            tab_index = self.editor_tabs.indexOf(form_page)
            if tab_index >= 0:
                self.editor_tabs.setCurrentIndex(tab_index)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        if isinstance(target, QLineEdit):
            target.selectAll()

    def _field_key_from_path(self, tail):
        if not tail:
            return None
        key = tail[0].replace("~1", "/").replace("~0", "~")
        direct = {
            "element": "element",
            "x": "x",
            "surface": "surface",
            "y": "y",
            "strain": "strain",
            "measured_value": "strain",
            "weight": "weight",
            "zone_a": "zone_a",
            "zone_b": "zone_b",
            "node": "node",
            "node_id": "node",
            "dof": "dof",
            "value": "value",
            "label": "label",
            "u": "u",
            "v": "v",
        }
        if key in direct:
            return direct[key]
        if key != "attachment" or len(tail) < 2:
            return None
        attachment_key = tail[1]
        if attachment_key == "local_coordinates":
            return "x"
        if attachment_key in {"surface_side", "surface_angle_degrees"}:
            return "surface"
        if attachment_key == "integration_bounds":
            return "zone_b" if len(tail) >= 3 and tail[2] == "1" else "zone_a"
        return None

    def _emit_change(self):
        if callable(self.on_change):
            self.on_change()


class ReadOnlyTable(QWidget):
    def __init__(
        self,
        columns,
        headings,
        parent=None,
        stretch_columns=True,
        *,
        accessible_name="结果数据表",
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.table = QTableWidget(0, len(columns))
        self.columns = columns
        self.headings = headings
        self.table.setHorizontalHeaderLabels(headings)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setAccessibleName(accessible_name)
        self.table.setAccessibleDescription(
            "只读科学结果表。选择一行后使用复制快捷键可导出为制表符分隔文本。"
        )
        self.table.setToolTip("选择一行后按 Ctrl+C（macOS 为 ⌘C）复制数据")
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(76)
        if stretch_columns:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setStretchLastSection(True)
        layout.addWidget(self.table)

        self.copy_action = QAction("复制所选行", self)
        self.copy_action.triggered.connect(self.copy_selected_row)
        self.table.addAction(self.copy_action)
        self.copy_shortcut = QShortcut(
            QKeySequence.StandardKey.Copy,
            self.table,
        )
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.copy_shortcut.activated.connect(self.copy_selected_row)

    def copy_selected_row(self):
        """Copy the current result row as TSV for spreadsheets and reports."""
        row = self.table.currentRow()
        if row < 0:
            return False
        values = []
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            values.append("" if item is None else item.text())
        QApplication.clipboard().setText("\t".join(values))
        return True

    def set_rows(self, rows):
        self.table.setRowCount(0)
        for payload in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, column in enumerate(self.columns):
                item = QTableWidgetItem(str(payload.get(column, "")))
                alignment = Qt.AlignmentFlag.AlignLeft if column == "标签" else Qt.AlignmentFlag.AlignRight
                item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 30)


class AnalysisEmptyState(QFrame):
    """Actionable pre-analysis state shown instead of an inert blank plot."""

    action_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("analysisEmptyState")
        self.setAccessibleName("分析准备状态")

        root = QVBoxLayout(self)
        self.root_layout = root
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(10)
        root.addStretch(2)

        self.eyebrow_label = QLabel("分析流程")
        self.eyebrow_label.setObjectName("analysisEmptyEyebrow")
        self.eyebrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.eyebrow_label)

        self.title_label = QLabel("正在检查输入")
        self.title_label.setObjectName("analysisEmptyTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        root.addWidget(self.title_label)

        self.description_label = QLabel("模型、测点与约束会在这里汇总。")
        self.description_label.setObjectName("analysisEmptyDescription")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        root.addWidget(self.description_label)

        self.workflow = QFrame()
        self.workflow.setObjectName("analysisWorkflow")
        self.workflow.setMinimumHeight(38)
        workflow_layout = QHBoxLayout(self.workflow)
        workflow_layout.setContentsMargins(8, 7, 8, 7)
        workflow_layout.setSpacing(7)
        self.step_frames = []
        self.step_markers = []
        for index, text in enumerate(("检查输入", "运行重构", "查看结果"), start=1):
            step = QFrame()
            step.setObjectName("analysisStep")
            step_layout = QHBoxLayout(step)
            step_layout.setContentsMargins(9, 5, 9, 5)
            step_layout.setSpacing(6)
            marker = QLabel(str(index))
            marker.setObjectName("analysisStepMarker")
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setFixedSize(20, 20)
            label = QLabel(text)
            label.setObjectName("analysisStepLabel")
            step_layout.addWidget(marker)
            step_layout.addWidget(label)
            workflow_layout.addWidget(step, 1)
            self.step_frames.append(step)
            self.step_markers.append(marker)
        root.addWidget(self.workflow)

        self.issue_label = QLabel()
        self.issue_label.setObjectName("analysisEmptyIssue")
        self.issue_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.issue_label.setWordWrap(True)
        self.issue_label.setMinimumHeight(34)
        root.addWidget(self.issue_label)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.action_button = QPushButton("检查输入")
        self.action_button.setObjectName("emptyStateAction")
        self.action_button.setMinimumWidth(168)
        self.action_button.clicked.connect(
            lambda _checked=False: self.action_requested.emit()
        )
        action_row.addWidget(self.action_button)
        action_row.addStretch(1)
        root.addLayout(action_row)
        root.addStretch(3)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.height() < 280
        self.eyebrow_label.setVisible(not compact)
        if compact:
            self.root_layout.setContentsMargins(24, 10, 24, 10)
            self.root_layout.setSpacing(6)
            self.issue_label.setMinimumHeight(22)
        else:
            self.root_layout.setContentsMargins(40, 24, 40, 24)
            self.root_layout.setSpacing(10)
            self.issue_label.setMinimumHeight(34)

    @staticmethod
    def _apply_state(widget, state):
        widget.setProperty("state", state)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def set_readiness(self, issues, *, waiting_for_algorithm=False):
        issues = list(issues or [])
        if issues:
            count = len(issues)
            if waiting_for_algorithm:
                self.title_label.setText("模型已保存，正在等待可用算法")
                self.description_label.setText(
                    "当前几何超出已接入求解器的能力范围，配置不会丢失。"
                )
                self.action_button.setText("查看算法说明")
            else:
                self.title_label.setText("先完成输入检查")
                self.description_label.setText(
                    f"发现 {count} 项需要处理；定位后可直接回到这里运行重构。"
                )
                self.action_button.setText("定位首个问题")
            first_message = str(issues[0].get("message", "请检查当前输入。"))
            self.issue_label.setText(first_message)
            self.issue_label.setToolTip("\n".join(
                str(issue.get("message", "")) for issue in issues[:4]
            ))
            states = ("active", "waiting", "waiting")
            markers = ("1", "2", "3")
        else:
            self.title_label.setText("输入已就绪，可以开始重构")
            self.description_label.setText(
                "运行后可在形态、应变与应力之间切换，并复制精确结果数据。"
            )
            self.issue_label.setText("所有必填项和当前算法兼容性检查均已通过")
            self.issue_label.setToolTip("")
            self.action_button.setText("运行重构")
            states = ("done", "active", "waiting")
            markers = ("✓", "2", "3")

        for frame, marker, state, marker_text in zip(
            self.step_frames,
            self.step_markers,
            states,
            markers,
        ):
            marker.setText(marker_text)
            self._apply_state(frame, state)
            self._apply_state(marker, state)
        self.setAccessibleDescription(
            f"{self.title_label.text()}。{self.issue_label.text()}"
        )
        self.action_button.setAccessibleName(self.action_button.text())


class MeasurementPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_id = current_theme_id()
        self._apply_theme_colors()
        self.preview_data = {
            "ok": False,
            "message": "填写合法节点与测量数据后显示示意。",
            "beam_start": 0.0,
            "beam_end": 0.0,
            "beam_length": 0.0,
            "nodes": [],
            "items": [],
            "measurement_count": 0,
            "node_count": 0,
        }
        self._hovered_item_key = None
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        self._apply_theme_colors()
        self.update()

    def _apply_theme_colors(self):
        theme = resolve_theme(self._theme_id)
        self.MARK_LINE = QColor(theme.color("sensor_dark"))
        self.MARK_FILL = QColor(theme.color("sensor"))
        self.MARK_HOVER = QColor(theme.color("sensor_hover"))
        self.BEAM_COLOR = QColor(theme.color("beam"))
        self.BEAM_FILL = QColor(theme.color("beam_fill"))
        self.NODE_COLOR = QColor(theme.color("node"))
        self.TEXT_COLOR = QColor(theme.color("text"))
        self.MUTED_TEXT = QColor(theme.color("text_muted"))

    def set_preview_data(self, preview_data):
        self.preview_data = preview_data
        self._hovered_item_key = None
        QToolTip.hideText()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(12, 10, -12, -10)
        if rect.width() <= 80 or rect.height() <= 80:
            return

        painter.setPen(self.TEXT_COLOR)
        if not self.preview_data.get("ok"):
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.preview_data["message"])
            return

        summary = (
            f"梁长 {self.preview_data['beam_length']:.6g} | "
            f"节点 {self.preview_data['node_count']} | "
            f"测点 {self.preview_data['measurement_count']}"
        )
        painter.drawText(rect.left(), rect.top() + 16, summary)
        legend_x = max(rect.left() + 160, rect.right() - 130)
        self._draw_legend(painter, legend_x, rect.top() + 15)

        beam_left, beam_right, beam_y = self._drawing_geometry(rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.BEAM_FILL)
        painter.drawRoundedRect(beam_left, beam_y - 6, beam_right - beam_left, 12, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.BEAM_COLOR, 1.4))
        painter.drawLine(beam_left, beam_y - 6, beam_right, beam_y - 6)
        painter.drawLine(beam_left, beam_y + 6, beam_right, beam_y + 6)
        painter.setPen(self.MUTED_TEXT)
        painter.drawText(rect.left(), beam_y - 28, 52, 18, Qt.AlignmentFlag.AlignRight, "上表面")
        painter.drawText(rect.left(), beam_y + 10, 52, 18, Qt.AlignmentFlag.AlignRight, "下表面")

        nodes = self.preview_data["nodes"]
        for node in nodes:
            x_pos = self._map_x(node, beam_left, beam_right)
            painter.setPen(QPen(self.NODE_COLOR, 1))
            painter.drawLine(x_pos, beam_y - 11, x_pos, beam_y + 11)
            painter.setPen(self.MUTED_TEXT)
            painter.drawText(x_pos - 25, beam_y + 40, 50, 18, Qt.AlignmentFlag.AlignHCenter, f"{node:.3g}")

        laid_out_items = self._layout_items(beam_left, beam_right, beam_y)
        for item in laid_out_items:
            rect_width = item["rect_width"]
            rect_height = item["rect_height"]
            y_pos = item["center_y"]
            x_pos = item["pixel_x"]

            is_hovered = item["sequence"] == self._hovered_item_key
            if is_hovered:
                halo = QColor(self.MARK_FILL)
                halo.setAlpha(45)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawRoundedRect(
                    x_pos - rect_width // 2 - 4,
                    y_pos - rect_height // 2 - 4,
                    rect_width + 8,
                    rect_height + 8,
                    5,
                    5,
                )
                painter.setPen(QPen(self.MARK_HOVER, 1.6))
                painter.setBrush(self.MARK_HOVER)
            else:
                painter.setPen(QPen(self.MARK_LINE, 1.2))
                painter.setBrush(self.MARK_FILL)
            painter.drawRoundedRect(x_pos - rect_width // 2, y_pos - rect_height // 2, rect_width, rect_height, 3, 3)

    def mouseMoveEvent(self, event):
        item = self._find_item_at(event.position().x(), event.position().y())
        if item is None:
            if self._hovered_item_key is not None:
                self.update()
            self._hovered_item_key = None
            self.unsetCursor()
            QToolTip.hideText()
            return

        item_key = item["sequence"]
        if item_key != self._hovered_item_key:
            self._hovered_item_key = item_key
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        QToolTip.showText(event.globalPosition().toPoint(), self._tooltip_text(item), self)

    def leaveEvent(self, _event):
        self._hovered_item_key = None
        self.unsetCursor()
        QToolTip.hideText()
        self.update()

    def _draw_legend(self, painter, x, y):
        self._draw_legend_chip(painter, x, y, self.MARK_FILL, self.MARK_LINE, "测点（悬停详情）")

    def _draw_legend_chip(self, painter, x, y, fill_color, line_color, text):
        painter.setPen(QPen(line_color, 1.2))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(x, y - 9, 18, 9, 3, 3)
        painter.setPen(self.TEXT_COLOR)
        painter.drawText(x + 24, y, text)

    @staticmethod
    def _drawing_geometry(rect):
        beam_left = rect.left() + 62
        beam_right = rect.right() - 18
        drawing_top = rect.top() + 48
        drawing_bottom = rect.bottom() - 24
        beam_y = int((drawing_top + drawing_bottom) / 2)
        return beam_left, beam_right, beam_y

    def _map_x(self, value, beam_left, beam_right):
        beam_start = self.preview_data["beam_start"]
        beam_length = max(self.preview_data["beam_length"], 1e-12)
        ratio = (value - beam_start) / beam_length
        return int(beam_left + ratio * (beam_right - beam_left))

    def _layout_items(self, beam_left, beam_right, beam_y):
        items = []
        side_row_ends = {"top": [], "bottom": []}
        min_gap = 6

        for item in sorted(
            self.preview_data["items"],
            key=lambda payload: (payload["surface_side"], payload["global_x"], payload["sequence"]),
        ):
            payload = {
                "pixel_x": self._map_x(item["global_x"], beam_left, beam_right),
                "rect_width": 18,
                "rect_height": 9,
                "row_index": 0,
                "surface_side": item["surface_side"],
                "sequence": item["sequence"],
                "element_index": item["element_index"],
                "local_x": item["local_x"],
                "global_x": item["global_x"],
                "surface_label": item["surface_label"],
                "strain_text": item["strain_text"],
            }
            row_ends = side_row_ends[payload["surface_side"]]
            left_edge = payload["pixel_x"] - payload["rect_width"] // 2
            row_index = 0
            while row_index < len(row_ends) and left_edge <= row_ends[row_index] + min_gap:
                row_index += 1
            right_edge = payload["pixel_x"] + payload["rect_width"] // 2
            if row_index == len(row_ends):
                row_ends.append(right_edge)
            else:
                row_ends[row_index] = right_edge
            payload["row_index"] = row_index
            if payload["surface_side"] == "top":
                payload["center_y"] = beam_y - 15 - row_index * 15
            else:
                payload["center_y"] = beam_y + 15 + row_index * 15
            items.append(payload)

        return items

    def _find_item_at(self, x_pos, y_pos):
        rect = self.rect().adjusted(12, 10, -12, -10)
        if not self.preview_data.get("ok") or rect.width() <= 80 or rect.height() <= 80:
            return None

        beam_left, beam_right, beam_y = self._drawing_geometry(rect)
        for item in reversed(self._layout_items(beam_left, beam_right, beam_y)):
            half_width = item["rect_width"] // 2 + 3
            half_height = item["rect_height"] // 2 + 4
            if (item["pixel_x"] - half_width) <= x_pos <= (item["pixel_x"] + half_width) and (
                item["center_y"] - half_height
            ) <= y_pos <= (item["center_y"] + half_height):
                return item
        return None

    def _tooltip_text(self, item):
        return (
            f"位置: 单元 {item['element_index']} | 局部 x={item['local_x']:.6g} | 全局 x={item['global_x']:.6g}\n"
            f"表面: {item['surface_label']}\n"
            f"应变: {item['strain_text']}"
        )


class AnalysisSetupWidget(QWidget):
    """User-selected reconstruction method with project solvability feedback."""

    RECOVERY_UNBOUND = "unbound"
    RECOVERY_READY = "ready"
    RECOVERY_MISSING = "plugin_missing"
    RECOVERY_VERSION = "version_mismatch"
    RECOVERY_SCHEMA = "schema_mismatch"
    RECOVERY_INCOMPATIBLE = "incompatible"
    RECOVERY_INVALID_SCHEMA = "invalid_schema"

    def __init__(self, analysis_service, on_change=None, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("重构方法")
        self.analysis_service = analysis_service
        self.on_change = on_change
        self._active_algorithm_id = analysis_service.default_algorithm_id
        self._requested_algorithm_id = self._active_algorithm_id
        self._active_case_id = None
        self._saved_case = None
        self._saved_parameters = {}
        self._binding_accepted = True
        self._configuration_modified = False
        self._recovery_status = self.RECOVERY_UNBOUND
        self._parameter_issues = ()
        self._parameter_editors = {}
        self._parameter_schemas = {}
        self._parameter_cache = {}
        self._compatible_algorithm_ids = ()
        self._algorithm_matches = {}
        self.is_compatible = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        self.method_card = QFrame()
        self.method_card.setObjectName("analysisMethodCard")
        self.method_card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.method_card.setAccessibleName("当前重构方法")
        method_layout = QHBoxLayout(self.method_card)
        method_layout.setContentsMargins(11, 8, 9, 8)
        method_layout.setSpacing(9)

        method_text = QVBoxLayout()
        method_text.setSpacing(0)
        self.algorithm_name_label = QLabel()
        self.algorithm_name_label.setObjectName("algorithmName")
        self.algorithm_meta_label = QLabel()
        self.algorithm_meta_label.setObjectName("algorithmMeta")
        method_text.addWidget(self.algorithm_name_label)
        method_text.addWidget(self.algorithm_meta_label)
        method_layout.addLayout(method_text, 1)

        self.algorithm_state_label = QLabel("待匹配")
        self.algorithm_state_label.setObjectName("algorithmState")
        self.algorithm_state_label.setProperty("state", "pending")
        self.algorithm_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        method_layout.addWidget(self.algorithm_state_label, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.method_card)

        self.algorithm_selector_row = QFrame()
        self.algorithm_selector_row.setObjectName("algorithmSelectorRow")
        selector_layout = QHBoxLayout(self.algorithm_selector_row)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(8)
        self.algorithm_selector_label = QLabel("切换方法")
        self.algorithm_selector_label.setObjectName("fieldLabel")
        self.algorithm_selector = NoWheelComboBox()
        self.algorithm_selector.setAccessibleName("切换重构方法")
        self.algorithm_selector_label.setBuddy(self.algorithm_selector)
        self.algorithm_selector.currentIndexChanged.connect(
            self._on_algorithm_selected
        )
        selector_layout.addWidget(self.algorithm_selector_label)
        selector_layout.addWidget(self.algorithm_selector, 1)
        root.addWidget(self.algorithm_selector_row)

        self.algorithm_feedback_label = QLabel()
        self.algorithm_feedback_label.setObjectName("hintLabel")
        self.algorithm_feedback_label.setWordWrap(True)
        root.addWidget(self.algorithm_feedback_label)

        recovery_actions = QHBoxLayout()
        recovery_actions.setContentsMargins(0, 0, 0, 0)
        recovery_actions.addStretch(1)
        self.accept_current_button = QPushButton("采用当前版本/配置")
        self.accept_current_button.setObjectName("smallPrimaryButton")
        self.accept_current_button.setToolTip(
            "明确使用当前已安装插件及其参数模式；接受前项目中的原配置保持不变"
        )
        self.accept_current_button.clicked.connect(self._accept_current_binding)
        self.accept_current_button.hide()
        recovery_actions.addWidget(self.accept_current_button)
        root.addLayout(recovery_actions)

        parameter_header = QLabel("方法参数")
        parameter_header.setObjectName("fieldLabel")
        root.addWidget(parameter_header)

        self.parameter_panel = QFrame()
        self.parameter_panel.setObjectName("algorithmParameters")
        self.parameter_grid = QGridLayout(self.parameter_panel)
        self.parameter_grid.setContentsMargins(0, 0, 0, 0)
        self.parameter_grid.setHorizontalSpacing(9)
        self.parameter_grid.setVerticalSpacing(7)
        self.parameter_grid.setColumnStretch(1, 1)
        self.parameter_grid.setColumnStretch(3, 1)
        root.addWidget(self.parameter_panel)

        self._activate_algorithm(
            self._active_algorithm_id,
            use_cache=False,
            force_rebuild=True,
        )
        self.set_project(None)

    @property
    def active_algorithm_id(self):
        return self._active_algorithm_id

    @property
    def requested_algorithm_id(self):
        return self._requested_algorithm_id

    @property
    def active_case_id(self):
        return self._active_case_id

    @property
    def recovery_status(self):
        return self._recovery_status

    @property
    def should_preserve_saved_case(self):
        return self._saved_case is not None and not self._binding_accepted

    @property
    def configuration_modified(self):
        return self._configuration_modified

    @property
    def active_algorithm(self):
        if self._active_algorithm_id not in self.analysis_service.registry:
            return None
        return self.analysis_service.registry.get(self._active_algorithm_id)

    @property
    def active_algorithm_display_name(self):
        algorithm = self.active_algorithm
        if algorithm is not None:
            return algorithm.metadata.display_name
        return self._requested_algorithm_id or "未指定方法"

    @property
    def active_algorithm_version(self):
        algorithm = self.active_algorithm
        return None if algorithm is None else algorithm.metadata.version

    @property
    def active_parameter_schema_version(self):
        algorithm = self.active_algorithm
        if algorithm is None:
            return None
        return algorithm.metadata.parameter_schema_version

    @property
    def parameter_issues(self):
        return tuple(self._parameter_issues)

    @property
    def declared_parameter_names(self):
        return frozenset(self._parameter_schemas)

    @staticmethod
    def parameter_field_path(name):
        return parameter_field(name)

    def field_target(self, field_path):
        """Resolve stable analysis field paths without inspecting translated text."""
        field_path = str(field_path or "")
        if field_path in {
            "/analysis/algorithm/id",
            "/analysis/algorithm/version",
            "/analysis/algorithm/parameter-schema-version",
            "/analysis/solvability",
        }:
            if not self.accept_current_button.isHidden():
                return self.accept_current_button
            if not self.algorithm_selector_row.isHidden():
                return self.algorithm_selector
            return self.method_card
        prefix = "/analysis/parameters/"
        if not field_path.startswith(prefix):
            return None
        name = field_path[len(prefix) :].replace("~1", "/").replace("~0", "~")
        return self.parameter_editor(name)

    def parameter_editor(self, name):
        return self._parameter_editors.get(name)

    def parameter_values(self):
        if self.should_preserve_saved_case:
            return dict(self._saved_parameters)
        values = {
            name: self._editor_value(editor)
            for name, editor in self._parameter_editors.items()
            if editor.property("parameterHasValue") is not False
        }
        if self._active_algorithm_id:
            self._parameter_cache[self._active_algorithm_id] = dict(values)
        return values

    def set_parameter_values(self, parameters):
        if self.should_preserve_saved_case:
            return
        for name, value in dict(parameters).items():
            editor = self._parameter_editors.get(name)
            schema = self._parameter_schemas.get(name)
            if (
                editor is not None
                and schema is not None
                and self._parameter_value_is_valid(name, schema, value)
            ):
                if self._set_editor_value(editor, value):
                    editor.setProperty("parameterHasValue", True)
        if self._active_algorithm_id:
            self._parameter_cache[self._active_algorithm_id] = self.parameter_values()

    @staticmethod
    def _active_case(project):
        if project is None or not project.analysis_cases:
            return None
        if project.active_analysis_id is not None:
            return next(
                (
                    case
                    for case in project.analysis_cases
                    if case.identifier == project.active_analysis_id
                ),
                project.analysis_cases[0],
            )
        return project.analysis_cases[0]

    def project_requires_recovery(self, project):
        """Inspect binding safety without changing the current editor state."""
        active_case = self._active_case(project)
        if active_case is None:
            return False
        requested_id = active_case.algorithm_id
        if requested_id not in self.analysis_service.registry:
            return True
        matches = match_project_algorithms(
            project,
            self.analysis_service.registry.list(),
        )
        match = next(
            (item for item in matches if item.algorithm_id == requested_id),
            None,
        )
        if match is None or not match.compatible:
            return True
        resolution = self.analysis_service.registry.resolve(
            requested_id,
            expected_version=active_case.algorithm_version,
            expected_schema_version=active_case.parameter_schema_version,
        )
        if not resolution.is_ready:
            return True
        schema = self.analysis_service.registry.parameter_schema(requested_id)
        return not validate_parameters(schema, active_case.parameters).is_valid

    def set_project(self, project):
        algorithms = self.analysis_service.registry.list()
        matches = () if project is None else match_project_algorithms(project, algorithms)
        match_by_id = {match.algorithm_id: match for match in matches}
        compatible_ids = tuple(
            match.algorithm_id for match in matches if match.compatible
        )
        if project is None:
            compatible_ids = tuple(
                algorithm.metadata.identifier for algorithm in algorithms
            )

        active_case = self._active_case(project)
        self._parameter_cache = {}
        self._parameter_issues = ()
        self._saved_case = active_case
        self._configuration_modified = False
        self._active_case_id = None if active_case is None else active_case.identifier
        self._saved_parameters = (
            {} if active_case is None else dict(active_case.parameters)
        )
        self._compatible_algorithm_ids = compatible_ids
        self._algorithm_matches = match_by_id

        if project is None:
            self._requested_algorithm_id = self.analysis_service.default_algorithm_id
            self._active_algorithm_id = self._requested_algorithm_id
            self._binding_accepted = True
            self._recovery_status = self.RECOVERY_UNBOUND
            self._activate_algorithm(
                self._active_algorithm_id,
                use_cache=False,
                force_rebuild=True,
            )
            self._configure_selector(algorithms, blocked=False)
            self.is_compatible = False
            self._set_state("待匹配", "pending")
            self.algorithm_feedback_label.setText("载入模型后自动检查适用性。")
            self.parameter_panel.setEnabled(True)
            self.accept_current_button.hide()
            return

        if active_case is None:
            # A project without a bound case keeps the configured default as a
            # user-visible preselection. Compatibility is advisory and must not
            # silently replace the user's method choice.
            selected_id = self.analysis_service.default_algorithm_id
            self._requested_algorithm_id = selected_id
            self._active_algorithm_id = selected_id
            self._binding_accepted = True
            self._recovery_status = (
                self.RECOVERY_READY
                if selected_id in compatible_ids
                else self.RECOVERY_INCOMPATIBLE
            )
            self._activate_algorithm(
                selected_id,
                use_cache=False,
                force_rebuild=True,
            )
            self._configure_selector(algorithms, blocked=False)
            self.is_compatible = selected_id in compatible_ids
            if self.is_compatible:
                self._set_state("适用", "pending")
                self.algorithm_feedback_label.setText(
                    "当前重构方法能力范围适用；完成输入校验后确定可解性。"
                    "项目保存时将创建活动工况。"
                )
                self.parameter_panel.setEnabled(True)
            else:
                self._set_state("不可求解", "blocked")
                self.algorithm_feedback_label.setText(
                    self._solvability_feedback(selected_id)
                )
                self.parameter_panel.setEnabled(True)
            self.accept_current_button.hide()
            return

        requested_id = active_case.algorithm_id
        self._requested_algorithm_id = requested_id
        self._active_algorithm_id = requested_id
        self._binding_accepted = False

        if requested_id not in self.analysis_service.registry:
            self._recovery_status = self.RECOVERY_MISSING
            self.is_compatible = False
            self._set_missing_identity(active_case)
            self._show_preserved_parameters()
            self._set_state("插件缺失", "blocked")
            version = getattr(active_case, "algorithm_version", None) or "未知"
            self.algorithm_feedback_label.setText(
                f"项目需要算法 {requested_id}（v{version}），但当前未安装。"
                "原算法 ID 与参数已保留；请选择替代方法后才会改绑。"
            )
            self.accept_current_button.hide()
            self._configure_selector(algorithms, blocked=True)
            return

        algorithm = self.analysis_service.registry.get(requested_id)
        match = match_by_id.get(requested_id)
        if match is None or not match.compatible:
            self._recovery_status = self.RECOVERY_INCOMPATIBLE
            self.is_compatible = False
            self._set_installed_identity(algorithm)
            self._show_preserved_parameters()
            self._set_state("不可求解", "blocked")
            reason = "当前模型不适用于项目保存的重构方法。"
            if match is not None and match.reasons:
                reason = "；".join(match.reasons)
            self.algorithm_feedback_label.setText(
                f"不可求解：{reason} 原工况保持不变；选择其他重构方法后才会改绑。"
            )
            self.accept_current_button.hide()
            self._configure_selector(algorithms, blocked=True)
            return

        try:
            schema = self.analysis_service.registry.parameter_schema(requested_id)
        except (TypeError, ValueError) as exc:
            self._recovery_status = self.RECOVERY_INVALID_SCHEMA
            self.is_compatible = False
            self._set_installed_identity(algorithm)
            self._show_preserved_parameters()
            self._set_state("模式错误", "blocked")
            self.algorithm_feedback_label.setText(
                f"插件参数模式无效：{exc} 原工况未修改。"
            )
            self.accept_current_button.hide()
            self._configure_selector(algorithms, blocked=True)
            return

        report = validate_parameters(schema, self._saved_parameters)
        self._parameter_issues = tuple(report.issues)
        saved_algorithm_version = getattr(active_case, "algorithm_version", None)
        saved_schema_version = getattr(active_case, "parameter_schema_version", None)
        algorithm_version_changed = (
            saved_algorithm_version not in (None, "")
            and saved_algorithm_version != algorithm.metadata.version
        )
        schema_version_changed = (
            saved_schema_version not in (None, "")
            and saved_schema_version != algorithm.metadata.parameter_schema_version
        )

        if algorithm_version_changed or schema_version_changed or not report.is_valid:
            self._recovery_status = (
                self.RECOVERY_SCHEMA
                if schema_version_changed or not report.is_valid
                else self.RECOVERY_VERSION
            )
            self.is_compatible = False
            self._set_installed_identity(algorithm, active_case=active_case)
            self._show_preserved_parameters()
            self._set_state("需确认", "pending")
            details = []
            if algorithm_version_changed:
                details.append(
                    f"算法版本：项目 {saved_algorithm_version} → 当前 {algorithm.metadata.version}"
                )
            if schema_version_changed:
                details.append(
                    "参数模式：项目 "
                    f"{saved_schema_version} → 当前 {algorithm.metadata.parameter_schema_version}"
                )
            details.extend(issue.message for issue in report.issues[:3])
            self.algorithm_feedback_label.setText(
                "；".join(details)
                + "。接受前普通保存不会修改原工况；采用后才切换到当前版本和配置。"
            )
            self.accept_current_button.show()
            self._configure_selector(algorithms, blocked=True)
            return

        self._binding_accepted = True
        self._configuration_modified = False
        self._recovery_status = self.RECOVERY_READY
        self._activate_algorithm(
            requested_id,
            self._saved_parameters,
            use_cache=False,
            force_rebuild=True,
        )
        self._configure_selector(algorithms, blocked=False)
        self.is_compatible = True
        self._set_state("适用", "pending")
        if len(compatible_ids) == 1:
            feedback = "已恢复项目保存的重构方法和参数。"
        else:
            feedback = f"已恢复项目方法；当前模型另有 {len(compatible_ids) - 1} 个适用方法。"
        self.algorithm_feedback_label.setText(feedback)
        self.parameter_panel.setEnabled(True)
        self.accept_current_button.hide()

    def _algorithm_option_details(self, algorithm):
        identifier = algorithm.metadata.identifier
        match = self._algorithm_matches.get(identifier)
        if match is None:
            status = "待分析"
            detail = "载入模型后检查是否可求解。"
        elif match.compatible:
            status = "适用 · 待校验"
            detail = "能力范围适用；选中后结合输入、观测和约束检查可解性。"
        else:
            status = "不可求解"
            detail = match.reason_text or "当前模型不满足该重构方法的能力要求。"
        text = f"{algorithm.metadata.display_name} · {status}"
        tooltip = f"{algorithm.metadata.display_name}\n{status}：{detail}"
        return text, tooltip

    def _solvability_feedback(self, identifier):
        match = self._algorithm_matches.get(identifier)
        if match is None:
            return "尚未取得当前重构方法的可求解性分析结果。"
        if match.compatible:
            return (
                "当前重构方法能力范围适用；"
                "还需结合输入、观测与约束完成可解性检查。"
            )
        reason = match.reason_text or "当前模型不满足该重构方法的能力要求"
        return (
            f"不可求解：{reason}。所选重构方法仍会保留；"
            "修正模型或改选其他方法后再运行。"
        )

    def _add_algorithm_option(self, algorithm):
        text, tooltip = self._algorithm_option_details(algorithm)
        self.algorithm_selector.addItem(text, algorithm.metadata.identifier)
        index = self.algorithm_selector.count() - 1
        self.algorithm_selector.setItemData(
            index,
            tooltip,
            Qt.ItemDataRole.ToolTipRole,
        )

    def _sync_algorithm_selector_tooltip(self):
        index = self.algorithm_selector.currentIndex()
        tooltip = (
            self.algorithm_selector.property("selectionPromptToolTip") or ""
            if index < 0
            else self.algorithm_selector.itemData(index, Qt.ItemDataRole.ToolTipRole)
        )
        self.algorithm_selector.setToolTip(str(tooltip or ""))
        self.algorithm_selector.setProperty(
            "validationBaseToolTip",
            str(tooltip or ""),
        )

    def _configure_selector(self, algorithms, *, blocked):
        algorithms = tuple(algorithms)
        self.algorithm_selector.blockSignals(True)
        self.algorithm_selector.clear()
        # The method card is the source of truth for the active selection.
        # This action-only selector deliberately contains alternatives only.
        if blocked:
            candidates = [
                algorithm
                for algorithm in algorithms
                if algorithm.metadata.identifier != self._requested_algorithm_id
            ]
            label = "替代方法"
            placeholder = "选择替代重构方法…"
            prompt_tooltip = (
                "原项目工况保持不变；明确选择后才会改绑到另一重构方法。"
            )
        else:
            candidates = [
                algorithm
                for algorithm in algorithms
                if algorithm.metadata.identifier != self._active_algorithm_id
            ]
            label = "切换方法"
            placeholder = "选择其他重构方法…"
            prompt_tooltip = (
                f"当前使用 {self.active_algorithm_display_name}；"
                "请选择要切换到的其他已安装方法。"
            )
        self.algorithm_selector_label.setText(label)
        self.algorithm_selector.setAccessibleName(
            "选择替代重构方法" if blocked else "切换重构方法"
        )
        self.algorithm_selector.setAccessibleDescription(prompt_tooltip)
        self.algorithm_selector.setPlaceholderText(placeholder)
        self.algorithm_selector.setProperty(
            "selectionPromptToolTip",
            prompt_tooltip,
        )
        for algorithm in candidates:
            self._add_algorithm_option(algorithm)
        self.algorithm_selector.setCurrentIndex(-1)
        self.algorithm_selector_row.setVisible(bool(candidates))
        self.algorithm_selector.setEnabled(bool(candidates))
        self._sync_algorithm_selector_tooltip()
        self.algorithm_selector.blockSignals(False)

    def _set_missing_identity(self, active_case):
        self.algorithm_name_label.setText("原算法未安装")
        version = getattr(active_case, "algorithm_version", None) or "未知版本"
        schema_version = (
            getattr(active_case, "parameter_schema_version", None) or "未知模式"
        )
        self.algorithm_meta_label.setText(
            f"重构方法 · {active_case.algorithm_id} · v{version} · 参数模式 {schema_version}"
        )
        self.algorithm_name_label.setToolTip(active_case.algorithm_id)

    def _set_installed_identity(self, algorithm, *, active_case=None):
        self.algorithm_name_label.setText(algorithm.metadata.display_name)
        if active_case is None:
            meta = (
                f"重构方法 · 已安装 · v{algorithm.metadata.version} · "
                f"参数模式 {algorithm.metadata.parameter_schema_version}"
            )
        else:
            saved_version = getattr(active_case, "algorithm_version", None) or "未知"
            saved_schema = (
                getattr(active_case, "parameter_schema_version", None) or "未知"
            )
            meta = (
                f"重构方法 · 项目 v{saved_version} / 当前 v{algorithm.metadata.version} · "
                f"参数模式 {saved_schema} / {algorithm.metadata.parameter_schema_version}"
            )
        self.algorithm_meta_label.setText(meta)
        self.algorithm_name_label.setToolTip(algorithm.metadata.description)

    def _clear_parameter_panel(self):
        while self.parameter_grid.count():
            item = self.parameter_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._parameter_editors = {}
        self._parameter_schemas = {}

    def _show_preserved_parameters(self):
        self._clear_parameter_panel()
        count = len(self._saved_parameters)
        label = QLabel(f"已原样保留 {count} 个项目参数；确认恢复或替代前不会写入默认值。")
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        label.setToolTip(repr(self._saved_parameters))
        self.parameter_grid.addWidget(label, 0, 0, 1, 4)
        self.parameter_panel.setEnabled(False)

    def _known_valid_parameters(self, algorithm):
        schema = self.analysis_service.registry.parameter_schema(
            algorithm.metadata.identifier
        )
        properties = dict(schema.get("properties", {}))
        values = {}
        for name, value in self._saved_parameters.items():
            property_schema = properties.get(name)
            if property_schema is None:
                continue
            if self._parameter_value_is_valid(name, property_schema, value):
                values[name] = value
        return values

    def _accept_current_binding(self, _checked=False):
        if self._requested_algorithm_id not in self.analysis_service.registry:
            return
        if self._requested_algorithm_id not in self._compatible_algorithm_ids:
            return
        algorithm = self.analysis_service.registry.get(self._requested_algorithm_id)
        values = self._known_valid_parameters(algorithm)
        previous_status = self._recovery_status
        try:
            self._activate_algorithm(
                self._requested_algorithm_id,
                values,
                use_cache=False,
                force_rebuild=True,
            )
        except Exception as exc:
            self._active_algorithm_id = self._requested_algorithm_id
            self._binding_accepted = False
            self._configuration_modified = False
            self._recovery_status = previous_status
            self.is_compatible = False
            self._set_installed_identity(algorithm, active_case=self._saved_case)
            self._show_preserved_parameters()
            self._set_state("无法采用", "blocked")
            self.algorithm_feedback_label.setText(
                f"当前插件参数界面无法建立：{exc} 原工况保持不变。"
            )
            self.accept_current_button.hide()
            self._configure_selector(
                self.analysis_service.registry.list(),
                blocked=True,
            )
            return
        self._binding_accepted = True
        self._configuration_modified = True
        self._recovery_status = self.RECOVERY_READY
        self.is_compatible = True
        self._set_state("适用", "pending")
        self.algorithm_feedback_label.setText(
            "已明确采用当前插件版本和参数模式；未知旧参数仍会原样保留。"
        )
        self.parameter_panel.setEnabled(True)
        self.accept_current_button.hide()
        self._configure_selector(self.analysis_service.registry.list(), blocked=False)
        self._parameters_changed()

    def _activate_algorithm(
        self,
        identifier,
        parameters=None,
        *,
        use_cache=True,
        force_rebuild=False,
    ):
        if identifier not in self.analysis_service.registry:
            self._active_algorithm_id = identifier
            return
        if self._parameter_editors and self._active_algorithm_id:
            self._parameter_cache[self._active_algorithm_id] = {
                name: self._editor_value(editor)
                for name, editor in self._parameter_editors.items()
            }
        algorithm = self.analysis_service.registry.get(identifier)
        same_algorithm = (
            not force_rebuild
            and identifier == self._active_algorithm_id
            and bool(self._parameter_editors)
        )
        self._active_algorithm_id = identifier
        self._set_installed_identity(algorithm)

        if same_algorithm:
            if parameters is not None:
                self.set_parameter_values(parameters)
            return

        self._clear_parameter_panel()
        schema = self.analysis_service.registry.parameter_schema(identifier)
        properties = dict(schema.get("properties", {}))
        initial_values = (
            dict(self._parameter_cache.get(identifier, {})) if use_cache else {}
        )
        if parameters is not None:
            initial_values.update(parameters)
        for index, (name, field_schema) in enumerate(properties.items()):
            field_schema = dict(field_schema)
            label = QLabel(str(field_schema.get("title", name)))
            label.setObjectName("fieldLabel")
            editor = self._create_parameter_editor(field_schema)
            editor.setAccessibleName(label.text())
            description = str(field_schema.get("description", "")).strip()
            if description:
                label.setToolTip(description)
                editor.setToolTip(description)
                editor.setAccessibleDescription(description)
            editor.setProperty("fieldPath", parameter_field(name))
            label.setBuddy(editor)
            has_value = name in initial_values or "default" in field_schema
            value = initial_values.get(name, field_schema.get("default"))
            if (
                has_value
                and self._parameter_value_is_valid(name, field_schema, value)
            ):
                has_value = self._set_editor_value(editor, value)
            else:
                has_value = False
            editor.setProperty("parameterHasValue", bool(has_value))
            self._connect_parameter_editor(editor)
            row = index // 2
            column = (index % 2) * 2
            self.parameter_grid.addWidget(label, row, column)
            self.parameter_grid.addWidget(editor, row, column + 1)
            self._parameter_editors[name] = editor
            self._parameter_schemas[name] = field_schema

        if not properties:
            empty_label = QLabel("此方法无需额外求解参数。")
            empty_label.setObjectName("hintLabel")
            self.parameter_grid.addWidget(empty_label, 0, 0, 1, 4)
        self._parameter_cache[identifier] = self.parameter_values()

    @staticmethod
    def _parameter_value_is_valid(name, schema, value):
        report = validate_parameters(
            {"type": "object", "properties": {name: dict(schema)}},
            {name: value},
        )
        return report.is_valid

    def _create_parameter_editor(self, schema):
        values = schema.get("enum")
        if values:
            editor = QComboBox()
            if "default" not in schema:
                editor.addItem("— 未设置 —", None)
                editor.setProperty("parameterAllowsUnset", True)
            for value in values:
                editor.addItem(str(value), value)
            return editor
        value_type = schema.get("type", "string")
        if value_type == "integer":
            has_complete_range = "minimum" in schema and "maximum" in schema
            has_default = "default" in schema
            if has_complete_range and has_default:
                minimum = ceil(schema["minimum"])
                maximum = floor(schema["maximum"])
            else:
                minimum = maximum = None
            if (
                minimum is None
                or maximum is None
                or minimum < -(2**31)
                or maximum > 2**31 - 1
            ):
                editor = QLineEdit()
                editor.setProperty("parameterValueType", "integer")
                editor.setProperty("parameterAllowsUnset", not has_default)
                editor.setPlaceholderText("输入整数")
                return editor
            editor = QSpinBox()
            editor.setRange(minimum, maximum)
            editor.setKeyboardTracking(False)
            return editor
        if value_type == "number":
            editor = QLineEdit()
            editor.setProperty("parameterValueType", "number")
            editor.setProperty("parameterAllowsUnset", "default" not in schema)
            editor.setPlaceholderText("输入数值")
            return editor
        if value_type == "boolean":
            if "default" not in schema:
                editor = QComboBox()
                editor.addItem("— 未设置 —", None)
                editor.addItem("是", True)
                editor.addItem("否", False)
                editor.setProperty("parameterAllowsUnset", True)
                return editor
            return QCheckBox()
        editor = QLineEdit()
        editor.setProperty("parameterAllowsUnset", "default" not in schema)
        if "default" not in schema:
            editor.setPlaceholderText("未设置")
        return editor

    def _connect_parameter_editor(self, editor):
        if isinstance(editor, QComboBox):
            editor.currentIndexChanged.connect(
                lambda _index, target=editor: self._parameter_editor_changed(target)
            )
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.valueChanged.connect(
                lambda _value, target=editor: self._parameter_editor_changed(target)
            )
        elif isinstance(editor, QCheckBox):
            editor.toggled.connect(
                lambda _checked, target=editor: self._parameter_editor_changed(target)
            )
        else:
            editor.textChanged.connect(
                lambda _text, target=editor: self._parameter_editor_changed(target)
            )

    def _parameter_editor_changed(self, editor):
        has_value = True
        if editor.property("parameterAllowsUnset"):
            if isinstance(editor, QComboBox):
                has_value = editor.currentData() is not None
            elif isinstance(editor, QLineEdit):
                has_value = bool(editor.text().strip())
        editor.setProperty("parameterHasValue", has_value)
        self._parameters_changed()

    def _editor_value(self, editor):
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        parameter_value_type = editor.property("parameterValueType")
        if parameter_value_type == "integer":
            text = editor.text().strip()
            if text and text.lstrip("+-").isdigit():
                return int(text)
            return text
        if parameter_value_type == "number":
            text = editor.text().strip()
            try:
                value = float(text)
            except ValueError:
                return text
            return value if np.isfinite(value) else text
        return editor.text()

    def _set_editor_value(self, editor, value):
        editor.blockSignals(True)
        try:
            if isinstance(editor, QComboBox):
                index = editor.findData(value)
                if index < 0:
                    index = editor.findText(str(value))
                if index >= 0:
                    editor.setCurrentIndex(index)
                    return True
                return False
            elif isinstance(editor, QSpinBox):
                parsed = int(value)
                if isinstance(value, bool) or parsed < editor.minimum() or parsed > editor.maximum():
                    return False
                editor.setValue(parsed)
                return True
            elif isinstance(editor, QDoubleSpinBox):
                parsed = float(value)
                if not np.isfinite(parsed) or parsed < editor.minimum() or parsed > editor.maximum():
                    return False
                editor.setValue(parsed)
                return True
            elif isinstance(editor, QCheckBox):
                if not isinstance(value, bool):
                    return False
                editor.setChecked(bool(value))
                return True
            else:
                editor.setText(str(value))
                return True
        finally:
            editor.blockSignals(False)

    def _on_algorithm_selected(self, index):
        if index < 0:
            return
        identifier = self.algorithm_selector.itemData(index)
        if not identifier:
            return
        if identifier == self._active_algorithm_id and self._binding_accepted:
            return
        previous_id = self._active_algorithm_id
        previous_requested_id = self._requested_algorithm_id
        previous_status = self._recovery_status
        previous_binding_accepted = self._binding_accepted
        previous_configuration_modified = self._configuration_modified
        previous_is_compatible = self.is_compatible
        previous_parameter_issues = self._parameter_issues
        previous_parameter_values = (
            self.parameter_values() if previous_binding_accepted else {}
        )
        previous_parameter_cache = {
            algorithm_id: dict(values)
            for algorithm_id, values in self._parameter_cache.items()
        }
        previous_state_text = self.algorithm_state_label.text()
        previous_state_style = self.algorithm_state_label.property("state")
        previous_accept_visible = not self.accept_current_button.isHidden()
        previous_panel_enabled = self.parameter_panel.isEnabled()
        try:
            self._activate_algorithm(
                identifier,
                use_cache=True,
                force_rebuild=True,
            )
        except Exception as exc:
            restore_error = None
            self._parameter_cache = previous_parameter_cache
            if (
                previous_binding_accepted
                and previous_id in self.analysis_service.registry
            ):
                try:
                    self._activate_algorithm(
                        previous_id,
                        previous_parameter_values,
                        use_cache=False,
                        force_rebuild=True,
                    )
                except Exception as restore_exc:
                    restore_error = restore_exc

            self._active_algorithm_id = previous_id
            self._requested_algorithm_id = previous_requested_id
            self._parameter_issues = previous_parameter_issues
            self.algorithm_selector.blockSignals(True)
            self.algorithm_selector.setCurrentIndex(-1)
            self.algorithm_selector.blockSignals(False)
            self._sync_algorithm_selector_tooltip()

            if restore_error is None and previous_binding_accepted:
                self._binding_accepted = True
                self._configuration_modified = previous_configuration_modified
                self._recovery_status = previous_status
                self.is_compatible = previous_is_compatible
                self.parameter_panel.setEnabled(previous_panel_enabled)
                self.accept_current_button.setVisible(previous_accept_visible)
                self._set_state(previous_state_text, previous_state_style)
                self.algorithm_feedback_label.setText(
                    f"未能切换到所选插件：{exc} 已恢复原重构方法和参数。"
                )
                return

            self._binding_accepted = False
            self._configuration_modified = False
            self._recovery_status = previous_status
            self.is_compatible = False
            if (
                self._saved_case is not None
                and previous_id not in self.analysis_service.registry
            ):
                self._set_missing_identity(self._saved_case)
            elif previous_id in self.analysis_service.registry:
                previous_algorithm = self.analysis_service.registry.get(previous_id)
                active_case = (
                    self._saved_case
                    if previous_status
                    in {self.RECOVERY_VERSION, self.RECOVERY_SCHEMA}
                    else None
                )
                self._set_installed_identity(
                    previous_algorithm,
                    active_case=active_case,
                )
            self._show_preserved_parameters()
            self.accept_current_button.setVisible(previous_accept_visible)
            self._set_state(previous_state_text, previous_state_style)
            detail = f"替代插件参数界面无法建立：{exc}"
            if restore_error is not None:
                detail += f"；原插件界面也无法恢复：{restore_error}"
            self.algorithm_feedback_label.setText(
                f"{detail}。原工况仍按原样保留。"
            )
            return
        self._requested_algorithm_id = identifier
        self._binding_accepted = True
        self._recovery_status = self.RECOVERY_READY
        self.is_compatible = identifier in self._compatible_algorithm_ids
        self._set_state(
            "适用" if self.is_compatible else "不可求解",
            "pending" if self.is_compatible else "blocked",
        )
        self.algorithm_feedback_label.setText(
            self._solvability_feedback(identifier)
        )
        self.parameter_panel.setEnabled(True)
        self.accept_current_button.hide()
        self._configure_selector(self.analysis_service.registry.list(), blocked=False)
        self._parameters_changed()

    def _parameters_changed(self, *_args):
        self._configuration_modified = True
        self._parameter_cache[self._active_algorithm_id] = self.parameter_values()
        if callable(self.on_change):
            self.on_change()

    def _set_state(self, text, state):
        self.algorithm_state_label.setText(text)
        self.algorithm_state_label.setProperty("state", state)
        style = self.algorithm_state_label.style()
        style.unpolish(self.algorithm_state_label)
        style.polish(self.algorithm_state_label)
        self.algorithm_state_label.update()

    def set_readiness_solvability(self, issues):
        """Refine the method card after full input and observability checks."""
        if (
            not self._binding_accepted
            or self.active_algorithm is None
            or not self.is_compatible
        ):
            return
        error_issues = [
            issue for issue in issues if issue.get("severity", "error") == "error"
        ]
        solvability_issue = next(
            (
                issue
                for issue in error_issues
                if issue.get("field") == "/analysis/solvability"
            ),
            None,
        )
        if solvability_issue is not None:
            self._set_state("不可求解", "blocked")
            message = str(solvability_issue["message"])
            self.algorithm_feedback_label.setText(
                message if "不可求解" in message else f"不可求解：{message}"
            )
        elif error_issues:
            self._set_state("适用", "pending")
            self.algorithm_feedback_label.setText(
                "重构方法能力范围适用；修正当前输入后继续检查可解性。"
            )
        else:
            self._set_state("可求解", "ready")
            if len(self.analysis_service.registry.list()) == 1:
                message = "当前仅安装此方法；能力与可解性检查均已通过。"
            else:
                message = "当前方法的能力与可解性检查均已通过。"
            self.algorithm_feedback_label.setText(message)

    def sync_accessibility(self):
        details = [
            self.algorithm_name_label.text().strip(),
            self.algorithm_state_label.text().strip(),
            self.algorithm_meta_label.text().strip(),
            self.algorithm_feedback_label.text().strip(),
        ]
        self.method_card.setAccessibleDescription(
            "；".join(item for item in details if item)
        )


class ReconstructionMainWindow(QMainWindow):
    def __init__(
        self,
        analysis_service=None,
        *,
        theme_id=None,
        project_library=None,
    ):
        super().__init__()
        self.project_library = project_library or ProjectLibrary()
        self.current_theme_id = apply_application_theme(
            theme_id or current_theme_id(),
            persist=False,
        )
        self.setWindowTitle("iFEM")
        self.resize(1640, 960)
        self.setMinimumSize(1180, 760)
        self.setStyleSheet(
            compose_stylesheet(APP_STYLESHEET + STUDIO_THEME, self.current_theme_id)
        )

        self.current_model = None
        self.current_config = None
        self.current_inputs = None
        self.current_field = None
        self.current_raw_field = None
        self.current_recovered_field = None
        self.current_visual_model = None
        self.current_result_frame = None
        self.current_project_document = None
        self.current_project_path = None
        self.project_dirty = False
        self.results_stale = False
        self._analysis_busy = False
        self.result_sequence = 0
        self.current_view = "stress"
        self._field_colorbar = None
        self._loading_form = False
        self._view_meta_text = ""
        self._readiness_issues = []
        self._is_shut_down = False
        self.analysis_service = analysis_service or get_default_analysis_service()

        self._build_ui()
        self.load_sample_data(initial=True)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 10, 12, 7)
        root_layout.setSpacing(10)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        toolbar = QHBoxLayout(top_bar)
        toolbar.setContentsMargins(12, 9, 10, 9)
        toolbar.setSpacing(7)
        self.top_bar_shadow = QGraphicsDropShadowEffect(top_bar)
        self.top_bar_shadow.setBlurRadius(18)
        self.top_bar_shadow.setOffset(0, 3)
        top_bar.setGraphicsEffect(self.top_bar_shadow)
        self._update_theme_shadow()

        brand_mark = QLabel("iF")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(40, 40)
        toolbar.addWidget(brand_mark)

        identity = QVBoxLayout()
        identity.setSpacing(1)
        app_title = QLabel("iFEM")
        app_title.setObjectName("appTitle")
        self.app_subtitle = QLabel("未命名项目 · 未保存")
        self.app_subtitle.setObjectName("appSubtitle")
        identity.addWidget(app_title)
        identity.addWidget(self.app_subtitle)
        toolbar.addLayout(identity)
        toolbar.addStretch(1)

        command_cluster = QFrame()
        command_cluster.setObjectName("commandCluster")
        command_layout = QHBoxLayout(command_cluster)
        command_layout.setContentsMargins(3, 3, 3, 3)
        command_layout.setSpacing(1)
        project_actions = [
            ("新建", self.new_project, "新建结构项目并进入交互建模（Ctrl+N）", "Ctrl+N"),
            ("打开", self.open_project, "从项目库打开项目（Ctrl+O）", "Ctrl+O"),
            ("保存", self.save_current_project, "保存到 iFEM 项目库（Ctrl+S）", "Ctrl+S"),
        ]
        for text, handler, tooltip, shortcut in project_actions:
            button = QPushButton(text)
            button.setObjectName("topBarButton")
            button.setToolTip(tooltip)
            button.setShortcut(QKeySequence(shortcut))
            button.clicked.connect(handler)
            command_layout.addWidget(button)

        more_menu = QMenu(self)
        save_as_action = more_menu.addAction("另存项目…")
        save_as_action.triggered.connect(self.save_project_as)
        sample_action = more_menu.addAction("载入示例")
        sample_action.triggered.connect(self.load_sample_data)
        more_menu.addSeparator()
        appearance_action = more_menu.addAction("界面风格…")
        appearance_action.setShortcut(QKeySequence("Ctrl+,"))
        appearance_action.setToolTip("切换整个软件的配色风格（Ctrl+,）")
        appearance_action.triggered.connect(self.show_appearance_settings)
        more_menu.addSeparator()
        exchange_action = more_menu.addAction("打开数据交换")
        exchange_action.triggered.connect(self.show_data_exchange)
        refresh_json_action = more_menu.addAction("由表单刷新 JSON")
        refresh_json_action.triggered.connect(self.refresh_json_from_form)
        import_json_action = more_menu.addAction("从 JSON 更新表单")
        import_json_action.triggered.connect(self.import_json_to_form)
        self.more_button = QPushButton("更多")
        self.more_button.setObjectName("topBarButton")
        self.more_button.setToolTip("另存项目、切换界面风格或进行 JSON 数据交换")
        self.more_button.setMenu(more_menu)
        command_layout.addWidget(self.more_button)
        self.appearance_action = appearance_action
        self.save_as_action = QAction("另存项目", self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.setToolTip("以新名称保存到项目库（Ctrl+Shift+S）")
        self.save_as_action.triggered.connect(self.save_project_as)
        self.addAction(self.save_as_action)
        toolbar.addWidget(command_cluster)

        action_divider = QFrame()
        action_divider.setObjectName("toolbarDivider")
        action_divider.setFrameShape(QFrame.Shape.VLine)
        action_divider.setFixedHeight(26)
        toolbar.addWidget(action_divider)

        self.modeler_button = QPushButton("交互建模")
        self.modeler_button.setObjectName("modelerButton")
        self.modeler_button.setToolTip(
            "创建直梁、曲梁或空间梁，并编辑节点、单元、截面与测点（Ctrl+M）"
        )
        self.modeler_button.setShortcut(QKeySequence("Ctrl+M"))
        self.modeler_button.clicked.connect(self.open_interactive_modeler)
        toolbar.addWidget(self.modeler_button)

        self.run_button = QPushButton("运行重构")
        self.run_button.setObjectName("primaryButton")
        self.run_button.setToolTip("校验当前输入并计算梁的重构形状（Ctrl+Return）")
        self.run_button.setShortcut(QKeySequence("Ctrl+Return"))
        self.run_button.setAccessibleName("运行重构")
        self.run_button.setAccessibleDescription(
            "校验模型、测点、约束和算法参数后运行当前重构方案。"
        )
        self.run_button.clicked.connect(self.run_reconstruction)
        toolbar.addWidget(self.run_button)
        self.run_action = QAction("运行重构", self)
        self.run_action.setShortcut(QKeySequence("F5"))
        self.run_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.run_action.triggered.connect(self.run_reconstruction)
        self.addAction(self.run_action)
        root_layout.addWidget(top_bar)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split = main_split
        main_split.setChildrenCollapsible(False)
        main_split.setHandleWidth(8)
        root_layout.addWidget(main_split, 1)

        left_panel = QWidget()
        self.left_panel = left_panel
        left_panel.setMinimumWidth(420)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(9)
        main_split.addWidget(left_panel)

        left_heading = QHBoxLayout()
        left_accent = QFrame()
        left_accent.setObjectName("sectionAccent")
        left_accent.setFixedSize(3, 30)
        left_heading.addWidget(left_accent, 0, Qt.AlignmentFlag.AlignVCenter)
        left_title_box = QVBoxLayout()
        left_title_box.setSpacing(0)
        left_title = QLabel("模型与输入")
        left_title.setObjectName("sectionTitle")
        left_hint = QLabel("组织几何、测点与约束，布置示意在下方同步更新")
        left_hint.setObjectName("sectionHint")
        left_title_box.addWidget(left_title)
        left_title_box.addWidget(left_hint)
        left_heading.addLayout(left_title_box)
        left_heading.addStretch(1)
        self.input_status_label = QPushButton("检查中")
        self.input_status_label.setObjectName("inputBadge")
        self.input_status_label.setProperty("state", "pending")
        self.input_status_label.setToolTip("显示当前模型、测点、约束和分析参数是否可运行")
        self.input_status_label.setAccessibleName("输入就绪状态")
        self.input_status_label.setAccessibleDescription(
            "激活后定位首个输入问题；全部就绪时运行重构。"
        )
        self.input_status_label.clicked.connect(self._activate_input_status)
        left_heading.addWidget(
            self.input_status_label,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        left_layout.addLayout(left_heading)

        left_split = QSplitter(Qt.Orientation.Vertical)
        left_split.setChildrenCollapsible(False)
        left_split.setHandleWidth(8)
        left_layout.addWidget(left_split, 1)

        self.left_tabs = QTabWidget()
        self.left_tabs.setAccessibleName("模型与输入工作区")
        left_split.addWidget(self.left_tabs)
        self._build_left_tabs()

        preview_group = QGroupBox("梁与传感器布置")
        preview_group.setObjectName("workspaceGroup")
        preview_group.setMinimumHeight(150)
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        self.measurement_preview = MeasurementPreviewWidget()
        self.measurement_preview.setMinimumHeight(140)
        self.measurement_preview.setAccessibleName("梁与传感器布置预览")
        self.measurement_preview.setAccessibleDescription(
            "根据当前节点坐标和测点表显示梁、节点与测点位置。"
        )
        preview_layout.addWidget(self.measurement_preview)
        left_split.addWidget(preview_group)
        left_split.setSizes([550, 170])
        left_split.setStretchFactor(0, 3)
        left_split.setStretchFactor(1, 1)
        self.refresh_measurement_preview()

        right_panel = QWidget()
        right_panel.setMinimumWidth(700)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(9)
        main_split.addWidget(right_panel)

        right_heading = QHBoxLayout()
        right_accent = QFrame()
        right_accent.setObjectName("sectionAccent")
        right_accent.setFixedSize(3, 30)
        right_heading.addWidget(right_accent, 0, Qt.AlignmentFlag.AlignVCenter)
        right_title_box = QVBoxLayout()
        right_title_box.setSpacing(0)
        right_title = QLabel("重构与观察")
        right_title.setObjectName("sectionTitle")
        right_hint = QLabel("在形状、应变与应力之间切换，并读取精确结果")
        right_hint.setObjectName("sectionHint")
        right_title_box.addWidget(right_title)
        right_title_box.addWidget(right_hint)
        right_heading.addLayout(right_title_box)
        right_heading.addStretch(1)
        self.run_status_label = QLabel("等待运行")
        self.run_status_label.setObjectName("statusBadge")
        self.run_status_label.setProperty("state", "idle")
        self.run_status_label.setMinimumWidth(168)
        self.run_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_heading.addWidget(self.run_status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        right_layout.addLayout(right_heading)

        analysis_summary = QFrame()
        analysis_summary.setObjectName("analysisSummary")
        analysis_summary_layout = QHBoxLayout(analysis_summary)
        analysis_summary_layout.setContentsMargins(8, 6, 8, 6)
        analysis_summary_layout.setSpacing(0)
        self.analysis_metric_labels = {}
        self.analysis_metric_title_labels = {}
        metric_specs = [
            (
                "solver",
                "重构方法",
                self.analysis_setup.active_algorithm_display_name,
            ),
            ("mesh", "离散模型", "--"),
            ("sensors", "传感配置", "--"),
            ("material", "材料参数", "未设置 E"),
        ]
        for index, (key, name, default_value) in enumerate(metric_specs):
            metric_card = QFrame()
            if index == 0:
                metric_card.setObjectName("metricCardPrimary")
            elif index == len(metric_specs) - 1:
                metric_card.setObjectName("metricCardLast")
            else:
                metric_card.setObjectName("metricCard")
            metric_layout = QVBoxLayout(metric_card)
            metric_layout.setContentsMargins(10, 3, 10, 3)
            metric_layout.setSpacing(0)
            metric_name = QLabel(name)
            metric_name.setObjectName("metricName")
            metric_value = QLabel(default_value)
            metric_value.setObjectName("metricValue")
            metric_layout.addWidget(metric_name)
            metric_layout.addWidget(metric_value)
            self.analysis_metric_title_labels[key] = metric_name
            self.analysis_metric_labels[key] = metric_value
            analysis_summary_layout.addWidget(metric_card, 1)
        right_layout.addWidget(analysis_summary)

        right_split = QSplitter(Qt.Orientation.Vertical)
        self.right_split = right_split
        right_split.setChildrenCollapsible(False)
        right_split.setHandleWidth(8)
        right_layout.addWidget(right_split, 1)

        plot_group = QGroupBox("重构场可视化")
        plot_group.setObjectName("workspaceGroup")
        plot_group_layout = QVBoxLayout(plot_group)
        plot_group_layout.setContentsMargins(10, 12, 10, 10)
        plot_group_layout.setSpacing(8)
        right_split.addWidget(plot_group)

        view_toolbar = QFrame()
        view_toolbar.setObjectName("viewToolbar")
        self.view_toolbar = view_toolbar
        view_toolbar_layout = QHBoxLayout(view_toolbar)
        view_toolbar_layout.setContentsMargins(8, 5, 8, 5)
        view_toolbar_layout.setSpacing(4)
        view_label = QLabel("结果")
        view_label.setObjectName("fieldLabel")
        view_toolbar_layout.addWidget(view_label)

        self.view_button_group = QButtonGroup(self)
        self.view_button_group.setExclusive(True)
        self.view_buttons = {}
        for mode, text, tooltip in [
            ("shape", "形态", "查看重构后的几何形态"),
            ("strain", "应变", "查看重构后的轴向应变云图"),
            ("stress", "应力", "查看重构后的轴向应力云图"),
        ]:
            button = QPushButton(text)
            button.setObjectName("viewModeButton")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, selected=mode: self._switch_view(selected))
            self.view_button_group.addButton(button)
            self.view_buttons[mode] = button
            view_toolbar_layout.addWidget(button)
        self.view_buttons["stress"].setChecked(True)
        self.view_shortcut_actions = []
        for index, mode in enumerate(("shape", "strain", "stress"), start=1):
            shortcut = f"Ctrl+{index}"
            action = QAction(f"切换到{self.view_buttons[mode].text()}结果", self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(
                lambda _checked=False, selected=mode: self._switch_view(selected)
            )
            self.addAction(action)
            self.view_shortcut_actions.append(action)
            self.view_buttons[mode].setToolTip(
                f"{self.view_buttons[mode].toolTip()}（{shortcut}）"
            )

        toolbar_divider = QFrame()
        toolbar_divider.setObjectName("toolbarDivider")
        toolbar_divider.setFrameShape(QFrame.Shape.VLine)
        view_toolbar_layout.addWidget(toolbar_divider)
        display_label = QLabel("空间")
        display_label.setObjectName("fieldLabel")
        view_toolbar_layout.addWidget(display_label)
        self.display_button_group = QButtonGroup(self)
        self.display_button_group.setExclusive(True)
        self.display_buttons = {}
        for index, (key, text) in enumerate([("2d", "2D"), ("3d", "3D")]):
            button = QPushButton(text)
            button.setObjectName("displayModeButton")
            button.setCheckable(True)
            button.setToolTip(
                "二维截面场与重构曲线"
                if key == "2d"
                else "鼠标拖拽旋转、滚轮缩放，并可切换标准视角"
            )
            button.clicked.connect(
                lambda _checked=False, selected=index: self._switch_visualization_space(selected)
            )
            self.display_button_group.addButton(button)
            self.display_buttons[key] = button
            view_toolbar_layout.addWidget(button)
        self.display_buttons["2d"].setChecked(True)

        scale_divider = QFrame()
        scale_divider.setObjectName("toolbarDivider")
        scale_divider.setFrameShape(QFrame.Shape.VLine)
        view_toolbar_layout.addWidget(scale_divider)
        scale_label = QLabel("比例")
        scale_label.setObjectName("fieldLabel")
        view_toolbar_layout.addWidget(scale_label)
        self.scale_button_group = QButtonGroup(self)
        self.scale_button_group.setExclusive(True)
        self.scale_buttons = {}
        for mode, text, tooltip in [
            ("fit", "协调", "增强厚度并自动协调坐标比例，便于观察应力梯度"),
            ("true", "1:1", "使用等比例坐标轴和真实梁厚度，不进行视觉夸大"),
        ]:
            button = QPushButton(text)
            button.setObjectName("displayModeButton")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.clicked.connect(
                lambda _checked=False, selected=mode: self._switch_scale_mode(selected)
            )
            self.scale_button_group.addButton(button)
            self.scale_buttons[mode] = button
            view_toolbar_layout.addWidget(button)
        self.scale_buttons["fit"].setChecked(True)

        view_toolbar_layout.addStretch(1)
        self.display_settings_button = QPushButton("显示设置")
        self.display_settings_button.setObjectName("displayModeButton")
        self.display_settings_button.setCheckable(True)
        self.display_settings_button.setToolTip(
            "展开图标题、坐标范围、场连续化和标注等显示选项"
        )
        view_toolbar_layout.addWidget(self.display_settings_button)
        self.focus_mode_button = QPushButton("专注")
        self.focus_mode_button.setObjectName("displayModeButton")
        self.focus_mode_button.setCheckable(True)
        self.focus_mode_button.setToolTip(
            "隐藏输入区和结果表格，仅保留可视化视口；再次点击恢复"
        )
        self.focus_mode_button.toggled.connect(self._toggle_focus_mode)
        view_toolbar_layout.addWidget(self.focus_mode_button)
        plot_group_layout.addWidget(view_toolbar)

        self.display_settings_panel = self._build_display_settings_panel()
        self.display_settings_panel.setVisible(False)
        self.display_settings_button.toggled.connect(
            self.display_settings_panel.setVisible
        )
        plot_group_layout.addWidget(self.display_settings_panel)

        plot_meta_bar = QFrame()
        plot_meta_bar.setObjectName("plotMetaBar")
        plot_meta_layout = QHBoxLayout(plot_meta_bar)
        plot_meta_layout.setContentsMargins(8, 0, 8, 5)
        plot_meta_layout.setSpacing(12)
        self.view_context_label = QLabel("二维结果 · 轴向应力")
        self.view_context_label.setObjectName("plotContext")
        plot_meta_layout.addWidget(self.view_context_label)
        self.result_freshness_label = QLabel("结果已过期")
        self.result_freshness_label.setObjectName("resultFreshness")
        self.result_freshness_label.setProperty("state", "stale")
        self.result_freshness_label.setToolTip(
            "输入已修改；当前图表仍保留上一次计算结果，请重新运行后再用于判断。"
        )
        self.result_freshness_label.setAccessibleName("结果已过期")
        self.result_freshness_label.hide()
        plot_meta_layout.addWidget(self.result_freshness_label)
        plot_meta_layout.addStretch(1)
        self.view_meta_label = QLabel()
        self.view_meta_label.setObjectName("viewMeta")
        self.view_meta_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.view_meta_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        plot_meta_layout.addWidget(self.view_meta_label, 1)
        plot_group_layout.addWidget(plot_meta_bar)
        self._set_view_meta("重构后优先显示应力场 · 未设置 E 时显示应变场")

        canvas_container = QFrame()
        canvas_container.setObjectName("plotCanvas")
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(6, 6, 6, 6)
        self.figure = Figure(figsize=(9.5, 6.0), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setAccessibleName("二维重构结果图")
        self.canvas.setAccessibleDescription(
            "显示重构形态、轴向应变或轴向应力；结果数值可在下方表格读取。"
        )
        canvas_layout.addWidget(self.canvas)

        self.visualization_stack = QStackedWidget()
        self.visualization_stack.setAccessibleName("结果可视化视口")
        self.visualization_stack.addWidget(canvas_container)
        self.structure_3d_view = Structure3DView()
        self.visualization_stack.addWidget(self.structure_3d_view)

        self.plot_content_stack = QStackedWidget()
        self.plot_content_stack.setObjectName("plotContentStack")
        self.analysis_empty_state = AnalysisEmptyState()
        self.analysis_empty_state.action_requested.connect(
            self._activate_empty_state_action
        )
        self.plot_content_stack.addWidget(self.analysis_empty_state)
        self.plot_content_stack.addWidget(self.visualization_stack)
        plot_group_layout.addWidget(self.plot_content_stack, 1)

        result_group = QGroupBox("结果数据")
        self.result_group = result_group
        result_group.setObjectName("workspaceGroup")
        result_group.setMinimumHeight(145)
        result_layout = QVBoxLayout(result_group)
        result_layout.setContentsMargins(6, 8, 6, 5)
        right_split.addWidget(result_group)
        right_split.setSizes([700, 155])
        right_split.setStretchFactor(0, 4)
        right_split.setStretchFactor(1, 1)

        self.result_tabs = QTabWidget()
        self.result_tabs.setObjectName("resultTabs")
        self.result_tabs.setAccessibleName("重构结果数据")
        result_layout.addWidget(self.result_tabs)

        self.node_result_table = ReadOnlyTable(
            columns=["节点", "x坐标", "u位移", "v位移", "转角phi"],
            headings=["节点", "x坐标", "u位移", "v位移", "转角phi"],
            accessible_name="节点重构结果表",
        )
        self.query_result_table = ReadOnlyTable(
            columns=["序号", "x", "u", "v"],
            headings=["序号", "x坐标", "u位移", "v位移"],
            accessible_name="查询点位移结果表",
        )
        self.compare_result_table = ReadOnlyTable(
            columns=["序号", "标签", "x", "u_实测", "v_实测", "u_重构", "v_重构", "Δu", "Δv"],
            headings=["序号", "标签", "x坐标", "u实测", "v实测", "u重构", "v重构", "Δu", "Δv"],
            stretch_columns=False,
            accessible_name="实测与重构对比表",
        )
        self.field_result_table = ReadOnlyTable(
            columns=["序号", "x", "上表面应变", "下表面应变", "上表面应力", "下表面应力"],
            headings=["序号", "x坐标", "上表面应变 με", "下表面应变 με", "上表面应力 MPa", "下表面应力 MPa"],
            stretch_columns=False,
            accessible_name="截面应变应力场结果表",
        )
        self.message_text = QTextEdit()
        self.message_text.setReadOnly(True)
        self.message_text.setAccessibleName("运行信息")

        self.node_result_tab_index = self.result_tabs.addTab(
            self.node_result_table, "节点结果"
        )
        self.query_result_tab_index = self.result_tabs.addTab(
            self.query_result_table, "查询结果"
        )
        self.compare_result_tab_index = self.result_tabs.addTab(
            self.compare_result_table, "实测对比"
        )
        self.field_result_tab_index = self.result_tabs.addTab(self.field_result_table, "截面场")
        self.message_result_tab_index = self.result_tabs.addTab(
            self.message_text, "运行信息"
        )

        main_split.setSizes([520, 1100])
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 2)

        self._connect_change_tracking()
        self._render_empty_plot()
        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.showMessage("就绪")
        units_status = QLabel("SI 单位")
        units_status.setObjectName("statusMeta")
        units_status.setToolTip("项目内部统一使用国际单位制")
        compute_status = QLabel("本地计算")
        compute_status.setObjectName("statusMeta")
        compute_status.setToolTip("当前算法在本机进程中运行")
        status_bar.addPermanentWidget(units_status)
        status_bar.addPermanentWidget(compute_status)

    @staticmethod
    def _create_scroll_page():
        page = QWidget()
        page.setObjectName("tabPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("tabScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("tabContent")
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page, content

    def _build_left_tabs(self):
        basic_page, basic_tab = self._create_scroll_page()
        measure_page, measure_tab = self._create_scroll_page()
        boundary_page, boundary_tab = self._create_scroll_page()
        optional_page, optional_tab = self._create_scroll_page()
        json_tab = QWidget()

        self.left_tab_names = ("模型", "测点", "约束", "对比", "高级")
        self.left_tabs.addTab(basic_page, self.left_tab_names[0])
        self.left_tabs.addTab(measure_page, self.left_tab_names[1])
        self.left_tabs.addTab(boundary_page, self.left_tab_names[2])
        self.left_tabs.addTab(optional_page, self.left_tab_names[3])
        self.left_tabs.addTab(json_tab, self.left_tab_names[4])
        self._left_tab_tooltips = (
            "设置模型与材料，选择重构方法并检查是否可解",
            "配置应变测点的位置、数据和局部积分区间",
            "设置节点位移与转角约束",
            "录入实测位移，用于重构结果校核",
            "项目 JSON 数据检查与交换",
        )
        for index, tooltip in enumerate(self._left_tab_tooltips):
            self.left_tabs.setTabToolTip(index, f"{tooltip}（Alt+{index + 1}）")

        self.input_tab_actions = []
        for index, name in enumerate(self.left_tab_names):
            action = QAction(f"打开{name}输入页", self)
            action.setShortcut(QKeySequence(f"Alt+{index + 1}"))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(
                lambda _checked=False, selected=index: self._focus_input_tab(selected)
            )
            self.addAction(action)
            self.input_tab_actions.append(action)

        self._build_basic_tab(basic_tab)
        self._build_measure_tab(measure_tab)
        self._build_boundary_tab(boundary_tab)
        self._build_optional_tab(optional_tab)
        self._build_json_tab(json_tab)

    def _build_basic_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        model_group = QGroupBox("模型参数")
        model_group.setObjectName("formSection")
        layout.addWidget(model_group)
        grid = QGridLayout(model_group)
        grid.setContentsMargins(12, 16, 12, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.node_x_edit = QLineEdit()
        self.thickness_edit = QLineEdit()
        self.elastic_modulus_edit = QLineEdit()
        self.title_edit = QLineEdit("二维梁重构形态")
        self.query_xs_edit = QLineEdit()
        self.y_min_edit = QLineEdit()
        self.y_max_edit = QLineEdit()
        self.thickness_scale_combo = QComboBox()
        self.thickness_scale_combo.setEditable(True)
        self.thickness_scale_combo.addItem("自动增强", "auto")
        self.thickness_scale_combo.addItem("真实比例 ×1", 1.0)
        self.thickness_scale_combo.addItem("显示 ×10", 10.0)
        self.thickness_scale_combo.addItem("显示 ×100", 100.0)
        self.thickness_scale_combo.addItem("显示 ×1000", 1000.0)
        self.thickness_scale_combo.setToolTip("可选择预设倍率，也可直接输入大于 0 的数值")
        self.field_representation_combo = QComboBox()
        self.field_representation_combo.addItem("节点平均连续化", "nodal_average")
        self.field_representation_combo.addItem("原始单元场", "raw")
        self.field_representation_combo.setToolTip(
            "连续化仅用于后处理显示；原始单元场保留单元边界两侧的真实离散跳变"
        )
        self.show_original_check = QCheckBox("原始中性层")
        self.show_original_check.setChecked(True)
        self.show_nodes_check = QCheckBox("重构节点")
        self.show_nodes_check.setChecked(True)
        self.equal_axis_check = QCheckBox("等比例坐标轴")
        self.annotate_points_check = QCheckBox("实测/重构标注")
        self.connect_pairs_check = QCheckBox("差异连线")
        self.connect_pairs_check.setChecked(True)

        for line_edit in [
            self.node_x_edit,
            self.thickness_edit,
            self.elastic_modulus_edit,
            self.title_edit,
            self.query_xs_edit,
            self.y_min_edit,
            self.y_max_edit,
        ]:
            line_edit.setClearButtonEnabled(True)

        self.node_x_edit.setPlaceholderText("例如：0, 1, 2, 3")
        self.thickness_edit.setPlaceholderText("例如：0.0016")
        self.elastic_modulus_edit.setPlaceholderText("可选，例如：206")
        self.query_xs_edit.setPlaceholderText("可选，例如：0.5, 1.5, 2.5")
        self.y_min_edit.setPlaceholderText("自动")
        self.y_max_edit.setPlaceholderText("自动")

        node_label = QLabel("节点坐标 node_x")
        node_label.setObjectName("fieldLabel")
        node_label.setBuddy(self.node_x_edit)
        thickness_label = QLabel("梁厚度")
        thickness_label.setObjectName("fieldLabel")
        thickness_label.setBuddy(self.thickness_edit)
        elastic_modulus_label = QLabel("弹性模量 E (GPa)")
        elastic_modulus_label.setObjectName("fieldLabel")
        elastic_modulus_label.setBuddy(self.elastic_modulus_edit)
        self.node_x_edit.setAccessibleName("节点坐标")
        self.thickness_edit.setAccessibleName("梁厚度")
        self.elastic_modulus_edit.setAccessibleName("弹性模量")
        self.query_xs_edit.setAccessibleName("位移查询点")

        grid.addWidget(node_label, 0, 0)
        grid.addWidget(self.node_x_edit, 0, 1, 1, 3)
        grid.addWidget(thickness_label, 1, 0)
        grid.addWidget(self.thickness_edit, 1, 1, 1, 3)
        grid.addWidget(elastic_modulus_label, 2, 0)
        grid.addWidget(self.elastic_modulus_edit, 2, 1, 1, 3)

        model_hint = QLabel(
            "弹性模量仅用于 σ=Eε 应力后处理；节点坐标使用英文逗号分隔。"
        )
        model_hint.setObjectName("hintLabel")
        model_hint.setWordWrap(True)
        grid.addWidget(model_hint, 3, 0, 1, 4)

        analysis_group = QGroupBox("重构方法与可解性")
        analysis_group.setObjectName("formSection")
        analysis_layout = QVBoxLayout(analysis_group)
        analysis_layout.setContentsMargins(12, 16, 12, 12)
        analysis_layout.setSpacing(9)
        self.analysis_setup = AnalysisSetupWidget(
            self.analysis_service,
            on_change=self._on_analysis_setup_changed,
        )
        analysis_layout.addWidget(self.analysis_setup)
        query_row = QHBoxLayout()
        query_row.setSpacing(10)
        query_label = QLabel("位移查询点")
        query_label.setObjectName("fieldLabel")
        query_label.setBuddy(self.query_xs_edit)
        query_row.addWidget(query_label)
        query_row.addWidget(self.query_xs_edit, 1)
        analysis_layout.addLayout(query_row)
        layout.addWidget(analysis_group)

        layout.addStretch(1)

    def _build_display_settings_panel(self):
        panel = QFrame()
        panel.setObjectName("displaySettingsPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(7)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        title_label = QLabel("图标题")
        title_label.setObjectName("fieldLabel")
        field_label = QLabel("场显示")
        field_label.setObjectName("fieldLabel")
        y_range_label = QLabel("Y 轴范围")
        y_range_label.setObjectName("fieldLabel")
        y_separator = QLabel("至")
        y_separator.setObjectName("hintLabel")
        y_separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thickness_label = QLabel("厚度显示")
        thickness_label.setObjectName("fieldLabel")

        self.title_edit.setToolTip("设置二维结果图标题；留空时使用默认标题")
        self.field_representation_combo.setToolTip(
            "节点平均用于连续显示；原始单元场保留单元边界跳变"
        )
        self.y_min_edit.setToolTip("留空时自动确定 Y 轴范围；手动设置时需同时填写最大值")
        self.y_max_edit.setToolTip("留空时自动确定 Y 轴范围；手动设置时需同时填写最小值")
        self.thickness_scale_combo.setToolTip(
            "只改变梁截面轮廓的显示倍率，不改变模型或计算结果"
        )

        grid.addWidget(title_label, 0, 0)
        grid.addWidget(self.title_edit, 0, 1, 1, 3)
        grid.addWidget(field_label, 0, 4)
        grid.addWidget(self.field_representation_combo, 0, 5)
        grid.addWidget(y_range_label, 1, 0)
        grid.addWidget(self.y_min_edit, 1, 1)
        grid.addWidget(y_separator, 1, 2)
        grid.addWidget(self.y_max_edit, 1, 3)
        grid.addWidget(thickness_label, 1, 4)
        grid.addWidget(self.thickness_scale_combo, 1, 5)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)
        panel_layout.addLayout(grid)

        options = QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(14)
        option_tooltips = {
            self.show_original_check: "在结果图中显示变形前的中性层参考线",
            self.show_nodes_check: "显示重构后的有限元节点",
            self.equal_axis_check: "使 X、Y 坐标使用相同比例",
            self.annotate_points_check: "显示实测点和对应重构点的文字标注",
            self.connect_pairs_check: "使用连线表示实测点与重构点之间的差异",
        }
        for checkbox, tooltip in option_tooltips.items():
            checkbox.setToolTip(tooltip)
            options.addWidget(checkbox)
        options.addStretch(1)
        panel_layout.addLayout(options)
        return panel

    def _build_measure_tab(self, parent):
        layout = QVBoxLayout(parent)
        specs = [
            {
                "key": "element",
                "label": "梁段",
                "table_label": "梁段",
                "table_align": "right",
                "placeholder": "从 0 开始",
            },
            {
                "key": "x",
                "label": "局部位置 x",
                "table_label": "位置",
                "table_align": "right",
                "placeholder": "测点位置",
            },
            {
                "key": "surface",
                "label": "表面",
                "table_label": "表面",
                "table_align": "center",
                "table_display": {
                    "top": "上",
                    "bot": "下",
                    "上": "上",
                    "下": "下",
                    "": "-",
                },
                "choices": ["", "top", "bot", "上", "下"],
                "tooltip": "选择 top/上表示上表面，bot/下表示下表面；也可留空后填写 y",
            },
            {"key": "y", "label": "截面 y", "placeholder": "与表面二选一"},
            {
                "key": "strain",
                "label": "应变 ε",
                "table_label": "应变",
                "table_align": "right",
                "placeholder": "例如：1.5e-4",
            },
            {"key": "weight", "label": "权重", "placeholder": "留空默认为 1"},
            {
                "key": "zone_a",
                "label": "局部积分起点 a",
                "placeholder": "积分起点",
                "tooltip": "用户自选的单元局部积分起点，必须位于当前梁段内",
            },
            {
                "key": "zone_b",
                "label": "局部积分终点 b",
                "placeholder": "积分终点",
                "tooltip": "用户自选的单元局部积分终点，必须大于起点且位于当前梁段内",
            },
        ]
        self.measurement_editor = EditableTable(
            "传感器配置",
            specs,
            on_change=self._on_measurements_changed,
            form_columns=2,
            stretch_columns=False,
            table_columns=("element", "x", "surface", "strain"),
            form_sections=(
                ("位置", ("element", "x", "surface", "y")),
                ("数据", ("strain", "weight")),
                ("局部积分", ("zone_a", "zone_b")),
            ),
            table_min_height=176,
            record_noun="个测点",
            header_action=("模型布点", self.open_interactive_modeler),
        )
        self.measurement_editor.setObjectName("sensorEditor")
        self.measurement_editor.add_button.setText("新增测点")
        self.measurement_editor.update_button.setText("保存修改")
        self.measurement_editor.delete_button.setText("删除")
        self.measurement_editor.clear_button.setText("清空")
        layout.addWidget(self.measurement_editor)

    def _build_boundary_tab(self, parent):
        layout = QVBoxLayout(parent)
        specs = [
            {"key": "node", "label": "节点号"},
            {"key": "dof", "label": "自由度", "choices": ["u", "v", "phi"]},
            {"key": "value", "label": "约束值"},
        ]
        self.boundary_editor = EditableTable(
            "位移约束",
            specs,
            on_change=self._mark_results_stale,
            description="按节点设置 u、v 或 phi；程序会自动换算为全局自由度编号。",
            form_columns=2,
        )
        layout.addWidget(self.boundary_editor)

    def _build_optional_tab(self, parent):
        layout = QVBoxLayout(parent)
        specs = [
            {"key": "label", "label": "标签"},
            {"key": "x", "label": "x"},
            {"key": "u", "label": "u实测"},
            {"key": "v", "label": "v实测"},
        ]
        self.true_point_editor = EditableTable(
            "实测位移对比点",
            specs,
            on_change=self._mark_results_stale,
            description="可选：输入已知位移，用于计算重构值与实测值的差异。",
            form_columns=2,
        )
        layout.addWidget(self.true_point_editor)

    def _build_json_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(10, 10, 10, 10)
        json_hint = QLabel("可在此检查、修改或粘贴完整配置；使用顶部按钮完成表单与 JSON 的双向转换。")
        json_hint.setObjectName("hintLabel")
        json_hint.setWordWrap(True)
        layout.addWidget(json_hint)
        self.json_text = QPlainTextEdit()
        self.json_text.setObjectName("jsonEditor")
        self.json_text.setMinimumHeight(300)
        layout.addWidget(self.json_text)

    def _connect_change_tracking(self):
        self.node_x_edit.textChanged.connect(self._on_node_x_changed)
        for line_edit in [
            self.thickness_edit,
            self.elastic_modulus_edit,
            self.query_xs_edit,
        ]:
            line_edit.textChanged.connect(self._mark_results_stale)

        for line_edit in [self.title_edit, self.y_min_edit, self.y_max_edit]:
            line_edit.textChanged.connect(self._on_plot_settings_changed)

        self.thickness_scale_combo.currentTextChanged.connect(self._on_plot_settings_changed)
        self.field_representation_combo.currentTextChanged.connect(self._on_plot_settings_changed)

        for checkbox in [
            self.show_original_check,
            self.show_nodes_check,
            self.equal_axis_check,
            self.annotate_points_check,
            self.connect_pairs_check,
        ]:
            checkbox.toggled.connect(self._on_plot_settings_changed)

    def _on_node_x_changed(self, *_args):
        self.refresh_measurement_preview()
        self._mark_results_stale()

    def _on_measurements_changed(self):
        self.refresh_measurement_preview()
        self._mark_results_stale()

    def _on_analysis_setup_changed(self):
        self._sync_analysis_parameter_controls()
        if hasattr(self, "analysis_metric_labels"):
            self.analysis_metric_labels["solver"].setText(
                self.analysis_setup.active_algorithm_display_name
            )
        if self.current_project_document is not None:
            config = None
            if not self.analysis_setup.should_preserve_saved_case:
                try:
                    config = self._build_form_config(require_measurements=False)
                except (KeyError, TypeError, ValueError):
                    config = None
            self.current_project_document = self._apply_analysis_setup_to_project(
                self.current_project_document,
                config=config,
            )
        self._mark_results_stale()

    def _sync_analysis_parameter_controls(self):
        blocked = self.analysis_setup.should_preserve_saved_case
        message = (
            "当前插件绑定尚未恢复；这些分析参数按原工况不透明保留，"
            "明确采用当前插件或替代算法后才可编辑。"
        )
        for widget in (self.query_xs_edit, self.true_point_editor):
            widget.setEnabled(not blocked)
            widget.setToolTip(message if blocked else "")

    def _on_plot_settings_changed(self, *_args):
        if self._loading_form:
            return
        self._set_project_dirty(True)
        try:
            plot_options = self._collect_plot_options()
        except (TypeError, ValueError):
            self._refresh_input_readiness()
            return
        if self.current_project_document is not None:
            self.current_project_document = self._apply_view_state_to_project(
                self.current_project_document,
                plot_options,
            )
        self._sync_scale_buttons(plot_options)
        if self.current_inputs is not None:
            self.current_inputs["plot_options"] = plot_options
            if self.current_config is not None:
                self.current_config["plot_options"] = dict(plot_options)
            self._select_active_field()
            self._fill_field_result_table()
            self._render_current_view()
        self._refresh_input_readiness()

    def _mark_results_stale(self, *_args):
        if self._loading_form or not hasattr(self, "run_status_label"):
            return
        self._set_project_dirty(True)
        if self.current_model is None:
            self._set_run_status("参数待运行", "idle")
            self._set_result_freshness(False)
        else:
            self._set_run_status("参数已修改 · 请重新运行", "stale")
            self._set_result_freshness(True)
        self._refresh_input_readiness()

    @staticmethod
    def _set_validation_state(widget, state="", message=""):
        if widget is None:
            return
        base_tooltip = widget.property("validationBaseToolTip")
        if base_tooltip is None:
            base_tooltip = widget.toolTip()
            widget.setProperty("validationBaseToolTip", base_tooltip)
        widget.setProperty("validationState", state)
        widget.setToolTip(message or str(base_tooltip or ""))
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _readiness_issue_target(self, field_path=None, message=""):
        field_path = str(field_path or "")
        if field_path.startswith("/analysis/"):
            return 0, self.analysis_setup.field_target(field_path) or self.analysis_setup
        if field_path == "/model/node_x":
            return 0, self.node_x_edit
        if field_path.startswith("/sections/") and field_path.endswith("/thickness"):
            return 0, self.thickness_edit
        if field_path.startswith("/materials/") and field_path.endswith(
            "/elastic_modulus"
        ):
            return 0, self.elastic_modulus_edit
        if field_path == "/view_state/thickness_scale":
            return 0, self.thickness_scale_combo
        if field_path in {"/view_state/y_limits", "/view_state/y_limits/0"}:
            return 0, self.y_min_edit
        if field_path == "/view_state/y_limits/1":
            return 0, self.y_max_edit
        if field_path.startswith("/view_state/"):
            return 0, self.display_settings_button
        if field_path.startswith(("/measurements/", "/sensors/")) or field_path in {
            "/measurements",
            "/sensors",
        }:
            return 1, self.measurement_editor
        if field_path.startswith("/boundary_conditions/") or field_path == "/boundary_conditions":
            return 2, self.boundary_editor
        if field_path.startswith("/true_points/") or field_path == "/true_points":
            return 3, self.true_point_editor
        if field_path.startswith("/data_exchange/"):
            return 4, self.json_text
        if field_path.startswith("/model/"):
            return 0, self.analysis_setup

        # Compatibility path for third-party plugins that have not yet attached
        # a field. New built-in validation never depends on translated text.
        text = str(message)
        if "厚度显示倍率" in text:
            return 0, self.thickness_scale_combo
        if "Y 轴" in text or "Y轴" in text:
            return 0, self.y_min_edit if "最小" in text else self.y_max_edit
        if "plot_options" in text or "显示" in text:
            return 0, self.display_settings_button
        if "node_x" in text or "节点" in text:
            return 0, self.node_x_edit
        if "thickness" in text or "厚度" in text:
            return 0, self.thickness_edit
        if "弹性模量" in text or "elastic_modulus" in text:
            return 0, self.elastic_modulus_edit
        if "查询" in text or "query_xs" in text:
            return 0, self.query_xs_edit
        if "测量" in text or "measurement" in text or "surface" in text or "zone" in text:
            return 1, self.measurement_editor
        if "边界" in text or "自由度" in text:
            return 2, self.boundary_editor
        if "实测" in text or "true_points" in text:
            return 3, self.true_point_editor
        return 0, self.analysis_setup

    def _update_readiness_tabs(self, tab_counts, messages):
        for index, name in enumerate(self.left_tab_names):
            count = int(tab_counts.get(index, 0))
            tab_text = name if count == 0 else f"{name} · {count}"
            self.left_tabs.setTabText(index, tab_text)
            if count:
                self.left_tabs.setTabToolTip(index, "\n".join(messages[index]))
            else:
                self.left_tabs.setTabToolTip(
                    index,
                    f"{self._left_tab_tooltips[index]}（Alt+{index + 1}）",
                )

    def _focus_input_tab(self, index):
        if not 0 <= int(index) < self.left_tabs.count():
            return
        index = int(index)
        self.left_tabs.setCurrentIndex(index)
        targets = (
            self.node_x_edit,
            self.measurement_editor.table,
            self.boundary_editor.table,
            self.true_point_editor.table,
            self.json_text,
        )
        target = targets[index]
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _activate_input_status(self):
        if self._analysis_busy:
            return
        if self._readiness_issues:
            self._focus_first_input_issue()
            return
        self.run_reconstruction()

    def _activate_empty_state_action(self):
        self._activate_input_status()

    def _sync_empty_state(self, *, waiting_for_algorithm=False):
        if not hasattr(self, "analysis_empty_state"):
            return
        self.analysis_empty_state.set_readiness(
            self._readiness_issues,
            waiting_for_algorithm=waiting_for_algorithm,
        )

    def _focus_first_input_issue(self):
        if not self._readiness_issues:
            return
        issue = self._readiness_issues[0]
        tab_index = issue["tab"]
        widget = issue.get("widget")
        self.left_tabs.setCurrentIndex(tab_index)
        if widget in {
            self.y_min_edit,
            self.y_max_edit,
            self.thickness_scale_combo,
        }:
            self.display_settings_button.setChecked(True)
        if widget is not None:
            if isinstance(widget, EditableTable):
                widget.focus_validation_issue(
                    issue["message"],
                    field_path=issue.get("field"),
                )
            else:
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
            if isinstance(widget, QLineEdit):
                widget.selectAll()
        self.statusBar().showMessage(issue["message"], 7000)

    def _refresh_input_readiness(self):
        """Refresh non-modal validation and the single source of run-button state."""
        if not hasattr(self, "left_tabs") or not hasattr(self, "input_status_label"):
            return False
        for widget in (
            self.node_x_edit,
            self.thickness_edit,
            self.elastic_modulus_edit,
            self.query_xs_edit,
            self.y_min_edit,
            self.y_max_edit,
            self.thickness_scale_combo,
            self.display_settings_button,
            self.analysis_setup.method_card,
            self.analysis_setup.algorithm_selector,
        ):
            self._set_validation_state(widget)
        for editor in (
            self.measurement_editor,
            self.boundary_editor,
            self.true_point_editor,
        ):
            editor.set_validation_state()
        for editor in self.analysis_setup._parameter_editors.values():
            self._set_validation_state(editor)

        issues = []
        tab_counts = {index: 0 for index in range(len(self.left_tab_names))}
        tab_messages = {index: [] for index in range(len(self.left_tab_names))}

        def add_issue(value, *, field=None, severity="error"):
            if isinstance(value, ValidationIssue):
                message = value.message
                field_path = value.field
                issue_severity = value.severity
            else:
                message = str(value)
                field_path = field or getattr(value, "field", None)
                issue_severity = severity
            if issue_severity != "error":
                return
            tab_index, widget = self._readiness_issue_target(
                field_path,
                message,
            )
            issue = {
                "message": str(message),
                "field": field_path,
                "severity": issue_severity,
                "tab": tab_index,
                "widget": widget,
            }
            issues.append(issue)
            tab_counts[tab_index] += 1
            tab_messages[tab_index].append(str(message))
            if widget in {
                self.node_x_edit,
                self.thickness_edit,
                self.elastic_modulus_edit,
                self.query_xs_edit,
                self.y_min_edit,
                self.y_max_edit,
                self.thickness_scale_combo,
                self.display_settings_button,
            }:
                self._set_validation_state(widget, "error", str(message))
                if widget in {
                    self.y_min_edit,
                    self.y_max_edit,
                    self.thickness_scale_combo,
                }:
                    self._set_validation_state(
                        self.display_settings_button,
                        "error",
                        str(message),
                    )
            elif widget is self.measurement_editor:
                self.measurement_editor.set_validation_state("error", str(message))
            elif widget is self.boundary_editor:
                self.boundary_editor.set_validation_state("error", str(message))
            elif widget is self.true_point_editor:
                self.true_point_editor.set_validation_state("error", str(message))
            elif widget is not None:
                self._set_validation_state(widget, "error", str(message))

        capability = None
        plot_options = None
        try:
            plot_options = self._collect_plot_options()
        except (TypeError, ValueError) as exc:
            add_issue(exc)

        if self.current_project_document is None:
            add_issue("尚未载入项目模型。", field="/model")
        else:
            try:
                capability = PathBeamEditor.capability(self.current_project_document)
            except (TypeError, ValueError) as exc:
                add_issue(exc, field="/model/geometry")

            if (
                capability is not None
                and capability.legacy_solver_compatible
                and plot_options is not None
            ):
                try:
                    config = self._build_form_config(plot_options=plot_options)
                    if self.analysis_setup.is_compatible:
                        report = self.analysis_service.validate(
                            config,
                            algorithm_id=self.analysis_setup.active_algorithm_id,
                            parameters=self.analysis_setup.parameter_values(),
                        )
                        for validation_issue in report.issues:
                            add_issue(validation_issue)
                except (TypeError, ValueError) as exc:
                    add_issue(exc)
            elif capability is not None:
                add_issue(
                    f"{capability.kind}：{capability.reason}。当前求解入口暂未接入。",
                    field="/analysis/algorithm/id",
                )

        if not self.analysis_setup.is_compatible:
            feedback = self.analysis_setup.algorithm_feedback_label.text().strip()
            recovery_fields = {
                self.analysis_setup.RECOVERY_MISSING: "/analysis/algorithm/id",
                self.analysis_setup.RECOVERY_VERSION: "/analysis/algorithm/version",
                self.analysis_setup.RECOVERY_SCHEMA: "/analysis/algorithm/parameter-schema-version",
                self.analysis_setup.RECOVERY_INVALID_SCHEMA: "/analysis/algorithm/parameter-schema-version",
                self.analysis_setup.RECOVERY_INCOMPATIBLE: "/analysis/algorithm/id",
            }
            add_issue(
                feedback or "当前模型没有可用的兼容算法。",
                field=recovery_fields.get(
                    self.analysis_setup.recovery_status,
                    "/analysis/algorithm/id",
                ),
            )
            for parameter_issue in self.analysis_setup.parameter_issues:
                add_issue(parameter_issue)

        self._readiness_issues = issues
        self.analysis_setup.set_readiness_solvability(issues)
        self.analysis_setup.sync_accessibility()
        self._update_readiness_tabs(tab_counts, tab_messages)
        if issues:
            has_solvability_issue = any(
                issue.get("field") == "/analysis/solvability"
                for issue in issues
            )
            recovery_parameter_gate = self.analysis_setup.recovery_status in {
                self.analysis_setup.RECOVERY_VERSION,
                self.analysis_setup.RECOVERY_SCHEMA,
                self.analysis_setup.RECOVERY_INVALID_SCHEMA,
            }
            has_algorithm_only = all(
                str(issue.get("field") or "").startswith("/analysis/algorithm/")
                or (
                    recovery_parameter_gate
                    and str(issue.get("field") or "").startswith(
                        "/analysis/parameters/"
                    )
                )
                for issue in issues
            )
            state = (
                "error"
                if has_solvability_issue or not has_algorithm_only
                else "pending"
            )
            self.input_status_label.setText(
                "不可求解  ›"
                if has_solvability_issue
                else (
                    "等待算法  ›"
                    if has_algorithm_only
                    else f"需检查 · {len(issues)}  ›"
                )
            )
        else:
            has_algorithm_only = False
            has_solvability_issue = False
            state = "ready"
            self.input_status_label.setText("可运行  ›")
        self.input_status_label.setProperty("state", state)
        self.input_status_label.setToolTip(
            "输入已就绪；点击运行重构（Ctrl+Return 或 F5）"
            if not issues
            else "点击定位首个问题\n" + "\n".join(
                issue["message"] for issue in issues[:4]
            )
        )
        self.input_status_label.setAccessibleDescription(
            "输入已就绪，激活后运行重构。"
            if not issues
            else f"发现 {len(issues)} 项问题，激活后定位首个问题。"
        )
        style = self.input_status_label.style()
        style.unpolish(self.input_status_label)
        style.polish(self.input_status_label)
        self.input_status_label.update()
        self._sync_empty_state(
            waiting_for_algorithm=(
                has_algorithm_only and not has_solvability_issue
            )
        )
        can_run = (
            not issues
            and capability is not None
            and capability.legacy_solver_compatible
            and not self._analysis_busy
        )
        self.run_button.setEnabled(bool(can_run))
        self.run_action.setEnabled(bool(can_run))
        self.input_status_label.setEnabled(not self._analysis_busy)
        if hasattr(self, "analysis_empty_state"):
            self.analysis_empty_state.action_button.setEnabled(
                not self._analysis_busy
            )
        if not self._analysis_busy and not self.analysis_setup.is_compatible:
            if self.analysis_setup.recovery_status in {
                self.analysis_setup.RECOVERY_READY,
                self.analysis_setup.RECOVERY_INCOMPATIBLE,
            }:
                self._set_run_status("当前重构方法不可求解", "error")
            else:
                self._set_run_status("重构方法待恢复", "stale")
        elif not self._analysis_busy and has_solvability_issue:
            self._set_run_status("当前重构方法不可求解", "error")
        return bool(can_run)

    def _set_run_status(self, text, state):
        if not hasattr(self, "run_status_label"):
            return
        self.run_status_label.setText(text)
        self.run_status_label.setProperty("state", state)
        style = self.run_status_label.style()
        style.unpolish(self.run_status_label)
        style.polish(self.run_status_label)
        self.run_status_label.update()

    def _set_analysis_busy(self, busy):
        self._analysis_busy = bool(busy)
        self.run_button.setText("计算中…" if busy else "运行重构")
        self.run_button.setAccessibleName(self.run_button.text())
        self.run_button.setEnabled(False if busy else not self._readiness_issues)
        self.run_action.setEnabled(False if busy else not self._readiness_issues)
        self.input_status_label.setEnabled(not busy)
        if hasattr(self, "analysis_empty_state"):
            self.analysis_empty_state.action_button.setEnabled(not busy)
        if busy:
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.unsetCursor()

    def _set_result_freshness(self, stale):
        self.results_stale = bool(stale and self.current_model is not None)
        if hasattr(self, "result_freshness_label"):
            self.result_freshness_label.setVisible(self.results_stale)
        if hasattr(self, "result_group"):
            self.result_group.setTitle(
                "结果数据 · 已过期" if self.results_stale else "结果数据"
            )
        if self.results_stale:
            self.statusBar().showMessage(
                "输入已修改；当前仍显示上一次结果，请重新运行。",
                6000,
            )

    def _capture_analysis_result_state(self):
        return {
            "current_model": self.current_model,
            "current_config": self.current_config,
            "current_inputs": self.current_inputs,
            "current_field": self.current_field,
            "current_raw_field": self.current_raw_field,
            "current_recovered_field": self.current_recovered_field,
            "current_visual_model": self.current_visual_model,
            "current_result_frame": self.current_result_frame,
            "current_view": self.current_view,
            "result_sequence": self.result_sequence,
            "result_tab_index": self.result_tabs.currentIndex(),
            "visualization_index": self.visualization_stack.currentIndex(),
            "json_text": self.json_text.toPlainText(),
            "metrics": {
                key: label.text()
                for key, label in self.analysis_metric_labels.items()
            },
        }

    def _restore_analysis_result_state(self, snapshot):
        previous_model = snapshot["current_model"]
        if previous_model is None:
            self._clear_result_views()
        else:
            for key in (
                "current_model",
                "current_config",
                "current_inputs",
                "current_field",
                "current_raw_field",
                "current_recovered_field",
                "current_visual_model",
                "current_result_frame",
                "current_view",
                "result_sequence",
            ):
                setattr(self, key, snapshot[key])
            self.view_buttons[self.current_view].setChecked(True)
            self._fill_result_tables(self.current_model, self.current_inputs)
            self._render_current_view()
            self.visualization_stack.setCurrentIndex(
                snapshot["visualization_index"]
            )
            self.result_tabs.setCurrentIndex(snapshot["result_tab_index"])
            self._set_result_freshness(True)
        self.json_text.setPlainText(snapshot["json_text"])
        for key, text in snapshot["metrics"].items():
            self.analysis_metric_labels[key].setText(text)

    def _set_view_meta(self, text):
        self._view_meta_text = str(text)
        if not hasattr(self, "view_meta_label"):
            return
        self.view_meta_label.setToolTip(self._view_meta_text)
        if hasattr(self, "view_toolbar"):
            self.view_toolbar.setToolTip(self._view_meta_text)
        self._refresh_view_meta()

    def _refresh_view_meta(self):
        if not hasattr(self, "view_meta_label"):
            return
        self.view_meta_label.setText(self._view_meta_text)
        self.view_meta_label.setVisible(bool(self._view_meta_text))
        self._refresh_view_context()

    def _refresh_view_context(self):
        if not hasattr(self, "view_context_label"):
            return
        mode_text = {
            "shape": "重构形态",
            "strain": "轴向应变",
            "stress": "轴向应力",
        }.get(self.current_view, "重构结果")
        is_3d = (
            hasattr(self, "visualization_stack")
            and self.visualization_stack.currentIndex() == 1
        )
        space_text = "三维交互" if is_3d else "二维结果"
        self.view_context_label.setText(f"{space_text} · {mode_text}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_view_meta()

    def _update_analysis_summary(self, config=None, model=None):
        if not hasattr(self, "analysis_metric_labels"):
            return

        if model is not None:
            node_count = model.n_nodes
            element_count = model.n_elems
        elif config is not None:
            node_count = len(config.get("node_x", []))
            element_count = max(node_count - 1, 0)
        else:
            node_count = 0
            element_count = 0

        measurement_count = 0
        elastic_modulus = None
        if config is not None:
            measurement_count = sum(
                len(element.get("measurements", []))
                for element in config.get("elements_sensor_data", [])
            )
            elastic_modulus = config.get("material", {}).get("elastic_modulus")

        mesh_text = "--" if node_count == 0 else f"{node_count} 节点 / {element_count} 单元"
        sensor_text = "--" if config is None else f"{measurement_count} 个测点"
        material_text = (
            "未设置 E"
            if elastic_modulus in (None, "")
            else f"E {float(elastic_modulus) / 1.0e9:.6g} GPa"
        )
        self.analysis_metric_labels["mesh"].setText(mesh_text)
        self.analysis_metric_labels["sensors"].setText(sensor_text)
        self.analysis_metric_labels["material"].setText(material_text)
        if config is not None:
            self.analysis_metric_labels["solver"].setText(
                self.analysis_setup.active_algorithm_display_name
            )

    def _update_project_summary(self, project):
        if not hasattr(self, "analysis_metric_labels"):
            return
        self.analysis_setup.set_project(project)
        material = project.materials[0] if project.materials else None
        elastic_modulus = None if material is None else material.elastic_modulus
        self.analysis_metric_labels["solver"].setText(
            self.analysis_setup.active_algorithm_display_name
        )
        self.analysis_metric_labels["mesh"].setText(
            f"{project.modeling_space.upper()} · "
            f"{len(project.nodes)} 节点 / {len(project.elements)} 单元"
        )
        self.analysis_metric_labels["sensors"].setText(f"{len(project.sensors)} 个测点")
        self.analysis_metric_labels["material"].setText(
            "未设置 E"
            if elastic_modulus in (None, "")
            else f"E {float(elastic_modulus) / 1.0e9:.6g} GPa"
        )

    def _clear_figure_overlays(self):
        self._field_colorbar = None
        # Colorbar creation changes the parent axes geometry. Rebuilding the axes
        # prevents those layout changes from accumulating across view switches.
        self.figure.clear()
        self.axes = self.figure.add_subplot(111)

    def _render_empty_plot(self):
        if hasattr(self, "plot_content_stack"):
            self.plot_content_stack.setCurrentWidget(self.analysis_empty_state)
            self._sync_empty_state()
        self._clear_figure_overlays()
        self.axes.clear()
        self.axes.set_axis_off()
        self.axes.set_facecolor(self._theme_color("canvas"))
        self.figure.set_facecolor(self._theme_color("canvas"))
        self.axes.text(
            0.5,
            0.54,
            "尚未生成重构结果",
            transform=self.axes.transAxes,
            ha="center",
            va="center",
            fontsize=17,
            color=self._theme_color("text_strong"),
            fontweight="semibold",
        )
        self.axes.text(
            0.5,
            0.45,
            "检查左侧参数后，点击右上角“运行重构”",
            transform=self.axes.transAxes,
            ha="center",
            va="center",
            fontsize=10,
            color=self._theme_color("text_muted"),
        )
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw_idle()

    def _clear_result_views(self):
        self.current_inputs = None
        self.current_field = None
        self.current_raw_field = None
        self.current_recovered_field = None
        self.current_visual_model = None
        self.current_result_frame = None
        self._set_result_freshness(False)
        self.current_view = "stress"
        if hasattr(self, "view_buttons"):
            self.view_buttons["stress"].setChecked(True)
            self._set_view_meta("重构后优先显示应力场 · 未设置 E 时显示应变场")
            self.result_tabs.setCurrentIndex(self.field_result_tab_index)
        self.node_result_table.set_rows([])
        self.query_result_table.set_rows([])
        self.compare_result_table.set_rows([])
        self.field_result_table.set_rows([])
        if hasattr(self, "node_result_tab_index"):
            self.result_tabs.setTabText(self.node_result_tab_index, "节点结果")
            self.result_tabs.setTabText(self.query_result_tab_index, "查询结果")
            self.result_tabs.setTabText(self.compare_result_tab_index, "实测对比")
        if hasattr(self, "field_result_tab_index"):
            self.result_tabs.setTabText(self.field_result_tab_index, "截面场")
        if hasattr(self, "structure_3d_view"):
            self.structure_3d_view.clear_frame()
        self._render_empty_plot()

    def _collect_plot_options(self):
        y_min_text = self.y_min_edit.text().strip()
        y_max_text = self.y_max_edit.text().strip()
        if y_min_text or y_max_text:
            if not (y_min_text and y_max_text):
                field = (
                    "/view_state/y_limits/0"
                    if not y_min_text
                    else "/view_state/y_limits/1"
                )
                raise InputValidationError(
                    "手动设置 Y 轴时，Y轴最小值和最大值必须同时填写。",
                    field=field,
                )
            try:
                y_min = float(y_min_text)
            except ValueError as exc:
                raise InputValidationError(
                    "Y 轴最小值必须是有效数值。",
                    field="/view_state/y_limits/0",
                ) from exc
            try:
                y_max = float(y_max_text)
            except ValueError as exc:
                raise InputValidationError(
                    "Y 轴最大值必须是有效数值。",
                    field="/view_state/y_limits/1",
                ) from exc
            if not np.isfinite(y_min):
                raise InputValidationError(
                    "Y 轴最小值必须是有限数值。",
                    field="/view_state/y_limits/0",
                )
            if not np.isfinite(y_max):
                raise InputValidationError(
                    "Y 轴最大值必须是有限数值。",
                    field="/view_state/y_limits/1",
                )
            y_limits = [y_min, y_max]
            if y_limits[1] <= y_limits[0]:
                raise InputValidationError(
                    "Y 轴范围不合法，要求最大值大于最小值。",
                    field="/view_state/y_limits/1",
                )
        else:
            y_limits = None

        thickness_scale_text = self.thickness_scale_combo.currentText().strip()
        preset_index = self.thickness_scale_combo.findText(thickness_scale_text)
        if preset_index >= 0:
            thickness_scale = self.thickness_scale_combo.itemData(preset_index)
        else:
            if thickness_scale_text in ("", "auto", "自动增强"):
                thickness_scale = "auto"
            else:
                try:
                    thickness_scale = float(thickness_scale_text)
                except ValueError as exc:
                    raise InputValidationError(
                        "厚度显示倍率必须是大于 0 的数值或自动增强。",
                        field="/view_state/thickness_scale",
                    ) from exc
                if not np.isfinite(thickness_scale) or thickness_scale <= 0.0:
                    raise InputValidationError(
                        "厚度显示倍率必须是大于 0 的有限数值或自动增强。",
                        field="/view_state/thickness_scale",
                    )

        return {
            "show_original": self.show_original_check.isChecked(),
            "show_nodes": self.show_nodes_check.isChecked(),
            "equal_axis": self.equal_axis_check.isChecked(),
            "annotate_points": self.annotate_points_check.isChecked(),
            "connect_pairs": self.connect_pairs_check.isChecked(),
            "title": self.title_edit.text().strip() or "二维梁重构形态",
            "legend_loc": "best",
            "label_offset_scale": 0.04,
            "figsize": [11.0, 4.5],
            "y_limits": y_limits,
            "thickness_scale": thickness_scale,
            "field_representation": self.field_representation_combo.currentData(),
        }

    def _build_form_config(self, *, plot_options=None, require_measurements=True):
        # A recovery-blocked case may contain values that the current (or missing)
        # plugin cannot parse.  Keep those values in the case snapshot, but do not
        # feed them through the legacy form adapter merely to save unrelated edits.
        analysis_parameters = (
            {}
            if self.analysis_setup.should_preserve_saved_case
            else self.analysis_setup.parameter_values()
        )
        if plot_options is None:
            plot_options = self._collect_plot_options()
        return build_config_from_form_data(
            node_x_text=self.node_x_edit.text(),
            thickness_text=self.thickness_edit.text(),
            gauss_n_text=str(analysis_parameters.get("gauss_n", 3)),
            points_per_element_text=str(
                analysis_parameters.get("points_per_element", 120)
            ),
            query_xs_text=self.query_xs_edit.text(),
            measurement_rows=self.measurement_editor.get_rows(),
            boundary_rows=self.boundary_editor.get_rows(),
            true_point_rows=self.true_point_editor.get_rows(),
            plot_options=plot_options,
            elastic_modulus_gpa_text=self.elastic_modulus_edit.text(),
            require_measurements=require_measurements,
        )

    def _set_project_dirty(self, dirty=True):
        self.project_dirty = bool(dirty)
        project_name = (
            self.current_project_document.name
            if self.current_project_document is not None
            else "未命名项目"
        )
        if self.project_dirty:
            state_text = "未保存"
        elif self.current_project_path is None:
            state_text = "未关联文件"
        else:
            state_text = "已保存"
        self.app_subtitle.setText(f"{project_name} · {state_text}")
        location = (
            str(self.current_project_path)
            if self.current_project_path is not None
            else "尚未关联项目文件"
        )
        self.app_subtitle.setToolTip(f"{location}\n{state_text}")
        dirty_mark = " *" if self.project_dirty else ""
        self.setWindowTitle(f"iFEM — {project_name}{dirty_mark}")

    def _confirm_save_before_action(self):
        if not self.project_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "未保存的修改",
            "当前项目包含未保存修改。是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return bool(self.save_current_project())
        return answer == QMessageBox.StandardButton.Discard

    def _confirm_discard_changes(self):
        """Compatibility wrapper for callers that only need a destructive-action gate."""
        return self._confirm_save_before_action()

    def new_project(self):
        if not self._confirm_discard_changes():
            return False
        selection = ProjectNameDialog.choose_project_name(
            self,
            library=self.project_library,
            title="新建项目",
            confirm_text="开始建模",
            theme_id=self.current_theme_id,
        )
        if selection is None:
            return False
        project_name, project_path = selection
        dialog = BeamModelerDialog(empty_beam_project(name=project_name), self)
        if hasattr(dialog, "set_project_storage"):
            dialog.set_project_storage(
                self.project_library,
                project_path,
                project_is_saved=False,
            )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        dialog_path = getattr(dialog, "project_path", None)
        self.current_project_path = Path(dialog_path or project_path)
        self._apply_project_document(
            dialog.project,
            dirty=not bool(getattr(dialog, "project_is_saved", False)),
            status_text="新项目已建立 · 待运行",
        )
        return True

    def open_project(self):
        if not self._confirm_discard_changes():
            return False
        path = ProjectLibraryDialog.choose_project(
            self,
            library=self.project_library,
            theme_id=self.current_theme_id,
        )
        if not path:
            return False
        return self.load_project_path(path)

    def load_project_path(self, path):
        """Load a selected project path for both toolbar and startup-center flows."""
        try:
            project = load_project(path)
            PathBeamEditor.ordered_path(project)
            self._apply_project_document(
                project,
                dirty=False,
                status_text="项目已打开 · 待运行",
            )
            self.current_project_path = Path(path)
            self._set_project_dirty(False)
            self.statusBar().showMessage(f"已打开项目：{path}", 6000)
            return True
        except (OSError, TypeError, ValueError) as exc:
            self._show_error(exc)
            return False

    def save_current_project(self):
        if self.current_project_path is None:
            return self.save_project_as()
        return self._save_project_to(self.current_project_path)

    def save_project_as(self):
        project_name = (
            self.current_project_document.name
            if self.current_project_document is not None
            else "未命名项目"
        )
        allowed_path = (
            self.current_project_path
            if self.project_library.contains_path(self.current_project_path)
            else None
        )
        selection = ProjectNameDialog.choose_project_name(
            self,
            library=self.project_library,
            initial_name=project_name,
            allowed_existing_path=allowed_path,
            title="项目另存为",
            confirm_text="保存项目",
            theme_id=self.current_theme_id,
        )
        if selection is None:
            return False
        project_name, path = selection
        return self._save_project_to(path, project_name=project_name)

    def _save_project_to(self, path, *, project_name=None):
        try:
            if not self._save_inputs_are_valid():
                self._focus_first_input_issue()
                return False
            project = self._project_for_save()
            if project_name and project.name != project_name:
                project = replace(project, name=project_name)
            destination = save_project(path, project)
            self.current_project_document = project
            self.current_project_path = destination
            self._sync_editor_entity_ids(project)
            self._set_project_dirty(False)
            self._write_message(f"项目已保存：\n{destination}")
            return True
        except (OSError, KeyError, TypeError, ValueError) as exc:
            self._show_error(exc)
            return False

    def _save_inputs_are_valid(self):
        try:
            plot_options = self._collect_plot_options()
        except (TypeError, ValueError):
            self._refresh_input_readiness()
            return False
        current = self.current_project_document
        if current is None:
            try:
                self._build_form_config(
                    plot_options=plot_options,
                    require_measurements=False,
                )
            except (TypeError, ValueError):
                self._refresh_input_readiness()
                return False
            return True
        try:
            capability = PathBeamEditor.capability(current)
        except (TypeError, ValueError):
            self._refresh_input_readiness()
            return False
        if not capability.legacy_solver_compatible:
            return True
        try:
            self._build_form_config(
                plot_options=plot_options,
                require_measurements=False,
            )
        except (TypeError, ValueError):
            self._refresh_input_readiness()
            return False
        return True

    @staticmethod
    def _model_config_projection(config):
        return {
            key: config.get(key)
            for key in (
                "node_x",
                "thickness",
                "material",
                "elements_sensor_data",
                "prescribed_dofs",
            )
        }

    def _apply_view_state_to_project(self, project, plot_options=None):
        if plot_options is None:
            plot_options = self._collect_plot_options()
        plot_options = dict(plot_options)
        if dict(project.view_state) == plot_options:
            return project
        return project.revised(view_state=plot_options)

    @staticmethod
    def _section_with_legacy_thickness(section, thickness):
        parameters = dict(section.parameters)
        dimension_key = {
            "rectangle": "height",
            "circle": "diameter",
            "circular_tube": "outer_diameter",
            "box": "outer_height",
            "i_section": "height",
        }.get(section.shape)
        if dimension_key is not None:
            parameters[dimension_key] = float(thickness)
        return replace(section, thickness=float(thickness), parameters=parameters)

    def _merge_legacy_form_into_project(self, current, config):
        """Apply the legacy 2D form while retaining stable project identities."""
        generated = project_from_legacy_config(config, project_name=current.name)
        old_nodes = sorted(current.nodes, key=lambda node: node.coordinates[0])
        generated_nodes = list(generated.nodes)

        node_ids = [None] * len(generated_nodes)
        if len(old_nodes) == len(generated_nodes):
            node_ids = [node.identifier for node in old_nodes]
        else:
            unused_old = set(range(len(old_nodes)))
            for new_index, node in enumerate(generated_nodes):
                match = next(
                    (
                        old_index
                        for old_index in unused_old
                        if np.isclose(
                            old_nodes[old_index].coordinates[0],
                            node.coordinates[0],
                            rtol=0.0,
                            atol=1.0e-12,
                        )
                    ),
                    None,
                )
                if match is not None:
                    node_ids[new_index] = old_nodes[match].identifier
                    unused_old.remove(match)
        nodes = tuple(
            replace(node, identifier=node_ids[index] or node.identifier)
            for index, node in enumerate(generated_nodes)
        )

        if current.materials:
            material = replace(
                current.materials[0],
                elastic_modulus=generated.materials[0].elastic_modulus,
            )
            materials = (material, *current.materials[1:])
        else:
            material = generated.materials[0]
            materials = generated.materials
        if current.sections:
            section = self._section_with_legacy_thickness(
                current.sections[0], generated.sections[0].thickness
            )
            sections = (section, *current.sections[1:])
        else:
            section = generated.sections[0]
            sections = generated.sections

        old_element_by_pair = {
            frozenset(element.node_ids): element for element in current.elements
        }
        elements = []
        for index, generated_element in enumerate(generated.elements):
            node_pair = (nodes[index].identifier, nodes[index + 1].identifier)
            old_element = old_element_by_pair.get(frozenset(node_pair))
            elements.append(
                replace(
                    generated_element,
                    identifier=(
                        old_element.identifier
                        if old_element is not None
                        else generated_element.identifier
                    ),
                    node_ids=node_pair,
                    family=(
                        old_element.family
                        if old_element is not None
                        else generated_element.family
                    ),
                    section_id=(
                        old_element.section_id
                        if old_element is not None and old_element.section_id is not None
                        else section.identifier
                    ),
                    material_id=(
                        old_element.material_id
                        if old_element is not None and old_element.material_id is not None
                        else material.identifier
                    ),
                )
            )
        elements = tuple(elements)

        old_node_index = {node.identifier: index for index, node in enumerate(old_nodes)}
        old_element_index = {}
        for element in current.elements:
            indices = sorted(old_node_index[node_id] for node_id in element.node_ids)
            if len(indices) == 2 and indices[1] == indices[0] + 1:
                old_element_index[element.identifier] = indices[0]
        ordered_old_element_ids = [
            element_id
            for element_id, _index in sorted(
                old_element_index.items(), key=lambda item: item[1]
            )
        ]
        old_sensors = [
            sensor
            for element_id in ordered_old_element_ids
            for sensor in current.sensors
            if sensor.attachment.entity_id == element_id
        ]
        generated_element_index = {
            element.identifier: index for index, element in enumerate(generated.elements)
        }
        generated_sensors = list(generated.sensors)
        sensor_rows_by_element = [[] for _element in generated.elements]
        for row in self.measurement_editor.get_rows():
            element_index = int(str(row.get("element", "")).strip())
            sensor_rows_by_element[element_index].append(row)
        sensor_row_ids = [
            str(row.get("_entity_id", ""))
            for rows in sensor_rows_by_element
            for row in rows
        ]
        old_sensor_by_id = {sensor.identifier: sensor for sensor in old_sensors}
        used_sensor_ids = set()
        sensors = []
        for index, generated_sensor in enumerate(generated_sensors):
            element_index = generated_element_index[generated_sensor.attachment.entity_id]
            attachment = replace(
                generated_sensor.attachment,
                entity_id=elements[element_index].identifier,
            )
            requested_id = sensor_row_ids[index] if index < len(sensor_row_ids) else ""
            old_sensor = old_sensor_by_id.get(requested_id)
            if (
                old_sensor is None
                and not requested_id
                and len(old_sensors) == len(generated_sensors)
                and index < len(old_sensors)
                and old_sensors[index].identifier not in used_sensor_ids
            ):
                old_sensor = old_sensors[index]
            if old_sensor is None:
                sensors.append(replace(generated_sensor, attachment=attachment))
            else:
                used_sensor_ids.add(old_sensor.identifier)
                sensors.append(
                    replace(
                        generated_sensor,
                        identifier=old_sensor.identifier,
                        label=old_sensor.label,
                        channel_id=old_sensor.channel_id,
                        attachment=attachment,
                    )
                )

        old_boundaries = {
            (boundary.node_id, boundary.dof): boundary
            for boundary in current.boundary_conditions
        }
        old_boundary_by_id = {
            boundary.identifier: boundary for boundary in current.boundary_conditions
        }
        boundary_row_ids = [
            str(row.get("_entity_id", ""))
            for row in self.boundary_editor.get_rows()
        ]
        generated_node_index = {
            node.identifier: index for index, node in enumerate(generated.nodes)
        }
        boundaries = []
        for generated_boundary in generated.boundary_conditions:
            node_index = generated_node_index[generated_boundary.node_id]
            node_id = nodes[node_index].identifier
            requested_id = (
                boundary_row_ids[len(boundaries)]
                if len(boundaries) < len(boundary_row_ids)
                else ""
            )
            old_boundary = old_boundary_by_id.get(requested_id)
            if old_boundary is None:
                old_boundary = old_boundaries.get((node_id, generated_boundary.dof))
            boundaries.append(
                replace(
                    generated_boundary,
                    identifier=(
                        old_boundary.identifier
                        if old_boundary is not None
                        else generated_boundary.identifier
                    ),
                    node_id=node_id,
                )
            )

        return current.revised(
            nodes=nodes,
            elements=elements,
            sensors=tuple(sensors),
            boundary_conditions=tuple(boundaries),
            materials=materials,
            sections=sections,
        )

    def _project_for_save(self):
        """Build a save snapshot without flattening non-legacy project geometry."""
        current = self.current_project_document
        if current is None:
            config = self._build_form_config(require_measurements=False)
            project = project_from_legacy_config(config)
            return self._apply_analysis_setup_to_project(project, config=config)

        capability = PathBeamEditor.capability(current)
        if not capability.legacy_solver_compatible:
            project = self._apply_analysis_setup_to_project(current)
            return self._apply_view_state_to_project(project)

        config = self._build_form_config(require_measurements=False)
        existing_config = legacy_config_from_project(
            current,
            include_analysis_parameters=(
                not self.analysis_setup.should_preserve_saved_case
            ),
        )
        if self._model_config_projection(existing_config) == self._model_config_projection(config):
            project = current
        else:
            project = self._merge_legacy_form_into_project(current, config)
        project = self._apply_analysis_setup_to_project(project, config=config)
        return self._apply_view_state_to_project(project, config["plot_options"])

    def _apply_project_document(self, project, *, dirty, status_text):
        capability = PathBeamEditor.capability(project)
        config = None
        config_json = None
        if capability.legacy_solver_compatible:
            preserve_analysis = self.analysis_setup.project_requires_recovery(project)
            config = legacy_config_from_project(
                project,
                include_analysis_parameters=not preserve_analysis,
            )
            config_json = config_to_json(config)

        previous_project = self.current_project_document
        try:
            self.analysis_setup.set_project(project)
        except Exception:
            if previous_project is not None:
                self.analysis_setup.set_project(previous_project)
            raise

        self.current_project_document = project
        self._sync_analysis_parameter_controls()
        self.current_model = None
        self.current_config = None
        self._clear_result_views()
        if capability.legacy_solver_compatible:
            self._loading_form = True
            try:
                self._load_config_to_form(config)
            finally:
                self._loading_form = False
            self.json_text.setPlainText(config_json)
            self._update_analysis_summary(config=config)
            self.run_button.setEnabled(True)
            self._set_run_status(status_text, "idle")
        else:
            self._loading_form = True
            try:
                self.node_x_edit.clear()
                self.thickness_edit.clear()
                self.elastic_modulus_edit.clear()
                self.measurement_editor.set_rows([])
                self.boundary_editor.set_rows([])
                self.true_point_editor.set_rows([])
            finally:
                self._loading_form = False
            self.measurement_preview.set_preview_data(
                build_measurement_preview("", [])
            )
            self.json_text.clear()
            self._update_project_summary(project)
            self.run_button.setEnabled(False)
            self._set_run_status("项目已载入 · 算法待接入", "stale")
            try:
                self._loading_form = True
                self._load_plot_options_to_form(dict(project.view_state))
            except (TypeError, ValueError):
                pass
            finally:
                self._loading_form = False
        self._set_project_dirty(dirty)
        self._refresh_input_readiness()
        self._write_message(
            f"{status_text}。\n{capability.kind} · {len(project.nodes)} 节点 · "
            f"{len(project.elements)} 单元 · {len(project.sensors)} 测点"
        )

    def show_data_exchange(self):
        self.left_tabs.setCurrentIndex(4)
        self.json_text.setFocus()

    def refresh_json_from_form(self):
        try:
            config = self._build_form_config()
            self.json_text.setPlainText(config_to_json(config))
            self._write_message("已根据当前表单生成 JSON 配置。")
            self.statusBar().showMessage("JSON 配置已由当前表单更新", 5000)
        except Exception as exc:
            self._show_error(exc)

    def import_json_to_form(self):
        try:
            config = load_config_from_json(self.json_text.toPlainText().strip())
            project = project_from_legacy_config(config)
            if not self._confirm_save_before_action():
                return
            self._apply_project_document(
                project,
                dirty=True,
                status_text="JSON 已导入 · 待运行",
            )
        except Exception as exc:
            self._loading_form = False
            self._show_error(exc)

    def load_sample_data(self, _checked=False, *, initial=False):
        if not initial and not self._confirm_save_before_action():
            return False
        config = get_sample_config()
        project = project_from_legacy_config(config)
        self.current_project_path = None
        self._apply_project_document(
            project,
            dirty=not initial,
            status_text="示例已载入 · 待运行",
        )
        return True

    def _project_for_interactive_modeler(self):
        return self._project_for_save()

    def _apply_analysis_setup_to_project(self, project, *, config=None):
        def merged_parameters(original=None, *, include_setup=True):
            parameters = dict(original or {})
            if include_setup:
                for name in self.analysis_setup.declared_parameter_names:
                    parameters.pop(name, None)
                parameters.update(self.analysis_setup.parameter_values())
            if config is not None:
                parameters["query_xs"] = list(config.get("query_xs", []))
                parameters["true_points"] = list(config.get("true_points", []))
            return parameters

        if not project.analysis_cases:
            analysis_case = AnalysisCase(
                identifier=new_entity_id("analysis"),
                name="重构分析工况",
                algorithm_id=self.analysis_setup.active_algorithm_id,
                parameters=merged_parameters(),
                algorithm_version=self.analysis_setup.active_algorithm_version,
                parameter_schema_version=(
                    self.analysis_setup.active_parameter_schema_version
                ),
            )
            return project.revised(
                analysis_cases=(analysis_case,),
                active_analysis_id=analysis_case.identifier,
            )

        active_id = project.active_analysis_id or project.analysis_cases[0].identifier
        if self.analysis_setup.should_preserve_saved_case:
            if project.active_analysis_id == active_id:
                return project
            return project.revised(
                active_analysis_id=active_id,
            )

        updated_cases = []
        changed = False
        for analysis_case in project.analysis_cases:
            if analysis_case.identifier != active_id:
                updated_cases.append(analysis_case)
                continue
            updated_case = replace(
                analysis_case,
                algorithm_id=self.analysis_setup.active_algorithm_id,
                parameters=merged_parameters(
                    analysis_case.parameters,
                    include_setup=self.analysis_setup.configuration_modified,
                ),
                algorithm_version=(
                    self.analysis_setup.active_algorithm_version
                    if self.analysis_setup.configuration_modified
                    else analysis_case.algorithm_version
                ),
                parameter_schema_version=(
                    self.analysis_setup.active_parameter_schema_version
                    if self.analysis_setup.configuration_modified
                    else analysis_case.parameter_schema_version
                ),
            )
            changed = changed or updated_case != analysis_case
            updated_cases.append(updated_case)
        if not changed:
            return project
        return project.revised(
            analysis_cases=tuple(updated_cases),
            active_analysis_id=active_id,
        )

    def open_interactive_modeler(self):
        try:
            project = self._project_for_interactive_modeler()
        except Exception as exc:
            if self.current_project_document is None:
                self._show_error(exc)
                return
            project = self.current_project_document

        dialog = BeamModelerDialog(project, self)
        if hasattr(dialog, "set_project_storage"):
            dialog.set_project_storage(
                self.project_library,
                self.current_project_path,
                project_is_saved=(
                    not self.project_dirty and self.current_project_path is not None
                ),
            )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            project = dialog.project
            dialog_path = getattr(dialog, "project_path", None)
            if dialog_path is not None:
                self.current_project_path = Path(dialog_path)
            self.current_project_document = project
            self.analysis_setup.set_project(project)
            self._sync_analysis_parameter_controls()
            self._set_project_dirty(
                not bool(getattr(dialog, "project_is_saved", False))
            )
            self.current_model = None
            self.current_config = None
            self._clear_result_views()
            capability = PathBeamEditor.capability(project)
            if capability.legacy_solver_compatible:
                config = legacy_config_from_project(
                    project,
                    include_analysis_parameters=(
                        not self.analysis_setup.should_preserve_saved_case
                    ),
                )
                self._loading_form = True
                try:
                    self._load_config_to_form(config)
                finally:
                    self._loading_form = False
                self._update_analysis_summary(config=config)
                self.json_text.setPlainText(config_to_json(config))
                self.run_button.setEnabled(True)
                self._set_run_status("模型已更新 · 待运行", "idle")
                detail = "可由当前二维直梁算法直接计算。"
            else:
                self._update_project_summary(project)
                self.run_button.setEnabled(False)
                self._set_run_status("模型已保存 · 算法待接入", "stale")
                detail = f"{capability.reason}，当前求解按钮已停用。"
            self._write_message(
                f"交互模型已保存：{capability.kind}，弧长 {capability.total_length:.6g} m，"
                f"{len(project.nodes)} 个节点，{len(project.elements)} 个单元，"
                f"{len(project.sensors)} 个测点。\n{detail}"
            )
            self._refresh_input_readiness()
        except Exception as exc:
            self._loading_form = False
            self._show_error(exc)

    def _load_plot_options_to_form(self, plot_options):
        plot_options = dict(plot_options or {})
        self.title_edit.setText(plot_options.get("title", "二维梁重构形态"))
        y_limits = plot_options.get("y_limits")
        if isinstance(y_limits, (list, tuple)) and len(y_limits) == 2:
            self.y_min_edit.setText(f"{float(y_limits[0]):.12g}")
            self.y_max_edit.setText(f"{float(y_limits[1]):.12g}")
        else:
            self.y_min_edit.clear()
            self.y_max_edit.clear()
        self.show_original_check.setChecked(bool(plot_options.get("show_original", True)))
        self.show_nodes_check.setChecked(bool(plot_options.get("show_nodes", True)))
        self.equal_axis_check.setChecked(bool(plot_options.get("equal_axis", False)))
        self.annotate_points_check.setChecked(bool(plot_options.get("annotate_points", True)))
        self.connect_pairs_check.setChecked(bool(plot_options.get("connect_pairs", True)))
        thickness_scale = plot_options.get("thickness_scale", "auto")
        thickness_scale_index = self.thickness_scale_combo.findData(thickness_scale)
        if thickness_scale_index >= 0:
            self.thickness_scale_combo.setCurrentIndex(thickness_scale_index)
        elif thickness_scale not in (None, ""):
            self.thickness_scale_combo.setEditText(f"{float(thickness_scale):.12g}")
        field_representation = plot_options.get("field_representation", "nodal_average")
        field_representation_index = self.field_representation_combo.findData(field_representation)
        self.field_representation_combo.setCurrentIndex(max(field_representation_index, 0))
        self._sync_scale_buttons()

    def _load_config_to_form(self, config):
        self.node_x_edit.setText(", ".join(f"{x:.12g}" for x in config["node_x"]))
        self.thickness_edit.setText(f"{float(config['thickness']):.12g}")
        elastic_modulus = config.get("material", {}).get("elastic_modulus")
        if elastic_modulus in (None, ""):
            self.elastic_modulus_edit.clear()
        else:
            self.elastic_modulus_edit.setText(f"{float(elastic_modulus) / 1.0e9:.12g}")
        self.analysis_setup.set_parameter_values(
            {
                "gauss_n": config.get("gauss_n", 3),
                "points_per_element": config.get("points_per_element", 120),
            }
        )
        self.query_xs_edit.setText(", ".join(f"{float(x):.12g}" for x in config.get("query_xs", [])))
        self._load_plot_options_to_form(config.get("plot_options", {}))

        measurement_rows = measurement_rows_from_config(config)
        boundary_rows = boundary_rows_from_prescribed_dofs(config["prescribed_dofs"])
        self._attach_project_entity_ids(measurement_rows, boundary_rows)
        self.measurement_editor.set_rows(measurement_rows)
        self.boundary_editor.set_rows(boundary_rows)
        self.true_point_editor.set_rows(true_point_rows_from_config(config))
        self.refresh_measurement_preview()

    def _attach_project_entity_ids(self, measurement_rows, boundary_rows):
        project = self.current_project_document
        if project is None:
            return
        nodes = sorted(project.nodes, key=lambda node: node.coordinates[0])
        element_by_pair = {
            frozenset(element.node_ids): element for element in project.elements
        }
        ordered_elements = [
            element_by_pair[frozenset((left.identifier, right.identifier))]
            for left, right in zip(nodes, nodes[1:])
        ]
        ordered_sensors = [
            sensor
            for element in ordered_elements
            for sensor in project.sensors
            if sensor.attachment.entity_id == element.identifier
        ]
        if len(ordered_sensors) == len(measurement_rows):
            for row, sensor in zip(measurement_rows, ordered_sensors):
                row["_entity_id"] = sensor.identifier

        node_index = {node.identifier: index for index, node in enumerate(nodes)}
        boundary_by_key = {
            (node_index[boundary.node_id], boundary.dof): boundary
            for boundary in project.boundary_conditions
        }
        for row in boundary_rows:
            boundary = boundary_by_key.get((int(row["node"]), row["dof"]))
            if boundary is not None:
                row["_entity_id"] = boundary.identifier

    def _sync_editor_entity_ids(self, project):
        try:
            capability = PathBeamEditor.capability(project)
        except (TypeError, ValueError):
            return
        if not capability.legacy_solver_compatible:
            return

        nodes = sorted(project.nodes, key=lambda node: node.coordinates[0])
        element_by_pair = {
            frozenset(element.node_ids): element for element in project.elements
        }
        ordered_elements = [
            element_by_pair[frozenset((left.identifier, right.identifier))]
            for left, right in zip(nodes, nodes[1:])
        ]
        sensor_ids_by_element = {
            index: [
                sensor.identifier
                for sensor in project.sensors
                if sensor.attachment.entity_id == element.identifier
            ]
            for index, element in enumerate(ordered_elements)
        }
        sensor_offsets = {index: 0 for index in sensor_ids_by_element}
        measurement_ids = []
        for row in self.measurement_editor.get_rows():
            element_index = int(str(row["element"]).strip())
            offset = sensor_offsets[element_index]
            measurement_ids.append(sensor_ids_by_element[element_index][offset])
            sensor_offsets[element_index] = offset + 1
        self.measurement_editor.set_row_entity_ids(measurement_ids)

        node_index = {node.identifier: index for index, node in enumerate(nodes)}
        boundary_ids = {
            (node_index[boundary.node_id], boundary.dof): boundary.identifier
            for boundary in project.boundary_conditions
        }
        self.boundary_editor.set_row_entity_ids(
            [
                boundary_ids[(int(row["node"]), row["dof"])]
                for row in self.boundary_editor.get_rows()
            ]
        )

    def refresh_measurement_preview(self):
        if not hasattr(self, "measurement_editor") or not hasattr(self, "measurement_preview"):
            return
        preview_data = build_measurement_preview(self.node_x_edit.text(), self.measurement_editor.get_rows())
        self.measurement_preview.set_preview_data(preview_data)

    def run_reconstruction(self):
        if self._analysis_busy:
            return
        if not self._refresh_input_readiness():
            self._set_run_status("请先修正输入", "error")
            self._focus_first_input_issue()
            return
        if self.current_project_document is not None:
            try:
                matches = match_project_algorithms(
                    self.current_project_document,
                    self.analysis_service.registry.list(),
                )
            except (KeyError, TypeError, ValueError) as exc:
                self._show_error(exc)
                return
            selected_match = next(
                (
                    match
                    for match in matches
                    if match.algorithm_id == self.analysis_setup.active_algorithm_id
                ),
                None,
            )
            if selected_match is None or not selected_match.compatible:
                self._set_run_status("当前模型缺少匹配算法", "error")
                reason = (
                    "当前模型没有已注册的适用算法"
                    if selected_match is None
                    else selected_match.reason_text
                )
                self._show_error(
                    ValueError(
                        f"{reason}。模型已经安全保存，不会进入不兼容的求解器。"
                    )
                )
                return
        previous_result_state = self._capture_analysis_result_state()
        failure = None
        self._set_run_status("正在计算…", "running")
        self._set_analysis_busy(True)
        QApplication.processEvents()
        try:
            config = self._build_form_config()
            result = self.analysis_service.run(
                config,
                algorithm_id=self.analysis_setup.active_algorithm_id,
                parameters=self.analysis_setup.parameter_values(),
            )
            model = result.native_model
            inputs = dict(result.inputs)
            self.current_model = model
            self.current_config = config
            self.json_text.setPlainText(config_to_json(config))
            self._render_plot(model, inputs)
            self._fill_result_tables(model, inputs)
            self._update_analysis_summary(config=config, model=model)
            self._set_result_freshness(False)
            result_tab_index = 0 if self.current_view == "shape" else self.field_result_tab_index
            self.result_tabs.setCurrentIndex(result_tab_index)
            self._set_run_status(f"重构完成 · {model.n_nodes} 节点 / {model.n_elems} 单元", "success")
            message_lines = [
                "重构完成。",
                f"重构方法: {self.analysis_setup.active_algorithm_display_name} "
                f"v{result.algorithm_version}",
                f"节点数: {model.n_nodes}",
                f"单元数: {model.n_elems}",
                f"高斯点数: {inputs['gauss_n']}",
                f"每单元采样点数: {inputs['points_per_element']}",
                f"真实梁厚度: {model.thickness:.6g}",
            ]
            boundary_jumps = element_boundary_jumps(self.current_raw_field)
            strain_jumps = [
                abs(value) * 1.0e6
                for row in boundary_jumps
                for value in (row["top_strain_jump"], row["bottom_strain_jump"])
            ]
            max_strain_jump = max(strain_jumps, default=0.0)
            message_lines.append(f"原始场最大边界应变跳变: {max_strain_jump:.6g} με")
            representation = inputs["plot_options"].get(
                "field_representation", "nodal_average"
            )
            message_lines.append(
                "场显示: 原始单元场"
                if representation == "raw"
                else "场显示: 节点平均连续化（仅后处理，不改变原始解）"
            )
            message_lines.append(
                "三维视图: PyVistaQt / VTK 已启用"
                if self.structure_3d_view.backend_available
                else "三维视图: 当前环境使用二维兼容模式"
            )
            elastic_modulus = inputs.get("material", {}).get("elastic_modulus")
            if elastic_modulus is None:
                message_lines.append("应力后处理: 未设置弹性模量 E")
            else:
                max_stress_mpa = float(np.max(np.abs(self.current_raw_field.stress))) / 1.0e6
                stress_jumps = [
                    abs(value) / 1.0e6
                    for row in boundary_jumps
                    for value in (row["top_stress_jump"], row["bottom_stress_jump"])
                    if value is not None
                ]
                message_lines.append(f"弹性模量 E: {elastic_modulus / 1.0e9:.6g} GPa")
                message_lines.append(f"最大轴向应力绝对值: {max_stress_mpa:.6g} MPa")
                message_lines.append(
                    f"原始场最大边界应力跳变: {max(stress_jumps, default=0.0):.6g} MPa"
                )
                message_lines.append("应力假设: 一维线弹性 σ=Eε")
            self._write_message("\n".join(message_lines))
        except Exception as exc:
            failure = exc
            try:
                self._restore_analysis_result_state(previous_result_state)
            except Exception:
                self._clear_result_views()
        finally:
            self._set_analysis_busy(False)
            self._refresh_input_readiness()
        if failure is not None:
            self._show_error(failure)

    def _render_plot(self, model, inputs):
        elastic_modulus = inputs.get("material", {}).get("elastic_modulus")
        self.current_inputs = inputs
        self.current_raw_field = reconstruct_section_field(
            model,
            points_per_element=inputs["points_per_element"],
            elastic_modulus=elastic_modulus,
            through_thickness_points=9,
        )
        self.current_recovered_field = recover_continuous_section_field(self.current_raw_field)
        visual_section = None
        if self.current_project_document is not None and self.current_project_document.sections:
            try:
                project_nodes = PathBeamEditor.ordered_nodes(
                    self.current_project_document
                )
                project_x = np.asarray(
                    [node.coordinates[0] for node in project_nodes],
                    dtype=float,
                )
                section = self.current_project_document.sections[0]
                if (
                    len(project_x) == len(model.node_x)
                    and np.allclose(project_x, model.node_x)
                    and np.isclose(section.thickness, model.thickness)
                ):
                    visual_section = section
            except (TypeError, ValueError):
                visual_section = None
        self.current_visual_model = structural_model_from_beam(
            model,
            section=visual_section,
        )
        self.result_sequence += 1
        self.current_view = "stress" if self.current_recovered_field.stress is not None else "strain"
        self.view_buttons[self.current_view].setChecked(True)
        self._select_active_field()
        self._render_current_view()

    def _select_active_field(self):
        if self.current_inputs is None:
            self.current_field = None
            return
        representation = self.current_inputs["plot_options"].get(
            "field_representation", "nodal_average"
        )
        self.current_field = (
            self.current_raw_field if representation == "raw" else self.current_recovered_field
        )

    def _switch_view(self, mode):
        if mode not in self.view_buttons:
            return
        self.current_view = mode
        self._refresh_view_context()
        result_tab_index = 0 if mode == "shape" else self.field_result_tab_index
        self.result_tabs.setCurrentIndex(result_tab_index)
        if not self.view_buttons[mode].isChecked():
            self.view_buttons[mode].setChecked(True)
        if self.current_model is None or self.current_field is None:
            self._render_empty_plot()
            return
        self._render_current_view()

    def _switch_visualization_space(self, index):
        if not hasattr(self, "visualization_stack"):
            return
        self.visualization_stack.setCurrentIndex(index)
        key = "3d" if index == 1 else "2d"
        self._refresh_view_context()
        if not self.display_buttons[key].isChecked():
            self.display_buttons[key].setChecked(True)
        if index == 1 and self.current_model is not None and self.current_field is not None:
            thickness_setting = self.current_inputs["plot_options"].get(
                "thickness_scale", "auto"
            )
            thickness_scale = resolve_thickness_scale(self.current_field, thickness_setting)
            self._render_3d_view(thickness_scale)

    def _toggle_focus_mode(self, enabled):
        self.left_panel.setVisible(not enabled)
        self.result_group.setVisible(not enabled)
        self.focus_mode_button.setText("退出专注" if enabled else "专注")
        self.focus_mode_button.setToolTip(
            "恢复输入区和结果表格"
            if enabled
            else "隐藏输入区和结果表格，仅保留可视化视口；再次点击恢复"
        )

    def _switch_scale_mode(self, mode):
        if mode not in self.scale_buttons:
            return
        self._loading_form = True
        try:
            if mode == "true":
                self.thickness_scale_combo.setCurrentIndex(
                    self.thickness_scale_combo.findData(1.0)
                )
                self.equal_axis_check.setChecked(True)
            else:
                self.thickness_scale_combo.setCurrentIndex(
                    self.thickness_scale_combo.findData("auto")
                )
                self.equal_axis_check.setChecked(False)
        finally:
            self._loading_form = False
        self._on_plot_settings_changed()

    def _sync_scale_buttons(self, plot_options=None):
        if not hasattr(self, "scale_buttons"):
            return
        if plot_options is None:
            try:
                plot_options = self._collect_plot_options()
            except (TypeError, ValueError):
                return
        thickness_scale = plot_options.get("thickness_scale", "auto")
        is_true_scale = (
            thickness_scale != "auto"
            and np.isclose(float(thickness_scale), 1.0)
            and bool(plot_options.get("equal_axis", False))
        )
        self.scale_buttons["true" if is_true_scale else "fit"].setChecked(True)

    def _render_current_view(self):
        self._select_active_field()
        if self.current_model is None or self.current_field is None or self.current_inputs is None:
            self._render_empty_plot()
            return

        if hasattr(self, "plot_content_stack"):
            self.plot_content_stack.setCurrentWidget(self.visualization_stack)

        thickness_setting = self.current_inputs["plot_options"].get("thickness_scale", "auto")
        thickness_scale = resolve_thickness_scale(self.current_field, thickness_setting)
        if self.current_view == "shape":
            self._render_shape_view(thickness_scale)
        elif self.current_view == "strain":
            self._render_field_view("strain", thickness_scale)
        elif self.current_field.stress is None:
            self._render_stress_unavailable()
        else:
            self._render_field_view("stress", thickness_scale)
        self._render_3d_view(thickness_scale)

    def _render_3d_view(self, thickness_scale):
        if (
            not hasattr(self, "structure_3d_view")
            or self.current_visual_model is None
            or self.current_model is None
            or self.current_field is None
            or self.current_inputs is None
        ):
            return
        self.current_result_frame = result_frame_from_beam(
            self.current_model,
            self.current_field,
            elements_sensor_data=self.current_inputs["elements_sensor_data"],
            sequence=self.result_sequence,
            time_value=0.0,
            reference_field=self.current_raw_field,
        )
        self.structure_3d_view.set_frame(
            self.current_visual_model,
            self.current_result_frame,
            mode=self.current_view,
            thickness_scale=thickness_scale,
        )

    def _render_shape_view(self, thickness_scale):
        self._clear_figure_overlays()
        plot_options = dict(self.current_inputs["plot_options"])
        plot_options.pop("figsize", None)
        plot_options.pop("thickness_scale", None)
        plot_options.pop("field_representation", None)
        title = plot_options.pop("title", "二维梁重构形态")

        self.current_model.plot_on_axes(
            self.axes,
            points_per_element=self.current_inputs["points_per_element"],
            true_points=self.current_inputs["true_points"],
            title=title,
            show_legend=False,
            **plot_options,
        )
        self.axes.set_axis_on()
        self.axes.set_facecolor(self._theme_color("canvas"))
        self.figure.set_facecolor(self._theme_color("canvas"))
        themed_lines = {
            "原始中性层": self._theme_color("node"),
            "重构后形状": self._theme_color("primary"),
            "重构节点": self._theme_color("focus"),
        }
        for line in self.axes.get_lines():
            if line.get_label() in themed_lines:
                line.set_color(themed_lines[line.get_label()])
        self.axes.title.set_color(self._theme_color("text_strong"))
        self.axes.xaxis.label.set_color(self._theme_color("text_secondary"))
        self.axes.yaxis.label.set_color(self._theme_color("text_secondary"))
        self.axes.tick_params(colors=self._theme_color("text_secondary"))
        self.axes.grid(
            True,
            linestyle=(0, (4, 4)),
            linewidth=0.8,
            color=self._theme_color("grid"),
            alpha=0.76,
        )
        self.axes.spines["left"].set_color(self._theme_color("node"))
        self.axes.spines["bottom"].set_color(self._theme_color("node"))
        compact_plot = self.canvas.width() < 760 or self.canvas.height() < 330
        if compact_plot:
            self.axes.set_title(
                self.axes.get_title(),
                pad=7,
                fontsize=13,
                color=self._theme_color("text_strong"),
                fontweight="semibold",
            )
            self.axes.set_xlabel("变形后 x", fontsize=9)
            self.axes.set_ylabel("y", fontsize=9)
            self.axes.tick_params(labelsize=8.5)

        x_grid, y_grid = self.current_field.display_grid(thickness_scale)
        outline_x = np.concatenate([x_grid[-1], x_grid[0, ::-1]])
        outline_y = np.concatenate([y_grid[-1], y_grid[0, ::-1]])
        self.axes.fill(
            outline_x,
            outline_y,
            facecolor=self._theme_color("primary_soft"),
            edgecolor=self._theme_color("beam"),
            linewidth=0.8,
            alpha=0.54,
            zorder=1.2,
        )
        self.axes.plot(
            x_grid[-1],
            y_grid[-1],
            color=self._theme_color("beam"),
            linewidth=0.7,
            alpha=0.9,
            zorder=1.3,
        )
        self.axes.plot(
            x_grid[0],
            y_grid[0],
            color=self._theme_color("beam"),
            linewidth=0.7,
            alpha=0.9,
            zorder=1.3,
        )
        self._set_view_meta(
            f"真实厚度 {self.current_field.thickness:.6g} · 轮廓显示 ×{thickness_scale:.3g}"
        )
        self._render_plot_legend()
        self.figure.tight_layout(pad=1.0, rect=(0.02, 0.02, 0.98, 0.84))
        self.canvas.draw_idle()

    def _render_field_view(self, field_kind, thickness_scale):
        self._clear_figure_overlays()
        self.axes.clear()
        self.axes.set_axis_on()
        self.axes.set_facecolor(self._theme_color("canvas"))
        self.figure.set_facecolor(self._theme_color("canvas"))
        plot_options = self.current_inputs["plot_options"]
        raw_representation = plot_options.get("field_representation") == "raw"
        compact_plot = self.canvas.width() < 760 or self.canvas.height() < 330

        if field_kind == "stress":
            field_values = self.current_field.stress / 1.0e6
            reference_values = self.current_raw_field.stress / 1.0e6
            field_title = r"轴向应力场  $\sigma_x$"
            colorbar_label = r"$\sigma_x$ / MPa"
        else:
            field_values = self.current_field.strain * 1.0e6
            reference_values = self.current_raw_field.strain * 1.0e6
            field_title = r"轴向应变场  $\varepsilon_x$"
            colorbar_label = r"$\varepsilon_x$ / $\mu\varepsilon$"

        x_grid, y_grid = self.current_field.display_grid(thickness_scale)
        finite_values = reference_values[np.isfinite(reference_values)]
        value_limit = float(np.max(np.abs(finite_values))) if finite_values.size else 1.0
        if value_limit <= 1e-12:
            value_limit = 1.0
        normalization = Normalize(vmin=-value_limit, vmax=value_limit)

        if raw_representation:
            element_ids = np.unique(self.current_field.element_index)
            for element in element_ids:
                indices = np.flatnonzero(self.current_field.element_index == element)
                self.axes.pcolormesh(
                    x_grid[:, indices],
                    y_grid[:, indices],
                    field_values[:, indices],
                    cmap="coolwarm",
                    norm=normalization,
                    shading="gouraud",
                    rasterized=True,
                    zorder=1.0,
                )
                if element != element_ids[-1]:
                    boundary_index = indices[-1]
                    self.axes.plot(
                        x_grid[:, boundary_index],
                        y_grid[:, boundary_index],
                        color=self._theme_color("beam"),
                        linewidth=0.65,
                        linestyle=(0, (2, 2)),
                        alpha=0.8,
                        zorder=2.0,
                    )
        else:
            self.axes.pcolormesh(
                x_grid,
                y_grid,
                field_values,
                cmap="coolwarm",
                norm=normalization,
                shading="gouraud",
                rasterized=True,
                zorder=1.0,
            )

        self.axes.plot(
            x_grid[-1],
            y_grid[-1],
            color=self._theme_color("beam"),
            linewidth=0.8,
        )
        self.axes.plot(
            x_grid[0],
            y_grid[0],
            color=self._theme_color("beam"),
            linewidth=0.8,
        )
        self.axes.plot(
            self.current_field.x_deformed,
            self.current_field.y_deformed,
            color="white",
            linewidth=0.8,
            alpha=0.8,
        )

        if plot_options.get("show_original", True):
            self.axes.plot(
                self.current_model.node_x,
                np.zeros_like(self.current_model.node_x),
                linestyle=(0, (4, 3)),
                color=self._theme_color("node"),
                linewidth=1.0,
                alpha=0.7,
            )
        if plot_options.get("show_nodes", True):
            u_node, v_node, _ = self.current_model.nodal_results()
            self.axes.plot(
                self.current_model.node_x + u_node,
                v_node,
                linestyle="none",
                marker="o",
                markersize=4.5,
                markerfacecolor=self._theme_color("primary"),
                markeredgecolor="white",
                markeredgewidth=0.7,
            )

        self.axes.autoscale_view()
        self.axes.margins(x=0.04, y=0.14)
        label_font_size = 9 if compact_plot else 10
        title_font_size = 13 if compact_plot else 15
        self.axes.set_xlabel(
            "变形后 x",
            color=self._theme_color("text_secondary"),
            fontsize=label_font_size,
        )
        self.axes.set_ylabel(
            "y",
            color=self._theme_color("text_secondary"),
            fontsize=label_font_size,
        )
        self.axes.set_title(
            field_title,
            pad=8 if compact_plot else 11,
            fontsize=title_font_size,
            color=self._theme_color("text_strong"),
            fontweight="semibold",
        )
        self.axes.grid(
            True,
            linestyle=(0, (4, 4)),
            linewidth=0.7,
            color=self._theme_color("grid"),
            alpha=0.72,
        )
        self.axes.tick_params(
            colors=self._theme_color("text_secondary"),
            labelsize=8.5 if compact_plot else 9.5,
        )
        self.axes.spines["top"].set_visible(False)
        self.axes.spines["right"].set_visible(False)
        self.axes.spines["left"].set_color(self._theme_color("node"))
        self.axes.spines["bottom"].set_color(self._theme_color("node"))

        y_limits = plot_options.get("y_limits")
        if y_limits is not None:
            self.axes.set_ylim(float(y_limits[0]), float(y_limits[1]))
        if plot_options.get("equal_axis", False):
            self.axes.set_aspect("equal", adjustable="datalim")

        scalar_mappable = ScalarMappable(norm=normalization, cmap="coolwarm")
        scalar_mappable.set_array([])
        self._field_colorbar = self.figure.colorbar(
            scalar_mappable,
            ax=self.axes,
            pad=0.018,
            fraction=0.045,
        )
        self._field_colorbar.set_label(
            colorbar_label,
            color=self._theme_color("text_secondary"),
            fontsize=8.5 if compact_plot else 9.5,
            labelpad=7,
        )
        self._field_colorbar.ax.tick_params(
            colors=self._theme_color("text_secondary"),
            labelsize=8 if compact_plot else 8.5,
            pad=2,
        )

        if field_kind == "stress":
            elastic_modulus_gpa = self.current_field.elastic_modulus / 1.0e9
            if raw_representation:
                jumps = element_boundary_jumps(self.current_raw_field)
                stress_jumps = [
                    abs(value) / 1.0e6
                    for row in jumps
                    for value in (row["top_stress_jump"], row["bottom_stress_jump"])
                    if value is not None
                ]
                max_jump = max(stress_jumps, default=0.0)
                self._set_view_meta(
                    f"原始场 · 最大边界跳变 {max_jump:.3g} MPa · E {elastic_modulus_gpa:.6g} GPa"
                )
            else:
                self._set_view_meta(
                    f"节点平均连续化（后处理） · E {elastic_modulus_gpa:.6g} GPa"
                )
        else:
            if raw_representation:
                jumps = element_boundary_jumps(self.current_raw_field)
                strain_jumps = [
                    abs(value) * 1.0e6
                    for row in jumps
                    for value in (row["top_strain_jump"], row["bottom_strain_jump"])
                ]
                self._set_view_meta(
                    f"原始场 · 最大边界跳变 {max(strain_jumps, default=0.0):.3g} με"
                )
            else:
                self._set_view_meta("节点平均连续化（后处理） · 原始场可在左侧切换")

        self.figure.tight_layout(pad=1.0)
        self.canvas.draw_idle()

    def _render_stress_unavailable(self):
        self._clear_figure_overlays()
        self.axes.clear()
        self.axes.set_axis_off()
        self.axes.set_facecolor(self._theme_color("canvas"))
        self.figure.set_facecolor(self._theme_color("canvas"))
        self.axes.text(
            0.5,
            0.55,
            "尚未设置弹性模量 E",
            transform=self.axes.transAxes,
            ha="center",
            va="center",
            fontsize=17,
            color=self._theme_color("text_strong"),
            fontweight="semibold",
        )
        self.axes.text(
            0.5,
            0.45,
            "在“模型参数”中填写 E 后重新运行，可按 σ=Eε 查看轴向应力",
            transform=self.axes.transAxes,
            ha="center",
            va="center",
            fontsize=10,
            color=self._theme_color("text_muted"),
        )
        self._set_view_meta("应力视图需要弹性模量 E · 当前仅提供应变场")
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw_idle()

    def _render_plot_legend(self):
        for legend in list(self.figure.legends):
            legend.remove()

        handles, labels = self.axes.get_legend_handles_labels()
        unique = []
        seen = set()
        core_labels = {"原始中性层", "重构后形状", "重构节点"}
        for handle, label in zip(handles, labels):
            if not label or label in seen or label not in core_labels:
                continue
            seen.add(label)
            unique.append((handle, label))

        if not unique:
            return

        legend_handles = [handle for handle, _label in unique]
        legend_labels = [label for _handle, label in unique]
        self.figure.legend(
            legend_handles,
            legend_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.985),
            ncol=len(legend_labels),
            frameon=False,
            labelcolor=self._theme_color("text_secondary"),
            fontsize=8.5,
            handlelength=2.0,
            handletextpad=0.6,
            columnspacing=1.3,
        )

    def _fill_result_tables(self, model, inputs):
        node_rows = []
        for row in model.nodal_results_table():
            node_rows.append(
                {
                    "节点": row["节点"],
                    "x坐标": f"{row['x坐标']:.6f}",
                    "u位移": f"{row['u位移']:.6e}",
                    "v位移": f"{row['v位移']:.6e}",
                    "转角phi": f"{row['转角phi']:.6e}",
                }
            )
        self.node_result_table.set_rows(node_rows)
        self.result_tabs.setTabText(
            self.node_result_tab_index,
            f"节点结果 · {len(node_rows)}",
        )

        query_rows = []
        for idx, row in enumerate(model.evaluate_displacement_at_points(inputs["query_xs"]), start=1):
            query_rows.append(
                {
                    "序号": idx,
                    "x": f"{row['x']:.6f}",
                    "u": f"{row['u']:.6e}",
                    "v": f"{row['v']:.6e}",
                }
            )
        self.query_result_table.set_rows(query_rows)
        self.result_tabs.setTabText(
            self.query_result_tab_index,
            f"查询结果 · {len(query_rows)}",
        )

        compare_rows = []
        for row in model.compare_true_points(inputs["true_points"]):
            compare_rows.append(
                {
                    "序号": row["序号"],
                    "标签": row["标签"],
                    "x": f"{row['x']:.6f}",
                    "u_实测": f"{row['u_实测']:.6e}",
                    "v_实测": f"{row['v_实测']:.6e}",
                    "u_重构": f"{row['u_重构']:.6e}",
                    "v_重构": f"{row['v_重构']:.6e}",
                    "Δu": f"{row['Δu']:.6e}",
                    "Δv": f"{row['Δv']:.6e}",
                }
            )
        self.compare_result_table.set_rows(compare_rows)
        self.result_tabs.setTabText(
            self.compare_result_tab_index,
            f"实测对比 · {len(compare_rows)}",
        )

        self._fill_field_result_table()

    def _fill_field_result_table(self):
        field_rows = []
        if self.current_field is not None:
            for row in section_field_rows(self.current_field):
                stress_top = row["stress_top"]
                stress_bottom = row["stress_bottom"]
                field_rows.append(
                    {
                        "序号": row["sequence"],
                        "x": f"{row['x']:.6f}",
                        "上表面应变": f"{row['strain_top'] * 1.0e6:.6e}",
                        "下表面应变": f"{row['strain_bottom'] * 1.0e6:.6e}",
                        "上表面应力": "--" if stress_top is None else f"{stress_top / 1.0e6:.6e}",
                        "下表面应力": "--" if stress_bottom is None else f"{stress_bottom / 1.0e6:.6e}",
                    }
                )
        self.field_result_table.set_rows(field_rows)
        if hasattr(self, "field_result_tab_index"):
            if self.current_field is None:
                tab_text = "截面场"
            elif self.current_field.representation == "raw":
                tab_text = f"截面场 · 原始 · {len(field_rows)}"
            else:
                tab_text = f"截面场 · 连续化 · {len(field_rows)}"
            self.result_tabs.setTabText(self.field_result_tab_index, tab_text)

    def _write_message(self, message):
        self.message_text.setPlainText(message)
        self.statusBar().showMessage(str(message).splitlines()[0], 6000)

    def show_appearance_settings(self):
        previous_theme_id = self.current_theme_id
        dialog = AppearanceDialog(previous_theme_id, self)
        dialog.theme_previewed.connect(
            lambda theme_id: self.apply_theme(theme_id, persist=False)
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_theme(dialog.selected_theme_id, persist=True)
            self.statusBar().showMessage(
                f"已使用“{resolve_theme(self.current_theme_id).name}”界面风格",
                4000,
            )
        else:
            self.apply_theme(previous_theme_id, persist=False)

    def apply_theme(self, theme_id, *, persist=False):
        self.current_theme_id = apply_application_theme(
            theme_id,
            persist=persist,
            update_stylesheet=persist,
        )
        self.setStyleSheet(
            compose_stylesheet(APP_STYLESHEET + STUDIO_THEME, self.current_theme_id)
        )
        self._update_theme_shadow()
        if hasattr(self, "measurement_preview"):
            self.measurement_preview.set_theme(self.current_theme_id)
        if hasattr(self, "structure_3d_view"):
            self.structure_3d_view.apply_theme(self.current_theme_id)
        for dialog in self.findChildren(BeamModelerDialog):
            dialog.apply_theme(self.current_theme_id)
        if hasattr(self, "figure"):
            if self.current_model is None or self.current_field is None:
                self._render_empty_plot()
            else:
                self._render_current_view()

    def _update_theme_shadow(self):
        if not hasattr(self, "top_bar_shadow"):
            return
        shadow = QColor(resolve_theme(self.current_theme_id).color("primary"))
        shadow.setAlpha(26)
        self.top_bar_shadow.setColor(shadow)

    def _theme_color(self, role):
        return resolve_theme(self.current_theme_id).color(role)

    def _show_error(self, exc):
        message = str(exc)
        self._set_run_status("输入或计算失败", "error")
        self._write_message(f"运行失败：\n{message}")
        QMessageBox.critical(self, "错误", message)

    def closeEvent(self, event):
        if not self._confirm_save_before_action():
            event.ignore()
            return
        self.shutdown()
        event.accept()

    def shutdown(self):
        if self._is_shut_down:
            return
        self._is_shut_down = True
        for dialog in self.findChildren(BeamModelerDialog):
            dialog.shutdown()
        if hasattr(self, "structure_3d_view"):
            self.structure_3d_view.shutdown()


def _apply_startup_request(window, request):
    if request.action == START_NEW:
        window.new_project()
        return
    if request.action == START_OPEN:
        window.load_project_path(request.project_path)
        return
    if request.action == START_SAMPLE:
        window.load_sample_data(initial=False)
        return
    if request.action == START_WORKSPACE:
        window.current_project_path = None
        window._apply_project_document(
            empty_beam_project(),
            dirty=False,
            status_text="空白工作台 · 待配置",
        )
        return
    raise ValueError(f"未知启动操作：{request.action}")


def launch_app(*, show_start_center=True):
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("iFEM")
    apply_application_theme(load_theme_id(), app=app)

    request = None
    if show_start_center:
        start_center = StartCenterDialog()
        if start_center.exec() != QDialog.DialogCode.Accepted:
            return 0
        if start_center.request is None:
            return 0
        request = start_center.request
        apply_application_theme(
            getattr(start_center, "theme_id", current_theme_id(app)),
            app=app,
            persist=True,
        )

    window = ReconstructionMainWindow()
    window.show()
    app._ifem_main_window = window
    if hasattr(window, "shutdown"):
        app.aboutToQuit.connect(window.shutdown)
    if request is not None:
        QTimer.singleShot(0, lambda: _apply_startup_request(window, request))
    if owns_app:
        try:
            return app.exec()
        finally:
            window.shutdown()
    return 0
