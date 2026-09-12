"""Functional, animated start center shown before the main workbench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ifem.infrastructure.project_library import ProjectLibrary
from ifem.ui.project_library import ProjectLibraryDialog
from ifem.ui.start_animation import BeamReconstructionAnimation
from ifem.ui.theme import (
    compose_stylesheet, current_theme_id, resolve_theme,
)


START_NEW = "new"
START_OPEN = "open"
START_SAMPLE = "sample"
START_WORKSPACE = "workspace"
_START_ACTIONS = {START_NEW, START_OPEN, START_SAMPLE, START_WORKSPACE}
# Retained as an editable static illustration, not loaded by the start center.
START_CENTER_HERO_PATH = Path(__file__).with_name("assets") / "ifem_inverse_workflow.svg"
BeamWorkflowPreview = BeamReconstructionAnimation


@dataclass(frozen=True)
class StartupRequest:
    """A start-center selection consumed by the application launcher."""

    action: str
    project_path: Path | None = None

    def __post_init__(self):
        if self.action not in _START_ACTIONS:
            raise ValueError(f"未知启动操作：{self.action}")
        if self.action == START_OPEN and self.project_path is None:
            raise ValueError("打开项目操作必须包含项目路径。")
        if self.action != START_OPEN and self.project_path is not None:
            raise ValueError("仅打开项目操作可以包含项目路径。")


def _start_stylesheet(theme_id):
    c = resolve_theme(theme_id).colors
    return compose_stylesheet("", theme_id) + f"""
