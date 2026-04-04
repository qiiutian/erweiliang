import sys

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from config_adapter import (
    build_config_from_form_data,
    boundary_rows_from_prescribed_dofs,
    config_to_json,
    get_sample_config,
    load_config_from_json,
    measurement_rows_from_config,
    run_reconstruction,
    true_point_rows_from_config,
)
from layout_preview import build_measurement_preview


matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun", "Arial Unicode MS"]
matplotlib.rcParams["axes.unicode_minus"] = False


class EditableTable(QWidget):
    def __init__(self, title, field_specs, parent=None, on_change=None):
        super().__init__(parent)
        self.field_specs = field_specs
        self.inputs = {}
        self.on_change = on_change

        layout = QVBoxLayout(self)
        group = QGroupBox(title)
        layout.addWidget(group)

        group_layout = QVBoxLayout(group)
        self.table = QTableWidget(0, len(field_specs))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.setMinimumHeight(260)

        headers = [spec["label"] for spec in field_specs]
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        group_layout.addWidget(self.table)

        form = QWidget()
        form_layout = QGridLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(8)

        for index, spec in enumerate(field_specs):
            row = index // 4
            col = (index % 4) * 2
            form_layout.addWidget(QLabel(spec["label"]), row, col)
            widget = self._create_input(spec)
            self.inputs[spec["key"]] = widget
            form_layout.addWidget(widget, row, col + 1)

        group_layout.addWidget(form)

        button_bar = QHBoxLayout()
        add_button = QPushButton("新增")
        update_button = QPushButton("更新选中")
        delete_button = QPushButton("删除选中")
        clear_button = QPushButton("清空表格")
        add_button.clicked.connect(self.add_row)
        update_button.clicked.connect(self.update_selected)
        delete_button.clicked.connect(self.delete_selected)
        clear_button.clicked.connect(self.clear_rows)

        button_bar.addWidget(add_button)
        button_bar.addWidget(update_button)
        button_bar.addWidget(delete_button)
        button_bar.addWidget(clear_button)
        button_bar.addStretch(1)
        group_layout.addLayout(button_bar)

    def _create_input(self, spec):
        choices = spec.get("choices")
        if choices:
            widget = QComboBox()
            widget.addItems(choices)
            widget.setEditable(False)
            return widget
        widget = QLineEdit()
        return widget

    def _get_widget_value(self, widget):
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return widget.text().strip()

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
            self.table.setItem(row, col, QTableWidgetItem(values[spec["key"]]))
        self.clear_form()
        self._emit_change()

    def update_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        values = self.get_form_values()
        for col, spec in enumerate(self.field_specs):
            self.table.setItem(row, col, QTableWidgetItem(values[spec["key"]]))
        self._emit_change()

    def delete_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._emit_change()

    def clear_rows(self):
        self.table.setRowCount(0)
        self.clear_form()
        self._emit_change()

    def on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            return
        values = {}
        for col, spec in enumerate(self.field_specs):
            item = self.table.item(row, col)
            values[spec["key"]] = "" if item is None else item.text()
        self.set_form_values(values)

    def get_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            payload = {}
            for col, spec in enumerate(self.field_specs):
                item = self.table.item(row, col)
                payload[spec["key"]] = "" if item is None else item.text()
            rows.append(payload)
        return rows

    def set_rows(self, rows):
        self.table.setRowCount(0)
        for payload in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, spec in enumerate(self.field_specs):
                self.table.setItem(row, col, QTableWidgetItem(str(payload.get(spec["key"], ""))))
        self.clear_form()
        self._emit_change()

    def _emit_change(self):
        if callable(self.on_change):
            self.on_change()


class ReadOnlyTable(QWidget):
    def __init__(self, columns, headings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(columns))
        self.columns = columns
        self.table.setHorizontalHeaderLabels(headings)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def set_rows(self, rows):
        self.table.setRowCount(0)
        for payload in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, column in enumerate(self.columns):
                self.table.setItem(row, col, QTableWidgetItem(str(payload.get(column, ""))))


