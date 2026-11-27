"""Verify the user command, separate judge, and Codex comparison contract."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.repair.policy import _remember
from kolos_states.programming_lab.synthesis.benchmark import _prompt, _reply
from kolos_states.programming_lab.synthesis.constraints import from_examples
from kolos_states.programming_lab.synthesis.corpus import HELD_OUT, TEACHING
from kolos_states.programming_lab.synthesis.grammar import Predicate, Recipe, choices, render, semantic_key
from kolos_states.programming_lab.synthesis.judge import evaluate
from kolos_states.programming_lab.synthesis.solver import solve, train
from kolos_states.programming_lab.synthesis.spec import parse_task


def _task(check_expected: list[int]) -> dict:
    """A task with two possible interpretations in its open input."""
    return dict(function='positive', parameter='numbers', examples=[dict(input=[0, 1], expected=[1])],
                checks=[dict(input=[-1, 0, 1], expected=check_expected)])


def test_hidden_check_does_not_change_search() -> None:
    """A different check can reject the same submitted program without reranking it."""
    engine = StateEngine()
    first = solve(parse_task(_task([1])), engine, 8, monotonic() + 10)
    second = solve(parse_task(_task([-1, 1])), engine, 8, monotonic() + 10)
    assert first['status'] == 'solved' and second['status'] == 'check_failed'
    assert first['attempts'] == second['attempts'] and second['source'] is None


def test_equivalent_integer_comparisons_have_one_key() -> None:
    """Inclusive and exclusive neighbours should not spend two interpreter attempts."""
    assert semantic_key(Recipe('count', predicate=Predicate(None, '>=', -4))) == Recipe(
        'count', predicate=Predicate(None, '>', -5))
    assert semantic_key(Recipe('sum', predicate=Predicate(None, '<=', 9))) == Recipe(
        'sum', predicate=Predicate(None, '<', 10))


@pytest.mark.parametrize('expected', [[-11, -11, 0], 3, -22])
def test_numeric_constraints_agree_with_generated_python(expected) -> None:
    """Check every operator and candidate family against the full public evaluator."""
    task = parse_task(dict(function='measure', parameter='data', examples=[
        dict(input=[-11, -11, 0, 3, 8, 8], expected=expected),
    ], checks=[dict(input=[-11, -11, 0, 3, 8, 8], expected=expected)]))
    permitted = from_examples(task.examples)
    assert permitted is not None
    for recipe in choices(task.examples):
        observed = evaluate(render(task, recipe), task.function, task.parameter, task.examples)
        assert permitted(recipe) == observed.passed


@pytest.mark.parametrize(('shown', 'unseen'), [([4, 4], [4, 4]), ([-14, 0, 17], [-50, 0, 50])])
def test_equality_and_inequality_do_not_exhaust_attempts(shown: list[int], unseen: list[int]) -> None:
    """Use unfamiliar thresholds and examples that require equality or its complement."""
    task = parse_task(dict(function='select', parameter='data', examples=[
        dict(input=[-14, 0, 4, 4, 17], expected=shown),
    ], checks=[dict(input=[-50, 4, 0, 4, 50], expected=unseen)]))
    result = solve(task, StateEngine(), 1, monotonic() + 10)
    assert result['status'] == 'solved' and len(result['attempts']) == 1
    assert result['screening']['rejected_by_examples'] > 0


def test_learned_order_does_not_override_a_simpler_exact_match() -> None:
    """An overly strong operator preference should not hide a simpler fitting rule."""
    task = parse_task(dict(function='count_real', parameter='data', examples=[
        dict(input=[0, 1, 2, 4], expected=3), dict(input=[0, -2, 3, 7], expected=3),
    ], checks=[dict(input=[0, 0, 20], expected=1)]))
    engine = StateEngine()
    _remember(engine, 'synthesis/number/count/<=', 50, 0)
    _remember(engine, 'synthesis/number/count/!=', 0, 50)
    result = solve(task, engine, 1, monotonic() + 10)
    assert result['status'] == 'solved' and result['screening']['eligible'] > 1
    assert result['attempts'][0]['recipe']['predicate']['op'] == '!='


def test_rejects_mismatched_and_boolean_examples() -> None:
    """Python equality cannot silently merge boolean and integer data domains."""
    task = _task([1])
    task['checks'][0]['input'] = [True]
    with pytest.raises(ValueError, match='целыми числами'):
        parse_task(task)


def test_submitted_source_uses_restricted_evaluator() -> None:
    """Submitted Python cannot reach an import or filesystem call through the judge."""
    task = parse_task(_task([1]))
    attempts = ('import os\ndef positive(numbers):\n    return [1]\n',
                'def positive(numbers):\n    open("data.txt")\n    return [1]\n',
                'def positive(numbers):\n    return [True]\n')
    for source in attempts:
        assert not evaluate(source, task.function, task.parameter, task.examples).passed


def test_corpus_and_codex_feedback_keep_checks_private() -> None:
    """The external adapter sends public examples and rejects unexpected tool use."""
    assert len(HELD_OUT) == 18
    assert {t.function for t in TEACHING}.isdisjoint(t.function for t in HELD_OUT)
    prompt = _prompt(parse_task(_task([-99])), [])
    assert '-99' not in prompt and 'checks' not in prompt
    events = [{'type': 'item.completed', 'item': {'type': 'command_execution'}}, {'type': 'turn.completed'}]
    assert _reply('\n'.join(map(json.dumps, events))) == (None, {'failure': 'tool_used'})


def test_cli_generates_importable_user_file_and_preserves_output_on_failure() -> None:
    """Run the ordinary entry point from outside the fixture corpus, with native memory reload."""
    with TemporaryDirectory() as folder:
        path = Path(folder)
        task, output, memory = path / 'user.json', path / 'totals.py', path / 'memory'
        payload = dict(function='my_totals', parameter='data', examples=[
            dict(input=[{'id': 'M', 'n': 11}, {'id': 'M', 'n': -2}], expected={'M': 9}),
        ], checks=[dict(input=[{'id': 'other', 'n': 31}], expected={'other': 31}),
                   dict(input=[], expected={})])
        task.write_text(json.dumps(payload), encoding='utf-8')
        entry = [sys.executable, '-B', '-m', 'kolos_states.programming_lab']
        primed = subprocess.run([*entry, 'synthesize-learn', '--memory', str(memory), '--task', str(task)],
                                capture_output=True, timeout=30)
        assert primed.returncode == 0, primed.stderr
        command = [*entry, 'synthesize', '--task', str(task), '--output', str(output), '--memory', str(memory)]
        built = subprocess.run(command, capture_output=True, timeout=30)
        assert built.returncode == 0, built.stderr
        before = output.read_bytes()
        checked = subprocess.run([sys.executable, '-B', '-c',
                                  "from totals import my_totals; assert my_totals([{'id': 'X', 'n': 3}]) == {'X': 3}"],
                                 cwd=path, capture_output=True, timeout=10)
        assert checked.returncode == 0, checked.stderr
        payload['checks'][0]['expected'] = {'other': 32}
        task.write_text(json.dumps(payload), encoding='utf-8')
        rejected = subprocess.run(command, capture_output=True, timeout=30)
        assert rejected.returncode == 1 and json.loads(rejected.stdout)['status'] == 'check_failed'
        assert output.read_bytes() == before
