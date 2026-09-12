import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

import gui_qt
from config_adapter import get_sample_config
from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm
from ifem.application.analysis_service import AlgorithmRegistry, AnalysisService
from ifem.domain.analysis import AlgorithmMetadata, ValidationReport
from ifem.domain.project import AnalysisCase, empty_beam_project
from ifem.infrastructure import load_project, project_from_legacy_config, save_project
from ifem.modeling import BeamProjectEditor, PathBeamEditor
from ifem.modeling.section_geometry import section_boundary_point
from ifem.ui.modeler import (
    BeamModelCanvas,
    BeamModelerDialog,
    SensorArrayDialog,
    SpatialCurveDialog,
)
from ifem.ui.modeler_3d import BeamGeometry3DView
from visualization_3d import Structure3DView


class ModelerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._question_patcher = patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Discard,
        )
        self._question_patcher.start()
        self.addCleanup(self._question_patcher.stop)

    def test_canvas_click_inserts_node_and_undo_restores_model(self):
        project = project_from_legacy_config(get_sample_config())
        dialog = BeamModelerDialog(project)
        dialog.resize(1100, 700)
        dialog.show()
        self.app.processEvents()

        before_node_ids = {node.identifier for node in dialog.project.nodes}
        dialog.mode_buttons[BeamModelCanvas.MODE_ADD_NODE].click()
        click_position = QPoint(
            round(dialog.canvas._x_to_pixel(1.5)),
            round(dialog.canvas._beam_y()),
        )
        QTest.mouseClick(
            dialog.canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            click_position,
        )
        self.app.processEvents()

        self.assertEqual(len(dialog.project.nodes), 5)
        self.assertEqual(len(dialog.project.elements), 4)
        self.assertEqual(len(dialog.project.sensors), 12)
        self.assertNotEqual(
            {node.identifier for node in dialog.project.nodes},
            before_node_ids,
        )

        dialog.undo_stack.undo()
        self.assertEqual(len(dialog.project.nodes), 4)
        self.assertEqual(
            {node.identifier for node in dialog.project.nodes},
            before_node_ids,
        )
        dialog.close()

    def test_main_window_applies_modeler_project_and_can_reconstruct(self):
        window = gui_qt.ReconstructionMainWindow()
        edited_project = BeamProjectEditor.add_node(
            window.current_project_document,
            0.5,
        )

        class AcceptedModeler:
            def __init__(self, _project, _parent=None):
                self.project = edited_project

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch.object(gui_qt, "BeamModelerDialog", AcceptedModeler):
            window.open_interactive_modeler()

        self.assertEqual(window.node_x_edit.text(), "0, 0.5, 1, 2, 3")
        self.assertEqual(len(window.measurement_editor.get_rows()), 12)
        self.assertEqual(window.run_status_label.text(), "模型已更新 · 待运行")

        window.run_reconstruction()
        self.assertEqual(window.current_model.n_nodes, 5)
        self.assertEqual(window.current_model.n_elems, 4)
        self.assertEqual(window.run_status_label.property("state"), "success")
        window.close()

    def test_main_window_exposes_primary_action_shortcuts(self):
        window = gui_qt.ReconstructionMainWindow()

        self.assertEqual(window.modeler_button.shortcut().toString(), "Ctrl+M")
        self.assertEqual(window.run_button.shortcut().toString(), "Ctrl+Return")
        self.assertFalse(hasattr(window, "appearance_action"))
        self.assertFalse(hasattr(window, "show_appearance_settings"))
        self.assertNotIn(
            "Ctrl+,",
            [action.shortcut().toString() for action in window.findChildren(QAction)],
        )
        self.assertTrue(window.measurement_editor.header_action_button.toolTip())
        window.close()

    def test_single_algorithm_uses_card_without_redundant_selector(self):
        window = gui_qt.ReconstructionMainWindow()
        setup = window.analysis_setup

        self.assertTrue(setup.algorithm_selector_row.isHidden())
        self.assertEqual(setup.algorithm_selector.count(), 0)
        self.assertEqual(
            setup.active_algorithm_id,
            BeamSurfaceIntegralAlgorithm.metadata.identifier,
        )
        self.assertEqual(setup.algorithm_selector.currentIndex(), -1)
        self.assertEqual(setup.algorithm_state_label.text(), "可求解")
        self.assertEqual(
            setup.algorithm_name_label.text(),
            BeamSurfaceIntegralAlgorithm.metadata.display_name,
        )
        self.assertEqual(setup.method_card.accessibleName(), "当前重构方法")
        self.assertEqual(setup.algorithm_selector_label.text(), "切换方法")
        self.assertEqual(
            window.analysis_metric_title_labels["solver"].text(),
            "重构方法",
        )
        self.assertIn("仅安装此方法", setup.algorithm_feedback_label.text())
        self.assertIn(
            BeamSurfaceIntegralAlgorithm.metadata.display_name,
            setup.method_card.accessibleDescription(),
        )
        self.assertIn(
            "不会改变用户设置的积分区间",
            setup.parameter_editor("gauss_n").toolTip(),
        )
        self.assertIn(
            "不参与方程组装",
            setup.parameter_editor("points_per_element").toolTip(),
        )
        self.assertEqual(
            setup.parameter_values(),
            {"gauss_n": 3, "points_per_element": 120},
        )

        setup.set_parameter_values({"gauss_n": 4, "points_per_element": 160})
        config = window._build_form_config()
        self.assertEqual(config["gauss_n"], 4)
        self.assertEqual(config["points_per_element"], 160)
        window.close()

    def test_input_readiness_marks_invalid_field_without_modal_error(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        self.app.processEvents()

        self.assertFalse(window.project_dirty)
        window.node_x_edit.setText("0, 1, invalid")
        self.app.processEvents()

        self.assertTrue(window.project_dirty)
        self.assertFalse(window.run_button.isEnabled())
        self.assertEqual(window.node_x_edit.property("validationState"), "error")
        self.assertIn("·", window.left_tabs.tabText(0))
        self.assertEqual(window.left_tabs.currentIndex(), 0)

        window.run_reconstruction()
        self.assertTrue(window.node_x_edit.hasFocus())
        window.close()

    def test_readiness_badge_and_empty_state_are_actionable(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        self.app.processEvents()

        self.assertIs(
            window.plot_content_stack.currentWidget(),
            window.analysis_empty_state,
        )
        self.assertEqual(window.analysis_empty_state.action_button.text(), "运行重构")

        window.node_x_edit.setText("0, invalid")
        self.app.processEvents()
        self.assertIn("需检查", window.input_status_label.text())
        self.assertEqual(
            window.analysis_empty_state.action_button.text(),
            "定位首个问题",
        )

        window.input_status_label.click()
        self.app.processEvents()
        self.assertEqual(window.left_tabs.currentIndex(), 0)
        self.assertTrue(window.node_x_edit.hasFocus())
        window.close()

    def test_structured_measurement_issue_focuses_exact_row_and_field(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        self.app.processEvents()
        rows = window.measurement_editor.get_rows()
        rows[2]["strain"] = "invalid"
        window.measurement_editor.set_rows(rows)
        self.app.processEvents()

        self.assertEqual(
            window._readiness_issues[0]["field"],
            "/measurements/2/strain",
        )
        window.input_status_label.click()
        self.app.processEvents()

        self.assertEqual(window.left_tabs.currentIndex(), 1)
        self.assertEqual(window.measurement_editor.table.currentRow(), 2)
        self.assertTrue(window.measurement_editor.inputs["strain"].hasFocus())
        window.close()

    def test_plugin_validation_field_focuses_dynamic_parameter_editor(self):
        class FieldFailingAlgorithm(BeamSurfaceIntegralAlgorithm):
            def validate(self, context):
                return ValidationReport.invalid(
                    "请检查高斯点数。",
                    field="/analysis/parameters/gauss_n",
                )

        algorithm = FieldFailingAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        window.show()
        self.app.processEvents()

        editor = window.analysis_setup.parameter_editor("gauss_n")
        self.assertIsNotNone(editor)
        self.assertEqual(editor.property("validationState"), "error")
        self.assertEqual(
            window._readiness_issues[0]["field"],
            "/analysis/parameters/gauss_n",
        )
        window.input_status_label.click()
        self.app.processEvents()

        self.assertEqual(window.left_tabs.currentIndex(), 0)
        self.assertTrue(editor.hasFocus())
        window.close()

    def test_rank_deficiency_marks_method_unsolvable_and_focuses_method_card(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        self.app.processEvents()
        original_rows = window.measurement_editor.get_rows()
        rows = [dict(row) for row in original_rows]
        for row in rows:
            row["surface"] = "top"
        window.measurement_editor.set_rows(rows)
        self.app.processEvents()
        window._refresh_input_readiness()

        issue = next(
            item
            for item in window._readiness_issues
            if item["field"] == "/analysis/solvability"
        )
        self.assertIn("秩", issue["message"])
        self.assertEqual(
            window.analysis_setup.algorithm_state_label.text(),
            "不可求解",
        )
        self.assertIn(
            "秩",
            window.analysis_setup.algorithm_feedback_label.text(),
        )
        self.assertTrue(window.analysis_setup.algorithm_selector_row.isHidden())
        self.assertIn("不可求解", window.input_status_label.text())
        self.assertEqual(
            window.run_status_label.text(),
            "当前重构方法不可求解",
        )
        self.assertFalse(window.run_button.isEnabled())

        window.input_status_label.click()
        self.app.processEvents()

        self.assertEqual(window.left_tabs.currentIndex(), 0)
        self.assertTrue(window.analysis_setup.method_card.hasFocus())

        window.measurement_editor.set_rows(original_rows)
        window._refresh_input_readiness()

        self.assertFalse(
            window.analysis_setup.method_card.property("validationState")
        )
        self.assertNotIn("秩", window.analysis_setup.method_card.toolTip())
        self.assertEqual(
            window.analysis_setup.algorithm_state_label.text(),
            "可求解",
        )
        window.close()

    def test_stale_result_is_preserved_and_visibly_marked_until_rerun(self):
        window = gui_qt.ReconstructionMainWindow()
        window.run_reconstruction()
        original_rows = window.node_result_table.table.rowCount()

        window.thickness_edit.setText("0.0017")
        self.app.processEvents()

        self.assertTrue(window.results_stale)
        self.assertFalse(window.result_freshness_label.isHidden())
        self.assertIn("已过期", window.result_group.title())
        self.assertEqual(window.node_result_table.table.rowCount(), original_rows)

        window.run_reconstruction()
        self.assertFalse(window.results_stale)
        self.assertNotIn("已过期", window.result_group.title())
        window.close()

    def test_failed_postprocessing_restores_last_result_as_stale(self):
        window = gui_qt.ReconstructionMainWindow()
        window.run_reconstruction()
        previous_model = window.current_model
        previous_first_value = window.node_result_table.table.item(0, 2).text()
        window.thickness_edit.setText("0.0017")

        with patch.object(
            gui_qt,
            "element_boundary_jumps",
            side_effect=RuntimeError("forced postprocess failure"),
        ), patch.object(gui_qt.QMessageBox, "critical"):
            window.run_reconstruction()

        self.assertIs(window.current_model, previous_model)
        self.assertEqual(
            window.node_result_table.table.item(0, 2).text(),
            previous_first_value,
        )
        self.assertTrue(window.results_stale)
        self.assertEqual(window.run_status_label.property("state"), "error")
        window.close()

    def test_busy_state_cannot_be_reenabled_and_exits_before_error_dialog(self):
        window = gui_qt.ReconstructionMainWindow()
        observed = {}

        def fail_while_busy(*_args, **_kwargs):
            observed["busy_before_refresh"] = window._analysis_busy
            observed["button_text"] = window.run_button.text()
            window._refresh_input_readiness()
            observed["button_enabled_after_refresh"] = window.run_button.isEnabled()
            observed["action_enabled_after_refresh"] = window.run_action.isEnabled()
            observed["status_enabled_after_refresh"] = (
                window.input_status_label.isEnabled()
            )
            raise RuntimeError("forced solver failure")

        def inspect_error_dialog(*_args, **_kwargs):
            observed["busy_during_dialog"] = window._analysis_busy
            observed["text_during_dialog"] = window.run_button.text()
            return QMessageBox.StandardButton.Ok

        with patch.object(
            window.analysis_service,
            "run",
            side_effect=fail_while_busy,
        ), patch.object(
            gui_qt.QMessageBox,
            "critical",
            side_effect=inspect_error_dialog,
        ):
            window.run_reconstruction()

        self.assertTrue(observed["busy_before_refresh"])
        self.assertEqual(observed["button_text"], "计算中…")
        self.assertFalse(observed["button_enabled_after_refresh"])
        self.assertFalse(observed["action_enabled_after_refresh"])
        self.assertFalse(observed["status_enabled_after_refresh"])
        self.assertFalse(observed["busy_during_dialog"])
        self.assertEqual(observed["text_during_dialog"], "运行重构")
        self.assertFalse(window._analysis_busy)
        window.close()

    def test_result_row_can_be_copied_as_tsv(self):
        window = gui_qt.ReconstructionMainWindow()
        window.run_reconstruction()
        window.show()
        window.result_tabs.setCurrentIndex(window.node_result_tab_index)
        self.app.processEvents()
        table = window.node_result_table.table
        table.selectRow(0)
        table.setFocus()
        QApplication.clipboard().clear()

        QTest.keySequence(table, QKeySequence.StandardKey.Copy)
        self.app.processEvents()
        copied = QApplication.clipboard().text()
        self.assertEqual(len(copied.split("\t")), table.columnCount())
        self.assertEqual(copied.split("\t")[0], table.item(0, 0).text())
        window.close()

    def test_workspace_navigation_shortcuts_have_scoped_actions(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        self.app.processEvents()

        self.assertEqual(window.run_action.shortcut().toString(), "F5")
        self.assertEqual(
            [action.shortcut().toString() for action in window.view_shortcut_actions],
            ["Ctrl+1", "Ctrl+2", "Ctrl+3"],
        )
        self.assertEqual(
            [action.shortcut().toString() for action in window.input_tab_actions],
            ["Alt+1", "Alt+2", "Alt+3", "Alt+4", "Alt+5"],
        )
        window._focus_input_tab(4)
        self.app.processEvents()
        self.assertEqual(window.left_tabs.currentIndex(), 4)
        self.assertTrue(window.json_text.hasFocus())
        window.close()

    def test_field_feedback_targets_thickness_and_clears_stale_tooltip(self):
        window = gui_qt.ReconstructionMainWindow()
        base_tooltip = window.thickness_edit.toolTip()

        window.thickness_edit.setText("not-a-number")
        self.app.processEvents()

        self.assertEqual(window.thickness_edit.property("validationState"), "error")
        self.assertIn("厚度", window.thickness_edit.toolTip())
        self.assertFalse(window.run_button.isEnabled())

        window.thickness_edit.setText("0.0016")
        self.app.processEvents()

        self.assertNotEqual(window.thickness_edit.property("validationState"), "error")
        self.assertEqual(window.thickness_edit.toolTip(), base_tooltip)
        window.close()

    def test_measurement_parse_error_is_reported_on_sensor_tab(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        editor = window.measurement_editor
        editor.table.selectRow(0)
        editor.inputs["strain"].setText("invalid")
        editor.update_selected()
        self.app.processEvents()

        self.assertEqual(editor.count_label.property("state"), "error")
        self.assertIn("测量数据", editor.count_label.toolTip())
        self.assertIn("·", window.left_tabs.tabText(1))
        self.assertFalse(window.run_button.isEnabled())
        window.input_status_label.click()
        self.app.processEvents()
        self.assertEqual(window.left_tabs.currentIndex(), 1)
        self.assertTrue(editor.inputs["strain"].hasFocus())
        self.assertEqual(editor.inputs["strain"].selectedText(), "invalid")
        window.close()

    def test_mixed_display_and_algorithm_issues_keep_error_action(self):
        window = gui_qt.ReconstructionMainWindow()
        spatial_project = PathBeamEditor.create_circular_arc(
            window.current_project_document,
            radius=2.0,
            sweep_degrees=90.0,
            plane="xz",
        )
        window._apply_project_document(
            spatial_project,
            dirty=False,
            status_text="空间模型已载入",
        )
        window.show()
        window.y_min_edit.setText("invalid")
        window.y_max_edit.setText("1")
        self.app.processEvents()

        self.assertIn("需检查", window.input_status_label.text())
        self.assertNotIn("等待算法", window.input_status_label.text())
        self.assertEqual(
            window.analysis_empty_state.action_button.text(),
            "定位首个问题",
        )
        window.input_status_label.click()
        self.app.processEvents()
        self.assertTrue(window.display_settings_panel.isVisible())
        self.assertTrue(window.y_min_edit.hasFocus())
        window.close()

    def test_display_settings_are_saved_in_view_state(self):
        window = gui_qt.ReconstructionMainWindow()
        window.title_edit.setText("持久化结果标题")
        window.equal_axis_check.setChecked(True)
        self.app.processEvents()

        self.assertTrue(window.project_dirty)
        self.assertEqual(
            window.current_project_document.view_state["title"],
            "持久化结果标题",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "view-state.ifemproj"
            self.assertTrue(window._save_project_to(path))
            restored = load_project(path)

        self.assertEqual(restored.view_state["title"], "持久化结果标题")
        self.assertTrue(restored.view_state["equal_axis"])
        self.assertFalse(window.project_dirty)
        window.close()

    def test_spatial_project_save_keeps_entity_ids(self):
        window = gui_qt.ReconstructionMainWindow()
        spatial_project = PathBeamEditor.create_circular_arc(
            empty_beam_project(modeling_space="3d"),
            radius=2.0,
            sweep_degrees=90.0,
            plane="xz",
        )
        window._apply_project_document(
            spatial_project,
            dirty=True,
            status_text="三维项目已载入 · 待运行",
        )
        expected_ids = {
            key: tuple(getattr(spatial_project, key)[index].identifier for index in range(len(getattr(spatial_project, key))))
            for key in ("nodes", "elements", "materials", "sections")
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spatial.ifemproj"
            self.assertTrue(window._save_project_to(path))
            restored = load_project(path)

        for key, identifiers in expected_ids.items():
            self.assertEqual(
                tuple(item.identifier for item in getattr(restored, key)),
                identifiers,
            )
        self.assertEqual(restored.modeling_space, "3d")
        window.close()

    def test_spatial_project_rejects_invalid_unsaved_display_settings(self):
        window = gui_qt.ReconstructionMainWindow()
        spatial_project = PathBeamEditor.create_circular_arc(
            empty_beam_project(modeling_space="3d"),
            radius=2.0,
            sweep_degrees=90.0,
            plane="xz",
        )
        window._apply_project_document(
            spatial_project,
            dirty=False,
            status_text="三维项目已载入 · 待运行",
        )
        window.y_min_edit.setText("invalid")
        window.y_max_edit.setText("1")
        self.app.processEvents()

        self.assertEqual(window.display_settings_button.property("validationState"), "error")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-view.ifemproj"
            self.assertFalse(window._save_project_to(path))
            self.assertFalse(path.exists())
        self.assertTrue(window.project_dirty)
        window.close()

    def test_legacy_form_save_preserves_ids_labels_and_analysis_cases(self):
        window = gui_qt.ReconstructionMainWindow()
        project = window.current_project_document
        renamed_sensor = replace(project.sensors[0], label="SG-CUSTOM")
        secondary_case = AnalysisCase(
            identifier="analysis_secondary_test",
            name="备用分析工况",
            algorithm_id=project.analysis_cases[0].algorithm_id,
            parameters={"gauss_n": 2, "points_per_element": 80},
        )
        project = project.revised(
            sensors=(renamed_sensor, *project.sensors[1:]),
            analysis_cases=(*project.analysis_cases, secondary_case),
        )
        window._apply_project_document(
            project,
            dirty=False,
            status_text="项目已载入 · 待运行",
        )
        expected_ids = {
            key: tuple(item.identifier for item in getattr(project, key))
            for key in (
                "nodes",
                "elements",
                "sensors",
                "boundary_conditions",
                "materials",
                "sections",
                "analysis_cases",
            )
        }

        window.thickness_edit.setText("0.002")
        window.measurement_editor.table.selectRow(0)
        window.measurement_editor.inputs["strain"].setText("2.5e-4")
        window.measurement_editor.update_selected()
        saved_project = window._project_for_save()

        self.assertEqual(saved_project.identifier, project.identifier)
        for key, identifiers in expected_ids.items():
            self.assertEqual(
                tuple(item.identifier for item in getattr(saved_project, key)),
                identifiers,
            )
        self.assertEqual(saved_project.sensors[0].label, "SG-CUSTOM")
        self.assertEqual(saved_project.active_analysis_id, project.active_analysis_id)
        self.assertEqual(len(saved_project.analysis_cases), 2)
        window.close()

    def test_measurement_add_and_delete_preserve_unmodified_entity_ids(self):
        window = gui_qt.ReconstructionMainWindow()
        project = window.current_project_document
        renamed_sensor = replace(project.sensors[0], label="SG-PERSIST")
        project = project.revised(sensors=(renamed_sensor, *project.sensors[1:]))
        window._apply_project_document(
            project,
            dirty=False,
            status_text="项目已载入 · 待运行",
        )
        original_ids = {sensor.identifier for sensor in project.sensors}

        window.measurement_editor.set_form_values(
            {
                "element": "0",
                "x": "0.1",
                "surface": "top",
                "y": "",
                "strain": "1e-4",
                "weight": "1",
                "zone_a": "0.05",
                "zone_b": "0.15",
            }
        )
        window.measurement_editor.add_row()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensor-cycle.ifemproj"
            self.assertTrue(window._save_project_to(path))
            added_project = window.current_project_document
            added_ids = {sensor.identifier for sensor in added_project.sensors}
            added_row_id = window.measurement_editor.get_rows()[-1]["_entity_id"]

            self.assertTrue(original_ids.issubset(added_ids))
            self.assertEqual(len(added_ids - original_ids), 1)
            self.assertIn(added_row_id, added_ids - original_ids)
            self.assertEqual(
                next(
                    sensor
                    for sensor in added_project.sensors
                    if sensor.identifier == renamed_sensor.identifier
                ).label,
                "SG-PERSIST",
            )
            self.assertNotIn(
                "_entity_id",
                gui_qt.config_to_json(window._build_form_config()),
            )

            deleted_id = window.measurement_editor.get_rows()[1]["_entity_id"]
            window.measurement_editor.table.selectRow(1)
            window.measurement_editor.delete_selected()
            self.assertTrue(window._save_project_to(path))
            deleted_project = window.current_project_document
        remaining_ids = {sensor.identifier for sensor in deleted_project.sensors}

        self.assertEqual(remaining_ids, added_ids - {deleted_id})
        self.assertIn(added_row_id, remaining_ids)
        self.assertEqual(
            next(sensor for sensor in deleted_project.sensors if sensor.identifier == renamed_sensor.identifier).label,
            "SG-PERSIST",
        )
        window.close()

    def test_new_boundary_id_survives_second_save_without_reload(self):
        window = gui_qt.ReconstructionMainWindow()
        window.boundary_editor.set_form_values(
            {"node": "1", "dof": "u", "value": "0"}
        )
        window.boundary_editor.add_row()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boundary-cycle.ifemproj"
            self.assertTrue(window._save_project_to(path))
            row = window.boundary_editor.table.rowCount() - 1
            created_id = window.boundary_editor.get_rows()[row]["_entity_id"]

            window.boundary_editor.table.selectRow(row)
            window.boundary_editor.inputs["dof"].setCurrentText("phi")
            window.boundary_editor.update_selected()
            self.assertTrue(window._save_project_to(path))

        updated = next(
            boundary
            for boundary in window.current_project_document.boundary_conditions
            if boundary.identifier == created_id
        )
        self.assertEqual(updated.dof, "phi")
        self.assertEqual(
            window.boundary_editor.get_rows()[-1]["_entity_id"],
            created_id,
        )
        window.close()

    def test_boundary_attachment_edit_preserves_row_entity_id(self):
        window = gui_qt.ReconstructionMainWindow()
        original_project = window.current_project_document
        original_boundary_id = window.boundary_editor.get_rows()[0]["_entity_id"]

        window.boundary_editor.table.selectRow(0)
        window.boundary_editor.inputs["node"].setText("1")
        window.boundary_editor.inputs["dof"].setCurrentText("u")
        window.boundary_editor.update_selected()
        updated_project = window._project_for_save()

        updated_boundary = next(
            boundary
            for boundary in updated_project.boundary_conditions
            if boundary.identifier == original_boundary_id
        )
        ordered_nodes = sorted(updated_project.nodes, key=lambda node: node.coordinates[0])
        self.assertEqual(updated_boundary.node_id, ordered_nodes[1].identifier)
        self.assertEqual(updated_boundary.dof, "u")
        self.assertEqual(
            len(updated_project.boundary_conditions),
            len(original_project.boundary_conditions),
        )
        window.close()

    def test_invalid_thickness_scale_targets_display_settings_not_beam_thickness(self):
        window = gui_qt.ReconstructionMainWindow()
        window.thickness_scale_combo.setEditText("invalid")
        self.app.processEvents()

        self.assertEqual(window.display_settings_button.property("validationState"), "error")
        self.assertNotEqual(window.thickness_edit.property("validationState"), "error")
        self.assertFalse(window.run_button.isEnabled())
        window.close()

    def test_destructive_project_actions_honor_unsaved_cancel(self):
        window = gui_qt.ReconstructionMainWindow()
        window.title_edit.setText("尚未保存的标题")
        self.app.processEvents()

        with patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Cancel,
        ), patch.object(gui_qt, "BeamModelerDialog") as modeler_dialog:
            window.new_project()
            modeler_dialog.assert_not_called()

        with patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Cancel,
        ), patch.object(
            gui_qt.ProjectLibraryDialog, "choose_project"
        ) as open_dialog:
            window.open_project()
            open_dialog.assert_not_called()

        with patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            self.assertFalse(window.load_sample_data())
        self.assertEqual(window.title_edit.text(), "尚未保存的标题")

        with patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Discard,
        ):
            self.assertTrue(window.load_sample_data())
        self.assertTrue(window.project_dirty)
        window.close()

    def test_programmatic_close_honors_unsaved_cancel(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        window.title_edit.setText("尚未保存的标题")
        self.app.processEvents()

        with patch.object(window.structure_3d_view, "shutdown") as shutdown, patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as confirm:
            self.assertFalse(window.close())
            confirm.assert_called_once()
            shutdown.assert_not_called()
        self.assertTrue(window.isVisible())

        with patch.object(window.structure_3d_view, "shutdown") as shutdown, patch.object(
            gui_qt.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Discard,
        ):
            self.assertTrue(window.close())
            shutdown.assert_called_once()

    def test_modeler_reject_shuts_down_embedded_3d_view(self):
        dialog = BeamModelerDialog(empty_beam_project())

        with patch.object(dialog.geometry_3d_view, "shutdown") as shutdown:
            dialog.reject()

        shutdown.assert_called_once()

    def test_focus_mode_hides_and_restores_input_and_result_panels(self):
        window = gui_qt.ReconstructionMainWindow()
        window.show()
        self.app.processEvents()
        window.focus_mode_button.setChecked(True)
        self.assertFalse(window.left_panel.isVisible())
        self.assertFalse(window.result_group.isVisible())

        window.focus_mode_button.setChecked(False)
        self.assertTrue(window.left_panel.isVisible())
        self.assertTrue(window.result_group.isVisible())
        window.close()

    def test_algorithm_selector_appears_when_multiple_methods_are_compatible(self):
        class AlternateBeamAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.beam2d.alternate.test",
                display_name="测试梁重构方法",
                version="0.1.0",
                description="用于验证分析方案界面的插件发现行为。",
            )

        class BrokenValidationAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.beam2d.broken-validation.test",
                display_name="校验异常测试方法",
                version="0.1.0",
            )

            def validate(self, context):
                raise RuntimeError("third-party validation failed")

        primary = BeamSurfaceIntegralAlgorithm()
        alternate = AlternateBeamAlgorithm()
        broken = BrokenValidationAlgorithm()
        registry = AlgorithmRegistry((primary, alternate, broken))
        service = AnalysisService(
            registry,
            default_algorithm_id=primary.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        window.show()
        self.app.processEvents()
        setup = window.analysis_setup

        self.assertFalse(setup.algorithm_selector_row.isHidden())
        self.assertEqual(setup.algorithm_selector_label.text(), "切换方法")
        self.assertEqual(
            setup.algorithm_selector.placeholderText(),
            "选择其他重构方法…",
        )
        self.assertEqual(
            setup.algorithm_selector.accessibleName(),
            "切换重构方法",
        )
        self.assertIn(
            primary.metadata.display_name,
            setup.algorithm_selector.accessibleDescription(),
        )
        self.assertIs(
            setup.algorithm_selector_label.buddy(),
            setup.algorithm_selector,
        )
        self.assertEqual(setup.algorithm_selector.currentIndex(), -1)
        self.assertEqual(setup.algorithm_selector.count(), 2)
        self.assertEqual(
            setup.algorithm_selector.findData(primary.metadata.identifier),
            -1,
        )
        self.assertIn(
            "适用",
            setup.algorithm_selector.itemText(
                setup.algorithm_selector.findData(alternate.metadata.identifier)
            ),
        )
        alternate_index = setup.algorithm_selector.findData(
            alternate.metadata.identifier
        )
        self.assertEqual(alternate_index, 0)
        project_before_wheel = window.current_project_document
        parameters_before_wheel = setup.parameter_values()
        window.run_button.setFocus()
        selector_position = setup.algorithm_selector.mapTo(
            window,
            setup.algorithm_selector.rect().center(),
        )
        QTest.wheelEvent(
            window.windowHandle(),
            selector_position,
            QPoint(0, -120),
        )
        self.app.processEvents()
        self.assertEqual(setup.active_algorithm_id, primary.metadata.identifier)
        self.assertEqual(window.current_project_document, project_before_wheel)
        self.assertEqual(setup.parameter_values(), parameters_before_wheel)
        self.assertEqual(setup.algorithm_selector.currentIndex(), -1)

        setup.algorithm_selector.setFocus()
        QTest.keyClick(setup.algorithm_selector, Qt.Key.Key_Down)
        self.app.processEvents()
        self.assertEqual(
            setup.active_algorithm_id,
            alternate.metadata.identifier,
        )
        self.assertEqual(setup.algorithm_selector.currentIndex(), -1)
        self.assertGreaterEqual(
            setup.algorithm_selector.findData(primary.metadata.identifier),
            0,
        )
        self.assertEqual(
            window.analysis_metric_labels["solver"].text(),
            alternate.metadata.display_name,
        )
        active_case = next(
            case
            for case in window.current_project_document.analysis_cases
            if case.identifier == window.current_project_document.active_analysis_id
        )
        self.assertEqual(active_case.algorithm_id, alternate.metadata.identifier)
        self.assertEqual(active_case.algorithm_version, alternate.metadata.version)
        self.assertEqual(
            active_case.parameter_schema_version,
            alternate.metadata.parameter_schema_version,
        )
        self.assertEqual(
            window._project_for_interactive_modeler().analysis_cases[0].algorithm_id,
            alternate.metadata.identifier,
        )

        project_snapshot = window._project_for_save()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected-method.ifemproj"
            save_project(path, project_snapshot)
            reopened = load_project(path)
        reopened_case = next(
            case
            for case in reopened.analysis_cases
            if case.identifier == reopened.active_analysis_id
        )
        self.assertEqual(reopened_case.algorithm_id, alternate.metadata.identifier)
        self.assertEqual(reopened_case.algorithm_version, alternate.metadata.version)
        self.assertEqual(
            reopened_case.parameter_schema_version,
            alternate.metadata.parameter_schema_version,
        )
        self.assertEqual(reopened_case.parameters, active_case.parameters)

        broken_index = setup.algorithm_selector.findData(
            broken.metadata.identifier
        )
        self.assertGreaterEqual(broken_index, 0)
        setup.algorithm_selector.setCurrentIndex(broken_index)
        self.app.processEvents()
        self.assertEqual(setup.active_algorithm_id, broken.metadata.identifier)
        self.assertFalse(window.run_button.isEnabled())
        self.assertTrue(
            any(
                issue.get("field") == "/analysis/algorithm/id"
                and "RuntimeError" in issue.get("message", "")
                for issue in window._readiness_issues
            )
        )
        window.close()

    def test_incompatible_method_remains_selectable_with_reason_and_blocks_run(self):
        class SpatialOnlyAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.beam3d.spatial-only.test",
                display_name="仅三维测试方法",
                version="0.1.0",
                description="用于验证用户可选择当前模型不可解的方法。",
            )
            capabilities = replace(
                BeamSurfaceIntegralAlgorithm.capabilities,
                modeling_spaces=("3d",),
            )

        primary = BeamSurfaceIntegralAlgorithm()
        spatial_only = SpatialOnlyAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((primary, spatial_only)),
            default_algorithm_id=primary.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        setup = window.analysis_setup

        spatial_index = setup.algorithm_selector.findData(
            spatial_only.metadata.identifier
        )
        self.assertGreaterEqual(spatial_index, 0)
        self.assertIn("不可求解", setup.algorithm_selector.itemText(spatial_index))
        self.assertIn(
            "不支持2D建模空间",
            setup.algorithm_selector.itemData(
                spatial_index,
                Qt.ItemDataRole.ToolTipRole,
            ),
        )

        setup.algorithm_selector.setCurrentIndex(spatial_index)
        self.app.processEvents()

        self.assertEqual(setup.active_algorithm_id, spatial_only.metadata.identifier)
        self.assertFalse(setup.is_compatible)
        self.assertEqual(setup.algorithm_state_label.text(), "不可求解")
        self.assertIn("不支持2D建模空间", setup.algorithm_feedback_label.text())
        self.assertTrue(setup.parameter_panel.isEnabled())
        self.assertFalse(window.run_button.isEnabled())
        self.assertEqual(
            window.run_status_label.text(),
            "当前重构方法不可求解",
        )
        self.assertEqual(
            window.analysis_metric_labels["solver"].text(),
            spatial_only.metadata.display_name,
        )

        primary_index = setup.algorithm_selector.findData(primary.metadata.identifier)
        setup.algorithm_selector.setCurrentIndex(primary_index)
        self.app.processEvents()
        self.assertTrue(setup.is_compatible)
        self.assertEqual(setup.algorithm_state_label.text(), "可求解")
        self.assertTrue(window.run_button.isEnabled())
        window.close()

    def test_project_without_case_keeps_incompatible_default_preselected(self):
        class SpatialDefaultAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.beam3d.default-selection.test",
                display_name="默认三维测试方法",
                version="0.1.0",
            )
            capabilities = replace(
                BeamSurfaceIntegralAlgorithm.capabilities,
                modeling_spaces=("3d",),
            )

        primary = BeamSurfaceIntegralAlgorithm()
        spatial_default = SpatialDefaultAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((primary, spatial_default)),
            default_algorithm_id=spatial_default.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        project = window.current_project_document.revised(
            analysis_cases=(),
            active_analysis_id=None,
        )

        window.analysis_setup.set_project(project)

        self.assertEqual(
            window.analysis_setup.active_algorithm_id,
            spatial_default.metadata.identifier,
        )
        self.assertFalse(window.analysis_setup.is_compatible)
        self.assertEqual(
            window.analysis_setup.algorithm_state_label.text(),
            "不可求解",
        )
        window.close()

    def test_recovery_selector_lists_all_alternatives_with_solvability_status(self):
        class SpatialOnlyAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.beam3d.recovery-alternative.test",
                display_name="三维替代测试方法",
                version="0.1.0",
            )
            capabilities = replace(
                BeamSurfaceIntegralAlgorithm.capabilities,
                modeling_spaces=("3d",),
            )

        primary = BeamSurfaceIntegralAlgorithm()
        spatial_only = SpatialOnlyAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((primary, spatial_only)),
            default_algorithm_id=primary.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        original_case = replace(
            window.current_project_document.analysis_cases[0],
            algorithm_id="vendor.missing.recovery-choice",
            algorithm_version="4.0.0",
            parameter_schema_version="9",
        )
        project = window.current_project_document.revised(
            analysis_cases=(original_case,)
        )

        window._apply_project_document(
            project,
            dirty=False,
            status_text="恢复候选测试项目已载入",
        )
        selector = window.analysis_setup.algorithm_selector

        self.assertFalse(window.analysis_setup.algorithm_selector_row.isHidden())
        self.assertEqual(
            window.analysis_setup.algorithm_selector_label.text(),
            "替代方法",
        )
        self.assertEqual(selector.placeholderText(), "选择替代重构方法…")
        self.assertEqual(selector.accessibleName(), "选择替代重构方法")
        self.assertEqual(selector.currentIndex(), -1)
        self.assertEqual(selector.count(), 2)
        primary_index = selector.findData(primary.metadata.identifier)
        spatial_index = selector.findData(spatial_only.metadata.identifier)
        self.assertIn("适用", selector.itemText(primary_index))
        self.assertIn("不可求解", selector.itemText(spatial_index))
        self.assertIn(
            "不支持2D建模空间",
            selector.itemData(spatial_index, Qt.ItemDataRole.ToolTipRole),
        )
        self.assertEqual(window._project_for_save().analysis_cases[0], original_case)
        window.close()

    def test_missing_algorithm_save_preserves_case_until_explicit_rebind(self):
        window = gui_qt.ReconstructionMainWindow()
        project = window.current_project_document
        original_case = replace(
            project.analysis_cases[0],
            algorithm_id="vendor.missing.reconstruction",
            algorithm_version="9.4.1",
            parameter_schema_version="7",
            parameters={
                "gauss_n": "legacy-mode",
                "points_per_element": {"adaptive": True},
                "query_xs": {"adaptive": True},
                "true_points": "opaque-future-format",
                "legacy_extension": {"gain": 2.5},
            },
        )
        project = project.revised(analysis_cases=(original_case,))

        window._apply_project_document(
            project,
            dirty=False,
            status_text="缺失插件项目已载入",
        )
        setup = window.analysis_setup

        self.assertEqual(setup.recovery_status, setup.RECOVERY_MISSING)
        self.assertEqual(setup.active_algorithm_id, original_case.algorithm_id)
        self.assertIsNone(setup.active_algorithm)
        self.assertFalse(setup.is_compatible)
        self.assertFalse(window.run_button.isEnabled())
        self.assertFalse(window.query_xs_edit.isEnabled())
        self.assertFalse(window.true_point_editor.isEnabled())
        self.assertEqual(window._project_for_save().analysis_cases[0], original_case)

        installed_id = BeamSurfaceIntegralAlgorithm.metadata.identifier
        replacement_index = setup.algorithm_selector.findData(installed_id)
        self.assertGreaterEqual(replacement_index, 0)
        setup.algorithm_selector.setCurrentIndex(replacement_index)
        rebound_case = window._project_for_save().analysis_cases[0]

        self.assertTrue(window.query_xs_edit.isEnabled())
        self.assertTrue(window.true_point_editor.isEnabled())
        self.assertEqual(rebound_case.algorithm_id, installed_id)
        self.assertEqual(
            rebound_case.algorithm_version,
            BeamSurfaceIntegralAlgorithm.metadata.version,
        )
        self.assertEqual(
            rebound_case.parameter_schema_version,
            BeamSurfaceIntegralAlgorithm.metadata.parameter_schema_version,
        )
        self.assertEqual(rebound_case.parameters["gauss_n"], 3)
        self.assertEqual(rebound_case.parameters["points_per_element"], 120)
        self.assertEqual(
            rebound_case.parameters["legacy_extension"],
            {"gain": 2.5},
        )
        self.assertEqual(rebound_case.parameters["query_xs"], [])
        self.assertEqual(rebound_case.parameters["true_points"], [])
        window.close()

    def test_missing_plugin_opaque_parameters_load_from_file_without_interpretation(self):
        window = gui_qt.ReconstructionMainWindow()
        original_case = replace(
            window.current_project_document.analysis_cases[0],
            algorithm_id="vendor.missing.opaque-file",
            algorithm_version="3.0.0",
            parameter_schema_version="future-7",
            parameters={
                "query_xs": {"strategy": "adaptive"},
                "true_points": "vendor-owned",
                "nested": {"keep": [1, 2, 3]},
            },
        )
        project = window.current_project_document.revised(
            analysis_cases=(original_case,)
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opaque.ifemproj"
            save_project(path, project)

            self.assertTrue(window.load_project_path(path))
            self.assertEqual(window.current_project_path, path)
            self.assertEqual(
                window._project_for_save().analysis_cases[0],
                original_case,
            )
        window.close()

    def test_failed_project_preflight_keeps_current_document_path_and_form(self):
        window = gui_qt.ReconstructionMainWindow()
        previous_project = window.current_project_document
        previous_path = window.current_project_path
        previous_node_text = window.node_x_edit.text()
        invalid_case = replace(
            previous_project.analysis_cases[0],
            algorithm_version=BeamSurfaceIntegralAlgorithm.metadata.version,
            parameter_schema_version=(
                BeamSurfaceIntegralAlgorithm.metadata.parameter_schema_version
            ),
            parameters={
                **previous_project.analysis_cases[0].parameters,
                "query_xs": {"not": "a legacy list"},
            },
        )
        invalid_project = previous_project.revised(analysis_cases=(invalid_case,))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-analysis.ifemproj"
            save_project(path, invalid_project)
            with patch.object(window, "_show_error") as show_error:
                self.assertFalse(window.load_project_path(path))

        show_error.assert_called_once()
        self.assertIs(window.current_project_document, previous_project)
        self.assertEqual(window.current_project_path, previous_path)
        self.assertEqual(window.node_x_edit.text(), previous_node_text)
        window.close()

    def test_version_and_schema_mismatch_preserve_until_accept_current(self):
        class UpdatedBeamAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier=BeamSurfaceIntegralAlgorithm.metadata.identifier,
                display_name="局部积分 ASP-iFEM",
                version="2.0.0",
                description="用于验证插件升级恢复流程。",
                parameter_schema_version="2",
            )

        algorithm = UpdatedBeamAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        project = window.current_project_document
        original_case = replace(
            project.analysis_cases[0],
            algorithm_version="1.0.0",
            parameter_schema_version="1",
            parameters={
                "gauss_n": 4,
                "points_per_element": 160,
                "future_parameter": "keep-me",
            },
        )
        project = project.revised(analysis_cases=(original_case,))

        window._apply_project_document(
            project,
            dirty=False,
            status_text="旧版本插件项目已载入",
        )
        setup = window.analysis_setup

        self.assertEqual(setup.recovery_status, setup.RECOVERY_SCHEMA)
        self.assertFalse(setup.accept_current_button.isHidden())
        self.assertTrue(setup.algorithm_selector_row.isHidden())
        self.assertEqual(setup.algorithm_selector.count(), 0)
        self.assertEqual(setup.algorithm_selector.currentIndex(), -1)
        self.assertFalse(setup.is_compatible)
        self.assertEqual(window._project_for_save().analysis_cases[0], original_case)

        setup.accept_current_button.click()
        accepted_case = window._project_for_save().analysis_cases[0]
        self.assertEqual(setup.recovery_status, setup.RECOVERY_READY)
        self.assertTrue(setup.is_compatible)
        self.assertEqual(accepted_case.algorithm_version, "2.0.0")
        self.assertEqual(accepted_case.parameter_schema_version, "2")
        self.assertEqual(accepted_case.parameters["gauss_n"], 4)
        self.assertEqual(accepted_case.parameters["points_per_element"], 160)
        self.assertEqual(accepted_case.parameters["future_parameter"], "keep-me")
        window.close()

    def test_save_creates_active_analysis_case_when_project_has_none(self):
        window = gui_qt.ReconstructionMainWindow()
        project = window.current_project_document.revised(
            analysis_cases=(),
            active_analysis_id=None,
        )
        window._apply_project_document(
            project,
            dirty=False,
            status_text="无工况项目已载入",
        )

        saved = window._project_for_save()

        self.assertEqual(len(saved.analysis_cases), 1)
        self.assertEqual(saved.active_analysis_id, saved.analysis_cases[0].identifier)
        self.assertEqual(
            saved.analysis_cases[0].algorithm_id,
            BeamSurfaceIntegralAlgorithm.metadata.identifier,
        )
        self.assertEqual(
            saved.analysis_cases[0].algorithm_version,
            BeamSurfaceIntegralAlgorithm.metadata.version,
        )
        window.close()

    def test_invalid_saved_parameters_are_not_silently_clamped(self):
        window = gui_qt.ReconstructionMainWindow()
        project = window.current_project_document
        original_case = replace(
            project.analysis_cases[0],
            algorithm_version=BeamSurfaceIntegralAlgorithm.metadata.version,
            parameter_schema_version=(
                BeamSurfaceIntegralAlgorithm.metadata.parameter_schema_version
            ),
            parameters={
                "gauss_n": 99,
                "points_per_element": 1,
                "unknown_parameter": [1, 2, 3],
            },
        )
        project = project.revised(analysis_cases=(original_case,))

        window._apply_project_document(
            project,
            dirty=False,
            status_text="非法旧参数项目已载入",
        )
        setup = window.analysis_setup

        self.assertEqual(setup.recovery_status, setup.RECOVERY_SCHEMA)
        self.assertEqual(setup.parameter_values()["gauss_n"], 99)
        self.assertEqual(setup.parameter_values()["points_per_element"], 1)
        self.assertEqual(window._project_for_save().analysis_cases[0], original_case)
        self.assertIsNone(setup.parameter_editor("gauss_n"))
        self.assertIn("等待算法", window.input_status_label.text())
        window.show()
        self.app.processEvents()
        window.input_status_label.click()
        self.app.processEvents()
        self.assertTrue(setup.accept_current_button.hasFocus())
        window.close()

        class OptionalParameterAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier=BeamSurfaceIntegralAlgorithm.metadata.identifier,
                display_name="可选参数升级方法",
                version="2.0.0",
                parameter_schema_version="2",
            )

            def parameter_schema(self):
                return {
                    "type": "object",
                    "properties": {"gain": {"type": "number"}},
                }

        algorithm = OptionalParameterAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )
        recovery_window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        recovery_case = replace(
            recovery_window.current_project_document.analysis_cases[0],
            algorithm_version="1.0.0",
            parameter_schema_version="1",
            parameters={
                "gain": "invalid-old-value",
                "unknown_parameter": {"keep": True},
            },
        )
        recovery_project = recovery_window.current_project_document.revised(
            analysis_cases=(recovery_case,)
        )
        recovery_window._apply_project_document(
            recovery_project,
            dirty=False,
            status_text="可选参数迁移测试项目已载入",
        )

        recovery_window.analysis_setup.accept_current_button.click()
        migrated = recovery_window._project_for_save()
        migrated_case = migrated.analysis_cases[0]
        self.assertNotIn("gain", migrated_case.parameters)
        self.assertEqual(
            migrated_case.parameters["unknown_parameter"],
            {"keep": True},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "optional-parameter.ifemproj"
            save_project(path, migrated)
            reopened = load_project(path)
        reopened_case = reopened.analysis_cases[0]
        resolution = service.registry.resolve(
            reopened_case.algorithm_id,
            expected_version=reopened_case.algorithm_version,
            expected_schema_version=reopened_case.parameter_schema_version,
        )
        self.assertTrue(resolution.is_ready)
        self.assertTrue(service.validate_project(reopened).is_valid)
        recovery_window.close()

    def test_failed_recovery_activation_is_transactional(self):
        class UpdatedBeamAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier=BeamSurfaceIntegralAlgorithm.metadata.identifier,
                display_name="升级测试方法",
                version="2.0.0",
                parameter_schema_version="2",
            )

        algorithm = UpdatedBeamAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        original_case = replace(
            window.current_project_document.analysis_cases[0],
            algorithm_version="1.0.0",
            parameter_schema_version="1",
        )
        project = window.current_project_document.revised(
            analysis_cases=(original_case,)
        )
        window._apply_project_document(
            project,
            dirty=False,
            status_text="待恢复项目已载入",
        )
        setup = window.analysis_setup

        with patch.object(
            setup,
            "_activate_algorithm",
            side_effect=RuntimeError("forced editor failure"),
        ):
            setup.accept_current_button.click()

        self.assertTrue(setup.should_preserve_saved_case)
        self.assertFalse(setup.configuration_modified)
        self.assertFalse(setup.is_compatible)
        self.assertEqual(window._project_for_save().analysis_cases[0], original_case)
        window.close()

    def test_failed_alternative_activation_restores_ready_ui_and_values(self):
        class UnstableAlternative(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.beam2d.unstable-alternative.test",
                display_name="不稳定替代方法",
                version="0.1.0",
            )

        primary = BeamSurfaceIntegralAlgorithm()
        alternative = UnstableAlternative()
        service = AnalysisService(
            AlgorithmRegistry((primary, alternative)),
            default_algorithm_id=primary.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        setup = window.analysis_setup
        setup.set_parameter_values({"gauss_n": 4, "points_per_element": 160})
        original_activate = setup._activate_algorithm

        def fail_only_for_alternative(identifier, *args, **kwargs):
            if identifier == alternative.metadata.identifier:
                raise RuntimeError("schema unavailable")
            return original_activate(identifier, *args, **kwargs)

        alternative_index = setup.algorithm_selector.findData(
            alternative.metadata.identifier
        )
        with patch.object(
            setup,
            "_activate_algorithm",
            side_effect=fail_only_for_alternative,
        ):
            setup.algorithm_selector.setCurrentIndex(alternative_index)

        self.assertEqual(setup.active_algorithm_id, primary.metadata.identifier)
        self.assertEqual(setup.requested_algorithm_id, primary.metadata.identifier)
        self.assertEqual(setup.recovery_status, setup.RECOVERY_READY)
        self.assertTrue(setup.is_compatible)
        self.assertFalse(setup.should_preserve_saved_case)
        self.assertEqual(
            setup.parameter_values(),
            {"gauss_n": 4, "points_per_element": 160},
        )
        self.assertEqual(
            setup.algorithm_selector.findData(primary.metadata.identifier),
            -1,
        )
        self.assertGreaterEqual(
            setup.algorithm_selector.findData(alternative.metadata.identifier),
            0,
        )
        self.assertEqual(setup.algorithm_selector.currentIndex(), -1)
        self.assertIn(primary.metadata.display_name, setup.algorithm_selector.toolTip())
        self.assertNotIn(
            alternative.metadata.display_name,
            setup.algorithm_selector.toolTip(),
        )
        self.assertTrue(window.run_button.isEnabled())
        window.close()

    def test_dynamic_parameter_editors_preserve_scientific_values_and_unset(self):
        class ScientificParameterAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier=BeamSurfaceIntegralAlgorithm.metadata.identifier,
                display_name="科学参数测试方法",
                version="1.0.0",
                parameter_schema_version="scientific-1",
            )

            def parameter_schema(self):
                return {
                    "type": "object",
                    "properties": {
                        "big_int": {
                            "type": "integer",
                            "default": 10**20,
                        },
                        "big_num": {
                            "type": "number",
                            "default": 1.0e20,
                        },
                        "tolerance": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "default": 1.0e-12,
                        },
                        "automatic_gain": {"type": "number"},
                    },
                }

        algorithm = ScientificParameterAlgorithm()
        service = AnalysisService(
            AlgorithmRegistry((algorithm,)),
            default_algorithm_id=algorithm.metadata.identifier,
        )
        window = gui_qt.ReconstructionMainWindow(analysis_service=service)
        setup = window.analysis_setup

        self.assertEqual(
            setup.parameter_values(),
            {
                "big_int": 10**20,
                "big_num": 1.0e20,
                "tolerance": 1.0e-12,
            },
        )
        self.assertNotIn("automatic_gain", setup.parameter_values())

        big_int_editor = setup.parameter_editor("big_int")
        self.assertIsInstance(big_int_editor, gui_qt.QLineEdit)
        big_int_editor.setText(str(10**21))
        saved_case = window._project_for_save().analysis_cases[0]

        self.assertEqual(saved_case.parameters["big_int"], 10**21)
        self.assertEqual(saved_case.parameters["big_num"], 1.0e20)
        self.assertEqual(saved_case.parameters["tolerance"], 1.0e-12)
        self.assertNotIn("automatic_gain", saved_case.parameters)
        window.close()

    def test_missing_plugin_badge_focuses_explicit_replacement_selector(self):
        window = gui_qt.ReconstructionMainWindow()
        original_case = replace(
            window.current_project_document.analysis_cases[0],
            algorithm_id="vendor.missing.focus",
            algorithm_version="1.0.0",
            parameter_schema_version="1",
        )
        project = window.current_project_document.revised(
            analysis_cases=(original_case,)
        )
        window._apply_project_document(
            project,
            dirty=False,
            status_text="缺失插件项目已载入",
        )
        window.show()
        self.app.processEvents()

        window.input_status_label.click()
        self.app.processEvents()

        self.assertFalse(window.analysis_setup.algorithm_selector_row.isHidden())
        self.assertTrue(window.analysis_setup.algorithm_selector.hasFocus())
        window.close()

    def test_legacy_unversioned_case_is_not_stamped_or_defaulted_by_save(self):
        window = gui_qt.ReconstructionMainWindow()
        project = window.current_project_document
        parameters = dict(project.analysis_cases[0].parameters)
        parameters.pop("points_per_element", None)
        original_case = replace(
            project.analysis_cases[0],
            algorithm_version=None,
            parameter_schema_version=None,
            parameters=parameters,
        )
        project = project.revised(analysis_cases=(original_case,))
        window._apply_project_document(
            project,
            dirty=False,
            status_text="历史项目已载入",
        )

        saved_case = window._project_for_save().analysis_cases[0]

        self.assertIsNone(saved_case.algorithm_version)
        self.assertIsNone(saved_case.parameter_schema_version)
        self.assertNotIn("points_per_element", saved_case.parameters)
        window.close()

    def test_result_context_bar_tracks_field_and_space(self):
        window = gui_qt.ReconstructionMainWindow()
        window.run_reconstruction()

        self.assertEqual(window.view_context_label.text(), "二维结果 · 轴向应力")
        self.assertIn("节点平均连续化", window.view_meta_label.text())

        window.visualization_stack.setCurrentIndex(1)
        window._refresh_view_context()
        self.assertEqual(window.view_context_label.text(), "三维交互 · 轴向应力")

        window.current_view = "shape"
        window._refresh_view_context()
        self.assertEqual(window.view_context_label.text(), "三维交互 · 重构形态")
        window.close()

    def test_canvas_click_adds_surface_sensor_and_opens_properties(self):
        project = project_from_legacy_config(get_sample_config())
        dialog = BeamModelerDialog(project)
        dialog.resize(1100, 700)
        dialog.show()
        self.app.processEvents()

        dialog.mode_buttons[BeamModelCanvas.MODE_ADD_TOP_SENSOR].click()
        click_position = QPoint(
            round(dialog.canvas._x_to_pixel(1.45)),
            round(dialog.canvas._beam_y()),
        )
        QTest.mouseClick(
            dialog.canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            click_position,
        )
        self.app.processEvents()

        self.assertEqual(len(dialog.project.sensors), 13)
        self.assertEqual(dialog.selected_kind, "sensor")
        self.assertEqual(dialog.inspector_tabs.currentIndex(), 1)
        self.assertEqual(dialog.property_stack.currentIndex(), 2)
        self.assertEqual(dialog.sensor_config_tabs.count(), 3)
        sensor = dialog.project.sensors[-1]
        self.assertEqual(sensor.attachment.surface_side, "top")
        self.assertAlmostEqual(
            BeamProjectEditor.sensor_location(dialog.project, sensor.identifier).global_x,
            1.45,
            places=2,
        )

        dialog.sensor_surface_angle_edit.setText("90")
        dialog.sensor_orientation_angle_edit.setText("30")
        dialog._update_sensor_property()
        updated = next(
            item for item in dialog.project.sensors if item.identifier == sensor.identifier
        )
        self.assertEqual(updated.attachment.surface_angle_degrees, 90.0)
        self.assertEqual(updated.attachment.orientation_angle_degrees, 30.0)
        self.assertEqual(dialog.sensor_surface_combo.currentData(), "custom")
        _polygons, centers, directions = dialog.canvas._sensor_polygons()
        self.assertAlmostEqual(centers[sensor.identifier].y(), dialog.canvas._beam_y(), places=6)
        self.assertGreater(directions[sensor.identifier].y(), 0.0)
        dialog.close()

    def test_sensor_quick_layout_actions_are_undoable(self):
        project = project_from_legacy_config(get_sample_config())
        dialog = BeamModelerDialog(project)
        source = dialog.project.sensors[0]
        dialog._selection_changed("sensor", source.identifier)

        self.assertTrue(dialog.sensor_copy_button.isEnabled())
        self.assertTrue(dialog.sensor_opposite_button.isEnabled())
        self.assertTrue(dialog.sensor_array_button.isEnabled())
        self.assertEqual(
            dialog.sensor_move_button.isEnabled(),
            BeamGeometry3DView.backend_available,
        )

        original_count = len(dialog.project.sensors)
        dialog._copy_selected_sensor()
        copied = dialog.project.sensors[-1]
        self.assertEqual(len(dialog.project.sensors), original_count + 1)
        self.assertEqual(dialog.selected_id, copied.identifier)
        self.assertEqual(copied.measured_value, 0.0)
        dialog.undo_stack.undo()
        self.assertEqual(len(dialog.project.sensors), original_count)
        self.assertEqual(dialog.selected_kind, "")

        dialog._selection_changed("sensor", source.identifier)
        dialog._add_opposite_sensor()
        opposite = dialog.project.sensors[-1]
        expected_angle = (source.attachment.surface_angle_degrees + 180.0) % 360.0
        self.assertAlmostEqual(opposite.attachment.surface_angle_degrees, expected_angle)
        dialog.undo_stack.undo()

        dialog._selection_changed("sensor", source.identifier)
        source_distance = PathBeamEditor.sensor_location(
            dialog.project,
            source.identifier,
        ).path_distance
        direction = 1 if source_distance + 0.3 <= 3.0 else -1
        dialog._array_selected_sensor(count=3, spacing=0.1, direction=direction)
        self.assertEqual(len(dialog.project.sensors), original_count + 3)
        distances = [
            PathBeamEditor.sensor_location(dialog.project, sensor.identifier).path_distance
            for sensor in dialog.project.sensors[-3:]
        ]
        expected = [source_distance + direction * 0.1 * index for index in range(1, 4)]
        for actual, target in zip(distances, expected):
            self.assertAlmostEqual(actual, target, places=10)
        dialog.undo_stack.undo()
        self.assertEqual(len(dialog.project.sensors), original_count)
        dialog.close()

    def test_surface_sensor_move_handler_preserves_id_and_is_undoable(self):
        project = project_from_legacy_config(get_sample_config())
        dialog = BeamModelerDialog(project)
        sensor = dialog.project.sensors[0]
        target_element = PathBeamEditor.ordered_elements(dialog.project)[1]
        centerline = PathBeamEditor.point_on_element(dialog.project, target_element, 0.65)
        _tangent, normal, binormal = PathBeamEditor.section_frame(
            dialog.project,
            target_element,
            0.65,
        )
        section = next(
            item
            for item in dialog.project.sections
            if item.identifier == target_element.section_id
        )
        boundary = section_boundary_point(section, 210.0)
        picked = tuple(
            center
            + boundary.local_position[0] * normal_value
            + boundary.local_position[1] * binormal_value
            for center, normal_value, binormal_value in zip(
                centerline,
                normal,
                binormal,
            )
        )
        location = PathBeamEditor.surface_location_from_point(dialog.project, picked)

        dialog._move_surface_sensor_from_3d(sensor.identifier, location)
        moved = next(
            item for item in dialog.project.sensors if item.identifier == sensor.identifier
        )
        self.assertEqual(moved.identifier, sensor.identifier)
        self.assertEqual(moved.attachment.entity_id, target_element.identifier)
        self.assertAlmostEqual(moved.attachment.local_coordinates[0], 0.65, places=10)
        self.assertAlmostEqual(moved.attachment.surface_angle_degrees, 210.0, places=8)

        dialog.undo_stack.undo()
        restored = next(
            item for item in dialog.project.sensors if item.identifier == sensor.identifier
        )
        self.assertEqual(restored.attachment, sensor.attachment)
        dialog.close()

    def test_sensor_array_dialog_prevents_out_of_path_creation(self):
        dialog = SensorArrayDialog("M1", 0.8, 1.0)
        dialog.direction_combo.setCurrentIndex(dialog.direction_combo.findData(1))
        dialog.count_spin.setValue(3)
        dialog.spacing_spin.setValue(0.1)

        create_button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(create_button.isEnabled())
        self.assertIn("超出梁路径", dialog.preview_label.text())

        dialog.direction_combo.setCurrentIndex(dialog.direction_combo.findData(-1))
        self.assertTrue(create_button.isEnabled())
        dialog.close()

    def test_sensor_configuration_uses_compact_table_and_sectioned_editor(self):
        window = gui_qt.ReconstructionMainWindow()
        editor = window.measurement_editor

        self.assertEqual(editor.count_label.text(), "12 个测点")
        self.assertEqual(editor.editor_tabs.count(), 3)
        self.assertFalse(editor.table.isColumnHidden(0))
        self.assertFalse(editor.table.isColumnHidden(1))
        self.assertFalse(editor.table.isColumnHidden(2))
        self.assertTrue(editor.table.isColumnHidden(3))
        self.assertFalse(editor.table.isColumnHidden(4))
        self.assertTrue(editor.table.isColumnHidden(5))
        self.assertTrue(editor.table.isColumnHidden(6))
        self.assertTrue(editor.table.isColumnHidden(7))

        editor.table.selectRow(0)
        self.app.processEvents()
        self.assertEqual(editor.table.item(0, 2).text(), "上")
        self.assertEqual(editor.get_rows()[0]["surface"], "top")
        self.assertEqual(editor.inputs["element"].text(), "0")
        self.assertEqual(editor.inputs["surface"].currentText(), "top")
        self.assertNotEqual(editor.inputs["zone_b"].text(), "")
        window.close()

    def test_arc_generator_and_property_editor_keep_one_geometry_entity(self):
        dialog = BeamModelerDialog(empty_beam_project())
        dialog.resize(1100, 700)
        dialog.show()
        self.app.processEvents()

        dialog.model_space_buttons["3d"].click()
        dialog.geometry_combo.setCurrentIndex(dialog.geometry_combo.findData("arc"))
        dialog.primary_spin.setValue(2.5)
        dialog.sweep_spin.setValue(120.0)
        dialog.orientation_combo.setCurrentIndex(
            dialog.orientation_combo.findData("yz")
        )
        dialog._generate_geometry()

        self.assertEqual(len(dialog.project.nodes), 2)
        self.assertEqual(len(dialog.project.elements), 1)
        element = dialog.project.elements[0]
        self.assertEqual(element.geometry.kind, "circular_arc")
        self.assertEqual(element.geometry.parameters["plane"], "yz")

        dialog._selection_changed("element", element.identifier)
        self.assertEqual(dialog.property_stack.currentIndex(), 3)
        self.assertEqual(dialog.element_geometry_label.text(), "参数化圆弧")
        dialog.arc_radius_edit.setText("3.25")
        dialog.arc_sweep_edit.setText("-75")
        dialog.arc_plane_combo.setCurrentIndex(dialog.arc_plane_combo.findData("xz"))
        dialog._update_element_property()

        updated = dialog.project.elements[0]
        self.assertEqual(len(dialog.project.nodes), 2)
        self.assertEqual(len(dialog.project.elements), 1)
        self.assertEqual(updated.geometry.parameters["radius"], 3.25)
        self.assertEqual(updated.geometry.parameters["sweep_degrees"], -75.0)
        self.assertEqual(updated.geometry.parameters["plane"], "xz")
        dialog.close()

    def test_path_generator_uses_compact_segmented_controls(self):
        dialog = BeamModelerDialog(empty_beam_project())
        dialog.resize(1040, 680)
        dialog.show()
        self.app.processEvents()

        self.assertEqual(dialog.path_generator_label.text(), "快速生成")
        self.assertFalse(dialog.geometry_combo.isVisible())
        self.assertTrue(dialog.path_kind_buttons["straight"].isChecked())
        self.assertEqual(
            dialog.path_kind_buttons["arc"].accessibleName(),
            "路径几何类型：圆弧",
        )

        dialog.path_kind_buttons["arc"].click()
        dialog.primary_spin.setValue(5.001)
        dialog.sweep_spin.setValue(90.0)
        self.app.processEvents()

        self.assertEqual(dialog.geometry_combo.currentData(), "arc")
        self.assertTrue(dialog.path_kind_buttons["arc"].isChecked())
        self.assertIn("5.001 m", dialog.primary_spin.text())
        self.assertNotIn("5.001000", dialog.primary_spin.text())
        self.assertEqual(dialog.sweep_spin.text(), "90°")
        self.assertEqual(dialog.append_button.text(), "追加圆弧")
        self.assertTrue(dialog.append_button.property("primaryAction"))
        self.assertFalse(bool(dialog.generate_button.property("primaryAction")))
        self.assertIn("清空", dialog.generate_button.toolTip())
        dialog.path_kind_buttons["straight"].click()
        dialog.path_kind_buttons["arc"].click()
        self.assertIn("清空", dialog.generate_button.toolTip())
        self.assertIn("当前路径", dialog.current_path_label.toolTip())
        self.assertIs(dialog.primary_label.buddy(), dialog.primary_spin)
        self.assertIs(dialog.secondary_label.buddy(), dialog.sweep_spin)
        for button in (
            dialog.spatial_curve_button,
            dialog.generate_button,
            dialog.append_button,
        ):
            self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
        dialog.close()

    def test_path_generator_keeps_segment_draft_after_append_and_undo(self):
        dialog = BeamModelerDialog(empty_beam_project())
        dialog.path_kind_buttons["straight"].click()
        dialog.primary_spin.setValue(0.75)
        dialog.orientation_combo.setCurrentIndex(
            dialog.orientation_combo.findData("x")
        )

        dialog._append_geometry()
        self.assertAlmostEqual(PathBeamEditor.total_length(dialog.project), 1.75)
        self.assertAlmostEqual(dialog.primary_spin.value(), 0.75)

        dialog.undo_stack.undo()
        self.assertAlmostEqual(PathBeamEditor.total_length(dialog.project), 1.0)
        self.assertAlmostEqual(dialog.primary_spin.value(), 0.75)
        dialog.close()

    def test_modeler_builds_a_mixed_2d_path_without_discretizing_the_arc(self):
        dialog = BeamModelerDialog(empty_beam_project(modeling_space="2d"))
        dialog.resize(1100, 700)
        dialog.show()
        self.app.processEvents()

        dialog.geometry_combo.setCurrentIndex(dialog.geometry_combo.findData("straight"))
        dialog.primary_spin.setValue(2.0)
        dialog.element_count_spin.setValue(1)
        dialog.orientation_combo.setCurrentIndex(
            dialog.orientation_combo.findData("x")
        )
        dialog._generate_geometry()
        dialog.geometry_combo.setCurrentIndex(dialog.geometry_combo.findData("arc"))
        dialog.primary_spin.setValue(1.0)
        dialog.sweep_spin.setValue(90.0)
        dialog._append_geometry()

        capability = PathBeamEditor.capability(dialog.project)
        self.assertEqual(dialog.project.modeling_space, "2d")
        self.assertEqual(len(dialog.project.elements), 2)
        self.assertEqual(
            [element.geometry.kind for element in dialog.project.elements],
            ["line", "circular_arc"],
        )
        self.assertEqual(capability.kind, "二维直线/圆弧组合梁")
        self.assertEqual(dialog.capability_label.text(), "无可用算法")
        dialog.close()

    def test_main_window_keeps_spatial_model_but_disables_legacy_solver(self):
        window = gui_qt.ReconstructionMainWindow()
        spatial_project = PathBeamEditor.create_circular_arc(
            window.current_project_document,
            radius=2.0,
            sweep_degrees=90.0,
            plane="xz",
        )

        class AcceptedModeler:
            def __init__(self, _project, _parent=None):
                self.project = spatial_project

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch.object(gui_qt, "BeamModelerDialog", AcceptedModeler):
            window.open_interactive_modeler()

        self.assertIs(window.current_project_document, spatial_project)
        self.assertFalse(window.run_button.isEnabled())
        self.assertEqual(
            window.analysis_metric_labels["solver"].text(),
            window.analysis_setup.active_algorithm_display_name,
        )
        self.assertEqual(
            window.run_status_label.text(),
            "当前重构方法不可求解",
        )
        window.close()

    def test_uniform_section_form_switches_shape_and_updates_project(self):
        dialog = BeamModelerDialog(empty_beam_project())
        dialog.section_shape_combo.setCurrentIndex(
            dialog.section_shape_combo.findData("box")
        )
        values = ("0.24", "0.12", "0.015")
        for edit, value in zip(dialog.section_parameter_edits, values):
            edit.setText(value)
        dialog.material_e_edit.setText("70")

        dialog._update_primary_properties()

        section = dialog.project.sections[0]
        self.assertEqual(section.shape, "box")
        self.assertEqual(
            section.parameters,
            {"outer_height": 0.24, "outer_width": 0.12, "wall_thickness": 0.015},
        )
        self.assertTrue(
            all(element.section_id == section.identifier for element in dialog.project.elements)
        )
        dialog.close()

    def test_3d_surface_pick_adds_sensor_selects_it_and_supports_undo(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(),
            length=2.0,
            element_count=1,
        )
        project = PathBeamEditor.update_primary_properties(
            project,
            thickness=0.2,
            width=0.1,
            elastic_modulus=70.0e9,
        )
        dialog = BeamModelerDialog(project)
        element = project.elements[0]
        centerline = PathBeamEditor.point_on_element(project, element, 0.4)
        _tangent, normal, binormal = PathBeamEditor.section_frame(project, element, 0.4)
        boundary = section_boundary_point(project.sections[0], 35.0)
        picked = tuple(
            center
            + normal_value * boundary.local_position[0]
            + binormal_value * boundary.local_position[1]
            for center, normal_value, binormal_value in zip(
                centerline,
                normal,
                binormal,
            )
        )

        dialog._set_mode(BeamGeometry3DView.MODE_ADD_SURFACE_SENSOR)
        dialog.geometry_3d_view._picked(picked)
        self.app.processEvents()

        self.assertEqual(dialog.view_stack.currentIndex(), 1)
        self.assertEqual(len(dialog.project.sensors), 1)
        sensor = dialog.project.sensors[0]
        self.assertEqual(dialog.selected_kind, "sensor")
        self.assertEqual(dialog.selected_id, sensor.identifier)
        self.assertAlmostEqual(sensor.attachment.local_coordinates[0], 0.4, places=10)
        self.assertAlmostEqual(sensor.attachment.surface_angle_degrees, 35.0, places=10)
        self.assertIn("表面", dialog.sensor_position_label.text())
        self.assertIn("s=", dialog.sensor_position_label.text())

        dialog.undo_stack.undo()
        self.assertEqual(len(dialog.project.sensors), 0)
        dialog.close()

    def test_escape_exits_3d_surface_placement_mode(self):
        dialog = BeamModelerDialog(empty_beam_project())
        dialog._set_mode(BeamGeometry3DView.MODE_ADD_SURFACE_SENSOR)

        QTest.keyClick(dialog, Qt.Key.Key_Escape)

        self.assertEqual(dialog.canvas.mode, BeamModelCanvas.MODE_SELECT)
        self.assertEqual(dialog.geometry_3d_view.mode, BeamGeometry3DView.MODE_SELECT)
        self.assertTrue(dialog.mode_buttons[BeamModelCanvas.MODE_SELECT].isChecked())
        dialog.close()

    def test_result_3d_view_keeps_sensor_overlays_in_modeler_only(self):
        view = Structure3DView()

        self.assertIn("测点布置请在建模视图查看", view.interaction_hint.text())
        self.assertFalse(hasattr(view, "show_sensors_check"))
        view.close()

    def test_modeler_actions_describe_persistence_and_replacement(self):
        dialog = BeamModelerDialog(project_from_legacy_config(get_sample_config()))

        self.assertEqual(dialog.save_project_button.text(), "保存项目")
        self.assertIn("项目库", dialog.save_project_button.toolTip())
        self.assertEqual(dialog.apply_to_workspace_button.text(), "应用到工作台")
        self.assertIn("不会自动写入", dialog.apply_to_workspace_button.toolTip())
        self.assertEqual(dialog.generate_button.text(), "替换当前路径")
        self.assertIn("清空", dialog.generate_button.toolTip())
        dialog.close()

    def test_spatial_curve_dialog_parses_arc_and_nurbs_definitions(self):
        dialog = SpatialCurveDialog()
        dialog.points_edit.setPlainText(
            "0, 0, 0\n1, 0.5, 0.75\n2, 1.5, 0.25"
        )
        arc = dialog.definition()

        self.assertEqual(arc["kind"], SpatialCurveDialog.ARC)
        self.assertEqual(len(arc["points"]), 3)

        dialog.kind_combo.setCurrentIndex(
            dialog.kind_combo.findData(SpatialCurveDialog.NURBS)
        )
        self.assertEqual(dialog.degree_spin.value(), 2)
        self.assertTrue(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )
        dialog.points_edit.setPlainText(
            "0, 0, 0\n1, 0, 1\n2, 1, 1\n3, 1, 0"
        )
        dialog.degree_spin.setValue(3)
        dialog.weights_edit.setText("1, 0.8, 1.2, 1")
        nurbs = dialog.definition()

        self.assertEqual(nurbs["kind"], SpatialCurveDialog.NURBS)
        self.assertEqual(nurbs["degree"], 3)
        self.assertEqual(nurbs["weights"], (1.0, 0.8, 1.2, 1.0))

        dialog.weights_edit.setText("1, 0, 1, 1")
        with self.assertRaisesRegex(ValueError, "大于 0"):
            dialog.definition()
        dialog.close()

    def test_spatial_curve_dialog_builds_parametric_templates_and_targets_errors(self):
        dialog = SpatialCurveDialog()
        dialog.kind_combo.setCurrentIndex(
            dialog.kind_combo.findData(SpatialCurveDialog.PARAMETRIC)
        )

        helix = dialog.definition()

        self.assertEqual(helix["kind"], "parametric_curve")
        self.assertEqual(helix["template"], "helix")
        self.assertEqual(helix["domain"], (0.0, 1.0))
        self.assertEqual(helix["constants"]["R"], 1.0)
        self.assertIn("cos", helix["expressions"]["x"])
        self.assertEqual(len(dialog.parametric_preview.samples), 129)
        self.assertEqual(
            dialog.expression_edits["x"].accessibleName(),
            "参数表达式 x(t)",
        )
        self.assertEqual(
            dialog.constants_table.accessibleName(),
            "参数曲线用户常量表",
        )
        self.assertTrue(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )

        reopened = SpatialCurveDialog(initial_definition=helix)
        self.assertEqual(
            reopened.kind_combo.currentData(),
            SpatialCurveDialog.PARAMETRIC,
        )
        self.assertEqual(reopened.definition(), helix)
        self.assertEqual(reopened.windowTitle(), "编辑参数曲线")
        self.assertEqual(
            reopened.buttons.button(QDialogButtonBox.StandardButton.Ok).text(),
            "应用曲线",
        )
        reopened.close()

        precise = {
            "kind": "parametric_curve",
            "language": "ifem-math-v1",
            "domain": (0.12345678912345, 1.98765432198765),
            "expressions": {"x": "C*t", "y": "0", "z": "0"},
            "constants": {"C": 1.2345678901234567},
            "template": "custom",
        }
        precise_reopened = SpatialCurveDialog(initial_definition=precise)
        self.assertEqual(precise_reopened.definition(), precise)
        precise_reopened.close()

        dialog.parametric_template_combo.setCurrentIndex(
            dialog.parametric_template_combo.findData("parabola")
        )
        parabola = dialog.definition()
        self.assertEqual(parabola["template"], "parabola")
        self.assertEqual(parabola["expressions"]["y"], "4*H*t*(1-t)")

        dialog.parametric_template_combo.setCurrentIndex(
            dialog.parametric_template_combo.findData("custom")
        )
        dialog.expression_edits["x"].setText("open('curve')")
        dialog._refresh_state()
        self.assertFalse(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        )
        self.assertEqual(
            dialog.expression_edits["x"].property("validationState"),
            "error",
        )
        self.assertIn("x(t)", dialog.feedback_label.text())
        self.assertEqual(dialog.parametric_preview.samples, ())

        dialog.expression_edits["x"].setText("1/(t-0.5)")
        dialog._refresh_state()
        self.assertEqual(
            dialog.expression_edits["x"].property("validationState"),
            "error",
        )
        self.assertIn("只允许除以", dialog.feedback_label.text())
        self.assertEqual(dialog.parametric_preview.samples, ())

        dialog.expression_edits["x"].setText("t")
        dialog.domain_end_spin.setValue(dialog.domain_start_spin.value())
        dialog._refresh_state()
        self.assertEqual(
            dialog.domain_end_spin.property("validationState"),
            "error",
        )
        self.assertIn("t₀ < t₁", dialog.feedback_label.text())

        dialog.domain_end_spin.setValue(1.0)
        dialog.domain_start_spin.setText("")
        dialog._refresh_state()
        self.assertEqual(
            dialog.domain_start_spin.property("validationState"),
            "error",
        )
        dialog.domain_start_spin.setValue(0.0)
        dialog._add_constant_row()
        dialog.constants_table.item(0, 0).setText("t")
        dialog.constants_table.item(0, 1).setText("2")
        dialog._refresh_state()
        self.assertEqual(
            dialog.constants_table.property("validationState"),
            "error",
        )
        self.assertIn("已保留", dialog.feedback_label.text())
        dialog.close()

    def test_modeler_creates_single_nurbs_entity_and_supports_undo(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
        )
        dialog = BeamModelerDialog(project)

        class AcceptedSpatialCurveDialog:
            ARC = SpatialCurveDialog.ARC
            NURBS = SpatialCurveDialog.NURBS

            def __init__(self, _parent=None):
                self.curve_definition = {
                    "kind": self.NURBS,
                    "points": (
                        (0.0, 0.0, 0.0),
                        (0.8, 0.0, 1.0),
                        (2.0, 1.0, 0.8),
                        (3.0, 1.2, 0.0),
                    ),
                    "degree": 3,
                    "weights": None,
                }

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch(
            "ifem.ui.modeler.SpatialCurveDialog",
            AcceptedSpatialCurveDialog,
        ):
            dialog._create_spatial_curve()

        self.assertEqual(len(dialog.project.elements), 1)
        self.assertEqual(dialog.project.elements[0].geometry.kind, "nurbs_curve")
        self.assertEqual(dialog.project.modeling_space, "3d")
        self.assertIn("3 次 NURBS", dialog.current_path_label.toolTip())
        self.assertIn("4 控制点", dialog.current_path_label.toolTip())
        dialog.undo_stack.undo()
        self.assertEqual(dialog.project.elements[0].geometry.kind, "line")
        dialog.close()

    def test_modeler_creates_parametric_curve_and_supports_undo(self):
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"),
            length=2.0,
            element_count=1,
        )
        dialog = BeamModelerDialog(project)

        class AcceptedParametricCurveDialog:
            ARC = SpatialCurveDialog.ARC

            def __init__(self, _parent=None):
                self.curve_definition = {
                    "kind": "parametric_curve",
                    "domain": (0.0, 1.0),
                    "expressions": {
                        "x": "R*cos(2*pi*N*t)",
                        "y": "R*sin(2*pi*N*t)",
                        "z": "H*t",
                    },
                    "constants": {"R": 1.0, "N": 2.0, "H": 2.0},
                    "template": "helix",
                }

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch(
            "ifem.ui.modeler.SpatialCurveDialog",
            AcceptedParametricCurveDialog,
        ):
            dialog._create_spatial_curve()

        element = dialog.project.elements[0]
        self.assertEqual(element.geometry.kind, "parametric_curve")
        self.assertEqual(element.geometry.parameters["template"], "helix")
        self.assertEqual(element.geometry.parameters["domain"], (0.0, 1.0))
        self.assertIn("参数方程曲线", dialog.current_path_label.toolTip())
        self.assertIn("空间螺旋线", dialog.current_path_label.toolTip())
        dialog._selection_changed("element", element.identifier)
        self.assertIn("参数方程曲线", dialog.element_geometry_label.text())
        self.assertFalse(dialog.element_family_combo.isEnabled())

        dialog.undo_stack.undo()
        self.assertEqual(dialog.project.elements[0].geometry.kind, "line")
        dialog.close()

    def test_modeler_creates_tilted_three_point_arc(self):
        project = empty_beam_project(modeling_space="3d")
        dialog = BeamModelerDialog(project)

        class AcceptedSpatialArcDialog:
            ARC = SpatialCurveDialog.ARC
            NURBS = SpatialCurveDialog.NURBS

            def __init__(self, _parent=None):
                self.curve_definition = {
                    "kind": self.ARC,
                    "points": (
                        (1.0, -1.0, 0.0),
                        (1.0, 0.0, 1.0),
                        (0.0, 1.0, 1.0),
                    ),
                }

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch(
            "ifem.ui.modeler.SpatialCurveDialog",
            AcceptedSpatialArcDialog,
        ):
            dialog._create_spatial_curve()

        element = dialog.project.elements[0]
        self.assertEqual(element.geometry.kind, "circular_arc")
        self.assertEqual(element.geometry.parameters["plane"], "custom")
        self.assertEqual(dialog.project.modeling_space, "3d")
        self.assertIn("任意平面圆弧", dialog.current_path_label.toolTip())
        dialog.close()

    def test_replacing_path_confirms_when_only_boundaries_would_be_cleared(self):
        project = project_from_legacy_config(get_sample_config()).revised(sensors=())
        self.assertTrue(project.boundary_conditions)
        dialog = BeamModelerDialog(project)

        with (
            patch(
                "ifem.ui.modeler.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as confirm,
            patch("ifem.ui.modeler.SpatialCurveDialog") as spatial_dialog,
        ):
            dialog._generate_geometry()

        confirm.assert_called_once()
        self.assertIn("边界约束", confirm.call_args.args[2])
        self.assertEqual(dialog.project.to_dict(), project.to_dict())

        with patch(
            "ifem.ui.modeler.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ) as confirm:
            dialog._create_spatial_curve()

        confirm.assert_called_once()
        spatial_dialog.assert_not_called()
        self.assertEqual(dialog.project.to_dict(), project.to_dict())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
