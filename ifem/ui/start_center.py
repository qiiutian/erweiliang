"""Functional start center shown before the main iFEM workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ifem.infrastructure.project_library import ProjectLibrary
from ifem.ui.project_library import ProjectLibraryDialog
from ifem.ui.theme import (
    ThemePicker,
    apply_application_theme,
    compose_stylesheet,
    current_theme_id,
    resolve_theme,
)


START_NEW = "new"
START_OPEN = "open"
START_SAMPLE = "sample"
START_WORKSPACE = "workspace"
_START_ACTIONS = {START_NEW, START_OPEN, START_SAMPLE, START_WORKSPACE}
START_CENTER_HERO_PATH = (
    Path(__file__).with_name("assets") / "start_center_hero.png"
)


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


START_CENTER_STYLESHEET = """
QDialog#startCenter {
    color: #23302a;
    background: #eef2ef;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 13px;
}
QFrame#startShell {
    background: #ffffff;
    border: 1px solid #d7e0da;
    border-radius: 20px;
}
QLabel#startBrandMark {
    color: #ffffff;
    background: #365b49;
    border: 1px solid #2e4e3e;
    border-radius: 11px;
    font-family: "Avenir Next";
    font-size: 17px;
    font-weight: 700;
}
QLabel#startBrandTitle {
    color: #1f2c25;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC";
    font-size: 20px;
    font-weight: 700;
}
QFrame#startActions {
    background: #f8fafb;
    border: 1px solid #d7e0da;
    border-radius: 14px;
}
QFrame#startActionAccent {
    background: #365b49;
    border: none;
    border-radius: 2px;
}
QLabel#startHeadline {
    color: #203128;
    font-size: 25px;
    font-weight: 700;
}
QLabel#startDescription {
    color: #657168;
    font-size: 12px;
}
QLabel#startFileHint {
    color: #77827b;
    font-size: 10px;
}
QPushButton {
    min-height: 44px;
    padding: 0 16px;
    color: #3d4d43;
    background: #ffffff;
    border: 1px solid #cbd7cf;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover {
    color: #26382d;
    background: #f1f5f2;
    border-color: #9eafa3;
}
QPushButton:pressed {
    background: #e6ece8;
}
QPushButton:focus {
    border: 2px solid #527862;
}
QPushButton#startPrimary {
    min-height: 52px;
    color: #ffffff;
    background: #365b49;
    border: 1px solid #2f503f;
    font-size: 14px;
}
QPushButton#startPrimary:hover {
    background: #2d4e3e;
    border-color: #284638;
}
QPushButton#startQuiet {
    min-height: 35px;
    color: #536158;
    background: transparent;
    border: 1px solid transparent;
    padding: 0 8px;
}
QPushButton#startQuiet:hover {
    color: #2f5945;
    background: #ffffff;
    border-color: #d7e0da;
}
QFrame#startDivider {
    color: #e1e7e3;
    background: #e1e7e3;
    border: none;
}
"""


class BeamWorkflowPreview(QWidget):
    """Small code-drawn product visual; no rendering backend is required."""

    def __init__(self, parent=None, *, theme_id=None):
        super().__init__(parent)
        self._theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self._hero_pixmap = QPixmap(str(START_CENTER_HERO_PATH))
        self.setObjectName("startPreview")
        self.setMinimumSize(430, 390)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("结构建模、测点配置、求解与结果可视化流程示意")
        self.setToolTip("从梁模型和测点布置进入逆有限元重构结果")

    @property
    def has_hero_image(self):
        return not self._hero_pixmap.isNull()

    def set_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        self.update()

    def _color(self, role):
        return QColor(resolve_theme(self._theme_id).color(role))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)

        background = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        background.setColorAt(0.0, self._color("surface"))
        background.setColorAt(1.0, self._color("primary_soft"))
        painter.setPen(QPen(self._color("border"), 1.0))
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(bounds, 14.0, 14.0)

        content = bounds.adjusted(30.0, 26.0, -30.0, -24.0)
        if self.has_hero_image:
            self._draw_hero_image(painter, content)
        else:
            self._draw_grid(painter, content)
            self._draw_structure(painter, content)
        self._draw_header(painter, content)
        self._draw_flow(painter, content)

    def _draw_hero_image(self, painter, content):
        target = QRectF(
            content.left() - 5.0,
            content.top() + 42.0,
            content.width() + 10.0,
            content.height() - 93.0,
        )
        target_size = target.size().toSize()
        scaled = self._hero_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        source = QRectF(
            max(0.0, (scaled.width() - target.width()) / 2.0),
            max(0.0, (scaled.height() - target.height()) / 2.0),
            target.width(),
            target.height(),
        )
        clip = QPainterPath()
        clip.addRoundedRect(target, 10.0, 10.0)
        painter.save()
        painter.setClipPath(clip)
        painter.drawPixmap(target, scaled, source)

        veil = QLinearGradient(target.topLeft(), target.bottomLeft())
        top = self._color("surface")
        top.setAlpha(105)
        clear = self._color("surface")
        clear.setAlpha(0)
        bottom = self._color("surface")
        bottom.setAlpha(75)
        veil.setColorAt(0.0, top)
        veil.setColorAt(0.20, clear)
        veil.setColorAt(0.78, clear)
        veil.setColorAt(1.0, bottom)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(veil))
        painter.drawRect(target)
        painter.restore()

    def _draw_header(self, painter, content):
        painter.setPen(self._color("text_strong"))
        painter.setFont(QFont("Avenir Next", 13, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(content.left(), content.top(), content.width(), 24.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "结构场",
        )

    def _draw_grid(self, painter, content):
        grid_top = content.top() + 48.0
        grid_bottom = content.bottom() - 62.0
        grid_color = self._color("grid")
        grid_color.setAlpha(150)
        painter.setPen(QPen(grid_color, 1.0, Qt.PenStyle.DotLine))
        for index in range(1, 6):
            x = content.left() + content.width() * index / 6.0
            painter.drawLine(QPointF(x, grid_top), QPointF(x, grid_bottom))
        for index in range(1, 4):
            y = grid_top + (grid_bottom - grid_top) * index / 4.0
            painter.drawLine(QPointF(content.left(), y), QPointF(content.right(), y))

    def _draw_structure(self, painter, content):
        left = content.left() + 20.0
        right = content.right() - 18.0
        baseline_y = content.top() + content.height() * 0.62
        curve = QPainterPath(QPointF(left, baseline_y + 20.0))
        curve.cubicTo(
            QPointF(left + (right - left) * 0.25, baseline_y + 18.0),
            QPointF(left + (right - left) * 0.34, baseline_y - 110.0),
            QPointF(left + (right - left) * 0.56, baseline_y - 80.0),
        )
        curve.cubicTo(
            QPointF(left + (right - left) * 0.75, baseline_y - 54.0),
            QPointF(left + (right - left) * 0.82, baseline_y + 2.0),
            QPointF(right, baseline_y + 6.0),
        )

        glow = self._color("primary")
        glow.setAlpha(24)
        painter.setPen(
            QPen(
                glow,
                34.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(curve)

        painter.setPen(
            QPen(
                self._color("beam_fill"),
                20.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(curve)

        field_gradient = QLinearGradient(left, baseline_y, right, baseline_y)
        field_gradient.setColorAt(0.0, self._color("primary"))
        field_gradient.setColorAt(0.46, self._color("focus"))
        field_gradient.setColorAt(0.72, QColor("#C48A58"))
        field_gradient.setColorAt(1.0, self._color("sensor"))
        painter.setPen(
            QPen(
                QBrush(field_gradient),
                9.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPath(curve)

        percentages = (0.0, 0.26, 0.52, 0.76, 1.0)
        for percentage in percentages:
            point = curve.pointAtPercent(percentage)
            painter.setPen(QPen(self._color("primary"), 2.0))
            painter.setBrush(self._color("surface"))
            painter.drawEllipse(point, 5.5, 5.5)

        for percentage in (0.15, 0.38, 0.63, 0.86):
            point = curve.pointAtPercent(percentage)
            painter.save()
            painter.translate(point)
            painter.rotate(-curve.angleAtPercent(percentage))
            painter.setPen(QPen(self._color("sensor_dark"), 1.0))
            painter.setBrush(self._color("sensor"))
            painter.drawRoundedRect(QRectF(-10.0, -14.0, 20.0, 8.0), 3.0, 3.0)
            painter.restore()

        reference = self._color("node")
        reference.setAlpha(160)
        painter.setPen(QPen(reference, 1.1, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(left, baseline_y + 50.0),
            QPointF(right, baseline_y + 50.0),
        )

    def _draw_flow(self, painter, content):
        labels = ("建模", "测点", "求解", "结果")
        y = content.bottom() - 31.0
        segment_width = content.width() / len(labels)
        first_x = content.left() + segment_width * 0.5
        last_x = content.right() - segment_width * 0.5
        painter.setPen(QPen(self._color("divider"), 1.5))
        painter.drawLine(QPointF(first_x, y), QPointF(last_x, y))
        for index, label in enumerate(labels):
            center_x = content.left() + segment_width * (index + 0.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color("primary"))
            painter.drawEllipse(QPointF(center_x, y), 3.5, 3.5)
            painter.setPen(self._color("text_secondary"))
            painter.setFont(QFont("Avenir Next", 8, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(
                    content.left() + segment_width * index,
                    y + 8.0,
                    segment_width,
                    18.0,
                ),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )


class StartCenterDialog(QDialog):
    """Project entry point displayed before constructing the main window."""

    def __init__(self, parent=None, *, theme_id=None, project_library=None):
        super().__init__(parent)
        self.request: StartupRequest | None = None
        self.project_library = project_library or ProjectLibrary()
        self.theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self.setObjectName("startCenter")
        self.setWindowTitle("iFEM")
        self.setModal(True)
        self.resize(1040, 620)
        self.setMinimumSize(900, 590)
        self.setStyleSheet(compose_stylesheet(START_CENTER_STYLESHEET, self.theme_id))
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("startShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(26, 22, 26, 24)
        shell_layout.setSpacing(18)
        self.shell_shadow = QGraphicsDropShadowEffect(shell)
        self.shell_shadow.setBlurRadius(28)
        self.shell_shadow.setOffset(0, 7)
        shell.setGraphicsEffect(self.shell_shadow)
        self._update_shadow()
        root.addWidget(shell)

        header = QHBoxLayout()
        header.setSpacing(12)
        brand_mark = QLabel("iF")
        brand_mark.setObjectName("startBrandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(42, 42)
        header.addWidget(brand_mark)

        self.brand_title = QLabel("iFEM")
        self.brand_title.setObjectName("startBrandTitle")
        self.brand_title.setWordWrap(False)
        header.addWidget(self.brand_title)
        header.addStretch(1)
        self.theme_picker = ThemePicker(
            self.theme_id,
            compact=True,
            show_swatches=False,
            label_text="外观",
        )
        self.theme_picker.theme_changed.connect(self._theme_changed)
        header.addWidget(self.theme_picker, 0, Qt.AlignmentFlag.AlignVCenter)
        shell_layout.addLayout(header)

        divider = QFrame()
        divider.setObjectName("startDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        shell_layout.addWidget(divider)

        body = QHBoxLayout()
        body.setSpacing(24)
        self.preview = BeamWorkflowPreview(theme_id=self.theme_id)
        body.addWidget(self.preview, 7)
        body.addWidget(self._build_actions(), 4)
        shell_layout.addLayout(body, 1)

    def _build_actions(self):
        panel = QFrame()
        panel.setObjectName("startActions")
        panel.setMinimumWidth(292)
        panel.setMaximumWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 28, 24, 22)
        layout.setSpacing(9)

        accent = QFrame()
        accent.setObjectName("startActionAccent")
        accent.setFixedSize(34, 3)
        layout.addWidget(accent)
        layout.addSpacing(7)

        self.headline = QLabel("开始工作")
        self.headline.setObjectName("startHeadline")
        self.headline.setWordWrap(False)
        layout.addWidget(self.headline)

        self.action_description = QLabel("选择项目入口")
        self.action_description.setObjectName("startDescription")
        self.action_description.setWordWrap(False)
        layout.addWidget(self.action_description)
        layout.addSpacing(15)

        self.new_button = QPushButton("新建项目")
        self.new_button.setObjectName("startPrimary")
        self.new_button.setDefault(True)
        self.new_button.setShortcut("Ctrl+N")
        self.new_button.setToolTip("打开交互建模器，从二维或三维梁模型开始")
        self.new_button.clicked.connect(lambda: self._select(START_NEW))
        layout.addWidget(self.new_button)

        self.open_button = QPushButton("打开项目")
        self.open_button.setShortcut("Ctrl+O")
        self.open_button.setToolTip("从 iFEM 项目库选择已保存项目")
        self.open_button.clicked.connect(self._choose_project)
        layout.addWidget(self.open_button)
        layout.addSpacing(3)

        secondary = QHBoxLayout()
        secondary.setSpacing(8)
        self.sample_button = QPushButton("示例工程")
        self.sample_button.setToolTip("载入内置二维梁案例，快速查看完整流程")
        self.sample_button.clicked.connect(lambda: self._select(START_SAMPLE))
        self.workspace_button = QPushButton("空白工作台")
        self.workspace_button.setToolTip("进入无测点的空白工作台，稍后再配置模型")
        self.workspace_button.clicked.connect(lambda: self._select(START_WORKSPACE))
        secondary.addWidget(self.sample_button)
        secondary.addWidget(self.workspace_button)
        layout.addLayout(secondary)
        layout.addStretch(1)

        file_hint = QLabel("项目文件 · .ifemproj")
        file_hint.setObjectName("startFileHint")
        file_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(file_hint)

        self.exit_button = QPushButton("退出")
        self.exit_button.setObjectName("startQuiet")
        self.exit_button.setToolTip("关闭启动中心并退出软件（Esc）")
        self.exit_button.clicked.connect(self.reject)
        layout.addWidget(self.exit_button)
        return panel

    def _theme_changed(self, theme_id):
        self.theme_id = apply_application_theme(theme_id, persist=True)
        self.setStyleSheet(compose_stylesheet(START_CENTER_STYLESHEET, self.theme_id))
        self.preview.set_theme(self.theme_id)
        self._update_shadow()

    def _update_shadow(self):
        shadow = QColor(resolve_theme(self.theme_id).color("primary"))
        shadow.setAlpha(34)
        self.shell_shadow.setColor(shadow)

    def _select(self, action):
        self.request = StartupRequest(action)
        self.accept()

    def _choose_project(self):
        path = ProjectLibraryDialog.choose_project(
            self,
            library=self.project_library,
            theme_id=self.theme_id,
        )
        if not path:
            return
        self.request = StartupRequest(START_OPEN, Path(path))
        self.accept()


__all__ = [
    "BeamWorkflowPreview",
    "START_NEW",
    "START_OPEN",
    "START_SAMPLE",
    "START_WORKSPACE",
    "START_CENTER_HERO_PATH",
    "StartCenterDialog",
    "StartupRequest",
]
