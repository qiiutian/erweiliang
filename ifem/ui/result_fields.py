"""Native-model-independent, read-only inspection of plugin result fields."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QTableView, QVBoxLayout, QWidget,
)

from ifem.domain.result_fields import map_result_field


class ResultFieldTableModel(QAbstractTableModel):
    """Keep full precision in the snapshot; format lazily for visible cells."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layer = None

    def set_layer(self, layer):
        self.beginResetModel()
        self.layer = layer
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or self.layer is None else len(self.layer.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or self.layer is None else 5 + len(self.layer.components)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or self.layer is None:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        headers = ["实体"]
        labels = {"top": "上表面", "bottom": "下表面", "axial": "轴向"} if self.layer.known else {}
        headers += [f"{labels.get(name, name)} / {self.layer.unit or '未声明单位'}" for name in self.layer.components]
        headers += ["参考 x / m", "参考 y / m", "参考 z / m", "来源 ID"]
        return headers[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.layer is None:
            return None
        record = self.layer.records[index.row()]
        coordinates = record.reference_position or (None, None, None)
        values = (record.entity_id, *record.values, *coordinates, record.source_entity_id or "—")
        value = values[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return record.label or record.entity_id
            return "—" if value is None else f"{value:.8g}" if isinstance(value, (int, float)) else str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{record.label or record.entity_id}\n参考位置：{record.reference_position}\n重构位置：{record.position}\n原值：{value}"
        if role == Qt.ItemDataRole.TextAlignmentRole and 0 < index.column() < self.columnCount() - 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole:
            return value
        return None


class ResultFieldsPanel(QWidget):
    """Browse any contract field, including custom plugin metadata, without a solver model."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self._layers = {}
        self._errors = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        label = QLabel("结果字段")
        self.selector = QComboBox()
        self.selector.setAccessibleName("浏览通用结果字段")
        self.selector.setMinimumContentsLength(16)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        label.setBuddy(self.selector)
        row.addWidget(label)
        row.addWidget(self.selector, 1)
        layout.addLayout(row)
        self.metadata = QLabel("运行后查看方法输出的字段、实体、分量和单位。")
        self.metadata.setObjectName("sectionHint")
        self.metadata.setWordWrap(True)
        layout.addWidget(self.metadata)
        self.table = QTableView()
        self.table.setAccessibleName("通用结果字段数据表")
        self.model = ResultFieldTableModel(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(125)
        layout.addWidget(self.table, 1)
        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_selection)
        self.selector.currentIndexChanged.connect(self._select)
        self.set_result(None)

    def set_result(self, result):
        previous = self.selector.currentData()
        self.result = result
        self._layers = {}
        self._errors = {}
        self.selector.blockSignals(True)
        self.selector.clear()
        if result is not None:
            for identifier in result.fields:
                try:
                    layer = map_result_field(result, identifier)
                    self._layers[identifier] = layer
                    self.selector.addItem(layer.label, identifier)
                except (TypeError, ValueError, KeyError) as exc:
                    # Contract-v0 plugins may expose arbitrary payloads. Do not
                    # fail their existing native view because they lack v1 data.
                    self._errors[identifier] = str(exc)
                    self.selector.addItem(f"{identifier} · 暂不可浏览", identifier)
        index = self.selector.findData(previous)
        self.selector.setCurrentIndex(max(0, index) if self.selector.count() else -1)
        self.selector.blockSignals(False)
        self.selector.setEnabled(self.selector.count() > 0)
        self._select()

    def _select(self, *_args):
        identifier = self.selector.currentData()
        layer = self._layers.get(identifier)
        self.model.set_layer(layer)
        if layer is None:
            self.metadata.setText("此字段尚未提供通用数据契约；原有结果视图不受影响。" if identifier is not None
                                  else "暂无通用结果字段；旧版方法仍可使用原有结果视图。")
            self.metadata.setToolTip(self._errors.get(identifier, ""))
            return
        associations = {"node": "节点", "element": "单元", "sensor": "测点", "sample": "采样点", "global": "全局"}
        self.metadata.setText(
            f"{associations.get(layer.association, layer.association)} · {len(layer.records)} 条 · "
            f"{layer.coordinate_system} 坐标系 · 原始单位 {layer.unit or '未声明'}"
            + (" · 插件自定义字段" if not layer.known else "")
        )
        self.metadata.setToolTip(f"字段 ID：{layer.identifier}\n不进行平滑、单位换算或未知位置推断。复制保留原始数值精度。")

    def copy_selection(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:
            return
        columns = range(self.model.columnCount())
        lines = ["\t".join("实体 ID" if column == 0 else self.model.headerData(column, Qt.Orientation.Horizontal) for column in columns)]
        for row in rows:
            values = [self.model.data(self.model.index(row, column), Qt.ItemDataRole.UserRole) for column in columns]
            lines.append("\t".join("" if value is None else str(value) for value in values))
        QApplication.clipboard().setText("\n".join(lines))
