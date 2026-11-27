"""Demonstrated working episodes, role binding and per-attempt values.

No world, form, copy/save route or command grammar lives here. The graph stores
only demonstrated order and explicit dataflow. Adapters provide independently
observed receipts; dispatch alone never releases a step or declares success.
The legacy state/goal/language paths and their equations are unchanged.
"""
from __future__ import annotations

import math
from .protocol import clone, compact, clamp, require

SCHEMA = 'kolos-working-episode/1'
MAX_VALUE = 20000
DESCRIPTOR_KEYS = ('kind', 'name', 'scope', 'automation_id')


def descriptor(raw):
    require(isinstance(raw, dict), 'Object descriptor is missing')
    result = {k: raw.get(k, '') for k in DESCRIPTOR_KEYS}
    require(all(isinstance(v, str) and len(v) <= 512 for v in result.values()),
            'Invalid object descriptor')
    require(result['kind'] and result['scope'] and
            (result['name'] or result['automation_id']),
            'Object needs a stable name or automation ID and a scope')
    return result


def observe(raw):
    require(isinstance(raw, dict) and raw.get('schema') == SCHEMA,
            'Expected a working-episode observation')
    require(isinstance(raw.get('session'), str) and 0 < len(raw['session']) <= 200,
            'Observation session is missing')
    require(type(raw.get('version')) is int and raw['version'] >= 0,
            'Observation version must be a nonnegative integer')
    require(isinstance(raw.get('captured_at'), (int, float)) and
            math.isfinite(raw['captured_at']) and raw['captured_at'] >= 0,
            'Observation capture time is missing')
    objects = raw.get('objects')
    require(isinstance(objects, list) and 0 < len(objects) <= 200,
            'Expected 1-200 observed objects')
    result = clone(raw)
    ids = set()
    for obj in result['objects']:
        require(isinstance(obj, dict) and isinstance(obj.get('id'), str) and
                0 < len(obj['id']) <= 512 and obj['id'] not in ids,
                'Missing or duplicate runtime object ID')
        ids.add(obj['id'])
        obj['descriptor'] = descriptor(obj.get('descriptor'))
        for key in ('readable', 'writable', 'enabled', 'protected'):
            require(type(obj.get(key)) is bool, 'Missing object flag: ' + key)
        require(not obj['protected'] or (not obj['readable'] and obj.get('value') is None),
                'Protected values must never be exposed')
        if obj['readable']:
            require(isinstance(obj.get('value'), str) and len(obj['value']) <= MAX_VALUE,
                    'Invalid or oversized observed value')
        else:
            require(obj.get('value') is None, 'Unreadable values must be None')
    return result


def object_by_id(obs, oid):
    matches = [o for o in obs['objects'] if o['id'] == oid]
    require(len(matches) == 1, 'Object is not visible')
    return matches[0]


def bind(obs, desc):
    matches = [o for o in obs['objects'] if o['descriptor'] == desc]
    require(len(matches) == 1, 'Missing or ambiguous role: ' + desc['name'])
    obj = matches[0]
    require(obj['enabled'] and not obj['protected'], 'Role is disabled or protected')
    return obj


def values(obs, exclude=()):
    excluded = {compact(d) for d in exclude}
    return sorted((compact(o['descriptor']), o['readable'], o['value'] or '')
                  for o in obs['objects'] if compact(o['descriptor']) not in excluded)


def fresh(before, after):
    require(before['session'] == after['session'] and
            after['version'] > before['version'] and
            after['captured_at'] >= before['captured_at'],
            'Stale, out-of-order or foreign observation')


