"""Property inputs are session drafts until explicitly applied to the model."""

import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from config_adapter import get_sample_config
from ifem.domain.project import empty_beam_project
from ifem.infrastructure import load_project, project_from_legacy_config, save_project
from ifem.modeling import PathBeamEditor
from ifem.ui.modeler import BeamModelerDialog, ProjectLibraryDialog
from test_ui_support import isolated_workspace_settings


GLOBAL_KEY = ("primary", "")


@isolated_workspace_settings
class PropertyDraftUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, project=None):
        if project is None:
            project = project_from_legacy_config(get_sample_config())
        with patch("ifem.ui.modeler_3d.MODEL_3D_AVAILABLE", False):
            dialog = BeamModelerDialog(project, theme_id="graphite")
        self.addCleanup(self.dispose, dialog)
        return dialog

    def dispose(self, dialog):
        # Rejection is intentionally not cleanup: it can ask about live drafts.
        dialog.hide()
        dialog.shutdown()
        dialog.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def select(self, dialog, kind, entity):
        identifier = entity if isinstance(entity, str) else entity.identifier
        dialog._selection_changed(kind, identifier)
        return kind, identifier

    def test_initial_load_and_repeated_refresh_do_not_create_drafts(self):
        dialog = self.dialog()
        for kind, entity in (
            ("node", dialog.project.nodes[0]),
            ("element", dialog.project.elements[0]),
            ("sensor", dialog.project.sensors[0]),
        ):
            self.select(dialog, kind, entity)
            dialog._refresh_property_panel()
            dialog._apply_project(dialog.project.revised())
            self.assertFalse(dialog.property_drafts.pending)
        self.assertNotIn("未应用", dialog.windowTitle())
        self.assertIn("已同步", dialog.draft_summary.text())

    def test_missing_strain_and_explicit_zero_remain_distinguishable(self):
        project = project_from_legacy_config(get_sample_config())
        sensor = replace(project.sensors[0], measured_value=None)
        dialog = self.dialog(replace(project, sensors=(sensor,) + project.sensors[1:]))
        key = self.select(dialog, "sensor", sensor)
        self.assertEqual(dialog.sensor_strain_edit.text(), "")
        self.assertFalse(dialog.property_drafts.pending)
        dialog.sensor_strain_edit.setText("0")
        self.assertIn(key, dialog.property_drafts.pending)
        self.assertTrue(dialog._update_sensor_property())
        self.assertEqual(dialog.project.sensors[0].measured_value, 0.0)
        dialog.sensor_strain_edit.clear()
        self.assertTrue(dialog._update_sensor_property())
        self.assertIsNone(dialog.project.sensors[0].measured_value)
        dialog.undo_stack.undo()
        self.assertEqual(dialog.sensor_strain_edit.text(), "0")

    def test_node_invalid_text_survives_same_and_other_object_selection(self):
        dialog = self.dialog(empty_beam_project())
        first, second = dialog.project.nodes
        before = dialog.project.to_dict()
        for text in ("-", "1e-", "", "  2.500000  "):
            with self.subTest(text=text):
                key = self.select(dialog, "node", first)
                dialog.node_y_edit.setText(text)
                self.select(dialog, "node", first)
                self.assertEqual(dialog.node_y_edit.text(), text)
                self.select(dialog, "node", second)
                self.select(dialog, "node", first)
                self.assertEqual(dialog.node_y_edit.text(), text)
                self.assertIn(key, dialog.property_drafts.pending)
        self.assertEqual(dialog.project.to_dict(), before)
        self.assertEqual(dialog.undo_stack.count(), 0)

    def test_reverting_text_and_resetting_one_group_leave_other_drafts(self):
        dialog = self.dialog(empty_beam_project())
        node = dialog.project.nodes[0]
        key = self.select(dialog, "node", node)
        original = dialog.node_y_edit.text()
        dialog.node_y_edit.setText("0.2")
        self.assertIn(key, dialog.property_drafts.pending)
        dialog.node_y_edit.setText(original)
        self.assertNotIn(key, dialog.property_drafts.pending)
        dialog.node_y_edit.setText("0.3")
        dialog.material_e_edit.setText("70")
        dialog.property_drafts.reset("node")
        self.assertEqual(dialog.node_y_edit.text(), original)
        self.assertNotIn(key, dialog.property_drafts.pending)
        self.assertIn(GLOBAL_KEY, dialog.property_drafts.pending)
        self.assertEqual(dialog.material_e_edit.text(), "70")
        self.assertEqual(dialog.undo_stack.count(), 0)

    def test_field_delta_keeps_new_model_coordinates_through_undo_and_redo(self):
        dialog = self.dialog(empty_beam_project())
        first = dialog.project.nodes[0]
        self.select(dialog, "node", first)
        dialog.node_y_edit.setText("0.25")
        before = dialog.project
        moved = PathBeamEditor.move_node(before, first.identifier, (0.1, 0.0, 0.0))
        dialog._commit_project(before, moved, "画布拖动节点")
        self.assertEqual(float(dialog.node_x_edit.text()), 0.1)
        self.assertEqual(dialog.node_y_edit.text(), "0.25")
        dialog.undo_stack.undo()
        self.assertEqual(float(dialog.node_x_edit.text()), 0.0)
        self.assertEqual(dialog.node_y_edit.text(), "0.25")
        dialog.undo_stack.redo()
        self.assertEqual(float(dialog.node_x_edit.text()), 0.1)
        self.assertEqual(dialog.node_y_edit.text(), "0.25")
        self.assertTrue(dialog._update_node_property())
        updated = next(n for n in dialog.project.nodes if n.identifier == first.identifier)
        self.assertEqual(updated.coordinates, (0.1, 0.25, 0.0))
        self.assertFalse(dialog.property_drafts.pending)

    def test_sensor_tabs_and_reference_combo_preserve_exact_draft(self):
        dialog = self.dialog()
        sensor, other = dialog.project.sensors[:2]
        key = self.select(dialog, "sensor", sensor)
        target = dialog.project.elements[-1].identifier
        dialog.sensor_element_combo.setCurrentIndex(dialog.sensor_element_combo.findData(target))
        edits = {
            "sensor_label_edit": " 测点草稿 A ",
            "sensor_xi_edit": "0.35",
            "sensor_surface_angle_edit": "75",
            "sensor_orientation_angle_edit": "1e-",
            "sensor_strain_edit": "-",
            "sensor_weight_edit": "2.5",
            "sensor_zone_a_edit": "0.1",
            "sensor_zone_b_edit": "0.9",
        }
        for name, value in edits.items():
            getattr(dialog, name).setText(value)
        self.select(dialog, "sensor", other)
        self.select(dialog, "sensor", sensor)
        for name, value in edits.items():
            self.assertEqual(getattr(dialog, name).text(), value, name)
        self.assertEqual(dialog.sensor_element_combo.currentData(), target)
        self.assertIn(key, dialog.property_drafts.pending)
        self.assertEqual(dialog.undo_stack.count(), 0)

    def test_arc_draft_applies_once_and_undo_restores_geometry(self):
        project = PathBeamEditor.create_circular_arc(
            empty_beam_project(), radius=2.0, sweep_degrees=60.0, plane="xy"
        )
        dialog = self.dialog(project)
        element = project.elements[0]
        self.select(dialog, "element", element)
        dialog.arc_radius_edit.setText("3.25")
        dialog.arc_sweep_edit.setText("80")
        self.select(dialog, "node", project.nodes[0])
        self.select(dialog, "element", element)
        self.assertEqual(dialog.arc_radius_edit.text(), "3.25")
        self.assertEqual(dialog.arc_sweep_edit.text(), "80")
        self.assertTrue(dialog._update_element_property())
        self.assertEqual(dialog.undo_stack.count(), 1)
        self.assertEqual(dialog.project.elements[0].geometry.parameters["radius"], 3.25)
        self.assertFalse(dialog.property_drafts.pending)
        dialog.undo_stack.undo()
        self.assertEqual(dialog.project.to_dict(), project.to_dict())
        self.assertEqual(float(dialog.arc_radius_edit.text()), 2.0)
        self.assertFalse(dialog.property_drafts.pending)

    def test_section_shape_variants_keep_inputs_and_reset_to_model(self):
        dialog = self.dialog(empty_beam_project())
        original_shape = dialog.section_shape_combo.currentData()
        original_size = dialog.section_parameter_edits[0].text()
        dialog.section_parameter_edits[0].setText("1e-")
        dialog.section_shape_combo.setCurrentIndex(dialog.section_shape_combo.findData("box"))
        for edit, text in zip(dialog.section_parameter_edits, ("0.24", "0.12", "0.015")):
            edit.setText(text)
        dialog.section_shape_combo.setCurrentIndex(dialog.section_shape_combo.findData(original_shape))
        self.assertEqual(dialog.section_parameter_edits[0].text(), "1e-")
        dialog.section_shape_combo.setCurrentIndex(dialog.section_shape_combo.findData("box"))
        self.assertEqual([edit.text() for edit in dialog.section_parameter_edits[:3]], ["0.24", "0.12", "0.015"])
        dialog.property_drafts.reset("primary")
        self.assertEqual(dialog.section_shape_combo.currentData(), original_shape)
        self.assertEqual(dialog.section_parameter_edits[0].text(), original_size)
        self.assertFalse(dialog.property_drafts.pending)

    def test_section_diameter_draft_retains_circle_schema_after_undo_to_rectangle(self):
        dialog = self.dialog(empty_beam_project())
        dialog.section_shape_combo.setCurrentIndex(dialog.section_shape_combo.findData("circle"))
        dialog.section_parameter_edits[0].setText("0.2")
        self.assertTrue(dialog._update_primary_properties())
        self.assertEqual(dialog.project.sections[0].shape, "circle")
        dialog.section_parameter_edits[0].setText("0.35")
        dialog.undo_stack.undo()
        self.assertEqual(dialog.project.sections[0].shape, "rectangle")
        self.assertEqual(dialog.section_shape_combo.currentData(), "circle")
        self.assertEqual(dialog.section_parameter_edits[0].text(), "0.35")
        self.assertIn("直径", dialog.section_parameter_labels[0].text())
        self.assertIn(GLOBAL_KEY, dialog.property_drafts.pending)
        self.assertTrue(dialog._update_primary_properties())
        section = dialog.project.sections[0]
        self.assertEqual(section.shape, "circle")
        self.assertEqual(section.parameters, {"diameter": 0.35})
        self.assertFalse(dialog.property_drafts.pending)

    def test_apply_all_commits_multiple_groups_as_one_undo_step(self):
        dialog = self.dialog()
        original = dialog.project.to_dict()
        sensor = dialog.project.sensors[0]
        node = dialog.project.nodes[0]
        dialog.material_e_edit.setText("70")
        self.select(dialog, "sensor", sensor)
        dialog.sensor_label_edit.setText("已应用测点")
        self.select(dialog, "node", node)
        dialog.node_y_edit.setText("0.025")
        self.assertEqual(len(dialog.property_drafts.pending), 3)
        self.assertTrue(dialog.property_drafts.apply_all())
        self.assertEqual(dialog.undo_stack.count(), 1)
        self.assertFalse(dialog.property_drafts.pending)
        self.assertEqual(dialog.project.materials[0].elastic_modulus, 70e9)
        self.assertEqual(next(s for s in dialog.project.sensors if s.identifier == sensor.identifier).label, "已应用测点")
        dialog.undo_stack.undo()
        self.assertEqual(dialog.project.to_dict(), original)
        self.assertFalse(dialog.property_drafts.pending)

    def test_invalid_batch_is_atomic_and_targets_inline_error(self):
        dialog = self.dialog(empty_beam_project())
        dialog.show()
        self.app.processEvents()
        original = dialog.project.to_dict()
        dialog.material_e_edit.setText("70")
        key = self.select(dialog, "node", dialog.project.nodes[0])
        dialog.node_y_edit.setText("1e-")
        pending = {key: dict(value) for key, value in dialog.property_drafts.pending.items()}
        with patch.object(QMessageBox, "warning") as warning:
            self.assertFalse(dialog.property_drafts.apply_all())
        warning.assert_not_called()
        self.assertEqual(dialog.project.to_dict(), original)
        self.assertEqual(dialog.undo_stack.count(), 0)
        self.assertEqual(dialog.property_drafts.pending, pending)
        self.assertIn(key, dialog.property_drafts.pending)
        self.assertEqual(dialog.node_y_edit.text(), "1e-")
        self.assertEqual(dialog.property_feedback["node"].property("state"), "error")
        self.assertEqual(dialog.node_y_edit.property("validationState"), "error")
        self.assertTrue(dialog.node_y_edit.hasFocus())

    def test_minimum_window_error_field_is_visible_and_selector_tracks_error_group(self):
        dialog = self.dialog(empty_beam_project())
        dialog.resize(1040, 680)
        dialog.show()
        self.app.processEvents()
        node = dialog.project.nodes[0]
        node_key = self.select(dialog, "node", node)
        dialog.node_y_edit.setText("0.15")
        dialog.section_shape_combo.setCurrentIndex(dialog.section_shape_combo.findData("box"))
        for edit, text in zip(dialog.section_parameter_edits, ("0.24", "0.12", "0.08")):
            edit.setText(text)
        self.select(dialog, "node", node)
        self.assertEqual(tuple(dialog.draft_selector.currentData()), node_key)
        self.assertFalse(dialog.property_drafts.apply_all())
        QTest.qWait(40)
        self.assertEqual(dialog.width(), 1040)
        self.assertEqual(dialog.height(), 680)
        self.assertEqual(dialog.inspector_tabs.currentIndex(), 0)
        self.assertEqual(tuple(dialog.draft_selector.currentData()), GLOBAL_KEY)
        field = dialog.section_parameter_edits[2]
        self.assertEqual(field.property("validationState"), "error")
        self.assertTrue(field.hasFocus())
        viewport = dialog.inspector_tabs.widget(0).viewport()
        field_rect = QRect(field.mapTo(viewport, QPoint(0, 0)), field.size())
        self.assertTrue(
            viewport.rect().contains(field_rect),
            f"错误字段被裁切: field={field_rect}, viewport={viewport.rect()}",
        )

    def test_deleted_object_draft_blocks_apply_and_returns_after_undo(self):
        dialog = self.dialog()
        sensor = dialog.project.sensors[0]
        key = self.select(dialog, "sensor", sensor)
        dialog.sensor_label_edit.setText("删除前草稿")
        dialog._delete_selected()
        self.assertIn(key, dialog.property_drafts.pending)
        after_delete = dialog.project.to_dict()
        self.assertFalse(dialog.property_drafts.apply_all())
        self.assertEqual(dialog.project.to_dict(), after_delete)
        self.assertEqual(dialog.undo_stack.count(), 1)
        dialog.undo_stack.undo()
        self.select(dialog, "sensor", sensor)
        self.assertEqual(dialog.sensor_label_edit.text(), "删除前草稿")
        self.assertTrue(dialog.property_drafts.apply_all())
        self.assertEqual(next(s for s in dialog.project.sensors if s.identifier == sensor.identifier).label, "删除前草稿")

    def test_draft_navigation_and_explicit_discard_leave_model_untouched(self):
        dialog = self.dialog()
        before = dialog.project.to_dict()
        node_key = self.select(dialog, "node", dialog.project.nodes[0])
        dialog.node_y_edit.setText("0.25")
        sensor_key = self.select(dialog, "sensor", dialog.project.sensors[0])
        dialog.sensor_weight_edit.setText("3")
        self.assertEqual(dialog.draft_selector.count(), 2)
        self.assertIn("2", dialog.draft_summary.text())
        index = next(
            index for index in range(dialog.draft_selector.count())
            if tuple(dialog.draft_selector.itemData(index)) == node_key
        )
        dialog.draft_selector.activated.emit(index)
        self.assertEqual((dialog.selected_kind, dialog.selected_id), node_key)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            dialog.property_drafts.discard_all()
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
        self.assertEqual(set(dialog.property_drafts.pending), {node_key, sensor_key})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            dialog.property_drafts.discard_all()
        self.assertFalse(dialog.property_drafts.pending)
        self.assertEqual(dialog.project.to_dict(), before)
        self.assertEqual(dialog.undo_stack.count(), 0)
        self.assertEqual(float(dialog.node_y_edit.text()), 0.0)

    def test_save_validates_drafts_before_writing_and_persists_applied_values(self):
        dialog = self.dialog(empty_beam_project())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft-save.ifem.json"
            save_project(path, dialog.project)
            dialog.set_project_storage(None, path, project_is_saved=True)
            self.assertTrue(dialog.project_is_saved)
            self.select(dialog, "node", dialog.project.nodes[0])
            dialog.node_y_edit.setText("-")
            self.assertFalse(dialog.project_is_saved)
            with patch("ifem.ui.modeler.save_project") as write:
                dialog._save_project()
            write.assert_not_called()
            self.assertEqual(dialog.node_y_edit.text(), "-")
            dialog.node_y_edit.setText("0.2")
            dialog._save_project()
            saved = load_project(path)
            self.assertEqual(saved.nodes[0].coordinates[1], 0.2)
            self.assertTrue(dialog.project_is_saved)
            self.assertFalse(dialog.property_drafts.pending)
            self.assertNotIn("draft", path.read_text().lower())

    def test_saved_state_uses_content_when_undo_branch_reuses_revision(self):
        dialog = self.dialog(empty_beam_project())
        node = dialog.project.nodes[0]
        self.select(dialog, "node", node)
        dialog.node_y_edit.setText("0.1")
        self.assertTrue(dialog._update_node_property())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "revision-branch.ifem.json"
            save_project(path, dialog.project)
            dialog.set_project_storage(None, path, project_is_saved=True)
            saved_revision = dialog.project.revision
            saved_bytes = path.read_bytes()
            self.assertTrue(dialog.project_is_saved)
            dialog.undo_stack.undo()
            self.select(dialog, "node", node)
            dialog.node_y_edit.setText("0.2")
            self.assertTrue(dialog._update_node_property())
            self.assertEqual(dialog.project.revision, saved_revision)
            self.assertFalse(dialog.property_drafts.pending)
            self.assertFalse(dialog.project_is_saved)
            self.assertEqual(path.read_bytes(), saved_bytes)
            self.assertEqual(load_project(path).nodes[0].coordinates[1], 0.1)

    def test_discard_selected_orphan_keeps_other_drafts_and_model_history(self):
        dialog = self.dialog()
        node = dialog.project.nodes[0]
        sensor = dialog.project.sensors[0]
        node_key = self.select(dialog, "node", node)
        dialog.node_y_edit.setText("0.15")
        sensor_key = self.select(dialog, "sensor", sensor)
        dialog.sensor_label_edit.setText("待放弃的孤立草稿")
        dialog._delete_selected()
        deleted_state = dialog.project.to_dict()
        index = dialog.draft_selector.findData(list(sensor_key))
        self.assertGreaterEqual(index, 0)
        dialog.draft_selector.setCurrentIndex(index)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            dialog.draft_discard_selected.click()
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
        self.assertEqual(set(dialog.property_drafts.pending), {node_key, sensor_key})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            dialog.draft_discard_selected.click()
        self.assertEqual(set(dialog.property_drafts.pending), {node_key})
        self.assertEqual(dialog.project.to_dict(), deleted_state)
        self.assertEqual(dialog.undo_stack.count(), 1)
        dialog.undo_stack.undo()
        self.select(dialog, "sensor", sensor)
        self.assertEqual(dialog.sensor_label_edit.text(), sensor.label)
        self.select(dialog, "node", node)
        self.assertEqual(dialog.node_y_edit.text(), "0.15")

    def test_workspace_accept_stops_on_invalid_draft_then_applies_valid_input(self):
        dialog = self.dialog(empty_beam_project())
        dialog.show()
        self.select(dialog, "node", dialog.project.nodes[0])
        dialog.node_y_edit.setText("1e-")
        before = dialog.project.to_dict()
        with patch.object(dialog, "shutdown") as shutdown:
            dialog.accept()
        shutdown.assert_not_called()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.project.to_dict(), before)
        dialog.node_y_edit.setText("0.3")
        with patch.object(QMessageBox, "question") as question:
            dialog.accept()
        question.assert_not_called()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.project.nodes[0].coordinates[1], 0.3)
        self.assertFalse(dialog.property_drafts.pending)

    def test_draft_only_exit_can_be_cancelled_for_all_dialog_exit_paths(self):
        for action in ("reject", "close", "done", "escape"):
            with self.subTest(action=action):
                dialog = self.dialog(empty_beam_project())
                dialog.show()
                self.select(dialog, "node", dialog.project.nodes[0])
                dialog.node_y_edit.setText("-")
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question, patch.object(dialog, "shutdown") as shutdown:
                    if action == "done":
                        dialog.done(QDialog.DialogCode.Rejected)
                    elif action == "escape":
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
                    else:
                        getattr(dialog, action)()
                question.assert_called_once()
                shutdown.assert_not_called()
                self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
                self.assertTrue(dialog.isVisible())
                self.assertEqual(dialog.node_y_edit.text(), "-")
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                    dialog.reject()
                self.assertFalse(dialog.isVisible())

    def test_open_cancel_preserves_draft_path_selection_and_history(self):
        dialog = self.dialog(empty_beam_project())
        before = dialog.project
        moved = PathBeamEditor.move_node(before, before.nodes[0].identifier, (0.1, 0.0, 0.0))
        dialog._commit_project(before, moved, "已有编辑")
        key = self.select(dialog, "node", before.nodes[0])
        dialog.node_y_edit.setText("1e-")
        with tempfile.TemporaryDirectory() as directory:
            original_path = Path(directory) / "original.ifem.json"
            replacement_path = Path(directory) / "replacement.ifem.json"
            save_project(original_path, moved)
            save_project(replacement_path, empty_beam_project("另一个项目"))
            dialog.set_project_storage(None, original_path, project_is_saved=True)
            with patch.object(ProjectLibraryDialog, "choose_project", return_value=None), patch.object(QMessageBox, "question") as question:
                dialog._open_project()
            question.assert_not_called()
            with patch.object(ProjectLibraryDialog, "choose_project", return_value=replacement_path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
                dialog._open_project()
            question.assert_called_once()
            self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
            self.assertEqual(dialog.project.to_dict(), moved.to_dict())
            self.assertEqual(dialog.project_path, original_path.resolve())
            self.assertEqual((dialog.selected_kind, dialog.selected_id), key)
            self.assertEqual(dialog.node_y_edit.text(), "1e-")
            self.assertEqual(dialog.undo_stack.count(), 1)

    def test_failed_open_preflight_keeps_old_drafts_and_undo_without_prompt(self):
        dialog = self.dialog(empty_beam_project())
        key = self.select(dialog, "node", dialog.project.nodes[0])
        dialog.node_y_edit.setText("0.2")
        before = dialog.project.to_dict()
        for failing_stage in ("load_project", "PathBeamEditor.ordered_path"):
            with self.subTest(stage=failing_stage):
                with patch.object(ProjectLibraryDialog, "choose_project", return_value=Path("/unread-project.ifem.json")), patch("ifem.ui.modeler.load_project", return_value=empty_beam_project("新项目")), patch(f"ifem.ui.modeler.{failing_stage}", side_effect=ValueError("损坏项目")), patch.object(QMessageBox, "question") as question, patch.object(QMessageBox, "critical") as critical:
                    dialog._open_project()
                question.assert_not_called()
                critical.assert_called_once()
                self.assertEqual(dialog.project.to_dict(), before)
                self.assertIn(key, dialog.property_drafts.pending)
                self.assertEqual(dialog.node_y_edit.text(), "0.2")
                self.assertEqual(dialog.undo_stack.count(), 0)

    def test_open_discard_clears_old_drafts_even_for_reused_entity_ids(self):
        original = empty_beam_project("进入工作台的模型")
        dialog = self.dialog(original)
        original_baseline = dict(dialog._workspace_baseline)
        node = original.nodes[0]
        self.select(dialog, "node", node)
        dialog.node_y_edit.setText("1e-")
        replacement = PathBeamEditor.move_node(original, node.identifier, (0.0, 0.4, 0.0)).revised(name="同 ID 的另一个文件")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reused-identities.ifem.json"
            save_project(path, replacement)
            with patch.object(ProjectLibraryDialog, "choose_project", return_value=path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                dialog._open_project()
            self.assertEqual(dialog.project.to_dict(), replacement.to_dict())
            self.assertEqual(dialog.project_path, path)
            self.assertTrue(dialog.project_is_saved)
            self.assertFalse(dialog.property_drafts.pending)
            self.assertEqual(dialog.undo_stack.count(), 0)
            self.assertEqual(dialog._workspace_baseline, original_baseline)
            self.select(dialog, "node", node)
            self.assertEqual(float(dialog.node_y_edit.text()), 0.4)
            self.assertFalse(dialog.property_drafts.pending)

    def test_open_save_choice_requires_success_then_saves_old_model_before_switch(self):
        original = empty_beam_project("旧模型")
        replacement = empty_beam_project("新模型")
        dialog = self.dialog(original)
        self.select(dialog, "node", original.nodes[0])
        dialog.node_y_edit.setText("-")
        with tempfile.TemporaryDirectory() as directory:
            old_path = Path(directory) / "old.ifem.json"
            new_path = Path(directory) / "new.ifem.json"
            save_project(old_path, original)
            save_project(new_path, replacement)
            dialog.set_project_storage(None, old_path, project_is_saved=True)
            with patch.object(ProjectLibraryDialog, "choose_project", return_value=new_path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                dialog._open_project()
            self.assertEqual(dialog.project.to_dict(), original.to_dict())
            self.assertEqual(dialog.project_path, old_path.resolve())
            self.assertEqual(dialog.node_y_edit.text(), "-")
            self.assertEqual(load_project(old_path).nodes[0].coordinates[1], 0.0)
            dialog.node_y_edit.setText("0.2")
            with patch.object(ProjectLibraryDialog, "choose_project", return_value=new_path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                dialog._open_project()
            self.assertEqual(load_project(old_path).nodes[0].coordinates[1], 0.2)
            self.assertEqual(dialog.project.to_dict(), replacement.to_dict())
            self.assertEqual(dialog.project_path, new_path)
            self.assertFalse(dialog.property_drafts.pending)
            self.assertEqual(dialog.undo_stack.count(), 0)

    def test_saving_and_opening_same_file_does_not_restore_preloaded_old_snapshot(self):
        original = empty_beam_project("同一个项目文件")
        dialog = self.dialog(original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "same-file.ifem.json"
            save_project(path, original)
            dialog.set_project_storage(None, path, project_is_saved=True)
            self.select(dialog, "node", original.nodes[0])
            dialog.node_y_edit.setText("0.4")
            with patch.object(ProjectLibraryDialog, "choose_project", return_value=path), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                dialog._open_project()
            self.assertEqual(dialog.project.nodes[0].coordinates[1], 0.4)
            self.assertEqual(load_project(path).nodes[0].coordinates[1], 0.4)
            self.assertTrue(dialog.project_is_saved)
            self.assertFalse(dialog.property_drafts.pending)
            self.assertEqual(dialog.undo_stack.count(), 0)


if __name__ == "__main__":
    unittest.main()
