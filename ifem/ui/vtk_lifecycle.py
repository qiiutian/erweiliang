"""Shared lifecycle helpers for embedded PyVistaQt interactors."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QCoreApplication, QEvent, QObject


def interactor_is_active(plotter) -> bool:
    return plotter is not None and not getattr(plotter, "_closed", True)


def render_interactor_now(plotter) -> bool:
    """Render synchronously on Qt's thread instead of queuing a macOS worker."""
    if not interactor_is_active(plotter):
        return False
    render_now = getattr(plotter, "_render", None)
    try:
        if callable(render_now):
            render_now()
        else:
            plotter.render()
    except RuntimeError:
        return False
    return True


def shutdown_interactor(plotter) -> None:
    """Stop timers and queued renders before Qt destroys the native window."""
    if plotter is None:
        return

    for timer_name in ("render_timer", "_Timer"):
        timer = getattr(plotter, timer_name, None)
        if timer is not None:
            with suppress(RuntimeError):
                timer.stop()

    render_signal = getattr(plotter, "render_signal", None)
    if render_signal is not None:
        with suppress(RuntimeError, TypeError):
            render_signal.disconnect()

    vtk_interactor = getattr(getattr(plotter, "iren", None), "interactor", None)
    if vtk_interactor is not None:
        with suppress(AttributeError, RuntimeError):
            vtk_interactor.Disable()

    if isinstance(plotter, QObject):
        with suppress(AttributeError, RuntimeError):
            plotter.setUpdatesEnabled(False)
        QCoreApplication.removePostedEvents(plotter, QEvent.Type.MetaCall)
        QCoreApplication.removePostedEvents(plotter, QEvent.Type.UpdateRequest)

    if not getattr(plotter, "_closed", True):
        with suppress(AttributeError, RuntimeError, TypeError):
            plotter.close()


__all__ = [
    "interactor_is_active",
    "render_interactor_now",
    "shutdown_interactor",
]
