"""Isolated, inference-only worker transport using the already installed Hermes SDK."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from time import perf_counter_ns

from .world import World


def public_input(world: World) -> dict:
    """Remove every business identifier, query, source path and settings fingerprint."""
    observation = world.observe()
    observation['session'] = 'offline-replay'
    context = dict(task=dict(identity=dict(shop_id='demo-shop', nm_id='demo-product', vendor_code='demo-sku'),
                            campaign_id='demo-campaign', query='demo-cluster', excluded=world.case['target']),
                   approval_valid=world.approval, expected_scope='requested-scope',
                   observed_scope='requested-scope' if world.scope == world.observed_scope else 'other-scope',
                   protected_settings='unchanged-demo-settings')
    return dict(context=context, observation=observation)


def launch_command(install: Path) -> list[str]:
    """Read the committed SDK interpreter; never invoke updater/repair or modify profiles."""
    code = ('import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
            'from pm.environments import committed_venv, venv_command, site_packages; '
            'root=Path(sys.argv[1]); '
            'v=committed_venv(root); '
            'print(json.dumps({"command":venv_command(root,v,("-I","-B")),"site":str(site_packages(v))}))')
    raw = subprocess.check_output([sys.executable, '-B', '-c', code, str(install)], text=True, encoding='utf-8')
    runtime = json.loads(raw)
    boot = ('import sys,runpy,site; site.addsitedir(sys.argv[2]); '
            'sys.path.insert(0,sys.argv[1]); runpy.run_path(sys.argv[3],run_name="__main__")')
    return [*runtime['command'], '-c', boot, str(install), runtime['site'],
            str(Path(__file__).with_name('hermes_worker.py').resolve())]


class Model:
    """The model returns JSON data; only the parent local simulator can execute it."""

    def __init__(self, output: Path, install: Path):
        """Keep logs and cwd in the experiment; never resume a working Hermes chat."""
        start = perf_counter_ns()
        self.errors = (output / 'model-runtime.log').open('w', encoding='utf-8')
        self.process = subprocess.Popen(launch_command(install), cwd=output.resolve(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        ready = self._receive(90)
        if not ready.get('ready'):
            self.close()
            raise RuntimeError('Inference worker unavailable: ' + str(ready))
        self.model, self.startup_ns = ready['model'], perf_counter_ns() - start
        self.skill = Path(__file__).with_name('skill.md').read_text(encoding='utf-8')

    def _read(self) -> None:
        """Avoid a blocking unbounded readline when a provider stalls."""
        for line in self.process.stdout:
            try:
                self.lines.put(json.loads(line))
            except ValueError:
                continue
        self.lines.put(dict(ok=False, error_type='worker_closed'))

    def _receive(self, seconds: int) -> dict:
        """Only accept bounded local worker responses."""
        try:
            return self.lines.get(timeout=seconds)
        except queue.Empty:
            raise TimeoutError('Model worker deadline') from None

    def plan(self, world: World, trial_id: str) -> dict:
        """Send minimal saved task facts and the common host's current observation."""
        payload = public_input(world)
        request = dict(id=trial_id, messages=[dict(role='system', content=self.skill),
                       dict(role='user', content=json.dumps(payload, ensure_ascii=False))])
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
        self.process.stdin.flush()
        result = self._receive(110)
        if result.get('id') != trial_id:
            raise RuntimeError('Mismatched model response')
        return dict(request=request, response=result)

    def close(self) -> None:
        """Close only this owned inference worker, never an existing Hermes service."""
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
        self.errors.close()
