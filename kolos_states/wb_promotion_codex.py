"""One read-only Codex turn on an isolated synthetic input, with usage evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic

from .ipc import atomic_json

FEATURES = ('shell_tool', 'apps', 'plugins', 'hooks', 'memories', 'multi_agent', 'multi_agent_v2')
PROFILE = tuple(flag for name in FEATURES for flag in ('--disable', name)) + (
    '-c', 'project_doc_max_bytes=0', '-c', 'skills.bundled.enabled=false',
    '-c', 'mcp_servers={}', '-c', 'web_search="disabled"',
)
USAGE_KEYS = ('input_tokens', 'output_tokens', 'cached_input_tokens')
ALLOWED_ITEMS = {'agent_message', 'reasoning', 'plan'}
PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


class CodexUnavailable(ValueError):
    pass


def _text(data: str | bytes | None) -> str:
    return data.decode('utf-8', errors='replace') if isinstance(data, bytes) else data or ''


def _pairs(pairs: list) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('Повтор ключа JSON')
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError('Недопустимая числовая константа JSON')


def strict_json(data: str) -> object:
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def turn_result(stdout: str | bytes | None, failure: str | None = None) -> dict:
    """Keep independently usable telemetry even if the answer must be rejected."""
    damaged = unexpected = failed_event = False
    messages = []
    completions = []
    for line in _text(stdout).splitlines():
        if not line.strip():
            continue
        try:
            event = strict_json(line)
        except ValueError:
            damaged = True
            continue
        if not isinstance(event, dict):
            damaged = True
            continue
        kind = event.get('type')
        if kind == 'turn.completed':
            completions.append(event.get('usage'))
        if kind in ('turn.failed', 'error'):
            failed_event = True
        if kind in ('item.started', 'item.updated', 'item.completed'):
            item = event.get('item')
            if not isinstance(item, dict) or item.get('type') not in ALLOWED_ITEMS:
                unexpected = True
            elif kind == 'item.completed' and item['type'] == 'agent_message':
                messages.append(item.get('text'))

    raw = completions[0] if len(completions) == 1 and isinstance(completions[0], dict) else {}
    usage = {key: raw[key] if type(raw.get(key)) is int and raw[key] >= 0 else None
             for key in USAGE_KEYS}
    if (usage['cached_input_tokens'] is not None and usage['input_tokens'] is not None
            and usage['cached_input_tokens'] > usage['input_tokens']):
        usage['cached_input_tokens'] = None
    if messages and isinstance(messages[-1], str):
        try:
            answer = strict_json(messages[-1])
        except ValueError:
            answer = None
    else:
        answer = None
    if unexpected:
        failure = failure or 'codex_tool_event'
    if damaged or failed_event or len(completions) != 1 or not isinstance(answer, dict):
        failure = failure or 'codex_invalid_response'
    return dict(answer=answer if failure is None else None, usage=usage,
                failure=failure, codex_exec_count=1, completed_turns=len(completions))


class Codex:
    def __init__(self, model: str | None, scratch: Path, *, executable: Path | None = None) -> None:
        exe = executable or shutil.which('codex')
        if not exe:
            raise CodexUnavailable('Codex CLI не найден в PATH')
        home = Path.home().resolve()
        if any((parent / '.git').exists() or (parent != home and (parent / '.codex').exists())
               for parent in (scratch, *scratch.parents)):
            raise CodexUnavailable('Временный каталог Codex должен находиться вне репозитория и конфигурации проекта')
        self.exe = str(Path(exe).resolve())
        self.model = model
        self.scratch = scratch
        version = self._inspect('--version')
        settings = self._inspect(*PROFILE, 'features', 'list')
        rows = {parts[0]: parts[-1] for line in settings.splitlines() if (parts := line.split())}
        if not version.startswith('codex-cli ') or any(rows.get(feature) != 'false' for feature in FEATURES):
            raise CodexUnavailable('Не удалось подтвердить ограниченный профиль CLI')
        self.version = version.strip()
        self._inspect('login', 'status')

    def _inspect(self, *args: str) -> str:
        try:
            run = subprocess.run([self.exe, *args], cwd=self.scratch, capture_output=True,
                                 encoding='utf-8', errors='replace', timeout=10, creationflags=PROCESS_FLAGS)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CodexUnavailable('Не удалось проверить установленный Codex CLI') from error
        if run.returncode:
            raise CodexUnavailable('Codex CLI отклонил проверку профиля или входа в аккаунт')
        return run.stdout.strip()

    def __call__(self, prompt: str, schema: dict) -> dict:
        started = monotonic()
        with TemporaryDirectory(dir=self.scratch, ignore_cleanup_errors=True) as name:
            cwd = Path(name)
            schema_path = cwd / 'response-schema.json'
            atomic_json(schema_path, schema)
            model_arg = ['--model', self.model] if self.model else []
            command = [self.exe, 'exec', '--strict-config', '--ephemeral', '--ignore-user-config',
                       '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(cwd),
                       *model_arg, *PROFILE, '--output-schema', str(schema_path), '--json', '-']
            try:
                run = subprocess.run(command, input=prompt, cwd=cwd, encoding='utf-8',
                                     errors='replace', capture_output=True, timeout=120, creationflags=PROCESS_FLAGS)
            except subprocess.TimeoutExpired as error:
                result = turn_result(error.stdout, 'codex_timeout')
            except OSError:
                result = dict(turn_result(None, 'codex_launch_failed'), codex_exec_count=0)
            else:
                result = turn_result(run.stdout, 'codex_exit_error' if run.returncode else None)
                if run.returncode and not result['completed_turns']:
                    error_log = run.stderr.lower()
                    if 'unknown field' in error_log or 'strict' in error_log and 'config' in error_log:
                        result['failure'] = 'codex_config_rejected'
                    elif 'rate limit' in error_log or 'quota' in error_log:
                        result['failure'] = 'codex_quota'
                    elif 'access denied' in error_log or 'os error 5' in error_log:
                        result['failure'] = 'codex_runtime_access_denied'
        return dict(result, seconds=round(monotonic() - started, 3))
