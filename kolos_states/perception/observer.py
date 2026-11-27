"""Thin bridge between fresh visual evidence and the pure neural recognizer."""
from __future__ import annotations

import os
import sys
from .matching import binding
from .types import views
from .dynamics import apply_binding
from ..window_context import window_context


class VisualAccessibility:
    """Own-window input guard only; never reads UIA, labels or control identities."""

    def __init__(self, own_pid: int):
        self.own_pid = own_pid

    def ensure_available(self) -> None:
        """This observation mode has no accessibility dependency."""

    def read(self) -> dict:
        """OS foreground PID protects the teacher window, without identifying targets."""
        own = False; foreground = None
        if sys.platform == 'win32':
            import ctypes
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            pid = ctypes.c_ulong()
            foreground = user32.GetForegroundWindow()
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
            own = pid.value in (self.own_pid, os.getpid())
        return dict(focus='', output='', readable=False, selected_bbox=None, field_bbox=None,
                    window='', own=own, foreground=foreground,
                    window_context=window_context(foreground),
                    context_valid=bool(foreground) if sys.platform=='win32' else True,
                    reason='Зрительный режим: содержимое полей не считывается')


def requests(model: dict, action: dict | None = None) -> list[dict]:
    """Motor verification always re-observes every learned fine variant."""
    if action and action.get('visual'):
        return views(model['memory'], action['visual'], fine_only=True)
    return (model.get('perception') or {}).get('requests', [])


def verify(model: dict, observed: dict, action: dict) -> dict:
    """Recompute current sensory proof, without altering weights or the pending action."""
    proof = binding(model['memory'], action['visual'], observed, model['config'])
    observed['visual_bindings'] = {}
    return apply_binding(observed, action, proof) if proof else observed