def validate_action(raw, obs, slots):
    require(isinstance(raw, dict), 'Missing episode action')
    kind = raw.get('kind')
    require(kind in ('read', 'write', 'activate'), 'Unknown episode primitive')
    obj = object_by_id(obs, raw.get('object'))
    bind(obs, obj['descriptor'])
    a = dict(kind=kind, object=obj['id'])
    if kind in ('read', 'write'):
        require(obj['readable'], 'Field is not readable')
    if kind == 'read':
        slot = raw.get('slot')
        require(isinstance(slot, str) and 0 < len(slot) <= 80 and slot not in slots,
                'Read needs a new working-memory slot')
        a['slot'] = slot
    elif kind == 'write':
        slot = raw.get('source')
        require(slot in slots and obj['writable'], 'Write needs a known value and writable field')
        require(raw.get('value') == slots[slot], 'Write is not linked to the demonstrated read')
        a.update(source=slot, value=slots[slot])
    else:
        require(obj['descriptor']['kind'] == 'button', 'Activation needs an observed button')
    return a, obj


def _changed(before, after):
    changes = []
    for old in before['objects']:
        if not old['readable']:
            continue
        new = bind(after, old['descriptor'])
        require(new['readable'], 'A readable field disappeared')
        if new['value'] != old['value']:
            changes.append(new)
    return changes


def _connected(engine, source, target, kind):
    return any(e['to'] == target and e['weight'] > 0
               for e in engine.edges(source, kind))


def teach(engine, record):
    m = engine.model
    require(not m['pending'] and m['status'] not in ('running', 'waiting'),
            'Finish or reset the active attempt before teaching')
    require(isinstance(record, dict) and record.get('schema') == SCHEMA,
            'Invalid episode demonstration schema')
    query = record.get('query')
    require(isinstance(query, str) and 0 < len(query) <= 160, 'Query: 1-160 characters')
    receipts = record.get('receipts')
    require(isinstance(receipts, list) and 0 < len(receipts) <= 100,
            'Demonstration: 1-100 receipts')
    require(len(m.get('episodeCommands', [])) < 20, 'Episode demonstration limit')
    require(not any(c['query'] == query for c in m.get('episodeCommands', [])),
            'An episode with this exact query already exists')
    backup = clone(m)
    try:
        command = engine._node(kind='episode_command', label=query)
        engine._edge(m['memory']['root'], command['id'], 'episode_command')
        roles, slots, slot_nodes, slot_roles, writes, effects_roles = {}, {}, {}, {}, set(), set()
        previous, last_obs, seen = command['id'], None, set()
        checked = []

        def role(desc):
            key = compact(desc)
            if key not in roles:
                roles[key] = engine._node(kind='episode_role', label=desc['name'] or desc['automation_id'],
                                         descriptor=clone(desc))
                engine._edge(command['id'], roles[key]['id'], 'episode_role', 1)
            return roles[key]['id']

        for raw in receipts:
            require(isinstance(raw, dict) and raw.get('ok') is True and
                    isinstance(raw.get('id'), str) and raw['id'] not in seen,
                    'Teaching needs unique successful receipts')
            seen.add(raw['id'])
            before, after = observe(raw['before']), observe(raw['after'])
            fresh(before, after)
            if last_obs is not None:
                require(last_obs['session'] == before['session'] and
                        before['version'] >= last_obs['version'] and
                        before['captured_at'] >= last_obs['captured_at'] and
                        values(last_obs) == values(before), 'Broken demonstration continuity')
            a, obj = validate_action(raw['action'], before, slots)
            rid = role(obj['descriptor'])
            step = engine._node(kind='episode_step', label=a['kind'].upper() + ' ' + (obj['descriptor']['name'] or rid),
                                operation=a['kind'], role=rid, effects=[])
            engine._edge(previous, step['id'], 'episode_next')
            engine._edge(rid, step['id'], 'episode_binds', 1)
            target = bind(after, obj['descriptor'])
            if a['kind'] == 'read':
                require(target['readable'] and values(before) == values(after),
                        'Read changed the environment')
                slots[a['slot']] = target['value']
                slot = engine._node(kind='episode_slot', label=a['slot'])
                slot_nodes[a['slot']] = slot['id']
                slot_roles[slot['id']] = rid
                step['slot'] = slot['id']
                engine._edge(step['id'], slot['id'], 'episode_produces', 1)
            elif a['kind'] == 'write':
                require(target['readable'] and target['value'] == a['value'] and
                        values(before, [obj['descriptor']]) == values(after, [obj['descriptor']]),
                        'Write result or unchanged surrounding fields were not confirmed')
                step['source'] = slot_nodes[a['source']]
                engine._edge(step['source'], step['id'], 'episode_value', 1)
                writes.add(rid)
            else:
                changes = _changed(before, after)
                require(changes, 'Activation has no independently observed result')
                require(values(before, [o['descriptor'] for o in changes]) ==
                        values(after, [o['descriptor'] for o in changes]),
                        'Unsupported structural change during activation')
                for changed in changes:
                    matches = [name for name, val in slots.items() if val == changed['value']]
                    require(len(matches) <= 1, 'Ambiguous dataflow in observed activation result')
                    effect_role = role(changed['descriptor'])
                    effect = dict(role=effect_role)
                    if matches:
                        effect['source'] = slot_nodes[matches[0]]
                        engine._edge(effect['source'], step['id'], 'episode_value', 1)
                    else:
                        effect['literal'] = changed['value']
                    step['effects'].append(effect)
                    engine._edge(step['id'], effect_role, 'episode_effect', 1)
                    effects_roles.add(effect_role)
            checked.append(dict(id=raw['id'], action=a, ok=True, before=before, after=after))
            previous, last_obs = step['id'], after
        require(slots and writes, 'A working episode needs observed reading and writing')
        finish = engine._node(kind='episode_finish', label='Observed episode complete')
        engine._edge(previous, finish['id'], 'episode_next')
        protected = sorted(set(slot_roles.values()) - writes - effects_roles)
        spec = dict(query=query, node=command['id'], protected=protected,
                    roles=[r['id'] for r in roles.values()])
        m.setdefault('episodeCommands', []).append(spec)
        normalized = dict(schema=SCHEMA, query=query, receipts=checked)
        m['learningLog'].append(dict(episode=True, record=normalized))
        m.update(status='trained', message='Working episode learned from observed actions and dataflow.')
    except Exception:
        engine.model = backup
        raise
    return engine._event(dict(kind='episode-teach', command=command['id']))


