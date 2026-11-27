"""Run the frozen synthesis corpus with shared tests and an optional live Codex comparator."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
from time import monotonic
from uuid import uuid4

from ...core import StateEngine
from ...ipc import atomic_json
from ...storage import Store
from .corpus import HELD_OUT
from .judge import GROUP_ITERATION, PROMPT_RULES
from .solver import check, finish, solve, train
from .spec import Task

BUDGET = 8
SECONDS = 120
OUTPUT = Path('tests/desktop-output/programming-lab/synthesis')
SCHEMA = {'type': 'object', 'properties': {'source': {'type': 'string'}},
          'required': ['source'], 'additionalProperties': False}


class Codex:
    """Use isolated Codex turns and pass only each bundled task's open examples."""

    def __init__(self, path: Path, model: str, *, compose: bool = False) -> None:
        self.exe = shutil.which('codex')
        self.model = model
        self.path = path
        self.compose = compose
        self.schema = path / 'codex-schema.json'
        atomic_json(self.schema, SCHEMA)
        self.version = self._version()

    def _version(self) -> str | None:
        """Record the installed CLI without echoing environment or auth state."""
        if self.exe is None:
            return None
        try:
            result = subprocess.run([self.exe, '--version'], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _call(self, cwd: Path, prompt: str, timeout: float) -> tuple[str | None, dict]:
        """Read the final JSONL answer and record usage and tool policy violations."""
        if self.exe is None:
            return None, dict(failure='codex_not_found')
        command = [self.exe, 'exec', '--ephemeral', '--ignore-user-config', '--skip-git-repo-check',
                   '--sandbox', 'read-only', '-C', str(cwd), '--model', self.model,
                   '--output-schema', str(self.schema), '--json', '-']
        try:
            run = subprocess.run(command, input=prompt, text=True, encoding='utf-8', errors='replace',
                                 capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, dict(failure='time_limit')
        except OSError:
            return None, dict(failure='launch_failed')
        if run.returncode != 0:
            error = (run.stderr + run.stdout).lower()
            if 'credit' in error or 'quota' in error or 'rate limit' in error:
                reason = 'quota_or_rate_limit'
            elif any(s in error for s in ('access is denied', 'отказано в доступе', 'permission denied')):
                reason = 'runtime_access_denied'
            elif 'model' in error and any(s in error for s in ('not found', 'not supported', 'does not exist')):
                reason = 'model_unavailable'
            else:
                reason = 'codex_exit_error'
            return None, dict(failure=reason, exit_code=run.returncode)
        return _reply(run.stdout)

    def solve(self, task: Task) -> dict:
        """Iterate on public failures only, using the same final judge as Kolos."""
        cwd = self.path / task.function
        cwd.mkdir()
        start = monotonic()
        attempts = []
        for _ in range(BUDGET):
            remaining = SECONDS - (monotonic() - start)
            if remaining <= 0:
                return dict(status='time_limit', attempts=attempts, source=None)
            source, evidence = self._call(cwd, _prompt(task, attempts, compose=self.compose), remaining)
            if source is None and evidence.get('failure') != 'invalid_reply':
                return dict(status='unavailable' if evidence.get('failure') != 'time_limit' else 'time_limit',
                            attempts=attempts, source=None, infrastructure=evidence)
            candidate = source or ''
            open_result = check(task, candidate)
            attempts.append(dict(source=candidate, feedback=asdict(open_result), codex=evidence))
            if open_result.passed:
                return finish(task, candidate, attempts)
        return dict(status='no_solution', attempts=attempts, source=None)


def _reply(stdout: str) -> tuple[str | None, dict]:
    """Extract a source only from a completed turn with no external tool action."""
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.startswith('{')]
    except ValueError:
        return None, dict(failure='invalid_reply')
    items = [event['item'] for event in events if event.get('type') == 'item.completed']
    if any(item.get('type') not in ('agent_message', 'reasoning', 'plan') for item in items):
        return None, dict(failure='tool_used')
    if not any(event.get('type') == 'turn.completed' for event in events):
        return None, dict(failure='invalid_reply')
    reply = next((item['text'] for item in reversed(items) if item.get('type') == 'agent_message'), None)
    usage = next((event.get('usage') for event in reversed(events) if event.get('type') == 'turn.completed'), None)
    try:
        payload = json.loads(reply or '')
        source = payload['source']
    except (ValueError, KeyError, TypeError):
        return None, dict(failure='invalid_reply', usage=usage)
    return (source, dict(usage=usage)) if isinstance(source, str) else (None, dict(failure='invalid_reply', usage=usage))


def _prompt(task: Task, attempts: list[dict], *, compose: bool = False) -> str:
    """Encode a task without its private checks or source files."""
    public = dict(function=task.function, parameter=task.parameter, examples=[asdict(e) for e in task.examples])
    prior = [{k: row[k] for k in ('source', 'feedback')} for row in attempts[-2:]]
    rules = PROMPT_RULES + (GROUP_ITERATION if compose else '')
    return ('Infer the function from the supplied examples. Do not use any tools or access files. '
            'Return a JSON object with the source string. ' + rules + '\n' +
            json.dumps(dict(task=public, prior_attempts=prior), ensure_ascii=True))


def _reported(result: dict, started: float, folder: Path, label: str) -> dict:
    """Save verified source separately and account for wall time in the report."""
    if result['source'] is not None:
        (folder / f'{label}.py').write_text(result['source'], encoding='utf-8')
    result['seconds'] = round(monotonic() - started, 4)
    return result


def _summary(rows: dict[str, dict], label: str) -> dict:
    """Separate infrastructure failures from counted attempts and correctness."""
    results = [row[label] for row in rows.values()]
    summary = dict(total=len(results), solved=sum(row['status'] == 'solved' for row in results),
                   unavailable=sum(row['status'] == 'unavailable' for row in results),
                   time_limits=sum(row['status'] == 'time_limit' for row in results),
                   attempts=sum(len(row['attempts']) for row in results),
                   total_seconds=round(sum(row['seconds'] for row in results), 3))
    screened = [row['screening'] for row in results if 'screening' in row]
    if screened:
        summary['screening'] = {key: sum(row[key] for row in screened) for key in screened[0]}
    return summary


def _measure(folder: Path, learned: StateEngine, tasks: tuple[Task, ...], codex: Codex | None, *,
             compose: bool) -> dict[str, dict]:
    """Use the same tasks, budgets, and independent evaluator for all participants."""
    rows = {task.function: {} for task in tasks}
    for label, graph in (('kolos', learned), ('empty_graph', StateEngine())):
        for task in tasks:
            task_folder = folder / 'results' / task.function
            task_folder.mkdir(parents=True, exist_ok=True)
            start = monotonic()
            result = solve(task, graph, BUDGET, start + SECONDS, compose=compose)
            rows[task.function][label] = _reported(result, start, task_folder, label)
    if codex is not None:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for name, result in pool.map(lambda task: _gpt_trial(codex, folder, task), tasks):
                rows[name]['gpt_codex'] = result
    return rows


def run(output: Path, model: str | None, *, compose: bool = False) -> tuple[Path, dict]:
    """Persist and reload experience before evaluating the predeclared held-out split."""
    folder = output.resolve() / f'run-{uuid4().hex}'
    folder.mkdir(parents=True)
    controls = ()
    if compose:
        from .group_corpus import CONTROLS, LESSONS, ORDERED_TASKS
        primary, controls = ORDERED_TASKS, CONTROLS
        taught, counts = train(LESSONS)
    else:
        primary = HELD_OUT
        taught, counts = train()
    store = Store(folder / 'memory')
    try:
        store.save(taught)
        learned = store.load()
    finally:
        store.close()
    codex = Codex(folder, model, compose=compose) if model else None
    rows = _measure(folder, learned, primary + controls, codex, compose=compose)
    labels = ('kolos', 'empty_graph', 'gpt_codex') if codex else ('kolos', 'empty_graph')
    targets = {task.function: rows[task.function] for task in primary}
    report = dict(schema='kolos-synthesis/1', budget=BUDGET, seconds_per_task=SECONDS,
                  codex=dict(model=codex.model, cli=codex.version) if codex else None,
                  summary={label: _summary(targets, label) for label in labels}, teaching=counts, tasks=rows)
    if compose:
        _composition_report(report, primary, controls, labels)
    atomic_json(folder / 'report.json', report)
    return folder, report


def _composition_report(report: dict, primary: tuple[Task, ...], controls: tuple[Task, ...],
                        labels: tuple[str, ...]) -> None:
    """Certify lack of an original-grammar solution and account for order controls."""
    from .group_corpus import LESSONS, baseline_orders

    proof = {task.function: baseline_orders(task) for task in primary + controls}
    control_rows = {task.function: report['tasks'][task.function] for task in controls}
    report.update(schema='kolos-synthesis-composition/1',
                  baseline_orders=proof,
                  proved_after_required=sum(not proof[task.function] for task in primary),
                  teaching_tasks=[task.function for task in LESSONS],
                  controls={label: _summary(control_rows, label) for label in labels})


def _gpt_trial(codex: Codex, path: Path, task: Task) -> tuple[str, dict]:
    """Run one model task and record results only in its own output folder."""
    start = monotonic()
    return task.function, _reported(codex.solve(task), start, path / 'results' / task.function, 'gpt_codex')


def main(argv: list[str]) -> int:
    """The external benchmark is opt-in and accepts a pinned model name."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab synthesis-benchmark')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--with-gpt', action='store_true')
    parser.add_argument('--gpt-model', default='gpt-6.2-sol')
    parser.add_argument('--compose', action='store_true', help='use the held-out group-order benchmark')
    args = parser.parse_args(argv)
    output = args.output or (OUTPUT / 'compose' if args.compose else OUTPUT)
    folder, report = run(output, args.gpt_model if args.with_gpt else None, compose=args.compose)
    result = dict(summary=report['summary'], codex=report['codex'], report=str(folder / 'report.json'))
    if args.compose:
        result.update(controls=report['controls'], proved_after_required=report['proved_after_required'])
    print(json.dumps(result))
    infrastructure_failed = any(v['unavailable'] for v in (*report['summary'].values(), *report.get('controls', {}).values()))
    invalid_corpus = args.compose and report['proved_after_required'] != report['summary']['kolos']['total']
    return int(infrastructure_failed or invalid_corpus)
