"""Honest, native-model-independent plots of analysis nodes and field records."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import MaxNLocator, NullLocator
from mpl_toolkits.mplot3d import proj3d
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ifem.domain.result_fields import map_result_field
from ifem.ui.studio import ElidingLabel
from ifem.ui.theme import DEFAULT_THEME_ID, resolve_theme
from ifem.visualization.generic_results import build_result_geometry, build_scalar_points


class GenericResultView(QWidget):
    """Plot supplied records only; straight node links are not curved beam geometry."""

    record_selected = Signal(str, str)
    node_selected = Signal(str)
    view_changed = Signal()
    _PROJECTIONS = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2), "3d": (0, 1, 2)}

    def __init__(self, parent=None, *, theme_id=DEFAULT_THEME_ID):
        super().__init__(parent)
        self.setAccessibleName("通用重构结果视图")
        self.result = None
        self._geometry = None
        self._layers = {}
        self._field_errors = {}
        self._selected_record = None
        self._selected_node = None
        self._scalar_layer = None
        self._point_artist = None
        self._selection_artist = None
        self._press = None
        self._stopped = False
        self._updating = False
        self._theme = resolve_theme(theme_id)
        self._camera = (25.0, -55.0)
        self._font = FontProperties(family=["Hiragino Sans GB", "Arial Unicode MS", "DejaVu Sans"], size=9)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setSpacing(6)
        self.field_selector = QComboBox()
        self.component_selector = QComboBox()
        self.projection_selector = QComboBox()
        for column, (label_text, selector, accessible) in enumerate((
            ("显示", self.field_selector, "通用图形结果字段"),
            ("分量", self.component_selector, "通用图形结果分量"),
            ("视角", self.projection_selector, "通用图形结果投影视角"),
        )):
            label = QLabel(label_text)
            label.setBuddy(selector)
            selector.setAccessibleName(accessible)
            selector.setMinimumContentsLength((6, 4, 5)[column])
            selector.setMinimumWidth((70, 100, 80)[column])
            selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.toolbar_layout.addWidget(label)
            self.toolbar_layout.addWidget(selector, (3, 1, 2)[column])
        for key, label in (("xy", "XY 投影"), ("xz", "XZ 投影"), ("yz", "YZ 投影"), ("3d", "三维 XYZ")):
            self.projection_selector.addItem(label, key)
        # The workbench may append its existing 70 px focus button here; the
        # three selectors can shrink without introducing a second toolbar row.
        layout.addLayout(self.toolbar_layout)
        self.description = ElidingLabel()
        self.description.setObjectName("sectionHint")
        self.description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.description)
        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setAccessibleName("分析节点连线与离散结果点图")
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas.setMinimumSize(180, 110)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.canvas, 1)
        self.selection_label = ElidingLabel("选择字段数据行，或单击图中离散点查看原值。")
        self.selection_label.setObjectName("sectionHint")
        self.selection_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.selection_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.selection_label)
        self.axes = None
        self.colorbar = None
        self.field_selector.currentIndexChanged.connect(self._field_changed)
        self.component_selector.currentIndexChanged.connect(self._component_changed)
        self.projection_selector.currentIndexChanged.connect(self._projection_changed)
        self._connections = (
            self.canvas.mpl_connect("button_press_event", self._on_press),
            self.canvas.mpl_connect("button_release_event", self._on_release),
        )
        self.clear()

    @property
    def field_id(self):
        return self.field_selector.currentData()

    @property
    def component(self):
        return self.component_selector.currentData()

    @property
    def projection(self):
        return self.projection_selector.currentData() or "xy"

    @property
    def selected_record(self):
        return self._selected_record

    @property
    def selected_node(self):
        return self._selected_node

    @property
    def geometry(self):
        return self._geometry

    @property
    def scalar_layer(self):
        return self._scalar_layer

    def set_result(self, result):
        if self._stopped:
            return
        first = self.result is None
        previous_field, previous_component = self.field_id, self.component
        self._updating = True
        try:
            self.result = result
            self._selected_record = None
            self._selected_node = None
            self._layers, self._field_errors = {}, {}
            self._geometry = None
            self._geometry_error = ""
            if result is not None and result.state is not None:
                try:
                    self._geometry = build_result_geometry(result.state)
                except (TypeError, ValueError, KeyError) as exc:
                    self._geometry_error = str(exc)
            with QSignalBlocker(self.field_selector):
                self.field_selector.clear()
                self.field_selector.addItem("分析节点形态", None)
                if result is not None:
                    for identifier in result.fields:
                        try:
                            layer = map_result_field(result, identifier)
                            self._layers[identifier] = layer
                            label = layer.label
                        except (TypeError, ValueError, KeyError) as exc:
                            self._field_errors[identifier] = str(exc)
                            label = f"{identifier} · 不可绘制"
                        self.field_selector.addItem(label, identifier)
                index = self.field_selector.findData(previous_field)
                self.field_selector.setCurrentIndex(max(0, index))
            if first and self._geometry is not None:
                with QSignalBlocker(self.projection_selector):
                    key = "3d" if self._geometry.modeling_space == "3d" else "xy"
                    self.projection_selector.setCurrentIndex(self.projection_selector.findData(key))
            self._populate_components(previous_component)
            self.field_selector.setEnabled(result is not None)
            self.projection_selector.setEnabled(result is not None)
            self._redraw()
        finally:
            self._updating = False

    def clear(self):
        self.set_result(None)

    def set_field(self, identifier):
        index = self.field_selector.findData(identifier)
        if index < 0 or self._stopped:
            return False
        self.field_selector.setCurrentIndex(index)
        return True

    def set_component(self, component):
        index = self.component_selector.findData(component)
        if index < 0 or self._stopped:
            return False
        self.component_selector.setCurrentIndex(index)
        return True

    def set_projection(self, projection):
        key = str(projection).lower()
        if key not in self._PROJECTIONS:
            raise ValueError("结果视角必须为 xy、xz、yz 或 3d。")
        if not self._stopped:
            self.projection_selector.setCurrentIndex(self.projection_selector.findData(key))

    def _populate_components(self, preferred=None):
        layer = self._layers.get(self.field_id)
        with QSignalBlocker(self.component_selector):
            self.component_selector.clear()
            if layer is not None:
                for component in layer.components:
                    self.component_selector.addItem(component, component)
                self.component_selector.setCurrentIndex(max(0, self.component_selector.findData(preferred)))
        self.component_selector.setEnabled(layer is not None)

    def _field_changed(self, *_args):
        if self._stopped or self._updating:
            return
        if self.field_id is not None:
            self._selected_node = None
        if self._selected_record is not None:
            old_layer = self._layers.get(self._selected_record[0])
            new_layer = self._layers.get(self.field_id)
            entity_id = self._selected_record[1]
            keep = old_layer is not None and new_layer is not None and old_layer.association == new_layer.association
            self._selected_record = ((self.field_id, entity_id)
                if keep and any(record.entity_id == entity_id for record in new_layer.records) else None)
        self._populate_components(self.component)
        self._redraw()
        self.view_changed.emit()

    def _component_changed(self, *_args):
        if not self._stopped and not self._updating:
            self._redraw()
            self.view_changed.emit()

    def _projection_changed(self, *_args):
        if not self._stopped and not self._updating:
            self._redraw()
            self.view_changed.emit()

    def apply_theme(self, theme_id):
        self._theme = resolve_theme(theme_id)
        if not self._stopped:
            self._redraw()

    def _plot_positions(self, positions, **kwargs):
        coordinates = np.asarray(positions, dtype=float)
        dimensions = self._PROJECTIONS[self.projection]
        return self.axes.plot(*(coordinates[:, dimension] for dimension in dimensions), **kwargs)

    def _scatter(self, positions, **kwargs):
        coordinates = np.asarray(positions, dtype=float)
        dimensions = self._PROJECTIONS[self.projection]
        return self.axes.scatter(*(coordinates[:, dimension] for dimension in dimensions), **kwargs)

    def _redraw(self):
        if self._stopped:
            return
        self.field_selector.setToolTip(self.field_selector.currentText() +
            (f"\n字段 ID：{self.field_id}" if self.field_id is not None else ""))
        self.component_selector.setToolTip(self.component_selector.currentText())
        self.projection_selector.setToolTip(self.projection_selector.currentText())
        if self.axes is not None and self.axes.name == "3d":
            self._camera = (self.axes.elev, self.axes.azim)
        self.figure.clear()
        self.colorbar = self._point_artist = self._selection_artist = None
        self._scalar_layer = None
        color = self._theme.color
        self.figure.set_facecolor(color("canvas"))
        self.axes = self.figure.add_subplot(111, projection="3d" if self.projection == "3d" else None)
        self.axes.set_facecolor(color("canvas"))
        if self.projection == "3d":
            self.axes.view_init(*self._camera)
        self.figure.subplots_adjust(left=0.12, right=0.90, bottom=0.20, top=0.87)
        if self.result is None:
            self.description.setText("运行重构后，查看分析节点形态或离散结果字段。")
            self.axes.set_axis_off()
            self._update_selection_label()
            self.canvas.draw_idle()
            return
        notes = ["三维 XYZ · 拖动旋转 · 坐标单位 m" if self.projection == "3d" else f"{self.projection.upper()} 二维投影"]
        geometry = self._geometry
        if geometry is not None:
            for index, line in enumerate(geometry.lines):
                self._plot_positions(line.reference_positions, color=color("node"), linestyle="--", linewidth=1.1,
                                     label="参考节点连线" if index == 0 else None)
                self._plot_positions(line.positions, color=color("primary"), linewidth=1.5,
                                     label="重构节点连线" if index == 0 else None)
            if geometry.nodes:
                self._scatter([node.position for node in geometry.nodes], color=color("primary"), s=13, zorder=4)
            notes.append("分析节点连线，非曲梁精确几何；变形不放大")
        else:
            notes.append(self._geometry_error or "未提供分析节点几何")
        if self.field_id is not None:
            try:
                self._scalar_layer = build_scalar_points(self.result, self.field_id, self.component)
                layer = self._scalar_layer
                notes.append(f"{layer.label} · {layer.component} / {layer.unit or '未声明单位'} · 离散原值，非连续场")
                if layer.points:
                    values = np.asarray([point.value for point in layer.points], dtype=float)
                    low, high = float(values.min()), float(values.max())
                    constant = low == high
                    margin = max(abs(low) * 0.01, 1.0e-12) if constant else 0.0
                    norm = Normalize(vmin=low - margin, vmax=high + margin)
                    cmap = LinearSegmentedColormap.from_list("ifem_scalar", [color("surface_muted"), color("primary")])
                    self._point_artist = self._scatter([point.position for point in layer.points],
                        c=values, cmap=cmap, norm=norm, s=36, edgecolors=color("text_secondary"), linewidths=0.35, zorder=6)
                    self.colorbar = self.figure.colorbar(self._point_artist, ax=self.axes, fraction=0.045, pad=0.06)
                    self.colorbar.set_label(f"{layer.component} / {layer.unit or '未声明单位'}", fontproperties=self._font,
                                            color=color("text_secondary"))
                    self.colorbar.ax.tick_params(labelsize=8, colors=color("text_secondary"))
                    self.colorbar.outline.set_edgecolor(color("border"))
                    if constant:
                        self.colorbar.set_ticks([low])
                if layer.unlocated_records:
                    notes.append(f"{len(layer.unlocated_records)} 条记录无空间位置，仅在结果字段表查看")
                if not layer.points and not layer.unlocated_records:
                    notes.append("此字段没有记录")
            except (TypeError, ValueError, KeyError) as exc:
                notes.append(f"此字段不可绘制：{exc}；其他结果仍可查看")
        self.description.setText(" · ".join(notes))
        self.description.setToolTip(self.description.text())
        self.canvas.setAccessibleDescription(self.description.text() + "。图中离散点可从结果字段表以键盘选择。")
        dimensions = self._PROJECTIONS[self.projection]
        for dimension, setter in zip(dimensions, (self.axes.set_xlabel, self.axes.set_ylabel,
                                                 getattr(self.axes, "set_zlabel", None))):
            setter(f"{'xyz'[dimension]} / m", fontproperties=self._font, color=color("text_secondary"), labelpad=3)
        self.axes.tick_params(labelsize=8, colors=color("text_secondary"), pad=2)
        self.axes.xaxis.set_major_locator(MaxNLocator(4))
        self.axes.yaxis.set_major_locator(MaxNLocator(4))
        self.axes.grid(True, color=color("grid"), linewidth=0.6)
        if self.projection != "3d":
            self.axes.set_aspect("equal", adjustable="datalim")
            for spine in self.axes.spines.values():
                spine.set_color(color("border"))
        else:
            # A colorbar gives 3D axes a right anchor by default; recenter the
            # cube in the remaining plot area instead of leaving a blank half.
            self.axes.set_anchor("C")
            self.axes.zaxis.set_major_locator(MaxNLocator(4))
            if geometry is not None and geometry.nodes:
                all_positions = np.asarray([node.reference_position for node in geometry.nodes] +
                                           [node.position for node in geometry.nodes], dtype=float)
                extents = np.ptp(all_positions, axis=0)
                longest = max(float(extents.max()), 1.0e-12)
                minimum = max(longest * 1.0e-6, 1.0e-12)
                self.axes.set_box_aspect(np.maximum(extents, minimum))
                hidden = []
                for name, extent, axis in zip("xyz", extents, (self.axes.xaxis, self.axes.yaxis, self.axes.zaxis)):
                    if extent / longest < 0.14:
                        axis.set_major_locator(NullLocator())
                        axis.label.set_visible(False)
                        hidden.append(name)
                    elif extent / longest < 0.3:
                        axis.set_major_locator(MaxNLocator(2))
                if hidden:
                    note = f"{'/'.join(hidden)} 短轴刻度略去；坐标单位 m，完整坐标见表"
                    caption = f"{'/'.join(hidden)} / m · 坐标见表"
                    if len(hidden) >= 2:
                        # A near-one-dimensional 3D box also places the long
                        # axis labels on top of the nodes. Do not widen the
                        # geometry for cosmetic effect: show its actual range
                        # as a separate caption, leaving coordinates in tables.
                        major_index = int(np.argmax(extents))
                        major_name = "xyz"[major_index]
                        for axis in (self.axes.xaxis, self.axes.yaxis, self.axes.zaxis):
                            axis.set_major_locator(NullLocator())
                            axis.label.set_visible(False)
                        lower = float(all_positions[:, major_index].min())
                        upper = float(all_positions[:, major_index].max())
                        caption = f"{major_name}：{lower:.6g} … {upper:.6g} m · 完整坐标见表"
                        note += f"；{major_name} 轴以实际范围文字显示"
                    self.description.setText(self.description.text() + " · " + note)
                    self.axes.text2D(0.5, -0.11, caption, ha="center",
                                     transform=self.axes.transAxes, fontproperties=self._font,
                                     color=color("text_secondary"))
                    self.canvas.setAccessibleDescription(self.description.text())
        if geometry is not None and geometry.lines:
            self.axes.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=2,
                             frameon=False, prop=self._font, labelcolor=color("text_secondary"))
        self._draw_selection()
        self.canvas.draw_idle()

    def highlight_record(self, field_id, entity_id):
        if self._stopped or field_id not in self._layers:
            return False
        layer = self._layers[field_id]
        if not any(record.entity_id == entity_id for record in layer.records):
            return False
        selected = (field_id, entity_id)
        if self._selected_record == selected and self.field_id == field_id:
            return True
        self._updating = True
        try:
            self.field_selector.setCurrentIndex(self.field_selector.findData(field_id))
            self._populate_components(self.component)
            self._selected_record = selected
            self._selected_node = None
            self._redraw()
        finally:
            self._updating = False
        self.view_changed.emit()
        return True

    def highlight_node(self, entity_id):
        if self._stopped or self._geometry is None:
            return False
        if not any(node.entity_id == entity_id for node in self._geometry.nodes):
            return False
        if self._selected_node == entity_id and self.field_id is None:
            return True
        self._updating = True
        try:
            self.field_selector.setCurrentIndex(0)
            self._populate_components()
            self._selected_record = None
            self._selected_node = entity_id
            self._redraw()
        finally:
            self._updating = False
        self.view_changed.emit()
        return True

    def _selected_point(self):
        if self._scalar_layer is None or self._selected_record is None:
            return None
        return next((point for point in (*self._scalar_layer.points, *self._scalar_layer.unlocated_records)
                     if point.entity_id == self._selected_record[1]), None)

    def _draw_selection(self):
        point = self._selected_point()
        if self._selected_node is not None and self._geometry is not None:
            point = next((node for node in self._geometry.nodes if node.entity_id == self._selected_node), None)
        if point is not None and point.position is not None:
            self._selection_artist = self._scatter([point.position], s=115, facecolors="none",
                edgecolors=self._theme.color("sensor_dark"), linewidths=1.8, zorder=12)
        self._update_selection_label()

    def _update_selection_label(self):
        if self._selected_node is not None and self._geometry is not None:
            node = next((node for node in self._geometry.nodes if node.entity_id == self._selected_node), None)
            if node is not None:
                coordinates = ", ".join(f"{value:.6g}" for value in node.position)
                self.selection_label.setText(f"节点 {node.entity_id} · 重构坐标 (m)：{coordinates}")
                self.selection_label.setToolTip(f"节点 ID：{node.entity_id}\n参考位置：{node.reference_position}\n重构位置：{node.position}")
                self.selection_label.setAccessibleDescription(self.selection_label.toolTip())
                return
        point = self._selected_point()
        if point is None:
            self.selection_label.setText("选择字段数据行，或单击图中离散点查看原值。")
            self.selection_label.setToolTip(self.selection_label.text())
            self.selection_label.setAccessibleDescription(self.selection_label.text())
            return
        layer = self._scalar_layer
        position = "无空间位置，仅在数据表查看" if point.position is None else (
            "重构坐标 (m)：" + ", ".join(f"{value:.6g}" for value in point.position)
        )
        self.selection_label.setText(f"{point.label or point.entity_id} · {layer.component} = {point.value:.8g} {layer.unit} · {position}")
        self.selection_label.setToolTip(f"字段：{layer.identifier}\n实体 ID：{point.entity_id}\n原值：{point.value}\n参考位置：{point.reference_position}\n重构位置：{point.position}")
        self.selection_label.setAccessibleDescription(self.selection_label.toolTip())

    def _screen_positions(self):
        records = (self._geometry.nodes if self.field_id is None and self._geometry is not None
                   else () if self._scalar_layer is None else self._scalar_layer.points)
        if not records:
            return np.empty((0, 2))
        xyz = np.asarray([point.position for point in records], dtype=float)
        if self.projection == "3d":
            x, y, _depth = proj3d.proj_transform(xyz[:, 0], xyz[:, 1], xyz[:, 2], self.axes.get_proj())
            projected = np.column_stack((x, y))
        else:
            projected = xyz[:, self._PROJECTIONS[self.projection]]
        return self.axes.transData.transform(projected)

    def _on_press(self, event):
        self._press = None
        if not self._stopped and event.button == 1 and event.inaxes is self.axes and event.x is not None:
            self._press = (event.x, event.y)

    def _on_release(self, event):
        press, self._press = self._press, None
        if self._stopped or press is None or event.button != 1 or event.inaxes is not self.axes or event.x is None:
            return
        if np.hypot(event.x - press[0], event.y - press[1]) > 5:
            return
        points = self._screen_positions()
        if not len(points):
            return
        distances = np.linalg.norm(points - np.asarray((event.x, event.y)), axis=1)
        index = int(np.argmin(distances))
        if distances[index] > 12:
            return
        if self.field_id is None and self._geometry is not None:
            node = self._geometry.nodes[index]
            self.highlight_node(node.entity_id)
            self.node_selected.emit(node.entity_id)
            return
        record = self._scalar_layer.points[index]
        field_id = self.field_id
        self.highlight_record(field_id, record.entity_id)
        self.record_selected.emit(field_id, record.entity_id)

    def shutdown(self):
        self._stopped = True
        self._press = None
        for connection in self._connections:
            self.canvas.mpl_disconnect(connection)
