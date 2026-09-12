import math
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import shiboken6

from ifem.ui.start_animation import (
    BeamReconstructionAnimation,
    _prefers_reduced_motion,
    _system_reduced_motion,
)
from ifem.ui.theme import THEMES


class StartAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.environment = patch.dict(os.environ, {"IFEM_REDUCED_MOTION": "0"})
        self.environment.start()
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if shiboken6.isValid(widget):
                widget.close()
        self.app.processEvents()
        self.environment.stop()

    def make_animation(self, parent=None):
        widget = BeamReconstructionAnimation(parent, theme_id="porcelain_blue")
        widget.resize(720, 440)
        self.widgets.append(widget)
        return widget

    def activate(self, widget):
        widget.show()
        self.app.processEvents()
        # The offscreen platform need not own OS focus. Exercise the same slot
        # that receives Qt's application-state event in a visible desktop app.
        widget._application_state_changed(Qt.ApplicationState.ApplicationActive)

    def test_animation_stages_are_smooth_and_distinct(self):
        widget = self.make_animation()
        changes = []
        widget.phaseChanged.connect(changes.append)
        for phase, name, amplitude in (
            (0.10, "应变观测", 0.0),
            (0.42, "形态重构", 0.5),
            (0.70, "位移重构", 1.0),
            (1.0, "位移重构", 0.0),
        ):
            widget.set_phase(phase)
            self.assertEqual(widget.phase_name, name)
            self.assertAlmostEqual(widget._amplitude(), amplitude)
        self.assertEqual(changes, ["应变观测", "形态重构", "位移重构"])
        for boundary in (0.20, 0.64, 0.83):
            widget.set_phase(boundary - 0.0001)
            before = widget._amplitude()
            widget.set_phase(boundary + 0.0001)
            self.assertLess(abs(widget._amplitude() - before), 0.00001)

    def test_fixed_frame_is_paused_and_invalid_input_does_not_mutate_it(self):
        widget = self.make_animation()
        self.activate(widget)
        widget.set_phase(0.47)
        self.assertTrue(widget.is_paused)
        self.assertFalse(widget._timer.isActive())
        for invalid in (-0.001, 1.001, float("inf"), float("nan")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                widget.set_phase(invalid)
            self.assertEqual(widget.phase, 0.47)

    def test_play_pause_resume_has_no_hidden_elapsed_time_jump(self):
        widget = self.make_animation()
        widget.set_phase(0.4)
        self.activate(widget)
        widget.set_paused(False)
        self.assertTrue(widget._timer.isActive())
        self.assertGreaterEqual(widget._timer.interval(), 34)
        QTest.qWait(90)
        self.assertGreater(widget.phase, 0.4)
        widget.set_paused(True)
        paused_phase = widget.phase
        self.assertFalse(widget._elapsed.isValid())
        QTest.qWait(250)
        self.assertEqual(widget.phase, paused_phase)
        widget.set_paused(False)
        # Allow more than one frame deadline when the full UI suite is busy.
        # The bound below still rejects catching up the paused interval.
        QTest.qWait(100)
        self.assertGreater(widget.phase, paused_phase)
        self.assertLess(widget.phase - paused_phase, 0.02)

    def test_hidden_parent_and_inactive_application_stop_timer(self):
        parent = QWidget()
        self.widgets.append(parent)
        widget = self.make_animation(parent)
        parent.show()
        self.activate(widget)
        self.assertTrue(widget._timer.isActive())
        parent.hide()
        self.assertFalse(widget._timer.isActive())
        phase = widget.phase
        widget._tick()
        self.assertEqual(widget.phase, phase)
        parent.show()
        self.app.processEvents()
        widget._application_state_changed(Qt.ApplicationState.ApplicationActive)
        self.assertTrue(widget._timer.isActive())
        widget._application_state_changed(Qt.ApplicationState.ApplicationInactive)
        self.assertFalse(widget._timer.isActive())
        widget._application_state_changed(Qt.ApplicationState.ApplicationActive)
        self.assertTrue(widget._timer.isActive())

    def test_shutdown_and_close_cannot_restart_timer(self):
        for action in ("shutdown", "close"):
            with self.subTest(action=action):
                widget = self.make_animation()
                self.activate(widget)
                getattr(widget, action)()
                self.assertFalse(widget._timer.isActive())
                self.assertFalse(widget._elapsed.isValid())
                widget.show()
                widget.set_paused(False)
                widget._application_state_changed(Qt.ApplicationState.ApplicationActive)
                self.assertFalse(widget._timer.isActive())

    def test_destroying_animation_also_destroys_owned_timer(self):
        widget = self.make_animation()
        self.activate(widget)
        timer = widget._timer
        destroyed = []
        timer.destroyed.connect(lambda: destroyed.append(True))
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(shiboken6.isValid(widget))
        self.assertFalse(shiboken6.isValid(timer))
        self.assertEqual(destroyed, [True])
        # Application-level state events must not invoke the deleted widget.
        self.app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)

    def test_reduced_motion_remains_static_even_when_play_is_requested(self):
        with patch.dict(os.environ, {"IFEM_REDUCED_MOTION": "1"}):
            widget = self.make_animation()
        self.activate(widget)
        initial_phase = widget.phase
        self.assertTrue(widget.reduced_motion)
        self.assertTrue(widget.is_paused)
        self.assertAlmostEqual(widget._amplitude(), 1.0)
        widget.set_paused(False)
        self.assertTrue(widget.is_paused)
        self.assertFalse(widget._timer.isActive())
        QTest.qWait(50)
        self.assertEqual(widget.phase, initial_phase)

    def test_explicit_motion_environment_overrides_system_preference(self):
        for override, expected in (("1", True), ("true", True), ("0", False), ("false", False)):
            with self.subTest(override=override), patch.dict(
                os.environ, {"IFEM_REDUCED_MOTION": override}
            ), patch("ifem.ui.start_animation._system_reduced_motion") as system:
                self.assertEqual(_prefers_reduced_motion(), expected)
                system.assert_not_called()
        with patch.dict(os.environ, {"IFEM_REDUCED_MOTION": ""}), patch(
            "ifem.ui.start_animation._system_reduced_motion", return_value=True
        ):
            self.assertTrue(_prefers_reduced_motion())

    def test_macos_motion_preference_is_read_only_bounded_and_cached(self):
        _system_reduced_motion.cache_clear()
        self.addCleanup(_system_reduced_motion.cache_clear)
        with patch("ifem.ui.start_animation.sys.platform", "darwin"), patch(
            "ifem.ui.start_animation.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="1\n"),
        ) as read:
            self.assertTrue(_system_reduced_motion())
            self.assertTrue(_system_reduced_motion())
            read.assert_called_once()
            self.assertEqual(read.call_args.args[0], [
                "/usr/bin/defaults", "read", "com.apple.universalaccess", "reduceMotion",
            ])
            self.assertLessEqual(read.call_args.kwargs["timeout"], 0.25)

    def test_unavailable_system_motion_preference_never_blocks_startup(self):
        self.addCleanup(_system_reduced_motion.cache_clear)
        for failure in (OSError("not available"), subprocess.TimeoutExpired("defaults", 0.25)):
            _system_reduced_motion.cache_clear()
            with self.subTest(failure=failure), patch(
                "ifem.ui.start_animation.sys.platform", "darwin"
            ), patch("ifem.ui.start_animation.subprocess.run", side_effect=failure):
                self.assertFalse(_system_reduced_motion())
        _system_reduced_motion.cache_clear()
        with patch("ifem.ui.start_animation.sys.platform", "linux"), patch(
            "ifem.ui.start_animation.subprocess.run"
        ) as read:
            self.assertFalse(_system_reduced_motion())
            read.assert_not_called()

    def test_resize_and_theme_only_affect_presentation_not_geometry(self):
        widget = self.make_animation()
        widget.set_phase(0.68)
        original_geometry = [widget._surface_point(t, across, 1.0)
                             for t in (0.0, 0.2, 0.5, 0.8, 1.0)
                             for across in (-0.5, 0.0, 0.5)]
        for theme in THEMES:
            widget.set_theme(theme.identifier)
            self.assertEqual(widget._color("primary").name().upper(), theme.color("primary"))
            for size in ((260, 190), (720, 440), (1100, 560)):
                with self.subTest(theme=theme.identifier, size=size):
                    widget.resize(*size)
                    target = widget._scene_rect()
                    self.assertTrue(QRectF(widget.rect()).contains(target))
                    self.assertAlmostEqual(target.width() / target.height(), 720 / 440)
                    self.assertFalse(widget.grab().isNull())
                    geometry = [widget._surface_point(t, across, 1.0)
                                for t in (0.0, 0.2, 0.5, 0.8, 1.0)
                                for across in (-0.5, 0.0, 0.5)]
                    self.assertEqual(geometry, original_geometry)
                    self.assertEqual(widget.phase, 0.68)
        self.assertEqual(len(widget.SENSOR_POSITIONS), 6)
        self.assertTrue(all(math.isfinite(point.x()) and math.isfinite(point.y())
                            for point in original_geometry))

    def test_complete_animation_geometry_stays_within_vector_canvas(self):
        widget = self.make_animation()
        bounds = QRectF(0, 0, widget.DESIGN_SIZE.width(), widget.DESIGN_SIZE.height())
        for frame in range(101):
            widget.set_phase(frame / 100)
            amplitude = widget._amplitude()
            for index in range(73):
                for across in (-0.5, 0.5):
                    point = widget._surface_point(index / 72, across, amplitude, depth=0.085)
                    self.assertTrue(bounds.contains(point), (frame, index, point))


if __name__ == "__main__":
    unittest.main()
