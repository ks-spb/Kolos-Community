"""Descriptive paired results; no invented prices or model token estimates."""
from __future__ import annotations

import statistics


def summarize(rows: list[dict]) -> dict:
    """Keep clean completion, safe fault outcomes and actual inference usage separate."""
    clean = [r for r in rows if r['variant'] == 'clean']
    measured = [r for r in rows if isinstance(r.get('input_tokens'), int)]
    return dict(n=len(rows), correct_outcomes=sum(r['correct_outcome'] for r in rows),
                clean_completed=sum(r['completed'] and r['status'] == 'complete' for r in clean), clean_n=len(clean),
                false_success=sum(r['false_success'] for r in rows),
                unsafe_attempts=sum(r['unsafe_attempts'] for r in rows),
                repeated_save=sum(r['repeated_save'] for r in rows),
                protocol_errors=sum(r.get('protocol_error', False) for r in rows),
                unavailable=sum(r['status'] == 'unavailable' for r in rows),
                llm_calls=sum(r['llm_calls'] for r in rows), measured_usage_trials=len(measured),
                input_tokens=sum(r['input_tokens'] for r in measured),
                output_tokens=sum(r['output_tokens'] for r in measured),
                cache_read_tokens=sum(r.get('cache_read_tokens', 0) for r in measured),
                median_clean_ms=statistics.median(r['elapsed_ns'] / 1e6 for r in clean),
                median_clean_execution_ms=statistics.median(r['execute_ns'] / 1e6 for r in clean),
                median_clean_operations=statistics.median(len(r['operations']) for r in clean),
                median_clean_input_tokens=statistics.median(r['input_tokens'] for r in clean
                    if isinstance(r.get('input_tokens'), int)) if any(isinstance(r.get('input_tokens'), int) for r in clean) else None)


def build(data: dict) -> dict:
    """Group paired cases and expose each fault rather than hiding safe abstentions."""
    selectors = sorted({r['selector'] for r in data['rows']})
    result = {s: summarize([r for r in data['rows'] if r['selector'] == s]) for s in selectors}
    faults = {v: {s: sum(r['correct_outcome'] for r in data['rows']
                        if r['selector'] == s and r['variant'] == v) for s in selectors}
              for v in data['protocol']['variants']}
    return dict(controllers=result, outcomes_by_variant=faults, teaching=data['teaching'])


def markdown(data: dict) -> str:
    """Save an inspectable readout beside detailed evidence."""
    lines = ['# Offline cluster replay', '',
             'Local reconstruction from saved before/after contracts; no live UI or advertising writes.', '',
             '| Controller | Clean completed | Correct outcomes | False success | LLM calls | Input tokens | Output tokens | Cached input | Median clean ms |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, r in data['summary']['controllers'].items():
        lines.append(f"| {name} | {r['clean_completed']}/{r['clean_n']} | {r['correct_outcomes']}/{r['n']} | "
                     f"{r['false_success']} | {r['llm_calls']} | {r['input_tokens']} | {r['output_tokens']} | "
                     f"{r['cache_read_tokens']} | {r['median_clean_ms']:.3f} |")
    lines += ['', 'Token counts come from the model provider. Cached tokens are included in input, not added again.',
              'No cash savings are inferred: account pricing/subscription limits and engineering labor are not measured.',
              'The model gets an optimized batched skill prompt, not a replay of the full historical manager chat.',
              'Five held-out real operations do not establish reliability on arbitrary XWAY pages.', '']
    return '\n'.join(lines)
