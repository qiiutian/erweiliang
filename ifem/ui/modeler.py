from __future__ import annotations

from math import ceil, hypot, isfinite
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ifem.application import get_default_analysis_service, match_project_algorithms
from ifem.domain.project import ProjectDocument, SectionDefinition
from ifem.infrastructure.project_io import load_project, save_project
from ifem.infrastructure.project_library import ProjectLibrary
from ifem.modeling.path_editor import BeamSurfaceLocation, PathBeamEditor
from ifem.modeling.section_geometry import (
    SECTION_PARAMETER_SPECS,
    SECTION_SHAPE_LABELS,
    default_section_parameters,
    section_profile_loops,
    section_shape_label,
)
from ifem.ui.modeler_3d import BeamGeometry3DView
from ifem.ui.project_library import ProjectLibraryDialog, ProjectNameDialog
from ifem.ui.theme import compose_stylesheet, current_theme_id, resolve_theme


MODELER_STYLESHEET = """
QDialog#modelerDialog {
    background: #f5f7f5;
}
QFrame#modelerHeader {
    background: transparent;
    border: none;
    border-bottom: 1px solid #dfe5e0;
}
QLabel#modelerTitle {
    color: #25332a;
    font-size: 18px;
    font-weight: 700;
}
QLabel#modelerSummary {
    color: #59675e;
    background: transparent;
    border: none;
    font-size: 12px;
}
QFrame#modelerToolBar, QFrame#modelerGenerator {
    background: #ffffff;
    border: 1px solid #dce4de;
    border-radius: 8px;
}
QLabel#toolbarLabel {
    color: #445249;
    font-size: 12px;
    font-weight: 700;
    padding: 0 4px;
}
QPushButton#modelerModeButton {
    min-height: 30px;
    padding: 0 12px;
    color: #59665e;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
}
QPushButton#modelerModeButton:hover {
    color: #2f5945;
    background: #edf3ef;
}
QPushButton#modelerModeButton:checked {
    color: #ffffff;
    background: #365b49;
    border-color: #365b49;
}
QPushButton#modelerToolButton, QPushButton#modelerFileButton,
QPushButton#modelerPathButton {
    min-height: 30px;
    padding: 0 12px;
    color: #48564d;
    background: #ffffff;
    border: 1px solid #cfd9d2;
    border-radius: 6px;
}
QPushButton#modelerToolButton:hover, QPushButton#modelerFileButton:hover,
QPushButton#modelerPathButton:hover {
    color: #2f5945;
    background: #eef4f0;
    border-color: #9eafa3;
}
QPushButton#modelerDangerButton {
    min-height: 30px;
    padding: 0 12px;
    color: #934b3d;
    background: #fffafa;
    border: 1px solid #e7cbc5;
    border-radius: 6px;
}
QPushButton#modelerDangerButton:hover {
    background: #f8e9e5;
    border-color: #d8aba2;
}
QPushButton#modelerToolButton:disabled, QPushButton#modelerDangerButton:disabled {
    color: #a2aaa5;
    background: #f3f5f3;
    border-color: #e0e5e1;
}
QFrame#modelerViewBar {
    background: transparent;
    border: none;
    border-bottom: 1px solid #dfe5e0;
}
QFrame#modelerInspector {
    background: #ffffff;
    border: 1px solid #dce4de;
    border-radius: 8px;
}
QLabel#inspectorTitle {
    color: #2d3c32;
    font-size: 14px;
    font-weight: 700;
}
QTabWidget#inspectorTabs::pane {
    background: #ffffff;
    border: none;
    border-top: 1px solid #e2e8e3;
    top: -1px;
}
QTabWidget#inspectorTabs QTabBar::tab {
    min-width: 92px;
    min-height: 34px;
    padding: 0 10px;
    margin: 0 3px 0 0;
    color: #69746d;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabWidget#inspectorTabs QTabBar::tab:selected {
    color: #2f5945;
    border-bottom: 2px solid #365b49;
    font-weight: 700;
}
QTabWidget#inspectorTabs QTabBar::tab:hover:!selected {
    color: #34483b;
    background: #f0f4f1;
}
QTabWidget#sensorConfigTabs::pane {
    background: #f8faf8;
    border: 1px solid #dce4de;
    border-radius: 7px;
    top: -1px;
}
QTabWidget#sensorConfigTabs QTabBar::tab {
    min-width: 62px;
    min-height: 30px;
    padding: 0 10px;
    margin-right: 2px;
    color: #68746c;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabWidget#sensorConfigTabs QTabBar::tab:selected {
    color: #2f5945;
    background: #f8faf8;
    border-bottom: 2px solid #365b49;
    font-weight: 700;
}
QWidget#inspectorSubpage {
    background: #f8faf8;
}
QWidget#inspectorPage, QScrollArea#inspectorScroll,
QScrollArea#inspectorScroll > QWidget > QWidget {
    background: #ffffff;
}
QDialog#modelerDialog QLineEdit, QDialog#modelerDialog QComboBox,
QDialog#modelerDialog QSpinBox, QDialog#modelerDialog QDoubleSpinBox {
    min-height: 28px;
    border-radius: 6px;
}
QPushButton#workspacePrimary {
    min-width: 126px;
    min-height: 36px;
    color: #ffffff;
    background: #365b49;
    border: 1px solid #2f503f;
    border-radius: 7px;
    font-weight: 700;
}
QPushButton#workspacePrimary:hover {
    background: #2d4e3e;
}
QLabel#modelerStatus {
    color: #59675e;
    background: #edf2ee;
    border: 1px solid #d6dfd8;
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 11px;
}
QLabel#modelerStatus[state="ready"] {
    color: #315b46;
    background: #e6f0e9;
    border-color: #c6daca;
}
QLabel#modelerStatus[state="waiting"] {
    color: #7b5d2d;
    background: #f6efdf;
    border-color: #e5d6b7;
}
"""


