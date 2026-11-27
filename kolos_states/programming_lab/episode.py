"""Run the learned read, stage and verify workflow through native Kolos episodes."""
from __future__ import annotations

from dataclasses import asdict
from difflib import SequenceMatcher
import json
from uuid import uuid4

from ..core import StateEngine
from ..episode_experiment import memory_signature
from ..episodes import SCHEMA
from .fixtures import Case, DEMO, DEMO_AFTER, behavior
from .transform import GuardRule, apply_guard

QUERY = 'Применить показанную проверку к функции'
SCOPE = 'Kolos.ProgrammingLab'


class Lab:
    """Expose the same controls with fresh runtime IDs for each attempt."""

    def __init__(self, case: Case, rule: GuardRule):
        self.case = case
        self.values = {'Rule': json.dumps(asdict(rule), ensure_ascii=False), 'Draft': '',
                       'Status': 'pending', 'Verify': None}
        self.session = uuid4().hex
        self.ids = {name: f'{self.session}:{i}' for i, name in enumerate(self.values)}
        self.version = 0
        self.actions: list[dict] = []
        self.checks: list[dict] = []
        self.preserved = False
        self.candidate: str | None = None

    def observe(self) -> dict:
        """Read current lab state independently of the graph's expected effects."""
        self.version += 1
        objects = [dict(id=self.ids[name], descriptor=dict(name=name, scope=SCOPE,
                        kind='button' if name == 'Verify' else 'field'), value=value,
                        readable=value is not None, writable=name == 'Draft', enabled=True,
                        protected=False) for name, value in self.values.items()]
        return dict(schema=SCHEMA, session=self.session, version=self.version,
                    captured_at=float(self.version), objects=objects)

    def execute(self, request: dict) -> dict:
        """Accept only the lab controls and report their observed effect."""
        before = self.observe()
        action = request['action']
        name = next((name for name, oid in self.ids.items() if oid == action['object']), '')
        operation = action['kind'], name
        reason = None
        if operation == ('write', 'Draft'):
            self.values['Draft'] = action['value']
        elif operation == ('activate', 'Verify'):
            reason = self._verify()
        elif operation != ('read', 'Rule'):
            raise ValueError(f'Unsupported lab operation: {operation}')
        self.actions.append(dict(kind=operation[0], control=name, ok=reason is None))
        return dict(id=request['id'], action=action, ok=reason is None, reason=reason,
                    before=before, after=self.observe())

    def _verify(self) -> str | None:
        """Build a candidate and confirm both a local diff and independent test results."""
        try:
            rule = GuardRule(**json.loads(self.values['Draft']))
            candidate = apply_guard(self.case.source, self.case.name, rule)
            self.preserved = _insertion_only(self.case.source, candidate)
            self.checks = behavior(self.case, candidate)
        except (ValueError, SyntaxError) as error:
            return str(error)
        if not (self.preserved and self.checks and all(row['passed'] for row in self.checks)):
            return 'Candidate failed structural or behavioral verification'
        self.candidate = candidate
        self.values['Status'] = 'verified'
        return None


def _insertion_only(before: str, after: str) -> bool:
    """Confirm existing lines remain intact and only one two-line block was added."""
    changes = [op for op in SequenceMatcher(None, before.splitlines(keepends=True),
                                           after.splitlines(keepends=True), autojunk=False).get_opcodes()
               if op[0] != 'equal']
    return len(changes) == 1 and changes[0][0] == 'insert' and changes[0][4] - changes[0][3] == 2


def teach_episode(engine: StateEngine, rule: GuardRule) -> dict:
    """Record one verified human workflow on the demonstration case."""
    lab = Lab(DEMO, rule)
    sequence = [dict(kind='read', object=lab.ids['Rule'], slot='rule'),
                dict(kind='write', object=lab.ids['Draft'], source='rule', value=lab.values['Rule']),
                dict(kind='activate', object=lab.ids['Verify'])]
    receipts = [lab.execute(dict(id=f'demo:{i}', action=action)) for i, action in enumerate(sequence)]
    if lab.candidate != DEMO_AFTER:
        raise ValueError('The demonstration did not reproduce the human patch')
    engine.learn_episode(dict(schema=SCHEMA, query=QUERY, receipts=receipts))
    return dict(actions=lab.actions, checks=lab.checks, runtime_session=lab.session)


def run_episode(engine: StateEngine, case: Case, rule: GuardRule) -> tuple[dict, str | None]:
    """Drive only actions requested by the restored episode and collect its evidence."""
    lab = Lab(case, rule)
    frozen, error, events = memory_signature(engine), None, []
    try:
        engine.start_episode(QUERY, lab.observe())
        for _ in range(40):
            event = engine.tick()
            events.append(event['kind'])
            if event['kind'] == 'dispatch':
                ack = engine.accept_receipt(lab.execute(engine.model['pending']))
                events.append(ack['kind'])
            if engine.model['status'] not in ('running', 'waiting'):
                break
    except ValueError as exc:
        error = str(exc)
    status = engine.model['status']
    record = dict(case=case.key, function=case.name, status=status, runtime_session=lab.session,
                  reason=error or (engine.model['message'] if status != 'complete' else None),
                  actions=lab.actions, events=events, checks=lab.checks, preserved=lab.preserved,
                  memory_unchanged=memory_signature(engine) == frozen)
    return record, lab.candidate if error is None and status == 'complete' else None
