"""Tool-hosted browser evidence for existing working episodes, without a browser motor.

The browser host supplies fresh DOM readings. This module only learns/dispatches
generic read/write operations in the existing StateEngine. Real browser input
remains with the supported browser tool and its permission checks.
"""
from __future__ import annotations

from typing import Any

from .core import StateEngine
from .episodes import SCHEMA, bind, fresh, observe, values, verify_effect, _changed
from .protocol import clone, require


class BrowserEpisodeBridge:
    """Record verified demonstrations and expose one kernel-selected action at a time."""

    def __init__(self, state: dict | None = None) -> None:
        self.engine = StateEngine()
        self.record: dict | None = None
        self.pending: dict | None = None
        self.slots: dict = {}
        self.serial = 0
        if state is not None:
            self.engine.model = clone(state['model'])
            self.record, self.pending = clone(state['record']), clone(state['pending'])
            self.slots, self.serial = clone(state['slots']), state['serial']

    def dump(self) -> dict:
        """Persist only this isolated experiment's engine and pending receipt."""
        return dict(model=clone(self.engine.model), record=clone(self.record),
                    pending=clone(self.pending), slots=clone(self.slots), serial=self.serial)

    def begin_teaching(self, query: str) -> None:
        """Start an explicit demonstration, never infer its route from the task text."""
        require(self.pending is None, 'An unconfirmed action must not be replayed')
        self.engine.reset()
        self.record = dict(schema=SCHEMA, query=query, receipts=[])
        self.slots = {}

    def prepare(self, raw: dict, kind: str, role: str, source: str | None = None) -> dict:
        """Teacher selects one observed role; dispatch does not count as success."""
        require(self.record is not None and self.pending is None, 'Start teaching and confirm the previous action')
        before = observe(raw)
        matches = [obj for obj in before['objects'] if obj['descriptor']['name'] == role]
        require(len(matches) == 1, 'Teacher role is missing or ambiguous')
        obj = matches[0]
        require(obj['enabled'] and not obj['protected'], 'Role is disabled or protected')
        require(kind == 'activate' or obj['readable'], 'Role cannot be read')
        action = dict(kind=kind, object=obj['id'], descriptor=clone(obj['descriptor']), effects=[])
        if kind == 'read':
            action['slot'] = 'v' + str(len(self.slots))
        elif kind == 'write':
            require(obj['writable'] and source in self.slots, 'Write requires a demonstrated source')
            action.update(source=source, value=self.slots[source])
        elif kind == 'activate':
            require(obj['descriptor']['kind'] == 'button', 'Activation requires an observed button')
        else:
            raise ValueError('Unsupported episode primitive')
        self.serial += 1
        self.pending = dict(id=f'tool-teach:{self.serial}', action=action, before=before)
        return clone(self.pending)

    def _verify(self, request: dict, after: dict) -> None:
        """Teaching may discover an activation effect; replay must verify the learned effect."""
        if self.record is not None and request['action']['kind'] == 'activate':
            fresh(request['before'], after)
            changed = _changed(request['before'], after)
            require(changed and values(request['before'], [o['descriptor'] for o in changed]) ==
                    values(after, [o['descriptor'] for o in changed]), 'Activation has no stable observed result')
        else:
            verify_effect(request['action'], request['before'], after)

    def confirm(self, first: dict, second: dict, *,
                verified_by: str = 'two-fresh-DOM-observations-and-local-file-readback') -> dict:
        """Accept two fresh matching observations, then let the existing kernel validate."""
        require(self.pending is not None, 'There is no unconfirmed action')
        request = self.pending
        one, two = observe(first), observe(second)
        fresh(one, two)
        for after in (one, two):
            self._verify(request, after)
            for protected in request.get('protected', []):
                require(bind(after, protected['descriptor'])['value'] == protected['value'], 'Protected source changed')
        require(values(one) == values(two), 'Browser evidence is not stable')
        receipt = dict(id=request['id'], action=clone(request['action']), ok=True,
                       before=clone(request['before']), after=two,
                       verified_by=verified_by)
        if self.record is not None:
            self.record['receipts'].append(receipt)
            action = request['action']
            if action['kind'] == 'read':
                self.slots[action['slot']] = bind(two, action['descriptor'])['value']
        else:
            self.engine.accept_receipt(receipt)
        self.pending = None
        return clone(receipt)

    def finish_teaching(self) -> dict:
        """Learn only the completed observed demonstration through production code."""
        require(self.record is not None and self.pending is None, 'Demonstration is incomplete')
        self.engine.learn_episode(self.record)
        result = clone(self.record)
        self.record, self.slots = None, {}
        return result

    def start(self, query: str, raw: dict) -> None:
        """Start a learned command against new DOM elements and current values."""
        require(self.pending is None and self.record is None, 'Unfinished demonstration or action')
        self.engine.reset()
        self.engine.start_episode(query, observe(raw))

    def next(self, raw: dict) -> dict[str, Any]:
        """Expose exactly one kernel dispatch; a pending action is never sent twice."""
        require(self.pending is None and self.record is None, 'Confirm the previous action first')
        self.engine.observe(observe(raw))
        for _ in range(20):
            event = self.engine.tick()
            if event['kind'] == 'dispatch':
                self.pending = clone(self.engine.model['pending'])
                return clone(self.pending)
            if self.engine.model['status'] not in ('running', 'waiting'):
                return dict(status=self.engine.model['status'], message=self.engine.model['message'])
        raise ValueError('Kernel did not produce a bounded next step')
