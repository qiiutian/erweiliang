"""Local reading controls and recoverable, geometry-independent layouts."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QTableWidget, QVBoxLayout,
)

from ifem.ui.theme import compose_stylesheet
from ifem.ui.workspace_preferences import ReadingPreferences


def apply_reading_metrics(root, preferences):
    """Give larger type room without accumulating metrics on repeated apply."""
    for table in root.findChildren(QTableWidget):
        header = table.verticalHeader()
        baseline = table.property("ifemBaseRowHeight")
        if baseline is None:
            baseline = header.defaultSectionSize()
            table.setProperty("ifemBaseRowHeight", baseline)
        height = round(baseline * preferences.font_scale / 100)
        if preferences.density == "comfortable":
            height += 8
        header.setDefaultSectionSize(max(height, table.fontMetrics().height() + 8))


class ReadingPreferencesDialog(QDialog):
    """Stage choices in an isolated preview; Cancel never changes the owner."""

    def __init__(self, preferences, parent=None, *, theme_id="graphite"):
        super().__init__(parent)
        self.setWindowTitle("阅读与布局")
        self.setObjectName("readingPreferencesDialog")
        self._theme_id = theme_id
        self.resize(480, 400)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        title = QLabel("适合你的工作台")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel("仅保存在本机，不改变项目、计算单位或结果图比例。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        form.setSpacing(12)
        self.font_scale_combo = QComboBox()
        self.font_scale_combo.setAccessibleName("界面字号")
        for name, scale in (("标准 · 100%", 100), ("较大 · 110%", 110), ("大号 · 120%", 120)):
            self.font_scale_combo.addItem(name, scale)
        self.density_combo = QComboBox()
        self.density_combo.setAccessibleName("界面密度")
        self.density_combo.addItem("紧凑 · 更多内容", "compact")
        self.density_combo.addItem("舒适 · 更多留白", "comfortable")
        form.addRow("界面字号", self.font_scale_combo)
        form.addRow("界面密度", self.density_combo)
        layout.addLayout(form)
        self.preview = QGroupBox("阅读预览")
        preview_layout = QVBoxLayout(self.preview)
        preview_layout.addWidget(QLabel("模型与测点 · 输入检查"))
        sample = QLineEdit("0.000125")
        sample.setReadOnly(True)
        sample.setAccessibleName("只读字号预览示例")
        preview_layout.addWidget(sample)
        preview_hint = QLabel("这只是字号示例，不是当前项目数据。")
        preview_hint.setObjectName("hintLabel")
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)
        layout.addWidget(self.preview)
        layout_hint = QLabel("面板大小和展开状态会在正常退出时记住。\n可从“更多”菜单一键恢复工作区布局。")
        layout_hint.setWordWrap(True)
        layout_hint.setObjectName("hintLabel")
        layout.addWidget(layout_hint)
        self.buttons = QDialogButtonBox()
        self.reset_button = self.buttons.addButton("恢复阅读默认", QDialogButtonBox.ButtonRole.ResetRole)
        self.cancel_button = self.buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_button = self.buttons.addButton("应用", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName("smallPrimaryButton")
        self.apply_button.setDefault(True)
        self.reset_button.clicked.connect(lambda: self.set_preferences(ReadingPreferences()))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setStyleSheet(compose_stylesheet("", theme_id, preferences=preferences))
        self.font_scale_combo.currentIndexChanged.connect(self._refresh_preview)
        self.density_combo.currentIndexChanged.connect(self._refresh_preview)
        self.set_preferences(preferences)

    @property
    def preferences(self):
        return ReadingPreferences(
            font_scale=self.font_scale_combo.currentData(),
            density=self.density_combo.currentData(),
        )

    def set_preferences(self, preferences):
        self.font_scale_combo.setCurrentIndex(self.font_scale_combo.findData(preferences.font_scale))
        self.density_combo.setCurrentIndex(self.density_combo.findData(preferences.density))
        self._refresh_preview()

    def _refresh_preview(self, *_args):
        self.preview.setStyleSheet(compose_stylesheet("", self._theme_id, preferences=self.preferences))


class WorkspaceLayoutController(QObject):
    """Persist normal layout only; hidden panes never replace healthy ratios."""

    def __init__(self, window, store, surface, splitters, defaults, visibility=None):
        super().__init__(window)
        self.window = window
        self.store = store
        self.surface = surface
        self.splitters = splitters
        self.defaults = {key: list(value) for key, value in defaults.items()}
        self.visibility = visibility or {}
        self._ratios = dict(self.defaults)
        self._restoring = False
        self._stopped = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.restore_ratios)
        state = store.load_layout(surface)
        self._initial_restore = bool(state)
        self._ratios.update({key: value for key, value in state.get("ratios", {}).items() if key in splitters})
        size = state.get("window_size")
        if size:
            available = window.screen().availableGeometry().size()
            window.resize(
                max(window.minimumWidth(), min(size[0], available.width())),
                max(window.minimumHeight(), min(size[1], available.height())),
            )
        self._restoring = True
        for key, button in self.visibility.items():
            button.setChecked(state.get("visibility", {}).get(key, True))
        self._restoring = False
        for splitter in splitters.values():
            splitter.splitterMoved.connect(self.capture)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if not self._stopped and watched is self.window and event.type() == QEvent.Type.Show and self._initial_restore:
            self._initial_restore = False
            self._timer.start(0)
        return super().eventFilter(watched, event)

    def capture(self, *_args):
        if self._restoring or self._stopped:
            return
        for key, splitter in self.splitters.items():
            if any(splitter.widget(index).isHidden() for index in range(splitter.count())):
                continue
            sizes = splitter.sizes()
            if len(sizes) == 2 and min(sizes) > 0:
                self._ratios[key] = sizes

    def restore_ratios(self):
        if self._stopped:
            return
        self._restoring = True
        try:
            for key, splitter in self.splitters.items():
                if any(splitter.widget(index).isHidden() for index in range(splitter.count())):
                    continue
                ratio = self._ratios[key]
                length = splitter.width() if splitter.orientation() == Qt.Orientation.Horizontal else splitter.height()
                length = max(length - splitter.handleWidth(), 1)
                splitter.setSizes([max(1, round(length * part / sum(ratio))) for part in ratio])
        finally:
            self._restoring = False

    def restore_later(self):
        if not self._stopped:
            self._timer.start(20)

    def save(self):
        if self._stopped:
            return
        self.capture()
        geometry = self.window.normalGeometry() if self.window.isMaximized() else self.window.geometry()
        self.store.save_layout(self.surface, {
            "ratios": self._ratios,
            "visibility": {key: button.isChecked() for key, button in self.visibility.items()},
            "window_size": [geometry.width(), geometry.height()],
        })

    def reset(self):
        self._timer.stop()
        self._restoring = True
        try:
            for button in self.visibility.values():
                button.setChecked(True)
        finally:
            self._restoring = False
        self._ratios = {key: list(value) for key, value in self.defaults.items()}
        self.restore_ratios()
        self.store.reset_layout(self.surface)

    def stop(self):
        self._stopped = True
        self._timer.stop()
