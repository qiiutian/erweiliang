"""Main-window background analysis, stale snapshots, and safe exit contracts."""

import os
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import gui_qt
from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm
from ifem.application.analysis_service import create_default_analysis_service
from ifem.domain.analysis import AlgorithmMetadata
from ifem.ui.analysis_job import _RUNNING_THREADS
from test_ui_support import isolated_workspace_settings


class _ControlledService:
    """Keep real registry/readiness; gate only the solver with explicit events."""

    def __init__(self, delegate=None):
        self.delegate = delegate or create_default_analysis_service()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.hold = True
        self.failure = None
        self.calls = 0
        self.threads = []

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def run(self, config, **kwargs):
        self.calls += 1
        self.threads.append(QThread.currentThread())
        if self.hold:
            kwargs["progress"](0.35, "测试组装阶段")
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("测试未释放后台服务")
        if self.failure is not None:
            raise self.failure
        return self.delegate.run(config, **kwargs)


@isolated_workspace_settings
class AnalysisJobUiTests(unittest.TestCase):
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
        self.service = _ControlledService()
        self.window = gui_qt.ReconstructionMainWindow(
            theme_id="graphite", analysis_service=self.service,
        )
        self.addCleanup(self._dispose)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()

    def _until(self, predicate, timeout=4000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(2)
        self.assertTrue(predicate(), "窗口后台任务没有在测试时限内完成。")

    def _dispose(self):
        self.window._close_after_analysis = False
        self.service.release.set()
        if self.window.analysis_jobs.is_running:
            self.window.cancel_reconstruction()
        self._until(lambda: not self.window.analysis_jobs.is_running)
        self._until(lambda: not _RUNNING_THREADS)
        self.window.hide()
        self.window.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _start(self, action=None):
        (action or self.window.start_reconstruction)()
        self._until(self.service.entered.is_set)
        self._until(lambda: self.window.analysis_progress_bar.value() == 35)
        self.assertTrue(self.window._analysis_busy)
        self.assertTrue(self.window.analysis_jobs.is_running)

    def _finish(self):
        self.service.release.set()
        self._until(lambda: not self.window._analysis_busy)
        self.app.processEvents()

    def _baseline(self):
        self.service.hold = False
        with patch.object(self.window, "_show_error") as error:
            self.window.run_reconstruction()
        error.assert_not_called()
        self.assertIsNotNone(self.window.current_model)
        self.service.hold = True
        self.service.calls = 0
        self.service.threads.clear()
        return self.window.current_analysis_result, self.window.current_result_frame

    def test_background_success_progress_and_busy_controls_are_restored(self):
        self._start()
        window = self.window
        self.assertEqual(window.analysis_progress_label.text(), "测试组装阶段")
        self.assertTrue(window.analysis_progress_panel.isVisible())
        self.assertFalse(window.run_button.isEnabled())
        self.assertFalse(window.run_action.isEnabled())
        self.assertFalse(window.left_panel.isEnabled())
        self.assertFalse(window.save_as_action.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in window.scale_buttons.values()))
        self.assertTrue(window.analysis_cancel_button.isEnabled())
        self.assertTrue(all(thread != self.app.thread() for thread in self.service.threads))
        self._finish()
        self.assertIsNotNone(window.current_analysis_result)
        self.assertIsNotNone(window.current_model)
        self.assertTrue(window.result_link.targets["node"])
        self.assertTrue(window.run_button.isEnabled())
        self.assertTrue(window.left_panel.isEnabled())
        self.assertTrue(window.save_as_action.isEnabled())
        self.assertTrue(all(button.isEnabled() for button in window.scale_buttons.values()))
        self.assertFalse(window.analysis_progress_panel.isVisible())
        self.assertIsNone(window._active_analysis_job)
        self.assertIsNone(window._pending_analysis_config)
        self.assertIn("重构完成", window.run_status_label.text())

    def test_duplicate_start_is_ignored_without_replacing_live_job(self):
        self._start()
        identifier = self.window._active_analysis_job
        self.window.start_reconstruction()
        self.window.run_action.trigger()
        self.window.run_button.click()
        self.assertEqual(self.service.calls, 1)
        self.assertEqual(self.window._active_analysis_job, identifier)
        self._finish()

    def test_cancel_preserves_existing_result_and_waits_for_service(self):
        previous_result, previous_frame = self._baseline()
        sequence = self.window.result_sequence
        self._start()
        self.window.analysis_cancel_button.click()
        self.assertTrue(self.window.analysis_jobs.cancellation_requested)
        self.assertFalse(self.window.analysis_cancel_button.isEnabled())
        self.assertTrue(self.window._analysis_busy)
        self.assertIn("等待当前计算步骤", self.window.analysis_progress_label.text())
        self._finish()
        self.assertIs(self.window.current_analysis_result, previous_result)
        self.assertIs(self.window.current_result_frame, previous_frame)
        self.assertEqual(self.window.result_sequence, sequence)
        self.assertIn("已取消", self.window.run_status_label.text())
        self.assertFalse(self.window.results_stale)

    def test_generation_change_does_not_install_old_snapshot(self):
        previous_result, previous_frame = self._baseline()
        self._start()
        generation = self.window._analysis_generation
        # Disabled UI widgets still may change through programmatic integrations.
        self.window.query_xs_edit.setText("0.45, 1.6")
        self.assertGreater(self.window._analysis_generation, generation)
        with patch.object(self.window, "_apply_analysis_result") as apply_result:
            self._finish()
        apply_result.assert_not_called()
        self.assertIs(self.window.current_analysis_result, previous_result)
        self.assertIs(self.window.current_result_frame, previous_frame)
        self.assertEqual(self.window.query_xs_edit.text(), "0.45, 1.6")
        self.assertTrue(self.window.results_stale)
        self.assertIn("未应用", self.window.run_status_label.text())

    def test_project_replacement_does_not_install_old_job(self):
        self._baseline()
        self._start()
        project = self.window.current_project_document.revised(name="新工程快照")
        self.window._apply_project_document(project, dirty=False, status_text="已切换")
        current_frame = self.window.current_result_frame
        with patch.object(self.window, "_apply_analysis_result") as apply_result:
            self._finish()
        apply_result.assert_not_called()
        self.assertEqual(self.window.current_project_document.name, "新工程快照")
        self.assertIs(self.window.current_result_frame, current_frame)

    def test_worker_failure_preserves_result_and_restores_controls(self):
        previous_result, previous_frame = self._baseline()
        failure = ValueError("测试求解失败")
        self.service.failure = failure
        self._start()
        with patch.object(self.window, "_show_error") as error:
            self._finish()
        error.assert_called_once_with(failure)
        self.assertIs(self.window.current_analysis_result, previous_result)
        self.assertIs(self.window.current_result_frame, previous_frame)
        self.assertTrue(self.window.run_button.isEnabled())

    def test_view_installation_failure_restores_previous_snapshot_and_probe(self):
        previous_result, previous_frame = self._baseline()
        self.window.result_link.select("node", 1)
        selected = self.window.result_link.selected
        previous_rows = self.window.sensor_result_table.table.rowCount()
        original_fill = self.window._fill_contract_result_tables
        attempts = []

        def fail_once():
            attempts.append(1)
            if len(attempts) == 1:
                raise ValueError("测试结果视图更新失败")
            original_fill()

        self._start()
        with patch.object(self.window, "_fill_contract_result_tables", side_effect=fail_once), \
                patch.object(self.window, "_show_error") as error:
            self._finish()
        error.assert_called_once()
        self.assertIs(self.window.current_analysis_result, previous_result)
        self.assertEqual(self.window.current_result_frame.sequence, previous_frame.sequence)
        np.testing.assert_array_equal(
            self.window.current_result_frame.nodal_displacement, previous_frame.nodal_displacement,
        )
        self.assertEqual(self.window.result_link.selected, selected)
        self.assertEqual(self.window.sensor_result_table.table.rowCount(), previous_rows)
        self.assertTrue(self.window.run_button.isEnabled())

    def test_stale_worker_failure_does_not_report_error_for_new_input(self):
        self.service.failure = ValueError("旧任务失败")
        self._start()
        self.window.query_xs_edit.setText("0.45")
        with patch.object(self.window, "_show_error") as error:
            self._finish()
        error.assert_not_called()
        self.assertIn("忽略旧任务错误", self.window.run_status_label.text())

    def test_close_requests_cancel_then_waits_before_actual_shutdown(self):
        self.window.project_dirty = False
        self._start()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window._close_after_analysis)
        self.assertFalse(self.window._is_shut_down)
        self.assertTrue(self.window.analysis_jobs.is_running)
        self.assertTrue(self.window.analysis_jobs.cancellation_requested)
        self._finish()
        self._until(lambda: self.window._is_shut_down)
        self.assertFalse(self.window.isVisible())

    def test_declining_close_keeps_job_and_window_alive(self):
        self._start()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.window.close())
        self.assertFalse(self.window._close_after_analysis)
        self.assertFalse(self.window.analysis_jobs.cancellation_requested)
        self._finish()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window._is_shut_down)

    def test_declining_second_close_withdraws_pending_close_without_uncancelling_job(self):
        self.window.project_dirty = False
        self._start()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.close()
        self.assertTrue(self.window._close_after_analysis)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.window.close()
        self.assertFalse(self.window._close_after_analysis)
        self.assertTrue(self.window.analysis_jobs.cancellation_requested)
        self._finish()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window._is_shut_down)

    def test_application_quit_is_deferred_until_worker_finishes(self):
        self.window.project_dirty = False
        self._start()
        quitting = QSignalSpy(self.app.aboutToQuit)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            self.assertTrue(QCoreApplication.sendEvent(self.app, QEvent(QEvent.Type.Quit)))
        question.assert_called_once()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.analysis_jobs.is_running)
        self.assertFalse(self.window.analysis_jobs.cancellation_requested)
        self.assertFalse(self.window._close_after_analysis)
        self.assertEqual(quitting.count(), 0)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question:
            self.assertTrue(QCoreApplication.sendEvent(self.app, QEvent(QEvent.Type.Quit)))
        question.assert_called_once()
        self.assertTrue(self.window._close_after_analysis)
        self.assertTrue(self.window.analysis_jobs.cancellation_requested)
        self.assertFalse(self.window._is_shut_down)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(quitting.count(), 0)
        self._finish()
        self._until(lambda: self.window._is_shut_down)
        self.assertFalse(self.window.isVisible())

    def test_busy_command_calls_do_not_open_dialogs_or_save_project(self):
        self._start()
        project = self.window.current_project_document
        dirty = self.window.project_dirty
        generation = self.window._analysis_generation
        previous_path = self.window.current_project_path
        with patch.object(gui_qt.ProjectNameDialog, "choose_project_name", return_value=None) as choose, \
                patch.object(gui_qt, "BeamModelerDialog") as modeler, \
                patch.object(self.window, "_save_project_to") as save:
            modeler.return_value.exec.return_value = QDialog.DialogCode.Rejected
            for path in (None, Path("/private/tmp/ifem-background-test-not-written.ifem")):
                self.window.current_project_path = path
                self.assertFalse(self.window.save_current_project())
                self.assertFalse(self.window.save_project_as())
            self.window.open_interactive_modeler()
        self.window.current_project_path = previous_path
        choose.assert_not_called()
        modeler.assert_not_called()
        save.assert_not_called()
        self.assertIs(self.window.current_project_document, project)
        self.assertEqual(self.window.project_dirty, dirty)
        self.assertEqual(self.window._analysis_generation, generation)
        self._finish()

    def test_cancelled_save_prompt_after_job_close_keeps_controller_reusable(self):
        self.window.project_dirty = True
        self._start()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.close()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self._finish()
        self.assertFalse(self.window._is_shut_down)
        self.assertFalse(self.window._close_after_analysis)
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.analysis_jobs._closed)
        self.assertTrue(self.window.run_button.isEnabled())

    def test_missing_plugin_does_not_start_worker(self):
        project = self.window.current_project_document
        case = replace(project.analysis_cases[0], algorithm_id="vendor.missing.background")
        self.window._apply_project_document(
            project.revised(analysis_cases=(case,)), dirty=False, status_text="缺失插件",
        )
        with patch.object(self.window.analysis_jobs, "start") as start:
            self.window.start_reconstruction()
        start.assert_not_called()
        self.assertFalse(self.window.run_button.isEnabled())
        self.assertFalse(self.window.analysis_jobs.is_running)

    def test_incompatible_algorithm_does_not_start_worker(self):
        class SpatialOnlyAlgorithm(BeamSurfaceIntegralAlgorithm):
            metadata = AlgorithmMetadata(
                identifier="ifem.background.spatial-only.test",
                display_name="三维后台测试方法", version="0.1.0",
            )
            capabilities = replace(
                BeamSurfaceIntegralAlgorithm.capabilities, modeling_spaces=("3d",),
            )

        spatial = SpatialOnlyAlgorithm()
        self.service.registry.register(spatial)
        self.window.analysis_setup.set_project(self.window.current_project_document)
        combo = self.window.analysis_setup.algorithm_selector
        index = combo.findData(spatial.metadata.identifier)
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)
        self.app.processEvents()
        self.assertFalse(self.window.analysis_setup.is_compatible)
        with patch.object(self.window.analysis_jobs, "start") as start:
            self.window.start_reconstruction()
        start.assert_not_called()
        self.assertFalse(self.window.run_button.isEnabled())

    def test_run_button_uses_background_entry_not_synchronous_compatibility(self):
        with patch.object(self.window, "run_reconstruction", side_effect=AssertionError("同步入口被触发")):
            self._start(self.window.run_button.click)
            self._finish()
        self.assertEqual(self.service.calls, 1)

    def test_f5_key_uses_background_entry(self):
        self.window.raise_()
        self.window.activateWindow()
        self.window.node_x_edit.setFocus()
        self.app.processEvents()
        with patch.object(self.window, "run_reconstruction", side_effect=AssertionError("同步入口被触发")):
            self._start(lambda: QTest.keyClick(self.window, Qt.Key.Key_F5))
            self._finish()
        self.assertEqual(self.service.calls, 1)

    def test_input_status_and_empty_state_use_background_entry(self):
        for method in ("_activate_input_status", "_activate_empty_state_action"):
            with self.subTest(method=method), patch.object(self.window, "start_reconstruction") as start:
                getattr(self.window, method)()
            start.assert_called_once_with()

    def test_command_palette_run_command_uses_background_entry(self):
        captured = []

        def palette(commands, *_args, **_kwargs):
            command = next(command for command in commands if command.title == "运行重构")
            captured.append(command)
            return SimpleNamespace(exec=lambda: QDialog.DialogCode.Accepted, selected_command=command)

        with patch.object(gui_qt, "CommandPalette", side_effect=palette):
            self._start(self.window.show_command_palette)
            self._finish()
        self.assertEqual(captured[0].callback, self.window.start_reconstruction)


if __name__ == "__main__":
    unittest.main()
