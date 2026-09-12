"""Shared navigation and discovery controls for the desktop workspaces."""

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QFrame, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QSizePolicy, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ifem.ui.theme import application_stylesheet, resolve_theme


def line_icon(name, color, size=20):
    """Draw a small, consistent set of resolution-independent tool glyphs."""
    paths = {
        "model": [(4, 17, 4, 6, 12, 2, 20, 6, 20, 17, 12, 22, 4, 17),
                  (4, 6, 12, 11, 20, 6), (12, 11, 12, 22)],
        "sensors": [(3, 12, 7, 12, 10, 5, 14, 19, 17, 12, 21, 12)],
        "boundary": [(5, 4, 5, 20), (5, 7, 19, 7), (5, 17, 19, 17),
                     (1, 7, 5, 3), (1, 13, 5, 9), (1, 19, 5, 15)],
        "compare": [(4, 3, 4, 20, 21, 20), (7, 15, 11, 8, 15, 12, 21, 4),
                    (7, 17, 11, 12, 15, 15, 21, 9)],
        "code": [(8, 6, 2, 12, 8, 18), (16, 6, 22, 12, 16, 18), (14, 3, 10, 21)],
        "search": [(15, 15, 21, 21)],
        "plus": [(12, 5, 12, 19), (5, 12, 19, 12)],
        "open": [(3, 19, 3, 5, 10, 5, 12, 8, 21, 8, 21, 19, 3, 19),
                 (3, 11, 21, 11)],
        "save": [(4, 3, 17, 3, 21, 7, 21, 21, 3, 21, 3, 3, 4, 3),
                 (7, 3, 7, 9, 17, 9, 17, 3), (7, 21, 7, 14, 17, 14, 17, 21)],
        "play": [(8, 4, 20, 12, 8, 20, 8, 4)],
        "focus": [(3, 9, 3, 3, 9, 3), (15, 3, 21, 3, 21, 9),
                  (3, 15, 3, 21, 9, 21), (15, 21, 21, 21, 21, 15)],
        "table": [(3, 4, 21, 4, 21, 20, 3, 20, 3, 4),
                  (3, 9, 21, 9), (3, 14, 21, 14), (10, 4, 10, 20)],
        "settings": [(4, 6, 20, 6), (4, 12, 20, 12), (4, 18, 20, 18),
                     (9, 3, 9, 9), (16, 9, 16, 15), (8, 15, 8, 21)],
        "select": [(5, 3, 6, 20, 11, 15, 17, 21, 20, 18, 14, 12, 21, 10, 5, 3)],
        "undo": [(9, 4, 3, 10, 9, 16), (3, 10, 15, 10, 19, 13, 19, 19)],
        "redo": [(15, 4, 21, 10, 15, 16), (21, 10, 9, 10, 5, 13, 5, 19)],
    }
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.65)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    for points in paths.get(name, paths["model"]):
        path = QPainterPath(QPointF(points[0], points[1]))
        for index in range(2, len(points), 2):
            path.lineTo(points[index], points[index + 1])
        painter.drawPath(path)
    if name == "search":
        painter.drawEllipse(QPointF(10, 10), 6, 6)
    painter.end()
    return QIcon(pixmap)


