"""Exercise repair composition, partial test feedback, and experiment controls."""
from __future__ import annotations

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.fixtures import DEMO, DEMO_AFTER
from kolos_states.programming_lab.repair.cases import TEACHING
from kolos_states.programming_lab.repair.compose import compose
from kolos_states.programming_lab.repair.composition_cases import CHECKS, PAIRS, SINGLE
from kolos_states.programming_lab.repair.composition_experiment import minimum_edits
from kolos_states.programming_lab.repair.policy import Ranker, learned_order, teach
from kolos_states.programming_lab.repair.search import score
from kolos_states.programming_lab.transform import GuardRule, learn_guard


@pytest.fixture(scope='module')
def policy() -> tuple[GuardRule, Ranker]:
    """Learn individual operations on the original six cases only."""
    rule = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    engine = StateEngine()
    teach(engine, TEACHING, rule)
    return rule, learned_order(engine)


def test_all_composition_tasks_require_two_edits(policy: tuple[GuardRule, Ranker]) -> None:
    """Independently rule out all single-edit solutions, including using hidden tests."""
    rule, _ = policy
    assert [minimum_edits(task, rule)['minimum'] for task in PAIRS] == [2] * len(PAIRS)


def test_search_extends_the_intermediate_fix(policy: tuple[GuardRule, Ranker]) -> None:
    """The second change is applied to the patched revision, preserving the guard."""
    rule, rank = policy
    task = next(case for case in PAIRS if case.name == 'name-display')
    result = compose(task.source, task.visible, rule, rank, 2, feedback=True)
    assert [a['path'] for a in result.attempts] == [(1,), (1, 2)]
    assert [(a['function'], a['failed_before'], a['failed_after']) for a in result.attempts] == [
        ('normalize', 2, 1), ('display', 1, 0),
    ]
    row, source = score(task, result)
    assert row['status'] == 'solved' and source is not None
    assert 'if name is None:\n        return None' in source
    assert "'Без имени' if cleaned is None else cleaned" in source


def test_search_can_cross_a_plateau(policy: tuple[GuardRule, Ranker]) -> None:
    """A first edit can be part of the solution even if the same test remains red."""
    rule, rank = policy
    task = next(case for case in PAIRS if case.name == 'joint-result')
    result = compose(task.source, task.visible, rule, rank, 12, feedback=True)
    row, source = score(task, result)
    first, second = result.attempts[-1]['path']
    assert result.attempts[first - 1]['failed_before'] == result.attempts[first - 1]['failed_after'] == 1
    assert result.attempts[second - 1]['failed_after'] == 0
    assert row['status'] == 'solved' and source is not None


def test_budget_does_not_count_hidden_tests_as_search_feedback(policy: tuple[GuardRule, Ranker]) -> None:
    """Stop short at one try and withhold a visibly valid but incorrect proposal."""
    rule, rank = policy
    task = PAIRS[0]
    limited = compose(task.source, task.visible, rule, rank, 1, feedback=True)
    assert len(limited.attempts) == 1 and limited.proposal is None
    rejected = next(case for case in CHECKS if case.name == 'hidden-failure')
    reviewed = compose(rejected.source, rejected.visible, rule, rank, 12, feedback=True)
    assert reviewed.proposal is not None
    row, generated = score(rejected, reviewed)
    assert row['status'] == 'hidden-failed' and generated is None
    assert minimum_edits(rejected, rule)['minimum'] == 2


def test_single_edit_is_not_forced_into_a_pair(policy: tuple[GuardRule, Ranker]) -> None:
    """Stop on the first verified candidate, even when it contains only one edit."""
    rule, rank = policy
    result = compose(SINGLE.source, SINGLE.visible, rule, rank, 12, feedback=True)
    row, source = score(SINGLE, result)
    assert row['status'] == 'solved' and source is not None
    assert len(result.attempts[-1]['path']) == 1
