"""Integration links use snapshot entity IDs, never native-model or table-row guesses."""

import os
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import gui_qt
from config_adapter import get_sample_config
from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm
from ifem.application.analysis_service import AlgorithmRegistry, AnalysisService
from ifem.domain.analysis import DeformationRegime
from ifem.domain.project import AnalysisCase, empty_beam_project
from ifem.modeling import PathBeamEditor
from ifem.infrastructure import project_from_legacy_config
from test_generic_workbench import _WorkbenchProbe
from test_ui_support import isolated_workspace_settings


@isolated_workspace_settings
class GenericResultLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for patcher in (
            patch.object(gui_qt, "apply_application_theme", return_value="graphite"),
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard),
            patch.object(QMessageBox, "critical"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        native = BeamSurfaceIntegralAlgorithm()
        self.probe = _WorkbenchProbe("3d", DeformationRegime.LARGE.value)
        service = AnalysisService(
            AlgorithmRegistry((native, self.probe)),
            default_algorithm_id=native.metadata.identifier,
        )
        self.window = gui_qt.ReconstructionMainWindow(analysis_service=service, theme_id="graphite")
        self.addCleanup(self._dispose)
        self.window.show()
        self.app.processEvents()
        project = PathBeamEditor.create_straight_beam(
            empty_beam_project(modeling_space="3d"), length=3.0, element_count=3, axis="z",
        )
        case = AnalysisCase(
            identifier="test-generic-link-case", name="结果 ID 联动测试",
            algorithm_id=self.probe.metadata.identifier,
            algorithm_version=self.probe.metadata.version,
            parameter_schema_version=self.probe.metadata.parameter_schema_version,
            parameters={"max_iterations": 9},
        )
        project = project.revised(analysis_cases=(case,), active_analysis_id=case.identifier)
        self.window._apply_project_document(project, dirty=False, status_text="联动测试工程")
        with patch.object(self.window, "_show_error") as error:
            self.window.run_reconstruction()
        error.assert_not_called()
        self.app.processEvents()
        self.assertTrue(self.window._is_generic_result())
        self.result = self.window.current_analysis_result
        self.view = self.window.generic_result_view
        self.panel = self.window.result_fields_panel

    def _dispose(self):
        self.window.hide()
        self.window.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _select_field_row(self, row):
        self.window.result_tabs.setCurrentWidget(self.panel)
        self.panel.table.setCurrentIndex(self.panel.model.index(row, 0))
        self.panel.table.selectRow(row)
        self.app.processEvents()

    def _click_plot_record(self, index):
        self.view.canvas.draw()
        x, y = self.view._screen_positions()[index]
        self.view._on_press(SimpleNamespace(button=1, inaxes=self.view.axes, x=x, y=y))
        self.view._on_release(SimpleNamespace(button=1, inaxes=self.view.axes, x=x, y=y))
        self.app.processEvents()

    def _install_native_snapshot_without_model(self):
        config = get_sample_config()
        project = project_from_legacy_config(config)
        self.window._apply_project_document(project, dirty=False, status_text="测点联动快照测试")
        native = self.window.analysis_service.run_project(project)
        generic = replace(native, native_model=None)
        self.window._apply_analysis_result(generic, config)
        self.app.processEvents()
        self.assertTrue(self.window._is_generic_result())
        self.assertIs(self.view.result, generic)
        self.assertEqual(self.window.sensor_result_table.table.rowCount(), len(project.sensors))
        return native, generic, config

    def test_field_table_selection_highlights_original_id_despite_reversed_rows(self):
        self.assertEqual(self.panel.model.layer.records[0].entity_id, self.result.state.node_ids[-1])
        self._select_field_row(0)
        identifier = self.result.state.node_ids[-1]
        self.assertEqual(self.view.selected_record, ("quality", identifier))
        self.assertIsNone(self.view.selected_node)
        self.assertEqual(self.view.field_id, "quality")
        np.testing.assert_allclose(self.view._selected_point().position, self.result.state.deformed_coordinates[-1])
        self.assertEqual(self.panel.table.currentIndex().row(), 0)
        self.assertEqual(self.window.generic_state_table.table.currentRow(), -1)

    def test_keyboard_row_navigation_keeps_table_and_field_id_link(self):
        self._select_field_row(0)
        self.panel.table.setFocus()
        QTest.keyClick(self.panel.table, Qt.Key.Key_Down)
        self.app.processEvents()
        self.assertEqual(self.panel.table.currentIndex().row(), 1)
        identifier = self.panel.model.layer.records[1].entity_id
        self.assertEqual(self.view.selected_record, ("quality", identifier))

    def test_plot_field_pick_reveals_matching_data_row_and_leaves_focus_mode(self):
        self.view.set_field("quality")
        self.window.result_toggle.setChecked(False)
        self.window.focus_mode_button.setChecked(True)
        self._click_plot_record(2)
        identifier = self.result.fields["quality"].entity_ids[2]
        self.assertEqual(self.view.selected_record, ("quality", identifier))
        self.assertEqual(self.panel.table.currentIndex().row(), 2)
        self.assertIs(self.window.result_tabs.currentWidget(), self.panel)
        self.assertTrue(self.window.result_toggle.isChecked())
        self.assertFalse(self.window.focus_mode_button.isChecked())

    def test_shape_node_pick_reveals_state_row_without_fabricated_field(self):
        self.view.set_field(None)
        self.window.result_tabs.setCurrentWidget(self.panel)
        self._click_plot_record(1)
        self.assertEqual(self.view.selected_node, self.result.state.node_ids[1])
        self.assertIsNone(self.view.selected_record)
        self.assertIsNone(self.view.field_id)
        self.assertIs(self.window.result_tabs.currentWidget(), self.window.generic_state_table)
        self.assertEqual(self.window.generic_state_table.table.currentRow(), 1)
        self.assertFalse(self.panel.table.selectionModel().selectedRows())

    def test_state_table_selects_exact_node_and_clears_field_selection(self):
        self._select_field_row(0)
        table = self.window.generic_state_table.table
        self.window.result_tabs.setCurrentWidget(self.window.generic_state_table)
        table.setCurrentCell(2, 0)
        table.selectRow(2)
        self.app.processEvents()
        self.assertEqual(self.view.selected_node, self.result.state.node_ids[2])
        self.assertIsNone(self.view.selected_record)
        self.assertIsNone(self.view.field_id)
        self.assertEqual(table.currentRow(), 2)
        self.assertEqual(self.panel.table.currentIndex().row(), -1)

    def test_xy_xz_yz_and_3d_switch_keep_field_selection_and_table_row(self):
        self._select_field_row(1)
        selected = self.view.selected_record
        for projection in ("xy", "xz", "yz", "3d"):
            with self.subTest(projection=projection):
                self.view.set_projection(projection)
                self.app.processEvents()
                self.assertEqual(self.view.selected_record, selected)
                self.assertEqual(self.panel.table.currentIndex().row(), 1)
                self.assertEqual(self.view.projection, projection)
                self.assertTrue(self.window.display_buttons["3d" if projection == "3d" else "2d"].isChecked())
                self.assertEqual(self.view.axes.name == "3d", projection == "3d")

    def test_main_space_controls_do_not_switch_back_to_native_views(self):
        self._select_field_row(1)
        selected = self.view.selected_record
        self.window._switch_visualization_space(0)
        self.assertEqual(self.view.projection, "xy")
        self.assertIs(self.window.plot_content_stack.currentWidget(), self.view)
        self.window._switch_visualization_space(1)
        self.assertEqual(self.view.projection, "3d")
        self.assertEqual(self.view.selected_record, selected)
        self.assertIs(self.window.plot_content_stack.currentWidget(), self.view)

    def test_unprovided_strain_and_stress_controls_are_disabled(self):
        self.assertTrue(self.window.view_buttons["shape"].isEnabled())
        for index, mode in ((1, "strain"), (2, "stress")):
            with self.subTest(mode=mode):
                self.assertFalse(self.window.view_buttons[mode].isEnabled())
                self.assertFalse(self.window.view_shortcut_actions[index].isEnabled())
                self.window._switch_view(mode)
                self.assertIsNone(self.view.field_id)
                self.assertEqual(self.window.current_view, "shape")
        self.assertFalse(self.window.display_settings_button.isVisible())
        self.assertTrue(all(not button.isVisible() for button in self.window.scale_buttons.values()))

    def test_view_and_table_selection_restore_from_saved_snapshot(self):
        self._select_field_row(2)
        self.view.set_projection("xz")
        snapshot = self.window.generic_results.capture()
        self.view.highlight_node(self.result.state.node_ids[0])
        self.view.set_projection("3d")
        self.window.generic_results.restore(snapshot)
        self.assertEqual(self.view.selected_record, snapshot["record"])
        self.assertEqual(self.view.projection, "xz")
        self.assertEqual(self.panel.table.currentIndex().row(), 2)
        self.assertEqual(self.window.generic_state_table.table.currentRow(), -1)

    def test_generic_returns_to_native_result_tabs_controls_and_probe(self):
        self._select_field_row(1)
        self.window.load_sample_data(initial=True)
        self.assertIsNone(self.view.result)
        self.assertIsNone(self.view.selected_record)
        self.assertEqual(self.window.generic_state_table.table.rowCount(), 0)
        with patch.object(self.window, "_show_error") as error:
            self.window.run_reconstruction()
        error.assert_not_called()
        self.app.processEvents()
        self.assertFalse(self.window._is_generic_result())
        self.assertIsNotNone(self.window.current_model)
        self.assertIsNone(self.view.result)
        self.assertIs(self.window.plot_content_stack.currentWidget(), self.window.visualization_stack)
        self.assertFalse(self.window.result_tabs.isTabVisible(self.window.generic_state_tab_index))
        self.assertTrue(self.window.result_tabs.isTabVisible(self.window.node_result_tab_index))
        self.assertTrue(self.window.view_buttons["strain"].isEnabled())
        self.assertTrue(self.window.view_buttons["stress"].isEnabled())
        self.assertTrue(self.window.display_settings_button.isVisible())
        self.assertTrue(self.window.probe_bar.isVisible())
        self.assertTrue(self.window.result_link.select("node", 1))
        self.assertEqual(self.window.result_link.selected.kind, "node")
        self.assertEqual(self.window.node_result_table.table.currentRow(), 1)

    def test_shift_selection_and_copy_preserve_all_field_table_rows(self):
        self._select_field_row(0)
        self.panel.table.setFocus()
        for _ in range(2):
            QTest.keyClick(self.panel.table, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        self.app.processEvents()
        selected = sorted(index.row() for index in self.panel.table.selectionModel().selectedRows())
        self.assertEqual(selected, [0, 1, 2])
        self.assertEqual(self.view.selected_record, ("quality", self.panel.model.layer.records[2].entity_id))
        self.panel.copy_selection()
        lines = QApplication.clipboard().text().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual([line.split("\t")[0] for line in lines[1:]],
                         [self.panel.model.layer.records[row].entity_id for row in selected])
        self.assertEqual(sorted(index.row() for index in self.panel.table.selectionModel().selectedRows()), selected)

    def test_disjoint_multiselect_survives_current_row_plot_update(self):
        self._select_field_row(0)
        selection = self.panel.table.selectionModel()
        index = self.panel.model.index(2, 0)
        selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        selection.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.app.processEvents()
        self.assertEqual(sorted(item.row() for item in selection.selectedRows()), [0, 2])
        self.assertEqual(self.view.selected_record, ("quality", self.panel.model.layer.records[2].entity_id))
        for projection in ("xz", "yz", "3d"):
            self.view.set_projection(projection)
            self.app.processEvents()
            self.assertEqual(sorted(item.row() for item in selection.selectedRows()), [0, 2])
        self.panel.copy_selection()
        copied = QApplication.clipboard().text().splitlines()[1:]
        self.assertEqual([line.split("\t")[0] for line in copied],
                         [self.panel.model.layer.records[row].entity_id for row in (0, 2)])

    def test_generic_sensor_table_selection_is_not_cleared_by_native_probe(self):
        _native, generic, _config = self._install_native_snapshot_without_model()
        table = self.window.sensor_result_table.table
        self.window.result_tabs.setCurrentWidget(self.window.sensor_result_panel)
        for row in (0, 3, 1):
            with self.subTest(row=row):
                table.setCurrentCell(row, 0)
                table.selectRow(row)
                self.app.processEvents()
                identifier = generic.fields["sensor_strain_residual"].entity_ids[row]
                self.assertEqual(table.currentRow(), row)
                self.assertEqual([index.row() for index in table.selectionModel().selectedRows()], [row])
                self.assertEqual(self.view.selected_record, ("sensor_strain_residual", identifier))
                self.assertIsNone(self.view.selected_node)
                self.assertEqual(self.panel.model.layer.records[self.panel.table.currentIndex().row()].entity_id, identifier)
                self.assertIsNone(self.window.result_link.selected)
                self.assertFalse(self.window.result_link.targets)

    def test_generic_sensor_selection_stays_on_id_across_projection_and_field_changes(self):
        _native, generic, _config = self._install_native_snapshot_without_model()
        table = self.window.sensor_result_table.table
        table.setCurrentCell(2, 0)
        table.selectRow(2)
        identifier = generic.fields["sensor_strain_residual"].entity_ids[2]
        for field in ("sensor_measured_strain", "sensor_reconstructed_strain", "sensor_strain_residual"):
            for projection in ("xz", "3d", "xy"):
                with self.subTest(field=field, projection=projection):
                    self.view.set_field(field)
                    self.view.set_projection(projection)
                    self.app.processEvents()
                    self.assertEqual(self.view.selected_record, (field, identifier))
                    self.assertEqual(table.currentRow(), 2)
                    self.assertEqual([index.row() for index in table.selectionModel().selectedRows()], [2])
                    self.assertEqual(self.panel.model.layer.records[self.panel.table.currentIndex().row()].entity_id, identifier)

    def test_generic_sensor_graph_pick_updates_both_tables_by_sensor_id(self):
        _native, generic, _config = self._install_native_snapshot_without_model()
        self.view.set_field("sensor_strain_residual")
        self.view.set_projection("xy")
        # Top/bottom points may overlap on screen. Pick whichever record the
        # actual screen-space hit test selects, then require both tables to join
        # that exact ID rather than infer a row from the live project.
        self._click_plot_record(1)
        field, identifier = self.view.selected_record
        self.assertEqual(field, "sensor_strain_residual")
        row = generic.fields[field].entity_ids.index(identifier)
        self.assertEqual(self.window.sensor_result_table.table.currentRow(), row)
        self.assertEqual(self.panel.model.layer.records[self.panel.table.currentIndex().row()].entity_id, identifier)
        self.assertIs(self.window.result_tabs.currentWidget(), self.panel)

    def test_generic_residual_description_does_not_claim_builtin_point_semantics(self):
        native, _generic, config = self._install_native_snapshot_without_model()
        generic_text = self.window.sensor_explanation.text()
        self.assertIn("重构", generic_text)
        self.assertIn("观测", generic_text)
        self.assertNotIn("原始解的测点点值", generic_text)
        self.assertNotIn("不是区间积分目标", generic_text)
        self.window._apply_analysis_result(native, config)
        self.app.processEvents()
        self.assertFalse(self.window._is_generic_result())
        self.assertIn("原始解的测点点值", self.window.sensor_explanation.text())
        self.assertIn("不是区间积分目标", self.window.sensor_explanation.text())


if __name__ == "__main__":
    unittest.main()
