"""Validated table editing with spreadsheet selection and atomic undo.

The table owns only its rows and selection.  Its optional shared undo stack never
captures the surrounding workbench, so replay cannot overwrite unrelated input.
"""

from __future__ import annotations

import copy
import csv
import io
import re

from shiboken6 import isValid

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ifem.domain.analysis import InputValidationError
from ifem.domain.project import new_entity_id


class _TableEditCommand(QUndoCommand):
    def __init__(self, editor, before, after, text):
        super().__init__(f"{editor.title} · {text}")
        self.editor = editor
        self.before = before
        self.after = after
        self.operation = text
        self.first_redo = True

    def undo(self):
        self.editor._restore_state(self.before)
        self.editor._show_status(f"已撤销：{self.operation}")

    def redo(self):
        self.editor._restore_state(self.after)
        if not self.first_redo:
            self.editor._show_status(f"已重做：{self.operation}")
        self.first_redo = False


class EditableTable(QWidget):
    ENTITY_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    MAX_ROWS = 10_000
    MAX_CELLS = 100_000
    MAX_CLIPBOARD_BYTES = 2 * 1024 * 1024

    def __init__(
        self,
        title,
        field_specs,
        parent=None,
        on_change=None,
        description="",
        form_columns=2,
        stretch_columns=True,
        table_columns=None,
        form_sections=None,
        table_min_height=210,
        record_noun="条记录",
        header_action=None,
        *,
        undo_stack=None,
        validate_rows=None,
        can_mutate=None,
        entity_prefix="",
    ):
        super().__init__(parent)
        self.title = title
        self.field_specs = field_specs
        self.inputs = {}
        self.on_change = on_change
        self.validate_rows = validate_rows
        self.can_mutate = can_mutate
        self.entity_prefix = entity_prefix
        self.form_columns = max(1, int(form_columns))
        self.record_noun = record_noun
        self._restoring = False
        self._status_message = "拖选单元格可复制、粘贴和填充；未选中时粘贴为追加。"
        self._status_error = False
        self._default_visible_keys = set(
            table_columns or [spec["key"] for spec in field_specs]
        )
        self.undo_stack = undo_stack if undo_stack is not None else QUndoStack(self)
        self.history = self.undo_stack
        if undo_stack is None:
            self.history.setUndoLimit(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        group = QGroupBox(title)
        layout.addWidget(group)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 14, 12, 12)
        group_layout.setSpacing(10)
        meta_bar = QHBoxLayout()
        self.meta_bar = meta_bar
        if description:
            label = QLabel(description)
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            meta_bar.addWidget(label, 1)
        else:
            meta_bar.addStretch(1)
        self.count_label = QLabel("0 条记录")
        self.count_label.setObjectName("recordBadge")
        meta_bar.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignTop)
        if header_action:
            action_text, action_callback = header_action
            self.header_action_button = QPushButton(action_text)
            self.header_action_button.setObjectName("modelerButton")
            self.header_action_button.setToolTip("进入交互建模器，在梁模型表面布置和调整测点")
            self.header_action_button.clicked.connect(action_callback)
            meta_bar.addWidget(self.header_action_button, 0, Qt.AlignmentFlag.AlignTop)
        group_layout.addLayout(meta_bar)

        self.table = QTableWidget(0, len(field_specs))
        self.table.setAccessibleName(f"{title}数据表")
        self.table.setAccessibleDescription("选择矩形单元格区域进行复制、粘贴或向下填充；选中一行后可在下方编辑。")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(table_min_height)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setHorizontalHeaderLabels(
            [spec.get("table_label", spec["label"]) for spec in field_specs]
        )
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(76)
        # Stretch respects minimum section widths and yields a real horizontal
        # scrollbar when all fields cannot fit in a narrow workbench pane.
        for column, spec in enumerate(field_specs):
            self.table.setColumnHidden(column, spec["key"] not in self._default_visible_keys)
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch if stretch_columns
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        if not stretch_columns:
            header.setStretchLastSection(False)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self._build_table_actions(group_layout)
        group_layout.addWidget(self.table)

        self.status_label = QLabel(self._status_message)
        self.status_label.setObjectName("tableEditStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName(f"{title}编辑反馈")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        group_layout.addWidget(self.status_label)
        self._status_reveal_timer = QTimer(self)
        self._status_reveal_timer.setSingleShot(True)
        self._status_reveal_timer.timeout.connect(self._reveal_status)

        if form_sections:
            self.editor_tabs = QTabWidget()
            self.editor_tabs.setObjectName("editorTabs")
            specs_by_key = {spec["key"]: spec for spec in self.field_specs}
            for section_title, section_keys in form_sections:
                self.editor_tabs.addTab(
                    self._build_form([specs_by_key[key] for key in section_keys]),
                    section_title,
                )
            group_layout.addWidget(self.editor_tabs)
        else:
            group_layout.addWidget(self._build_form(self.field_specs))

        button_bar = QHBoxLayout()
        self.add_button = QPushButton("新增")
        self.update_button = QPushButton("更新选中")
        self.delete_button = QPushButton("删除选中")
        self.clear_button = QPushButton("清空全部")
        self.add_button.setObjectName("smallPrimaryButton")
        self.delete_button.setObjectName("dangerButton")
        self.clear_button.setObjectName("dangerGhostButton")
        self.add_button.setToolTip("校验后将填写的数据加入表格，可撤销")
        self.update_button.setToolTip("用下方表单更新单行；多行批量修改请使用粘贴或填充")
        self.delete_button.setToolTip("删除选中单元格所在的全部行，可一次撤销")
        self.clear_button.setToolTip("确认后清空当前表格，可撤销")
        self.add_button.clicked.connect(self.add_row)
        self.update_button.clicked.connect(self.update_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.clear_button.clicked.connect(self.confirm_clear_rows)
        for button in (self.add_button, self.update_button, self.delete_button, self.clear_button):
            button_bar.addWidget(button)
        button_bar.addStretch(1)
        group_layout.addLayout(button_bar)
        self.history.indexChanged.connect(self.refresh_actions)
        self.history.canUndoChanged.connect(self.refresh_actions)
        self.history.canRedoChanged.connect(self.refresh_actions)
        self._update_count()
        self.refresh_actions()

    def _build_table_actions(self, layout):
        self.copy_action = self._action("复制", self.copy_selected, QKeySequence.StandardKey.Copy)
        self.paste_action = self._action("粘贴", self.paste_text, QKeySequence.StandardKey.Paste)
        self.fill_down_action = self._action("向下填充", self.fill_down, QKeySequence("Ctrl+D"))
        self.undo_action = self._action("撤销", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self._action("重做", self.redo, QKeySequence.StandardKey.Redo)
        self.delete_action = self._action("删除选中行", self.delete_selected, QKeySequence("Delete"))
        self.select_all_action = self._action("全选", self.table.selectAll, QKeySequence.StandardKey.SelectAll)
        self.clear_action = self._action("清空全部", self.confirm_clear_rows)
        self.copy_action.setToolTip("复制所选矩形区域的原始字段值，不包含行 ID")
        self.paste_action.setToolTip("粘贴制表符分隔的数据；空选区追加，单个值填满所选区域")
        self.fill_down_action.setToolTip("将选区第一行的各列值向下填充，整批可撤销")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.copy_button = self._tool_button(self.copy_action)
        self.paste_button = self._tool_button(self.paste_action)
        self.undo_button = self._tool_button(self.undo_action)
        self.redo_button = self._tool_button(self.redo_action)
        for button in (self.copy_button, self.paste_button, self.undo_button, self.redo_button):
            toolbar.addWidget(button)
        self.more_button = QToolButton()
        self.more_button.setObjectName("tableEditToolButton")
        self.more_button.setText("更多")
        self.more_button.setAccessibleName(f"{self.title}更多表格操作")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.addAction(self.fill_down_action)
        self.more_menu.addAction(self.select_all_action)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.delete_action)
        self.more_menu.addAction(self.clear_action)
        self.more_button.setMenu(self.more_menu)
        toolbar.addWidget(self.more_button)
        toolbar.addStretch(1)
        self.all_fields_checkbox = QCheckBox("全部字段")
        self.all_fields_checkbox.setAccessibleName(f"{self.title}显示全部字段")
        self.all_fields_checkbox.setToolTip("显示隐藏的辅助与积分字段，便于整行复制或粘贴；不改变任何数据")
        self.all_fields_checkbox.setVisible(len(self._default_visible_keys) < len(self.field_specs))
        self.all_fields_checkbox.toggled.connect(self.set_all_fields_visible)
        self.meta_bar.insertWidget(0, self.all_fields_checkbox)
        layout.addLayout(toolbar)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

    def _action(self, text, callback, shortcut=None):
        action = QAction(text, self.table)
        if shortcut is not None:
            if isinstance(shortcut, QKeySequence.StandardKey):
                action.setShortcuts(QKeySequence.keyBindings(shortcut))
            else:
                action.setShortcut(shortcut)
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        # QAction.triggered passes a boolean; it must never become clipboard text.
        action.triggered.connect(lambda checked=False: callback())
        self.table.addAction(action)
        return action

    @staticmethod
    def _tool_button(action):
        button = QToolButton()
        button.setObjectName("tableEditToolButton")
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setAutoRaise(False)
        return button

    def _show_context_menu(self, position):
        self.refresh_actions()
        menu = QMenu(self.table)
        for action in (self.copy_action, self.paste_action, self.fill_down_action):
            menu.addAction(action)
        menu.addSeparator()
        for action in (self.undo_action, self.redo_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.select_all_action)
        menu.addAction(self.delete_action)
        menu.exec(self.table.viewport().mapToGlobal(position))
        menu.deleteLater()

    def set_all_fields_visible(self, visible):
        with QSignalBlocker(self.all_fields_checkbox):
            self.all_fields_checkbox.setChecked(bool(visible))
        for column, spec in enumerate(self.field_specs):
            self.table.setColumnHidden(column, not visible and spec["key"] not in self._default_visible_keys)
        self.table.horizontalHeader().setMinimumSectionSize(88 if visible else 76)
        self.refresh_actions()

    def _build_form(self, specs):
        form = QWidget()
        form.setObjectName("editorForm")
        layout = QGridLayout(form)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)
        for index, spec in enumerate(specs):
            row, column = index // self.form_columns, (index % self.form_columns) * 2
            label = QLabel(spec["label"])
            label.setObjectName("fieldLabel")
            widget = self._create_input(spec)
            label.setBuddy(widget)
            widget.setAccessibleName(spec["label"])
            widget.setMinimumWidth(0)
            self.inputs[spec["key"]] = widget
            layout.addWidget(label, row, column)
            layout.addWidget(widget, row, column + 1)
            layout.setColumnStretch(column + 1, 1)
        return form

    def _create_input(self, spec):
        if spec.get("choices"):
            widget = QComboBox()
            widget.addItems(spec["choices"])
            widget.setEditable(False)
        else:
            widget = QLineEdit()
            widget.setClearButtonEnabled(True)
            widget.setPlaceholderText(spec.get("placeholder", ""))
        if spec.get("tooltip"):
            widget.setToolTip(spec["tooltip"])
        return widget

    @staticmethod
    def _get_widget_value(widget):
        return (widget.currentText() if isinstance(widget, QComboBox) else widget.text()).strip()

    @staticmethod
    def _set_widget_value(widget, value):
        text = "" if value is None else str(value)
        if isinstance(widget, QComboBox):
            index = widget.findText(text)
            if index >= 0:
                widget.setCurrentIndex(index)
            elif text:
                # Loaded files may contain an older alias or unsupported value.
                # Display it faithfully instead of silently showing another enum.
                widget.addItem(text)
                widget.setCurrentIndex(widget.count() - 1)
        else:
            widget.setText(text)

    def _table_item(self, spec, value):
        raw_value = "" if value is None else str(value)
        item = QTableWidgetItem(spec.get("table_display", {}).get(raw_value, raw_value))
        item.setData(Qt.ItemDataRole.UserRole, raw_value)
        alignment = spec.get("table_align")
        if alignment == "right":
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif alignment == "center":
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @staticmethod
    def _table_item_value(item):
        if item is None:
            return ""
        raw_value = item.data(Qt.ItemDataRole.UserRole)
        return item.text() if raw_value is None else str(raw_value)

    def _row_entity_id(self, row):
        item = self.table.item(row, 0)
        return str(item.data(self.ENTITY_ID_ROLE) or "") if item is not None else ""

    def _set_row_entity_id(self, row, entity_id):
        item = self.table.item(row, 0)
        if item is not None:
            item.setData(self.ENTITY_ID_ROLE, str(entity_id) if entity_id else None)

    def set_row_entity_ids(self, entity_ids):
        if len(entity_ids) != self.table.rowCount():
            raise ValueError(f"{self.title}行数与实体 ID 数量不一致。")
        for row, entity_id in enumerate(entity_ids):
            self._set_row_entity_id(row, entity_id)

    def get_form_values(self):
        return {spec["key"]: self._get_widget_value(self.inputs[spec["key"]]) for spec in self.field_specs}

    def set_form_values(self, values):
        for spec in self.field_specs:
            self._set_widget_value(self.inputs[spec["key"]], values.get(spec["key"], ""))

    def clear_form(self):
        self.set_form_values({})

    def get_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            payload = {
                spec["key"]: self._table_item_value(self.table.item(row, column))
                for column, spec in enumerate(self.field_specs)
            }
            entity_id = self._row_entity_id(row)
            if entity_id:
                payload["_entity_id"] = entity_id
            rows.append(payload)
        return rows

    def _normalize_rows(self, rows):
        normalized = []
        for row in rows:
            payload = {
                spec["key"]: "" if row.get(spec["key"]) is None else str(row.get(spec["key"], ""))
                for spec in self.field_specs
            }
            if row.get("_entity_id"):
                payload["_entity_id"] = str(row["_entity_id"])
            normalized.append(payload)
        return normalized

    def _selection_state(self):
        return {
            "cells": [(index.row(), index.column()) for index in self.table.selectedIndexes()],
            "current": (self.table.currentRow(), self.table.currentColumn()),
        }

    def _snapshot(self):
        return {"rows": self.get_rows(), "selection": self._selection_state()}

    def _restore_state(self, state):
        self._restoring = True
        self.table.setUpdatesEnabled(False)
        try:
            with QSignalBlocker(self.table):
                self.table.setRowCount(0)
                self.table.setRowCount(len(state["rows"]))
                for row, payload in enumerate(state["rows"]):
                    for column, spec in enumerate(self.field_specs):
                        self.table.setItem(row, column, self._table_item(spec, payload.get(spec["key"], "")))
                    self._set_row_entity_id(row, payload.get("_entity_id", ""))
                self._restore_selection(state["selection"])
        finally:
            self.table.setUpdatesEnabled(True)
            self._restoring = False
        self.on_selection_changed()
        self._update_count()
        self.refresh_actions()
        self._emit_change()

    def _restore_selection(self, selection):
        model = self.table.selectionModel()
        model.clearSelection()
        indexes = self.table.model()
        selected = QItemSelection()
        # Coalesce adjacent cells and identical row spans. A 10000 × 8 paste
        # restores a few ranges instead of 80000 individual Qt selections.
        by_row = {}
        for row, column in selection["cells"]:
            if 0 <= row < self.table.rowCount() and 0 <= column < self.table.columnCount():
                by_row.setdefault(row, set()).add(column)
        ranges = []
        for row in sorted(by_row):
            columns = sorted(by_row[row])
            spans = []
            first = last = columns[0]
            for column in columns[1:]:
                if column == last + 1:
                    last = column
                else:
                    spans.append((first, last))
                    first = last = column
            spans.append((first, last))
            if ranges and ranges[-1][1] == row - 1 and ranges[-1][2] == spans:
                ranges[-1] = (ranges[-1][0], row, spans)
            else:
                ranges.append((row, row, spans))
        for top, bottom, spans in ranges:
            for left, right in spans:
                selected.select(indexes.index(top, left), indexes.index(bottom, right))
        model.select(selected, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        row, column = selection["current"]
        index = indexes.index(row, column)
        model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def set_rows(self, rows):
        """Load rows at a project boundary, clearing history without a command."""
        self.history.clear()
        self._restore_state({"rows": self._normalize_rows(rows), "selection": {"cells": [], "current": (-1, -1)}})
        self.clear_form()
        self._show_status("拖选单元格可复制、粘贴和填充；未选中时粘贴为追加。")

    def _allowed(self):
        return not callable(self.can_mutate) or bool(self.can_mutate())

    def _check_mutation(self):
        if self._allowed():
            return True
        self._show_status("当前表格暂不可修改，请先结束计算或解决项目/方法恢复问题。", error=True)
        self.refresh_actions()
        return False

    def _commit_rows(self, rows, text, *, selection=None, new_rows=(), focus_form=False):
        if not self._check_mutation():
            return False
        rows = self._normalize_rows(rows)
        try:
            if len(rows) > self.MAX_ROWS or len(rows) * len(self.field_specs) > self.MAX_CELLS:
                raise InputValidationError("操作后表格超过 10000 行或 100000 个单元格，请分成较小的数据集。")
            if callable(self.validate_rows):
                # A validator is read-only by contract; isolate candidate data even
                # from an accidental in-place normalization in external code.
                self.validate_rows(copy.deepcopy(rows))
            for index, row in enumerate(rows):
                for spec in self.field_specs:
                    choices = spec.get("choices")
                    value = row[spec["key"]]
                    if choices and value.strip().casefold() not in {
                        str(choice).strip().casefold() for choice in choices
                    }:
                        raise InputValidationError(
                            f"第 {index + 1} 行的{spec['label']}“{value}”不是支持的选项，请使用下拉框中的值。",
                            field=f"/rows/{index}/{spec['key']}",
                        )
        except (InputValidationError, ValueError) as error:
            self._show_status(f"未更改表格：{error}", error=True, reveal=not focus_form)
            if focus_form:
                self._focus_form_issue(str(error), getattr(error, "field", None))
            return False
        before = self._snapshot()
        if rows == before["rows"]:
            self._show_status("数据未变化，无需新增撤销记录。")
            return True
        # Allocate IDs only after all validation, once per successful insertion.
        for row in new_rows:
            if self.entity_prefix and not rows[row].get("_entity_id"):
                rows[row]["_entity_id"] = new_entity_id(self.entity_prefix)
        after = {"rows": rows, "selection": selection or before["selection"]}
        self.history.push(_TableEditCommand(self, before, after, text))
        self._show_status(f"已{text}；可撤销。")
        self.refresh_actions()
        return True

    def add_row(self):
        rows = self.get_rows()
        index = len(rows)
        rows.append(self.get_form_values())
        if self._commit_rows(rows, "新增 1 行", new_rows=(index,), focus_form=True):
            self.clear_form()
            return True
        return False

    def update_selected(self):
        selected = self._selected_rows()
        if len(selected) != 1:
            self._show_status("请选择一行后更新；修改多行请使用粘贴或向下填充。", error=True)
            return False
        row = selected[0]
        rows = self.get_rows()
        values = self.get_form_values()
        if rows[row].get("_entity_id"):
            values["_entity_id"] = rows[row]["_entity_id"]
        rows[row] = values
        return self._commit_rows(rows, "更新 1 行", focus_form=True)

    def delete_selected(self):
        selected = self._selected_rows()
        if not selected:
            self._show_status("请先选择要删除的行；同一行选中多个单元格只删除一次。", error=True)
            return False
        delete_rows = set(selected)
        rows = [row for index, row in enumerate(self.get_rows()) if index not in delete_rows]
        selection = {"cells": [], "current": (-1, -1)}
        if rows:
            row = min(selected[0], len(rows) - 1)
            columns = self._visible_columns()
            selection = {"cells": [(row, col) for col in columns], "current": (row, columns[0])}
        return self._commit_rows(rows, f"删除 {len(selected)} 行", selection=selection)

    def clear_rows(self):
        success = self._commit_rows([], "清空全部记录", selection={"cells": [], "current": (-1, -1)})
        if success:
            self.clear_form()
        return success

    def confirm_clear_rows(self):
        if not self.table.rowCount() or not self._check_mutation():
            return False
        answer = QMessageBox.question(
            self, f"清空{self.title}",
            f"确定清空全部 {self.table.rowCount()} 行记录吗？清空后可以撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return self.clear_rows() if answer == QMessageBox.StandardButton.Yes else False

    def _visible_columns(self):
        header = self.table.horizontalHeader()
        return sorted(
            (column for column in range(self.table.columnCount()) if not self.table.isColumnHidden(column)),
            key=header.visualIndex,
        )

    def _selected_cells(self):
        return {
            (index.row(), index.column()) for index in self.table.selectedIndexes()
            if not self.table.isColumnHidden(index.column())
        }

    def _selected_rows(self):
        return sorted({row for row, _column in self._selected_cells()})

    def _selection_rectangle(self):
        cells = self._selected_cells()
        if not cells:
            return None
        visible = self._visible_columns()
        positions = {column: index for index, column in enumerate(visible)}
        rows = sorted({row for row, _column in cells})
        columns = sorted({positions[column] for _row, column in cells})
        height, width = rows[-1] - rows[0] + 1, columns[-1] - columns[0] + 1
        if len(cells) != height * width:
            raise InputValidationError("请选择一个连续的矩形区域；不支持分散或不规则选区。")
        return rows[0], rows[-1], columns[0], columns[-1]

    def _parse_tsv(self, text):
        if not isinstance(text, str) or not text:
            raise InputValidationError("剪贴板没有可粘贴的文本。")
        if len(text.encode("utf-8")) > self.MAX_CLIPBOARD_BYTES:
            raise InputValidationError("粘贴内容超过 2 MB，请分批粘贴。")
        old_limit = csv.field_size_limit()
        try:
            csv.field_size_limit(self.MAX_CLIPBOARD_BYTES)
            reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True)
            rows = []
            width = None
            for record in reader:
                record = record or [""]
                width = len(record) if width is None else width
                if len(record) != width:
                    raise InputValidationError("粘贴数据每行列数必须一致；请保留空字段的制表符。")
                rows.append(record)
                if len(rows) > self.MAX_ROWS or len(rows) * width > self.MAX_CELLS:
                    raise InputValidationError("单次粘贴最多 10000 行、100000 个单元格，请分批粘贴。")
            if not rows:
                raise InputValidationError("剪贴板没有可粘贴的文本。")
            return rows
        except csv.Error as error:
            raise InputValidationError(f"制表符文本格式不完整，请检查成对的引号：{error}") from error
        finally:
            csv.field_size_limit(old_limit)

    def copy_selected(self):
        try:
            rectangle = self._selection_rectangle()
            if rectangle is None:
                raise InputValidationError("请先选择要复制的矩形单元格区域。")
            top, bottom, left, right = rectangle
            if (bottom - top + 1) * (right - left + 1) > self.MAX_CELLS or bottom - top + 1 > self.MAX_ROWS:
                raise InputValidationError("复制区域过大，请分批复制。")
            visible = self._visible_columns()[left:right + 1]
            output = io.StringIO(newline="")
            writer = csv.writer(output, delimiter="\t", lineterminator="\r\n")
            for row in range(top, bottom + 1):
                writer.writerow([self._table_item_value(self.table.item(row, column)) for column in visible])
            text = output.getvalue()
            if len(text.encode("utf-8")) > self.MAX_CLIPBOARD_BYTES:
                raise InputValidationError("复制内容超过 2 MB，请选择较小区域。")
        except InputValidationError as error:
            self._show_status(str(error), error=True)
            return ""
        QApplication.clipboard().setText(text)
        self._show_status(f"已复制 {bottom - top + 1} 行 × {right - left + 1} 列原始值。")
        return text

    def paste_text(self, text=None):
        if not self._check_mutation():
            return False
        try:
            values = self._parse_tsv(QApplication.clipboard().text() if text is None else text)
            rectangle = self._selection_rectangle()
            visible = self._visible_columns()
            if not visible:
                raise InputValidationError("没有可粘贴的可见字段，请先显示字段。")
            rows = self.get_rows()
            height, width = len(values), len(values[0])
            if rectangle is None:
                top, left = len(rows), 0
            else:
                top, bottom, left, right = rectangle
                selected_height, selected_width = bottom - top + 1, right - left + 1
                if height == width == 1:
                    height, width = selected_height, selected_width
                    values = [[values[0][0]] * width for _ in range(height)]
                elif selected_height * selected_width > 1 and (height, width) != (selected_height, selected_width):
                    raise InputValidationError("粘贴数据与所选区域尺寸不一致；请选择单个起始单元格，或选择相同大小的区域。")
            if left + width > len(visible):
                raise InputValidationError("粘贴列数超出可见字段，未更改任何数据；需要辅助字段时请开启“全部字段”。")
            if top + height > self.MAX_ROWS or (top + height) * len(self.field_specs) > self.MAX_CELLS:
                raise InputValidationError("粘贴后超过 10000 行或 100000 个单元格，请减少数据量。")
            original_count = len(rows)
            while len(rows) < top + height:
                rows.append({spec["key"]: "" for spec in self.field_specs})
            selected_cells = []
            for row_offset, record in enumerate(values):
                for column_offset, value in enumerate(record):
                    column = visible[left + column_offset]
                    rows[top + row_offset][self.field_specs[column]["key"]] = value
                    selected_cells.append((top + row_offset, column))
            selection = {"cells": selected_cells, "current": (top, visible[left])}
        except InputValidationError as error:
            self._show_status(f"未更改表格：{error}", error=True)
            return False
        return self._commit_rows(
            rows, f"粘贴 {height} 行 × {width} 列", selection=selection,
            new_rows=range(original_count, len(rows)),
        )

    def fill_down(self):
        if not self._check_mutation():
            return False
        try:
            rectangle = self._selection_rectangle()
            if rectangle is None or rectangle[1] == rectangle[0]:
                raise InputValidationError("请选择至少两行的矩形区域，第一行作为向下填充的来源。")
            top, bottom, left, right = rectangle
            visible = self._visible_columns()[left:right + 1]
            rows = self.get_rows()
            for row in range(top + 1, bottom + 1):
                for column in visible:
                    key = self.field_specs[column]["key"]
                    rows[row][key] = rows[top][key]
        except InputValidationError as error:
            self._show_status(f"未更改表格：{error}", error=True)
            return False
        return self._commit_rows(rows, f"向下填充 {bottom - top} 行 × {right - left + 1} 列")

    def _history_command(self, redo=False):
        if not isValid(self.history):
            return None
        index = self.history.index() if redo else self.history.index() - 1
        return self.history.command(index) if 0 <= index < self.history.count() else None

    def _history_allowed(self, redo=False):
        command = self._history_command(redo)
        if command is None or not self._allowed():
            return False
        owner = getattr(command, "editor", None)
        return owner is None or (isValid(owner) and owner._allowed())

    def undo(self):
        if not self._history_allowed():
            self._show_status("没有可撤销的操作，或该操作所属表格暂不可修改。", error=True)
            return False
        command = self._history_command()
        self.history.undo()
        if getattr(command, "editor", self) is not self:
            self._show_status(f"已撤销 {command.text()}", reveal=True)
        return True

    def redo(self):
        if not self._history_allowed(redo=True):
            self._show_status("没有可重做的操作，或该操作所属表格暂不可修改。", error=True)
            return False
        command = self._history_command(redo=True)
        self.history.redo()
        if getattr(command, "editor", self) is not self:
            self._show_status(f"已重做 {command.text()}", reveal=True)
        return True

    def on_selection_changed(self):
        if self._restoring:
            return
        selected = self._selected_rows()
        if len(selected) == 1:
            row = selected[0]
            self.set_form_values({
                spec["key"]: self._table_item_value(self.table.item(row, column))
                for column, spec in enumerate(self.field_specs)
            })
        self.refresh_actions()

    def refresh_actions(self, *_args):
        if (
            not hasattr(self, "clear_button")
            or not isValid(self)
            or not isValid(self.table)
            or not isValid(self.history)
            or not isValid(self.clear_button)
        ):
            return
        allowed = self._allowed()
        selected_rows = self._selected_rows()
        try:
            rectangle = self._selection_rectangle()
        except InputValidationError:
            rectangle = None
        self.copy_action.setEnabled(rectangle is not None)
        self.paste_action.setEnabled(allowed)
        self.fill_down_action.setEnabled(allowed and rectangle is not None and rectangle[1] > rectangle[0])
        self.add_button.setEnabled(allowed)
        for widget in self.inputs.values():
            widget.setEnabled(allowed)
        self.update_button.setEnabled(allowed and len(selected_rows) == 1)
        self.delete_button.setEnabled(allowed and bool(selected_rows))
        self.clear_button.setEnabled(allowed and bool(self.table.rowCount()))
        self.delete_action.setEnabled(self.delete_button.isEnabled())
        self.clear_action.setEnabled(self.clear_button.isEnabled())
        self.select_all_action.setEnabled(bool(self.table.rowCount()))
        self.undo_action.setEnabled(self._history_allowed())
        self.redo_action.setEnabled(self._history_allowed(redo=True))
        self.undo_action.setToolTip(f"撤销：{self.history.undoText()}" if self.history.canUndo() else "暂无可撤销的表格操作")
        self.redo_action.setToolTip(f"重做：{self.history.redoText()}" if self.history.canRedo() else "暂无可重做的表格操作")
        if len(selected_rows) > 1:
            self.update_button.setText("多行请用粘贴")
        else:
            self.update_button.setText("更新选中")
        if hasattr(self, "status_label"):
            self._render_status()

    def _show_status(self, message, *, error=False, reveal=None):
        self._status_message = str(message)
        self._status_error = error
        self._render_status()
        # Let wrapping and theme changes settle before scrolling. The owned
        # timer is destroyed with the editor, so no late callback can outlive it.
        self._status_reveal_timer.stop()
        should_reveal = error if reveal is None else reveal
        if should_reveal:
            self._status_reveal_timer.start(20)

    def _reveal_status(self):
        if not self.isVisible():
            return
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                ancestor.ensureWidgetVisible(self.status_label, 0, 8)
                return
            ancestor = ancestor.parentWidget()

    def _render_status(self):
        selected = self._selected_cells()
        prefix = f"已选 {len({row for row, _ in selected})} 行 / {len(selected)} 格 · " if selected else ""
        message = self._status_message if self._allowed() else "只读：当前计算或项目状态不允许编辑；仍可选择并复制数据。"
        self.status_label.setText(prefix + message)
        state = "error" if self._status_error else ""
        if self.status_label.property("validationState") != state:
            self.status_label.setProperty("validationState", state)
            style = self.status_label.style()
            style.unpolish(self.status_label)
            style.polish(self.status_label)
            self.status_label.update()
        self.status_label.setAccessibleDescription("错误：" + self._status_message if self._status_error else self._status_message)

    def _update_count(self):
        self.count_label.setText(f"{self.table.rowCount()} {self.record_noun}")

    def set_validation_state(self, state="", message=""):
        self.count_label.setProperty("state", state)
        self.count_label.setToolTip(message or f"{self.title}状态")
        style = self.count_label.style()
        style.unpolish(self.count_label)
        style.polish(self.count_label)
        self.count_label.update()

    def _focus_form_issue(self, message="", field_path=None):
        parts = [part for part in str(field_path or "").strip("/").split("/") if part]
        key = self._field_key_from_path(parts[2:]) if len(parts) >= 3 else None
        self._focus_form_field(self._issue_field_key(str(message), key))

    def _issue_field_key(self, text, key=None):
        if key in self.inputs:
            return key
        terms = (
            ("局部积分起点", "zone_a"), ("局部积分终点", "zone_b"),
            ("量长起点", "zone_a"), ("量长终点", "zone_b"),
            ("单元号", "element"), ("节点号", "node"), ("自由度", "dof"),
            ("约束值", "value"), ("截面 y", "y"), ("surface", "surface"),
            ("应变", "strain"), ("权重", "weight"), ("的 u", "u"),
            ("的 v", "v"), ("的 x", "x"),
        )
        return next((field for term, field in terms if term in text and field in self.inputs), next(iter(self.inputs), None))

    def _focus_form_field(self, key):
        target = self.inputs.get(key)
        if target is None:
            self.table.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if hasattr(self, "editor_tabs"):
            index = self.editor_tabs.indexOf(target.parentWidget())
            if index >= 0:
                self.editor_tabs.setCurrentIndex(index)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        if isinstance(target, QLineEdit):
            target.selectAll()

    def focus_validation_issue(self, message="", *, field_path=None):
        """Reveal a stored-data problem (not used for rejected clipboard drafts)."""
        text = str(message or "")
        parts = [part for part in str(field_path or "").strip("/").split("/") if part]
        row, key = -1, None
        if len(parts) >= 2:
            token = parts[1].replace("~1", "/").replace("~0", "~")
            if token.isdigit():
                row = int(token)
            else:
                for candidate, payload in enumerate(self.get_rows()):
                    if str(payload.get("_entity_id", "")) == token:
                        row = candidate
                        break
            key = self._field_key_from_path(parts[2:])
        if row < 0:
            match = re.search(r"第\s*(\d+)\s*(?:条|个)", text)
            row = int(match.group(1)) - 1 if match else self.table.currentRow()
        if not 0 <= row < self.table.rowCount():
            row = 0 if self.table.rowCount() else -1
        if row >= 0:
            self.table.selectRow(row)
            self.on_selection_changed()
        self._focus_form_field(self._issue_field_key(text, key))

    @staticmethod
    def _field_key_from_path(tail):
        if not tail:
            return None
        key = tail[0].replace("~1", "/").replace("~0", "~")
        direct = {
            "element": "element", "x": "x", "surface": "surface", "y": "y",
            "strain": "strain", "measured_value": "strain", "weight": "weight",
            "zone_a": "zone_a", "zone_b": "zone_b", "node": "node", "node_id": "node",
            "dof": "dof", "value": "value", "label": "label", "u": "u", "v": "v",
        }
        if key in direct:
            return direct[key]
        if key != "attachment" or len(tail) < 2:
            return None
        if tail[1] == "local_coordinates":
            return "x"
        if tail[1] in {"surface_side", "surface_angle_degrees"}:
            return "surface"
        if tail[1] == "integration_bounds":
            return "zone_b" if len(tail) >= 3 and tail[2] == "1" else "zone_a"
        return None

    def _emit_change(self):
        if callable(self.on_change):
            self.on_change()