def _roles(engine, run, obs):
    return {rid: bind(obs, engine.node(rid)['descriptor']) for rid in run['command']['roles']}


def _invariants(run, bound):
    for rid, value in run['protected'].items():
        require(bound[rid]['readable'] and bound[rid]['value'] == value,
                'A protected source changed during the episode')


def start(engine, query, raw):
    m = engine.model
    require(not m['pending'], 'An unconfirmed effect requires an explicit reset')
    obs = observe(raw)
    matches = [c for c in m.get('episodeCommands', []) if c['query'] == query]
    require(len(matches) == 1, 'Unknown or ambiguous episode query; demonstrate it first')
    command = matches[0]
    require(_connected(engine, m['memory']['root'], command['node'], 'episode_command'),
            'The learned command connection is missing')
    run = dict(command=clone(command), previous=command['node'], working={}, protected={},
               latest=obs, acknowledgements=[], bindings={}, complete=False)
    bound = _roles(engine, run, obs)
    run['protected'] = {rid: bound[rid]['value'] for rid in command['protected']}
    require(all(bound[rid]['readable'] for rid in command['protected']), 'A source is not readable')
    m['attempt'] += 1
    m.update(phase='episode', status='running', episode=run, observed=clone(obs), query=query,
             heldGoal=True, tick=0, intent=None, imagery=None, language=None, pending=None,
             activation={}, refractory={}, trace={}, occ=[], plan=None, detour=None,
             message='Roles bound; values will be read from this attempt, not the demonstration.')
    return engine._event(dict(kind='episode-start'))


