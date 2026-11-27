"""Paired adaptation outcomes and measured usage, without invented human labor costs."""
from __future__ import annotations

from ..cluster_replay.report import summarize


def build(data: dict) -> dict:
    """Separate changed restorations from the unchanged exclusion and retained v1 tasks."""
    groups = {}
    for phase in data['protocol']['phases']:
        groups[phase] = {}
        for selector in data['protocol']['selectors']:
            rows = [r for r in data['rows'] if r['phase'] == phase and r['selector'] == selector]
            restores = [r for r in rows if r['variant'] == 'clean' and r['restoration']]
            excludes = [r for r in rows if r['variant'] == 'clean' and not r['restoration']]
            groups[phase][selector] = dict(**summarize(rows),
                restorations_completed=sum(r['completed'] for r in restores), restorations_n=len(restores),
                exclusions_completed=sum(r['completed'] for r in excludes), exclusions_n=len(excludes),
                preview_rejections=sum(r['review_rejections'] for r in rows))
    return dict(phases=groups, adaptation=data['adaptation'], restart=data['restart'], lesion=data['lesion'])


def markdown(data: dict) -> str:
    """Readout uses successful tasks separately from expected blocked outcomes."""
    lines = ['# Offline procedure adaptation', '',
        'A synthetic preview step was added to restorations only; no real advertising changes.', '',
        '| Phase | Controller | Restorations | Exclusion | Correct outcomes | LLM calls | Input/output | Median clean ms |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for phase, groups in data['summary']['phases'].items():
        for selector, r in groups.items():
            lines.append(f'| {phase} | {selector} | {r["restorations_completed"]}/{r["restorations_n"]} | '
                         f'{r["exclusions_completed"]}/{r["exclusions_n"]} | {r["correct_outcomes"]}/{r["n"]} | '
                         f'{r["llm_calls"]} | {r["input_tokens"]}/{r["output_tokens"]} | {r["median_clean_ms"]:.3f} |')
    lines += ['', 'Kolos learned one full revised episode, not an automatic one-step graph repair.',
              'Script changes and skill annotation were supplied by the experiment author; human effort was not timed.',
              'Local semantic contracts are tested, not live browser adaptation or real monetary performance.', '']
    return '\n'.join(lines)
