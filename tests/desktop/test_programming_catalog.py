"""Check frozen lessons, ten independent program contracts and native policy persistence."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.calculator.lab import train
from kolos_states.programming_lab.catalog.cli import policy_of, save_policy
from kolos_states.programming_lab.catalog.corpus import STAGES, Request, corpora
from kolos_states.programming_lab.catalog.judge import evaluate
from kolos_states.programming_lab.catalog.routing import Policy, Router, Trainer, calibrate, choose_lexicon, decide, features
from kolos_states.programming_lab.catalog.spec import Clarify, KINDS, Spec, normalized, parse
from kolos_states.programming_lab.reconcile.cli import _load, _record, _train
from kolos_states.programming_lab.repair.policy import _activation, _remember


@pytest.fixture(scope='module')
def decks() -> tuple:
    """Use the frozen corpus and independent reference results."""
    return corpora()


def test_frozen_corpus_sizes_labels_and_isolation(decks: tuple) -> None:
    """Each protocol checkpoint has equal per-family coverage and independent requests."""
    train_cases, calibration, closed = decks
    keys = [normalized(row.text) for batch in decks for row in batch]
    assert len(set(keys)) == len(keys)
    assert (len(train_cases), len(calibration), len(closed)) == (10000, 140, 380)
    for target in STAGES[1:]:
        assert Counter(row.expected.kind for row in train_cases[:target]) == dict.fromkeys(KINDS, target // 10)
    assert Counter(row.category for row in closed) == {'supported': 300, 'ambiguous': 40, 'unknown': 40}
    assert all(len(row.probes) == 2 and row.probes[0] != row.probes[1] for row in closed if row.expected is not None)


def test_parameter_contract_separates_comparison_and_route() -> None:
    """A terminal period, signed threshold and required sort field follow one common parser."""
    assert parse('number_filter', 'Оставь целые числа не меньше −7.') == Spec('number_filter', '>=', -7)
    assert parse('csv_sort', 'отсортируй по количеству по убыванию') == Spec('csv_sort', column='qty', descending=True)
    with pytest.raises(Clarify):
        parse('number_count', 'посчитай числа больше 2.5')
    with pytest.raises(Clarify):
        parse('csv_sort', 'отсортируй csv')


def test_exact_native_receipts_update_existing_weights_without_new_nodes() -> None:
    """Repeated aggregate lessons reuse the same native transition and preserve unrelated experience."""
    engine = StateEngine()
    _remember(engine, 'older-skill', 2, 0)
    _remember(engine, 'catalog/route/test/number_filter', 1, 1, exact=True)
    counts = tuple(len(engine.model['memory'][key]) for key in ('nodes', 'edges'))
    _remember(engine, 'catalog/route/test/number_filter', 8, 2, exact=True)
    assert tuple(len(engine.model['memory'][key]) for key in ('nodes', 'edges')) == counts
    assert _activation(engine, 'older-skill') == 0.5
    assert _activation(engine, 'catalog/route/test/number_filter') == 0.5


def test_all_ten_runners_execute_on_independent_inputs(decks: tuple) -> None:
    """Exercise the full output format of each artifact in its own Python process."""
    engine, _ = train()
    _train(engine)
    samples = [next(row for row in decks[2] if row.expected is not None and row.expected.kind == kind)
               for kind in KINDS]
    with TemporaryDirectory() as folder:
        for sample in samples:
            _, report = evaluate((sample,), lambda _: sample.expected.kind, engine, Path(folder) / sample.id, 1)
            assert report['solved'] == 1 and report['python_executions'] == 2, sample.id


def test_public_cli_reloads_and_protects_existing_output() -> None:
    """Load a trained two-sentence router from disk and execute a newly issued filter."""
    learned = StateEngine()
    requests = (Request('a', 'оставь целые числа больше 7', Spec('number_filter', '>', 7)),
                Request('b', 'оставь целые числа меньше -2', Spec('number_filter', '<', -2)))
    lexicon = tuple(sorted(set().union(*(features(row.text) for row in requests))))
    trainer = Trainer(learned, lexicon)
    trainer.learn(requests)
    policy = Policy(lexicon, 0.1, 0.1)
    save_policy(learned, policy, lessons=2)
    with TemporaryDirectory() as folder:
        path = Path(folder)
        memory, program = path / 'memory', path / 'filter.py'
        _record(memory, learned)
        assert policy_of(_load(memory)) == policy
        command = [sys.executable, '-B', '-m', 'kolos_states.programming_lab', 'catalog', '--memory', str(memory),
                   '--output', str(program), '--request']
        issued = subprocess.run([*command, requests[0].text], capture_output=True, encoding='utf-8', timeout=30)
        assert issued.returncode == 0, (issued.stdout, issued.stderr)
        assert json.loads(issued.stdout)['python_executions'] == 2
        original = program.read_bytes()
        refused = subprocess.run([*command, 'посчитай медиану списка чисел'], capture_output=True,
                                 encoding='utf-8', timeout=30)
        assert refused.returncode == 2 and program.read_bytes() == original


def test_balanced_feature_set_is_bounded(decks: tuple) -> None:
    """Choosing the vocabulary uses only the first balanced training prefix."""
    lexicon = choose_lexicon(decks[0][:100])
    assert len(lexicon) == len(set(lexicon)) == 48
    assert not decide('посчитай медиану списка чисел', Router(StateEngine(), Policy()).pick).spec


def test_calibration_checks_meaningful_thresholds_above_point_three_five() -> None:
    """A high-score supported request should survive when a closer control can be rejected."""
    good = Request('a', 'оставь числа больше 7', Spec('number_filter', '>', 7))
    wrong = Request('b', 'построй диаграмму csv', None, category='unknown')

    class Evidence:
        policy = Policy(('числа',))

        def ranks(self, text: str) -> tuple[str, float, float]:
            """Make the margin identical so only a meaningful floor can separate the two."""
            return ('number_filter', 0.86, 0.50) if text == good.text else ('reconcile', 0.62, 0.50)

        def legacy(self, text: str) -> None:
            """The older recognizers provide no result on this pair."""
            return None

    policy, measured = calibrate(Evidence(), (good, wrong))
    assert 0.62 < policy.floor <= 0.86
    assert measured == dict(correct=1, wrong=0, false_accepts=0)
