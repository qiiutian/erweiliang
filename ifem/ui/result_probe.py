"""Read-only result selection shared by plots, tables and the model viewport."""
from __future__ import annotations

import numpy as np
from matplotlib.lines import Line2D
from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout

from ifem.ui.studio import ElidingLabel
from ifem.visualization.result_link import build_result_targets


class ResultProbeBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plotMetaBar")
        self.setAccessibleName("结果数值探针")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(1)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        self.title = ElidingLabel("结果探针")
        self.title.setObjectName("plotContext")
        heading.addWidget(self.title, 1)
        self.locate_button = QPushButton("定位数据行")
        self.locate_button.setObjectName("panelToggle")
        self.locate_button.setToolTip("展开结果表格并定位当前探针对应的数据行")
        self.clear_button = QPushButton("清除")
        self.clear_button.setObjectName("panelToggle")
        self.clear_button.setAccessibleName("清除结果探针")
        heading.addWidget(self.locate_button)
        heading.addWidget(self.clear_button)
        layout.addLayout(heading)
        self.detail = ElidingLabel("")
        self.detail.setObjectName("sectionHint")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)


class ResultLinkController(QObject):
    """Own selection of one result snapshot, never of live editable input data."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.targets = {}
        self.selected = None
        self.sequence = None
        self.representation = None
        self._artists = []
        self._press = None
        self._syncing = False
        self._stopped = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._resize_plot)
        window.canvas.installEventFilter(self)
        self.tables = {
            "node": window.node_result_table,
            "query": window.query_result_table,
            "compare": window.compare_result_table,
            "sample": window.field_result_table,
        }
        for kind, wrapper in self.tables.items():
            wrapper.table.currentCellChanged.connect(
                lambda row, _col, _previous, _previous_col, key=kind: self._table_selected(key, row)
            )
        window.probe_bar.clear_button.clicked.connect(self.clear_selection)
        window.probe_bar.locate_button.clicked.connect(self.reveal_selection)
        window.structure_3d_view.result_picked.connect(self._model_picked)
        self._connections = (
            window.canvas.mpl_connect("button_press_event", self._plot_press),
            window.canvas.mpl_connect("button_release_event", self._plot_release),
        )
        self.refresh()

    def eventFilter(self, watched, event):
        if watched is self.window.canvas and event.type() == QEvent.Type.Resize:
            if not self._stopped and self.window.current_model is not None:
                self._resize_timer.start()
        return super().eventFilter(watched, event)

    def _resize_plot(self):
        if not self._stopped and not self.window._analysis_busy and self.window.current_model is not None:
            self.window._render_current_view()

    def update(self):
        window = self.window
        if self._stopped:
            return
        if window.current_model is None or window.current_field is None:
            self.clear()
            return
        sequence = window.result_sequence
        representation = window.current_field.representation
        new_snapshot = self.sequence != sequence
        changed_representation = self.representation != representation
        previous = self.selected
        self.targets = build_result_targets(
            window.current_model, window.current_inputs,
            None if window.current_analysis_result is None else window.current_analysis_result.state,
            window.current_field, sequence,
        )
        self.sequence, self.representation = sequence, representation
        if new_snapshot or (changed_representation and previous and previous.kind == "sample"):
            self.selected = None
            self._clear_table_selections()
            if not new_snapshot and previous is not None:
                window.statusBar().showMessage("场表示已切换，请重新选择截面采样点；原始场与连续化场不混用。", 6000)
        elif previous:
            self.selected = next(
                (target for target in self.targets.get(previous.kind, ()) if target.entity_id == previous.entity_id),
                None,
            )
        if self.selected is not None:
            self._sync_table()
        self.refresh()

    def clear(self):
        self.targets = {}
        self.selected = None
        self.sequence = self.representation = None
        self._clear_table_selections()
        self.refresh()

    def _clear_table_selections(self, except_kind=None):
        for kind, wrapper in self.tables.items():
            if kind == except_kind:
                continue
            with QSignalBlocker(wrapper.table):
                wrapper.table.clearSelection()
                wrapper.table.setCurrentCell(-1, -1)

    def clear_selection(self):
        self.selected = None
        self._clear_table_selections()
        self.refresh()

    def _table_selected(self, kind, row):
        if self._syncing or self._stopped or row < 0:
            return
        item = self.tables[kind].table.item(row, 0)
        if item is not None:
            index = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(index, int):
                if not self.select(kind, index):
                    self._restore_rejected_selection()

    def select(self, kind, index, *, reveal=False, force=False):
        if self._stopped or (self.window._analysis_busy and not force):
            return False
        targets = self.targets.get(kind, ())
        if not isinstance(index, int) or not 0 <= index < len(targets):
            return False
        self.selected = targets[index]
        self._clear_table_selections(except_kind=kind)
        self._sync_table(reveal=reveal)
        self.refresh()
        return True

    def _sync_table(self, *, reveal=False):
        target = self.selected
        if target is None:
            return
        wrapper = self.tables[target.kind]
        table = wrapper.table
        self._syncing = True
        try:
            if target.kind == "sample" and not any(
                table.item(row, 0).data(Qt.ItemDataRole.UserRole) == target.index
                for row in range(table.rowCount())
            ):
                self.window._fill_field_result_table(include_sample=target.index)
            for row in range(table.rowCount()):
                if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == target.index:
                    with QSignalBlocker(table):
                        table.setCurrentCell(row, 0)
                        table.selectRow(row)
                    table.scrollToItem(table.item(row, 0))
                    break
            if reveal:
                self.window.result_tabs.setCurrentWidget(wrapper)
        finally:
            self._syncing = False

    def reveal_selection(self):
        if self.selected is None:
            return
        self.window.focus_mode_button.setChecked(False)
        self.window.result_toggle.setChecked(True)
        self._sync_table(reveal=True)
        self.tables[self.selected.kind].table.setFocus()

    def _model_picked(self, kind, index):
        if not self.select(kind, index, reveal=True):
            self._restore_rejected_selection()

    def _restore_rejected_selection(self):
        if self._stopped:
            return
        self._clear_table_selections()
        self._sync_table()
        self.refresh()

    def _plot_press(self, event):
        self._press = None
        if event.button == 1 and event.inaxes is self.window.axes and event.x is not None:
            self._press = (event.x, event.y)

    def _plot_release(self, event):
        press, self._press = self._press, None
        if press is None or event.button != 1 or event.inaxes is not self.window.axes:
            return
        if event.x is None or np.hypot(event.x - press[0], event.y - press[1]) > 5:
            return
        toolbar = getattr(self.window.canvas, "toolbar", None)
        if toolbar is not None and toolbar.mode:
            return
        target = self.pick_2d(event.x, event.y)
        if target is not None:
            self.select(target.kind, target.index, reveal=True)

    def pick_2d(self, x, y):
        """Screen-space hit test on rendered stations, not rounded table strings."""
        window = self.window
        if not self.targets or window.current_field is None:
            return None
        if window.current_view == "stress" and window.current_field.stress is None:
            return None
        point = np.asarray((x, y), dtype=float)
        if not np.isfinite(point).all():
            return None
        transform = window.axes.transData
        if window.current_view == "shape":
            nodes = self.targets.get("node", ())
            positions = transform.transform([target.position[:2] for target in nodes])
            distances = np.linalg.norm(positions - point, axis=1)
            if len(distances) and distances.min() <= 12:
                return nodes[int(np.argmin(distances))]
        from postprocessing import resolve_thickness_scale
        scale = resolve_thickness_scale(window.current_field, window.current_inputs["plot_options"].get("thickness_scale", "auto"))
        grid_x, grid_y = window.current_field.display_grid(scale)
        start = transform.transform(np.column_stack((grid_x[0], grid_y[0])))
        end = transform.transform(np.column_stack((grid_x[-1], grid_y[-1])))
        segment = end - start
        lengths = np.sum(segment * segment, axis=1)
        weight = np.clip(np.sum((point - start) * segment, axis=1) / np.maximum(lengths, 1e-20), 0, 1)
        distances = np.linalg.norm(start + weight[:, None] * segment - point, axis=1)
        index = int(np.argmin(distances))
        if distances[index] <= 10:
            return self.targets["sample"][index]
        return None

    def refresh(self):
        if self._stopped:
            return
        window, target = self.window, self.selected
        bar = window.probe_bar
        bar.locate_button.setEnabled(target is not None)
        bar.clear_button.setEnabled(target is not None)
        if target is None:
            bar.title.setText("结果探针" + (" · 已过期" if window.results_stale else ""))
            bar.title.setToolTip("")
            bar.detail.setText("单击结果图或选择数据行 · 三维视图 Ctrl+单击拾取" if self.targets else "运行重构后，可选择数据行或拾取结果模型。")
        else:
            kind_name = {"node": "节点", "sample": "截面采样", "query": "查询点", "compare": "实测对比"}[target.kind]
            representation = {"raw": "原始单元场", "nodal_average": "节点平均连续化"}.get(target.representation, "")
            status = "已过期 · " if window.results_stale else ""
            suffix = f" · {representation}" if representation else ""
            number = target.index if target.kind == "node" else target.index + 1
            element = f" · 单元 {int(window.current_field.element_index[target.index])}" if target.kind == "sample" else ""
            bar.title.setText(f"{status}{kind_name} {number}{element} · x = {target.reference_position[0]:.6g} m{suffix}")
            identity = f"结果帧 {self.sequence}\n实体：{target.source_id or target.entity_id}"
            if target.element_id:
                identity += f"\n单元：{target.element_id}"
            identity += "\n参考位置 (m)：" + ", ".join(f"{value:.12g}" for value in target.reference_position)
            identity += "\n重构位置 (m)：" + ", ".join(f"{value:.12g}" for value in target.position)
            bar.title.setToolTip(identity + ("\n当前为上一次计算结果，请重新运行。" if window.results_stale else ""))
            values = [f"{label} {'未提供' if value is None else f'{value:.6g}'}{(' ' + unit) if value is not None and unit else ''}" for label, value, unit in target.values]
            bar.detail.setText(" · ".join(values))
        bar.title.setAccessibleDescription(bar.title.text() + "\n" + bar.title.toolTip())
        bar.detail.setAccessibleDescription(bar.detail.text())
        self._draw_marker()
        viewport = window.structure_3d_view
        if target is None:
            viewport.set_result_selection(None, None)
        elif target.kind in {"node", "sample"}:
            viewport.set_result_selection(target.kind, target.index)
        else:
            viewport.set_probe_position(target.position)

    def _draw_marker(self):
        for artist in self._artists:
            try:
                artist.remove()
            except (ValueError, NotImplementedError):
                pass
        self._artists = []
        target, window = self.selected, self.window
        if target is not None and not (window.current_view == "stress" and window.current_field.stress is None):
            color = window._theme_color("focus")
            if target.kind == "sample":
                from postprocessing import resolve_thickness_scale
                field = window.current_field
                scale = resolve_thickness_scale(field, window.current_inputs["plot_options"].get("thickness_scale", "auto"))
                gx, gy = field.display_grid(scale)
                self._artists.append(Line2D(gx[[0, -1], target.index], gy[[0, -1], target.index], color=color, linewidth=1.6, linestyle="--", zorder=12))
            self._artists.append(Line2D([target.position[0]], [target.position[1]], marker="o", markersize=9, markerfacecolor="none", markeredgecolor=color, markeredgewidth=2, linestyle="none", zorder=13))
            for artist in self._artists:
                window.axes.add_artist(artist)
        window.canvas.draw_idle()

    def shutdown(self):
        self._stopped = True
        self._resize_timer.stop()
        self.window.canvas.removeEventFilter(self)
        for connection in self._connections:
            self.window.canvas.mpl_disconnect(connection)
