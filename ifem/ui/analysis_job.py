"""Snapshot-isolated background analysis with cooperative cancellation.

Only the supplied service runs in the worker. All public signals are delivered
by the controller on its owning (normally GUI) thread. The caller must retain
the application's event loop until ``finished`` before allowing final exit;
``shutdown`` requests cancellation, never terminates or waits on a worker.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from ifem.domain.analysis import AnalysisCancelled, CancellationToken


# A window/controller can be deleted before an uncooperative plugin returns.
# Never parent a running QThread to that window or let its wrapper be collected.
# Threads release themselves on the GUI event loop after run() really ends.
_RUNNING_THREADS: set[QThread] = set()


@dataclass(frozen=True)
class _JobRequest:
    job_id: str
    snapshot_key: Any
    config: dict
    parameters: dict
    project: Any
    algorithm_id: str | None
    project_only: bool = False


class _AnalysisThread(QThread):
    progress_reported = Signal(float, str)

    def __init__(self, service, request):
        super().__init__()  # No QWidget/QObject parent that could destroy us early.
        self.service = service
        self.request = request
        self.cancellation = CancellationToken()
        self.outcome = None

    def run(self):
        try:
            self.cancellation.raise_if_cancelled()
            kwargs = dict(algorithm_id=self.request.algorithm_id,
                          parameters=self.request.parameters, progress=self._report_progress,
                          cancellation=self.cancellation)
            if self.request.project_only:
                result = self.service.run_project(self.request.project, **kwargs)
            else:
                result = self.service.run(self.request.config, project=self.request.project, **kwargs)
            # Some plugins only check cancellation between expensive operations.
            # A completed calculation must not win over an already requested cancel.
            self.cancellation.raise_if_cancelled()
            self.outcome = ("succeeded", result)
        except AnalysisCancelled:
            self.outcome = ("cancelled", None)
        except BaseException as exc:
            # Even a third-party plugin's SystemExit cannot strand the controller
            # in a busy state or escape from QThread.run into Qt's event machinery.
            self.outcome = ("failed", exc)

    def _report_progress(self, fraction, message):
        self.cancellation.raise_if_cancelled()
        try:
            fraction = float(fraction)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(fraction):
            return
        self.progress_reported.emit(min(1.0, max(0.0, fraction)), str(message))

    @Slot()
    def release(self):
        _RUNNING_THREADS.discard(self)
        self.deleteLater()


class AnalysisJobController(QObject):
    """One live job, immutable input capture, and main-thread terminal delivery.

    ``start`` copies config/parameters/project/snapshot_key before returning.
    The caller still owns semantic freshness: compare job_id and snapshot_key
    with its current project/input generation before installing any result.

    At completion ``is_running`` becomes false, exactly one terminal signal
    (succeeded/failed/cancelled) is emitted, then ``finished`` follows with the
    same identifiers. A cancel request made before that delivery suppresses
    both success and failure, even when the native worker has already returned.

    ``shutdown()`` prevents new jobs and requests cancellation. Its bool return
    is true only when already idle. When false, keep the application/event loop
    alive and defer final close until ``finished``. Cancellation never forcefully
    kills native solver operations; completion can wait for their next checkpoint.
    """

    progress = Signal(str, object, float, str)
    succeeded = Signal(str, object, object)
    failed = Signal(str, object, object)
    cancelled = Signal(str, object)
    finished = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = None
        self._closed = False

    @property
    def is_running(self):
        return self._active is not None

    @property
    def active_job_id(self):
        return None if self._active is None else self._active.request.job_id

    @property
    def snapshot_key(self):
        return None if self._active is None else copy.deepcopy(self._active.request.snapshot_key)

    @property
    def cancellation_requested(self):
        return self._active is not None and self._active.cancellation.is_cancelled

    def _require_owner_thread(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("分析任务控制器必须从所属界面线程调用。")

    def start(
        self,
        service,
        config: Mapping[str, Any],
        *,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        project=None,
        snapshot_key=None,
        project_only=False,
    ) -> str:
        self._require_owner_thread()
        if self._closed:
            raise RuntimeError("分析任务控制器已经关闭。")
        if self.is_running:
            raise RuntimeError("已有分析任务正在运行；请等待完成或取消。")
        method = "run_project" if project_only else "run"
        if not callable(getattr(service, method, None)):
            raise TypeError(f"分析服务必须提供 {method}()。")
        if project_only and project is None:
            raise ValueError("通用分析任务必须提供工程快照。")
        request = _JobRequest(
            job_id=uuid4().hex,
            snapshot_key=copy.deepcopy(snapshot_key),
            config=copy.deepcopy(dict(config)),
            parameters=copy.deepcopy(dict(parameters or {})),
            project=copy.deepcopy(project),
            algorithm_id=algorithm_id,
            project_only=bool(project_only),
        )
        thread = _AnalysisThread(service, request)
        thread.progress_reported.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(thread.release, Qt.ConnectionType.QueuedConnection)
        self.destroyed.connect(thread.cancellation.cancel)
        self._active = thread
        _RUNNING_THREADS.add(thread)
        try:
            thread.start()
        except BaseException:
            self._active = None
            _RUNNING_THREADS.discard(thread)
            self.destroyed.disconnect(thread.cancellation.cancel)
            thread.deleteLater()
            raise
        return request.job_id

    def cancel(self) -> bool:
        self._require_owner_thread()
        if self._active is None:
            return False
        self._active.cancellation.cancel()
        return True

    def shutdown(self) -> bool:
        self._require_owner_thread()
        self._closed = True
        self.cancel()
        return not self.is_running

    @Slot(float, str)
    def _on_progress(self, fraction, message):
        thread = self.sender()
        if thread is not self._active or self._closed or self.cancellation_requested:
            return
        request = thread.request
        self.progress.emit(request.job_id, copy.deepcopy(request.snapshot_key), fraction, message)

    @Slot()
    def _on_finished(self):
        thread = self.sender()
        if thread is not self._active:
            return
        request = thread.request
        self._active = None
        self.destroyed.disconnect(thread.cancellation.cancel)
        outcome, payload = thread.outcome or (
            "failed", RuntimeError("分析任务结束但没有返回结果。")
        )
        if thread.cancellation.is_cancelled or self._closed:
            outcome = "cancelled"
        if outcome == "succeeded":
            self.succeeded.emit(request.job_id, copy.deepcopy(request.snapshot_key), payload)
        elif outcome == "failed":
            self.failed.emit(request.job_id, copy.deepcopy(request.snapshot_key), payload)
        else:
            self.cancelled.emit(request.job_id, copy.deepcopy(request.snapshot_key))
        self.finished.emit(request.job_id, copy.deepcopy(request.snapshot_key))
