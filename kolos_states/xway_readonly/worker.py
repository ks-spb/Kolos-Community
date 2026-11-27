"""JSON-lines child process: kernel decisions and evidence, with network denied."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
from datetime import datetime, timezone

from ..episode_browser import BrowserEpisodeBridge
from ..protocol import persistent_graph, require
from ..storage import Store
from .protocol import QUERIES, REPORT_FIELDS, authorize, snapshot, validate_task

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'tests' / 'desktop-output'


def denied(*_args: object, **_kwargs: object) -> None:
    """This process can neither call a model nor contact XWAY directly."""
    raise PermissionError('Network denied in XWAY kernel worker')


def digest(value: object) -> str:
    """Hash the frozen graph and command catalogue without activation currents."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


class Worker:
    """Keep one actual kernel alive; never implement a fallback action sequence."""

    def __init__(self, output: Path) -> None:
        self.output = output.resolve()
        require(self.output.is_relative_to(OUTPUT.resolve()), 'Output outside test workspace')
        self.output.mkdir(parents=True, exist_ok=True)
        self.bridge = BrowserEpisodeBridge()
        self.task: dict = {}
        self.stage = 'search'
        self.sequence = 0
        self.executed: set[str] = set()
        self.report_path = self.output / 'report.json'
        self.report_path.write_text(json.dumps(dict(sku='', wb_id='', budget='')), encoding='utf-8')

    def evidence(self, event: str, value: dict) -> None:
        """Append attributable events, including failures, with a hash chain."""
        self.sequence += 1
        payload = dict(sequence=self.sequence, utc=datetime.now(timezone.utc).isoformat(),
                       actor='kolos-kernel-worker', pid=os.getpid(), event=event, **value)
        payload['previous'] = getattr(self, 'previous', '')
        self.previous = payload['sha256'] = digest(payload)
        with (self.output / 'kernel.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + '\n')

    def signature(self) -> str:
        """Exclude transient run state from the inference immutability check."""
        model = self.bridge.engine.model
        return digest(dict(memory=persistent_graph(model['memory']), commands=model.get('episodeCommands', [])))

    def observation(self, raw: dict) -> dict:
        """Always read the current report from disk instead of expected values."""
        report = json.loads(self.report_path.read_text(encoding='utf-8'))
        return snapshot(raw, self.task, report, self.stage)

    def load(self, request: dict) -> dict:
        """Load copied memory, or remove a learned connection without changing the motor."""
        validate_task(request['task'])
        self.task = request['task']
        mode = request.get('mode', 'trained')
        require(mode in ('trained', 'empty', 'cut'), 'Unknown memory condition')
        if mode != 'empty':
            source = Path(request['memory']).resolve()
            require(source.is_relative_to(OUTPUT.resolve()), 'Memory outside evidence workspace')
            payload = json.loads(source.read_text(encoding='utf-8'))
            copied = self.output / 'memory'
            copied.mkdir()
            (copied / 'memory.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            store = Store(copied)
            try:
                self.bridge.engine = store.load()
            finally:
                store.close()
        removed = self.cut() if mode == 'cut' else None
        self.frozen = self.signature()
        return dict(pid=os.getpid(), memory_sha256=self.frozen, mode=mode, removed_edge=removed,
                    commands=len(self.bridge.engine.model.get('episodeCommands', [])), network='denied')

    def cut(self) -> dict:
        """Disconnect the search's first WRITE, leaving its first READ executable."""
        engine = self.bridge.engine
        command = next(c for c in engine.model['episodeCommands'] if c['query'] == QUERIES['search'])
        first = engine.node(engine.edges(command['node'], 'episode_next')[0]['to'])
        edge = engine.edges(first['id'], 'episode_next')[0]
        require(engine.node(edge['to'])['operation'] == 'write', 'Unexpected search topology')
        edge['weight'] = 0
        return dict(id=edge['id'], source=edge['from'], target=edge['to'])

    def pending(self, raw: dict) -> dict:
        """Return a kernel request only after its independent motor authorization."""
        request = self.bridge.pending
        if request is None:
            return dict(status=self.bridge.engine.model['status'], message=self.bridge.engine.model['message'])
        target = authorize(request['action'], self.observation(raw), self.task)
        return dict(id=request['id'], action=request['action'], motor=target,
                    step=request.get('step'), origin='teacher' if self.bridge.record is not None else 'learned-graph')

    def local(self, raw: dict) -> dict:
        """Write only one pending local report value; never retry an uncertain write."""
        request = self.bridge.pending
        require(request is not None and request['id'] not in self.executed, 'No new pending write')
        require(authorize(request['action'], self.observation(raw), self.task) == 'local-report',
                'Not an authorized local report write')
        self.executed.add(request['id'])
        report = json.loads(self.report_path.read_text(encoding='utf-8'))
        report[REPORT_FIELDS[request['action']['descriptor']['name']]] = request['action']['value']
        temporary = self.report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.report_path)
        return dict(written=True)

    def lesson(self, request: dict) -> dict:
        """Teaching is explicit and isolated from subsequent inference runs."""
        op = request['op']
        self.stage = 'read'
        if op == 'teach-start':
            self.bridge.begin_teaching(QUERIES['read'])
        elif op == 'prepare':
            self.bridge.prepare(self.observation(request['dom']), request['kind'],
                                request['role'], request.get('source'))
            return self.pending(request['dom'])
        elif op == 'teach-finish':
            record = self.bridge.finish_teaching()
            (self.output / 'lesson.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            store = Store(self.output / 'trained-memory')
            try:
                store.save(self.bridge.engine)
            finally:
                store.close()
            return dict(memory=str(self.output / 'trained-memory' / 'memory.json'),
                        memory_sha256=self.signature(), steps=len(record['receipts']))
        return dict(ok=True)

    def handle(self, request: dict) -> dict:
        """Dispatch a closed protocol, not code, shell, browser URLs or arbitrary commands."""
        op = request['op']
        if op == 'load':
            result = self.load(request)
        elif op in ('teach-start', 'prepare', 'teach-finish'):
            result = self.lesson(request)
        elif op == 'start':
            require(request['stage'] in QUERIES, 'Unknown stage')
            self.stage = request['stage']
            self.bridge.start(QUERIES[self.stage], self.observation(request['dom']))
            result = dict(started=True)
        elif op == 'next':
            self.bridge.next(self.observation(request['dom']))
            result = self.pending(request['dom'])
        elif op == 'local':
            result = self.local(request['dom'])
        elif op == 'confirm':
            receipt = self.bridge.confirm(self.observation(request['first']), self.observation(request['second']))
            result = dict(confirmed=receipt['id'])
        elif op == 'summary':
            result = dict(memory_sha256=self.signature(), memory_unchanged=self.signature() == self.frozen,
                          status=self.bridge.engine.model['status'], message=self.bridge.engine.model['message'],
                          report=json.loads(self.report_path.read_text(encoding='utf-8')))
        else:
            raise ValueError('Unknown worker operation')
        self.evidence(op, dict(request=request, result=result))
        return result


def respond(worker: Worker, line: str) -> dict:
    """Keep identical checked requests and errors for both local IPC transports."""
    try:
        require(len(line) <= 1_000_000, 'Oversized IPC request')
        return dict(ok=True, result=worker.handle(json.loads(line)))
    except Exception as exc:
        result = dict(ok=False, error=dict(type=type(exc).__name__, message=str(exc)))
        worker.evidence('error', result)
        return result


def serve_files(worker: Worker) -> None:
    """File IPC needs no child-process privileges in the supported browser runtime."""
    directory = worker.output / 'ipc'
    directory.mkdir(exist_ok=True)
    (directory / 'ready.json').write_text(json.dumps(dict(pid=os.getpid())), encoding='utf-8')
    print('Ready: ' + str(directory), flush=True)
    deadline, sequence = time.monotonic() + 600, 1
    while time.monotonic() < deadline and not (directory / 'close.json').exists():
        source = directory / f'in-{sequence}.json'
        if not source.exists():
            time.sleep(.03)
            continue
        result = respond(worker, source.read_text(encoding='utf-8'))
        temporary = directory / f'out-{sequence}.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temporary.replace(directory / f'out-{sequence}.json')
        sequence += 1
    worker.evidence('worker-exit', dict(requests=sequence - 1))


def main() -> None:
    """All output is bounded JSON; stdout never carries UI secrets or model prompts."""
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    worker = Worker(Path(sys.argv[1]))
    if '--files' in sys.argv[2:]:
        serve_files(worker)
    else:
        for line in sys.stdin:
            print(json.dumps(respond(worker, line), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
