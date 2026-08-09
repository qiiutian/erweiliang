import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from ifem.ui.vtk_lifecycle import render_interactor_now, shutdown_interactor


class _FakeTimer:
    def __init__(self):
        self.stop_count = 0

    def stop(self):
        self.stop_count += 1


class _FakeSignal:
    def __init__(self):
        self.disconnect_count = 0

    def disconnect(self):
        self.disconnect_count += 1


class _FakeVtkInteractor:
    def __init__(self):
        self.disable_count = 0

    def Disable(self):
        self.disable_count += 1


class _FakePlotter(QObject):
    def __init__(self):
        super().__init__()
        self._closed = False
        self.render_timer = _FakeTimer()
        self._Timer = _FakeTimer()
        self.render_signal = _FakeSignal()
        self.iren = SimpleNamespace(interactor=_FakeVtkInteractor())
        self.render_count = 0
        self.close_count = 0

    def _render(self):
        self.render_count += 1

    def close(self):
        self.close_count += 1
        self._closed = True


class VtkLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_render_uses_synchronous_qt_slot_and_stops_after_close(self):
        plotter = _FakePlotter()

        self.assertTrue(render_interactor_now(plotter))
        self.assertEqual(plotter.render_count, 1)
        plotter._closed = True
        self.assertFalse(render_interactor_now(plotter))
        self.assertEqual(plotter.render_count, 1)

    def test_shutdown_stops_timers_signals_and_vtk_before_close(self):
        plotter = _FakePlotter()

        shutdown_interactor(plotter)

        self.assertEqual(plotter.render_timer.stop_count, 1)
        self.assertEqual(plotter._Timer.stop_count, 1)
        self.assertEqual(plotter.render_signal.disconnect_count, 1)
        self.assertEqual(plotter.iren.interactor.disable_count, 1)
        self.assertEqual(plotter.close_count, 1)
        self.assertTrue(plotter._closed)


if __name__ == "__main__":
    unittest.main()
