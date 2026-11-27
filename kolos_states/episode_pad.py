"""Disposable real Win32 multi-field form for E13, with no engine imports.

The form exposes standard EDIT/BUTTON controls. Save copies the target fields
into read-only saved fields. The agent observes these through UI Automation;
no internal state, expected route or success flag is passed to the agent.
"""
import argparse
import sys


def main():
    if sys.platform != 'win32':
        raise SystemExit('The native episode pad needs Windows')
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='Sample 1700')
    parser.add_argument('--source2')
    parser.add_argument('--layout', type=int, default=0)
    parser.add_argument('--title', default='Kolos working episode')
    parser.add_argument('--fail-save', action='store_true')
    args = parser.parse_args()
    import ctypes as c
    from ctypes import wintypes as w
    user = c.WinDLL('user32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    WNDPROC = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

    class WNDCLASS(c.Structure):
        _fields_ = [('style', w.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', c.c_int),
                    ('cbWndExtra', c.c_int), ('hInstance', w.HINSTANCE), ('hIcon', w.HICON),
                    ('hCursor', w.HANDLE), ('hbrBackground', w.HBRUSH),
                    ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR)]

    user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DefWindowProcW.restype = c.c_ssize_t
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int,
                                    c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
    user.CreateWindowExW.restype = w.HWND
    kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
    kernel.GetModuleHandleW.restype = w.HINSTANCE
    user.RegisterClassW.argtypes = [c.POINTER(WNDCLASS)]
    user.RegisterClassW.restype = w.ATOM
    user.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
    user.GetWindowTextLengthW.argtypes = [w.HWND]
    user.DestroyWindow.argtypes = [w.HWND]
    user.GetMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    user.GetMessageW.restype = w.BOOL
    user.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    user.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
    user.DispatchMessageW.restype = c.c_ssize_t
    controls = {}
    count = 2 if args.source2 is not None else 1

    def text(hwnd):
        buf = c.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
        user.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value

    @WNDPROC
    def proc(hwnd, msg, wp, lp):
        if msg == 0x0111 and wp & 65535 == 900 and wp >> 16 == 0:
            if not args.fail_save:
                for i in range(count):
                    user.SetWindowTextW(controls[102 + i * 10], text(controls[101 + i * 10]))
            return 0
        if msg == 0x0010:
            user.DestroyWindow(hwnd)
            return 0
        if msg == 0x0002:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(hwnd, msg, wp, lp)

    instance = kernel.GetModuleHandleW(None)
    wc = WNDCLASS(0, proc, 0, 0, instance, None, None, 6, None, 'KolosWorkingEpisodePad')
    if not user.RegisterClassW(c.byref(wc)):
        raise c.WinError(c.get_last_error())
    parent = user.CreateWindowExW(0, wc.lpszClassName, args.title, 0x00CF0000 | 0x10000000,
                                  100 + args.layout * 80, 100, 720, 560, None, None, instance, None)
    rows = []
    for i in range(count):
        for j, (name, val) in enumerate([(f'Source {i+1}', args.source if i == 0 else args.source2),
                                        (f'Target {i+1}', '<old>'), (f'Saved {i+1}', '<not saved>')]):
            rows.append((100 + i * 10 + j, name, val, j == 2))
    rows.append((800, 'Unrelated', 'do not touch', False))
    if args.layout % 2:
        rows.reverse()
    for row, (oid, label, value, readonly) in enumerate(rows):
        y = 28 + row * 52
        user.CreateWindowExW(0, 'STATIC', label, 0x50000000, 22, y + 7, 150, 30,
                             parent, oid + 1000, instance, None)
        controls[oid] = user.CreateWindowExW(0x200, 'EDIT', value,
                            0x50010080 | (0x800 if readonly else 0),
                            178, y, 490, 38, parent, oid, instance, None)
    user.CreateWindowExW(0, 'BUTTON', 'Save', 0x50010000, 510, 430, 160, 45,
                         parent, 900, instance, None)
    print(parent, flush=True)
    msg = w.MSG()
    while user.GetMessageW(c.byref(msg), None, 0, 0) > 0:
        user.TranslateMessage(c.byref(msg))
        user.DispatchMessageW(c.byref(msg))


if __name__ == '__main__':
    main()
