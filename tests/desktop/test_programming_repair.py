"""Check autonomous selection, retries and hidden-test separation in the repair lab."""
from __future__ import annotations

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.fixtures import DEMO, DEMO_AFTER
from kolos_states.programming_lab.repair.cases import CONTROLS, HELD_OUT, TEACHING
from kolos_states.programming_lab.repair.patches import candidates
from kolos_states.programming_lab.repair.policy import Ranker, learned_order, teach, trace_order
from kolos_states.programming_lab.repair.search import score, solve
from kolos_states.programming_lab.transform import GuardRule, learn_guard


@pytest.fixture(scope='module')
def learned_policy() -> tuple[GuardRule, Ranker]:
    """Teach on the separate training sources only."""
    rule = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    engine = StateEngine()
    teach(engine, TEACHING, rule)
    return rule, learned_order(engine)


def test_finds_helper_using_only_the_public_call(learned_policy: tuple[GuardRule, Ranker]) -> None:
    """The failing test invokes export, while the verified patch belongs in format_name."""
    rule, rank = learned_policy
    task = next(case for case in HELD_OUT if case.name == 'slug')
    run = solve(task.source, task.visible, candidates(task.source, rule), rank, 3)
    row, verified = score(task, run)
    assert row['proposal']['function'] == 'format_name'
    assert task.visible[0].function == 'export'
    assert row['status'] == 'solved'
    assert verified and 'if title is None:' in verified


def test_retries_after_first_candidate_fails(learned_policy: tuple[GuardRule, Ranker]) -> None:
    """The lab rejects a highly ranked decoy and fixes the earlier expression."""
    rule, rank = learned_policy
    task = next(case for case in HELD_OUT if case.name == 'retry')
    pool = candidates(task.source, rule)
    first, _ = score(task, solve(task.source, task.visible, pool, rank, 1))
    row, verified = score(task, solve(task.source, task.visible, pool, rank, 3))
    assert first['status'] == 'no-solution'
    assert row['status'] == 'solved' and len(row['attempts']) == 2
    assert not all(check['passed'] for check in row['attempts'][0]['visible'])
    assert verified and "display = stamp or 'unused'" in verified


def test_hidden_failure_is_scored_after_submission(learned_policy: tuple[GuardRule, Ranker]) -> None:
    """Visible tests can accept an edit without hidden evaluation releasing it."""
    rule, rank = learned_policy
    task = next(case for case in CONTROLS if case.name == 'hidden-failure')
    run = solve(task.source, task.visible, candidates(task.source, rule), rank, 3)
    assert run.proposal is not None
    assert all(check['passed'] for check in run.attempts[-1]['visible'])
    row, verified = score(task, run)
    assert row['status'] == 'hidden-failed'
    assert not all(check['passed'] for check in row['hidden'])
    assert verified is None


def test_clean_task_never_dispatches_edits(learned_policy: tuple[GuardRule, Ranker]) -> None:
    """A clean public check ends search before selecting any candidate."""
    rule, rank = learned_policy
    task = next(case for case in CONTROLS if case.name == 'already-correct')
    row, verified = score(task, solve(task.source, task.visible, candidates(task.source, rule), rank, 3))
    assert row['status'] == 'unchanged' and not row['attempts'] and verified is None


def test_cold_policy_reproduces_enumeration(learned_policy: tuple[GuardRule, Ranker]) -> None:
    """Removing the learned graph leaves the same ordering as the simple baseline."""
    rule, _ = learned_policy
    cold = learned_order(StateEngine())
    for task in HELD_OUT + CONTROLS:
        pool = candidates(task.source, rule)
        assert solve(task.source, task.visible, pool, cold, 3) == solve(task.source, task.visible, pool, trace_order, 3)
