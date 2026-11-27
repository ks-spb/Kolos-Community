"""Explicitly scoped UI Automation adapter for working episodes.

The observer reads accessible values from one user-selected native window.
The motor uses ValuePattern/InvokePattern, not clipboard or hardcoded coordinates.
No elevated privileges, arbitrary script execution, background retry or OCR.
"""
from __future__ import annotations
import os
import sys
import threading
import time
import uuid
from typing import Any
from .protocol import clone, require
from .episodes import (SCHEMA, observe, bind, values, fresh, verify_effect,
                       object_by_id, _changed)
from .desktop import Indeterminate


def control_runtime_id(control: Any) -> str:
    """Identify a UIA element, never collapse sibling elements to a shared HWND."""
    runtime = control.GetRuntimeId()
    if runtime:
        require(all(type(part) is int for part in runtime), 'Invalid UIA runtime ID')
        result = 'uia:runtime:' + '.'.join(map(str, runtime))
    else:
        native = control.NativeWindowHandle
        require(type(native) is int and native > 0, 'Native control has no usable identity')
        result = 'uia:hwnd:' + str(native)
    require(len(result) <= 512, 'UIA runtime ID is too large')
    return result


class UIAObserver:
    def __init__(self, hwnd, *, own_pid=0):
        require(type(hwnd) is int and hwnd > 0, 'Select a native window first')
        self.hwnd = hwnd
        self.own_pid = own_pid
        self.session = uuid.uuid4().hex
        self.version = 0
        self.controls = {}
        self.auto = None
        self.pid = None

    def observe(self):
        require(sys.platform == 'win32', 'UI Automation needs Windows')
        if self.auto is None:
            import uiautomation as auto
            auto.SetGlobalSearchTimeout(1)
            self.auto = auto
        auto = self.auto
        with auto.UIAutomationInitializerInThread():
            top = auto.ControlFromHandle(self.hwnd)
            require(top and top.Exists(0, 0), 'Selected window is no longer available')
            require(top.ProcessId not in (self.own_pid, os.getpid()), 'Do not target Glaz or the controller itself')
            if self.pid is None:
                self.pid = top.ProcessId
            require(top.ProcessId == self.pid, 'The selected window handle was reused')
            scope = top.ClassName + '|' + top.AutomationId + '|' + top.Name
            queue = [(top, 0)]
            objects, controls = [], {}
            visited = 0
            while queue:
                c, depth = queue.pop(0)
                visited += 1
                require(visited <= 1500, 'Window is too large for a bounded safe observation')
                if depth < 6:
                    queue.extend((child, depth + 1) for child in c.GetChildren())
                kind = c.ControlTypeName
                if kind not in ('EditControl', 'DocumentControl', 'ButtonControl') or c.IsOffscreen:
                    continue
                password = bool(c.IsPassword)
                button = kind == 'ButtonControl'
                pattern = None
                value, writable = None, False
                if not button and not password:
                    try:
                        pattern = c.GetValuePattern()
                        if pattern:
                            value, writable = pattern.Value, not pattern.IsReadOnly
                    except Exception:
                        pass
                    if value is None:
                        try:
                            text = c.GetTextPattern()
                            if text:
                                value = text.DocumentRange.GetText(20001)
                        except Exception:
                            pass
                readable = isinstance(value, str) and len(value) <= 20000
                if not readable:
                    value = None
                oid = control_runtime_id(c)
                rect = c.BoundingRectangle
                obj = dict(id=oid, descriptor=dict(kind='button' if button else 'field',
                           name=c.Name or '', scope=scope, automation_id=c.AutomationId or ''),
                           readable=readable, writable=bool(writable), enabled=bool(c.IsEnabled),
                           protected=password, value=value,
                           bbox=[int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)])
                # Unlabelled controls cannot silently become position-based roles.
                if not obj['descriptor']['name'] and not obj['descriptor']['automation_id']:
                    continue
                require(oid not in controls, 'Ambiguous native control ID')
                objects.append(obj)
                controls[oid] = c
            self.version += 1
            result = observe(dict(schema=SCHEMA, session=self.session, version=self.version,
                                  captured_at=time.time(), objects=objects))
            self.controls = controls
            self.latest = clone(result)
            return result

    def send(self, action):
        # Called immediately after a fresh observation and guard checks.
        with self.auto.UIAutomationInitializerInThread():
            c = self.controls.get(action['object'])
            require(c and c.Exists(0, 0) and c.IsEnabled and not c.IsPassword,
                    'Native target disappeared, was disabled or became protected')
            if action['kind'] == 'read':
                return
            if action['kind'] == 'write':
                p = c.GetValuePattern()
                require(p and not p.IsReadOnly, 'No writable ValuePattern')
                p.SetValue(action['value'])
            elif action['kind'] == 'activate':
                p = c.GetInvokePattern()
                require(p, 'No supported InvokePattern')
                p.Invoke()
            else:
                raise ValueError('Unsupported native episode primitive')


