from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ifem.domain.project import ProjectDocument
from ifem.modeling.path_editor import PathBeamEditor
from ifem.modeling.section_geometry import (
    section_max_dimension,
    section_outer_radius,
    section_shape_label,
    sweep_section_mesh,
)
from ifem.ui.vtk_lifecycle import (
    interactor_is_active,
    render_interactor_now,
    shutdown_interactor,
)
from ifem.ui.theme import current_theme_id, resolve_theme
from ifem.visualization import bidirectional_axis_glyph, oriented_surface_patch_glyph


os.environ["QT_API"] = "pyside6"
_qt_platform = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
try:
    if _qt_platform in {"offscreen", "minimal"}:
        raise RuntimeError("当前 Qt 平台不支持嵌入式 VTK 渲染。")
    import pyvista as pv
    from pyvistaqt import QtInteractor
    from vtkmodules.vtkRenderingCore import vtkCellPicker

    MODEL_3D_AVAILABLE = True
    MODEL_3D_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on native rendering packages
    pv = None
    QtInteractor = None
    MODEL_3D_AVAILABLE = False
    MODEL_3D_IMPORT_ERROR = exc


class BeamGeometry3DView(QWidget):
    selection_changed = Signal(str, str)
    surface_sensor_requested = Signal(object)
    surface_sensor_move_requested = Signal(str, object)
    error_raised = Signal(str)
    backend_available = MODEL_3D_AVAILABLE

    MODE_SELECT = "select"
    MODE_ADD_SURFACE_SENSOR = "add_surface_sensor"
    MODE_MOVE_SURFACE_SENSOR = "move_surface_sensor"

    def __init__(self, project: ProjectDocument, parent=None):
        super().__init__(parent)
        self._theme_id = current_theme_id()
        self.project = project
        self.selected_kind = ""
        self.selected_id = ""
        self.mode = self.MODE_SELECT
        self._camera_initialized = False
        self._display_entities = []
        self._display_scale = 1.0
        self._display_size = 1.0
        self._preview_radius = 1.0
        self._preview_actor = None
        self._preview_mesh = None
        self._hover_event_position = None
        self._hover_update_scheduled = False
        self._is_shut_down = False
        self._hover_observer_id = None
        self._press_observer_id = None
        self._release_observer_id = None
        self._drag_sensor_id = ""
        self._drag_origin_event = None
        self._drag_last_location = None
        self._drag_moved = False
        self._drag_interactor_style = None
        self._drag_style_was_enabled = False
        self._base_status = ""
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(25)
        self._hover_timer.timeout.connect(self._update_surface_preview)
        self._initial_render_timer = QTimer(self)
        self._initial_render_timer.setSingleShot(True)
        self._initial_render_timer.timeout.connect(self._render_scene)
        self._build_ui()
        self.set_project(project)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toolbar = QFrame()
        toolbar.setObjectName("viewportToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(9, 5, 9, 5)
        toolbar_layout.setSpacing(7)
        title = QLabel("三维模型")
        title.setObjectName("fieldLabel")
        toolbar_layout.addWidget(title)
        self.hint_label = QLabel()
        self.hint_label.setObjectName("viewportHint")
        toolbar_layout.addWidget(self.hint_label)
        toolbar_layout.addStretch(1)
        self.status_label = QLabel()
        self.status_label.setObjectName("viewportStatus")
        toolbar_layout.addWidget(self.status_label)
        for text, camera in (
            ("等轴", "iso"),
            ("正视", "front"),
            ("俯视", "top"),
            ("截面", "section"),
            ("适应", "reset"),
        ):
            button = QPushButton(text)
            button.setObjectName("viewportButton")
            button.clicked.connect(
                lambda _checked=False, value=camera: self.set_camera(value)
            )
            toolbar_layout.addWidget(button)
        layout.addWidget(toolbar)

        if not MODEL_3D_AVAILABLE:
            fallback = QFrame()
            fallback.setObjectName("viewportFallback")
            fallback_layout = QVBoxLayout(fallback)
            fallback_layout.addStretch(1)
            title = QLabel("三维建模视图暂不可用")
            title.setObjectName("emptyTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail = QLabel("仍可在平面视图编辑 x / y / z 精确坐标并保存空间模型。")
            detail.setObjectName("sectionHint")
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback_layout.addWidget(title)
            fallback_layout.addWidget(detail)
            fallback_layout.addStretch(1)
            layout.addWidget(fallback, 1)
            self.status_label.setText("二维兼容模式")
            return

        # Disable PyVistaQt's threaded auto-render timer. Scene updates below
        # are explicit, so the timer only creates shutdown races on macOS.
        self.plotter = QtInteractor(self, auto_update=False)
        self.plotter.set_background(
            self._color("canvas"),
            top=self._color("surface_muted"),
        )
        self.plotter.enable_anti_aliasing("ssaa")
        self.plotter.add_axes(
            color=self._color("text_secondary"),
            line_width=1.2,
            xlabel="X",
            ylabel="Y",
            zlabel="Z",
        )
        self.plotter.enable_point_picking(
            callback=self._picked,
            tolerance=0.035,
            left_clicking=True,
            show_message=False,
            show_point=False,
            pickable_window=False,
        )
        self._hover_picker = vtkCellPicker()
        self._hover_picker.SetTolerance(0.0008)
        self._hover_observer_id = self.plotter.iren.interactor.AddObserver(
            "MouseMoveEvent",
            self._mouse_moved,
        )
        self._press_observer_id = self.plotter.iren.interactor.AddObserver(
            "LeftButtonPressEvent",
            self._left_button_pressed,
            1.0,
        )
        self._release_observer_id = self.plotter.iren.interactor.AddObserver(
            "LeftButtonReleaseEvent",
            self._left_button_released,
            1.0,
        )
        layout.addWidget(self.plotter.interactor, 1)
        self.set_mode(self.MODE_SELECT)

    def set_project(self, project: ProjectDocument):
        if self._is_shut_down:
            return
        self._cancel_sensor_drag()
        self.project = project
        valid_ids = {
            entity.identifier
            for entity in project.nodes + project.elements + project.sensors
        }
        if self.selected_id not in valid_ids:
            self.selected_kind = ""
            self.selected_id = ""
        if self._can_render():
            self._render_scene()
        else:
            capability = PathBeamEditor.capability(project)
            self.status_label.setText(capability.kind)

    def select_entity(self, kind: str, identifier: str):
        if self._is_shut_down:
            return
        if (kind, identifier) == (self.selected_kind, self.selected_id):
            return
        self.selected_kind = kind
        self.selected_id = identifier
        if self._can_render():
            self._render_scene()

    def set_mode(self, mode: str):
        if self._is_shut_down:
            return
        if mode not in {
            self.MODE_SELECT,
            self.MODE_ADD_SURFACE_SENSOR,
            self.MODE_MOVE_SURFACE_SENSOR,
        }:
            mode = self.MODE_SELECT
        if mode != self.mode:
            self._cancel_sensor_drag()
        self.mode = mode
        adding_sensor = mode == self.MODE_ADD_SURFACE_SENSOR
        moving_sensor = mode == self.MODE_MOVE_SURFACE_SENSOR
        if adding_sensor:
            hint = "单击真实梁表面连续布点 · 自动识别梁段/位置/环向角 · Esc 退出"
        elif moving_sensor:
            hint = "按住测点贴片拖动 · 梁长与截面环向同时吸附 · 松开提交 · Esc 退出"
        else:
            hint = "单击选择 · 拖拽旋转 · 贴片长边与双向箭头均表示应变测量轴"
        self.hint_label.setText(hint)
        if self._can_render():
            cursor = (
                Qt.CursorShape.CrossCursor
                if adding_sensor
                else Qt.CursorShape.OpenHandCursor
                if moving_sensor
                else Qt.CursorShape.ArrowCursor
            )
            self.plotter.interactor.setCursor(cursor)
            if not adding_sensor and not moving_sensor:
                self._hide_surface_preview(render=False)
            self._render_scene()

    def _can_render(self):
        return (
            MODEL_3D_AVAILABLE
            and not self._is_shut_down
            and hasattr(self, "plotter")
            and interactor_is_active(self.plotter)
        )

    def _color(self, role):
        return resolve_theme(self._theme_id).color(role)

    def apply_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        if self._can_render():
            self.plotter.set_background(
                self._color("canvas"),
                top=self._color("surface_muted"),
            )
            self._render_scene()

    def _scene_scale(self):
        coordinates = np.asarray(PathBeamEditor.sample_project(self.project), dtype=float)
        extent = float(np.linalg.norm(np.ptp(coordinates, axis=0)))
        extent = max(extent, PathBeamEditor.total_length(self.project) * 0.25, 1.0e-3)
        section = self.project.sections[0] if self.project.sections else None
        if section is None:
            return extent, None, 1.0, extent * 0.018, extent * 0.004
        physical_size = section_max_dimension(section)
        display_scale = max(1.0, extent * 0.028 / physical_size)
        display_size = physical_size * display_scale
        marker_radius = max(display_size * 0.12, extent * 0.004)
        return extent, section, display_scale, display_size, marker_radius

    def _sensor_display_frames(self, section, display_scale: float, display_size: float):
        frames = []
        for sensor in self.project.sensors:
            orientation = PathBeamEditor.sensor_orientation(self.project, sensor)
            centerline = np.asarray(orientation.centerline_position, dtype=float)
            placement_direction = np.asarray(orientation.surface_radial, dtype=float)
            surface_normal = np.asarray(orientation.surface_normal, dtype=float)
            direction = np.asarray(orientation.measurement_direction, dtype=float)
            boundary_offset = (
                display_size * 0.5
                if section is None
                else section_outer_radius(
                    section,
                    sensor.attachment.surface_angle_degrees,
                )
                * display_scale
            )
            point = (
                centerline
                + placement_direction * boundary_offset
                + surface_normal * display_size * 0.018
            )
            frames.append((sensor, centerline, point, surface_normal, direction))
        return frames

    def _render_scene(self):
        if not self._can_render():
            return
        camera = self.plotter.camera_position if self._camera_initialized else None
        self.plotter.clear()
        self.plotter.add_axes(color=self._color("text_secondary"), line_width=1.2)
        extent, section, display_scale, display_size, marker_radius = self._scene_scale()
        self._display_scale = display_scale
        self._display_size = display_size
        self._preview_radius = max(marker_radius * 1.1, display_size * 0.075)
        self._preview_actor = None
        self._preview_mesh = None
        self._display_entities = []

        for index, element in enumerate(PathBeamEditor.ordered_elements(self.project)):
            points = np.asarray(PathBeamEditor.sample_element(self.project, element), dtype=float)
            selected = element.identifier == self.selected_id
            if section is None:
                centerline = pv.lines_from_points(points, close=False)
                mesh = centerline.tube(radius=display_size * 0.5, n_sides=20)
            else:
                local_coordinates = np.linspace(0.0, 1.0, len(points))
                frames = PathBeamEditor.section_frames(
                    self.project,
                    element,
                    local_coordinates,
                )
                normals = np.asarray([frame[1] for frame in frames], dtype=float)
                binormals = np.asarray([frame[2] for frame in frames], dtype=float)
                mesh_points, mesh_faces = sweep_section_mesh(
                    points,
                    normals,
                    binormals,
                    section,
                    display_scale=display_scale,
                    resolution=36,
                )
                mesh = pv.PolyData(mesh_points, faces=mesh_faces)
            self.plotter.add_mesh(
                mesh,
                color=self._color("sensor") if selected else self._color("beam"),
                smooth_shading=section is None or section.shape in {"circle", "circular_tube"},
                specular=0.18,
                pickable=True,
                name=f"model-element-{element.identifier}",
                render=False,
                reset_camera=False,
            )
            midpoint = np.asarray(
                PathBeamEditor.point_on_element(self.project, element, 0.5),
                dtype=float,
            )
            self._display_entities.append(
                ("element", element.identifier, midpoint, display_size * 1.4)
            )

        node_points = np.asarray([node.coordinates for node in self.project.nodes], dtype=float)
        node_glyph = pv.PolyData(node_points).glyph(
            geom=pv.Sphere(
                radius=marker_radius * 1.25,
                theta_resolution=18,
                phi_resolution=14,
            ),
            scale=False,
            orient=False,
        )
        self.plotter.add_mesh(
            node_glyph,
            color=self._color("surface"),
            smooth_shading=True,
            pickable=True,
            name="model-nodes",
            render=False,
            reset_camera=False,
        )
        for node in self.project.nodes:
            selected = node.identifier == self.selected_id
            if selected:
                self.plotter.add_mesh(
                    pv.Sphere(
                        radius=marker_radius * 1.7,
                        center=node.coordinates,
                        theta_resolution=20,
                        phi_resolution=16,
                    ),
                    color=self._color("sensor"),
                    smooth_shading=True,
                    pickable=True,
                    name="selected-node",
                    render=False,
                    reset_camera=False,
                )
            self._display_entities.append(
                (
                    "node",
                    node.identifier,
                    np.asarray(node.coordinates, dtype=float),
                    marker_radius * 2.5,
                )
            )

        sensor_frames = self._sensor_display_frames(
            section,
            display_scale,
            display_size,
        )
        for sensor, centerline, point, surface_normal, direction in sensor_frames:
            half_length = max(display_size * 0.34, extent * 0.008)
            half_width = max(display_size * 0.13, extent * 0.0035)
            corners, patch_faces, measurement_axis, lateral = oriented_surface_patch_glyph(
                point,
                direction,
                surface_normal,
                half_length * 2.0,
                half_width * 2.0,
            )
            patch = pv.PolyData(corners, faces=patch_faces)
            selected = sensor.identifier == self.selected_id
            self.plotter.add_mesh(
                patch,
                color=(
                    self._color("sensor_hover")
                    if selected
                    else self._color("sensor")
                ),
                edge_color=self._color("sensor_dark"),
                line_width=2.0 if selected else 1.2,
                show_edges=True,
                lighting=True,
                pickable=True,
                name=f"model-sensor-{sensor.identifier}",
                render=False,
                reset_camera=False,
            )
            self.plotter.add_mesh(
                pv.Line(centerline, point),
                color=self._color("sensor_soft"),
                line_width=1.2,
                pickable=False,
                name=f"sensor-radial-{sensor.identifier}",
                render=False,
                reset_camera=False,
            )
            arrow_length = max(
                display_size * (1.75 if selected else 1.5),
                extent * 0.038,
            )
            axis_center = (
                point
                + surface_normal * display_size * 0.035
            )
            axis_points, axis_faces, axis_lines = bidirectional_axis_glyph(
                axis_center,
                measurement_axis,
                lateral,
                arrow_length,
            )
            axis_mesh = pv.PolyData(axis_points, faces=axis_faces)
            axis_mesh.lines = axis_lines
            self.plotter.add_mesh(
                axis_mesh,
                color=self._color("primary_pressed") if selected else self._color("primary"),
                line_width=3.2 if selected else 2.6,
                pickable=False,
                name=f"sensor-axis-{sensor.identifier}",
                render=False,
                reset_camera=False,
            )
            if selected:
                self.plotter.add_point_labels(
                    np.asarray((point + surface_normal * display_size * 0.55,)),
                    (
                        f"{sensor.label} | pos {sensor.attachment.surface_angle_degrees:.1f} deg"
                        f" | axis {sensor.attachment.orientation_angle_degrees:.1f} deg",
                    ),
                    font_size=11,
                    text_color=self._color("text"),
                    show_points=False,
                    name="selected-sensor-label",
                    shape_color=self._color("surface"),
                    shape="rounded_rect",
                    fill_shape=True,
                    margin=6,
                    shape_opacity=0.92,
                    pickable=False,
                    always_visible=True,
                    render=False,
                    reset_camera=False,
                )
            self._display_entities.append(
                ("sensor", sensor.identifier, point, max(display_size, marker_radius * 3.0))
            )

        capability = PathBeamEditor.capability(self.project)
        status_parts = [capability.kind, f"{len(self.project.sensors)} 测点"]
        if section is not None:
            status_parts.append(f"{section_shape_label(section.shape)}截面")
            if display_scale > 1.0001:
                status_parts.append(f"截面 ×{display_scale:.3g}")
        selected_sensor = next(
            (
                sensor
                for sensor in self.project.sensors
                if sensor.identifier == self.selected_id
            ),
            None,
        )
        if selected_sensor is not None:
            status_parts.append(
                f"θ {selected_sensor.attachment.surface_angle_degrees:.1f}°"
                f" / 轴 α {selected_sensor.attachment.orientation_angle_degrees:.1f}°"
            )
        if self.mode == self.MODE_ADD_SURFACE_SENSOR:
            status_parts.append("连续布点中")
        elif self.mode == self.MODE_MOVE_SURFACE_SENSOR:
            status_parts.append("测点拖动模式")
        self._base_status = " · ".join(status_parts)
        self.status_label.setText(self._base_status)
        if camera is not None:
            self.plotter.camera_position = camera
        else:
            self.plotter.view_isometric(render=False)
            self.plotter.reset_camera(render=False)
            self.plotter.camera.zoom(1.2)
            self._camera_initialized = True
        render_interactor_now(self.plotter)

    def _picked(self, point):
        if point is None or self._is_shut_down:
            return
        picked = np.asarray(point, dtype=float)
        if self.mode == self.MODE_ADD_SURFACE_SENSOR:
            try:
                location = PathBeamEditor.surface_location_from_point(
                    self.project,
                    picked,
                    display_scale=self._display_scale,
                )
            except (KeyError, ValueError) as exc:
                self.error_raised.emit(str(exc))
                return
            self.surface_sensor_requested.emit(location)
            return
        if self.mode == self.MODE_MOVE_SURFACE_SENSOR:
            return

        candidate = self._entity_near_point(picked)
        if candidate is not None:
            kind, identifier = candidate
        else:
            try:
                _index, element, _xi, _distance = PathBeamEditor.nearest_element(
                    self.project,
                    picked,
                )
            except (KeyError, ValueError) as exc:
                self.error_raised.emit(str(exc))
                return
            kind, identifier = "element", element.identifier
        self.selection_changed.emit(kind, identifier)

    def _entity_near_point(self, point, *, kind_filter=None):
        candidates = []
        for kind, identifier, position, radius in self._display_entities:
            if kind == "element" or (kind_filter is not None and kind != kind_filter):
                continue
            distance = float(np.linalg.norm(point - position))
            distance_ratio = distance / max(radius, 1.0e-12)
            if distance_ratio <= 1.8:
                selected_priority = 0 if identifier == self.selected_id else 1
                kind_priority = {"sensor": 0, "node": 1}[kind]
                candidates.append(
                    (distance_ratio, selected_priority, kind_priority, kind, identifier)
                )
        if not candidates:
            return None
        _distance, _selected, _kind_priority, kind, identifier = min(candidates)
        return kind, identifier

    def _surface_location_at_event(self, event_position):
        if event_position is None or not self._can_render():
            return None
        x, y = event_position
        picked = self._hover_picker.Pick(x, y, 0.0, self.plotter.renderer)
        if not picked or self._hover_picker.GetCellId() < 0:
            return None
        return PathBeamEditor.surface_location_from_point(
            self.project,
            self._hover_picker.GetPickPosition(),
            display_scale=self._display_scale,
        )

    def _left_button_pressed(self, interactor, _event_name):
        if not self._can_render() or self.mode != self.MODE_MOVE_SURFACE_SENSOR:
            return
        event_position = tuple(interactor.GetEventPosition())
        picked = self._hover_picker.Pick(
            event_position[0],
            event_position[1],
            0.0,
            self.plotter.renderer,
        )
        if not picked or self._hover_picker.GetCellId() < 0:
            return
        candidate = self._entity_near_point(
            np.asarray(self._hover_picker.GetPickPosition(), dtype=float),
            kind_filter="sensor",
        )
        if candidate is None:
            return
        _kind, sensor_id = candidate
        self._drag_sensor_id = sensor_id
        self._drag_origin_event = event_position
        self._drag_last_location = None
        self._drag_moved = False
        self.selection_changed.emit("sensor", sensor_id)
        self._drag_interactor_style = interactor.GetInteractorStyle()
        if self._drag_interactor_style is not None:
            self._drag_style_was_enabled = bool(
                self._drag_interactor_style.GetEnabled()
            )
            self._drag_interactor_style.SetEnabled(False)
        self.plotter.interactor.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _left_button_released(self, interactor, _event_name):
        if not self._can_render() or not self._drag_sensor_id:
            return
        sensor_id = self._drag_sensor_id
        location = self._drag_last_location
        if self._drag_moved:
            try:
                location = self._surface_location_at_event(
                    tuple(interactor.GetEventPosition())
                ) or location
            except (KeyError, ValueError):
                pass
        moved = self._drag_moved and location is not None
        self._cancel_sensor_drag(render=False)
        self._hide_surface_preview()
        if moved:
            self.surface_sensor_move_requested.emit(sensor_id, location)

    def _mouse_moved(self, interactor, _event_name):
        if not self._can_render():
            return
        if self._drag_sensor_id:
            position = tuple(interactor.GetEventPosition())
            if not self._drag_moved:
                dx = position[0] - self._drag_origin_event[0]
                dy = position[1] - self._drag_origin_event[1]
                if dx * dx + dy * dy < 16:
                    return
                self._drag_moved = True
            self._hover_event_position = position
        elif self.mode == self.MODE_ADD_SURFACE_SENSOR:
            self._hover_event_position = tuple(interactor.GetEventPosition())
        else:
            return
        if self._hover_update_scheduled:
            return
        self._hover_update_scheduled = True
        self._hover_timer.start()

    def _update_surface_preview(self):
        self._hover_update_scheduled = False
        if not self._can_render():
            return
        if (
            (
                self.mode != self.MODE_ADD_SURFACE_SENSOR
                and not (
                    self.mode == self.MODE_MOVE_SURFACE_SENSOR
                    and self._drag_sensor_id
                    and self._drag_moved
                )
            )
            or self._hover_event_position is None
        ):
            self._hide_surface_preview()
            return
        try:
            location = self._surface_location_at_event(self._hover_event_position)
        except (KeyError, ValueError):
            self._hide_surface_preview()
            return
        if location is None:
            self._hide_surface_preview()
            return
        if self._drag_sensor_id:
            self._drag_last_location = location
        self._show_surface_preview(location)

    def _show_surface_preview(self, location):
        if not self._can_render():
            return
        centerline = np.asarray(location.centerline_position, dtype=float)
        surface = np.asarray(location.global_position, dtype=float)
        normal = np.asarray(location.surface_normal, dtype=float)
        display_point = (
            centerline
            + (surface - centerline) * self._display_scale
            + normal * self._display_size * 0.028
        )
        direction = np.asarray(location.tangent, dtype=float)
        if self._drag_sensor_id:
            sensor = next(
                (
                    item
                    for item in self.project.sensors
                    if item.identifier == self._drag_sensor_id
                ),
                None,
            )
            if sensor is not None:
                angle = np.deg2rad(sensor.attachment.orientation_angle_degrees)
                direction = (
                    np.cos(angle) * np.asarray(location.tangent, dtype=float)
                    + np.sin(angle)
                    * np.asarray(location.surface_circumferential, dtype=float)
                )
        direction /= max(float(np.linalg.norm(direction)), 1.0e-12)
        preview_length = max(self._display_size * 0.7, self._preview_radius * 3.2)
        preview_width = max(self._display_size * 0.26, self._preview_radius * 1.25)
        corners, patch_faces, _axis, _lateral = oriented_surface_patch_glyph(
            display_point,
            direction,
            normal,
            preview_length,
            preview_width,
        )
        if self._preview_actor is None:
            self._preview_mesh = pv.PolyData(corners, faces=patch_faces)
            self._preview_actor = self.plotter.add_mesh(
                self._preview_mesh,
                color=self._color("warning"),
                emissive=True,
                show_edges=True,
                edge_color=self._color("primary_pressed"),
                line_width=1.5,
                opacity=0.92,
                pickable=False,
                name="surface-pick-preview",
                render=False,
                reset_camera=False,
            )
        else:
            self._preview_mesh.points = corners
            self._preview_mesh.faces = patch_faces
        self._preview_actor.SetVisibility(True)
        action = "拖动至" if self._drag_sensor_id else "预览"
        self.status_label.setText(
            f"{self._base_status} · {action} s {location.path_distance:.5g} m"
            f" / θ {location.surface_angle_degrees:.1f}°"
        )
        render_interactor_now(self.plotter)

    def _cancel_sensor_drag(self, *, render=False):
        if self._drag_interactor_style is not None and self._drag_style_was_enabled:
            self._drag_interactor_style.SetEnabled(True)
        self._drag_interactor_style = None
        self._drag_style_was_enabled = False
        self._drag_sensor_id = ""
        self._drag_origin_event = None
        self._drag_last_location = None
        self._drag_moved = False
        if self._can_render():
            cursor = (
                Qt.CursorShape.OpenHandCursor
                if self.mode == self.MODE_MOVE_SURFACE_SENSOR
                else Qt.CursorShape.CrossCursor
                if self.mode == self.MODE_ADD_SURFACE_SENSOR
                else Qt.CursorShape.ArrowCursor
            )
            self.plotter.interactor.setCursor(cursor)
            if render:
                render_interactor_now(self.plotter)

    def _hide_surface_preview(self, *, render=True):
        if self._preview_actor is not None:
            self._preview_actor.SetVisibility(False)
        if self._base_status:
            self.status_label.setText(self._base_status)
        if render and self._can_render():
            render_interactor_now(self.plotter)

    def set_camera(self, camera: str):
        if not self._can_render():
            return
        if camera == "front":
            self.plotter.view_xy(render=False)
        elif camera == "top":
            self.plotter.view_xz(render=False)
        elif camera == "iso":
            self.plotter.view_isometric(render=False)
        elif camera == "section":
            self.plotter.view_yz(render=False)
        self.plotter.reset_camera(render=False)
        render_interactor_now(self.plotter)

    def showEvent(self, event):
        super().showEvent(event)
        if self._can_render():
            self._initial_render_timer.start(0)

    def shutdown(self):
        if self._is_shut_down:
            return
        self._is_shut_down = True
        self._hover_timer.stop()
        self._initial_render_timer.stop()
        self._hover_update_scheduled = False
        self._hover_event_position = None

        if MODEL_3D_AVAILABLE and hasattr(self, "plotter"):
            vtk_interactor = getattr(getattr(self.plotter, "iren", None), "interactor", None)
            if vtk_interactor is not None:
                for attribute in (
                    "_hover_observer_id",
                    "_press_observer_id",
                    "_release_observer_id",
                ):
                    observer_id = getattr(self, attribute)
                    if observer_id is not None:
                        try:
                            vtk_interactor.RemoveObserver(observer_id)
                        except (AttributeError, RuntimeError):
                            pass
                        setattr(self, attribute, None)
            self._drag_interactor_style = None
            self._drag_sensor_id = ""
            shutdown_interactor(self.plotter)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
