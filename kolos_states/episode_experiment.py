"""Independent E13 environment and reproducible stage-1 report.

The environment knows only its own controls. It never reads graph state, goals,
roles, expected effects or a test number to decide a result.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import uuid
from .core import StateEngine
from .episodes import SCHEMA, bind, values
from .protocol import clone, compact


class FormWorld:
    def __init__(self, sources=('training-alpha',), *, layout=0, prefix=None):
        self.session = uuid.uuid4().hex
        self.version = 0
        self.layout = layout
        self.prefix = prefix or uuid.uuid4().hex[:8]
        self.data = {'Unrelated': 'do not touch'}
        self.pairs = []
        for i, value in enumerate(sources, 1):
            source, target, saved = f'Source {i}', f'Target {i}', f'Saved {i}'
            self.data.update({source: value, target: '<old>', saved: '<not saved>'})
            self.pairs.append((source, target, saved))
        self.ids = {name: self.prefix + ':' + str(i) for i, name in enumerate([*self.data, 'Save'])}
        self.actions = []
        self.fail_save = False
        self.corrupt_source = False
        self.hidden = set()
        self.unreadable = set()
        self.disabled = set()
        self.duplicate = None

    def observe(self):
        self.version += 1
        names = [*self.data, 'Save']
        if self.layout % 2:
            names.reverse()
        objects = []
        for i, name in enumerate(names):
            if name in self.hidden:
                continue
            button = name == 'Save'
            readable = not button and name not in self.unreadable
            obj = dict(id=self.ids[name], descriptor=dict(kind='button' if button else 'field',
                       name=name, scope='Kolos.WorkingEpisode', automation_id=''),
                       readable=readable, writable=name.startswith('Target '),
                       enabled=name not in self.disabled, protected=False,
                       value=self.data[name] if readable else None,
                       bbox=[10 + (i % 2) * 260, 20 + i * 40, 240 + (i % 2) * 260, 50 + i * 40])
            objects.append(obj)
            if name == self.duplicate:
                copy = clone(obj)
                copy['id'] += ':duplicate'
                objects.append(copy)
        return dict(schema=SCHEMA, session=self.session, version=self.version,
                    captured_at=float(self.version), objects=objects)

    def execute(self, request):
        before = self.observe()
        a = request['action']
        reverse = {value: key for key, value in self.ids.items()}
        name = reverse[a['object']]
        self.actions.append(clone(a))
        if a['kind'] == 'write':
            if not name.startswith('Target '):
                raise ValueError('Environment refuses a non-writable field')
            self.data[name] = a['value']
        elif a['kind'] == 'activate':
            if name != 'Save':
                raise ValueError('Environment has no such button')
            if not self.fail_save:
                for _, target, saved in self.pairs:
                    self.data[saved] = self.data[target]
        elif a['kind'] != 'read':
            raise ValueError('Unknown environment operation')
        if self.corrupt_source and a['kind'] == 'write':
            self.data[self.pairs[0][0]] = 'unexpected mutation'
        return dict(id=request['id'], action=clone(a), ok=True,
                    before=before, after=self.observe())


def demonstration(world=None, query='Copy the observed fields and save'):
    world = world or FormWorld()
    receipts, slots = [], {}
    for index, (source, target, _) in enumerate(world.pairs):
        slot = 'value' + str(index)
        a = dict(kind='read', object=world.ids[source], slot=slot)
        r = world.execute(dict(id='demo:' + str(len(receipts)), action=a))
        slots[slot] = next(o['value'] for o in r['after']['objects'] if o['id'] == world.ids[source])
        receipts.append(r)
        a = dict(kind='write', object=world.ids[target], source=slot, value=slots[slot])
        receipts.append(world.execute(dict(id='demo:' + str(len(receipts)), action=a)))
    receipts.append(world.execute(dict(id='demo:' + str(len(receipts)),
                                       action=dict(kind='activate', object=world.ids['Save']))))
    return dict(schema=SCHEMA, query=query, receipts=receipts)


def memory_signature(engine):
    return compact(dict(memory=engine.model['memory'], learningLog=engine.model['learningLog'],
                        commands=engine.model.get('episodeCommands', [])))


def run(engine, world, query='Copy the observed fields and save', limit=250):
    frozen = memory_signature(engine)
    expected_sources = {source: world.data[source] for source, _, _ in world.pairs}
    error = None
    frames = []
    try:
        engine.start_episode(query, world.observe())
        for _ in range(limit):
            event = engine.tick()
            frames.append(clone(event))
            if event['kind'] == 'dispatch':
                engine.accept_receipt(world.execute(clone(engine.model['pending'])))
            if engine.model['status'] not in ('running', 'waiting'):
                break
    except ValueError as exc:
        error = str(exc)
    checks = dict(complete=engine.model['status'] == 'complete' and error is None,
                  sourcesUnchanged=all(world.data[k] == v for k, v in expected_sources.items()),
                  targetsExact=all(world.data[t] == expected_sources[s] for s, t, _ in world.pairs),
                  savedExact=all(world.data[v] == expected_sources[s] for s, _, v in world.pairs),
                  unrelatedUnchanged=world.data['Unrelated'] == 'do not touch',
                  memoryUnchanged=memory_signature(engine) == frozen,
                  workingMemoryCleared=not (engine.model.get('episode') or {}).get('working'))
    return dict(passed=all(checks.values()), checks=checks, status=engine.model['status'],
                error=error, ticks=engine.model['tick'], actions=clone(world.actions), frames=frames)


def report():
    from .shared_experiment import SharedSession
    session = SharedSession()
    before = session.run_all()
    session.engine.reset()
    session.engine.learn_episode(demonstration())
    rows = []
    for text, layout in [('new-6143', 0), ('  новая строка Ω 🙂  ', 1), ('', 2), ('line one\nline two\tend', 3)]:
        session.engine.reset()
        row = run(session.engine, FormWorld((text,), layout=layout))
        rows.append(dict(experiment='E13', variant='new-value' if layout == 0 else 'new-layout-and-value', value=text, layout=layout,
                         passed=row['passed'], checks=row['checks'], ticks=row['ticks']))
    session.engine.reset()
    after = SharedSession(engine=session.engine).run_all(range(12, 0, -1))
    session.engine.reset()
    session.engine.learn_episode(demonstration(FormWorld(('alpha', 'beta')), query='Two independent values'))
    multiple = run(session.engine, FormWorld(('new first', 'new second'), layout=1), query='Two independent values')
    return dict(schema=SCHEMA, passed=all(r['passed'] for r in rows) and multiple['passed'] and
                all(r['pass'] for r in before + after),
                regressionsBefore=[dict(number=r['number'], passed=r['pass']) for r in before],
                experiments=rows, multipleFields=dict(passed=multiple['passed'], checks=multiple['checks']),
                regressionsAfter=[dict(number=r['number'], passed=r['pass']) for r in after],
                memorySHA256=hashlib.sha256(memory_signature(session.engine).encode()).hexdigest(),
                scope='Model environment; native Windows UI Automation is tested separately.')


def main():
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    result = report()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
