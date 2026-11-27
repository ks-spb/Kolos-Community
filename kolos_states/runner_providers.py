"""Explicit, tool-free providers for compiling a lesson into JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from .wb_promotion_codex import Codex, PROCESS_FLAGS, USAGE_KEYS, strict_json

PROVIDERS = ('codex', 'claude')


def find_cli(provider: str) -> Path:
    command = provider + '.exe' if os.name == 'nt' else provider
    installed = shutil.which(command)
    if installed:
        return Path(installed).resolve()
    if os.name == 'nt' and provider == 'codex' and os.environ.get('LOCALAPPDATA'):
        folder = Path(os.environ['LOCALAPPDATA']) / 'OpenAI' / 'Codex' / 'bin'
        candidates = sorted(folder.glob('*/codex.exe'), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    native = Path.home() / '.local' / 'bin' / command
    if native.is_file():
        return native
    label = 'Codex CLI' if provider == 'codex' else 'Claude Code CLI'
    raise ValueError(f'Установите {label}, войдите в аккаунт и перезапустите Колос.')


def claude_result(stdout: str | None, *, failure: str | None = None, launched: bool = True) -> dict:
    try:
        result = strict_json(stdout or '')
    except ValueError:
        result = None
    if not isinstance(result, dict):
        result = {}
    raw = result.get('usage')
    usage = dict.fromkeys(USAGE_KEYS)
    if isinstance(raw, dict):
        def tokens(name: str) -> int | None:
            value = raw.get(name)
            return value if type(value) is int and value >= 0 else None

        fresh = tokens('input_tokens')
        cache_read = tokens('cache_read_input_tokens')
        cache_write = tokens('cache_creation_input_tokens')
        input_parts = (fresh, cache_read, cache_write)
        usage.update(input_tokens=sum(input_parts) if None not in input_parts else None,
                     output_tokens=tokens('output_tokens'), cached_input_tokens=cache_read)
    answer = result.get('structured_output')
    if (result.get('type') != 'result' or result.get('subtype') != 'success' or result.get('is_error') is not False
            or type(result.get('num_turns')) is not int or result['num_turns'] != 1 or not isinstance(answer, dict)):
        failure = failure or 'Claude Code не вернул один корректный структурированный ответ.'
    if not launched:
        usage = dict.fromkeys(USAGE_KEYS, 0)
    return dict(answer=answer if failure is None else None, usage=usage,
                failure=failure, codex_exec_count=int(launched))


def _claude(exe: Path, model: str | None, scratch: Path, prompt: str, schema: dict) -> dict:
    if any((parent / '.git').exists() for parent in (scratch, *scratch.parents)):
        raise ValueError('Временный каталог Claude Code должен находиться вне репозитория.')
    model_arg = ['--model', model] if model else []
    command = [str(exe), '-p', '--safe-mode', '--restricted', '--tools', '', '--strict-mcp-config',
               '--mcp-config', '{"mcpServers":{}}', '--output-format', 'json', '--max-turns', '1',
               '--no-session-persistence', '--json-schema', json.dumps(schema), *model_arg]
    try:
        run = subprocess.run(command, input=prompt, cwd=scratch, encoding='utf-8', errors='replace',
                             capture_output=True, timeout=120, creationflags=PROCESS_FLAGS)
    except subprocess.TimeoutExpired:
        return claude_result(None, failure='Превышено время урока Claude Code.')
    except OSError:
        return claude_result(None, failure='Не удалось запустить Claude Code.', launched=False)
    failure = 'Claude Code завершился с ошибкой. Проверьте вход и версию CLI.' if run.returncode else None
    return claude_result(run.stdout, failure=failure)


def teach(provider: str, model: str | None, prompt: str, schema: dict) -> dict:
    if model is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', model):
        raise ValueError('Укажите идентификатор модели, например gpt-6.2-sol, или оставьте поле пустым.')
    exe = find_cli(provider)
    with TemporaryDirectory(prefix='kolos-provider-', ignore_cleanup_errors=True) as name:
        scratch = Path(name).resolve()
        if provider == 'codex':
            response = Codex(model, scratch, executable=exe)(prompt, schema)
            if not response['codex_exec_count']:
                response['usage'] = dict.fromkeys(USAGE_KEYS, 0)
            if response['failure']:
                response['failure'] = (f"Codex не завершил урок ({response['failure']}). "
                                       'Проверьте вход в Codex, выбранную модель и доступность CLI.')
            return response
        return _claude(exe, model, scratch, prompt, schema)