def update_observation(engine, raw):
    m = engine.model
    obs = observe(raw)
    previous = m['episode']['latest']
    require(obs['session'] == previous['session'] and obs['version'] >= previous['version'] and
            obs['captured_at'] >= previous['captured_at'], 'Stale or foreign observation')
    if obs['version'] == previous['version']:
        require(obs == previous, 'A frame version was reused with changed data')
    # Invariant values are never replaced by a later observation.
    m['episode']['latest'] = obs
    m['observed'] = clone(obs)


def _value(run, slot):
    require(slot in run['working'], 'A required value has not been read in this attempt')
    return run['working'][slot]['value']


def expected_effects(engine, step, run, bound):
    effects = []
    for effect in step.get('effects', []):
        require(_connected(engine, step['id'], effect['role'], 'episode_effect'),
                'A learned result connection is missing')
        if 'source' in effect:
            require(_connected(engine, effect['source'], step['id'], 'episode_value'),
                    'A learned value connection is missing')
        effects.append(dict(descriptor=clone(bound[effect['role']]['descriptor']),
                            value=_value(run, effect['source']) if 'source' in effect else effect['literal']))
    return effects


def tick(engine):
    m = engine.model
    run = m['episode']
    m['tick'] += 1
    if m['status'] not in ('running', 'waiting'):
        return engine._event(dict(kind='stopped'))
    if m['pending']:
        if m['tick'] - m['pending']['sent'] >= m['config']['timeout']:
            m.update(status='timeout', message='No receipt; no retry. Inspect the environment and reset explicitly.')
        return engine._event(dict(kind='waiting'))
    if m['tick'] > 1800:
        m.update(status='limit', message='Episode tick limit; goal remains held.')
        return engine._event(dict(kind='limit'))
    try:
        obs = run['latest']
        bound = _roles(engine, run, obs)
        _invariants(run, bound)
        run['bindings'] = {rid: obj['id'] for rid, obj in bound.items()}
        links = engine.edges(run['previous'], 'episode_next')
        require(len(links) == 1 and links[0]['weight'] > 0, 'Missing, disabled or ambiguous learned next connection')
        edge = links[0]
        step = engine.node(edge['to'])
        require(step and step['kind'] in ('episode_step', 'episode_finish'), 'Invalid learned episode step')
        score = clamp(m['activation'].get(step['id'], 0) * m['config']['decay'] + edge['weight'])
        m['activation'][step['id']] = score
        event = dict(kind='episode-charge', candidates=[dict(id=step['id'], label=step['label'],
                     a=score, threshold=m['config']['threshold'], allowed=True)],
                     flows=[dict(edge=edge['id'], source=edge['from'], target=edge['to'], value=edge['weight'])])
        if score < m['config']['threshold']:
            return engine._event(event)
        if step['kind'] == 'episode_finish':
            run['complete'] = True
            run['working'] = {}  # Values never leak into the next attempt.
            m.update(status='complete', heldGoal=False, message='Every demonstrated effect and source invariant is observed.')
            return engine._event(dict(kind='episode-complete'))
        require(_connected(engine, step['role'], step['id'], 'episode_binds'), 'A learned role connection is missing')
        obj = bound[step['role']]
        a = dict(kind=step['operation'], object=obj['id'], descriptor=clone(obj['descriptor']))
        if a['kind'] in ('read', 'write'):
            require(obj['readable'], 'Field is not readable')
        if a['kind'] == 'read':
            require(_connected(engine, step['id'], step['slot'], 'episode_produces'), 'A learned read connection is missing')
        elif a['kind'] == 'write':
            require(obj['writable'] and _connected(engine, step['source'], step['id'], 'episode_value'),
                    'Field is not writable or value connection is missing')
            a['value'] = _value(run, step['source'])
        a['effects'] = expected_effects(engine, step, run, bound)
        m['serial'] += 1
        request = dict(id=f"episode:{m['attempt']}:{m['serial']}", action=a, step=step['id'],
                       before=clone(obs), sent=m['tick'],
                       protected=[dict(descriptor=clone(bound[rid]['descriptor']), value=val)
                                  for rid, val in run['protected'].items()])
        m.update(pending=request, status='waiting', message='Waiting for independent evidence: ' + step['label'])
        event.update(kind='dispatch', request=request['id'], action=clone(a), winner=step['id'])
        return engine._event(event)
    except ValueError as exc:
        m.update(status='blocked', message=str(exc))
        return engine._event(dict(kind='episode-blocked', reason=str(exc)))


