"""Certify a local route winner before a faster signal can trigger an action.

The backward operator is monotone on [0, 1]. Iteration from zero and one
encloses every fixed point of the SAME learned dynamics, including cycles.
Selection needs disjoint score bounds, not a fixed delay or a route search.
Bounds are transient and restart when the operator or desired input changes.
"""
from __future__ import annotations

from . import dynamics
from .backward import backward_wave

# Ten rounding units of the existing nine-decimal activity arithmetic.
ROUNDING_GAP = 1e-8


def _advance(m: dict, owner: dict, cfg: dict, features: list[str],
             strength: float, flows: list[dict]) -> dict:
    """Propagate bounds; invalidate on topology, weight or input edits."""
    nodes = [n for n in m['memory']['nodes'] if n['kind'] in ('state', 'transition')]
    seed: dict = {}
    dynamics.seed_demand(m, seed, features, strength)
    stamp = ([(n['id'], n['kind']) for n in nodes],
             [(e['from'], e['to'], e['weight']) for e in m['memory']['edges'] if e['kind'] == 'backward'],
             seed, cfg['decay'], cfg['discount'], cfg.get('stateCompetition', 1))
    previous = owner.get('routeBounds', {})
    reset = not m['goalActivation'] or previous.get('stamp') != stamp
    lower = {} if reset else m['goalActivation']
    upper = {n['id']: 1 for n in nodes} if reset else previous['upper']
    lower = backward_wave(m['memory'], nodes, lower, cfg, flows)
    upper = backward_wave(m['memory'], nodes, upper, cfg, [])
    for node_id, value in seed.items():
        lower[node_id] = max(lower.get(node_id, 0), value)
        upper[node_id] = max(upper.get(node_id, 0), value)
    m['goalActivation'] = lower
    owner['routeBounds'] = dict(stamp=stamp, upper=upper)
    return upper


def certified_choice(candidates: list[dict], threshold: float, exhausted: bool) -> dict:
    """Require a lower bound above every allowed rival's upper bound; never break ties by ID."""
    ranks = sorted((c for c in candidates if c['allowed']), key=lambda c: -c['a'])
    if ranks and ranks[0]['a'] >= threshold:
        rival = max((c['upper'] for c in ranks[1:]), default=-1)
        if ranks[0]['a'] > rival + ROUNDING_GAP:
            return dict(winner=ranks[0])
    if exhausted:
        return dict(ambiguous=True) if sum(c['upper'] >= threshold for c in ranks) > 1 else dict(blocked=True)
    return {}


def route_decision(m: dict, owner: dict, cfg: dict, features: list[str], threshold: float,
                   event: dict, exhausted: bool, strength: float = 1) -> dict:
    """Share certified selection between goal execution and suspended-command recovery."""
    upper = _advance(m, owner, cfg, features, strength, event['flows'])
    candidates = dynamics.transition_candidates(m, m['goalActivation'], cfg, threshold)
    ceiling = {c['id']: c['a'] for c in dynamics.transition_candidates(m, upper, cfg, threshold)}
    for candidate in candidates:
        candidate['upper'] = ceiling[candidate['id']]
    event['candidates'] = candidates
    return certified_choice(candidates, threshold, exhausted)
