"""Atomic, session-scoped IPC. No reuse of geometry-only cached observations."""
from __future__ import annotations
import json
import os
import time
import uuid
from pathlib import Path

MAX_BYTES = 4_000_000
WINDOWS_REPLACE_TIMEOUT = .5
MAX_OBSERVATION_AGE = 3.0


class AtomicReplaceBlocked(PermissionError):
    """Windows still prevents atomic replacement after the bounded retries."""


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        # Windows readers can briefly prevent replacement of the destination.
        # Keep the old complete JSON visible until the reader releases it.
        deadline = time.monotonic() + WINDOWS_REPLACE_TIMEOUT
        while True:
            try:
                os.replace(tmp, path)
                break
            except PermissionError as exc:
                if os.name != 'nt' or getattr(exc, 'winerror', None) not in (5, 32, 33):
                    raise
                if time.monotonic() >= deadline:
                    raise AtomicReplaceBlocked(exc.errno, exc.strerror, exc.filename,
                                               exc.winerror, exc.filename2) from exc
                time.sleep(.01)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path):
    try:
        if path.stat().st_size > MAX_BYTES:return None
        with path.open(encoding='utf-8') as f:return json.load(f)
    except (OSError, ValueError, UnicodeError):return None


class ScanClient:
    def __init__(self, path: Path, session: str, *, stop=None, timeout=8.0):
        self.path, self.session, self.stop, self.timeout = path, session, stop, timeout

    def request(self, *, after=0.0, visual_requests=None, mode=None) -> dict:
        """Refresh expired evidence within one deadline, without resending any input."""
        if mode not in (None, 'frame-only'):
            raise ValueError('Неизвестный режим наблюдения')
        end=time.monotonic()+self.timeout
        payload = self._send_request(after, visual_requests, mode); expired = False
        while time.monotonic()<end:
            self._check_stop()
            r=read_json(self.path/'observation.json')
            self._check_stop()
            if r and r.get('session')==self.session and r.get('request')==payload['id']:
                if r.get('error') and not r.get('retryable'):raise RuntimeError(r['error'])
                if r.get('complete') and r.get('mode') != mode:
                    raise RuntimeError('Glaz вернул другой режим наблюдения. Перезапустите Glaz.')
                stamp=r.get('captured_at',0)
                age = time.time()-stamp
                if stamp >= payload['after'] and 0 <= age <= MAX_OBSERVATION_AGE and r.get('complete'):
                    return r
                if r.get('retryable') or (r.get('complete') and stamp >= payload['after'] and age > MAX_OBSERVATION_AGE):
                    expired = True
                    if time.monotonic() >= end:break
                    payload = self._send_request(after, visual_requests, mode)
            time.sleep(.03)
        if expired:
            raise TimeoutError('Glaz отвечает, но распознанные кадры устаревают до получения. Управление остановлено.')
        raise TimeoutError('Нет свежего полного наблюдения Glaz. Включите захват нужного монитора.')

    def _send_request(self, after: float, visual_requests: list | None, mode=None) -> dict:
        """A new nonce asks the bridge to compute another post-request observation."""
        self._check_stop(); issued = time.time()
        payload = dict(session=self.session, id=uuid.uuid4().hex, issued=issued, after=max(after, issued))
        if mode:
            payload['mode'] = mode
        elif visual_requests:
            payload['visual_requests'] = visual_requests
        atomic_json(self.path/'request.json', payload)
        return payload

    def _check_stop(self) -> None:
        """Observation retries must yield to the same emergency stop as input."""
        if self.stop and self.stop.is_set():raise InterruptedError('Аварийная остановка')