def verify_effect(a, before, after):
    """Shared evidence contract, used by recorder, adapter and kernel independently."""
    fresh(before, after)
    target = bind(after, a['descriptor'])
    if a['kind'] == 'read':
        require(target['readable'] and values(before) == values(after), 'Read evidence is inconsistent')
    elif a['kind'] == 'write':
        require(target['readable'] and target['value'] == a['value'] and
                values(before, [a['descriptor']]) == values(after, [a['descriptor']]),
                'Exact write result or unchanged surrounding fields not observed')
    elif a['kind'] == 'activate':
        effects = a.get('effects', [])
        require(effects, 'An activation needs learned observable effects')
        changed = False
        for effect in effects:
            old, new = bind(before, effect['descriptor']), bind(after, effect['descriptor'])
            require(new['readable'] and new['value'] == effect['value'], 'Activation result not observed')
            changed |= old['value'] != new['value']
        require(changed and values(before, [e['descriptor'] for e in effects]) ==
                values(after, [e['descriptor'] for e in effects]), 'No independent activation effect or unexpected mutation')
    else:
        raise ValueError('Unknown primitive')


def accept(engine, raw):
    m = engine.model
    run, pending = m['episode'], m['pending']
    if not isinstance(raw, dict):
        raise ValueError('Missing receipt')
    if raw.get('id') in run['acknowledgements']:
        return engine._event(dict(kind='duplicate'))
    if not pending or raw.get('id') != pending['id'] or raw.get('action') != pending['action']:
        return engine._event(dict(kind='ignored'))
    require(m['status'] == 'waiting', 'A stopped or timed-out attempt cannot resume from a late receipt')
    # Validate everything before releasing the pending request, source or step.
    before, after = observe(raw['before']), observe(raw['after'])
    baseline = pending['before']
    require(before['session'] == baseline['session'] and before['version'] >= baseline['version'] and
            before['captured_at'] >= baseline['captured_at'] and values(before) == values(baseline),
            'Receipt does not describe the selected starting observation')
    require(type(raw.get('ok')) is bool, 'Receipt must have a boolean outcome')
    _invariants(run, _roles(engine, run, before))
    fresh(before, after)
    if not raw['ok']:
        m.update(status='failed', message=raw.get('reason', 'Episode action failed; explicit reset required.'))
        return engine._event(dict(kind='episode-failed'))
    a = pending['action']
    obj = bind(before, a['descriptor'])
    require(obj['id'] == a['object'], 'Dispatch target changed')
    require(a['kind'] != 'write' or obj['writable'], 'Field is no longer writable')
    verify_effect(a, before, after)
    bound = _roles(engine, run, after)
    _invariants(run, bound)
    step = engine.node(pending['step'])
    if a['kind'] == 'read':
        run['working'][step['slot']] = dict(value=bound[step['role']]['value'], role=step['role'],
                                          readVersion=after['version'], consumedBy=[])
    used = {step['source']} if step.get('source') else set()
    used.update(e['source'] for e in step['effects'] if 'source' in e)
    for slot in used:
        run['working'][slot]['consumedBy'].append(raw['id'])
    run['previous'] = step['id']
    run['latest'] = clone(after)
    run['acknowledgements'].append(raw['id'])
    m['receipts'].append(clone(raw))
    m['activation'][step['id']] = 0
    m['trace'][step['id']] = 1
    m['refractory'][step['id']] = m['config']['refractory']
    m.update(pending=None, status='running', observed=clone(after), message='Observed and confirmed: ' + step['label'])
    return engine._event(dict(kind='episode-ack', receipt=clone(raw), winner=step['id']))