class ElidingLabel(QLabel):
    """Keep full text for copying/accessibility, elide only its painted form."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)
        self.setAccessibleName(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.setAccessibleName(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, self.alignment(), text)


class WorkspaceRail(QFrame):
    page_requested = Signal(int)
    search_requested = Signal()

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setObjectName("workspaceRail")
        self.setFixedWidth(70)
        self.setAccessibleName("工作区导航")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 14, 6, 10)
        layout.setSpacing(6)
        label = QLabel("工作区")
        label.setObjectName("railCaption")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        layout.addSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        self.icons = ("model", "sensors", "boundary", "compare", "code")
        self.names = tuple(names)
        for index, name in enumerate(names):
            button = self._button(name)
            button.setCheckable(True)
            button.setToolTip(f"{name} · Alt+{index + 1}")
            button.clicked.connect(lambda _checked=False, i=index: self.page_requested.emit(i))
            self.group.addButton(button)
            self.buttons.append(button)
            layout.addWidget(button)
        self.buttons[0].setChecked(True)
        layout.addStretch(1)
        self.search_button = self._button("命令")
        self.search_button.setToolTip("搜索命令 · Ctrl+K")
        self.search_button.clicked.connect(self.search_requested)
        layout.addWidget(self.search_button)
        self.apply_theme(None)

    @staticmethod
    def _button(text):
        button = QToolButton()
        button.setObjectName("railButton")
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(21, 21))
        button.setFixedSize(58, 62)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def apply_theme(self, theme_id):
        color = resolve_theme(theme_id).color("viewport_text")
        for button, icon in zip(self.buttons, self.icons):
            button.setIcon(line_icon(icon, color, 21))
        self.search_button.setIcon(line_icon("search", color, 21))

    def set_current(self, index):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def set_issue(self, index, count, tooltip):
        button = self.buttons[index]
        button.setText(f"{self.names[index]} · {count}" if count else self.names[index])
        button.setToolTip(tooltip)
        button.setAccessibleDescription(tooltip)
        button.setProperty("hasIssue", bool(count))
        button.style().unpolish(button)
        button.style().polish(button)


@dataclass
class StudioCommand:
    title: str
    hint: str
    callback: Callable
    enabled: bool = True
    keywords: str = ""


class CommandPalette(QDialog):
    """Search real application commands, retaining disabled-state semantics."""

    def __init__(self, commands, parent=None, *, theme_id=None):
        super().__init__(parent)
        self.commands = tuple(commands)
        self.selected_command = None
        self.setObjectName("commandPalette")
        self.setWindowTitle("搜索命令")
        self.setModal(True)
        self.resize(580, 420)
        self.setStyleSheet(application_stylesheet(theme_id))
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 12)
        root.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("commandSearch")
        self.search.setPlaceholderText("搜索操作，如：测点、重构、保存…")
        self.search.setAccessibleName("搜索命令")
        root.addWidget(self.search)
        self.results = QListWidget()
        self.results.setObjectName("commandResults")
        self.results.setAccessibleName("匹配的命令")
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.results, 1)
        self.empty = QLabel("没有匹配的命令，请换一个关键词。")
        self.empty.setObjectName("sectionHint")
        root.addWidget(self.empty)
        hint = QLabel("↑ ↓ 选择    Enter 执行    Esc 返回")
        hint.setObjectName("sectionHint")
        root.addWidget(hint)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._activate_current)
        self.search.installEventFilter(self)
        self.results.itemActivated.connect(self._activate_current)
        self.results.itemClicked.connect(self._activate_current)
        self._filter("")
        self.search.setFocus()

    def _filter(self, query):
        self.results.clear()
        tokens = query.casefold().split()
        for index, command in enumerate(self.commands):
            haystack = f"{command.title} {command.hint} {command.keywords}".casefold()
            if not all(token in haystack for token in tokens):
                continue
            hint = command.hint if command.enabled else "当前不可用 · " + command.hint
            item = QListWidgetItem(f"{command.title}\n{hint}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(0, 58))
            if not command.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.results.addItem(item)
        self.empty.setVisible(self.results.count() == 0)
        for row in range(self.results.count()):
            if self.results.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.results.setCurrentRow(row)
                break

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                row = self.results.currentRow() + step
                while 0 <= row < self.results.count():
                    if self.results.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                        self.results.setCurrentRow(row)
                        break
                    row += step
                return True
        return super().eventFilter(watched, event)

    def _activate_current(self, *_args):
        item = self.results.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self.selected_command = self.commands[item.data(Qt.ItemDataRole.UserRole)]
        self.accept()


class ModelOutline(QWidget):
    entity_selected = Signal(str, str)
    entity_activated = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 10, 2, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、编号或 ID")
        self.search.setAccessibleName("搜索模型对象")
        root.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName("modelOutline")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setUniformRowHeights(True)
        self.tree.setAccessibleName("节点、梁段与测点")
        root.addWidget(self.tree, 1)
        self.hint = QLabel("选择对象定位 · 双击或 Enter 编辑属性")
        self.hint.setObjectName("sectionHint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self._items = {}
        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(self._select)
        self.tree.itemActivated.connect(self._activate)
        self.tree.installEventFilter(self)
        self.search.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if watched is self.tree and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.tree.currentItem()
                if item is not None and not item.isHidden():
                    self._activate(item, 0)
                # Do not let Enter trigger the modeler's default file button.
                return True
            if watched is self.search and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down,
            ):
                item = next((item for item in self._items.values() if not item.isHidden()), None)
                if item is not None:
                    self.tree.setCurrentItem(item)
                    self.tree.setFocus(Qt.FocusReason.OtherFocusReason)
                return True
        return super().eventFilter(watched, event)

    def set_project(self, project, selected_id=""):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        for kind, title, prefix, entities in (
            ("node", "节点", "N", project.nodes),
            ("element", "梁段", "E", project.elements),
            ("sensor", "测点", "S", project.sensors),
        ):
            group = QTreeWidgetItem(self.tree, [f"{title}  ·  {len(entities)}"])
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            group.setExpanded(kind == "element")
            for index, entity in enumerate(entities, 1):
                name = getattr(entity, "name", "") or getattr(entity, "label", "")
                if kind == "element":
                    name = {"line": "直线", "circular_arc": "圆弧", "nurbs_curve": "NURBS", "parametric_curve": "参数曲线"}.get(entity.geometry.kind, entity.geometry.kind)
                label = f"{prefix}{index}  {name}".strip()
                item = QTreeWidgetItem(group, [label])
                item.setData(0, Qt.ItemDataRole.UserRole, (kind, entity.identifier))
                item.setToolTip(0, f"{label}\n{entity.identifier}")
                self._items[entity.identifier] = item
        self.tree.blockSignals(False)
        self._filter(self.search.text())
        self.set_selected(selected_id)

    def _filter(self, query):
        query = query.casefold().strip()
        visible = 0
        for item in self._items.values():
            matches = query in item.toolTip(0).casefold()
            item.setHidden(not matches)
            visible += matches
        for row in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(row)
            group.setHidden(bool(query) and all(group.child(i).isHidden() for i in range(group.childCount())))
            if query:
                group.setExpanded(True)
        self.hint.setText("没有匹配对象，请修改搜索词。" if query and not visible else "选择对象定位 · 双击或 Enter 编辑属性")

    def set_selected(self, identifier):
        self.tree.blockSignals(True)
        item = self._items.get(identifier)
        self.tree.setCurrentItem(item)
        if item is not None and not item.isHidden():
            item.parent().setExpanded(True)
        self.tree.blockSignals(False)

    def _select(self, item, _previous):
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if data:
            self.entity_selected.emit(*data)

    def _activate(self, item, _column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.entity_activated.emit(*data)
