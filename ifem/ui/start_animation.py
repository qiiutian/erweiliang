"""A lightweight, illustrative inverse-FEM ribbon for the startup screen.

The geometry is deliberately not connected to project data or a solver. Qt
paints the scene as vectors; no rendering engine or image asset is loaded.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from functools import lru_cache

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from ifem.ui.theme import current_theme_id, resolve_theme


@lru_cache(maxsize=1)
def _system_reduced_motion():
    """Read macOS accessibility once; a missing preference is not a startup error."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "com.apple.universalaccess", "reduceMotion"],
            capture_output=True,
            text=True,
            check=False,
            timeout=0.25,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() in {"1", "true", "yes"}


def _prefers_reduced_motion():
    override = os.environ.get("IFEM_REDUCED_MOTION", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return _system_reduced_motion()


def _smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def _normalize(vector):
    length = math.sqrt(sum(value * value for value in vector))
    return tuple(value / length for value in vector)


def _path(points, *, closed=False):
    result = QPainterPath(points[0])
    for point in points[1:]:
        result.lineTo(point)
    if closed:
        result.closeSubpath()
    return result


class BeamReconstructionAnimation(QWidget):
    """An interruptible observation / reconstruction illustration."""

    phaseChanged = Signal(str)
    CYCLE_SECONDS = 12.0
    FRAME_INTERVAL_MS = 34  # At most 30 fps; geometry remains responsive to resize.
    DESIGN_SIZE = QSize(720, 440)
    SENSOR_POSITIONS = (0.10, 0.25, 0.40, 0.56, 0.73, 0.90)

    def __init__(self, parent=None, *, theme_id=None):
        super().__init__(parent)
        self._theme_id = resolve_theme(theme_id or current_theme_id()).identifier
        self._reduced_motion = _prefers_reduced_motion()
        self._paused = False
        self._shutdown = False
        # A composed reconstructed pose is visible immediately, even before the
        # event loop's first frame. The loop then returns to strain observation.
        self._phase = 0.66
        self._phase_name = "位移重构"
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._elapsed = QElapsedTimer()
        application = QApplication.instance()
        self._application_active = (
            application is not None
            and application.applicationState() == Qt.ApplicationState.ApplicationActive
        )
        if application is not None:
            application.applicationStateChanged.connect(self._application_state_changed)
        self.setObjectName("beamReconstructionAnimation")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(260, 190)
        self.setAccessibleName("由表面应变观测重构空间梁形态的动态示意")
        self.setAccessibleDescription(
            "橙色贴片为应变观测，细网格为重构形态，虚线为参考构形；"
            "变形夸张显示，不是求解结果。可通过启动页的暂停按钮停止动态。"
        )

    @property
    def phase(self):
        return self._phase

    @property
    def phase_name(self):
        return self._phase_name

    @property
    def is_paused(self):
        return self._paused or self._reduced_motion

    @property
    def reduced_motion(self):
        return self._reduced_motion

    def sizeHint(self):
        return self.DESIGN_SIZE

    def set_theme(self, theme_id):
        self._theme_id = resolve_theme(theme_id).identifier
        self.update()

    def set_paused(self, paused):
        self._paused = bool(paused)
        self._sync_playback()

    def set_phase(self, phase):
        """Select a deterministic frame; playback remains paused until resumed."""
        phase = float(phase)
        if not math.isfinite(phase) or not 0.0 <= phase <= 1.0:
            raise ValueError("动画相位必须是 0 到 1 之间的有限数值。")
        self._paused = True
        self._sync_playback()
        self._update_phase(phase)

    def shutdown(self):
        """Permanently stop callbacks when the containing start center finishes."""
        self._shutdown = True
        self._sync_playback()

    @Slot(Qt.ApplicationState)
    def _application_state_changed(self, state):
        self._application_active = state == Qt.ApplicationState.ApplicationActive
        self._sync_playback()

    def _sync_playback(self):
        should_run = (
            self.isVisible() and self._application_active
            and not self.is_paused and not self._shutdown
        )
        if should_run and not self._timer.isActive():
            self._elapsed.start()
            self._timer.start()
        elif not should_run:
            self._timer.stop()
            self._elapsed.invalidate()

    @Slot()
    def _tick(self):
        if not self._timer.isActive() or not self._elapsed.isValid():
            return
        # A busy UI must not jump the complete scene ahead on its next event.
        seconds = min(self._elapsed.restart() / 1000.0, 0.1)
        self._update_phase((self._phase + seconds / self.CYCLE_SECONDS) % 1.0)

    def _update_phase(self, phase):
        self._phase = phase
        name = "应变观测" if phase < 0.20 else "形态重构" if phase < 0.64 else "位移重构"
        if name != self._phase_name:
            self._phase_name = name
            self.phaseChanged.emit(name)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_playback()

    def hideEvent(self, event):
        self._timer.stop()
        self._elapsed.invalidate()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _amplitude(self):
        if self._phase < 0.20:
            return 0.0
        if self._phase < 0.64:
            return _smooth((self._phase - 0.20) / 0.44)
        if self._phase < 0.83:
            return 1.0
        return 1.0 - _smooth((self._phase - 0.83) / 0.17)

    @staticmethod
    def _surface_point(t, across, amplitude, *, depth=0.0):
        """Orthographic view of a twisted ribbon's local section coordinates."""
        angle = 2.0 * math.pi * t
        x = 6.8 * t
        y = amplitude * 0.72 * math.sin(angle)
        z = amplitude * (1.05 * math.sin(angle) + 0.18 * math.sin(math.pi * t))
        dy = amplitude * 0.72 * 2.0 * math.pi * math.cos(angle)
        dz = amplitude * (1.05 * 2.0 * math.pi * math.cos(angle)
                          + 0.18 * math.pi * math.cos(math.pi * t))
        tangent = _normalize((6.8, dy, dz))
        normal = _normalize((-dy, 6.8, 0.0))
        binormal = (
            -tangent[2] * normal[1],
            tangent[2] * normal[0],
            tangent[0] * normal[1] - tangent[1] * normal[0],
        )
        twist = 0.18 + amplitude * 0.38 * math.sin(math.pi * (t - 0.12))
        lateral = tuple(
            math.cos(twist) * n + math.sin(twist) * b
            for n, b in zip(normal, binormal)
        )
        width = 1.42 - 0.16 * t
        x += lateral[0] * across * width
        y += lateral[1] * across * width
        z += lateral[2] * across * width - depth
        return QPointF(90.0 + 80.0 * x + 42.0 * y,
                       284.0 - 13.0 * x + 21.0 * y - 86.0 * z)

    def _color(self, role, alpha=1.0):
        value = QColor(resolve_theme(self._theme_id).color(role))
        value.setAlphaF(max(0.0, min(1.0, alpha)))
        return value

    def _scene_rect(self):
        available = QRectF(self.rect()).adjusted(6.0, 2.0, -6.0, -2.0)
        scale = min(available.width() / 720.0, available.height() / 440.0)
        target = QRectF(0, 0, 720.0 * scale, 440.0 * scale)
        target.moveCenter(available.center())
        return target

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        target = self._scene_rect()
        painter.translate(target.topLeft())
        painter.scale(target.width() / 720.0, target.height() / 440.0)
        amplitude = self._amplitude()
        self._draw_reference(painter, amplitude)
        self._draw_ribbon(painter, amplitude)
        self._draw_sensors(painter, amplitude)
        painter.end()

    def _draw_reference(self, painter, amplitude):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(self._color("border_strong", 0.26 + 0.30 * amplitude), 1.1)
        pen.setDashPattern([5.0, 7.0])
        painter.setPen(pen)
        for across in (-0.5, 0.5):
            painter.drawPath(_path([
                self._surface_point(index / 24.0, across, 0.0)
                for index in range(25)
            ]))
        for index in (0, 6, 12, 18, 24):
            t = index / 24.0
            painter.drawLine(self._surface_point(t, -0.5, 0.0),
                             self._surface_point(t, 0.5, 0.0))

    def _draw_ribbon(self, painter, amplitude):
        sections = tuple(index / 72.0 for index in range(73))
        back = [self._surface_point(t, -0.5, amplitude) for t in sections]
        front = [self._surface_point(t, 0.5, amplitude) for t in sections]
        underside = [self._surface_point(t, 0.5, amplitude, depth=0.085) for t in sections]
        top_path = _path(back + list(reversed(front)), closed=True)

        # A barely-there cast shadow gives the section width a readable depth.
        painter.save()
        painter.translate(0.0, 9.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((16.0, 0.012), (8.0, 0.020)):
            pen = QPen(self._color("beam", alpha), width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(top_path)
        painter.restore()

        side_gradient = QLinearGradient(80.0, 320.0, 650.0, 170.0)
        side_gradient.setColorAt(0.0, self._color("beam", 0.82))
        side_gradient.setColorAt(0.52, self._color("node", 0.90))
        side_gradient.setColorAt(1.0, self._color("text_secondary", 0.95))
        painter.setBrush(side_gradient)
        painter.setPen(QPen(self._color("beam", 0.65), 0.75))
        painter.drawPath(_path(front + list(reversed(underside)), closed=True))

        top_gradient = QLinearGradient(170.0, 120.0, 440.0, 340.0)
        top_gradient.setColorAt(0.0, self._color("surface"))
        top_gradient.setColorAt(0.46, self._color("beam_fill"))
        top_gradient.setColorAt(1.0, self._color("border"))
        painter.setBrush(top_gradient)
        painter.setPen(QPen(self._color("beam", 0.75), 1.0))
        painter.drawPath(top_path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._color("beam", 0.38), 0.8))
        for across in (-0.25, 0.0, 0.25):
            painter.drawPath(_path([self._surface_point(t, across, amplitude) for t in sections]))
        for index in range(1, 25):
            t = index / 25.0
            painter.drawLine(self._surface_point(t, -0.5, amplitude),
                             self._surface_point(t, 0.5, amplitude))
            painter.setPen(QPen(self._color("beam", 0.38), 0.7))
            painter.drawLine(self._surface_point(t, 0.5, amplitude),
                             self._surface_point(t, 0.5, amplitude, depth=0.085))
            painter.setPen(QPen(self._color("beam", 0.38), 0.8))

        # Exposed section end: a small actual polygon, not a thick painted line.
        end = [self._surface_point(1.0, across, amplitude, depth=depth)
               for across, depth in ((-0.5, 0.0), (0.5, 0.0), (0.5, 0.085), (-0.5, 0.085))]
        painter.setPen(QPen(self._color("beam", 0.7), 0.7))
        painter.setBrush(self._color("beam", 0.8))
        painter.drawPath(_path(end, closed=True))

        # A restrained traveling highlight represents observation, not progress.
        if 0.025 < self._phase < 0.20:
            t = (self._phase - 0.025) / 0.175
            painter.setPen(QPen(self._color("sensor", 0.32), 2.1))
            painter.drawLine(self._surface_point(t, -0.50, amplitude),
                             self._surface_point(t, 0.50, amplitude))

    def _draw_sensors(self, painter, amplitude):
        for index, t in enumerate(self.SENSOR_POSITIONS):
            opacity = _smooth((self._phase - index * 0.022) / 0.05)
            opacity *= 1.0 - _smooth((self._phase - 0.95) / 0.05)
            if opacity <= 0.001:
                continue
            corners = [self._surface_point(s, across, amplitude)
                       for s, across in ((t - 0.012, -0.24), (t + 0.012, -0.24),
                                         (t + 0.012, 0.24), (t - 0.012, 0.24))]
            painter.setPen(QPen(self._color("sensor_dark", opacity * 0.75), 0.65))
            painter.setBrush(self._color("sensor", opacity))
            painter.drawPath(_path(corners, closed=True))
            painter.setPen(QPen(self._color("surface", opacity * 0.7), 0.7))
            for shift in (-0.004, 0.004):
                painter.drawLine(self._surface_point(t + shift, -0.16, amplitude),
                                 self._surface_point(t + shift, 0.16, amplitude))


__all__ = ["BeamReconstructionAnimation"]
