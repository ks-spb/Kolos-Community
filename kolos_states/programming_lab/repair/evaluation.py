"""Execute bundled examples and observe the failing Python call trace."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import sys
from types import FrameType

from .cases import Probe

FILENAME = '<kolos-repair-fixture>'


@dataclass(frozen=True)
class Visit:
    """One executed line in a Python fixture."""

    function: str
    line: int
    depth: int


@dataclass(frozen=True)
class Check:
    """One actual result and its execution evidence."""

    probe: Probe
    passed: bool
    actual: object = None
    error: str | None = None
    trace: tuple[Visit, ...] = ()


def _depth(frame: FrameType) -> int:
    """Count only calls in the synthetic source."""
    depth = 1
    while frame.f_back and frame.f_back.f_code.co_filename == FILENAME:
        depth += 1
        frame = frame.f_back
    return depth


def _check(namespace: dict, probe: Probe, tracing: bool) -> Check:
    """Capture the requested call without leaking other host frames into the trace."""
    trace = []

    def observe(frame: FrameType, event: str, argument: object):
        if frame.f_code.co_filename != FILENAME:
            return None
        if event == 'line':
            trace.append(Visit(frame.f_code.co_name, frame.f_lineno, _depth(frame)))
        return observe

    previous = sys.gettrace()
    try:
        if tracing:
            sys.settrace(observe)
        actual = namespace[probe.function](deepcopy(probe.argument))
    except Exception as exc:
        return Check(probe, False, error=type(exc).__name__, trace=tuple(trace))
    finally:
        if tracing:
            sys.settrace(previous)
    passed = type(actual) is type(probe.expected) and actual == probe.expected
    return Check(probe, passed, actual=actual, trace=tuple(trace))


def evaluate(source: str, probes: tuple[Probe, ...], *, tracing: bool = False) -> list[Check]:
    """Run only lab-owned modules and return explicit, reproducible test results."""
    namespace: dict = {'__name__': '__kolos_repair_fixture__'}
    exec(compile(source, FILENAME, 'exec', dont_inherit=True), namespace)
    return [_check(namespace, probe, tracing) for probe in probes]
