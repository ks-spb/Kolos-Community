"""Explicit read-only UIA selections and an isolated writable report window.

A teacher supplies paths to observed elements and semantic context anchors.
There is no click, keyboard, navigation, OCR, expected amount, or source write.
Paths are runtime bindings to one open view, not a universal website skill.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from .episode_desktop import UIAObserver, control_runtime_id
from .episodes import SCHEMA, observe
from .protocol import clone, require


def resolve_path(root: Any, path: list[str], cache: dict | None = None) -> Any:
    """Follow exact runtime IDs; changed or ambiguous paths require a new selection."""
    require(isinstance(path, list) and 0 < len(path) <= 32 and
            all(isinstance(item, str) and item for item in path), 'Invalid selected UIA path')
    require(control_runtime_id(root) == path[0], 'Selected window identity changed')
    cache = {} if cache is None else cache
    current = root
    for depth, identity in enumerate(path[1:], 2):
        prefix = tuple(path[:depth])
        if prefix not in cache:
            children = current.GetChildren()
            require(len(children) <= 1000, 'Selected UIA level is too large')
            matches = [child for child in children if control_runtime_id(child) == identity]
            require(len(matches) == 1, 'Selected UIA path is missing or ambiguous')
            cache[prefix] = matches[0]
        current = cache[prefix]
    require(not current.IsOffscreen and not current.IsPassword and current.IsEnabled,
            'Selected source is hidden, protected or disabled')
    return current


def selected_text(root: Any, selection: dict, cache: dict | None = None) -> tuple[Any, str]:
    """Read the UIA Name chosen by the teacher, including visible button captions."""
    control = resolve_path(root, selection['path'], cache)
    value = control.Name
    require(isinstance(value, str) and len(value) <= 20000, 'Selected text is unavailable')
    return control, value


class ReadOnlySelectionObserver:
    """Expose named read-only sources from one explicitly bound native window."""

    def __init__(self, selection: dict) -> None:
        self.selection = clone(selection)
        require(type(selection.get('hwnd')) is int and selection['hwnd'] > 0, 'Select a window')
        require(isinstance(selection.get('title'), str) and selection['title'], 'Select window context')
        require(isinstance(selection.get('scope'), str) and selection['scope'], 'Select source scope')
        require(0 < len(selection.get('fields', [])) <= 10 and
                0 < len(selection.get('anchors', [])) <= 10, 'Select fields and context anchors')
        self.session, self.version = uuid.uuid4().hex, 0
        self.pid = None
        self.latest: dict = {}
        self.auto = None

    def _root(self) -> Any:
        """Recheck the exact window and its process before every observation."""
        root = self.auto.ControlFromHandle(self.selection['hwnd'])
        require(root and root.Exists(0, 0) and root.Name == self.selection['title'],
                'Selected page/window context changed')
        if self.pid is None:
            self.pid = root.ProcessId
        require(root.ProcessId == self.pid, 'Selected window handle was reused')
        return root

    def _anchors(self, root: Any, cache: dict) -> None:
        """Confirm the taught SKU, identity and column context without guessing."""
        for anchor in self.selection['anchors']:
            _, text = selected_text(root, anchor, cache)
            expected = anchor['text']
            require(isinstance(expected, str) and expected, 'Empty source context anchor')
            mode = anchor.get('match', 'exact')
            require(mode in ('exact', 'contains'), 'Unknown source anchor match')
            require(text == expected if mode == 'exact' else expected in text,
                    'Selected source context anchor changed')

    def _field(self, root: Any, field: dict, cache: dict) -> dict:
        """Keep the taught role name separate from the freshly read value."""
        control, text = selected_text(root, field, cache)
        require(isinstance(field.get('name'), str) and field['name'], 'Name the selected role')
        rect = control.BoundingRectangle
        return dict(id=control_runtime_id(control),
                    descriptor=dict(kind='field', name=field['name'],
                                    scope=self.selection['scope'], automation_id=''),
                    readable=True, writable=False, enabled=True, protected=False, value=text,
                    bbox=[int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)])

    def observe(self) -> dict:
        """Produce fresh evidence from exact selected elements; never send input."""
        if self.auto is None:
            import uiautomation as auto
            self.auto = auto
        with self.auto.UIAutomationInitializerInThread():
            root = self._root()
            # Reuse shared ancestors only within this fresh observation.
            cache: dict = {}
            self._anchors(root, cache)
            objects = [self._field(root, field, cache) for field in self.selection['fields']]
            self.version += 1
            self.latest = observe(dict(schema=SCHEMA, session=self.session, version=self.version,
                                       captured_at=time.time(), objects=objects))
            return clone(self.latest)

    def send(self, action: dict) -> None:
        """A source read has no side effect; every other operation is forbidden."""
        require(action['kind'] == 'read', 'Read-only source forbids all input')
        require(any(item['id'] == action['object'] for item in self.latest.get('objects', [])),
                'Read target is outside the selected source')


class SourceReportObserver:
    """Join a protected source with only Target fields/Save of a disposable pad."""

    def __init__(self, source: ReadOnlySelectionObserver, report: UIAObserver) -> None:
        require(source.selection['hwnd'] != report.hwnd, 'Source and report must be separate windows')
        self.source, self.report = source, report
        self.session, self.version = uuid.uuid4().hex, 0
        self.source_ids: set[str] = set()
        self.report_objects: dict[str, dict] = {}

    def observe(self) -> dict:
        """Read both windows while preserving their distinct role scopes."""
        source, report = self.source.observe(), self.report.observe()
        require(all(item['descriptor']['scope'].startswith('KolosWorkingEpisodePad|')
                    for item in report['objects']), 'Report is not the disposable Kolos pad')
        self.source_ids = {item['id'] for item in source['objects']}
        self.report_objects = {item['id']: item for item in report['objects']}
        require(not self.source_ids.intersection(self.report_objects), 'Source/report identity collision')
        self.version += 1
        return observe(dict(schema=SCHEMA, session=self.session, version=self.version,
                            captured_at=time.time(), objects=source['objects'] + report['objects']))

    def send(self, action: dict) -> None:
        """Enforce the source write ban at dispatch, independently of learned roles."""
        if action['object'] in self.source_ids:
            return self.source.send(action)
        target = self.report_objects.get(action['object'])
        require(target is not None, 'Action target is outside the report')
        name = target['descriptor']['name']
        allowed = ((action['kind'] == 'write' and name in ('Target 1', 'Target 2')) or
                   (action['kind'] == 'activate' and name == 'Save'))
        require(allowed, 'Only local report fields and Save may be changed')
        self.report.send(action)
