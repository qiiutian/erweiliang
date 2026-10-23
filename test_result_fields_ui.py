"""Contract-only field browser and sensor diagnostics integration."""

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

import gui_qt
from config_adapter import get_sample_config
from ifem.application.analysis_service import create_default_analysis_service
from ifem.domain.analysis import AnalysisResult, ResultField
from ifem.ui.result_fields import ResultFieldsPanel
from ifem.ui.workspace_preferences import ReadingPreferences
from ifem.visualization.sensor_residuals import sensor_residual_data
from test_result_fields import result_with, displacement, state_for
from test_ui_support import isolated_workspace_settings


class FieldBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = ResultFieldsPanel()
        self.addCleanup(self.panel.deleteLater)

    def test_no_native_model_four_regimes_and_id_order(self):
        for space in ("2d", "3d"):
            for regime in ("small_deformation", "large_deformation"):
                self.panel.set_result(result_with(displacement(), state=state_for(space=space, regime=regime)))
                self.assertEqual(self.panel.model.rowCount(), 2)
                self.assertEqual(self.panel.model.data(self.panel.model.index(0, 0)), "left")
                self.assertEqual(self.panel.model.data(self.panel.model.index(1, 4)), "5")
                self.assertEqual(self.panel.model.data(self.panel.model.index(1, 3)), "0.03")

    def test_unknown_global_metadata_and_missing_positions(self):
        field = ResultField("plugin.energy", "global", ("whole",), ("energy",), ((1.234567890123456,),), "J", "material")
        self.panel.set_result(result_with(field))
        self.assertIn("插件自定义", self.panel.metadata.text())
        self.assertEqual(self.panel.model.data(self.panel.model.index(0, 2)), "—")
        self.panel.table.selectRow(0)
        self.panel.copy_selection()
        self.assertIn("1.234567890123456", self.app.clipboard().text())
        self.assertIn("energy / J", self.app.clipboard().text())

    def test_legacy_arbitrary_fields_do_not_break_native_view(self):
        self.panel.set_result(AnalysisResult("legacy", "1", fields={"old": [1, 2]}))
        self.assertIn("尚未提供通用数据契约", self.panel.metadata.text())
        self.assertEqual(self.panel.model.rowCount(), 0)
        result = AnalysisResult("legacy", "1", fields={identifier: [1, 2] for identifier in
                               ("sensor_measured_strain", "sensor_reconstructed_strain", "sensor_strain_residual")})
        rows, targets, summary = sensor_residual_data(result)
        self.assertEqual((rows, targets), ([], ()))
        self.assertIn("暂不可用", summary)

    def test_full_lazy_table_has_no_sampling_truncation(self):
        field = ResultField("custom", "global", tuple(str(i) for i in range(5000)), ("value",), tuple((float(i),) for i in range(5000)))
        self.panel.set_result(result_with(field))
        self.assertEqual(self.panel.model.rowCount(), 5000)
        self.assertEqual(self.panel.model.data(self.panel.model.index(4999, 1)), "4999")
        self.panel.set_result(None)
        self.assertFalse(self.panel.selector.isEnabled())
        self.assertEqual(self.panel.model.rowCount(), 0)


@isolated_workspace_settings
class SensorResultUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for patcher in (patch.object(gui_qt, "apply_application_theme", return_value="graphite"),
                        patch.object(QMessageBox, "critical")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = gui_qt.ReconstructionMainWindow(theme_id="graphite")
        self.addCleanup(self.dispose)
        self.window.run_reconstruction()
        self.assertIsNotNone(self.window.current_model)

    def dispose(self):
        self.window.hide()
        self.window.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_residual_table_probe_and_summary_uses_snapshot(self):
        w = self.window
        rows, targets, summary = sensor_residual_data(w.current_analysis_result, w.result_sequence)
        self.assertEqual(w.sensor_result_table.table.rowCount(), len(rows))
        self.assertIn("RMS", summary)
        self.assertIn("不是真实误差", w.sensor_explanation.text())
        self.assertTrue(w.result_link.select("sensor", 0, reveal=True))
        self.assertIs(w.result_tabs.currentWidget(), w.sensor_result_panel)
        self.assertEqual(w.result_link.selected.source_id, targets[0].source_id)
        physical = w.result_link.selected.position
        w.thickness_scale_combo.setCurrentText("10")
        self.assertEqual(w.result_link.selected.position, physical)
        expected = w.current_analysis_result.fields["sensor_strain_residual"].values[0][0] * 1e6
        self.assertEqual(targets[0].values[-1][1], expected)
        self.assertIn("残差", w.probe_bar.detail.text())

    def test_selection_survives_display_smoothing_but_not_new_solve(self):
        w = self.window
        w.result_link.select("sensor", 1)
        selected = w.result_link.selected
        w.field_representation_combo.setCurrentIndex(w.field_representation_combo.findData("raw"))
        self.assertEqual(w.result_link.selected, selected)
        w.query_xs_edit.setText("0.1")
        self.assertTrue(w.results_stale)
        self.assertEqual(w.result_link.selected, selected)
        self.assertIn("已过期", w.probe_bar.title.text())
        w.run_reconstruction()
        self.assertIsNone(w.result_link.selected)

    def test_clear_and_failure_restore_field_panels(self):
        w = self.window
        result = w.current_analysis_result
        with patch.object(w, "_render_plot", side_effect=ValueError("render failure")), patch.object(w, "_show_error"):
            w.run_reconstruction()
        self.assertIs(w.current_analysis_result, result)
        self.assertIs(w.result_fields_panel.result, result)
        self.assertGreater(w.sensor_result_table.table.rowCount(), 0)
        w._clear_result_views()
        self.assertEqual(w.sensor_result_table.table.rowCount(), 0)
        self.assertEqual(w.result_fields_panel.model.rowCount(), 0)

    def test_residual_join_is_by_identity_not_row_number(self):
        result = self.window.current_analysis_result
        fields = dict(result.fields)
        observed = fields["sensor_measured_strain"]
        fields[observed.identifier] = replace(observed, entity_ids=observed.entity_ids[::-1], values=observed.values[::-1])
        rows, targets, _summary = sensor_residual_data(replace(result, fields=fields))
        np.testing.assert_allclose([target.values[0][1] for target in targets], np.array(observed.values)[:, 0] * 1e6)
        self.assertEqual(len(rows), len(observed.values))

    def test_invalid_residual_formula_is_not_summarized(self):
        result = self.window.current_analysis_result
        fields = dict(result.fields)
        residual = fields["sensor_strain_residual"]
        fields[residual.identifier] = replace(residual, values=tuple((-99.0e-6,) for _ in residual.values))
        rows, targets, summary = sensor_residual_data(replace(result, fields=fields))
        self.assertEqual((rows, targets), ([], ()))
        self.assertIn("字段值不满足", summary)

    def test_very_short_field_plot_retains_nonzero_data_area(self):
        w = self.window
        w.set_reading_preferences(ReadingPreferences(120, "comfortable"))
        w.canvas.setFixedSize(606, 49)
        w._render_current_view()
        w.canvas.draw()
        self.assertGreater(w.axes.get_window_extent().height, 20)
        self.assertGreater(w._field_colorbar.ax.get_window_extent().height, 20)
        self.assertGreater(len(w.axes.get_xticks()), 1)


if __name__ == "__main__":
    unittest.main()
