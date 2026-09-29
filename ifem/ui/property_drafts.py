"""Session-local property drafts for the native modeler (never project data)."""

from contextlib import contextmanager

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLineEdit, QMessageBox

from ifem.ui.property_values import (
    GLOBAL_KEY,
    PropertyInputError,
    apply_property_values,
    property_values,
)


class PropertyDrafts:
    """Keep field deltas by stable entity ID, independently of model undo."""

    def __init__(self, dialog, forms, feedback, apply_buttons, reset_buttons):
        self.dialog = dialog
        self.forms = forms
        self.feedback = feedback
        self.apply_buttons = apply_buttons
        self.reset_buttons = reset_buttons
        self.pending = {}
        self.errors = {}
        self.baselines = {}
        self.displayed_key = None
        self._loading = 0
        self.section_shape = None
        self.section_variants = {}
        self.section_dimensions = None
        for kind, fields in forms.items():
            for widget in fields.values():
                signal = widget.textChanged if isinstance(widget, QLineEdit) else widget.currentIndexChanged
                signal.connect(lambda *_args, group=kind: self.changed(group))
        dialog.draft_selector.activated.connect(self.navigate)
        dialog.draft_apply_all.clicked.connect(self.apply_all)
        dialog.draft_discard_all.clicked.connect(self.discard_all)
        dialog.draft_discard_selected.clicked.connect(self.discard_selected)
        dialog.inspector_tabs.currentChanged.connect(lambda _index: self.update_ui())

    @contextmanager
    def loading(self):
        self._loading += 1
        try:
            yield
        finally:
            self._loading -= 1

    def key_for(self, kind):
        if kind == "primary":
            return GLOBAL_KEY
        if self.displayed_key and self.displayed_key[0] == kind:
            return self.displayed_key
        return None

    @staticmethod
    def read(widget):
        return widget.text() if isinstance(widget, QLineEdit) else widget.currentData()

    def capture_key(self, key):
        if self._loading or key not in self.baselines:
            return
        baseline = self.baselines[key]
        values = {name: self.read(self.forms[key[0]][name]) for name in baseline}
        changes = {name: value for name, value in values.items() if value != baseline[name]}
        # Parameter positions mean different things across section shapes.
        if key == GLOBAL_KEY and "shape" in changes:
            changes.update({name: value for name, value in values.items() if name.startswith("parameter_")})
        if key == GLOBAL_KEY:
            if "shape" in changes or any(name.startswith("parameter_") for name in changes):
                # A diameter must not turn into a rectangle height when undo
                # changes the underlying section type. Keep its schema anchor.
                changes["shape"] = values["shape"]
                self.section_dimensions = {
                    name: value for name, value in values.items()
                    if name == "shape" or name.startswith("parameter_")
                }
            else:
                self.section_dimensions = None
        if changes:
            self.pending[key] = changes
        else:
            self.pending.pop(key, None)
            self.errors.pop(key, None)

    def capture(self):
        self.capture_key(GLOBAL_KEY)
        self.capture_key(self.displayed_key)

    def changed(self, kind):
        if self._loading:
            return
        key = self.key_for(kind)
        self.capture_key(key)
        self.errors.pop(key, None)
        self.update_ui()

    def restore(self, key):
        if key is None:
            return
        try:
            baseline = property_values(self.dialog.project, key)
        except KeyError:
            return
        self.baselines[key] = baseline
        values = self.merged_values(self.dialog.project, key)
        fields = self.forms[key[0]]
        with self.loading():
            if key == GLOBAL_KEY:
                self.dialog._loading_section = True
                try:
                    shape = values["shape"]
                    self.dialog.section_shape_combo.setCurrentIndex(
                        self.dialog.section_shape_combo.findData(shape)
                    )
                    self.dialog._configure_section_fields(shape)
                    self.section_shape = shape
                finally:
                    self.dialog._loading_section = False
            for name, value in values.items():
                widget = fields[name]
                if isinstance(widget, QLineEdit):
                    widget.setText(value)
                else:
                    index = widget.findData(value)
                    if index < 0 and value is not None:
                        # Keep an unresolved reference explicit; never select a
                        # different entity merely because its old ID disappeared.
                        widget.addItem(f"已不可用 · {value}", value)
                        index = widget.count() - 1
                    widget.setCurrentIndex(index)
        if key == GLOBAL_KEY:
            self.dialog._refresh_section_preview_from_form()
        self.capture_key(key)

    def merged_values(self, project, key):
        baseline = property_values(project, key)
        changes = self.pending.get(key, {})
        if (
            key == GLOBAL_KEY and self.section_dimensions
            and self.section_dimensions["shape"] != baseline["shape"]
        ):
            baseline.update(self.section_dimensions)
        return {**baseline, **changes}

    def restore_selected(self):
        key = (self.dialog.selected_kind, self.dialog.selected_id)
        self.displayed_key = key if key[0] in {"node", "element", "sensor"} and key[1] else None
        self.restore(self.displayed_key)
        self.update_ui()

    def switch_section_shape(self, shape):
        """A shape switch must not discard an unfinished dimension string."""
        if self.section_shape:
            self.section_variants[self.section_shape] = [
                edit.text() for edit in self.dialog.section_parameter_edits
            ]
        with self.loading():
            self.dialog._configure_section_fields(shape)
            if shape in self.section_variants:
                for edit, text in zip(self.dialog.section_parameter_edits, self.section_variants[shape]):
                    edit.setText(text)
        self.section_shape = shape

    def label(self, key):
        if key == GLOBAL_KEY:
            return "截面与材料"
        kind, identifier = key
        entities = getattr(self.dialog.project, {"node": "nodes", "element": "elements", "sensor": "sensors"}[kind])
        prefix = {"node": "节点", "element": "梁段", "sensor": "测点"}[kind]
        for index, entity in enumerate(entities, 1):
            if entity.identifier == identifier:
                return f"{prefix} {index} · {identifier[-6:]}"
        return f"已删除的{prefix} · {identifier[-6:]}"

    def update_ui(self):
        dialog = self.dialog
        count = len(self.pending)
        active_key = GLOBAL_KEY if dialog.inspector_tabs.currentIndex() == 0 else self.displayed_key
        active_error = self.errors.get(active_key)
        summary = f"待应用草稿 · {count} 组" if count else "属性输入已同步"
        if active_error:
            summary += "\n" + str(active_error)
        dialog.draft_summary.setText(summary)
        dialog.draft_summary.setProperty("state", "error" if active_error else "waiting" if count else "ready")
        dialog.draft_summary.style().unpolish(dialog.draft_summary)
        dialog.draft_summary.style().polish(dialog.draft_summary)
        dialog.draft_summary.setAccessibleName(dialog.draft_summary.text())
        dialog.draft_selector.blockSignals(True)
        previous = dialog.draft_selector.currentData()
        dialog.draft_selector.clear()
        for key in self.pending:
            label = self.label(key)
            # QVariantList has value equality in findData; an opaque Python
            # tuple does not compare reliably across Qt/PySide versions.
            dialog.draft_selector.addItem(label, list(key))
            dialog.draft_selector.setItemData(dialog.draft_selector.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        index = dialog.draft_selector.findData(list(active_key)) if active_key in self.pending else dialog.draft_selector.findData(previous)
        dialog.draft_selector.setCurrentIndex(max(index, 0))
        dialog.draft_selector.blockSignals(False)
        for widget in (dialog.draft_selector, dialog.draft_discard_selected, dialog.draft_apply_all, dialog.draft_discard_all):
            widget.setVisible(bool(count))
        dialog.inspector_tabs.setTabText(0, "截面与材料" + (" · 待应用" if GLOBAL_KEY in self.pending else ""))
        object_count = count - int(GLOBAL_KEY in self.pending)
        dialog.inspector_tabs.setTabText(1, "对象属性" + (f" · {object_count}" if object_count else ""))
        for kind, widgets in self.forms.items():
            key = self.key_for(kind)
            error = self.errors.get(key)
            dirty = key in self.pending
            self.apply_buttons[kind].setEnabled(dirty)
            self.reset_buttons[kind].setEnabled(dirty)
            status = self.feedback[kind]
            status.setText(str(error) if error else ("待应用 · 切换对象不会丢失输入" if dirty else "与当前模型一致"))
            status.setProperty("state", "error" if error else "waiting" if dirty else "ready")
            status.style().unpolish(status)
            status.style().polish(status)
            for name, widget in widgets.items():
                state = "error" if error and error.field == name else ""
                if widget.property("validationState") != state:
                    widget.setProperty("validationState", state)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
        current = dialog.project.to_dict()
        current.pop("revision", None)
        dialog.setWindowTitle("iFEM | 结构建模" + (" · 未应用" if count or current != dialog._workspace_baseline else ""))

    def focus_key(self, key, field=None):
        dialog = self.dialog
        if key == GLOBAL_KEY:
            dialog.inspector_tabs.setCurrentIndex(0)
        else:
            try:
                property_values(dialog.project, key)
            except KeyError:
                dialog._set_status("该对象已删除；撤销删除可恢复草稿，或用“放弃此项”清除。", "error")
                dialog.draft_discard_selected.setFocus()
                return
            dialog._selection_changed(*key)
        if field:
            widget = self.forms[key[0]].get(field)
            if widget:
                if key[0] == "sensor":
                    tab = 2 if field in {"strain", "weight", "zone_a", "zone_b"} else 1 if field in {"surface", "surface_angle", "orientation_angle"} else 0
                    dialog.sensor_config_tabs.setCurrentIndex(tab)
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
                if isinstance(widget, QLineEdit):
                    widget.selectAll()
                scroll = dialog.inspector_tabs.widget(0 if key == GLOBAL_KEY else 1)
                scroll.ensureWidgetVisible(widget)
                # Tab changes and dynamic feedback resize the scroll contents
                # on the next layout pass. Scroll again after that pass.
                QTimer.singleShot(20, scroll, lambda: scroll.ensureWidgetVisible(widget, 8, 24) if widget.isVisibleTo(scroll) else None)

    def navigate(self, index):
        key = self.dialog.draft_selector.itemData(index)
        if key:
            self.focus_key(tuple(key))

    def apply_keys(self, keys):
        self.capture()
        keys = [key for key in keys if key in self.pending]
        if not keys:
            return True
        before = after = self.dialog.project
        # Validate everything against a provisional document. No partial model
        # commits, history entries or draft clearing on a failed validation.
        for key in keys:
            try:
                values = self.merged_values(after, key)
                after = apply_property_values(after, key, values)
            except (KeyError, TypeError, ValueError) as exc:
                error = exc if isinstance(exc, PropertyInputError) else PropertyInputError("", str(exc))
                self.errors[key] = error
                self.focus_key(key, error.field)
                self.update_ui()
                self.dialog.draft_selector.setCurrentIndex(
                    self.dialog.draft_selector.findData(list(key))
                )
                if isinstance(exc, KeyError):
                    message = "草稿对象已删除 · 撤销删除可恢复，或放弃此项后重试"
                else:
                    message = f"{self.label(key)}未应用；输入已保留，请检查属性。"
                self.dialog._set_status(message, "error")
                return False
        with self.loading():
            for key in keys:
                self.pending.pop(key, None)
                self.errors.pop(key, None)
            if GLOBAL_KEY in keys:
                self.section_variants.clear()
                self.section_dimensions = None
            self.dialog._commit_project(before, after, "应用属性草稿" if len(keys) == 1 else f"应用 {len(keys)} 组属性草稿")
        self.update_ui()
        self.dialog._set_status("属性已应用到模型 · 可撤销；尚未写入项目文件", "ready")
        return True

    def apply_all(self):
        self.capture()
        keys = sorted(self.pending, key=lambda key: {"primary": 0, "node": 1, "element": 2, "sensor": 3}[key[0]])
        return self.apply_keys(keys)

    def reset(self, kind):
        key = self.key_for(kind)
        if key is None:
            return
        self.pending.pop(key, None)
        self.errors.pop(key, None)
        if key == GLOBAL_KEY:
            self.section_variants.clear()
            self.section_dimensions = None
        self.restore(key)
        self.update_ui()

    def discard_all(self):
        if not self.pending:
            return
        answer = QMessageBox.question(
            self.dialog, "放弃所有属性草稿？",
            f"将还原 {len(self.pending)} 组尚未应用的属性输入，当前模型和已保存文件不变。\n草稿本身不进入撤销历史。",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Discard:
            self.clear()
            self.restore(GLOBAL_KEY)
            self.restore_selected()

    def discard_selected(self):
        selected = self.dialog.draft_selector.currentData()
        key = tuple(selected) if selected else None
        if key not in self.pending:
            return
        answer = QMessageBox.question(
            self.dialog, "放弃这组属性草稿？",
            f"将放弃“{self.label(key)}”的未应用输入，其他草稿和当前模型保持不变。",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Discard:
            self.pending.pop(key, None)
            self.errors.pop(key, None)
            if key == GLOBAL_KEY:
                self.section_variants.clear()
                self.section_dimensions = None
            if key in (GLOBAL_KEY, self.displayed_key):
                self.restore(key)
            self.update_ui()

    def clear(self):
        self.pending.clear()
        self.errors.clear()
        self.baselines.clear()
        self.displayed_key = None
        self.section_variants.clear()
        self.section_shape = None
        self.section_dimensions = None
