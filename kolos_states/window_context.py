"""Read-only window context for scoped learning; handles never enter long-term memory."""
from __future__ import annotations
import hashlib
import json
import sys


def window_context(hwnd: int | None) -> str:
    if sys.platform != 'win32' or not hwnd:
        return ''
    try:
        import ctypes
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        klass = ctypes.create_unicode_buffer(512); title = ctypes.create_unicode_buffer(2048)
        if not user.GetClassNameW(hwnd, klass, len(klass)):
            return ''
        user.GetWindowTextW(hwnd, title, len(title))
        pid = w.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return ''
        try:
            path = ctypes.create_unicode_buffer(32768); length = w.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                return ''
        finally:
            kernel.CloseHandle(process)
        descriptor = [path.value.casefold(), klass.value, title.value]
        return hashlib.sha256(json.dumps(descriptor, ensure_ascii=False).encode('utf-8')).hexdigest()
    except (OSError, ValueError, AttributeError):
        return ''


def in_foreground(icon: dict, foreground: int | None) -> bool:
    """Read-only hit-test: a concept cannot borrow a glyph from another window."""
    if sys.platform != 'win32' or not foreground:
        return False
    try:
        import ctypes
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.WindowFromPoint.argtypes = [w.POINT]
        user.WindowFromPoint.restype = w.HWND
        user.GetAncestor.argtypes = [w.HWND, w.UINT]
        user.GetAncestor.restype = w.HWND
        user.GetForegroundWindow.restype = w.HWND
        if user.GetForegroundWindow() != foreground:
            return False
        window = user.WindowFromPoint(w.POINT(round(icon['x']), round(icon['y'])))
        return bool(window and user.GetAncestor(window, 2) == foreground)
    except (OSError, TypeError, ValueError, KeyError):
        return False