class EpisodeAdapter:
    def __init__(self, observer, *, allow=None, stop=None, paused=None, timeout=5.0):
        self.observer = observer
        self.allow = allow or (lambda: False)
        self.stop = stop or threading.Event()
        self.paused = paused or (lambda: False)
        self.timeout = timeout
        self.sent, self.receipts = {}, {}

    def safe(self):
        if self.stop.is_set():
            raise InterruptedError('Emergency stop')
        if not self.allow():
            raise PermissionError('Live control is not permitted')
        if self.paused():
            raise InterruptedError('Paused before another action')

    def execute(self, request, *, teaching=False):
        rid, a = request['id'], request['action']
        if rid in self.receipts:
            require(self.sent[rid] == a, 'Request ID was reused for another action')
            return clone(self.receipts[rid])
        if rid in self.sent:
            raise Indeterminate('This request was already sent; automatic replay is forbidden')
        self.safe()
        before = self.observer.observe()
        baseline = observe(request['before'])
        require(before['session'] == baseline['session'] and before['version'] >= baseline['version'] and
                before['captured_at'] >= baseline['captured_at'] and values(before) == values(baseline),
                'Environment changed after action selection')
        target = bind(before, a['descriptor'])
        require(target['id'] == a['object'], 'Runtime target changed before dispatch')
        if a['kind'] in ('read', 'write'):
            require(target['readable'], 'Field is not readable')
        if a['kind'] == 'write':
            require(target['writable'] and isinstance(a.get('value'), str) and len(a['value']) <= 20000,
                    'Field is not writable or value is invalid')
        if a['kind'] == 'activate':
            require(target['descriptor']['kind'] == 'button', 'Target is not a button')
        for item in request.get('protected', []):
            require(bind(before, item['descriptor'])['value'] == item['value'], 'Protected source changed')
        self.safe()
        self.sent[rid] = clone(a)  # Set BEFORE the side effect, even if the provider raises.
        self.observer.send(a)
        deadline, previous, stable = time.monotonic() + self.timeout, None, 0
        while time.monotonic() < deadline:
            self.safe()
            after = self.observer.observe()
            try:
                fresh(before, after)
                if teaching and a['kind'] == 'activate':
                    changed = _changed(before, after)
                    require(changed and values(before, [o['descriptor'] for o in changed]) ==
                            values(after, [o['descriptor'] for o in changed]), 'No observable activation result')
                else:
                    verify_effect(a, before, after)
                for item in request.get('protected', []):
                    require(bind(after, item['descriptor'])['value'] == item['value'], 'Protected source changed')
                fingerprint = values(after)
                stable = stable + 1 if fingerprint == previous else 1
                previous = fingerprint
                if stable >= 2:
                    result = dict(id=rid, action=clone(a), ok=True, before=before, after=after,
                                  verified_by='two-fresh-uia-observations')
                    self.receipts[rid] = result
                    return clone(result)
            except ValueError:
                stable, previous = 0, None
            time.sleep(.03)
        raise Indeterminate('The native effect was not confirmed. Inspect the window; do not resend.')


class EpisodeRecorder:
    """Explicit slow demonstration of generic primitives; no inferred task route."""
    def __init__(self, adapter, query):
        require(isinstance(query, str) and 0 < len(query) <= 160, 'Enter a demonstration query')
        self.adapter, self.query = adapter, query
        self.receipts, self.slots = [], {}
        self.session = uuid.uuid4().hex
        self.invalid = None

    def capture(self, kind, oid, source=None):
        require(self.invalid is None, 'Discard the failed demonstration before continuing')
        before = self.adapter.observer.observe()
        target = object_by_id(before, oid)
        a = dict(kind=kind, object=oid, descriptor=clone(target['descriptor']), effects=[])
        if kind == 'read':
            a['slot'] = 'v' + str(len(self.slots))
        elif kind == 'write':
            require(source in self.slots, 'Select an already observed value')
            a.update(source=source, value=self.slots[source])
        elif kind != 'activate':
            raise ValueError('Unknown demonstration primitive')
        request = dict(id='teach:' + self.session + ':' + str(len(self.receipts)), action=a, before=before)
        try:
            receipt = self.adapter.execute(request, teaching=True)
        except Exception as exc:
            self.invalid = str(exc)
            raise
        self.receipts.append(receipt)
        if kind == 'read':
            self.slots[a['slot']] = bind(receipt['after'], a['descriptor'])['value']
        return clone(receipt)

    def finish(self):
        require(self.invalid is None and self.receipts, 'No complete valid demonstration')
        return dict(schema=SCHEMA, query=self.query, receipts=clone(self.receipts))