class MeasurementPreviewWidget(QWidget):
    MARK_LINE = QColor("#b91c1c")
    MARK_FILL = QColor("#ef4444")
    BEAM_COLOR = QColor("#4b5563")
    NODE_COLOR = QColor("#9ca3af")
    TEXT_COLOR = QColor("#1f2937")
    MUTED_TEXT = QColor("#6b7280")

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

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
        self._draw_legend(painter, rect.left(), rect.top() + 34)

        beam_left = rect.left() + 38
        beam_right = rect.right() - 18
        drawing_top = rect.top() + 56
        drawing_bottom = rect.bottom() - 16
        beam_y = int((drawing_top + drawing_bottom) / 2)

        painter.setPen(QPen(self.BEAM_COLOR, 3))
        painter.drawLine(beam_left, beam_y, beam_right, beam_y)
        painter.setPen(self.MUTED_TEXT)
        painter.drawText(rect.left(), beam_y - 22, 30, 18, Qt.AlignmentFlag.AlignLeft, "上")
        painter.drawText(rect.left(), beam_y + 6, 30, 18, Qt.AlignmentFlag.AlignLeft, "下")

        nodes = self.preview_data["nodes"]
        for node in nodes:
            x_pos = self._map_x(node, beam_left, beam_right)
            painter.setPen(QPen(self.NODE_COLOR, 1))
            painter.drawLine(x_pos, beam_y - 14, x_pos, beam_y + 14)
            painter.setPen(self.MUTED_TEXT)
            painter.drawText(x_pos - 24, beam_y + 18, 48, 16, Qt.AlignmentFlag.AlignHCenter, f"{node:.3g}")

        laid_out_items = self._layout_items(beam_left, beam_right, beam_y)
        for item in laid_out_items:
            rect_width = item["rect_width"]
            rect_height = item["rect_height"]
            y_pos = item["center_y"]
            x_pos = item["pixel_x"]

            painter.setPen(QPen(self.MARK_LINE, 1.2))
            painter.setBrush(self.MARK_FILL)
            painter.drawRoundedRect(x_pos - rect_width // 2, y_pos - rect_height // 2, rect_width, rect_height, 3, 3)

    def mouseMoveEvent(self, event):
        item = self._find_item_at(event.position().x(), event.position().y())
        if item is None:
            self._hovered_item_key = None
            QToolTip.hideText()
            return

        item_key = item["sequence"]
        self._hovered_item_key = item_key
        QToolTip.showText(event.globalPosition().toPoint(), self._tooltip_text(item), self)

    def leaveEvent(self, _event):
        self._hovered_item_key = None
        QToolTip.hideText()

    def _draw_legend(self, painter, x, y):
        self._draw_legend_chip(painter, x, y, self.MARK_FILL, self.MARK_LINE, "测点位置（按上下表面分层）")

    def _draw_legend_chip(self, painter, x, y, fill_color, line_color, text):
        painter.setPen(QPen(line_color, 1.2))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(x, y - 9, 18, 9, 3, 3)
        painter.setPen(self.TEXT_COLOR)
        painter.drawText(x + 24, y, text)

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
                "rect_width": 14,
                "rect_height": 8,
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
                payload["center_y"] = beam_y - 18 - row_index * 16
            else:
                payload["center_y"] = beam_y + 18 + row_index * 16
            items.append(payload)

        return items

    def _find_item_at(self, x_pos, y_pos):
        rect = self.rect().adjusted(12, 10, -12, -10)
        if not self.preview_data.get("ok") or rect.width() <= 80 or rect.height() <= 80:
            return None

        beam_left = rect.left() + 38
        beam_right = rect.right() - 18
        beam_y = int(((rect.top() + 56) + (rect.bottom() - 16)) / 2)
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


class ReconstructionMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("二维梁形状重构桌面工具")
        self.resize(1700, 1000)
        self.setMinimumSize(1380, 860)

        self.current_model = None
        self.current_config = None

        self._build_ui()
        self.load_sample_data()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)

        toolbar = QHBoxLayout()
        for text, handler in [
            ("运行重构", self.run_reconstruction),
            ("加载示例数据", self.load_sample_data),
            ("表单生成 JSON", self.refresh_json_from_form),
            ("JSON 导入表单", self.import_json_to_form),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        root_layout.addLayout(toolbar)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(main_split, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        main_split.addWidget(left_panel)

        right_split = QSplitter(Qt.Orientation.Vertical)
        main_split.addWidget(right_split)
        main_split.setSizes([700, 1000])

        self.left_tabs = QTabWidget()
        left_layout.addWidget(self.left_tabs, 1)
        self._build_left_tabs()
        self.node_x_edit.textChanged.connect(self.refresh_measurement_preview)

        preview_group = QGroupBox("梁长与测点位置")
        preview_group.setMinimumHeight(240)
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        self.measurement_preview = MeasurementPreviewWidget()
        preview_layout.addWidget(self.measurement_preview)
        left_layout.addWidget(preview_group)
        self.refresh_measurement_preview()

        plot_panel = QWidget()
        plot_panel_layout = QVBoxLayout(plot_panel)
        plot_panel_layout.setContentsMargins(0, 0, 0, 0)
        right_split.addWidget(plot_panel)

        plot_group = QGroupBox("重构图")
        plot_group_layout = QVBoxLayout(plot_group)
        plot_panel_layout.addWidget(plot_group, 1)

        canvas_container = QFrame()
        canvas_container.setFrameShape(QFrame.Shape.StyledPanel)
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(8, 8, 8, 8)
        self.figure = Figure(figsize=(9.5, 6.0), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        canvas_layout.addWidget(self.canvas)
        plot_group_layout.addWidget(canvas_container, 1)

        result_tabs = QTabWidget()
        right_split.addWidget(result_tabs)
        right_split.setSizes([620, 340])

        self.node_result_table = ReadOnlyTable(
            columns=["节点", "x坐标", "u位移", "v位移", "转角phi"],
            headings=["节点", "x坐标", "u位移", "v位移", "转角phi"],
        )
        self.query_result_table = ReadOnlyTable(
            columns=["序号", "x", "u", "v"],
            headings=["序号", "x坐标", "u位移", "v位移"],
        )
        self.compare_result_table = ReadOnlyTable(
            columns=["序号", "标签", "x", "u_实测", "v_实测", "u_重构", "v_重构", "Δu", "Δv"],
            headings=["序号", "标签", "x坐标", "u实测", "v实测", "u重构", "v重构", "Δu", "Δv"],
        )
        self.message_text = QTextEdit()
        self.message_text.setReadOnly(True)

        result_tabs.addTab(self.node_result_table, "节点结果")
        result_tabs.addTab(self.query_result_table, "查询结果")
        result_tabs.addTab(self.compare_result_table, "实测对比")
        result_tabs.addTab(self.message_text, "运行信息")

    def _build_left_tabs(self):
        basic_tab = QWidget()
        measure_tab = QWidget()
        boundary_tab = QWidget()
        optional_tab = QWidget()
        json_tab = QWidget()

        self.left_tabs.addTab(basic_tab, "基本参数")
        self.left_tabs.addTab(measure_tab, "测量数据")
        self.left_tabs.addTab(boundary_tab, "边界条件")
        self.left_tabs.addTab(optional_tab, "可选数据")
        self.left_tabs.addTab(json_tab, "JSON")

        self._build_basic_tab(basic_tab)
        self._build_measure_tab(measure_tab)
        self._build_boundary_tab(boundary_tab)
        self._build_optional_tab(optional_tab)
        self._build_json_tab(json_tab)

    def _build_basic_tab(self, parent):
        layout = QVBoxLayout(parent)
        group = QGroupBox("基本参数")
        layout.addWidget(group)
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for col, stretch in [(1, 3), (3, 2), (5, 2)]:
            grid.setColumnStretch(col, stretch)

        self.node_x_edit = QLineEdit()
        self.thickness_edit = QLineEdit()
        self.gauss_n_edit = QLineEdit("3")
        self.points_per_element_edit = QLineEdit("120")
        self.title_edit = QLineEdit("直接表面应变矩阵法二维梁形状重构结果")
        self.query_xs_edit = QLineEdit()
        self.y_min_edit = QLineEdit()
        self.y_max_edit = QLineEdit()

        grid.addWidget(QLabel("节点 x 坐标"), 0, 0)
        grid.addWidget(self.node_x_edit, 0, 1, 1, 5)
        grid.addWidget(QLabel("梁厚度 thickness"), 1, 0)
        grid.addWidget(self.thickness_edit, 1, 1)
        grid.addWidget(QLabel("高斯点数 gauss_n"), 1, 2)
        grid.addWidget(self.gauss_n_edit, 1, 3)
        grid.addWidget(QLabel("每单元采样点数"), 1, 4)
        grid.addWidget(self.points_per_element_edit, 1, 5)
        grid.addWidget(QLabel("图标题"), 2, 0)
        grid.addWidget(self.title_edit, 2, 1, 1, 5)
        grid.addWidget(QLabel("查询点 x 列表"), 3, 0)
        grid.addWidget(self.query_xs_edit, 3, 1, 1, 5)
        grid.addWidget(QLabel("Y轴最小值"), 4, 0)
        grid.addWidget(self.y_min_edit, 4, 1)
        grid.addWidget(QLabel("Y轴最大值"), 4, 2)
        grid.addWidget(self.y_max_edit, 4, 3)
        grid.addWidget(QLabel("Y轴最小值和最大值同时留空时为自动缩放。"), 5, 0, 1, 6)

        options_group = QGroupBox("显示选项")
        options_layout = QGridLayout(options_group)
        self.show_original_check = QCheckBox("显示原始中性层")
        self.show_original_check.setChecked(True)
        self.show_nodes_check = QCheckBox("显示重构节点")
        self.show_nodes_check.setChecked(True)
        self.equal_axis_check = QCheckBox("等比例坐标轴")
        self.annotate_points_check = QCheckBox("标注实测/重构点")
        self.connect_pairs_check = QCheckBox("连线显示差异")
        self.connect_pairs_check.setChecked(True)

        options_layout.addWidget(self.show_original_check, 0, 0)
        options_layout.addWidget(self.show_nodes_check, 0, 1)
        options_layout.addWidget(self.equal_axis_check, 0, 2)
        options_layout.addWidget(self.annotate_points_check, 1, 0)
        options_layout.addWidget(self.connect_pairs_check, 1, 1)
        layout.addWidget(options_group)
        layout.addStretch(1)

    def _build_measure_tab(self, parent):
        layout = QVBoxLayout(parent)
        specs = [
            {"key": "element", "label": "单元号"},
            {"key": "x", "label": "x"},
            {"key": "surface", "label": "surface", "choices": ["", "top", "bot", "上", "下"]},
            {"key": "y", "label": "y"},
            {"key": "strain", "label": "strain"},
            {"key": "weight", "label": "weight"},
            {"key": "zone_a", "label": "zone起点"},
            {"key": "zone_b", "label": "zone终点"},
        ]
        self.measurement_editor = EditableTable("测量数据", specs, on_change=self.refresh_measurement_preview)
        layout.addWidget(self.measurement_editor)

    def _build_boundary_tab(self, parent):
        layout = QVBoxLayout(parent)
        specs = [
            {"key": "node", "label": "节点号"},
            {"key": "dof", "label": "自由度", "choices": ["u", "v", "phi"]},
            {"key": "value", "label": "约束值"},
        ]
        self.boundary_editor = EditableTable("边界条件", specs)
        layout.addWidget(self.boundary_editor)
        layout.addWidget(QLabel("界面使用 节点号 + 自由度(u/v/phi) 录入，程序会自动转换为全局自由度编号。"))

    def _build_optional_tab(self, parent):
        layout = QVBoxLayout(parent)
        specs = [
            {"key": "label", "label": "标签"},
            {"key": "x", "label": "x"},
            {"key": "u", "label": "u实测"},
            {"key": "v", "label": "v实测"},
        ]
        self.true_point_editor = EditableTable("实测对比点", specs)
        layout.addWidget(self.true_point_editor)

    def _build_json_tab(self, parent):
        layout = QVBoxLayout(parent)
        self.json_text = QPlainTextEdit()
        self.json_text.setMinimumHeight(300)
        layout.addWidget(self.json_text)

    def _collect_plot_options(self):
        y_min_text = self.y_min_edit.text().strip()
        y_max_text = self.y_max_edit.text().strip()
        if y_min_text or y_max_text:
            if not (y_min_text and y_max_text):
                raise ValueError("手动设置 Y 轴时，Y轴最小值和最大值必须同时填写。")
            y_limits = [float(y_min_text), float(y_max_text)]
            if y_limits[1] <= y_limits[0]:
                raise ValueError("Y 轴范围不合法，要求最大值大于最小值。")
        else:
            y_limits = None

        return {
            "show_original": self.show_original_check.isChecked(),
            "show_nodes": self.show_nodes_check.isChecked(),
            "equal_axis": self.equal_axis_check.isChecked(),
            "annotate_points": self.annotate_points_check.isChecked(),
            "connect_pairs": self.connect_pairs_check.isChecked(),
            "title": self.title_edit.text().strip() or "直接表面应变矩阵法二维梁形状重构结果",
            "legend_loc": "best",
            "label_offset_scale": 0.04,
            "figsize": [11.0, 4.5],
            "y_limits": y_limits,
        }

    def _build_form_config(self):
        return build_config_from_form_data(
            node_x_text=self.node_x_edit.text(),
            thickness_text=self.thickness_edit.text(),
            gauss_n_text=self.gauss_n_edit.text(),
            points_per_element_text=self.points_per_element_edit.text(),
            query_xs_text=self.query_xs_edit.text(),
            measurement_rows=self.measurement_editor.get_rows(),
            boundary_rows=self.boundary_editor.get_rows(),
            true_point_rows=self.true_point_editor.get_rows(),
            plot_options=self._collect_plot_options(),
        )

    def refresh_json_from_form(self):
        try:
            config = self._build_form_config()
            self.json_text.setPlainText(config_to_json(config))
            self._write_message("已根据当前表单生成 JSON 配置。")
        except Exception as exc:
            self._show_error(exc)

    def import_json_to_form(self):
        try:
            config = load_config_from_json(self.json_text.toPlainText().strip())
            self._load_config_to_form(config)
            self._write_message("JSON 已导入到表单。")
        except Exception as exc:
            self._show_error(exc)

    def load_sample_data(self):
        config = get_sample_config()
        self._load_config_to_form(config)
        self.json_text.setPlainText(config_to_json(config))
        self._write_message("已加载示例数据。")

    def _load_config_to_form(self, config):
        self.node_x_edit.setText(", ".join(f"{x:.12g}" for x in config["node_x"]))
        self.thickness_edit.setText(f"{float(config['thickness']):.12g}")
        self.gauss_n_edit.setText(str(config.get("gauss_n", 3)))
        self.points_per_element_edit.setText(str(config.get("points_per_element", 120)))
        self.query_xs_edit.setText(", ".join(f"{float(x):.12g}" for x in config.get("query_xs", [])))

        plot_options = config.get("plot_options", {})
        self.title_edit.setText(plot_options.get("title", "直接表面应变矩阵法二维梁形状重构结果"))
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

        self.measurement_editor.set_rows(measurement_rows_from_config(config))
        self.boundary_editor.set_rows(boundary_rows_from_prescribed_dofs(config["prescribed_dofs"]))
        self.true_point_editor.set_rows(true_point_rows_from_config(config))
        self.refresh_measurement_preview()

    def refresh_measurement_preview(self):
        if not hasattr(self, "measurement_editor") or not hasattr(self, "measurement_preview"):
            return
        preview_data = build_measurement_preview(self.node_x_edit.text(), self.measurement_editor.get_rows())
        self.measurement_preview.set_preview_data(preview_data)

    def run_reconstruction(self):
        try:
            config = self._build_form_config()
            model, inputs = run_reconstruction(config)
            self.current_model = model
            self.current_config = config
            self.json_text.setPlainText(config_to_json(config))
            self._render_plot(model, inputs)
            self._fill_result_tables(model, inputs)
            self._write_message(
                "重构完成。\n"
                f"节点数: {model.n_nodes}\n"
                f"单元数: {model.n_elems}\n"
                f"高斯点数: {inputs['gauss_n']}\n"
                f"每单元采样点数: {inputs['points_per_element']}"
            )
        except Exception as exc:
            self._show_error(exc)

    def _render_plot(self, model, inputs):
        plot_options = dict(inputs["plot_options"])
        plot_options.pop("figsize", None)
        title = plot_options.pop("title", "直接表面应变矩阵法二维梁形状重构结果")

        model.plot_on_axes(
            self.axes,
            points_per_element=inputs["points_per_element"],
            true_points=inputs["true_points"],
            title=title,
            show_legend=False,
            **plot_options,
        )
        self._render_plot_legend()
        self.figure.tight_layout(pad=1.0, rect=(0.02, 0.02, 0.98, 0.86))
        self.canvas.draw_idle()

    def _render_plot_legend(self):
        for legend in list(self.figure.legends):
            legend.remove()

        handles, labels = self.axes.get_legend_handles_labels()
        unique = []
        seen = set()
        for handle, label in zip(handles, labels):
            if not label or label in seen:
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
            ncol=min(len(legend_labels), 4),
            frameon=False,
            fontsize=9,
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

    def _write_message(self, message):
        self.message_text.setPlainText(message)

    def _show_error(self, exc):
        message = str(exc)
        self._write_message(f"运行失败：\n{message}")
        QMessageBox.critical(self, "错误", message)


def launch_app():
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    window = ReconstructionMainWindow()
    window.show()
    if owns_app:
        return app.exec()
    return 0
