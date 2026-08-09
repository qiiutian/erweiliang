"""Application-level project naming and project-library dialogs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ifem.infrastructure.project_library import ProjectLibrary
from ifem.ui.theme import compose_stylesheet, current_theme_id, resolve_theme


PROJECT_LIBRARY_STYLESHEET = """
QDialog#projectLibraryDialog, QDialog#projectNameDialog {
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei";
}
QLabel#projectDialogTitle {
    font-size: 22px;
    font-weight: 700;
}
QLabel#projectDialogHint, QLabel#projectLibraryMeta,
QLabel#projectNameStatus {
    font-size: 11px;
}
QFrame#projectLocationBar {
    border: 1px solid;
    border-radius: 9px;
}
QLineEdit#projectLibraryPath {
    min-height: 30px;
    border: none;
    background: transparent;
}
QLineEdit#projectSearch {
    min-height: 34px;
}
QTreeWidget#projectLibraryList {
    border: 1px solid;
    border-radius: 10px;
    outline: none;
}
QTreeWidget#projectLibraryList::item {
    min-height: 42px;
    padding: 3px 6px;
}
QLabel#projectEmptyState {
    font-size: 14px;
    font-weight: 600;
}
QLineEdit#projectNameEdit {
    min-height: 38px;
    font-size: 14px;
}
QLineEdit#projectNameEdit[validationState="error"] {
    border: 2px solid #A34D46;
}
QLabel#projectNameStatus[validationState="error"] {
    color: #A34D46;
}
"""


class ProjectLibraryDialog(QDialog):
    """Browse managed projects without exposing a raw file picker."""

    def __init__(self, library=None, parent=None, *, theme_id=None):
        super().__init__(parent)
        self.library = library or ProjectLibrary()
        self.selected_path: Path | None = None
        self._theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self._items = []
        self.setObjectName("projectLibraryDialog")
        self.setWindowTitle("项目库")
        self.setModal(True)
        self.resize(760, 520)
        self.setMinimumSize(650, 440)
        self.setStyleSheet(
            compose_stylesheet(PROJECT_LIBRARY_STYLESHEET, self._theme_id)
        )
        self._build_ui()
        self.refresh()

    @classmethod
    def choose_project(cls, parent=None, *, library=None, theme_id=None):
        dialog = cls(library=library, parent=parent, theme_id=theme_id)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_path

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(13)

        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(1)
        title = QLabel("项目库")
        title.setObjectName("projectDialogTitle")
        hint = QLabel("选择一个项目继续工作")
        hint.setObjectName("projectDialogHint")
        title_group.addWidget(title)
        title_group.addWidget(hint)
        heading.addLayout(title_group)
        heading.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("projectSearch")
        self.search_edit.setPlaceholderText("搜索项目")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(230)
        self.search_edit.textChanged.connect(self._apply_filter)
        heading.addWidget(self.search_edit)
        root.addLayout(heading)

        location = QFrame()
        location.setObjectName("projectLocationBar")
        location_layout = QHBoxLayout(location)
        location_layout.setContentsMargins(11, 5, 7, 5)
        location_layout.setSpacing(7)
        location_label = QLabel("项目位置")
        location_label.setObjectName("projectLibraryMeta")
        location_layout.addWidget(location_label)
        self.path_edit = QLineEdit(str(self.library.ensure_root()))
        self.path_edit.setObjectName("projectLibraryPath")
        self.path_edit.setReadOnly(True)
        self.path_edit.setCursorPosition(0)
        location_layout.addWidget(self.path_edit, 1)
        folder_button = QPushButton("打开文件夹")
        folder_button.setToolTip("在系统文件管理器中显示项目库")
        folder_button.clicked.connect(self._show_folder)
        location_layout.addWidget(folder_button)
        refresh_button = QPushButton("刷新")
        refresh_button.setToolTip("重新读取项目库")
        refresh_button.clicked.connect(self.refresh)
        location_layout.addWidget(refresh_button)
        root.addWidget(location)

        self.tree = QTreeWidget()
        self.tree.setObjectName("projectLibraryList")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(("项目名称", "空间", "模型", "最近修改"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._item_activated)
        root.addWidget(self.tree, 1)

        self.empty_label = QLabel("项目库为空")
        self.empty_label.setObjectName("projectEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(240)
        self.empty_label.hide()
        root.addWidget(self.empty_label, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("projectLibraryMeta")
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.rejected.connect(self.reject)
        self.open_button = buttons.addButton(
            "打开项目", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.open_button.setObjectName("primaryButton")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)
        footer.addWidget(buttons)
        root.addLayout(footer)

    def refresh(self):
        selected = self.selected_path
        self.selected_path = None
        self.tree.clear()
        self._items = []
        entries = self.library.entries()
        for entry in entries:
            if entry.valid:
                space = entry.modeling_space.upper()
                model = (
                    f"{entry.node_count} 节点 · {entry.element_count} 梁段"
                    f" · {entry.sensor_count} 测点"
                )
            else:
                space = "异常"
                model = "项目无法读取"
            modified = datetime.fromtimestamp(entry.modified_at).strftime(
                "%Y-%m-%d  %H:%M"
            )
            item = QTreeWidgetItem((entry.name, space, model, modified))
            item.setData(0, Qt.ItemDataRole.UserRole, str(entry.path))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, entry.valid)
            if entry.error:
                item.setToolTip(0, entry.error)
                item.setToolTip(2, entry.error)
            self.tree.addTopLevelItem(item)
            self._items.append(item)
            if selected is not None and entry.path == selected:
                self.tree.setCurrentItem(item)

        self.count_label.setText(f"{len(entries)} 个项目")
        self._apply_filter(self.search_edit.text())
        if self.tree.currentItem() is None:
            first_valid = next(
                (
                    item
                    for item in self._items
                    if bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
                    and not item.isHidden()
                ),
                None,
            )
            if first_valid is not None:
                self.tree.setCurrentItem(first_valid)
        self._selection_changed()

    def _apply_filter(self, text):
        query = str(text or "").strip().casefold()
        visible_count = 0
        for item in self._items:
            searchable = " ".join(item.text(column) for column in range(4)).casefold()
            visible = not query or query in searchable
            item.setHidden(not visible)
            visible_count += int(visible)
        self.tree.setVisible(bool(visible_count))
        self.empty_label.setVisible(not visible_count)
        self.empty_label.setText(
            "没有匹配的项目" if self._items else "项目库为空"
        )
        self._selection_changed()

    def _selection_changed(self):
        item = self.tree.currentItem()
        valid = bool(
            item is not None
            and not item.isHidden()
            and item.data(0, Qt.ItemDataRole.UserRole + 1)
        )
        self.open_button.setEnabled(valid)

    def _item_activated(self, item, _column):
        self.tree.setCurrentItem(item)
        self._open_selected()

    def _open_selected(self):
        item = self.tree.currentItem()
        if item is None or not item.data(0, Qt.ItemDataRole.UserRole + 1):
            return
        self.selected_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        self.accept()

    def _show_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.ensure_root())))


class ProjectNameDialog(QDialog):
    """Collect a safe project name and resolve it inside the project library."""

    def __init__(
        self,
        library=None,
        parent=None,
        *,
        initial_name="",
        allowed_existing_path=None,
        title="命名项目",
        confirm_text="继续",
        theme_id=None,
    ):
        super().__init__(parent)
        self.library = library or ProjectLibrary()
        self.library.ensure_root()
        self._theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self._allowed_existing_path = (
            Path(allowed_existing_path).expanduser().resolve()
            if allowed_existing_path is not None
            else None
        )
        self._project_name = ""
        self._project_path: Path | None = None
        self.setObjectName("projectNameDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 270)
        self.setMinimumWidth(480)
        self.setStyleSheet(
            compose_stylesheet(PROJECT_LIBRARY_STYLESHEET, self._theme_id)
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(11)
        heading = QLabel(title)
        heading.setObjectName("projectDialogTitle")
        root.addWidget(heading)
        hint = QLabel("项目将统一保存在 iFEM 项目库中")
        hint.setObjectName("projectDialogHint")
        root.addWidget(hint)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("projectNameEdit")
        self.name_edit.setPlaceholderText("例如：曲梁应变监测")
        clean_initial = "" if initial_name == "未命名项目" else str(initial_name)
        self.name_edit.setText(clean_initial)
        self.name_edit.setClearButtonEnabled(True)
        root.addWidget(self.name_edit)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_label = QLabel("项目位置")
        path_label.setObjectName("projectLibraryMeta")
        path_row.addWidget(path_label)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("projectLibraryPath")
        self.path_edit.setReadOnly(True)
        path_row.addWidget(self.path_edit, 1)
        root.addLayout(path_row)
        self.status_label = QLabel()
        self.status_label.setObjectName("projectNameStatus")
        self.status_label.setMinimumHeight(17)
        root.addWidget(self.status_label)
        root.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm_button = self.buttons.button(
            QDialogButtonBox.StandardButton.Save
        )
        self.confirm_button.setText(confirm_text)
        self.confirm_button.setObjectName("primaryButton")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._accept_valid_name)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.name_edit.textChanged.connect(self._validate_name)
        self._validate_name()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    @classmethod
    def choose_project_name(cls, parent=None, **kwargs):
        dialog = cls(parent=parent, **kwargs)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.project_name, dialog.project_path

    @property
    def project_name(self):
        return self._project_name

    @property
    def project_path(self):
        return self._project_path

    def _validate_name(self, *_args):
        try:
            name = self.name_edit.text()
            path = self.library.path_for_name(name)
            if path.exists() and path.resolve() != self._allowed_existing_path:
                raise ValueError("项目库中已存在同名项目。")
            self._project_name = path.stem
            self._project_path = path
            self.path_edit.setText(str(self.library.root))
            self.path_edit.setToolTip(str(path))
            self.path_edit.setCursorPosition(0)
            message = f"将保存为 {path.name}"
            state = "ready"
            valid = True
        except ValueError as exc:
            self._project_name = ""
            self._project_path = None
            self.path_edit.setText(str(self.library.root))
            self.path_edit.setToolTip(str(self.library.root))
            message = str(exc)
            state = "error"
            valid = False
        self.name_edit.setProperty("validationState", state)
        self.status_label.setProperty("validationState", state)
        self.status_label.setText(message)
        for widget in (self.name_edit, self.status_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.confirm_button.setEnabled(valid)
        return valid

    def _accept_valid_name(self):
        if self._validate_name():
            self.accept()


__all__ = ["ProjectLibraryDialog", "ProjectNameDialog"]
