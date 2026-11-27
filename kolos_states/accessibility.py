"""Read-only Windows UI Automation supplementation of Glaz vision.

Never extracts an amount from a command. Reads the actual focused ValuePattern /
TextPattern only. Password fields and ambiguous selections are not accepted.
"""
from __future__ import annotations
import hashlib
import os
import sys
from typing import Any
from .protocol import compact


def _bounds(rect):
    return [int(rect.left),int(rect.top),int(rect.right),int(rect.bottom)]


def _identity(control, top):
    values=[]
    c=control
    for _ in range(8):
        if c is None:break
        values.append([c.ControlTypeName,c.AutomationId,c.ClassName])
        if c.NativeWindowHandle and c.NativeWindowHandle==top.NativeWindowHandle:break
        c=c.GetParentControl()
    return 'uia:'+hashlib.sha256(compact(values).encode()).hexdigest()[:24]


class Accessibility:
    def __init__(self, own_pid=0):
        self.own_pid=own_pid
        self._auto=None

    def ensure_available(self) -> None:
        """Load the declared dependency before arming desktop recording or input."""
        if sys.platform!='win32':raise RuntimeError('UI Automation доступна только в Windows')
        if self._auto is not None:return
        try:
            import uiautomation as auto
        except ModuleNotFoundError as exc:
            raise RuntimeError('Не установлена зависимость UI Automation ('+str(exc.name)+'). '
                               'Запустите install_states.bat и перезапустите Glaz.') from exc
        auto.SetGlobalSearchTimeout(1)
        self._auto=auto

    def read(self) -> dict:
        empty=dict(focus='',output='',readable=False,selected_bbox=None,field_bbox=None,window='',own=False,
                   context_valid=False,reason='UI Automation недоступна')
        if sys.platform!='win32':return empty
        try:
            self.ensure_available()
            auto=self._auto
            with auto.UIAutomationInitializerInThread():
                top=auto.GetForegroundControl();c=auto.GetFocusedControl()
                if top is None or c is None:
                    empty['reason']='UI Automation не обнаружила активное окно или элемент ввода';return empty
                empty['own']=top.ProcessId in (self.own_pid,os.getpid())
                empty['foreground']=top.NativeWindowHandle
                from .window_context import window_context
                empty['window_context']=window_context(top.NativeWindowHandle)
                empty['context_valid']=bool(top.NativeWindowHandle)
                if empty['own']:empty['reason']='Фокус находится в Glaz/терминале';return empty
                empty['window']='window:'+top.ClassName+'|'+top.AutomationId
                if c.IsPassword:empty['reason']='Защищённое поле не считывается';return empty
                return self._read_control(c,top,empty)
        except Exception as exc:
            empty['reason']='UI Automation: '+str(exc)[:160];return empty

    def _read_control(self, control: Any, top: Any, result: dict) -> dict:
        """Read selection and text from the actual focused control only."""
        try:
            pattern=control.GetSelectionItemPattern()
            if pattern and pattern.IsSelected:result['selected_bbox']=_bounds(control.BoundingRectangle)
        except Exception:pass
        # Standard buttons can hold keyboard focus (e.g. the native test pad).
        if result['selected_bbox'] is None and control.ControlTypeName in ('ButtonControl','ListItemControl'):
            result['selected_bbox']=_bounds(control.BoundingRectangle)
        value=self._focused_value(control)
        if isinstance(value,str) and len(value)<=20000:
            # No strip(): spaces/newlines must remain actual field contents.
            result.update(focus=_identity(control,top),output=value,readable=True,
                          field_bbox=_bounds(control.BoundingRectangle),reason='')
        else:result['reason']='В фокусе нет доступного текстового поля'
        return result

    @staticmethod
    def _focused_value(control: Any) -> str | None:
        """Preserve field text exactly; never treat a button label as input."""
        try:
            pattern=control.GetValuePattern()
            if pattern and not pattern.IsReadOnly:return pattern.Value
        except Exception:pass
        if control.ControlTypeName in ('EditControl','DocumentControl'):
            try:
                pattern=control.GetTextPattern()
                if pattern:return pattern.DocumentRange.GetText(20001)
            except Exception:pass
        return None
