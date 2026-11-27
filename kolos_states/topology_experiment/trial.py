"""Shared native execution and explicit, receipt-safe delivery of changed goals."""
from __future__ import annotations

import copy
from time import perf_counter_ns
from unittest.mock import patch

from .. import goal_network
from ..core import StateEngine, STOP
from ..simulator import apply, observe
from ..transfer.runner import fingerprint
from . import oracle
from .selectors import LOW_THRESHOLD, Selector
from .world import TopologyLab

SCENARIOS = ('static', 'during_spread', 'after_click', 'pending_click')


class Trial:
    """Keep host time across goal resets; engine tick counters are per-goal."""

    def __init__(self, base: StateEngine, lab: TopologyLab, selector: str, scenario: str) -> None:
        """Pair all arms on identical frozen memory and environment."""
        if scenario not in SCENARIOS:
            raise ValueError('Unknown scenario: ' + scenario)
        self.engine = copy.deepcopy(base)
        self.engine.reset()
        self.engine.events.clear()
        self.lab, self.scenario, self.selector = lab, scenario, Selector(selector)
        self.world = lab.at()
        self.target = 2 if scenario in ('after_click', 'pending_click') else lab.goals[0]
        self.final_target = (0 if scenario == 'after_click' else
                             lab.goals[1] if scenario == 'during_spread' else lab.goals[0])
        self.tick = 0
        self.clicks = 0
        self.changes: list[dict] = []
        self.action_log: list[dict] = []
        self.decisions: list[dict] = []
        self.before = fingerprint(self.engine)
        self._start()

    def _start(self) -> None:
        """Use the public goal API for both initial and changed goals."""
        config = dict(routeThreshold=LOW_THRESHOLD) if self.selector.name == 'native_low_threshold' else None
        self.engine.start_goals([self.lab.goal(self.target)], observe(self.world), config)

    def _request(self) -> None:
        """Record actual arrival before any deferred receipt is processed."""
        m = self.engine.model
        self.changes.append(dict(request_tick=self.tick, from_target=self.target, to_target=self.final_target,
                                 surface=self.world['surface'], pending=bool(m['pending']),
                                 old_episode=bool(m['intent']['episode']), old_wave=m['intent']['wave'],
                                 action_index=len(self.action_log), deliver_tick=None))

    def _deliver(self) -> None:
        """Abort the old episode only after its outstanding effect has a receipt."""
        if not self.changes or self.changes[0]['deliver_tick'] is not None or self.engine.model['pending']:
            return
        self.target = self.final_target
        self._start()
        self.changes[0].update(deliver_tick=self.tick, delivered_surface=self.world['surface'],
                               delivered_action_index=len(self.action_log),
                               activation_cleared=not self.engine.model['goalActivation'],
                               old_episode_cleared=self.engine.model['intent']['episode'] is None)

    def _before_tick(self) -> None:
        """Trigger goal requests by execution milestones, rather than favorable route outcomes."""
        if not self.changes:
            spread = self.scenario == 'during_spread' and self.selector.stats['route_calls'] >= 2
            clicked = self.scenario == 'after_click' and self.clicks >= 1
            if spread or clicked:
                self._request()
        self._deliver()

    def _effect(self) -> None:
        """Separate dispatch, physical effect and acknowledgement; queue pending-goal requests."""
        pending = self.engine.model['pending']
        if self.scenario == 'pending_click' and not self.changes and pending['action']['kind'] == 'click':
            self._request()
        receipt = apply(self.world, pending)
        regret = oracle.click_regret(self.lab, self.target, receipt['action'])
        self.action_log.append(dict(tick=self.tick, goal=self.target, receipt=receipt,
                                    regret=None if regret == float('inf') else regret,
                                    off_goal=regret > 1e-7, after_change=bool(self.changes and self.changes[0]['deliver_tick'] is not None)))
        self.engine.tick()
        self.tick += 1
        self.engine.accept_receipt(receipt)
        self.clicks += int(receipt['action']['kind'] == 'click')
        self._deliver()

    def run(self) -> dict:
        """Measure identical route boundaries and independently score final state and costs."""
        start = perf_counter_ns()
        with patch.object(goal_network, 'route_wave', self.selector.route):
            for _ in range(1900):
                self._before_tick()
                if self.engine.model['status'] in STOP:
                    break
                event = self.engine.tick()
                self.tick += 1
                if event['kind'] == 'route':
                    self.decisions.append(dict(tick=self.tick, target=self.target, winner=event['winner']))
                if self.engine.model['pending']:
                    self._effect()
            else:
                self.engine.model.update(status='limit')
        elapsed = perf_counter_ns() - start
        return self._result(elapsed)

    def _result(self, elapsed: int) -> dict:
        """Distinguish arrival, reachability, refusal and successful completion."""
        m = self.engine.model
        switched = bool(self.changes and self.changes[0]['deliver_tick'] is not None)
        intended = self.final_target if self.scenario != 'static' else self.target
        origin = self.lab.labels.index(self.changes[0]['delivered_surface']) if switched else 0
        reachable = origin in oracle.costs(self.lab, intended)
        actual = self.world['surface'] == self.lab.labels[intended]
        declared = m['status'] == 'complete'
        delivered = switched or self.scenario == 'static'
        success = delivered and reachable and declared and actual
        after = [a for a in self.action_log if a['after_change'] or self.scenario == 'static']
        safe_block = delivered and not reachable and m['status'] == 'blocked' and not after
        change = self.changes[0] if switched else None
        return dict(family=self.lab.family, seed=self.lab.seed, selector=self.selector.name, scenario=self.scenario,
                    success=success, correct=success or safe_block, reachable=reachable, status=m['status'],
                    false_success=declared and not actual, changed=switched, changes=self.changes,
                    host_ticks=self.tick, elapsed_ns=elapsed, **self.selector.stats,
                    response_ticks=self.tick - change['deliver_tick'] if change else None,
                    clicks=self.clicks, actions=self.action_log, decisions=self.decisions,
                    off_goal_clicks=sum(a['off_goal'] for a in self.action_log),
                    off_goal_after_change=sum(a['off_goal'] for a in after),
                    failed_effects=sum(not a['receipt']['ok'] for a in self.action_log),
                    final_candidates=[{k: c[k] for k in ('id', 'label', 'a', 'allowed', 'upper') if k in c}
                                      for c in (self.engine.events[-1].get('candidates', []))],
                    memory_before=self.before, memory_after=fingerprint(self.engine))
