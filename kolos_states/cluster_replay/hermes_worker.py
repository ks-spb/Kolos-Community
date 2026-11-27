"""Inference-only Hermes SDK worker; no agent loop, tools, plugins or business adapters.

The installed provider client handles its own authentication. Credentials never
enter the replay files or stdout. Only whitelisted token counts and model text
are returned; SDK stdout is discarded and raw exceptions are never serialized.
"""
from __future__ import annotations

import contextlib
import io
import importlib
import json
import logging
from pathlib import Path
import site
import sys
import traceback
from time import perf_counter_ns
from urllib.parse import urlparse


def _field(value: object, key: str, default: object = None) -> object:
    """Handle both OpenAI objects and Hermes' normalized usage dictionaries."""
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def infer(client: object, model: str, request: dict) -> dict:
    """Make a single text completion; no executable tool surface is supplied."""
    start = perf_counter_ns()
    with contextlib.redirect_stdout(io.StringIO()):
        result = client.chat.completions.create(model=model, messages=request['messages'],
                    tools=[], temperature=0, max_tokens=1600, timeout=90)
    usage = result.usage
    input_tokens, output_tokens = _field(usage, 'prompt_tokens'), _field(usage, 'completion_tokens')
    details = _field(usage, 'prompt_tokens_details', {})
    cached = _field(usage, 'cache_read_tokens', _field(details, 'cached_tokens', 0))
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ValueError('Provider did not report token usage')
    choice = result.choices[0]
    if choice.message.tool_calls:
        raise ValueError('Unexpected tool call from inference-only model')
    return dict(ok=True, id=request['id'], text=choice.message.content, model=result.model,
                input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cached,
                infer_ns=perf_counter_ns() - start, finish_reason=choice.finish_reason)


def main() -> None:
    """Serve JSONL requests inside the existing Hermes dependency runtime."""
    logging.disable(logging.CRITICAL)
    try:
        site.addsitedir(str(Path(sys.argv[2]).resolve()))
        with contextlib.redirect_stdout(io.StringIO()):
            importlib.import_module('ruamel.yaml')
            from agent.auxiliary_client import resolve_provider_client
            client, model = resolve_provider_client('openai-codex', model='gpt-6.1-sol', api_mode='codex_responses')
        if client is None:
            raise RuntimeError('Configured model client unavailable')
        if urlparse(str(client.base_url)).hostname not in ('chatgpt.com', 'api.openai.com'):
            raise ValueError('Only OpenAI model hosts permitted')
        print(json.dumps(dict(ready=True, model=model)), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            try:
                result = infer(client, model, request)
            except Exception as error:
                result = dict(ok=False, id=request['id'], error_type=type(error).__name__,
                              status_code=getattr(error, 'status_code', None))
            print(json.dumps(result, ensure_ascii=False), flush=True)
        client.close()
    except Exception as error:
        print(json.dumps(dict(ready=False, error_type=type(error).__name__,
                              missing_module=getattr(error, 'name', None),
                              trace=[(f.filename, f.lineno, f.name) for f in traceback.extract_tb(error.__traceback__)])), flush=True)


if __name__ == '__main__':
    main()
