import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QKeySequence, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetSelectionRange, QWidget

from ifem.domain.analysis import InputValidationError
from ifem.ui.editable_table import EditableTable


class EditableTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []
        self.saved_clipboard = self.app.clipboard().text()

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.clipboard().setText(self.saved_clipboard)

    def editor(self, *, fields=None, **kwargs):
        fields = fields or [
            {"key": "x", "label": "位置"},
            {"key": "hidden", "label": "隐藏"},
            {"key": "value", "label": "数值"},
        ]
        editor = EditableTable("测试表", fields, **kwargs)
        self.widgets.append(editor)
        return editor

    @staticmethod
    def select(editor, top, left, bottom=None, right=None):
        editor.table.clearSelection()
        editor.table.setCurrentCell(top, left)
        editor.table.setRangeSelected(QTableWidgetSelectionRange(
            top, left, top if bottom is None else bottom, left if right is None else right,
        ), True)

    @staticmethod
    def selection(editor):
        return sorted((index.row(), index.column()) for index in editor.table.selectedIndexes())

    def test_copy_uses_raw_values_and_visible_columns_without_ids(self):
        editor = self.editor(fields=[
            {"key": "surface", "label": "表面", "table_display": {"top": "上"}},
            {"key": "hidden", "label": "隐藏"}, {"key": "value", "label": "值"},
        ], table_columns=["surface", "value"])
        editor.set_rows([{"surface": "top", "hidden": "secret", "value": " 2 ", "_entity_id": "sensor_1"}])
        editor.table.selectRow(0)
        self.assertEqual(editor.copy_selected(), "top\t 2 \r\n")
        self.assertEqual(editor.table.item(0, 0).text(), "上")

    def test_quoted_tsv_round_trips_spaces_empty_columns_tabs_and_newlines(self):
        editor = self.editor()
        original = [{"x": '  \"quoted\"\tX ', "hidden": "", "value": "first\rsecond\nthird"}]
        editor.set_rows(original)
        editor.table.selectAll()
        text = editor.copy_selected()
        editor.set_rows([])
        self.assertTrue(editor.paste_text(text))
        self.assertEqual(editor.get_rows(), original)

    def test_paste_skips_hidden_columns(self):
        editor = self.editor(table_columns=["x", "value"])
        editor.set_rows([{"x": "a", "hidden": "keep", "value": "b", "_entity_id": "stable"}])
        self.select(editor, 0, 0)
        self.assertTrue(editor.paste_text("c\td"))
        self.assertEqual(editor.get_rows(), [{"x": "c", "hidden": "keep", "value": "d", "_entity_id": "stable"}])
        self.assertEqual(editor.history.count(), 1)

    def test_copy_and_paste_follow_visible_header_order(self):
        editor = self.editor()
        editor.set_rows([{"x": "one", "hidden": "two", "value": "three"}])
        editor.table.horizontalHeader().moveSection(2, 0)
        editor.table.selectAll()
        self.assertEqual(editor.copy_selected(), "three\tone\ttwo\r\n")
        self.assertTrue(editor.paste_text("first\tsecond\tthird"))
        self.assertEqual(editor.get_rows(), [{"x": "second", "hidden": "third", "value": "first"}])

    def test_single_value_fills_selected_rectangle_atomically(self):
        editor = self.editor()
        editor.set_rows([{"x": "1"}, {"x": "2"}, {"x": "3"}])
        self.select(editor, 0, 0, 2, 2)
        self.assertTrue(editor.paste_text("same"))
        self.assertEqual(editor.history.count(), 1)
        self.assertTrue(all(set(row.values()) == {"same"} for row in editor.get_rows()))
        self.assertTrue(editor.undo())
        self.assertEqual([row["x"] for row in editor.get_rows()], ["1", "2", "3"])

    def test_nonrectangular_selection_rejects_paste_and_copy_without_clipboard_change(self):
        editor = self.editor()
        editor.set_rows([{"x": "1"}, {"x": "2"}])
        self.select(editor, 0, 0)
        editor.table.selectionModel().select(editor.table.model().index(1, 2), QItemSelectionModel.SelectionFlag.Select)
        before = editor.get_rows(), self.selection(editor)
        self.app.clipboard().setText("saved")
        self.assertFalse(editor.paste_text("7"))
        self.assertEqual(editor.copy_selected(), "")
        self.assertEqual((editor.get_rows(), self.selection(editor)), before)
        self.assertEqual(self.app.clipboard().text(), "saved")
        self.assertEqual(editor.history.count(), 0)

    def test_mismatched_selection_and_column_overflow_are_not_truncated(self):
        editor = self.editor()
        editor.set_rows([{"x": "1"}, {"x": "2"}])
        before = editor.get_rows()
        self.select(editor, 0, 0, 1, 1)
        self.assertFalse(editor.paste_text("a\tb\tc"))
        self.select(editor, 0, 2)
        self.assertFalse(editor.paste_text("a\tb"))
        self.assertEqual(editor.get_rows(), before)
        self.assertEqual(editor.history.count(), 0)

    def test_append_generates_entity_ids_only_after_validation_and_reuses_on_redo(self):
        validator = Mock()
        editor = self.editor(entity_prefix="sensor", validate_rows=validator)
        with patch("ifem.ui.editable_table.new_entity_id", side_effect=["new1", "new2"]) as generate:
            self.assertTrue(editor.paste_text("a\tb\tc\nd\te\tf"))
            inserted = editor.get_rows()
            self.assertEqual([row["_entity_id"] for row in inserted], ["new1", "new2"])
            self.assertEqual(validator.call_args.args[0][0].get("_entity_id"), None)
            self.assertTrue(editor.undo())
            self.assertTrue(editor.redo())
            self.assertEqual(editor.get_rows(), inserted)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(validator.call_count, 1)

    def test_failed_candidate_preserves_everything_and_does_not_allocate_ids(self):
        validator = Mock(side_effect=InputValidationError("数值不正确", field="/rows/0/value"))
        editor = self.editor(entity_prefix="row", validate_rows=validator)
        editor.set_rows([{"x": "old", "hidden": "keep", "value": "1", "_entity_id": "stable"}])
        self.select(editor, 0, 0)
        editor.inputs["value"].setText("unfinished")
        before = editor.get_rows(), self.selection(editor), editor.get_form_values()
        self.app.clipboard().setText("clipboard")
        with patch("ifem.ui.editable_table.new_entity_id") as generate:
            self.assertFalse(editor.paste_text("a\tb\tc\nd\te\tf"))
            generate.assert_not_called()
        self.assertEqual((editor.get_rows(), self.selection(editor), editor.get_form_values()), before)
        self.assertEqual(self.app.clipboard().text(), "clipboard")
        self.assertEqual(editor.history.count(), 0)
        self.assertIn("数值不正确", editor.status_label.text())

    def test_update_validation_failure_preserves_form_and_rows(self):
        editor = self.editor(validate_rows=lambda _rows: (_ for _ in ()).throw(InputValidationError("值不正确", field="/rows/0/value")))
        editor.set_rows([{"x": "1", "value": "2"}])
        editor.table.selectRow(0)
        editor.inputs["value"].setText("bad")
        self.assertFalse(editor.update_selected())
        self.assertEqual(editor.get_rows()[0]["value"], "2")
        self.assertEqual(editor.inputs["value"].text(), "bad")
        self.assertEqual(editor.inputs["value"].selectedText(), "bad")
        self.assertEqual(editor.history.count(), 0)

    def test_form_add_and_update_share_undo_and_existing_id(self):
        editor = self.editor(entity_prefix="record")
        editor.set_form_values({"x": "one", "hidden": "two", "value": "three"})
        self.assertTrue(editor.add_row())
        entity_id = editor.get_rows()[0]["_entity_id"]
        self.assertEqual(editor.get_form_values(), {"x": "", "hidden": "", "value": ""})
        editor.table.selectRow(0)
        editor.inputs["value"].setText("four")
        self.assertTrue(editor.update_selected())
        self.assertEqual(editor.history.count(), 2)
        self.assertEqual(editor.get_rows()[0]["_entity_id"], entity_id)
        editor.undo()
        self.assertEqual(editor.get_rows()[0]["value"], "three")
        editor.undo()
        self.assertEqual(editor.get_rows(), [])

    def test_multirow_selection_disables_single_row_update(self):
        editor = self.editor()
        editor.set_rows([{"x": "1"}, {"x": "2"}])
        self.select(editor, 0, 0, 1, 0)
        self.assertFalse(editor.update_button.isEnabled())
        self.assertFalse(editor.update_selected())
        self.assertEqual(editor.history.count(), 0)

    def test_fill_down_keeps_row_ids_and_undo_restores_selection(self):
        editor = self.editor()
        editor.set_rows([
            {"x": "same", "value": "1", "_entity_id": "one"},
            {"x": "other", "value": "2", "_entity_id": "two"},
            {"x": "third", "value": "3", "_entity_id": "three"},
        ])
        self.select(editor, 0, 0, 2, 0)
        before = editor.get_rows(), self.selection(editor)
        self.assertTrue(editor.fill_down())
        self.assertEqual([row["x"] for row in editor.get_rows()], ["same"] * 3)
        self.assertEqual([row["_entity_id"] for row in editor.get_rows()], ["one", "two", "three"])
        self.assertEqual(editor.history.count(), 1)
        editor.undo()
        self.assertEqual((editor.get_rows(), self.selection(editor)), before)

    def test_nonadjacent_multirow_delete_is_one_atomic_command(self):
        editor = self.editor()
        editor.set_rows([{"x": str(index), "_entity_id": str(index)} for index in range(4)])
        self.select(editor, 0, 0)
        editor.table.selectionModel().select(editor.table.model().index(3, 2), QItemSelectionModel.SelectionFlag.Select)
        before = editor.get_rows(), self.selection(editor)
        self.assertTrue(editor.delete_selected())
        self.assertEqual([row["x"] for row in editor.get_rows()], ["1", "2"])
        self.assertEqual(editor.history.count(), 1)
        editor.undo()
        self.assertEqual((editor.get_rows(), self.selection(editor)), before)

    def test_clear_confirmation_and_validation_are_respected(self):
        editor = self.editor()
        editor.set_rows([{"x": "1"}])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(editor.confirm_clear_rows())
        self.assertEqual(len(editor.get_rows()), 1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(editor.confirm_clear_rows())
        self.assertEqual(editor.get_rows(), [])
        editor.undo()
        self.assertEqual(len(editor.get_rows()), 1)
        editor.validate_rows = Mock(side_effect=InputValidationError("必须保留一行"))
        self.assertFalse(editor.clear_rows())
        self.assertEqual(len(editor.get_rows()), 1)

    def test_shared_history_restores_only_own_table_and_checks_command_owner(self):
        stack = QUndoStack()
        flags = {"first": True, "second": True}
        first = self.editor(undo_stack=stack, can_mutate=lambda: flags["first"])
        second = self.editor(undo_stack=stack, can_mutate=lambda: flags["second"])
        first.paste_text("1\t2\t3")
        second.paste_text("a\tb\tc")
        flags["second"] = False
        first.refresh_actions()
        self.assertFalse(first.undo_action.isEnabled())
        self.assertFalse(first.undo())
        self.assertEqual(stack.index(), 2)
        flags["second"] = True
        self.assertTrue(first.undo())
        self.assertEqual(second.get_rows(), [])
        self.assertEqual(first.get_rows()[0]["x"], "1")
        first.undo()
        self.assertEqual(first.get_rows(), [])
        first.redo()
        self.assertEqual(first.get_rows()[0]["x"], "1")

    def test_load_clears_shared_history_and_emits_change(self):
        change = Mock()
        editor = self.editor(on_change=change)
        editor.paste_text("1\t2\t3")
        editor.set_rows([{"x": "loaded"}])
        self.assertEqual(editor.history.count(), 0)
        self.assertEqual(change.call_count, 2)

    def test_unchanged_candidate_does_not_create_a_command_or_emit_change(self):
        change = Mock()
        editor = self.editor(on_change=change)
        editor.set_rows([{"x": "1", "value": "2"}])
        change.reset_mock()
        self.select(editor, 0, 0)
        self.assertTrue(editor.paste_text("1"))
        self.assertEqual(editor.history.count(), 0)
        change.assert_not_called()

    def test_undo_redo_emit_one_change_without_revalidation(self):
        change, validator = Mock(), Mock()
        editor = self.editor(on_change=change, validate_rows=validator)
        editor.paste_text("1\t2\t3")
        validator.side_effect = AssertionError("history must not revalidate")
        editor.undo()
        editor.redo()
        self.assertEqual(change.call_count, 3)
        self.assertEqual(validator.call_count, 1)

    def test_readonly_blocks_all_mutations_but_keeps_copy(self):
        allowed = {"value": False}
        editor = self.editor(can_mutate=lambda: allowed["value"])
        editor.set_rows([{"x": "1", "value": "2"}, {"x": "3", "value": "4"}])
        editor.table.selectAll()
        self.assertFalse(editor.paste_text("9"))
        self.assertFalse(editor.fill_down())
        self.assertFalse(editor.delete_selected())
        self.assertFalse(editor.clear_rows())
        self.assertFalse(editor.add_row())
        self.assertFalse(editor.inputs["x"].isEnabled())
        self.assertTrue(editor.copy_action.isEnabled())
        self.assertNotEqual(editor.copy_selected(), "")
        self.assertEqual(editor.history.count(), 0)
        self.assertIn("只读", editor.status_label.text())

    def test_all_fields_switch_changes_only_visibility_and_scroll_policy(self):
        editor = self.editor(table_columns=["x", "value"])
        editor.set_rows([{"x": "1", "hidden": "aux", "value": "2"}])
        before = editor.get_rows()
        editor.all_fields_checkbox.setChecked(True)
        self.assertFalse(editor.table.isColumnHidden(1))
        self.assertEqual(editor.table.horizontalHeader().minimumSectionSize(), 88)
        editor.set_all_fields_visible(False)
        self.assertTrue(editor.table.isColumnHidden(1))
        self.assertEqual(editor.table.horizontalHeader().minimumSectionSize(), 76)
        self.assertEqual(editor.get_rows(), before)
        self.assertEqual(editor.history.count(), 0)
        self.assertEqual(editor.table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def test_toolbar_and_status_have_graphite_theme_hooks(self):
        editor = self.editor()
        for button in (editor.copy_button, editor.paste_button, editor.undo_button, editor.redo_button, editor.more_button):
            self.assertEqual(button.objectName(), "tableEditToolButton")
        self.assertEqual(editor.status_label.objectName(), "tableEditStatus")
        self.assertFalse(editor.paste_text(""))
        self.assertEqual(editor.status_label.property("validationState"), "error")
        editor.refresh_actions()
        self.assertEqual(editor.status_label.property("validationState"), "error")
        editor.set_rows([])
        self.assertEqual(editor.status_label.property("validationState"), "")

    def test_large_payload_row_cell_and_byte_limits_preserve_table(self):
        editor = self.editor()
        editor.MAX_ROWS = 2
        self.assertFalse(editor.paste_text("1\n2\n3"))
        editor.MAX_ROWS = 100
        editor.MAX_CELLS = 4
        self.assertFalse(editor.paste_text("1\t2\t3\n4\t5\t6"))
        editor.MAX_CELLS = 100
        editor.MAX_CLIPBOARD_BYTES = 8
        self.assertFalse(editor.paste_text("一二三"))
        self.assertEqual(editor.history.count(), 0)
        self.assertEqual(editor.get_rows(), [])

    def test_malformed_tsv_and_incomplete_append_reject_without_partial_rows(self):
        def validator(rows):
            if any(not row["value"] for row in rows):
                raise InputValidationError("缺少必填数值")
        editor = self.editor(validate_rows=validator)
        self.assertFalse(editor.paste_text('"unterminated'))
        self.assertFalse(editor.paste_text("one\ttwo\nthree"))
        self.assertFalse(editor.paste_text("x\thidden"))
        self.assertFalse(editor.paste_text("x\thidden\tvalue\n\n"))
        self.assertEqual(editor.get_rows(), [])
        self.assertEqual(editor.history.count(), 0)

    def test_unknown_enum_cannot_silently_coerce_to_another_option(self):
        editor = self.editor(fields=[{"key": "dof", "label": "自由度", "choices": ["u", "v", "phi"]}])
        self.assertFalse(editor.paste_text("unknown"))
        self.assertTrue(editor.paste_text("U"))
        self.assertEqual(editor.get_rows()[0]["dof"], "U")
        self.assertEqual(editor.inputs["dof"].currentText(), "U")
        editor.set_rows([{"dof": "older-value"}])
        editor.table.selectRow(0)
        self.assertEqual(editor.inputs["dof"].currentText(), "older-value")
        self.assertFalse(editor.update_selected())
        self.assertEqual(editor.get_rows()[0]["dof"], "older-value")

    def test_shortcuts_are_scoped_to_table_and_do_not_capture_line_edit(self):
        editor = self.editor()
        editor.show()
        self.app.processEvents()
        self.assertEqual(editor.paste_action.shortcutContext(), Qt.ShortcutContext.WidgetShortcut)
        self.assertEqual(editor.undo_action.shortcutContext(), Qt.ShortcutContext.WidgetShortcut)
        target = editor.inputs["x"]
        target.setFocus()
        try:
            self.app.clipboard().setText("line edit clipboard")
            QTest.keySequence(target, QKeySequence(QKeySequence.StandardKey.Paste))
            self.assertEqual(target.text(), "line edit clipboard")
            self.assertEqual(editor.get_rows(), [])
            QTest.keySequence(target, QKeySequence(QKeySequence.StandardKey.Undo))
            self.assertEqual(target.text(), "")
        finally:
            # Offscreen macOS can retain the standard shortcut's modifier.
            # Release before teardown destroys the target, including on failure.
            QTest.keyRelease(target, Qt.Key.Key_Control)
            QTest.keyRelease(target, Qt.Key.Key_Meta)

    def test_shared_stack_parent_destruction_does_not_raise_in_connected_slots(self):
        host = QWidget()
        history = QUndoStack(host)
        editor = EditableTable("owned", [{"key": "x", "label": "X"}], parent=host, undo_stack=history)
        editor.paste_text("1")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            host.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertNotIn("already deleted", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
