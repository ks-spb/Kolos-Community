"""Rehearse saved cluster tasks with the frozen learner; no browser or advertisement IO."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

from ..cluster_replay.controllers import run_kolos, run_script
from ..cluster_replay.corpus import _case, digest
from ..cluster_replay.isolation import offline_host
from ..cluster_replay.world import Blocked, UnknownOutcome, VARIANTS, World
from .routing import CLUSTER


SHADOW_REPLAY_AUTHORIZATION_NOTICE = 'Synthetic local permission only; real approvals not consumed'


def cases(state: dict) -> tuple[list[dict], dict]:
    """Unexecuted proposals are simulated contracts, never historical successful examples."""
    result, proposals = [], {}
    for p in state['proposals'].values():
        if p['command'] != CLUSTER or p['status'] not in ('verified', 'proposed'):
            continue
        if p['status'] == 'verified':
            case = _case(p)
            case['source_kind'] = 'historical_verified_transition'
        else:
            target, before = p['payload']['excluded'], p['preconditions']
            if (before.get('campaign_id') != p['payload']['campaign_id']
                    or before.get('norm_query') != p['payload']['norm_query']
                    or p['payload']['nm_id'] != p['identity']['nm_id']):
                raise ValueError('Prospective proposal scope mismatch')
            if type(target) is not bool or type(before.get('excluded')) is not bool:
                raise ValueError('Cluster contract needs explicit boolean state')
            if target == before['excluded']:
                raise ValueError('Prospective fixture is already at target')
            case = dict(id=p['proposal_id'], identity=copy.deepcopy(p['identity']),
                        campaign_id=p['payload']['campaign_id'], query=p['payload']['norm_query'],
                        target=target, before=copy.deepcopy(before),
                        after=dict(before, excluded=target), source_kind='unexecuted_proposal_simulation')
        result.append(case)
        proposals[case['id']] = copy.deepcopy(p)
    return result, proposals


def load_goal_policy(path: Path):
    """Reuse the application's existing pure result matcher, not a new authority check."""
    spec = importlib.util.spec_from_file_location('kolos_frozen_goal_policy', path)
    if spec is None or spec.loader is None:
        raise ValueError('Goal policy unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_case(case: dict, proposal: dict, variant: str, selector: str, learned: dict,
             matcher, layout: int) -> dict:
    """Require kernel completion AND the independent WB application's target matcher."""
    world = World(case, variant, layout)
    reason = ''
    try:
        status = run_kolos(world, learned) if selector == 'kolos' else run_script(world)
    except UnknownOutcome:
        status, reason = 'pending', 'lost_receipt_no_retry'
    except (ValueError, KeyError, TypeError) as exc:
        status, reason = 'blocked', str(exc)
    observed = dict(case['before'], excluded=json.loads(world.data['Persisted excluded']))
    goal_matches = bool(matcher(proposal, observed))
    oracle = world.oracle(status)
    actual_goal = oracle['completed'] and goal_matches
    return dict(case=case['id'], source_kind=case['source_kind'], selector=selector, variant=variant,
                status=status, reason=reason, target=case['target'], goal_matches=goal_matches,
                confirmed_goal=actual_goal, memory_sha256=digest(learned),
                **dict(oracle, correct_outcome=oracle['correct_outcome'] and (actual_goal if variant == 'clean' else True),
                       false_success=status == 'complete' and not actual_goal), operations=world.operations)


def rehearse(heldout: list[dict], proposals: dict, learned: dict, goal_path: Path) -> dict:
    """Use identical cases and faults for Kolos and the ordinary local recipe."""
    frozen = digest(learned)
    policy = load_goal_policy(goal_path)
    with offline_host():
        rows = [run_case(case, proposals[case['id']], variant, selector, learned, policy.matches, index + 17)
                for index, case in enumerate(heldout) for variant in VARIANTS for selector in ('kolos', 'script')]
        damaged = copy.deepcopy(learned)
        first = next(e for e in damaged['model']['memory']['edges'] if e['kind'] == 'episode_next')
        first['weight'] = 0
        lesion = [run_case(c, proposals[c['id']], 'clean', 'kolos', damaged, policy.matches, 90 + i)
                  for i, c in enumerate(heldout)]
    if digest(learned) != frozen:
        raise AssertionError('Rehearsal modified frozen memory')
    return dict(pid=os.getpid(), memory_sha256=frozen, rows=rows, memory_off=lesion,
                authorization=SHADOW_REPLAY_AUTHORIZATION_NOTICE,
                live_ad_changes=0, model_calls=0, network='denied_during_rehearsal')


def restart(heldout: list[dict], proposals: dict, learned: dict, goal_path: Path) -> dict:
    """A fresh interpreter performs only clean held-out cases with the same saved memory."""
    policy = load_goal_policy(goal_path)
    with offline_host():
        rows = [run_case(c, proposals[c['id']], 'clean', 'kolos', learned, policy.matches, 200 + i)
                for i, c in enumerate(heldout)]
    return dict(pid=os.getpid(), memory_sha256=digest(learned), rows=rows,
                live_ad_changes=0, model_calls=0)
