"""Verify program composition, standalone reconciliation and graph preservation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.calculator.intent import Clarification
from kolos_states.programming_lab.reconcile.cli import _load, _record, _restore, _train
from kolos_states.programming_lab.reconcile.components import plans
from kolos_states.programming_lab.reconcile.intent import REQUEST, recognize
from kolos_states.programming_lab.repair.policy import _activation, _remember


def test_text_uses_learned_terms_without_accepting_extra_requirements() -> None:
    """The known request is understood and an unrecognized aggregation is reported."""
    engine = StateEngine()
    with pytest.raises(Clarification):
        recognize(REQUEST, engine)
    _train(engine)
    intent = recognize(REQUEST, engine)
    assert (intent.inputs, intent.duplicates, intent.output) == (2, 'sum', 'changed_only')
    assert intent.defaults == ()
    with pytest.raises(Clarification):
        recognize('сверь два csv и посчитай медиану', engine)


def test_task_specific_sum_lesson_preserves_generic_count_memory() -> None:
    """Generic experience can choose an inapplicable count until a scoped lesson is learned."""
    engine = StateEngine()
    _remember(engine, 'synthesis/mapping/count/all', 9, 0)
    generic = _activation(engine, 'synthesis/mapping/count/all')
    assert plans(engine)[0].group == 'count'
    _train(engine)
    assert plans(engine)[0].group == 'sum'
    assert _activation(engine, 'synthesis/mapping/count/all') == generic


def test_command_produces_a_runnable_report_writer_from_saved_memory() -> None:
    """Generate and invoke the ordinary standalone program on fresh files."""
    with TemporaryDirectory() as folder:
        path = Path(folder)
        memory, tool = path / 'memory', path / 'reconcile.py'
        engine = StateEngine()
        _train(engine)
        _record(memory, engine)
        created = subprocess.run([sys.executable, '-B', '-m', 'kolos_states.programming_lab', 'reconcile',
                                  '--request', REQUEST, '--memory', str(memory), '--output', str(tool)],
                                 capture_output=True, encoding='utf-8', timeout=60)
        assert created.returncode == 0, created.stderr
        assert json.loads(created.stdout)['checks_passed'] == 8
        before, after, output = (path / name for name in ('before.csv', 'after.csv', 'delta.csv'))
        before.write_text('sku,qty\nX,-7\nX,4\nY,3\n', encoding='utf-8')
        after.write_text('sku,qty\nX,1\nN,6\n', encoding='utf-8')
        command = [sys.executable, '-B', '-X', 'utf8', str(tool), str(before), str(after), '--output', str(output)]
        result = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=8)
        assert result.returncode == 0 and not result.stdout
        assert output.read_text(encoding='utf-8') == 'sku,before,after,delta\nN,0,6,6\nX,-3,1,4\nY,3,0,-3\n'


def test_restore_snapshot_and_preserve_a_concurrent_update() -> None:
    """Recovery copies the saved graph, and promotion respects an intervening write."""
    with TemporaryDirectory() as folder:
        path = Path(folder)
        archive, active = path / 'snapshots', path / 'active'
        initial = archive / 'initial'
        _record(initial, StateEngine())
        original = (initial / 'memory.json').read_bytes()
        assert _restore(active, archive) == str(initial / 'memory.json')
        assert (active / 'memory.json').read_bytes() == original
        newer = _load(active)
        _train(newer)
        _record(active, newer, expected=original)
        changed = (active / 'memory.json').read_bytes()
        assert changed != original
        assert not _record(active, StateEngine(), expected=original)
        assert (active / 'memory.json').read_bytes() == changed
