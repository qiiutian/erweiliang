"""Real Qt worker lifecycle checks without project settings or native views."""

import os
import threading
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ifem.domain.analysis import AnalysisCancelled
from ifem.ui.analysis_job import AnalysisJobController, _RUNNING_THREADS


class AnalysisJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = AnalysisJobController()
        self.events = []
        self.callback_threads = []
        for name in ("progress", "succeeded", "failed", "cancelled", "finished"):
            getattr(self.controller, name).connect(
                lambda *args, event=name: self._record(event, args)
            )
        self.release = threading.Event()
        self.entered = threading.Event()
        self.addCleanup(self._dispose)

    def _record(self, name, args):
        self.events.append((name, args))
        self.callback_threads.append(QThread.currentThread())

    def _until(self, predicate, timeout=3000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(2)
        self.assertTrue(predicate(), "后台任务没有在测试时限内完成。")

    def _dispose(self):
        self.release.set()
        try:
            self.controller.shutdown()
        except RuntimeError:  # The destruction test deliberately deletes it.
            pass
        self._until(lambda: not _RUNNING_THREADS)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _service(self, callback):
        return SimpleNamespace(run=callback)

    def _blocking(self, config, **kwargs):
        self.entered.set()
        self.release.wait(2)
        return {"config": config, "kwargs": kwargs}

    def _finish(self):
        self._until(lambda: not self.controller.is_running)
        self.app.processEvents()

    def test_success_runs_off_main_thread_with_main_thread_ordered_callbacks(self):
        observed = []

        def run(config, **kwargs):
            observed.append(QThread.currentThread())
            kwargs["progress"](0.35, "正在组装")
            return {"answer": 42}

        job = self.controller.start(self._service(run), {}, snapshot_key=12)
        self._finish()
        self.assertNotEqual(observed[0], self.app.thread())
        self.assertEqual([name for name, _ in self.events], ["progress", "succeeded", "finished"])
        self.assertTrue(all(thread == self.app.thread() for thread in self.callback_threads))
        self.assertEqual(self.events[1][1], (job, 12, {"answer": 42}))
        self.assertEqual(self.events[2][1], (job, 12))
        self.assertIsNone(self.controller.active_job_id)

    def test_inputs_are_copied_before_worker_observes_them(self):
        config = {"nodes": [0, 1]}
        parameters = {"options": {"n": 3}}
        project = {"sensors": [{"strain": 0.01}]}
        snapshot = {"generation": [4]}
        self.controller.start(
            self._service(self._blocking), config,
            parameters=parameters, project=project, snapshot_key=snapshot,
            algorithm_id="demo",
        )
        self.assertTrue(self.entered.wait(1))
        config["nodes"].append(2)
        parameters["options"]["n"] = 50
        project["sensors"][0]["strain"] = 99
        snapshot["generation"][0] = 7
        returned_key = self.controller.snapshot_key
        returned_key["generation"][0] = 100
        self.release.set()
        self._finish()
        job, captured_key, result = self.events[-2][1]
        self.assertEqual(captured_key, {"generation": [4]})
        self.assertEqual(result["config"], {"nodes": [0, 1]})
        self.assertEqual(result["kwargs"]["parameters"], {"options": {"n": 3}})
        self.assertEqual(result["kwargs"]["project"], {"sensors": [{"strain": 0.01}]})
        self.assertEqual(result["kwargs"]["algorithm_id"], "demo")

    def test_cancel_does_not_kill_uncooperative_service_or_publish_result(self):
        self.controller.start(self._service(self._blocking), {}, snapshot_key=8)
        self.assertTrue(self.entered.wait(1))
        self.assertTrue(self.controller.cancel())
        self.assertTrue(self.controller.cancellation_requested)
        self.app.processEvents()
        self.assertTrue(self.controller.is_running)
        self.assertEqual(self.events, [])
        self.release.set()
        self._finish()
        self.assertEqual([name for name, _ in self.events], ["cancelled", "finished"])

    def test_cancel_after_native_return_but_before_delivery_still_suppresses_success(self):
        native_done = threading.Event()

        def run(config, **kwargs):
            native_done.set()
            return 7

        self.controller.start(self._service(run), {}, snapshot_key="snapshot")
        self.assertTrue(native_done.wait(1))
        self.controller.cancel()  # No Qt event processing has delivered the result.
        self._finish()
        self.assertEqual([name for name, _ in self.events], ["cancelled", "finished"])

    def test_service_cancellation_is_distinct_from_failure(self):
        def run(config, **kwargs):
            raise AnalysisCancelled("stop")

        self.controller.start(self._service(run), {})
        self._finish()
        self.assertEqual([name for name, _ in self.events], ["cancelled", "finished"])

    def test_failure_is_delivered_once_and_controller_can_be_reused(self):
        failure = ValueError("invalid solve")

        def run(config, **kwargs):
            raise failure

        first = self.controller.start(self._service(run), {}, snapshot_key=1)
        self._finish()
        self.assertEqual(self.events[0], ("failed", (first, 1, failure)))
        self.assertEqual([name for name, _ in self.events], ["failed", "finished"])
        second = self.controller.start(self._service(lambda *_args, **_kwargs: 2), {}, snapshot_key=2)
        self._finish()
        self.assertNotEqual(first, second)
        self.assertEqual(self.events[-2], ("succeeded", (second, 2, 2)))

    def test_queued_progress_and_late_failure_are_suppressed_after_cancel(self):
        def run(config, **kwargs):
            kwargs["progress"](0.25, "stage")
            self.entered.set()
            self.release.wait(2)
            raise ValueError("late failure")

        self.controller.start(self._service(run), {})
        self.assertTrue(self.entered.wait(1))
        self.controller.cancel()
        self.release.set()
        self._finish()
        self.assertEqual([name for name, _ in self.events], ["cancelled", "finished"])

    def test_duplicate_start_and_shutdown_are_explicit(self):
        self.controller.start(self._service(self._blocking), {})
        with self.assertRaisesRegex(RuntimeError, "已有"):
            self.controller.start(self._service(self._blocking), {})
        self.assertFalse(self.controller.shutdown())
        self.assertFalse(self.controller.shutdown())
        with self.assertRaisesRegex(RuntimeError, "关闭"):
            self.controller.start(self._service(self._blocking), {})
        self.release.set()
        self._finish()
        self.assertTrue(self.controller.shutdown())
        self.assertFalse(self.controller.cancel())

    def test_gui_timer_remains_responsive_while_service_waits(self):
        ticks = []
        timer = QTimer()
        timer.setInterval(2)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            self.controller.start(self._service(self._blocking), {})
            self._until(lambda: len(ticks) >= 3)
            self.assertTrue(self.controller.is_running)
        finally:
            timer.stop()
        self.release.set()
        self._finish()

    def test_deleting_owner_cancels_but_retains_thread_until_it_really_finishes(self):
        owner = QObject()
        self.controller.setParent(owner)
        self.controller.start(self._service(self._blocking), {})
        self.assertTrue(self.entered.wait(1))
        worker = self.controller._active
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(worker.cancellation.is_cancelled)
        self.assertIn(worker, _RUNNING_THREADS)
        self.assertTrue(worker.isRunning())
        self.release.set()
        self._until(lambda: not _RUNNING_THREADS)
        self.assertEqual(self.events, [])

    def test_invalid_progress_is_ignored_and_finite_values_are_bounded(self):
        def run(config, **kwargs):
            for value in (float("nan"), float("inf"), "bad", -0.5, 0.35, 3):
                kwargs["progress"](value, "stage")
            return 1

        self.controller.start(self._service(run), {})
        self._finish()
        values = [args[2] for name, args in self.events if name == "progress"]
        self.assertEqual(values, [0.0, 0.35, 1.0])

    def test_invalid_service_or_copy_failure_does_not_leave_busy_state(self):
        with self.assertRaises(TypeError):
            self.controller.start(object(), {})

        class Uncopyable:
            def __deepcopy__(self, memo):
                raise ValueError("cannot capture")

        with self.assertRaisesRegex(ValueError, "capture"):
            self.controller.start(self._service(self._blocking), {"value": Uncopyable()})
        self.assertFalse(self.controller.is_running)
        self.assertFalse(_RUNNING_THREADS)

    def test_public_snapshot_payload_cannot_change_later_terminal_identity(self):
        def run(config, **kwargs):
            kwargs["progress"](0.5, "stage")
            return 1

        self.controller.progress.connect(lambda _job, key, *_args: key.update(generation=99))
        self.controller.succeeded.connect(lambda _job, key, _result: key.update(generation=100))
        self.controller.start(self._service(run), {}, snapshot_key={"generation": 3})
        self._finish()
        self.assertEqual(self.events[-1][1][1], {"generation": 3})

    def test_calls_from_another_thread_fail_before_starting_work(self):
        failures = []

        def invoke():
            for action in (
                lambda: self.controller.start(self._service(self._blocking), {}),
                self.controller.cancel,
                self.controller.shutdown,
            ):
                try:
                    action()
                except RuntimeError as error:
                    failures.append(str(error))

        caller = threading.Thread(target=invoke)
        caller.start()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(len(failures), 3)
        self.assertFalse(self.controller.is_running)
        self.assertFalse(self.controller._closed)

    def test_plugin_base_exception_does_not_strand_the_job(self):
        failure = SystemExit("plugin requested exit")

        def run(config, **kwargs):
            raise failure

        self.controller.start(self._service(run), {})
        self._finish()
        self.assertEqual([name for name, _ in self.events], ["failed", "finished"])
        self.assertIs(self.events[0][1][2], failure)

    def test_real_default_service_matches_synchronous_result(self):
        import numpy as np
        from config_adapter import get_sample_config
        from ifem.application.analysis_service import create_default_analysis_service
        from ifem.infrastructure import project_from_legacy_config

        service = create_default_analysis_service()
        config = get_sample_config()
        project = project_from_legacy_config(config)
        baseline = service.run(config, project=project)
        self.controller.start(service, config, project=project, snapshot_key=15)
        self._finish()
        self.assertEqual(self.events[-2][0], "succeeded")
        result = self.events[-2][1][2]
        np.testing.assert_allclose(result.native_model.U, baseline.native_model.U)
        self.assertEqual(result.state, baseline.state)
        self.assertEqual(
            [args[2] for name, args in self.events if name == "progress"],
            [0.0, 0.15, 0.35, 0.9, 1.0],
        )


if __name__ == "__main__":
    unittest.main()
