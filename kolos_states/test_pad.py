"""Disposable native Windows test window, not a source of engine observations.

Standard Win32 controls expose readable values to UI Automation. The inference
engine has no reference to this module. No files, payments or external apps.
"""
import sys

def main():
    if sys.platform!='win32':raise SystemExit('Тестовое окно доступно только в Windows')
    import ctypes as c
    from ctypes import wintypes as w
    user=c.WinDLL('user32',use_last_error=True);kernel=c.WinDLL('kernel32',use_last_error=True)
    WNDPROC=c.WINFUNCTYPE(c.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
    class WNDCLASS(c.Structure):
        _fields_=[('style',w.UINT),('lpfnWndProc',WNDPROC),('cbClsExtra',c.c_int),('cbWndExtra',c.c_int),('hInstance',w.HINSTANCE),('hIcon',w.HICON),('hCursor',w.HANDLE),('hbrBackground',w.HBRUSH),('lpszMenuName',w.LPCWSTR),('lpszClassName',w.LPCWSTR)]
    user.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];user.DefWindowProcW.restype=c.c_ssize_t
    user.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p];user.CreateWindowExW.restype=w.HWND
    kernel.GetModuleHandleW.argtypes=[w.LPCWSTR];kernel.GetModuleHandleW.restype=w.HINSTANCE
    user.ShowWindow.argtypes=[w.HWND,c.c_int];user.SetFocus.argtypes=[w.HWND];user.SetFocus.restype=w.HWND
    user.SetWindowTextW.argtypes=[w.HWND,w.LPCWSTR]
    user.RegisterClassW.argtypes=[c.POINTER(WNDCLASS)];user.RegisterClassW.restype=w.ATOM
    user.DestroyWindow.argtypes=[w.HWND];user.DestroyWindow.restype=w.BOOL
    user.GetMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT];user.GetMessageW.restype=w.BOOL
    user.TranslateMessage.argtypes=[c.POINTER(w.MSG)];user.TranslateMessage.restype=w.BOOL
    user.DispatchMessageW.argtypes=[c.POINTER(w.MSG)];user.DispatchMessageW.restype=c.c_ssize_t
    controls={};current='desk';selected='';parent=None
    def show(mode):
        nonlocal current,selected
        current=mode;selected=''
        for id,handle in controls.items():user.ShowWindow(handle,5 if (mode=='desk' and id in (101,102,103) or mode=='window' and id in (104,105,106) or mode=='calc' and id in (104,107)) else 0)
        if mode=='calc':user.SetWindowTextW(controls[107],'');user.SetFocus(controls[107])
    @WNDPROC
    def proc(hwnd,msg,wp,lp):
        nonlocal selected
        if msg==0x0111 and wp>>16==0:
            id=wp&65535
            if id==101:selected='A'
            elif id==103:show('calc')
            elif id==104:show('desk')
            return 0
        if msg==0x0010:user.DestroyWindow(hwnd);return 0
        if msg==0x0002:user.PostQuitMessage(0);return 0
        return user.DefWindowProcW(hwnd,msg,wp,lp)
    instance=kernel.GetModuleHandleW(None);wc=WNDCLASS(0,proc,0,0,instance,None,None,6,None,'KolosStatesNativeTestPad')
    if not user.RegisterClassW(c.byref(wc)):raise c.WinError(c.get_last_error())
    parent=user.CreateWindowExW(0,wc.lpszClassName,'Kolos — тестовая среда Windows',0x00CF0000|0x10000000,100,100,700,440,None,None,instance,None)
    for id,label,x,y in [(101,'A',60,85),(102,'B',285,85),(103,'CALC',510,85),(104,'X',605,20),(105,'D',140,185),(106,'E',370,185)]:
        controls[id]=user.CreateWindowExW(0,'BUTTON',label,0x50010000,x,y,80,55,parent,id,instance,None)
    controls[107]=user.CreateWindowExW(0x200,'EDIT','',0x50010080,65,210,490,40,parent,107,instance,None)
    show('desk');msg=w.MSG()
    while user.GetMessageW(c.byref(msg),None,0,0)>0:
        if msg.message==0x0100 and msg.wParam==13 and current=='desk' and selected=='A':show('window');continue
        user.TranslateMessage(c.byref(msg));user.DispatchMessageW(c.byref(msg))
if __name__=='__main__':main()
