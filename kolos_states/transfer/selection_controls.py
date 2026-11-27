"""Frozen pre-fix decision rule, used only as an experimental ablation.

The shared runtime still owns observations, actions, receipts and plasticity.
This reproduces first-threshold-crossing selection and the former .04 margin.
"""
from __future__ import annotations

from .. import dynamics
from ..backward import backward_wave
from ..goal_network import choose


def early_decision(m: dict, owner: dict, cfg: dict, features: list[str], threshold: float,
                   event: dict, exhausted: bool, strength: float = 1) -> dict:
    """Select directly from the current wave, exactly as before the route fix."""
    nodes = [n for n in m['memory']['nodes'] if n['kind'] in ('state', 'transition')]
    activity = backward_wave(m['memory'], nodes, m['goalActivation'], cfg, event['flows'])
    dynamics.seed_demand(m, activity, features, strength)
    m['goalActivation'] = activity
    event['candidates'] = dynamics.transition_candidates(m, activity, cfg, threshold)
    decision = choose(event['candidates'], threshold, cfg['margin'])
    return decision or (dict(blocked=True) if exhausted else {})
