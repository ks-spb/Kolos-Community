"""Check text recognition, independent fragment learning and standalone calculator execution."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from kolos_states.core import StateEngine
from kolos_states.programming_lab.calculator import lab
from kolos_states.programming_lab.calculator.cli import EXPLICIT_REQUEST, SHORT_REQUEST
from kolos_states.programming_lab.calculator.components import plans
from kolos_states.programming_lab.calculator.intent import Clarification, recognize


@pytest.fixture(scope='module')
def learned() -> StateEngine:
    """Use only standalone word and component lessons."""
    return lab.train()[0]


def test_short_and_explicit_requests_share_a_contract(learned: StateEngine) -> None:
    """Unknown wording is assembled from known words, with explicit defaults on the short request."""
    short, explicit = (recognize(request, learned) for request in (SHORT_REQUEST, EXPLICIT_REQUEST))
    assert short.operations == explicit.operations == ('+', '-', '*', '/')
    assert short.interface == explicit.interface == 'console'
    assert short.numbers == explicit.numbers == 'decimal'
    assert short.defaults == ('console', 'decimal', 'arithmetic') and explicit.defaults == ()
    with pytest.raises(Clarification):
        recognize(SHORT_REQUEST, StateEngine())


@pytest.mark.parametrize('request_text', ['сделай калькулятор с окном', 'не создавай калькулятор',
                                          'сделай калькулятор с логарифмами', 'создай программу'])
def test_unmet_request_does_not_choose_program(request_text: str, learned: StateEngine) -> None:
    """Reject requests that do not identify the supported calculator contract."""
    with pytest.raises(Clarification):
        recognize(request_text, learned)


def test_verified_fragments_rank_first(learned: StateEngine) -> None:
    """Training should change composition order before any full calculator test is used."""
    expected = ('three_arguments', 'decimal', 'quotient', 'plain_decimal', 'stderr')
    assert tuple(c.name for c in plans(learned)[0]) == expected
    assert tuple(c.name for c in plans(StateEngine())[0]) != expected


def _command(request: str, output: Path) -> subprocess.CompletedProcess:
    """Use the same documented CLI as an end user."""
    return subprocess.run([sys.executable, '-B', '-m', 'kolos_states.programming_lab', 'calculator',
                           '--request', request, '--output', str(output)],
                          capture_output=True, encoding='utf-8', timeout=60)


def test_public_command_generates_runnable_file() -> None:
    """A different fractional expression works in the independently invoked generated application."""
    with TemporaryDirectory() as folder:
        output = Path(folder) / 'calculator.py'
        made = _command(SHORT_REQUEST, output)
        assert made.returncode == 0, made.stderr
        outcome = json.loads(made.stdout)
        assert outcome['status'] == 'generated' and outcome['attempts'] == 1
        assert outcome['checks_passed'] == len(lab.CHECKS)
        launched = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(output), '10', '÷', '4'],
                                  cwd=folder, capture_output=True, encoding='utf-8', timeout=5)
        assert launched.returncode == 0 and launched.stdout.strip() == '2.5' and not launched.stderr


def test_window_request_preserves_existing_file() -> None:
    """A clarification leaves an existing user's application byte-for-byte intact."""
    with TemporaryDirectory() as folder:
        output = Path(folder) / 'calculator.py'
        output.write_bytes(b'# Original file\n')
        made = _command('сделай калькулятор с окном', output)
        assert made.returncode == 2 and json.loads(made.stdout)['status'] == 'needs_clarification'
        assert output.read_bytes() == b'# Original file\n'


def test_failed_independent_check_never_publishes(monkeypatch, learned: StateEngine) -> None:
    """Do not issue a generated file or fall back on another candidate after hidden failure."""
    monkeypatch.setattr(lab, 'CHECKS', (lab.Case('contradiction', ('1', '+', '1'), '3'),))
    with TemporaryDirectory() as folder:
        output = Path(folder) / 'calculator.py'
        output.write_bytes(b'# Original file\n')
        result = lab.generate(recognize(SHORT_REQUEST, learned), learned, output)
        assert result['status'] == 'check_failed' and len(result['attempts']) == 1
        assert output.read_bytes() == b'# Original file\n'