class ElidedLabel(QLabel):
    """Single-line label that yields space instead of overlapping siblings."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_elision()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elision()

    def _refresh_elision(self):
        available = max(0, self.contentsRect().width() - 8)
        displayed = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available,
        )
        if displayed != QLabel.text(self):
            QLabel.setText(self, displayed)


class SectionProfilePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_id = current_theme_id()
        self.section = None
        self.setFixedHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_section(self, section: SectionDefinition | None):
        self.section = section
        self.update()

    def set_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        self.update()

    def _color(self, role):
        return QColor(resolve_theme(self._theme_id).color(role))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(QPen(self._color("border"), 1.0))
        painter.setBrush(self._color("surface_subtle"))
        painter.drawRoundedRect(panel, 9.0, 9.0)
        if self.section is None:
            painter.setPen(self._color("text_muted"))
            painter.drawText(
                panel,
                Qt.AlignmentFlag.AlignCenter,
                "填写合法截面尺寸后显示预览",
            )
            return

        loops = section_profile_loops(self.section, resolution=44)
        coordinates = [point for loop in loops for point in loop]
        max_u = max(abs(float(point[0])) for point in coordinates)
        max_v = max(abs(float(point[1])) for point in coordinates)
        drawing = panel.adjusted(46.0, 18.0, -46.0, -28.0)
        scale = min(
            drawing.width() / max(2.0 * max_v, 1.0e-12),
            drawing.height() / max(2.0 * max_u, 1.0e-12),
        ) * 0.82
        center = drawing.center()

        axis_pen = QPen(self._color("border_strong"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(axis_pen)
        painter.drawLine(
            QPointF(drawing.left(), center.y()),
            QPointF(drawing.right(), center.y()),
        )
        painter.drawLine(
            QPointF(center.x(), drawing.top()),
            QPointF(center.x(), drawing.bottom()),
        )

        path = QPainterPath()
        for loop in loops:
            polygon = QPolygonF(
                [
                    QPointF(
                        center.x() + float(point[1]) * scale,
                        center.y() - float(point[0]) * scale,
                    )
                    for point in loop
                ]
            )
            path.addPolygon(polygon)
            path.closeSubpath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        painter.setPen(QPen(self._color("beam"), 1.6))
        painter.setBrush(self._color("beam_fill"))
        painter.drawPath(path)

        painter.setPen(self._color("text_muted"))
        painter.drawText(
            QRectF(panel.left() + 10.0, panel.top() + 7.0, 54.0, 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "0° 上",
        )
        painter.drawText(
            QRectF(panel.right() - 62.0, center.y() - 10.0, 54.0, 20.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "90° 侧",
        )
        painter.setPen(self._color("text_secondary"))
        painter.drawText(
            QRectF(panel.left(), panel.bottom() - 24.0, panel.width(), 18.0),
            Qt.AlignmentFlag.AlignCenter,
            section_shape_label(self.section.shape),
        )


class BeamModelCanvas(QWidget):
    selection_changed = Signal(str, str)
    commit_requested = Signal(object, object, str)
    error_raised = Signal(str)

    MODE_SELECT = "select"
    MODE_ADD_NODE = "add_node"
    MODE_EXTEND_PATH = "extend_path"
    MODE_ADD_TOP_SENSOR = "add_top_sensor"
    MODE_ADD_BOTTOM_SENSOR = "add_bottom_sensor"

    PLANE_AXES = {
        "xy": (0, 1, 2),
        "xz": (0, 2, 1),
        "yz": (1, 2, 0),
    }

    def __init__(self, project: ProjectDocument, parent=None):
        super().__init__(parent)
        self._theme_id = current_theme_id()
        self.project = project
        self.mode = self.MODE_SELECT
        self.plane = "xy"
        self.selected_kind = ""
        self.selected_id = ""
        self._hover_kind = ""
        self._hover_id = ""
        self._drag_node_id = ""
        self._drag_before = None
        self._drag_transform = None
        self.setMinimumSize(620, 430)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        self.update()

    def _color(self, role):
        return QColor(resolve_theme(self._theme_id).color(role))

    def set_project(self, project: ProjectDocument):
        self.project = project
        valid_ids = {
            entity.identifier
            for entity in project.nodes + project.elements + project.sensors
        }
        if self.selected_id not in valid_ids:
            self.selected_kind = ""
            self.selected_id = ""
            self.selection_changed.emit("", "")
        self.update()

    def set_mode(self, mode: str):
        self.mode = mode
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if mode == self.MODE_SELECT
            else Qt.CursorShape.CrossCursor
        )
        self.update()

    def set_plane(self, plane: str):
        if plane not in self.PLANE_AXES:
            return
        self.plane = plane
        self.update()

    def select_entity(self, kind: str, identifier: str, *, emit=True):
        self.selected_kind = kind
        self.selected_id = identifier
        if emit:
            self.selection_changed.emit(kind, identifier)
        self.update()

    def _drawing_rect(self) -> QRectF:
        return QRectF(
            64.0,
            28.0,
            max(140.0, self.width() - 96.0),
            max(140.0, self.height() - 50.0),
        )

    def _projected_coordinates(self, coordinates):
        horizontal, vertical, _hidden = self.PLANE_AXES[self.plane]
        return float(coordinates[horizontal]), float(coordinates[vertical])

    def _projection_transform(self):
        rect = self._drawing_rect()
        projected = [
            self._projected_coordinates(point)
            for point in PathBeamEditor.sample_project(self.project)
        ]
        x_min = min(point[0] for point in projected)
        x_max = max(point[0] for point in projected)
        y_min = min(point[1] for point in projected)
        y_max = max(point[1] for point in projected)
        x_span = x_max - x_min
        y_span = y_max - y_min
        reference_span = max(x_span, y_span, PathBeamEditor.total_length(self.project) * 0.2, 1.0e-6)
        if x_span <= 1.0e-12:
            x_min -= reference_span * 0.35
            x_max += reference_span * 0.35
        else:
            x_min -= x_span * 0.09
            x_max += x_span * 0.09
        if y_span <= 1.0e-12:
            y_min -= reference_span * 0.28
            y_max += reference_span * 0.28
        else:
            y_min -= y_span * 0.12
            y_max += y_span * 0.12
        scale = min(rect.width() / (x_max - x_min), rect.height() / (y_max - y_min))
        center_x = (x_min + x_max) * 0.5
        center_y = (y_min + y_max) * 0.5
        return rect, center_x, center_y, scale

    def _world_to_pixel(self, coordinates, transform=None) -> QPointF:
        rect, center_x, center_y, scale = transform or self._projection_transform()
        horizontal, vertical = self._projected_coordinates(coordinates)
        return QPointF(
            rect.center().x() + (horizontal - center_x) * scale,
            rect.center().y() - (vertical - center_y) * scale,
        )

    def _pixel_to_coordinates(self, position: QPointF, reference, transform=None):
        rect, center_x, center_y, scale = transform or self._projection_transform()
        horizontal = center_x + (position.x() - rect.center().x()) / scale
        vertical = center_y - (position.y() - rect.center().y()) / scale
        result = list(float(value) for value in reference)
        horizontal_axis, vertical_axis, _hidden = self.PLANE_AXES[self.plane]
        result[horizontal_axis] = horizontal
        result[vertical_axis] = vertical
        return tuple(result)

    # Compatibility helpers retained for existing straight-beam UI tests.
    def _view_range(self):
        x_values = [node.coordinates[0] for node in self.project.nodes]
        span = max(max(x_values) - min(x_values), 1.0e-9)
        return min(x_values) - 0.07 * span, max(x_values) + 0.07 * span

    def _x_to_pixel(self, x: float, _view_range=None) -> float:
        coordinates = (float(x), 0.0, 0.0)
        return self._world_to_pixel(coordinates).x()

    def _pixel_to_x(self, pixel_x: float, _view_range=None) -> float:
        beam_y = self._beam_y()
        return self._pixel_to_coordinates(
            QPointF(float(pixel_x), beam_y),
            (0.0, 0.0, 0.0),
        )[0]

    def _beam_y(self) -> float:
        return self._world_to_pixel((0.0, 0.0, 0.0)).y()

    def _node_positions(self):
        transform = self._projection_transform()
        return {
            node.identifier: self._world_to_pixel(node.coordinates, transform)
            for node in self.project.nodes
        }

    def _element_geometry(self):
        transform = self._projection_transform()
        return [
            (
                element,
                tuple(
                    self._world_to_pixel(point, transform)
                    for point in PathBeamEditor.sample_element(self.project, element)
                ),
            )
            for element in PathBeamEditor.ordered_elements(self.project)
        ]

    def _element_pixel_tangent(self, element, local_coordinate: float, transform=None):
        xi = min(1.0, max(0.0, float(local_coordinate)))
        delta = 1.0e-3
        left = max(0.0, xi - delta)
        right = min(1.0, xi + delta)
        if right <= left:
            left, right = 0.0, 1.0
        transform = transform or self._projection_transform()
        start = self._world_to_pixel(
            PathBeamEditor.point_on_element(self.project, element, left),
            transform,
        )
        end = self._world_to_pixel(
            PathBeamEditor.point_on_element(self.project, element, right),
            transform,
        )
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = hypot(dx, dy)
        if length <= 1.0e-12:
            return QPointF(1.0, 0.0)
        return QPointF(dx / length, dy / length)

    def _project_direction(self, direction):
        horizontal, vertical, _hidden = self.PLANE_AXES[self.plane]
        projected = QPointF(float(direction[horizontal]), -float(direction[vertical]))
        length = hypot(projected.x(), projected.y())
        if length <= 1.0e-12:
            return QPointF(), 0.0
        return QPointF(projected.x() / length, projected.y() / length), length

    @staticmethod
    def _line_pick(position: QPointF, start: QPointF, end: QPointF):
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        denominator = dx * dx + dy * dy
        if denominator <= 1.0e-12:
            return 0.0, hypot(position.x() - start.x(), position.y() - start.y())
        parameter = (
            (position.x() - start.x()) * dx + (position.y() - start.y()) * dy
        ) / denominator
        parameter = min(1.0, max(0.0, parameter))
        projected_x = start.x() + parameter * dx
        projected_y = start.y() + parameter * dy
        return parameter, hypot(position.x() - projected_x, position.y() - projected_y)

    def _nearest_element(self, position: QPointF):
        best = None
        for index, (element, points) in enumerate(self._element_geometry()):
            segment_count = len(points) - 1
            for sample_index, (start, end) in enumerate(zip(points, points[1:])):
                segment_parameter, distance = self._line_pick(position, start, end)
                parameter = (sample_index + segment_parameter) / segment_count
                candidate = (distance, index, element, parameter)
                if best is None or distance < best[0]:
                    best = candidate
        return best

    def _sensor_polygons(self):
        polygons = {}
        centers = {}
        directions = {}
        transform = self._projection_transform()
        for sensor in self.project.sensors:
            orientation = PathBeamEditor.sensor_orientation(self.project, sensor)
            center = self._world_to_pixel(
                orientation.centerline_position,
                transform,
            )
            radial, radial_visibility = self._project_direction(
                orientation.surface_radial
            )
            center += radial * (22.0 * min(1.0, radial_visibility))
            measurement_axis, direction_visibility = self._project_direction(
                orientation.measurement_direction
            )
            if direction_visibility <= 1.0e-6:
                element = PathBeamEditor._resolve_element(
                    self.project,
                    sensor.attachment.entity_id,
                )
                measurement_axis = self._element_pixel_tangent(
                    element,
                    sensor.attachment.local_coordinates[0],
                    transform,
                )
            cross_axis = QPointF(-measurement_axis.y(), measurement_axis.x())
            half_width = 10.0
            half_height = 5.0
            polygon = QPolygonF(
                [
                    center - measurement_axis * half_width - cross_axis * half_height,
                    center + measurement_axis * half_width - cross_axis * half_height,
                    center + measurement_axis * half_width + cross_axis * half_height,
                    center - measurement_axis * half_width + cross_axis * half_height,
                ]
            )
            polygons[sensor.identifier] = polygon
            centers[sensor.identifier] = center
            directions[sensor.identifier] = measurement_axis
        return polygons, centers, directions

    def _hit_test(self, position: QPointF):
        sensor_polygons, _centers, _directions = self._sensor_polygons()
        for sensor_id, polygon in reversed(tuple(sensor_polygons.items())):
            if polygon.boundingRect().adjusted(-5.0, -5.0, 5.0, 5.0).contains(position):
                return "sensor", sensor_id
        for node_id, point in self._node_positions().items():
            if hypot(point.x() - position.x(), point.y() - position.y()) <= 11.0:
                return "node", node_id
        nearest = self._nearest_element(position)
        if nearest is not None and nearest[0] <= 12.0:
            return "element", nearest[2].identifier
        return "", ""

    def _draw_label_tag(self, painter: QPainter, anchor: QPointF, text: str):
        metrics = painter.fontMetrics()
        label_rect = QRectF(
            anchor.x() - metrics.horizontalAdvance(text) / 2.0 - 5.0,
            anchor.y() - metrics.height() / 2.0 - 3.0,
            metrics.horizontalAdvance(text) + 10.0,
            metrics.height() + 6.0,
        )
        safe_rect = QRectF(
            8.0,
            10.0,
            max(1.0, self.width() - 16.0),
            max(1.0, self.height() - 20.0),
        )
        if label_rect.left() < safe_rect.left():
            label_rect.moveLeft(safe_rect.left())
        if label_rect.right() > safe_rect.right():
            label_rect.moveRight(safe_rect.right())
        if label_rect.top() < safe_rect.top():
            label_rect.moveTop(safe_rect.top())
        if label_rect.bottom() > safe_rect.bottom():
            label_rect.moveBottom(safe_rect.bottom())

        painter.setPen(QPen(self._color("border"), 1.0))
        panel_fill = self._color("surface")
        panel_fill.setAlpha(238)
        painter.setBrush(panel_fill)
        painter.drawRoundedRect(label_rect, 4.0, 4.0)
        painter.setPen(self._color("text_secondary"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self._color("canvas"))

        rect = self._drawing_rect()
        painter.setPen(QPen(self._color("grid"), 1.0))
        for index in range(7):
            x = rect.left() + rect.width() * index / 6.0
            y = rect.top() + rect.height() * index / 6.0
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        elements = PathBeamEditor.ordered_elements(self.project)
        element_label_stride = max(1, ceil(len(elements) / 7))
        geometry_by_id = {
            element.identifier: points for element, points in self._element_geometry()
        }
        for index, element in enumerate(elements):
            points = geometry_by_id[element.identifier]
            highlighted = element.identifier in {self.selected_id, self._hover_id}
            painter.setPen(
                QPen(
                    self._color("sensor") if highlighted else self._color("beam"),
                    12.0 if highlighted else 9.0,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(self._color("surface"), 1.0))
            painter.drawPolyline(QPolygonF(points))
            if index % element_label_stride == 0 or highlighted:
                tangent = self._element_pixel_tangent(element, 0.5)
                normal = QPointF(tangent.y(), -tangent.x())
                midpoint = self._world_to_pixel(
                    PathBeamEditor.point_on_element(self.project, element, 0.5)
                )
                self._draw_label_tag(
                    painter,
                    midpoint + normal * 24.0,
                    f"E{index + 1}",
                )

        sensor_polygons, sensor_centers, sensor_directions = self._sensor_polygons()
        for sensor in self.project.sensors:
            highlighted = sensor.identifier in {self.selected_id, self._hover_id}
            painter.setPen(QPen(self._color("sensor_dark"), 1.3))
            painter.setBrush(
                self._color("sensor_hover") if highlighted else self._color("sensor")
            )
            painter.drawPolygon(sensor_polygons[sensor.identifier])
            center = sensor_centers[sensor.identifier]
            direction = sensor_directions[sensor.identifier]
            cross_axis = QPointF(-direction.y(), direction.x())
            positive_tip = center + direction * 7.0
            negative_tip = center - direction * 7.0
            painter.setPen(QPen(self._color("sensor_dark"), 1.4))
            painter.drawLine(negative_tip, positive_tip)
            for tip, outward in (
                (positive_tip, direction),
                (negative_tip, -direction),
            ):
                painter.drawLine(tip, tip - outward * 3.0 + cross_axis * 2.0)
                painter.drawLine(tip, tip - outward * 3.0 - cross_axis * 2.0)

        positions = self._node_positions()
        ordered_nodes = PathBeamEditor.ordered_nodes(self.project)
        node_label_stride = max(1, ceil((len(ordered_nodes) - 1) / 7))
        for index, node in enumerate(ordered_nodes):
            point = positions[node.identifier]
            highlighted = node.identifier in {self.selected_id, self._hover_id}
            radius = 7.5 if highlighted else 6.0
            painter.setPen(
                QPen(
                    self._color("sensor_dark") if highlighted else self._color("primary"),
                    1.4,
                )
            )
            painter.setBrush(
                self._color("sensor_soft") if highlighted else self._color("surface")
            )
            painter.drawEllipse(point, radius, radius)
            show_label = (
                index in {0, len(ordered_nodes) - 1}
                or index % node_label_stride == 0
                or highlighted
            )
            if show_label:
                previous = positions[ordered_nodes[max(0, index - 1)].identifier]
                following = positions[
                    ordered_nodes[min(len(ordered_nodes) - 1, index + 1)].identifier
                ]
                dx = following.x() - previous.x()
                dy = following.y() - previous.y()
                length = max(hypot(dx, dy), 1.0e-12)
                normal = QPointF(-dy / length, dx / length)
                self._draw_label_tag(
                    painter,
                    point + normal * 27.0,
                    f"N{index + 1}",
                )

        painter.setPen(QPen(self._color("border"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            8.0,
            8.0,
        )
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position()
        if self.mode == self.MODE_SELECT:
            kind, identifier = self._hit_test(position)
            self.select_entity(kind, identifier)
            if kind == "node":
                if any(
                    identifier in element.node_ids and element.geometry.kind != "line"
                    for element in self.project.elements
                ):
                    self.error_raised.emit(
                        "参数化圆弧端点由半径、圆心角和平面控制，请在梁实体属性中编辑。"
                    )
                    return
                self._drag_node_id = identifier
                self._drag_before = self.project
                self._drag_transform = self._projection_transform()
            return

        try:
            before = self.project
            if self.mode == self.MODE_EXTEND_PATH:
                endpoint = PathBeamEditor.ordered_nodes(before)[-1]
                coordinates = self._pixel_to_coordinates(position, endpoint.coordinates)
                after = PathBeamEditor.append_node(before, coordinates)
                new_ids = {node.identifier for node in after.nodes} - {
                    node.identifier for node in before.nodes
                }
                selection = ("node", next(iter(new_ids)))
                description = "延伸梁路径"
            else:
                nearest = self._nearest_element(position)
                if nearest is None or nearest[0] > 24.0:
                    raise ValueError("请在梁段附近点击。")
                _distance, _index, element, xi = nearest
                if self.mode == self.MODE_ADD_NODE:
                    after = PathBeamEditor.insert_node(before, element.identifier, xi)
                    new_ids = {node.identifier for node in after.nodes} - {
                        node.identifier for node in before.nodes
                    }
                    selection = ("node", next(iter(new_ids)))
                    description = "插入梁节点"
                else:
                    side = "top" if self.mode == self.MODE_ADD_TOP_SENSOR else "bottom"
                    after = PathBeamEditor.add_sensor(before, element.identifier, xi, side)
                    selection = ("sensor", after.sensors[-1].identifier)
                    description = "添加应变测点"
            self.commit_requested.emit(before, after, description)
            self.select_entity(*selection)
        except (KeyError, TypeError, ValueError) as exc:
            self.error_raised.emit(str(exc))

    def mouseMoveEvent(self, event):
        position = event.position()
        if self._drag_node_id and self._drag_before is not None:
            try:
                node = next(
                    item
                    for item in self._drag_before.nodes
                    if item.identifier == self._drag_node_id
                )
                coordinates = self._pixel_to_coordinates(
                    position,
                    node.coordinates,
                    self._drag_transform,
                )
                self.project = PathBeamEditor.move_node(
                    self._drag_before,
                    self._drag_node_id,
                    coordinates,
                )
                self.update()
            except (KeyError, TypeError, ValueError):
                pass
            return

        kind, identifier = self._hit_test(position)
        if (kind, identifier) != (self._hover_kind, self._hover_id):
            self._hover_kind, self._hover_id = kind, identifier
            self._show_hover_tooltip(event, kind, identifier)
            self.update()

    def _show_hover_tooltip(self, event, kind: str, identifier: str):
        if kind == "sensor":
            sensor = next(item for item in self.project.sensors if item.identifier == identifier)
            location = PathBeamEditor.sensor_location(self.project, identifier)
            surface_angle = sensor.attachment.surface_angle_degrees
            if min(abs(surface_angle), abs(surface_angle - 360.0)) <= 1.0e-8:
                side = "局部上侧"
            elif abs(surface_angle - 180.0) <= 1.0e-8:
                side = "局部下侧"
            else:
                side = "自定义环向位置"
            point = location.global_position
            text = (
                f"{sensor.label}\n位置 = ({point[0]:.6g}, {point[1]:.6g}, {point[2]:.6g})\n"
                f"E{location.element_index + 1} · ξ={location.local_coordinate:.4f} · {side}\n"
                f"环向 θ={sensor.attachment.surface_angle_degrees:.2f}° · "
                f"测量轴 α={sensor.attachment.orientation_angle_degrees:.2f}°（±等价）\n"
                f"应变 = {float(sensor.measured_value or 0.0):.6e}"
            )
        elif kind == "node":
            node = next(item for item in self.project.nodes if item.identifier == identifier)
            point = node.coordinates
            text = f"节点\n({point[0]:.6g}, {point[1]:.6g}, {point[2]:.6g})"
        elif kind == "element":
            element = next(item for item in self.project.elements if item.identifier == identifier)
            length = PathBeamEditor.element_length(self.project, element)
            text = f"梁单元\n长度 = {length:.6g} m\n类型 = {element.family}"
        else:
            QToolTip.hideText()
            return
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._drag_node_id:
            return
        before = self._drag_before
        after = self.project
        self._drag_node_id = ""
        self._drag_before = None
        self._drag_transform = None
        if before is not None and before.to_dict() != after.to_dict():
            self.commit_requested.emit(before, after, "移动梁节点")

    def leaveEvent(self, _event):
        if not self._drag_node_id:
            self._hover_kind = ""
            self._hover_id = ""
            QToolTip.hideText()
            self.update()


class ProjectSnapshotCommand(QUndoCommand):
    def __init__(self, dialog, before: ProjectDocument, after: ProjectDocument, text: str):
        super().__init__(text)
        self.dialog = dialog
        self.before = before
        self.after = after

    def undo(self):
        self.dialog._apply_project(self.before)

    def redo(self):
        self.dialog._apply_project(self.after)


class SensorArrayDialog(QDialog):
    def __init__(
        self,
        sensor_label: str,
        source_distance: float,
        total_length: float,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("modelerDialog")
        self._theme_id = current_theme_id()
        self.setStyleSheet(compose_stylesheet(MODELER_STYLESHEET, self._theme_id))
        self.setWindowTitle("等距测点阵列")
        self.setMinimumWidth(360)
        self.source_distance = float(source_distance)
        self.total_length = float(total_length)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)
        title = QLabel(f"以 {sensor_label} 为模板")
        title.setObjectName("inspectorTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("朝路径末端", 1)
        self.direction_combo.addItem("朝路径起点", -1)
        toward_end = self.total_length - self.source_distance
        default_direction = 1 if toward_end >= self.source_distance else -1
        self.direction_combo.setCurrentIndex(
            self.direction_combo.findData(default_direction)
        )
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 500)
        self.count_spin.setValue(3)
        self.count_spin.setSuffix(" 个")
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setDecimals(8)
        self.spacing_spin.setRange(max(self.total_length * 1.0e-9, 1.0e-9), self.total_length)
        self.spacing_spin.setSuffix(" m")
        available = (
            self.total_length - self.source_distance
            if default_direction > 0
            else self.source_distance
        )
        self.spacing_spin.setValue(max(self.spacing_spin.minimum(), available / 3.0))
        form.addRow("阵列方向", self.direction_combo)
        form.addRow("新增数量", self.count_spin)
        form.addRow("中心间距", self.spacing_spin)
        layout.addLayout(form)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("modelerStatus")
        layout.addWidget(self.preview_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建阵列")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
            "workspacePrimary"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.direction_combo.currentIndexChanged.connect(self._refresh_preview)
        self.count_spin.valueChanged.connect(self._refresh_preview)
        self.spacing_spin.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def array_values(self) -> tuple[int, float, int]:
        return (
            self.count_spin.value(),
            self.spacing_spin.value(),
            int(self.direction_combo.currentData()),
        )

    def _refresh_preview(self, *_args):
        count, spacing, direction = self.array_values
        endpoint = self.source_distance + direction * count * spacing
        valid = -1.0e-10 <= endpoint <= self.total_length + 1.0e-10
        available = (
            self.total_length - self.source_distance
            if direction > 0
            else self.source_distance
        )
        if valid:
            text = f"新增 {count} 个测点 · 末点 s={endpoint:.6g} m"
            state = "ready"
        else:
            text = f"阵列超出梁路径 · 当前方向可用 {available:.6g} m"
            state = "waiting"
        self.preview_label.setText(text)
        self.preview_label.setProperty("state", state)
        self.preview_label.style().unpolish(self.preview_label)
        self.preview_label.style().polish(self.preview_label)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)


class SpatialCurveDialog(QDialog):
    """Collect an arbitrary three-point arc or a NURBS control polygon."""

    ARC = "arc_three_points"
    NURBS = "nurbs_curve"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("spatialCurveDialog")
        self.setWindowTitle("创建空间曲线")
        self.setMinimumSize(560, 470)
        self._definition = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("空间曲线")
        title.setObjectName("inspectorTitle")
        root.addWidget(title)
        intro = QLabel(
            "输入绝对坐标；圆弧通过三个点精确定义，NURBS 使用控制点和可选权重。"
        )
        intro.setObjectName("sectionHint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("任意平面圆弧（三点）", self.ARC)
        self.kind_combo.addItem("三维 B 样条 / NURBS", self.NURBS)
        form.addRow("曲线类型", self.kind_combo)
        self.degree_spin = QSpinBox()
        self.degree_spin.setRange(1, 5)
        self.degree_spin.setValue(3)
        self.degree_label = QLabel("样条次数")
        form.addRow(self.degree_label, self.degree_spin)
        self.weights_edit = QLineEdit()
        self.weights_edit.setPlaceholderText("可选，例如：1, 1, 0.8, 1")
        self.weights_label = QLabel("控制点权重")
        form.addRow(self.weights_label, self.weights_edit)
        root.addLayout(form)

        points_label = QLabel("空间点（每行 x, y, z）")
        points_label.setObjectName("fieldLabel")
        root.addWidget(points_label)
        self.points_edit = QPlainTextEdit()
        self.points_edit.setAccessibleName("空间曲线控制点")
        self.points_edit.setPlaceholderText(
            "0, 0, 0\n1, 0.5, 0.8\n2, 1.0, 0.2"
        )
        self.points_edit.setPlainText("0, 0, 0\n1, 0.5, 0.8\n2, 1.0, 0.2")
        root.addWidget(self.points_edit, 1)

        self.feedback_label = QLabel()
        self.feedback_label.setObjectName("sectionHint")
        self.feedback_label.setWordWrap(True)
        root.addWidget(self.feedback_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建曲线")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
            "smallPrimaryButton"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.kind_combo.currentIndexChanged.connect(self._curve_kind_changed)
        self.degree_spin.valueChanged.connect(self._refresh_state)
        self.weights_edit.textChanged.connect(self._refresh_state)
        self.points_edit.textChanged.connect(self._refresh_state)
        self._refresh_state()

    def _parse_points(self):
        points = []
        for line_number, line in enumerate(self.points_edit.toPlainText().splitlines(), 1):
            text = line.strip()
            if not text:
                continue
            parts = text.replace("，", ",").replace(",", " ").split()
            if len(parts) != 3:
                raise ValueError(f"第 {line_number} 行必须包含 x、y、z 三个坐标。")
            point = tuple(float(value) for value in parts)
            if not all(isfinite(value) for value in point):
                raise ValueError(f"第 {line_number} 行坐标必须是有限数值。")
            points.append(point)
        return tuple(points)

    def definition(self):
        points = self._parse_points()
        kind = self.kind_combo.currentData()
        if kind == self.ARC:
            if len(points) != 3:
                raise ValueError("任意平面圆弧必须恰好输入三个点。")
            first = tuple(right - left for left, right in zip(points[0], points[1]))
            second = tuple(right - left for left, right in zip(points[0], points[2]))
            cross = (
                first[1] * second[2] - first[2] * second[1],
                first[2] * second[0] - first[0] * second[2],
                first[0] * second[1] - first[1] * second[0],
            )
            if sum(value * value for value in cross) <= 1.0e-20:
                raise ValueError("任意平面圆弧的三个点不能共线或重合。")
            return {"kind": kind, "points": points}
        if len(points) < 2:
            raise ValueError("NURBS 曲线至少需要两个控制点。")
        degree = self.degree_spin.value()
        if degree >= len(points):
            raise ValueError("样条次数必须小于控制点数量。")
        weights_text = self.weights_edit.text().strip()
        weights = None
        if weights_text:
            weights = tuple(
                float(value)
                for value in weights_text.replace("，", ",").replace(",", " ").split()
            )
            if len(weights) != len(points):
                raise ValueError("权重数量必须与控制点数量一致。")
            if not all(isfinite(value) and value > 0.0 for value in weights):
                raise ValueError("每个 NURBS 权重都必须是大于 0 的有限数值。")
        return {
            "kind": kind,
            "points": points,
            "degree": degree,
            "weights": weights,
        }

    def _curve_kind_changed(self, *_args):
        if self.kind_combo.currentData() == self.NURBS:
            try:
                point_count = len(self._parse_points())
            except (TypeError, ValueError):
                point_count = 0
            if point_count >= 2 and self.degree_spin.value() >= point_count:
                self.degree_spin.setValue(point_count - 1)
        self._refresh_state()

    def _refresh_state(self, *_args):
        is_nurbs = self.kind_combo.currentData() == self.NURBS
        self.degree_label.setVisible(is_nurbs)
        self.degree_spin.setVisible(is_nurbs)
        self.weights_label.setVisible(is_nurbs)
        self.weights_edit.setVisible(is_nurbs)
        try:
            definition = self.definition()
            point_count = len(definition["points"])
            self.feedback_label.setText(
                f"可创建 · {point_count} 个定义点"
                + (f" · {definition['degree']} 次" if is_nurbs else "")
            )
            valid = True
        except (TypeError, ValueError) as exc:
            self.feedback_label.setText(str(exc))
            valid = False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def accept(self):
        try:
            self._definition = self.definition()
        except (TypeError, ValueError) as exc:
            self.feedback_label.setText(str(exc))
            return
        super().accept()

    @property
    def curve_definition(self):
        return self._definition


class BeamModelerDialog(QDialog):
    def __init__(self, project: ProjectDocument, parent=None, *, theme_id=None):
        super().__init__(parent)
        self.setObjectName("modelerDialog")
        self._theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self.setStyleSheet(compose_stylesheet(MODELER_STYLESHEET, self._theme_id))
        self.setWindowTitle("iFEM | 结构建模")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 680)
        self._project = project
        self._project_path = None
        self._project_library = ProjectLibrary()
        self._saved_revision = None
        self.selected_kind = ""
        self.selected_id = ""
        self._syncing_selection = False
        self._loading_section = False
        self.undo_stack = QUndoStack(self)
        self._build_ui()
        self._apply_project(project)

    @property
    def project(self) -> ProjectDocument:
        return self._project

    @property
    def project_path(self):
        return self._project_path

    @property
    def project_is_saved(self):
        return bool(
            self._project_path is not None
            and Path(self._project_path).exists()
            and self._saved_revision == self._project.revision
        )

    def set_project_storage(
        self,
        library,
        project_path=None,
        *,
        project_is_saved=False,
    ):
        self._project_library = library or ProjectLibrary()
        self._project_path = (
            Path(project_path).expanduser().resolve()
            if project_path is not None
            else None
        )
        self._saved_revision = self._project.revision if project_is_saved else None

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(9)

        header = QFrame()
        header.setObjectName("modelerHeader")
        heading = QHBoxLayout(header)
        heading.setContentsMargins(4, 0, 0, 9)
        heading.setSpacing(8)
        title = QLabel("结构建模")
        title.setObjectName("modelerTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.summary_label = ElidedLabel()
        self.summary_label.setObjectName("modelerSummary")
        self.summary_label.setMinimumWidth(0)
        self.summary_label.setMaximumWidth(720)
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        heading.addWidget(self.summary_label)
        heading.addSpacing(6)
        open_button = QPushButton("打开")
        open_button.setObjectName("modelerFileButton")
        open_button.setToolTip("从 iFEM 项目库打开项目")
        open_button.setShortcut(QKeySequence.StandardKey.Open)
        open_button.clicked.connect(self._open_project)
        heading.addWidget(open_button)
        self.save_project_button = QPushButton("保存项目")
        self.save_project_button.setObjectName("modelerFileButton")
        self.save_project_button.setToolTip(
            "将当前模型写入 iFEM 项目库；建模器保持打开（Ctrl+S）"
        )
        self.save_project_button.setShortcut(QKeySequence.StandardKey.Save)
        self.save_project_button.clicked.connect(self._save_project)
        heading.addWidget(self.save_project_button)
        root.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("modelerToolBar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(5)
        tool_label = QLabel("编辑")
        tool_label.setObjectName("toolbarLabel")
        toolbar_layout.addWidget(tool_label)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}
        modes = [
            (BeamModelCanvas.MODE_SELECT, "选择", "选择或拖动模型对象"),
            (BeamModelCanvas.MODE_ADD_NODE, "拆分", "在直梁段中插入节点"),
            (BeamModelCanvas.MODE_EXTEND_PATH, "延伸", "从路径末端延伸梁段"),
            (BeamModelCanvas.MODE_ADD_TOP_SENSOR, "上侧测点", "在二维视图布置上侧测点"),
            (BeamModelCanvas.MODE_ADD_BOTTOM_SENSOR, "下侧测点", "在二维视图布置下侧测点"),
            (BeamGeometry3DView.MODE_ADD_SURFACE_SENSOR, "表面测点", "在三维表面连续布置测点"),
            (
                BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR,
                "拖动测点",
                "在三维表面拖动已有测点，松开鼠标后提交",
            ),
        ]
        for mode, text, tooltip in modes:
            button = QPushButton(text)
            button.setObjectName("modelerModeButton")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, value=mode: self._set_mode(value))
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            toolbar_layout.addWidget(button)
        self.mode_buttons[BeamModelCanvas.MODE_SELECT].setChecked(True)

        toolbar_layout.addStretch(1)
        history_divider = QFrame()
        history_divider.setObjectName("toolbarDivider")
        history_divider.setFrameShape(QFrame.Shape.VLine)
        history_divider.setFixedHeight(24)
        toolbar_layout.addWidget(history_divider)
        toolbar_layout.addSpacing(3)
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        self.delete_button = QPushButton("删除")
        self.undo_button.setObjectName("modelerToolButton")
        self.redo_button.setObjectName("modelerToolButton")
        self.delete_button.setObjectName("modelerDangerButton")
        self.undo_button.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_button.setShortcut(QKeySequence.StandardKey.Redo)
        self.delete_button.setShortcut(QKeySequence.StandardKey.Delete)
        self.undo_button.clicked.connect(self.undo_stack.undo)
        self.redo_button.clicked.connect(self.undo_stack.redo)
        self.delete_button.clicked.connect(self._delete_selected)
        toolbar_layout.addWidget(self.undo_button)
        toolbar_layout.addWidget(self.redo_button)
        toolbar_layout.addWidget(self.delete_button)
        root.addWidget(toolbar)

        self._build_generator(root)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        viewport = QWidget()
        viewport_layout = QVBoxLayout(viewport)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(6)

        view_bar = QFrame()
        view_bar.setObjectName("modelerViewBar")
        view_bar_layout = QHBoxLayout(view_bar)
        view_bar_layout.setContentsMargins(4, 2, 4, 6)
        view_label = QLabel("视图")
        view_label.setObjectName("toolbarLabel")
        view_bar_layout.addWidget(view_label)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_buttons = {}
        for index, (key, text) in enumerate((("2d", "平面编辑"), ("3d", "三维预览"))):
            button = QPushButton(text)
            button.setObjectName("modelerModeButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, value=index: self._switch_view(value)
            )
            self.view_group.addButton(button)
            self.view_buttons[key] = button
            view_bar_layout.addWidget(button)
        self.view_buttons["2d"].setChecked(True)
        view_bar_layout.addSpacing(8)
        projection_label = QLabel("投影")
        projection_label.setObjectName("toolbarLabel")
        view_bar_layout.addWidget(projection_label)
        self.plane_combo = QComboBox()
        self.plane_combo.addItem("XY 平面", "xy")
        self.plane_combo.addItem("XZ 平面", "xz")
        self.plane_combo.addItem("YZ 平面", "yz")
        self.plane_combo.currentIndexChanged.connect(
            lambda _index: self.canvas.set_plane(self.plane_combo.currentData())
        )
        view_bar_layout.addWidget(self.plane_combo)
        view_bar_layout.addStretch(1)
        self.capability_label = ElidedLabel()
        self.capability_label.setObjectName("viewportStatus")
        self.capability_label.setMinimumWidth(76)
        self.capability_label.setMaximumWidth(180)
        self.capability_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        view_bar_layout.addWidget(self.capability_label)
        viewport_layout.addWidget(view_bar)

        self.view_stack = QStackedWidget()
        self.canvas = BeamModelCanvas(self._project)
        self.canvas.selection_changed.connect(self._selection_changed)
        self.canvas.commit_requested.connect(self._commit_project)
        self.canvas.error_raised.connect(self._show_nonblocking_error)
        self.view_stack.addWidget(self.canvas)
        self.geometry_3d_view = BeamGeometry3DView(self._project)
        self.geometry_3d_view.selection_changed.connect(self._selection_changed)
        self.geometry_3d_view.surface_sensor_requested.connect(
            self._add_surface_sensor_from_3d
        )
        self.geometry_3d_view.surface_sensor_move_requested.connect(
            self._move_surface_sensor_from_3d
        )
        self.geometry_3d_view.error_raised.connect(self._show_nonblocking_error)
        self.view_stack.addWidget(self.geometry_3d_view)
        surface_mode_button = self.mode_buttons[
            BeamGeometry3DView.MODE_ADD_SURFACE_SENSOR
        ]
        surface_mode_button.setEnabled(self.geometry_3d_view.backend_available)
        surface_mode_button.setToolTip(
            "切换到三维视图，在真实截面外表面单击连续添加测点"
            if self.geometry_3d_view.backend_available
            else "当前环境未安装或无法启动 PyVista/VTK 三维后端"
        )
        move_mode_button = self.mode_buttons[
            BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR
        ]
        move_mode_button.setEnabled(False)
        move_mode_button.setToolTip(
            "选择或直接按住测点贴片，在真实梁表面拖动；松开后可撤销"
            if self.geometry_3d_view.backend_available
            else "当前环境未安装或无法启动 PyVista/VTK 三维后端"
        )
        viewport_layout.addWidget(self.view_stack, 1)

        splitter.addWidget(viewport)
        splitter.addWidget(self._build_property_panel())
        splitter.setSizes([900, 330])
        splitter.setStretchFactor(0, 1)
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.footer_hint = QLabel()
        self.footer_hint.setObjectName("modelerStatus")
        self.footer_hint.setMinimumWidth(0)
        self.footer_hint.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        footer.addWidget(self.footer_hint)
        footer.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.apply_to_workspace_button = buttons.button(
            QDialogButtonBox.StandardButton.Apply
        )
        self.apply_to_workspace_button.setText("应用到工作台")
        self.apply_to_workspace_button.setToolTip(
            "将当前模型交回分析工作台并关闭建模器；不会自动写入项目库"
        )
        self.apply_to_workspace_button.setObjectName("workspacePrimary")
        buttons.rejected.connect(self.reject)
        self.apply_to_workspace_button.clicked.connect(self.accept)
        footer.addWidget(buttons)
        root.addLayout(footer)

        self.undo_stack.canUndoChanged.connect(self.undo_button.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_button.setEnabled)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self.delete_button.setEnabled(False)

    def _build_generator(self, root):
        generator = QFrame()
        generator.setObjectName("modelerGenerator")
        generator_layout = QVBoxLayout(generator)
        generator_layout.setContentsMargins(9, 6, 9, 6)
        generator_layout.setSpacing(5)

        parameter_row = QHBoxLayout()
        parameter_row.setSpacing(7)
        space_label = QLabel("空间")
        space_label.setObjectName("toolbarLabel")
        parameter_row.addWidget(space_label)
        self.model_space_group = QButtonGroup(self)
        self.model_space_group.setExclusive(True)
        self.model_space_buttons = {}
        for space, text in (("2d", "二维建模"), ("3d", "三维建模")):
            button = QPushButton(text)
            button.setObjectName("modelerModeButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, value=space: self._set_modeling_space(value)
            )
            self.model_space_group.addButton(button)
            self.model_space_buttons[space] = button
            parameter_row.addWidget(button)
        self.model_space_buttons[self._project.modeling_space].setChecked(True)

        space_divider = QFrame()
        space_divider.setObjectName("toolbarDivider")
        space_divider.setFrameShape(QFrame.Shape.VLine)
        space_divider.setFixedHeight(24)
        parameter_row.addWidget(space_divider)
        path_label = QLabel("路径")
        path_label.setObjectName("toolbarLabel")
        parameter_row.addWidget(path_label)
        self.geometry_combo = QComboBox()
        self.geometry_combo.addItem("直线段", "straight")
        self.geometry_combo.addItem("解析圆弧段", "arc")
        self.geometry_combo.currentIndexChanged.connect(self._generator_kind_changed)
        parameter_row.addWidget(self.geometry_combo)
        self.primary_label = QLabel("梁长")
        parameter_row.addWidget(self.primary_label)
        self.primary_spin = QDoubleSpinBox()
        self.primary_spin.setRange(0.001, 1.0e9)
        self.primary_spin.setDecimals(6)
        self.primary_spin.setSuffix(" m")
        self.primary_spin.setMinimumWidth(125)
        parameter_row.addWidget(self.primary_spin)
        self.secondary_label = QLabel("圆心角")
        parameter_row.addWidget(self.secondary_label)
        self.sweep_spin = QDoubleSpinBox()
        self.sweep_spin.setRange(-359.0, 359.0)
        self.sweep_spin.setDecimals(2)
        self.sweep_spin.setValue(90.0)
        self.sweep_spin.setSuffix("°")
        parameter_row.addWidget(self.sweep_spin)
        self.orientation_label = QLabel("方向")
        parameter_row.addWidget(self.orientation_label)
        self.orientation_combo = QComboBox()
        parameter_row.addWidget(self.orientation_combo)
        self.element_count_label = QLabel("单元数")
        parameter_row.addWidget(self.element_count_label)
        self.element_count_spin = QSpinBox()
        self.element_count_spin.setRange(1, 1000)
        parameter_row.addWidget(self.element_count_spin)
        parameter_row.addStretch(1)
        generator_layout.addLayout(parameter_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(7)
        action_row.addStretch(1)
        self.spatial_curve_button = QPushButton("空间曲线…")
        self.spatial_curve_button.setObjectName("modelerPathButton")
        self.spatial_curve_button.setToolTip(
            "通过三个空间点创建任意平面圆弧，或通过控制点创建 B 样条/NURBS"
        )
        self.spatial_curve_button.clicked.connect(self._create_spatial_curve)
        action_row.addWidget(self.spatial_curve_button)
        self.generate_button = QPushButton("新建路径")
        self.generate_button.setObjectName("modelerPathButton")
        self.generate_button.setToolTip("使用当前参数新建整条路径，并替换现有几何")
        self.generate_button.clicked.connect(self._generate_geometry)
        action_row.addWidget(self.generate_button)
        self.append_button = QPushButton("追加到末端")
        self.append_button.setObjectName("modelerPathButton")
        self.append_button.setToolTip("保留现有模型，在路径末端追加当前直线或圆弧段")
        self.append_button.clicked.connect(self._append_geometry)
        action_row.addWidget(self.append_button)
        generator_layout.addLayout(action_row)
        root.addWidget(generator)
        self.orientation_combo.currentIndexChanged.connect(
            self._generator_orientation_changed
        )
        self._generator_kind_changed()

    def _build_property_panel(self):
        panel = QFrame()
        panel.setObjectName("modelerInspector")
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        inspector_title = QLabel("属性")
        inspector_title.setObjectName("inspectorTitle")
        layout.addWidget(inspector_title)
        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setObjectName("inspectorTabs")
        self.property_stack = QStackedWidget()

        empty_page = QWidget()
        empty_page.setObjectName("inspectorPage")
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(8, 12, 8, 12)
        empty_layout.addStretch(1)
        empty_hint = QLabel("在画布中选择节点、梁段或测点\n即可在这里编辑工程属性")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setObjectName("sectionHint")
        empty_hint.setWordWrap(True)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch(1)
        self.property_stack.addWidget(empty_page)

        node_page = QWidget()
        node_page.setObjectName("inspectorPage")
        node_page.setMinimumHeight(300)
        node_layout = QVBoxLayout(node_page)
        node_layout.setContentsMargins(4, 12, 4, 8)
        node_layout.setSpacing(10)
        node_form = QFormLayout()
        node_form.setHorizontalSpacing(12)
        node_form.setVerticalSpacing(8)
        node_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.node_id_label = QLabel()
        self.node_x_edit = QLineEdit()
        self.node_y_edit = QLineEdit()
        self.node_z_edit = QLineEdit()
        node_form.addRow("节点 ID", self.node_id_label)
        node_form.addRow("x 坐标 (m)", self.node_x_edit)
        node_form.addRow("y 坐标 (m)", self.node_y_edit)
        node_form.addRow("z 坐标 (m)", self.node_z_edit)
        node_layout.addLayout(node_form)
        node_apply = QPushButton("更新节点坐标")
        node_apply.setObjectName("smallPrimaryButton")
        node_apply.clicked.connect(self._update_node_property)
        node_layout.addWidget(node_apply)
        node_layout.addStretch(1)
        self.property_stack.addWidget(node_page)

        element_page = QWidget()
        element_page.setObjectName("inspectorPage")
        element_page.setMinimumHeight(500)
        element_layout = QVBoxLayout(element_page)
        element_layout.setContentsMargins(4, 12, 4, 8)
        element_layout.setSpacing(10)
        element_form = QFormLayout()
        element_form.setHorizontalSpacing(12)
        element_form.setVerticalSpacing(8)
        element_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.element_id_label = QLabel()
        self.element_nodes_label = QLabel()
        self.element_length_label = QLabel()
        self.element_geometry_label = QLabel()
        self.arc_radius_label = QLabel("圆弧半径 (m)")
        self.arc_radius_edit = QLineEdit()
        self.arc_sweep_label = QLabel("圆心角 (°)")
        self.arc_sweep_edit = QLineEdit()
        self.arc_plane_label = QLabel("圆弧平面")
        self.arc_plane_combo = QComboBox()
        self.arc_plane_combo.addItem("XY 平面", "xy")
        self.arc_plane_combo.addItem("XZ 平面", "xz")
        self.arc_plane_combo.addItem("YZ 平面", "yz")
        self.arc_plane_combo.addItem("任意空间平面（保留法向）", "custom")
        self.element_family_combo = QComboBox()
        self.element_family_combo.addItem("二维 Euler-Bernoulli 梁", "beam2d_euler_bernoulli")
        self.element_family_combo.addItem("二维解析曲梁", "beam2d_curved")
        self.element_family_combo.addItem("空间线梁", "beam3d_line")
        self.element_family_combo.addItem("三维解析曲梁", "beam3d_curved")
        self.element_family_combo.addItem("参数化曲梁（旧项目）", "beam_curved")
        self.element_family_combo.addItem("曲梁折线段（旧项目）", "beam_curve_polyline")
        self.element_section_combo = QComboBox()
        self.element_material_combo = QComboBox()
        element_form.addRow("实体 ID", self.element_id_label)
        element_form.addRow("端点", self.element_nodes_label)
        element_form.addRow("长度", self.element_length_label)
        element_form.addRow("几何类型", self.element_geometry_label)
        element_form.addRow(self.arc_radius_label, self.arc_radius_edit)
        element_form.addRow(self.arc_sweep_label, self.arc_sweep_edit)
        element_form.addRow(self.arc_plane_label, self.arc_plane_combo)
        element_form.addRow("几何/单元族", self.element_family_combo)
        element_form.addRow("截面", self.element_section_combo)
        element_form.addRow("材料", self.element_material_combo)
        element_layout.addLayout(element_form)
        element_apply = QPushButton("更新梁实体")
        element_apply.setObjectName("smallPrimaryButton")
        element_apply.clicked.connect(self._update_element_property)
        element_layout.addWidget(element_apply)
        element_layout.addStretch(1)
        self.property_stack.addWidget(element_page)

        sensor_page = QWidget()
        sensor_page.setObjectName("inspectorPage")
        sensor_page.setMinimumHeight(430)
        sensor_layout = QVBoxLayout(sensor_page)
        sensor_layout.setContentsMargins(4, 12, 4, 8)
        sensor_layout.setSpacing(10)
        self.sensor_id_label = QLabel()
        self.sensor_label_edit = QLineEdit()
        self.sensor_element_combo = QComboBox()
        self.sensor_xi_edit = QLineEdit()
        self.sensor_position_label = QLabel()
        self.sensor_position_label.setWordWrap(True)
        self.sensor_surface_combo = QComboBox()
        self.sensor_surface_combo.addItem("局部上侧 (0°)", "top")
        self.sensor_surface_combo.addItem("局部下侧 (180°)", "bottom")
        self.sensor_surface_combo.addItem("自定义环向角", "custom")
        self.sensor_surface_combo.activated.connect(self._sensor_surface_preset_changed)
        self.sensor_surface_angle_edit = QLineEdit()
        self.sensor_orientation_angle_edit = QLineEdit()
        self.sensor_direction_label = QLabel()
        self.sensor_direction_label.setWordWrap(True)
        for data_label in (
            self.node_id_label,
            self.element_id_label,
            self.element_nodes_label,
            self.element_length_label,
            self.sensor_id_label,
            self.sensor_position_label,
            self.sensor_direction_label,
        ):
            data_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
        self.sensor_strain_edit = QLineEdit()
        self.sensor_weight_edit = QLineEdit()
        self.sensor_zone_a_edit = QLineEdit()
        self.sensor_zone_b_edit = QLineEdit()

        self.sensor_config_tabs = QTabWidget()
        self.sensor_config_tabs.setObjectName("sensorConfigTabs")

        position_page = QWidget()
        position_page.setObjectName("inspectorSubpage")
        position_form = QFormLayout(position_page)
        position_form.setContentsMargins(8, 10, 8, 8)
        position_form.setHorizontalSpacing(10)
        position_form.setVerticalSpacing(8)
        position_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        position_form.addRow("测点 ID", self.sensor_id_label)
        position_form.addRow("名称", self.sensor_label_edit)
        position_form.addRow("附着梁段", self.sensor_element_combo)
        position_form.addRow("局部坐标 ξ", self.sensor_xi_edit)
        position_form.addRow("位置 / 弧长", self.sensor_position_label)
        self.sensor_config_tabs.addTab(position_page, "定位")

        direction_page = QWidget()
        direction_page.setObjectName("inspectorSubpage")
        direction_form = QFormLayout(direction_page)
        direction_form.setContentsMargins(8, 10, 8, 8)
        direction_form.setHorizontalSpacing(10)
        direction_form.setVerticalSpacing(8)
        direction_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        direction_form.addRow("表面预设", self.sensor_surface_combo)
        direction_form.addRow("环向角 θ (°)", self.sensor_surface_angle_edit)
        direction_form.addRow("测量轴角 α (°)", self.sensor_orientation_angle_edit)
        direction_form.addRow("全局轴（±等价）", self.sensor_direction_label)
        self.sensor_config_tabs.addTab(direction_page, "方向")

        data_page = QWidget()
        data_page.setObjectName("inspectorSubpage")
        data_form = QFormLayout(data_page)
        data_form.setContentsMargins(8, 10, 8, 8)
        data_form.setHorizontalSpacing(10)
        data_form.setVerticalSpacing(8)
        data_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        data_form.addRow("应变 ε", self.sensor_strain_edit)
        data_form.addRow("权重", self.sensor_weight_edit)
        data_form.addRow("量长起点 a", self.sensor_zone_a_edit)
        data_form.addRow("量长终点 b", self.sensor_zone_b_edit)
        self.sensor_config_tabs.addTab(data_page, "数据")

        sensor_apply = QPushButton("更新测点")
        sensor_apply.setObjectName("smallPrimaryButton")
        sensor_apply.clicked.connect(self._update_sensor_property)
        quick_label = QLabel("快速布置")
        quick_label.setObjectName("toolbarLabel")
        sensor_action_top = QHBoxLayout()
        sensor_action_top.setSpacing(7)
        self.sensor_move_button = QPushButton("三维拖动")
        self.sensor_copy_button = QPushButton("复制")
        self.sensor_move_button.setObjectName("modelerToolButton")
        self.sensor_copy_button.setObjectName("modelerToolButton")
        self.sensor_move_button.setToolTip("进入三维拖动模式；按住贴片移动，松开提交")
        self.sensor_copy_button.setToolTip("复制布置参数并生成新测点；不复制通道和应变值")
        self.sensor_move_button.clicked.connect(self._activate_sensor_move_mode)
        self.sensor_copy_button.clicked.connect(self._copy_selected_sensor)
        sensor_action_top.addWidget(self.sensor_move_button, 1)
        sensor_action_top.addWidget(self.sensor_copy_button, 1)
        sensor_action_bottom = QHBoxLayout()
        sensor_action_bottom.setSpacing(7)
        self.sensor_opposite_button = QPushButton("对侧布置")
        self.sensor_array_button = QPushButton("等距阵列")
        self.sensor_opposite_button.setObjectName("modelerToolButton")
        self.sensor_array_button.setObjectName("modelerToolButton")
        self.sensor_opposite_button.setToolTip(
            "在相同梁长位置的截面对侧生成测点；新点不复制通道和应变值"
        )
        self.sensor_array_button.setToolTip(
            "按真实路径弧长生成等间距测点，可跨直梁和圆弧；新点不复制通道和应变值"
        )
        self.sensor_opposite_button.clicked.connect(self._add_opposite_sensor)
        self.sensor_array_button.clicked.connect(self._array_selected_sensor)
        sensor_action_bottom.addWidget(self.sensor_opposite_button, 1)
        sensor_action_bottom.addWidget(self.sensor_array_button, 1)
        for button in (
            self.sensor_move_button,
            self.sensor_copy_button,
            self.sensor_opposite_button,
            self.sensor_array_button,
        ):
            button.setEnabled(False)
        sensor_layout.addWidget(quick_label)
        sensor_layout.addLayout(sensor_action_top)
        sensor_layout.addLayout(sensor_action_bottom)
        sensor_layout.addWidget(self.sensor_config_tabs)
        sensor_layout.addWidget(sensor_apply)
        sensor_layout.addStretch(1)
        self.property_stack.addWidget(sensor_page)
        self.property_stack.removeWidget(element_page)
        self.property_stack.addWidget(element_page)
        property_scroll = QScrollArea()
        property_scroll.setObjectName("inspectorScroll")
        property_scroll.setWidgetResizable(True)
        property_scroll.setFrameShape(QFrame.Shape.NoFrame)
        property_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.property_stack.setObjectName("inspectorPage")
        property_scroll.setWidget(self.property_stack)

        primary_group = QWidget()
        primary_group.setObjectName("inspectorPage")
        primary_layout = QFormLayout(primary_group)
        primary_layout.setContentsMargins(4, 10, 4, 8)
        primary_layout.setHorizontalSpacing(12)
        primary_layout.setVerticalSpacing(8)
        primary_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.section_shape_combo = QComboBox()
        for shape, label in SECTION_SHAPE_LABELS.items():
            self.section_shape_combo.addItem(label, shape)
        self.section_shape_combo.currentIndexChanged.connect(
            self._section_shape_changed
        )
        primary_layout.addRow("截面类型", self.section_shape_combo)
        self.section_preview = SectionProfilePreview()
        primary_layout.addRow(self.section_preview)
        self.section_parameter_labels = []
        self.section_parameter_edits = []
        for _index in range(4):
            label = QLabel()
            edit = QLineEdit()
            self.section_parameter_labels.append(label)
            self.section_parameter_edits.append(edit)
            edit.textChanged.connect(self._refresh_section_preview_from_form)
            primary_layout.addRow(label, edit)
        # Compatibility aliases for older UI integrations and tests.
        self.section_thickness_edit = self.section_parameter_edits[0]
        self.section_width_edit = self.section_parameter_edits[1]
        self.material_e_edit = QLineEdit()
        primary_layout.addRow("弹性模量 (GPa)", self.material_e_edit)
        primary_apply = QPushButton("应用全局属性")
        primary_apply.setObjectName("smallPrimaryButton")
        primary_apply.clicked.connect(self._update_primary_properties)
        primary_layout.addRow(primary_apply)
        section_scroll = QScrollArea()
        section_scroll.setObjectName("inspectorScroll")
        section_scroll.setWidgetResizable(True)
        section_scroll.setFrameShape(QFrame.Shape.NoFrame)
        section_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        section_scroll.setWidget(primary_group)
        self.inspector_tabs.addTab(section_scroll, "截面与材料")
        self.inspector_tabs.addTab(property_scroll, "对象属性")
        layout.addWidget(self.inspector_tabs, 1)
        return panel

    def _set_mode(self, mode: str):
        is_3d_mode = mode in {
            BeamGeometry3DView.MODE_ADD_SURFACE_SENSOR,
            BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR,
        }
        self.canvas.set_mode(BeamModelCanvas.MODE_SELECT if is_3d_mode else mode)
        self.geometry_3d_view.set_mode(
            mode if is_3d_mode else BeamGeometry3DView.MODE_SELECT
        )
        if is_3d_mode:
            self.view_stack.setCurrentIndex(1)
            self.view_buttons["3d"].setChecked(True)
            self.plane_combo.setEnabled(False)
        elif self.view_stack.currentIndex() == 1 and mode != BeamModelCanvas.MODE_SELECT:
            self.view_stack.setCurrentIndex(0)
            self.view_buttons["2d"].setChecked(True)
            self.plane_combo.setEnabled(True)

    def _switch_view(self, index: int):
        if (
            index == 0
            and self.geometry_3d_view.mode != BeamGeometry3DView.MODE_SELECT
        ) or (index == 1 and self.canvas.mode != BeamModelCanvas.MODE_SELECT):
            self.mode_buttons[BeamModelCanvas.MODE_SELECT].setChecked(True)
            self.canvas.set_mode(BeamModelCanvas.MODE_SELECT)
            self.geometry_3d_view.set_mode(BeamGeometry3DView.MODE_SELECT)
        self.view_stack.setCurrentIndex(index)
        key = "3d" if index == 1 else "2d"
        self.view_buttons[key].setChecked(True)
        self.plane_combo.setEnabled(
            index == 0 and self._project.modeling_space == "3d"
        )

    def _set_modeling_space(self, modeling_space: str):
        if modeling_space == self._project.modeling_space:
            self._generator_kind_changed()
            return
        try:
            before = self._project
            after = PathBeamEditor.set_modeling_space(before, modeling_space)
            self._commit_project(
                before,
                after,
                "切换二维建模" if modeling_space == "2d" else "切换三维建模",
            )
            self._selection_changed("", "")
        except (TypeError, ValueError) as exc:
            self.model_space_buttons[self._project.modeling_space].setChecked(True)
            QMessageBox.warning(self, "切换建模空间", str(exc))

    def _generator_kind_changed(self, *_args):
        kind = self.geometry_combo.currentData()
        modeling_space = self._project.modeling_space
        current_orientation = self.orientation_combo.currentData()
        self.orientation_combo.clear()
        if kind == "arc":
            self.primary_label.setText("半径")
            self.secondary_label.show()
            self.sweep_spin.show()
            self.orientation_label.setText("平面")
            self.orientation_combo.addItem("XY", "xy")
            if modeling_space == "3d":
                self.orientation_combo.addItem("XZ", "xz")
                self.orientation_combo.addItem("YZ", "yz")
            self.element_count_label.hide()
            self.element_count_spin.hide()
            self.append_button.setText("追加圆弧段")
        else:
            self.primary_label.setText("段长")
            self.secondary_label.hide()
            self.sweep_spin.hide()
            self.orientation_label.setText("方向")
            self.orientation_combo.addItem("+X", "x")
            self.orientation_combo.addItem("-X", "-x")
            self.orientation_combo.addItem("+Y", "y")
            self.orientation_combo.addItem("-Y", "-y")
            if modeling_space == "3d":
                self.orientation_combo.addItem("+Z", "z")
                self.orientation_combo.addItem("-Z", "-z")
            self.orientation_combo.addItem("沿末端切线", "tangent")
            self.element_count_spin.setMinimum(1)
            self.element_count_label.setText("新建单元数")
            self.element_count_label.show()
            self.element_count_spin.show()
            self.append_button.setText("追加直线段")
        orientation_index = self.orientation_combo.findData(current_orientation)
        if orientation_index >= 0:
            self.orientation_combo.setCurrentIndex(orientation_index)
        self._generator_orientation_changed()

    def _generator_orientation_changed(self, *_args):
        if not hasattr(self, "generate_button"):
            return
        tangent_only = (
            self.geometry_combo.currentData() == "straight"
            and self.orientation_combo.currentData() == "tangent"
        )
        self.generate_button.setEnabled(not tangent_only)
        self.generate_button.setToolTip(
            "沿末端切线仅适用于追加；新建路径请选择全局方向"
            if tangent_only
            else "使用当前参数新建整条路径，并替换现有几何"
        )

    def _sensor_surface_preset_changed(self, *_args):
        preset = self.sensor_surface_combo.currentData()
        if preset in {"top", "bottom"}:
            self.sensor_surface_angle_edit.setText("0" if preset == "top" else "180")

    def _configure_section_fields(self, shape: str, values=None):
        specs = SECTION_PARAMETER_SPECS[shape]
        section = self._project.sections[0] if self._project.sections else None
        defaults = default_section_parameters(
            shape,
            height=section.thickness if section is not None else 0.1,
            width=section.width if section is not None else None,
        )
        values = defaults if values is None else values
        for index, (label, edit) in enumerate(
            zip(self.section_parameter_labels, self.section_parameter_edits)
        ):
            visible = index < len(specs)
            label.setVisible(visible)
            edit.setVisible(visible)
            if not visible:
                edit.clear()
                continue
            spec = specs[index]
            label.setText(spec.label)
            edit.setText(f"{float(values.get(spec.key, defaults[spec.key])):.12g}")

    def _section_shape_changed(self, *_args):
        if self._loading_section:
            return
        shape = self.section_shape_combo.currentData()
        if shape:
            self._configure_section_fields(shape)
            self._refresh_section_preview_from_form()

    @staticmethod
    def _section_overall_dimensions(shape: str, parameters):
        if shape == "rectangle":
            return parameters["height"], parameters["width"]
        if shape in {"circle", "circular_tube"}:
            key = "diameter" if shape == "circle" else "outer_diameter"
            return parameters[key], parameters[key]
        if shape == "box":
            return parameters["outer_height"], parameters["outer_width"]
        return parameters["height"], parameters["flange_width"]

    def _refresh_section_preview_from_form(self, *_args):
        if self._loading_section or not hasattr(self, "section_preview"):
            return
        try:
            shape = self.section_shape_combo.currentData()
            specs = SECTION_PARAMETER_SPECS[shape]
            parameters = {
                spec.key: float(self.section_parameter_edits[index].text())
                for index, spec in enumerate(specs)
            }
            thickness, width = self._section_overall_dimensions(shape, parameters)
            preview = SectionDefinition(
                "section_preview",
                "截面预览",
                thickness,
                width,
                shape,
                parameters,
            )
        except (KeyError, TypeError, ValueError):
            preview = None
        self.section_preview.set_section(preview)

    def _set_status(self, text: str, state: str):
        self.footer_hint.setText(text)
        self.footer_hint.setProperty("state", state)
        self.footer_hint.style().unpolish(self.footer_hint)
        self.footer_hint.style().polish(self.footer_hint)

    def _apply_project(self, project: ProjectDocument):
        PathBeamEditor.ordered_path(project)
        self._project = project
        valid_ids = {
            entity.identifier
            for entity in project.nodes + project.elements + project.sensors
        }
        if self.selected_id and self.selected_id not in valid_ids:
            self.selected_kind = ""
            self.selected_id = ""
        self.model_space_buttons[project.modeling_space].setChecked(True)
        self._generator_kind_changed()
        is_3d_model = project.modeling_space == "3d"
        self.node_z_edit.setEnabled(is_3d_model)
        self.node_z_edit.setToolTip(
            "三维建模中可编辑 z 坐标"
            if is_3d_model
            else "二维模型固定在 XY 平面，z 坐标恒为 0"
        )
        self.arc_plane_combo.setEnabled(is_3d_model)
        if not is_3d_model:
            self.plane_combo.setCurrentIndex(self.plane_combo.findData("xy"))
        self.plane_combo.setEnabled(
            is_3d_model and self.view_stack.currentIndex() == 0
        )
        self.canvas.set_project(project)
        self.geometry_3d_view.set_project(project)
        move_mode_button = self.mode_buttons[
            BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR
        ]
        move_mode_button.setEnabled(
            self.geometry_3d_view.backend_available and bool(project.sensors)
        )
        if (
            not project.sensors
            and self.geometry_3d_view.mode
            == BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR
        ):
            self.mode_buttons[BeamModelCanvas.MODE_SELECT].setChecked(True)
            self.geometry_3d_view.set_mode(BeamGeometry3DView.MODE_SELECT)
        capability = PathBeamEditor.capability(project)
        has_geometry = bool(project.elements)
        self.generate_button.setText(
            "替换当前路径" if has_geometry else "新建路径"
        )
        self.generate_button.setToolTip(
            "使用当前参数替换全部现有几何；现有测点和边界约束将被清空"
            if has_geometry
            else "使用当前参数创建第一条结构路径"
        )
        dimension_label = "二维" if capability.dimension == 2 else "三维"
        self.summary_label.setText(
            f"{dimension_label} · {capability.total_length:.6g} m · "
            f"{len(project.elements)} 梁段 · "
            f"{len(project.sensors)} 测点"
        )
        matches = match_project_algorithms(
            project,
            get_default_analysis_service().registry.list(),
        )
        compatible_matches = [match for match in matches if match.compatible]
        algorithm_status = (
            "算法 · " + " / ".join(match.display_name for match in compatible_matches)
            if compatible_matches
            else "无可用算法"
        )
        self.capability_label.setText(algorithm_status)
        self._set_status(
            "模型就绪" if compatible_matches else "等待算法插件",
            "ready" if compatible_matches else "waiting",
        )
        arc_elements = [
            element
            for element in project.elements
            if element.geometry.kind == "circular_arc"
        ]
        if len(project.elements) == 1 and len(arc_elements) == 1:
            arc = arc_elements[0]
            parameters = arc.geometry.parameters
            self.geometry_combo.setCurrentIndex(self.geometry_combo.findData("arc"))
            self.primary_spin.setValue(float(parameters["radius"]))
            self.sweep_spin.setValue(float(parameters["sweep_degrees"]))
            self.orientation_combo.setCurrentIndex(
                max(self.orientation_combo.findData(parameters["plane"]), 0)
            )
        else:
            self.geometry_combo.setCurrentIndex(self.geometry_combo.findData("straight"))
            self.primary_spin.setValue(max(capability.total_length, 0.001))
            self.element_count_spin.setValue(len(project.elements))
        section = project.sections[0] if project.sections else None
        material = project.materials[0] if project.materials else None
        self._loading_section = True
        try:
            shape = section.shape if section is not None else "rectangle"
            shape_index = self.section_shape_combo.findData(shape)
            self.section_shape_combo.setCurrentIndex(max(shape_index, 0))
            self._configure_section_fields(
                shape,
                None if section is None else section.parameters,
            )
            self.section_preview.set_section(section)
        finally:
            self._loading_section = False
        self.material_e_edit.setText(
            ""
            if material is None or material.elastic_modulus is None
            else f"{material.elastic_modulus / 1.0e9:.12g}"
        )
        self.delete_button.setEnabled(
            self.selected_kind in {"node", "sensor"} and bool(self.selected_id)
        )
        self._update_sensor_action_state()
        self._refresh_property_panel()

    def _commit_project(self, before, after, description):
        self.undo_stack.push(ProjectSnapshotCommand(self, before, after, description))

    def _add_surface_sensor_from_3d(self, location: BeamSurfaceLocation):
        try:
            if not isinstance(location, BeamSurfaceLocation):
                raise TypeError("三维拾取结果类型无效。")
            before = self._project
            after = PathBeamEditor.add_sensor(
                before,
                location.element_id,
                location.local_coordinate,
                location.surface_side,
                surface_angle_degrees=location.surface_angle_degrees,
            )
            sensor = after.sensors[-1]
            self._commit_project(before, after, "三维表面添加测点")
            self._selection_changed("sensor", sensor.identifier)
            self._set_status(f"已添加 {sensor.label}", "ready")
        except (KeyError, TypeError, ValueError) as exc:
            self._show_nonblocking_error(str(exc))

    def _move_surface_sensor_from_3d(
        self,
        sensor_id: str,
        location: BeamSurfaceLocation,
    ):
        try:
            before = self._project
            after = PathBeamEditor.move_sensor_to_surface(
                before,
                sensor_id,
                location,
            )
            self._commit_project(before, after, "三维拖动测点")
            self._selection_changed("sensor", sensor_id)
            sensor = next(item for item in after.sensors if item.identifier == sensor_id)
            self._set_status(f"已移动 {sensor.label}", "ready")
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            self._show_nonblocking_error(str(exc))

    def _selected_sensor(self):
        if self.selected_kind != "sensor":
            return None
        return next(
            (
                sensor
                for sensor in self._project.sensors
                if sensor.identifier == self.selected_id
            ),
            None,
        )

    def _activate_sensor_move_mode(self):
        if self._selected_sensor() is None:
            return
        button = self.mode_buttons[BeamGeometry3DView.MODE_MOVE_SURFACE_SENSOR]
        if button.isEnabled():
            button.click()

    def _copy_selected_sensor(self):
        sensor = self._selected_sensor()
        if sensor is None:
            return
        try:
            before = self._project
            after = PathBeamEditor.duplicate_sensor(before, sensor.identifier)
            duplicate = after.sensors[-1]
            self._commit_project(before, after, "复制应变测点")
            self._selection_changed("sensor", duplicate.identifier)
            self._set_status(f"已复制为 {duplicate.label}", "ready")
            self._activate_sensor_move_mode()
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "复制测点", str(exc))

    def _add_opposite_sensor(self):
        sensor = self._selected_sensor()
        if sensor is None:
            return
        try:
            before = self._project
            after = PathBeamEditor.add_opposite_sensor(before, sensor.identifier)
            opposite = after.sensors[-1]
            self._commit_project(before, after, "创建对侧测点")
            self._selection_changed("sensor", opposite.identifier)
            self._set_status(f"已创建对侧测点 {opposite.label}", "ready")
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "对侧布置", str(exc))

    def _array_selected_sensor(
        self,
        *,
        count: int | None = None,
        spacing: float | None = None,
        direction: int | None = None,
    ):
        sensor = self._selected_sensor()
        if sensor is None:
            return
        try:
            if count is None or spacing is None or direction is None:
                source = PathBeamEditor.sensor_location(
                    self._project,
                    sensor.identifier,
                )
                dialog = SensorArrayDialog(
                    sensor.label,
                    source.path_distance,
                    PathBeamEditor.total_length(self._project),
                    self,
                )
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                count, spacing, direction = dialog.array_values
            before = self._project
            after = PathBeamEditor.array_sensor(
                before,
                sensor.identifier,
                count=count,
                spacing=spacing,
                direction=direction,
            )
            last_sensor = after.sensors[-1]
            self._commit_project(before, after, "创建等距测点阵列")
            self._selection_changed("sensor", last_sensor.identifier)
            self._set_status(f"已新增 {count} 个等距测点", "ready")
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "等距阵列", str(exc))

    def _selection_changed(self, kind: str, identifier: str):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            self.selected_kind = kind
            self.selected_id = identifier
            self.canvas.select_entity(kind, identifier, emit=False)
            self.geometry_3d_view.select_entity(kind, identifier)
            self.delete_button.setEnabled(kind in {"node", "sensor"} and bool(identifier))
            self._update_sensor_action_state()
            self._refresh_property_panel()
            if kind and identifier:
                self.inspector_tabs.setCurrentIndex(1)
        finally:
            self._syncing_selection = False

    def _fill_entity_combos(self):
        elements = PathBeamEditor.ordered_elements(self._project)
        self.sensor_element_combo.clear()
        for index, element in enumerate(elements):
            self.sensor_element_combo.addItem(f"E{index + 1}", element.identifier)
        self.element_section_combo.clear()
        for section in self._project.sections:
            self.element_section_combo.addItem(section.name, section.identifier)
        self.element_material_combo.clear()
        for material in self._project.materials:
            self.element_material_combo.addItem(material.name, material.identifier)

    def _update_sensor_action_state(self):
        selected = self._selected_sensor() is not None
        self.sensor_move_button.setEnabled(
            selected and self.geometry_3d_view.backend_available
        )
        for button in (
            self.sensor_copy_button,
            self.sensor_opposite_button,
            self.sensor_array_button,
        ):
            button.setEnabled(selected)

    def _refresh_property_panel(self):
        self._update_sensor_action_state()
        self._fill_entity_combos()
        if self.selected_kind == "node":
            node = next(
                (item for item in self._project.nodes if item.identifier == self.selected_id),
                None,
            )
            if node is not None:
                self.property_stack.setCurrentIndex(1)
                self.node_id_label.setText(node.identifier[-10:])
                self.node_id_label.setToolTip(node.identifier)
                self.node_x_edit.setText(f"{node.coordinates[0]:.12g}")
                self.node_y_edit.setText(f"{node.coordinates[1]:.12g}")
                self.node_z_edit.setText(f"{node.coordinates[2]:.12g}")
                return
        if self.selected_kind == "element":
            element = next(
                (item for item in self._project.elements if item.identifier == self.selected_id),
                None,
            )
            if element is not None:
                self.property_stack.setCurrentIndex(3)
                self.element_id_label.setText(element.identifier[-10:])
                self.element_id_label.setToolTip(element.identifier)
                self.element_nodes_label.setText(
                    f"{element.node_ids[0][-6:]} → {element.node_ids[1][-6:]}"
                )
                self.element_nodes_label.setToolTip(
                    f"{element.node_ids[0]} → {element.node_ids[1]}"
                )
                self.element_length_label.setText(
                    f"{PathBeamEditor.element_length(self._project, element):.8g} m"
                )
                is_arc = element.geometry.kind == "circular_arc"
                is_nurbs = element.geometry.kind == "nurbs_curve"
                if is_arc:
                    geometry_text = "参数化圆弧"
                elif is_nurbs:
                    parameters = element.geometry.parameters
                    geometry_text = (
                        f"{parameters['degree']} 次 NURBS · "
                        f"{len(parameters['control_points'])} 控制点"
                    )
                else:
                    geometry_text = "直线"
                self.element_geometry_label.setText(geometry_text)
                for widget in (
                    self.arc_radius_label,
                    self.arc_radius_edit,
                    self.arc_sweep_label,
                    self.arc_sweep_edit,
                    self.arc_plane_label,
                    self.arc_plane_combo,
                ):
                    widget.setVisible(is_arc)
                if is_arc:
                    parameters = element.geometry.parameters
                    self.arc_radius_edit.setText(f"{float(parameters['radius']):.12g}")
                    self.arc_sweep_edit.setText(
                        f"{float(parameters['sweep_degrees']):.12g}"
                    )
                    self.arc_plane_combo.setCurrentIndex(
                        max(self.arc_plane_combo.findData(parameters["plane"]), 0)
                    )
                family_index = self.element_family_combo.findData(element.family)
                if family_index < 0:
                    self.element_family_combo.addItem(element.family, element.family)
                    family_index = self.element_family_combo.count() - 1
                self.element_family_combo.setCurrentIndex(family_index)
                self.element_family_combo.setEnabled(not (is_arc or is_nurbs))
                self.element_section_combo.setCurrentIndex(
                    max(self.element_section_combo.findData(element.section_id), 0)
                )
                self.element_material_combo.setCurrentIndex(
                    max(self.element_material_combo.findData(element.material_id), 0)
                )
                return
        if self.selected_kind == "sensor":
            sensor = next(
                (item for item in self._project.sensors if item.identifier == self.selected_id),
                None,
            )
            if sensor is not None:
                location = PathBeamEditor.sensor_location(self._project, sensor.identifier)
                self.property_stack.setCurrentIndex(2)
                self.sensor_id_label.setText(sensor.identifier[-10:])
                self.sensor_id_label.setToolTip(sensor.identifier)
                self.sensor_label_edit.setText(sensor.label)
                self.sensor_element_combo.setCurrentIndex(
                    max(self.sensor_element_combo.findData(sensor.attachment.entity_id), 0)
                )
                self.sensor_xi_edit.setText(f"{sensor.attachment.local_coordinates[0]:.12g}")
                point = PathBeamEditor.sensor_surface_position(self._project, sensor)
                axis_point = location.global_position
                self.sensor_position_label.setText(
                    f"表面 ({point[0]:.6g}, {point[1]:.6g}, {point[2]:.6g}) m\n"
                    f"轴线 ({axis_point[0]:.6g}, {axis_point[1]:.6g}, {axis_point[2]:.6g}) m"
                    f" · s={location.path_distance:.6g} m"
                )
                surface_angle = sensor.attachment.surface_angle_degrees
                if min(abs(surface_angle), abs(surface_angle - 360.0)) <= 1.0e-8:
                    surface_preset = "top"
                elif abs(surface_angle - 180.0) <= 1.0e-8:
                    surface_preset = "bottom"
                else:
                    surface_preset = "custom"
                self.sensor_surface_combo.setCurrentIndex(
                    max(self.sensor_surface_combo.findData(surface_preset), 0)
                )
                self.sensor_surface_angle_edit.setText(
                    f"{sensor.attachment.surface_angle_degrees:.12g}"
                )
                self.sensor_orientation_angle_edit.setText(
                    f"{sensor.attachment.orientation_angle_degrees:.12g}"
                )
                direction = sensor.attachment.direction
                self.sensor_direction_label.setText(
                    f"({direction[0]:.6g}, {direction[1]:.6g}, {direction[2]:.6g})"
                )
                self.sensor_strain_edit.setText(f"{float(sensor.measured_value or 0.0):.12g}")
                self.sensor_weight_edit.setText(f"{sensor.weight:.12g}")
                bounds = sensor.attachment.integration_bounds
                self.sensor_zone_a_edit.setText(f"{bounds[0]:.12g}")
                self.sensor_zone_b_edit.setText(f"{bounds[1]:.12g}")
                return
        self.property_stack.setCurrentIndex(0)
        self.delete_button.setEnabled(False)

    def _update_node_property(self):
        try:
            before = self._project
            after = PathBeamEditor.move_node(
                before,
                self.selected_id,
                (
                    float(self.node_x_edit.text()),
                    float(self.node_y_edit.text()),
                    float(self.node_z_edit.text()),
                ),
            )
            self._commit_project(before, after, "编辑节点三维坐标")
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "节点属性", str(exc))

    def _update_element_property(self):
        try:
            before = self._project
            element = next(
                item for item in before.elements if item.identifier == self.selected_id
            )
            after = PathBeamEditor.update_element(
                before,
                self.selected_id,
                family=self.element_family_combo.currentData(),
                section_id=self.element_section_combo.currentData(),
                material_id=self.element_material_combo.currentData(),
            )
            description = "编辑梁实体属性"
            if element.geometry.kind == "circular_arc":
                after = PathBeamEditor.update_circular_arc(
                    after,
                    self.selected_id,
                    radius=float(self.arc_radius_edit.text()),
                    sweep_degrees=float(self.arc_sweep_edit.text()),
                    plane=self.arc_plane_combo.currentData(),
                )
                description = "编辑参数化圆弧"
            self._commit_project(before, after, description)
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "梁段属性", str(exc))

    def _update_sensor_property(self):
        try:
            before = self._project
            sensor = next(
                item for item in before.sensors if item.identifier == self.selected_id
            )
            surface_angle = float(self.sensor_surface_angle_edit.text()) % 360.0
            surface_side = (
                "top" if surface_angle < 90.0 or surface_angle >= 270.0 else "bottom"
            )
            after = PathBeamEditor.update_sensor(
                before,
                self.selected_id,
                element_id=self.sensor_element_combo.currentData(),
                local_coordinate=float(self.sensor_xi_edit.text()),
                surface_side=surface_side,
                direction=sensor.attachment.direction,
                measured_value=float(self.sensor_strain_edit.text()),
                weight=float(self.sensor_weight_edit.text()),
                zone_a=float(self.sensor_zone_a_edit.text()),
                zone_b=float(self.sensor_zone_b_edit.text()),
                label=self.sensor_label_edit.text(),
                surface_angle_degrees=surface_angle,
                orientation_angle_degrees=float(
                    self.sensor_orientation_angle_edit.text()
                ),
            )
            self._commit_project(before, after, "编辑测点属性")
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "测点属性", str(exc))

    def _update_primary_properties(self):
        try:
            shape = self.section_shape_combo.currentData()
            specs = SECTION_PARAMETER_SPECS[shape]
            parameters = {
                spec.key: float(self.section_parameter_edits[index].text())
                for index, spec in enumerate(specs)
            }
            thickness, width = self._section_overall_dimensions(shape, parameters)
            modulus_text = self.material_e_edit.text().strip()
            before = self._project
            after = PathBeamEditor.update_primary_properties(
                before,
                thickness=thickness,
                width=width,
                elastic_modulus=None if not modulus_text else float(modulus_text) * 1.0e9,
                section_shape=shape,
                section_parameters=parameters,
            )
            self._commit_project(before, after, "编辑统一截面与材料")
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "截面与材料", str(exc))

    def _delete_selected(self):
        if not self.selected_id:
            return
        try:
            before = self._project
            if self.selected_kind == "node":
                after = PathBeamEditor.delete_node(before, self.selected_id)
                description = "删除梁节点"
            elif self.selected_kind == "sensor":
                after = PathBeamEditor.delete_sensor(before, self.selected_id)
                description = "删除应变测点"
            else:
                return
            self._commit_project(before, after, description)
            self._selection_changed("", "")
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "删除对象", str(exc))

    def _confirm_geometry_replacement(self):
        if self._project.sensors or self._project.boundary_conditions:
            cleared_items = []
            if self._project.sensors:
                cleared_items.append(f"{len(self._project.sensors)} 个测点")
            if self._project.boundary_conditions:
                cleared_items.append(
                    f"{len(self._project.boundary_conditions)} 条边界约束"
                )
            answer = QMessageBox.question(
                self,
                "替换当前模型",
                "参数化生成会替换当前几何，并清空"
                + "和".join(cleared_items)
                + "。此操作可以撤销，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        return True

    def _generate_geometry(self):
        if not self._confirm_geometry_replacement():
            return
        try:
            before = self._project
            if self.geometry_combo.currentData() == "arc":
                after = PathBeamEditor.create_circular_arc(
                    before,
                    radius=self.primary_spin.value(),
                    sweep_degrees=self.sweep_spin.value(),
                    plane=self.orientation_combo.currentData(),
                )
                description = "新建解析圆弧路径"
            else:
                after = PathBeamEditor.create_straight_beam(
                    before,
                    length=self.primary_spin.value(),
                    element_count=self.element_count_spin.value(),
                    axis=self.orientation_combo.currentData(),
                )
                description = "新建直线路径"
            self._commit_project(before, after, description)
            self._selection_changed("", "")
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "参数化生成", str(exc))

    def _create_spatial_curve(self):
        dialog = SpatialCurveDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._confirm_geometry_replacement():
            return
        try:
            definition = dialog.curve_definition
            before = self._project
            if definition["kind"] == SpatialCurveDialog.ARC:
                start, through, end = definition["points"]
                after = PathBeamEditor.create_circular_arc_through_points(
                    before,
                    start=start,
                    through=through,
                    end=end,
                )
                description = "新建任意平面圆弧"
            else:
                after = PathBeamEditor.create_nurbs_curve(
                    before,
                    control_points=definition["points"],
                    degree=definition["degree"],
                    weights=definition["weights"],
                )
                description = "新建空间 NURBS 曲线"
            self._commit_project(before, after, description)
            self._selection_changed("", "")
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "空间曲线", str(exc))

    def _append_geometry(self):
        try:
            before = self._project
            if self.geometry_combo.currentData() == "arc":
                after = PathBeamEditor.append_circular_arc(
                    before,
                    radius=self.primary_spin.value(),
                    sweep_degrees=self.sweep_spin.value(),
                    plane=self.orientation_combo.currentData(),
                )
                description = "追加解析圆弧段"
            else:
                after = PathBeamEditor.append_straight_segment(
                    before,
                    length=self.primary_spin.value(),
                    direction=self.orientation_combo.currentData(),
                )
                description = "追加直线段"
            self._commit_project(before, after, description)
            self._selection_changed("", "")
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "追加路径段", str(exc))

    def _open_project(self):
        path = ProjectLibraryDialog.choose_project(
            self,
            library=self._project_library,
            theme_id=self._theme_id,
        )
        if not path:
            return
        try:
            project = load_project(path)
            PathBeamEditor.ordered_path(project)
            self._project_path = Path(path)
            self._saved_revision = project.revision
            self.undo_stack.clear()
            self._selection_changed("", "")
            self._apply_project(project)
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "打开项目失败", str(exc))

    def _save_project(self):
        path = self._project_path
        if not path:
            selection = ProjectNameDialog.choose_project_name(
                self,
                library=self._project_library,
                initial_name=self._project.name,
                title="保存项目",
                confirm_text="保存项目",
                theme_id=self._theme_id,
            )
            if selection is None:
                return
            project_name, path = selection
            if self._project.name != project_name:
                self._project = self._project.revised(name=project_name)
        if not path:
            return
        try:
            destination = save_project(path, self._project)
            self._project_path = destination
            self._saved_revision = self._project.revision
            self._set_status("项目已保存", "ready")
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "保存项目失败", str(exc))

    def _show_nonblocking_error(self, message: str):
        QToolTip.showText(self.mapToGlobal(self.rect().center()), str(message), self)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Escape
            and (
                self.canvas.mode != BeamModelCanvas.MODE_SELECT
                or self.geometry_3d_view.mode
                != BeamGeometry3DView.MODE_SELECT
            )
        ):
            self.mode_buttons[BeamModelCanvas.MODE_SELECT].click()
            event.accept()
            return
        super().keyPressEvent(event)

    def apply_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        self.setStyleSheet(compose_stylesheet(MODELER_STYLESHEET, self._theme_id))
        if hasattr(self, "canvas"):
            self.canvas.set_theme(self._theme_id)
        if hasattr(self, "section_preview"):
            self.section_preview.set_theme(self._theme_id)
        if hasattr(self, "geometry_3d_view"):
            self.geometry_3d_view.apply_theme(self._theme_id)

    def shutdown(self):
        if hasattr(self, "geometry_3d_view"):
            self.geometry_3d_view.shutdown()

    def done(self, result):
        self.shutdown()
        super().done(result)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
