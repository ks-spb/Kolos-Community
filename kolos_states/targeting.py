"""Resolve interchangeable icon instances and learned moves from fresh evidence."""
from __future__ import annotations

from .protocol import clone


def click_followup(memory: dict, step: dict | None) -> dict | None:
    """Only a direct learned CLICK -> Enter on the same target grants continuation."""
    if not step or step.get('action', {}).get('kind') != 'click':
        return None
    links = [e for e in memory['edges'] if e['kind'] == 'next' and e['from'] == step['id']]
    if len(links) != 1:
        return None
    following = next((n for n in memory['nodes'] if n['id'] == links[0]['to']), {})
    target, clicked = following.get('action', {}), step['action']
    if (target.get('kind') == 'enter' and target.get('object') == clicked['object']
            and target.get('visual') == clicked.get('visual')):
        return clone(target)
    return None


def nearest_icons(icons: list[dict], cursor: dict) -> list[dict]:
    """Keep the closest center per visual ID, with a spatial tie-break."""
    groups: dict[str, list[dict]] = {}
    for icon in icons:
        groups.setdefault(icon['id'], []).append(icon)
    return [clone(min(group, key=lambda icon: _distance_key(icon, cursor)))
            for group in groups.values()]


def _distance_key(icon: dict, cursor: dict) -> tuple:
    """Equal-distance copies are interchangeable; row order never selects one."""
    distance = (icon['x']-cursor['x'])**2 + (icon['y']-cursor['y'])**2
    return distance, icon['y'], icon['x'], tuple(icon.get('bbox', ()))


def motor_action(memory: dict, step: dict, observed: dict) -> dict:
    """Retarget a MOVE followed by CHECK/CLICK without rewriting the lesson."""
    result = clone(step['action'])
    if result['kind'] != 'move' or result.get('visual'):
        return result
    links = [edge for edge in memory['edges']
             if edge['kind'] == 'next' and edge['from'] == step['id']]
    if len(links) != 1:
        return result
    following = next((node for node in memory['nodes'] if node['id'] == links[0]['to']), {})
    target = following.get('action', {})
    if target.get('kind') not in ('check', 'click') or target.get('visual'):
        return result
    icon = next((icon for icon in observed['icons'] if icon['id'] == target['object']), None)
    if icon:
        result.update(x=icon['x'], y=icon['y'])
    return result
