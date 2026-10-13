from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from visualization_data import build_surface_blocks
from ifem.modeling.section_geometry import section_shape_label
from ifem.ui.vtk_lifecycle import (
    interactor_is_active,
    render_interactor_now,
    shutdown_interactor,
)
from ifem.ui.theme import current_theme_id, resolve_theme
from ifem.ui.studio import ElidingLabel


os.environ["QT_API"] = "pyside6"

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor

    _qt_platform = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    PYVISTA_AVAILABLE = _qt_platform not in {"offscreen", "minimal"}
    PYVISTA_IMPORT_ERROR = (
        None
        if PYVISTA_AVAILABLE
        else RuntimeError("当前 Qt 平台不支持嵌入式 VTK 渲染。")
    )
except Exception as exc:  # pragma: no cover - depends on optional native packages
    pv = None
    QtInteractor = None
    PYVISTA_AVAILABLE = False
    PYVISTA_IMPORT_ERROR = exc


class Structure3DView(QWidget):
    backend_available = PYVISTA_AVAILABLE
    view_changed = Signal(str)
    result_picked = Signal(str, int)

    _SAMPLE_ID = "ifem_result_sample_index"
    _NODE_ID = "ifem_result_node_index"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_id = current_theme_id()
        self.model_data = None
        self.frame = None
        self.mode = "shape"
        self.thickness_scale = 1.0
        self._surface_meshes = []
        self._surface_actors = []
        self._surface_blocks = []
        self._node_mesh = None
        self._node_actor = None
        self._result_selection = None
        self._probe_position = None
        self._selection_actor_names = []
        self._pick_press_position = None
        self._render_key = None
        self._camera_initialized = False
        self._is_shut_down = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toolbar = QFrame()
        toolbar.setObjectName("viewportToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(9, 5, 9, 5)
        toolbar_layout.setSpacing(9)
        title = QLabel("交互三维")
        title.setObjectName("fieldLabel")
        title.setToolTip("支持鼠标旋转、缩放和平移；相机视角不会在结果刷新时被重置。")
        title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        toolbar_layout.addWidget(title)

        self.interaction_hint = ElidingLabel("Ctrl+单击选取 · 测点布置请在建模视图查看")
        self.interaction_hint.setObjectName("viewportHint")
        self.interaction_hint.setToolTip(
            "Ctrl+左键单击选取当前结果的节点或截面采样；普通左键拖拽旋转。\n"
            "仅显示结构与结果场；测点布置请在建模视图查看。"
        )
        self.interaction_hint.setMinimumWidth(0)
        self.interaction_hint.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        toolbar_layout.addWidget(self.interaction_hint, 1)

        option_group = QFrame()
        option_group.setObjectName("viewportOptions")
        option_layout = QHBoxLayout(option_group)
        option_layout.setContentsMargins(4, 0, 4, 0)
        option_layout.setSpacing(12)

        self.show_original_check = QCheckBox("原始模型")
        self.show_original_check.setMinimumWidth(92)
        self.show_original_check.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        self.show_original_check.setChecked(True)
        self.show_original_check.toggled.connect(self._rebuild_scene)
        option_layout.addWidget(self.show_original_check)
        toolbar_layout.addWidget(option_group)
        toolbar_layout.addStretch(1)

        self.status_label = QLabel("等待结构结果")
        self.status_label.setObjectName("viewportStatus")
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        toolbar_layout.addWidget(self.status_label)
        for text, camera in [
            ("等轴", "iso"),
            ("正视", "front"),
            ("俯视", "top"),
            ("截面", "section"),
            ("适应", "reset"),
        ]:
            button = QPushButton(text)
            button.setObjectName("viewportButton")
            button.setMinimumWidth(52)
            button.clicked.connect(lambda _checked=False, value=camera: self.set_camera(value))
            toolbar_layout.addWidget(button)
        layout.addWidget(toolbar)

        if not PYVISTA_AVAILABLE:
            fallback = QFrame()
            fallback.setObjectName("viewportFallback")
            fallback_layout = QVBoxLayout(fallback)
            fallback_layout.addStretch(1)
            fallback_title = QLabel("三维可视化后端未安装")
            fallback_title.setObjectName("emptyTitle")
            fallback_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback_detail = QLabel(
                "安装 pyvista、vtk 与 pyvistaqt 后启用；二维分析功能不受影响。"
            )
            fallback_detail.setObjectName("sectionHint")
            fallback_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback_detail.setWordWrap(True)
            fallback_layout.addWidget(fallback_title)
            fallback_layout.addWidget(fallback_detail)
            fallback_layout.addStretch(1)
            layout.addWidget(fallback, 1)
            return

        # The PyVistaQt default starts a 5 Hz render timer. On macOS that timer
        # queues threaded renders which can outlive the native Qt window.
        self.plotter = QtInteractor(self, auto_update=False)
        self.plotter.interactor.setToolTip(
            "左键拖拽旋转 · 滚轮缩放 · 右键拖拽平移 · Ctrl+左键单击选取结果"
        )
        self.plotter.interactor.installEventFilter(self)
        self.plotter.set_background(
            self._color("viewport_end"),
            top=self._color("viewport_start"),
        )
        self.plotter.enable_anti_aliasing("ssaa")
        self.plotter.add_axes(
            color=self._color("viewport_text"),
            line_width=1.2,
            xlabel="X",
            ylabel="Y",
            zlabel="Z",
        )
        layout.addWidget(self.plotter.interactor, 1)

    def clear_frame(self):
        self.model_data = None
        self.frame = None
        self._surface_meshes = []
        self._surface_actors = []
        self._surface_blocks = []
        self._node_mesh = None
        self._node_actor = None
        self._result_selection = None
        self._probe_position = None
        self._selection_actor_names = []
        self._pick_press_position = None
        self._render_key = None
        self._camera_initialized = False
        self.status_label.setText("等待结构结果")
        if self._can_render():
            self.plotter.clear()
            self.plotter.add_axes(color=self._color("viewport_text"), line_width=1.2)
            render_interactor_now(self.plotter)

    def set_frame(self, model_data, frame, *, mode="shape", thickness_scale=1.0):
        if self._is_shut_down:
            return
        if self.frame is None or self.frame.sequence != frame.sequence:
            self._result_selection = None
            self._probe_position = None
        self.model_data = model_data
        self.frame = frame
        self.mode = mode
        self.thickness_scale = float(thickness_scale)
        if not self._can_render():
            return
        self._render_scene()

    def set_result_selection(self, kind=None, index=None):
        """Highlight an exact result identity; never infer identities from coordinates."""
        if self._is_shut_down:
            return
        self._probe_position = None
        self._result_selection = None
        if self.frame is not None and kind in {"node", "sample"}:
            count = (
                len(self.frame.deformed_nodes)
                if kind == "node"
                else len(self.frame.section.x_reference)
            )
            if isinstance(index, (int, np.integer)) and not isinstance(index, (bool, np.bool_)):
                if 0 <= index < count:
                    self._result_selection = (kind, int(index))
        self._refresh_result_highlight()

    def set_probe_position(self, position=None):
        """Show an interpolated/query point without pretending it is a mesh sample."""
        if self._is_shut_down:
            return
        self._result_selection = None
        self._probe_position = None
        if self.frame is not None and position is not None:
            try:
                point = np.asarray(position, dtype=float)
                if point.shape == (3,) and np.all(np.isfinite(point)):
                    self._probe_position = tuple(float(value) for value in point)
            except (TypeError, ValueError):
                pass
        self._refresh_result_highlight()

    def eventFilter(self, watched, event):
        """Keep VTK's ordinary navigation; consume only an explicit pick gesture."""
        if hasattr(self, "plotter") and watched is self.plotter.interactor:
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonPress:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and self._can_render()
                    and self.frame is not None
                ):
                    self._pick_press_position = event.position()
                    return True
            elif event_type == QEvent.Type.MouseMove and self._pick_press_position is not None:
                return True
            elif event_type == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton and self._pick_press_position is not None:
                    origin = self._pick_press_position
                    self._pick_press_position = None
                    if (event.position() - origin).manhattanLength() <= 4:
                        self._pick_at_position(event.position())
                    return True
            elif event_type in {QEvent.Type.Hide, QEvent.Type.FocusOut}:
                self._pick_press_position = None
        return super().eventFilter(watched, event)

    def _pick_at_position(self, position):
        if not self._can_render() or self.frame is None:
            return
        # Match the bundled QVTKRenderWindowInteractor's physical-pixel mapping.
        widget = self.plotter.interactor
        scale = widget._getPixelRatio()
        x = int(round(position.x() * scale))
        y = int(round((widget.height() - position.y() - 1) * scale))
        from vtkmodules.vtkRenderingCore import vtkCellPicker, vtkPointPicker

        if self._node_actor is not None:
            picker = vtkPointPicker()
            picker.SetTolerance(0.006)
            picker.PickFromListOn()
            picker.AddPickList(self._node_actor)
            if picker.Pick(x, y, 0, self.plotter.renderer):
                if self._accept_result_pick(picker):
                    return
        picker = vtkCellPicker()
        picker.SetTolerance(0.006)
        picker.PickFromListOn()
        for actor in self._surface_actors:
            picker.AddPickList(actor)
        if picker.Pick(x, y, 0, self.plotter.renderer):
            self._accept_result_pick(picker)

    def _accept_result_pick(self, picker):
        if not self._can_render() or self.frame is None:
            return False
        actor = picker.GetActor()
        if actor is None:
            return False
        if actor is self._node_actor or actor == self._node_actor:
            kind, key = "node", self._NODE_ID
        elif any(actor is item or actor == item for item in self._surface_actors):
            kind, key = "sample", self._SAMPLE_ID
        else:
            return False
        data = picker.GetDataSet()
        if data is None:
            return False
        data = pv.wrap(data)
        if key not in data.point_data:
            return False
        point_id = int(picker.GetPointId())
        if not 0 <= point_id < data.n_points:
            cell_id = int(picker.GetCellId()) if hasattr(picker, "GetCellId") else -1
            if not 0 <= cell_id < data.n_cells:
                return False
            candidates = np.asarray(data.get_cell(cell_id).point_ids, dtype=int)
            if not len(candidates):
                return False
            picked = np.asarray(picker.GetPickPosition(), dtype=float)
            point_id = int(candidates[np.argmin(np.linalg.norm(data.points[candidates] - picked, axis=1))])
        index = int(data.point_data[key][point_id])
        self.set_result_selection(kind, index)
        if self._result_selection != (kind, index):
            return False
        self.result_picked.emit(kind, index)
        return True

    def _rebuild_scene(self, *_args):
        self._render_key = None
        if self.model_data is not None and self.frame is not None and self._can_render():
            self._render_scene()

    def _can_render(self):
        return (
            PYVISTA_AVAILABLE
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
                self._color("viewport_end"),
                top=self._color("viewport_start"),
            )
            if self.model_data is not None and self.frame is not None:
                self._render_key = None
                self._render_scene()
            else:
                self.plotter.clear()
                self.plotter.add_axes(
                    color=self._color("viewport_text"),
                    line_width=1.2,
                )
                render_interactor_now(self.plotter)

    def _field_definition(self, block):
        if self.mode == "strain":
            return block.axial_strain * 1.0e6, "Axial strain (microstrain)", "coolwarm", True
        if self.mode == "stress" and block.axial_stress is not None:
            return block.axial_stress / 1.0e6, "Axial stress (MPa)", "coolwarm", True
        return block.displacement_magnitude, "Displacement magnitude", "viridis", False

    def _symmetric_range(self, blocks, mode):
        if mode == "strain":
            limit = self.frame.section.strain_reference_limit * 1.0e6
        elif mode == "stress" and all(block.axial_stress is not None for block in blocks):
            limit = self.frame.section.stress_reference_limit / 1.0e6
        else:
            return None
        return (-max(limit, 1.0e-12), max(limit, 1.0e-12))

    @staticmethod
    def _structured_grid(points, field_name, field_values):
        grid = pv.StructuredGrid(
            points[..., 0],
            points[..., 1],
            points[..., 2],
        )
        grid.point_data[field_name] = np.asarray(field_values).ravel(order="F")
        grid.set_active_scalars(field_name)
        return grid

    def _block_sample_indices(self, block):
        # SurfaceBlock's first axis is the original section sample axis for both
        # swept real profiles and the rectangular volume grid.  Do not collapse
        # coincident raw element boundaries: their field values can differ.
        if block.element_index is None:
            indices = np.arange(len(self.frame.section.x_reference), dtype=int)
        else:
            indices = np.flatnonzero(self.frame.section.element_index == block.element_index)
        if len(indices) != block.points.shape[0]:
            raise ValueError("结果曲面采样索引与网格点不一致。")
        return indices

    def _refresh_result_highlight(self, *, render=True):
        if not self._can_render():
            return
        for name in self._selection_actor_names:
            self.plotter.remove_actor(name, render=False, reset_camera=False)
        self._selection_actor_names = []
        point = self._probe_position
        if self.frame is not None and self._result_selection is not None:
            kind, index = self._result_selection
            if kind == "node" and index < len(self.frame.deformed_nodes):
                point = self.frame.deformed_nodes[index]
            elif kind == "sample" and index < len(self.frame.section.x_reference):
                point = self.frame.section.centerline_deformed[index]
                for block_index, block in enumerate(self._surface_blocks):
                    matches = np.flatnonzero(self._block_sample_indices(block) == index)
                    if not len(matches):
                        continue
                    station = block.points[int(matches[0])]
                    if station.ndim == 3:
                        # Perimeter of a (through-thickness, width, xyz) station.
                        station = np.concatenate((
                            station[:, 0], station[-1, 1:],
                            station[-2::-1, -1], station[0, -2::-1],
                        ))
                        station = np.vstack((station, station[0]))
                    line = pv.PolyData(station)
                    line.lines = np.hstack(([len(station)], np.arange(len(station))))
                    name = f"result-selection-station-{block_index}"
                    self.plotter.add_mesh(
                        line, color=self._color("viewport_text"), line_width=3.5,
                        name=name, pickable=False, render=False, reset_camera=False,
                    )
                    self._selection_actor_names.append(name)
        if point is not None:
            name = "result-selection-point"
            self.plotter.add_mesh(
                pv.PolyData(np.asarray(point, dtype=float).reshape(1, 3)),
                color=self._color("viewport_text"), point_size=16,
                render_points_as_spheres=True, name=name, pickable=False,
                render=False, reset_camera=False,
            )
            self._selection_actor_names.append(name)
        if render:
            render_interactor_now(self.plotter)

    def _render_scene(self):
        if not self._can_render():
            return
        blocks = build_surface_blocks(self.model_data, self.frame, self.thickness_scale)
        self._surface_blocks = blocks
        field_values, field_name, cmap, symmetric = self._field_definition(blocks[0])
        render_key = (
            self.mode,
            self.frame.section.representation,
            tuple((block.element_index, block.points.shape) for block in blocks),
            len(self.frame.deformed_nodes),
            self.show_original_check.isChecked(),
        )

        if render_key != self._render_key:
            self._build_scene(blocks, field_name, cmap, symmetric)
            self._render_key = render_key
        else:
            for mesh, block in zip(self._surface_meshes, blocks):
                values, _name, _cmap, _symmetric = self._field_definition(block)
                mesh.points = block.points.reshape(-1, 3, order="F")
                mesh.point_data[field_name] = np.asarray(values).ravel(order="F")
                self._attach_sample_indices(mesh, block)
            scalar_range = self._symmetric_range(blocks, self.mode)
            if scalar_range is not None:
                for actor in self._surface_actors:
                    actor.mapper.scalar_range = scalar_range
            if self._node_mesh is not None:
                self._node_mesh.points = self.frame.deformed_nodes
        self._refresh_result_highlight(render=False)
        render_interactor_now(self.plotter)

        representation = (
            "原始单元场" if self.frame.section.representation == "raw" else "节点平均连续化"
        )
        if self.mode == "stress" and self.frame.section.stress is None:
            status = "未设置 E · 当前显示位移幅值"
        else:
            status = f"{representation} · 帧 {self.frame.sequence}"
        scale_name = "截面" if self.model_data.section_parameters else "厚度"
        status += f" · {scale_name}×{self.thickness_scale:.3g}"
        if self.model_data.section_parameters:
            status += f" · {section_shape_label(self.model_data.section_shape)}截面"
        elif self.model_data.section_width is None:
            status += " · 宽度示意"
        self.status_label.setText(status)
        self.view_changed.emit(status)

    def _build_scene(self, blocks, field_name, cmap, symmetric):
        camera_position = self.plotter.camera_position if self._camera_initialized else None
        self.plotter.clear()
        self.plotter.add_axes(color=self._color("viewport_text"), line_width=1.2)
        self._surface_meshes = []
        self._surface_actors = []
        self._node_mesh = None
        self._node_actor = None
        self._selection_actor_names = []
        scalar_range = self._symmetric_range(blocks, self.mode) if symmetric else None

        for block_index, block in enumerate(blocks):
            values, _field_name, _cmap, _symmetric = self._field_definition(block)
            mesh = self._structured_grid(block.points, field_name, values)
            self._attach_sample_indices(mesh, block)
            actor = self.plotter.add_mesh(
                mesh,
                scalars=field_name,
                cmap=cmap,
                clim=scalar_range,
                smooth_shading=True,
                show_edges=False,
                scalar_bar_args={
                    "title": field_name,
                    "color": self._color("viewport_text"),
                    "title_font_size": 12,
                    "label_font_size": 10,
                    "vertical": True,
                    "position_x": 0.86,
                    "position_y": 0.16,
                    "height": 0.66,
                    "width": 0.08,
                },
                show_scalar_bar=block_index == 0,
                name=f"result-block-{block_index}",
                render=False,
                reset_camera=False,
            )
            self._surface_meshes.append(mesh)
            self._surface_actors.append(actor)

        if self.show_original_check.isChecked():
            original = pv.PolyData(self.model_data.node_coordinates)
            original.lines = np.hstack(
                [[len(self.model_data.node_coordinates)], np.arange(len(self.model_data.node_coordinates))]
            )
            self.plotter.add_mesh(
                original,
                color=self._color("node"),
                line_width=2.0,
                opacity=0.75,
                style="wireframe",
                name="reference-centerline",
                pickable=False,
                render=False,
                reset_camera=False,
            )

        deformed_nodes = pv.PolyData(self.frame.deformed_nodes)
        deformed_nodes.point_data[self._NODE_ID] = np.arange(len(self.frame.deformed_nodes))
        self._node_mesh = deformed_nodes
        self._node_actor = self.plotter.add_mesh(
            deformed_nodes,
            color=self._color("viewport_text"),
            point_size=8,
            render_points_as_spheres=True,
            name="deformed-nodes",
            render=False,
            reset_camera=False,
        )
        if camera_position is not None:
            self.plotter.camera_position = camera_position
        else:
            self.plotter.view_xy(render=False)
            self.plotter.enable_parallel_projection()
            self.plotter.reset_camera(render=False)
            self.plotter.camera.zoom(1.3)
            self._camera_initialized = True

    def _attach_sample_indices(self, mesh, block):
        indices = self._block_sample_indices(block)
        sample_shape = (len(indices),) + (1,) * (block.points.ndim - 2)
        mesh.point_data[self._SAMPLE_ID] = np.broadcast_to(
            indices.reshape(sample_shape), block.points.shape[:-1]
        ).ravel(order="F")

    def set_camera(self, camera):
        if not self._can_render() or self.frame is None:
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

    def shutdown(self):
        if self._is_shut_down:
            return
        self._is_shut_down = True
        self._result_selection = None
        self._probe_position = None
        self._pick_press_position = None
        self._selection_actor_names = []
        self._surface_blocks = []
        if PYVISTA_AVAILABLE and hasattr(self, "plotter"):
            self.plotter.interactor.removeEventFilter(self)
            shutdown_interactor(self.plotter)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
