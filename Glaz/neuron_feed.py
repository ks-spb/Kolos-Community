"""Bounded file telemetry reader. The worker never calls Tk or the engine."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from kolos_states.ipc import atomic_json, read_json
from kolos_states.neuron_projection import project_neurons


class InlineNeuronFeed:
    def __init__(self, directory, session):
        self.directory = Path(directory); self.session = session
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='inline-neurons')
        self.future = None; self.sequence = 0; self.previous = None
        self.closed = False; self.enabled = False; self.error = ''; self.generation = 0

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        atomic_json(self.directory/'neuron-inline-watch.json', dict(session=self.session, enabled=self.enabled, stamp=time.time()))

    def reset(self):
        self.generation += 1; self.previous = None
        files = self._files(); self.sequence = max((int(p.stem) for p in files), default=0)

    def _files(self):
        return sorted(p for p in (self.directory/'neuron-frames').glob('*.json') if p.stem.isdigit())

    def _read(self, after, previous, generation):
        files = [p for p in self._files() if int(p.stem) > after]
        if not files: return None
        # Latest-state display does not queue a slow UI behind the physical world.
        for path in reversed(files):
            raw = read_json(path)
            if not raw or raw.get('session') != self.session or not isinstance(raw.get('model'), dict): continue
            seq = int(path.stem)
            consecutive = seq == after + 1
            frame = project_neurons(raw['model'], raw.get('event'), previous if consecutive else None)
            return dict(generation=generation, sequence=seq, skipped=max(0, seq-after-1),
                        frame=frame, model=raw['model'], captured_at=raw['captured_at'])
        return None

    def poll(self):
        """Nonblocking: collect one completed read and schedule at most one next."""
        if self.closed or not self.enabled: return None
        result = None
        if self.future is not None and self.future.done():
            try:
                value = self.future.result()
                if value and value['generation'] == self.generation:
                    self.sequence = value['sequence']; self.previous = value.pop('model'); result = value; self.error = ''
            except Exception as exc: self.error = str(exc)[:240]
            self.future = None
        if self.future is None:
            self.future = self.executor.submit(self._read, self.sequence, self.previous, self.generation)
        return result

    def close(self):
        if self.closed: return
        self.closed = True; self.set_enabled(False)
        self.executor.shutdown(wait=False, cancel_futures=True)
