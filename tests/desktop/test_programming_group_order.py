"""Verify inference of row filters and filters on group totals in Python synthesis."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.synthesis.benchmark import _prompt
from kolos_states.programming_lab.synthesis.corpus import HELD_OUT, TEACHING
from kolos_states.programming_lab.synthesis.grammar import choices, render, semantic_key
from kolos_states.programming_lab.synthesis.group_corpus import CONTROLS, LESSONS, ORDERED_TASKS, baseline_orders
from kolos_states.programming_lab.synthesis.grouped import compose_choices
from kolos_states.programming_lab.synthesis.judge import evaluate
from kolos_states.programming_lab.synthesis.solver import solve, train
from kolos_states.programming_lab.synthesis.spec import Task


def test_composition_corpus_is_distinct_and_requires_an_aggregate_filter() -> None:
    """The old grammar cannot independently pass both example sets on any primary task."""
    known = {task.function for task in TEACHING + HELD_OUT + LESSONS}
    assert len(ORDERED_TASKS) == 12
    assert {task.function for task in ORDERED_TASKS + CONTROLS}.isdisjoint(known)
    assert not any(baseline_orders(task) for task in ORDERED_TASKS)


def test_one_exact_candidate_per_new_task() -> None:
    """Test independent learned and empty graphs with one executable attempt each."""
    learned, weights = train(LESSONS)
    assert 'synthesis/mapping/sum/all' in weights and 'synthesis/list/filter/>' in weights
    for engine in (learned, StateEngine()):
        for task in ORDERED_TASKS:
            result = solve(task, engine, 1, monotonic() + 10, compose=True)
            assert result['status'] == 'solved'
            assert result['screening']['eligible'] == len(result['attempts']) == 1
            recipe = result['attempts'][0]['recipe']
            assert recipe['result_predicate'] is not None and recipe['predicate'] is None


@pytest.mark.parametrize(('task', 'order'), tuple(zip(CONTROLS, ('none', 'before', 'before'), strict=True)))
def test_original_filter_order_is_selected_when_required(task: Task, order: str) -> None:
    """The new mode still finds ordinary aggregation and the pre-aggregation filter."""
    verified_orders = baseline_orders(task)
    assert order in verified_orders
    if order == 'before':
        assert 'none' not in verified_orders
    result = solve(task, StateEngine(), 1, monotonic() + 10, compose=True)
    assert result['status'] == 'solved'
    recipe = result['attempts'][0]['recipe']
    assert recipe['result_predicate'] is None
    assert ('before' if recipe['predicate'] is not None else 'none') == order


@pytest.mark.parametrize('task', [ORDERED_TASKS[0], ORDERED_TASKS[-1], CONTROLS[1]], ids=lambda task: task.function)
def test_group_constraints_agree_with_generated_programs(task: Task) -> None:
    """Cross-check mathematical candidate rejection against the public evaluator."""
    candidates, permits = compose_choices(task.examples, choices(task.examples))
    for recipe in dict.fromkeys(map(semantic_key, candidates)):
        judge = evaluate(render(task, recipe), task.function, task.parameter, task.examples)
        assert permits(recipe) == judge.passed


def test_composition_prompt_contains_neither_solution_order_nor_hidden_examples() -> None:
    """The external comparator receives only public data and supported Python operations."""
    task = ORDERED_TASKS[0]
    prompt = _prompt(task, [], compose=True)
    hidden_key = task.checks[0].input[0]['sku']
    assert hidden_key not in prompt
    assert 'dictionary keys' in prompt and 'aggregate filter' not in prompt


def test_public_command_generates_an_importable_stock_function() -> None:
    """Check real command use and unseen cancelling or negative totals in Python."""
    with TemporaryDirectory() as folder:
        output = Path(folder) / 'totals.py'
        command = [sys.executable, '-B', '-m', 'kolos_states.programming_lab', 'synthesize', '--compose',
                   '--task', 'examples/programming/positive_stock_totals.json', '--output', str(output)]
        built = subprocess.run(command, capture_output=True, timeout=30)
        assert built.returncode == 0, built.stderr
        probe = ('from totals import positive_stock_totals as f\n'
                 'rows=[dict(sku="K",qty=100),dict(sku="X",qty=-5),dict(sku="K",qty=-100),dict(sku="X",qty=7)]\n'
                 'assert f(rows) == {"X": 2}\nassert f([]) == {}\n')
        checked = subprocess.run([sys.executable, '-B', '-c', probe], cwd=folder, capture_output=True, timeout=10)
        assert checked.returncode == 0, checked.stderr
