"""Compare demonstrated command paths without treating hover coordinates as intent."""
from .protocol import compact, observation_key


class AmbiguousCommand(ValueError):
    """Matching demonstrations describe distinct actions, fields, or contexts."""


def _signature(context: str, data: bool, focus: str, steps: list[dict]) -> str:
    """Keep observed states and action guards; anchor MOVE to its following CHECK."""
    normalized=[]
    for index, step in enumerate(steps):
        action=step['action']
        following=steps[index+1]['action'] if index+1<len(steps) else {}
        if action['kind']=='move' and following.get('kind')=='check':
            action=dict(kind='move',object=following['object'])
        normalized.append([action,step['pre'],step['post'],step.get('visual_ack',False),
                           step.get('dispatch_only',False)])
    return compact([context,data,focus,normalized])


def demonstration_signature(context: str, data: bool, focus: str, setup: list[dict], final: dict) -> str:
    """Derive the same identity from receipts before creating new graph steps."""
    steps=[dict(action=r['action'],pre=observation_key(r['before']),post=observation_key(r['after']),
                visual_ack=r['action']['kind']=='enter' and r.get('verified_by')=='visual-change',
                dispatch_only=r.get('effect_observed') is False) for r in setup]
    steps.append(dict(action=dict(kind='drive' if data else 'finish'),pre=observation_key(final),post=None))
    return _signature(context,data,focus,steps)


def command_signature(model: dict, command: dict) -> str | None:
    """Read actual stored paths so older coordinate-sensitive signatures also work."""
    nodes={n['id']:n for n in model['memory']['nodes']};following={}
    for edge in model['memory']['edges']:
        if edge['kind']=='next':following.setdefault(edge['from'],[]).append(edge['to'])
    current=command['first'];seen=set();steps=[]
    while current not in seen:
        seen.add(current);step=nodes.get(current)
        if not step or step.get('kind')!='step':return None
        pre=nodes.get(step.get('pre'));post=nodes.get(step.get('post'))
        if not pre or pre.get('kind')!='state' or (step.get('post') is not None and not post):return None
        steps.append(dict(action=step['action'],pre=pre['key'],post=post['key'] if post else None,
                          visual_ack=step.get('visual_ack',False),dispatch_only=step.get('dispatch_only',False)))
        if step['action']['kind']==('drive' if command['data'] else 'finish'):
            return _signature(command['context'],command['data'],command['focus'],steps)
        if len(following.get(current,[]))!=1:return None
        current=following[current][0]
    return None


def select_match(model: dict, matches: list[dict]) -> dict:
    """Collapse equivalent demonstrations while preserving genuine conflicts."""
    if len(matches)==1:return matches[0]
    signatures=[command_signature(model,match['command']) for match in matches]
    if None in signatures or len(set(signatures))!=1:
        raise AmbiguousCommand('Неоднозначная команда: демонстрации различаются по действиям, полям или состояниям')
    return matches[0]