QDialog#startCenter, QFrame#startShell {{
    background: {c['surface_subtle']}; color: {c['text']}; border: none;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 13px;
}}
QFrame#startActions {{ background: transparent; border: none; }}
QLabel#startBrandMark {{
    color: {c['on_primary']}; background: {c['primary']};
    border: none; border-radius: 9px; font-size: 17px; font-weight: 700;
}}
QLabel#startBrandTitle {{ color: {c['text_strong']}; font-size: 25px; font-weight: 600; }}
QLabel#startHeadline {{ color: {c['text_strong']}; font-size: 40px; font-weight: 500; }}
QLabel#startDescription {{ color: {c['text_secondary']}; font-size: 14px; }}
QLabel#startArtCaption {{ color: {c['text_muted']}; font-size: 12px; }}
QPushButton#startPrimary {{
    background: {c['primary']}; color: {c['on_primary']}; border: 1px solid {c['primary']};
    border-radius: 6px; padding: 8px 18px; min-height: 30px; font-size: 14px; font-weight: 500;
}}
QPushButton#startPrimary:hover {{ background: {c['primary_hover']}; }}
QPushButton#startPrimary:pressed {{ background: {c['primary_pressed']}; }}
QPushButton#startPrimary:focus {{ border: 2px solid {c['focus']}; padding: 7px 17px; }}
QPushButton#startOpen {{
    background: {c['surface']}; color: {c['text_strong']}; border: 1px solid {c['border_strong']};
    border-radius: 6px; padding: 8px 18px; min-height: 30px; font-size: 14px; font-weight: 500;
}}
QPushButton#startOpen:hover {{ background: {c['primary_soft']}; border-color: {c['primary']}; }}
QPushButton#startOpen:pressed {{ background: {c['primary_tint']}; }}
QPushButton#startOpen:focus {{ border: 2px solid {c['focus']}; padding: 7px 17px; }}
QPushButton#startSecondary, QPushButton#startQuiet, QPushButton#startMotion {{
    background: transparent; color: {c['text_secondary']}; border: 1px solid transparent;
    border-radius: 6px; padding: 6px 8px; min-height: 20px; font-size: 12px;
}}
QPushButton#startSecondary:hover, QPushButton#startQuiet:hover, QPushButton#startMotion:hover {{
    color: {c['primary']}; background: {c['primary_soft']};
}}
QPushButton#startSecondary:focus, QPushButton#startQuiet:focus, QPushButton#startMotion:focus {{
    border-color: {c['focus']};
}}
QPushButton#startSecondary:pressed, QPushButton#startQuiet:pressed, QPushButton#startMotion:pressed {{
    background: {c['primary_tint']};
}}
"""


class StartCenterDialog(QDialog):
    """A project entry point with a lightweight, pausable method demonstration."""

    def __init__(self, parent=None, *, theme_id=None, project_library=None):
        super().__init__(parent)
        self.request: StartupRequest | None = None
        self.project_library = project_library or ProjectLibrary()
        self.theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self.setObjectName("startCenter")
        self.setWindowTitle("iFEM")
        self.setModal(True)
        self.resize(1080, 640)
        self.setMinimumSize(900, 590)
        self.setStyleSheet(_start_stylesheet(self.theme_id))
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 40, 28)
        root.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(11)
        brand_mark = QLabel("iF")
        brand_mark.setObjectName("startBrandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(32, 32)
        header.addWidget(brand_mark)
        self.brand_title = QLabel("iFEM")
        self.brand_title.setObjectName("startBrandTitle")
        header.addWidget(self.brand_title)
        header.addStretch(1)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(28)
        body.addWidget(self._build_actions())
        self.preview = BeamWorkflowPreview(theme_id=self.theme_id)
        self.preview.setMinimumSize(430, 390)
        self.preview.setAccessibleName("从离散应变观测到连续位移形态的动态方法示意")
        self.preview.setToolTip(
            "橙色贴片表示应变测点，网格展示重构形态。\n"
            "演示仅表达逆有限元流程，变形已放大，不是真实计算结果。"
        )
        art = QVBoxLayout()
        art.setSpacing(0)
        art.addWidget(self.preview, 1)
        art_footer = QHBoxLayout()
        art_footer.setContentsMargins(20, 0, 4, 0)
        caption = QLabel("方法演示，非计算结果")
        caption.setObjectName("startArtCaption")
        art_footer.addWidget(caption)
        art_footer.addStretch(1)
        self.motion_button = QPushButton()
        self.motion_button.setObjectName("startMotion")
        self.motion_button.setAutoDefault(True)
        self.motion_button.setCheckable(True)
        self.motion_button.setToolTip("暂停或播放形态演示，不影响项目数据")
        settings = QSettings("iFEM", "iFEM Reconstruction")
        saved_paused = settings.value("appearance/startAnimationPaused", False, type=bool)
        if saved_paused:
            self.preview.set_paused(True)
        self.motion_button.setChecked(self.preview.is_paused)
        self._update_motion_label()
        self.motion_button.toggled.connect(self._toggle_motion)
        art_footer.addWidget(self.motion_button)
        art.addLayout(art_footer)
        body.addLayout(art, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        self.exit_button = QPushButton("退出")
        self.exit_button.setObjectName("startQuiet")
        self.exit_button.setAutoDefault(True)
        self.exit_button.setToolTip("关闭启动中心并退出软件（Esc）")
        self.exit_button.clicked.connect(self.reject)
        footer.addWidget(self.exit_button)
        footer.addStretch(1)
        root.addLayout(footer)

        self.setTabOrder(self.new_button, self.open_button)
        self.setTabOrder(self.open_button, self.sample_button)
        self.setTabOrder(self.sample_button, self.workspace_button)
        self.setTabOrder(self.workspace_button, self.motion_button)
        self.setTabOrder(self.motion_button, self.exit_button)
        self.new_button.setFocus()

    def _build_actions(self):
        panel = QFrame()
        panel.setObjectName("startActions")
        panel.setMinimumWidth(256)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        layout.addStretch(1)
        self.headline = QLabel("从应变\n重构形态")
        self.headline.setObjectName("startHeadline")
        layout.addWidget(self.headline)
        self.action_description = QLabel("逆有限元结构重构工作台")
        self.action_description.setObjectName("startDescription")
        layout.addWidget(self.action_description)
        layout.addSpacing(20)

        self.new_button = QPushButton("新建项目")
        self.new_button.setObjectName("startPrimary")
        self.new_button.setDefault(True)
        self.new_button.setShortcut("Ctrl+N")
        self.new_button.setToolTip("打开交互建模器，从二维或三维梁模型开始")
        self.new_button.clicked.connect(lambda: self._select(START_NEW))
        layout.addWidget(self.new_button)
        self.open_button = QPushButton("打开项目")
        self.open_button.setObjectName("startOpen")
        self.open_button.setAutoDefault(True)
        self.open_button.setShortcut("Ctrl+O")
        self.open_button.setToolTip("从 iFEM 项目库选择已保存项目")
        self.open_button.clicked.connect(self._choose_project)
        layout.addWidget(self.open_button)

        secondary = QHBoxLayout()
        secondary.setSpacing(12)
        self.sample_button = QPushButton("示例工程")
        self.sample_button.setObjectName("startSecondary")
        self.sample_button.setAutoDefault(True)
        self.sample_button.setToolTip("载入内置二维梁案例，快速查看完整流程")
        self.sample_button.clicked.connect(lambda: self._select(START_SAMPLE))
        self.workspace_button = QPushButton("空白工作台")
        self.workspace_button.setObjectName("startSecondary")
        self.workspace_button.setAutoDefault(True)
        self.workspace_button.setToolTip("进入无测点的空白工作台，稍后再配置模型")
        self.workspace_button.clicked.connect(lambda: self._select(START_WORKSPACE))
        secondary.addWidget(self.sample_button)
        secondary.addWidget(self.workspace_button)
        layout.addLayout(secondary)
        layout.addStretch(1)
        return panel

    def _update_motion_label(self):
        if self.preview.reduced_motion:
            self.motion_button.setText("已减少动态")
            self.motion_button.setEnabled(False)
            self.motion_button.setToolTip("已遵循减少动态偏好，以静态形态展示方法")
        else:
            self.motion_button.setText("播放演示" if self.preview.is_paused else "暂停演示")
        self.motion_button.setAccessibleName(self.motion_button.text())

    def _toggle_motion(self, paused):
        self.preview.set_paused(paused)
        self._update_motion_label()
        QSettings("iFEM", "iFEM Reconstruction").setValue(
            "appearance/startAnimationPaused", bool(paused),
        )

    def _select(self, action):
        self.request = StartupRequest(action)
        self.accept()

    def _choose_project(self):
        paused = self.preview.is_paused
        self.preview.set_paused(True)
        try:
            path = ProjectLibraryDialog.choose_project(
                self, library=self.project_library, theme_id=self.theme_id,
            )
        finally:
            self.preview.set_paused(paused)
        if not path:
            return
        self.request = StartupRequest(START_OPEN, Path(path))
        self.accept()

    def done(self, result):
        self.preview.shutdown()
        super().done(result)


__all__ = [
    "BeamWorkflowPreview", "START_NEW", "START_OPEN", "START_SAMPLE",
    "START_WORKSPACE", "START_CENTER_HERO_PATH", "StartCenterDialog", "StartupRequest",
]
