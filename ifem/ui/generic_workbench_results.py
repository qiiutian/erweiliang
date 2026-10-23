"""Link standard result snapshots to the desktop workbench, without a solver object."""

from PySide6.QtCore import QObject, QSignalBlocker, Qt
from PySide6.QtWidgets import QFrame, QSizePolicy


class GenericWorkbenchResults(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._syncing = False
        self._field_table_origin = False
        self._native_residual_explanation = window.sensor_explanation.text()
        view = window.generic_result_view
        view.record_selected.connect(self._record_picked)
        view.node_selected.connect(self._node_picked)
        view.view_changed.connect(self._view_changed)
        panel = window.result_fields_panel
        panel.selector.currentIndexChanged.connect(self._field_changed)
        panel.table.selectionModel().currentRowChanged.connect(self._field_row_changed)
        window.generic_state_table.table.currentCellChanged.connect(self._state_row_changed)
        window.sensor_result_table.table.currentCellChanged.connect(self._sensor_row_changed)

    def _ready(self):
        window = self.window
        return (not self._syncing and window._is_generic_result()
                and window.generic_result_view.result is window.current_analysis_result)

    def install(self, result):
        window = self.window
        self._syncing = True
        try:
            window.generic_result_view.set_result(result)
            self._fill_state(result.state)
            self.set_active(True)
            window.plot_content_stack.setCurrentWidget(window.generic_result_view)
            window.result_tabs.setCurrentWidget(window.generic_state_table)
            window.current_view = "shape"
            window.view_buttons["shape"].setChecked(True)
            state = result.state
            window.analysis_metric_labels["mesh"].setText(
                f"{state.modeling_space.upper()} · {len(state.node_ids)} 节点 / {len(state.element_ids)} 单元"
            )
            window.analysis_metric_labels["solver"].setText(window.analysis_setup.active_algorithm_display_name)
        finally:
            self._syncing = False
        self.refresh_context()

    def _fill_state(self, state):
        wrapper = self.window.generic_state_table
        rows = []
        for index, identifier in enumerate(state.node_ids):
            rotation = state.rotations[index] if state.rotations else ()
            rows.append({
                "节点": identifier,
                **{name: f"{value:.10g}" for name, value in zip(("x", "y", "z"), state.reference_coordinates[index])},
                **{name: f"{value:.10g}" for name, value in zip(("ux", "uy", "uz"), state.displacements[index])},
                "转动": ", ".join(f"{value:.10g}" for value in rotation) if rotation else "未提供",
            })
        wrapper.set_rows(rows)
        representation = state.rotation_representation
        rotation_note = {
            "rotation_vector": "转动向量 (rx, ry, rz)，单位 rad",
            "quaternion": "相对转动四元数 (w, x, y, z)，无量纲",
            "rotation_matrix": "相对转动矩阵，行优先 9 分量，无量纲",
        }.get(representation, f"转动表示：{representation}")
        wrapper.table.horizontalHeaderItem(7).setToolTip(rotation_note)
        wrapper.table.setToolTip(f"分析结果节点，参考坐标与位移单位 m。{rotation_note}；不折算为二维 φ。")
        for row in range(len(rows)):
            tooltip = (f"节点 ID：{state.node_ids[row]}\n参考位置：{state.reference_coordinates[row]}\n"
                       f"位移：{state.displacements[row]}\n{rotation_note}\n"
                       f"转动原值：{state.rotations[row] if state.rotations else '未提供'}")
            for column in range(wrapper.table.columnCount()):
                wrapper.table.item(row, column).setToolTip(tooltip)
        self.window.result_tabs.setTabText(self.window.generic_state_tab_index, f"重构状态 · {len(rows)}")

    def set_active(self, active):
        window = self.window
        # The generic selector already includes fields and projections. Keep
        # one control row instead of duplicating the native result toolbar.
        toolbar = getattr(window.generic_result_view, "toolbar_layout", None)
        if toolbar is not None:
            destination = toolbar if active else window.view_toolbar.layout()
            if destination.indexOf(window.focus_mode_button) < 0:
                destination.addWidget(window.focus_mode_button)
            window.view_toolbar.setVisible(not active)
        window.plot_content_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored if active else QSizePolicy.Policy.Preferred,
        )
        plot_layout = window.right_split.widget(0).layout()
        plot_layout.setContentsMargins(10, 3 if active else 10, 10, 3 if active else 8)
        plot_layout.setSpacing(2 if active else 8)
        # Hidden empty/native pages must not reserve their height in this mode.
        window.plot_content_stack.setMinimumHeight(window.generic_result_view.minimumSizeHint().height() if active else 0)
        for index in (window.node_result_tab_index, window.query_result_tab_index,
                      window.compare_result_tab_index, window.field_result_tab_index):
            window.result_tabs.setTabVisible(index, not active)
        window.result_tabs.setTabVisible(window.generic_state_tab_index, active)
        window.result_tabs.setTabVisible(window.sensor_result_tab_index,
                                        not active or window.sensor_result_table.table.rowCount() > 0)
        window.probe_bar.setVisible(not active)
        window.sensor_explanation.setText(
            "残差 = 重构应变 − 观测应变；由当前方法提供，拟合一致性不等于真实重构误差。"
            if active else self._native_residual_explanation
        )
        for button in window.scale_buttons.values():
            button.setVisible(not active)
            button.setEnabled(not active and not window._analysis_busy)
        window.display_settings_button.setVisible(not active)
        if active:
            window.display_settings_button.setChecked(False)
        # Keep the view/space divider, but hide the divider before native scaling.
        dividers = window.view_toolbar.findChildren(QFrame, "toolbarDivider")
        if len(dividers) > 1:
            dividers[-1].setVisible(not active)
        fields = {} if window.current_analysis_result is None else window.current_analysis_result.fields
        for index, mode in enumerate(("shape", "strain", "stress")):
            enabled = not active or mode == "shape" or f"axial_{mode}" in fields
            window.view_buttons[mode].setEnabled(enabled)
            window.view_shortcut_actions[index].setEnabled(enabled)

    def clear(self):
        self.window.generic_result_view.clear()
        self.window.generic_state_table.set_rows([])
        self.set_active(False)

    def capture(self):
        view = self.window.generic_result_view
        return {"field": view.field_id, "component": view.component,
                "projection": view.projection, "record": view.selected_record, "node": view.selected_node}

    def restore(self, snapshot):
        view = self.window.generic_result_view
        view.set_field(snapshot["field"])
        if snapshot["component"] is not None:
            view.set_component(snapshot["component"])
        view.set_projection(snapshot["projection"])
        if snapshot["record"] is not None:
            view.highlight_record(*snapshot["record"])
        elif snapshot["node"] is not None:
            view.highlight_node(snapshot["node"])
        self._view_changed()

    def _field_changed(self, *_args):
        if self._ready():
            self.window.generic_result_view.set_field(self.window.result_fields_panel.selector.currentData())

    def _field_row_changed(self, current, _previous):
        if self._ready() and current.isValid():
            layer = self.window.result_fields_panel.model.layer
            if layer is not None and 0 <= current.row() < len(layer.records):
                self._field_table_origin = True
                try:
                    self.window.generic_result_view.highlight_record(layer.identifier, layer.records[current.row()].entity_id)
                finally:
                    self._field_table_origin = False

    def _state_row_changed(self, row, *_args):
        if self._ready() and 0 <= row < len(self.window.current_analysis_result.state.node_ids):
            self.window.generic_result_view.highlight_node(self.window.current_analysis_result.state.node_ids[row])

    def _sensor_row_changed(self, row, *_args):
        if self._ready() and row >= 0:
            from ifem.visualization.sensor_residuals import sensor_residual_data
            targets = sensor_residual_data(self.window.current_analysis_result)[1]
            if row < len(targets):
                self.window.generic_result_view.highlight_record("sensor_strain_residual", targets[row].source_id)

    def _record_picked(self, _field, _entity):
        if self._ready():
            self._view_changed()
            self._reveal(self.window.result_fields_panel)

    def _node_picked(self, _entity):
        if self._ready():
            self._view_changed()
            self._reveal(self.window.generic_state_table)

    def _reveal(self, panel):
        self.window.focus_mode_button.setChecked(False)
        self.window.result_toggle.setChecked(True)
        self.window.result_tabs.setCurrentWidget(panel)

    def _view_changed(self):
        if not self._ready():
            return
        window = self.window
        view, panel = window.generic_result_view, window.result_fields_panel
        self._syncing = True
        try:
            if view.field_id is not None:
                index = panel.selector.findData(view.field_id)
                if index >= 0:
                    panel.selector.setCurrentIndex(index)
            current = panel.table.currentIndex()
            layer = panel.model.layer
            same_current_record = (
                layer is not None and current.isValid()
                and 0 <= current.row() < len(layer.records)
                and view.selected_record == (layer.identifier, layer.records[current.row()].entity_id)
            )
            preserve_selection = self._field_table_origin or same_current_record
            with QSignalBlocker(panel.table.selectionModel()):
                if not preserve_selection:
                    panel.table.clearSelection()
                    panel.table.setCurrentIndex(panel.model.index(-1, -1))
                if not preserve_selection and view.selected_record is not None and panel.model.layer is not None:
                    identifier, entity = view.selected_record
                    if identifier == panel.model.layer.identifier:
                        for row, record in enumerate(panel.model.layer.records):
                            if record.entity_id == entity:
                                panel.table.setCurrentIndex(panel.model.index(row, 0))
                                panel.table.selectRow(row)
                                panel.table.scrollTo(panel.model.index(row, 0))
                                break
            table = window.generic_state_table.table
            with QSignalBlocker(table):
                table.clearSelection()
                table.setCurrentCell(-1, -1)
                if view.selected_node is not None:
                    row = window.current_analysis_result.state.node_ids.index(view.selected_node)
                    table.setCurrentCell(row, 0)
                    table.selectRow(row)
                    table.scrollToItem(table.item(row, 0))
            sensor_table = window.sensor_result_table.table
            with QSignalBlocker(sensor_table):
                sensor_table.clearSelection()
                sensor_table.setCurrentCell(-1, -1)
                if (view.selected_record is not None and panel.model.layer is not None
                        and panel.model.layer.association == "sensor"):
                    from ifem.visualization.sensor_residuals import sensor_residual_data
                    for row, target in enumerate(sensor_residual_data(window.current_analysis_result)[1]):
                        if target.source_id == view.selected_record[1]:
                            sensor_table.setCurrentCell(row, 0)
                            sensor_table.selectRow(row)
                            sensor_table.scrollToItem(sensor_table.item(row, 0))
                            break
            mode = {None: "shape", "axial_strain": "strain", "axial_stress": "stress"}.get(view.field_id)
            window.view_button_group.setExclusive(False)
            for key, button in window.view_buttons.items():
                button.setChecked(key == mode)
            window.view_button_group.setExclusive(True)
            if mode is not None:
                window.current_view = mode
        finally:
            self._syncing = False
        self.refresh_context()

    def refresh_context(self):
        window = self.window
        view = window.generic_result_view
        if not window._is_generic_result() or view.result is None:
            return
        minimum = view.minimumSizeHint().height()
        if window.plot_content_stack.minimumHeight() != minimum:
            window.plot_content_stack.setMinimumHeight(minimum)
        space = "三维 XYZ" if view.projection == "3d" else f"{view.projection.upper()} 投影"
        field = view.field_selector.currentText()
        stale = " · 已过期" if window.results_stale else ""
        window.view_context_label.setText(f"通用结果 · {space} · {field}{stale}")
        state = view.result.state
        regime = "大变形" if state.deformation_regime == "large_deformation" else "小变形"
        text = f"{state.modeling_space.upper()} · {regime} · 实际坐标与离散原值 · 不生成连续云图"
        window._view_meta_text = text
        window.view_meta_label.setText(text)
        window.view_meta_label.setToolTip(text)
        window.view_meta_label.setVisible(True)
        window.view_toolbar.setToolTip(text)
        window.display_buttons["3d" if view.projection == "3d" else "2d"].setChecked(True)
