"""Summaries keep success, justified refusal, missing interventions and cost distinct."""
from __future__ import annotations

import random
import statistics


def summarize(rows: list[dict]) -> dict:
    """Include failures in latency medians; do not count refusal as task completion."""
    reachable = [r for r in rows if r['reachable']]
    changed = [r for r in rows if r['changed']]
    statuses = {s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})}
    return dict(n=len(rows), reachable=len(reachable), success=sum(r['success'] for r in rows),
                correct=sum(r['correct'] for r in rows), delivered=len(changed),
                delivered_success=sum(r['success'] for r in changed),
                false_success=sum(r['false_success'] for r in rows),
                failed_effects=sum(r['failed_effects'] for r in rows),
                off_goal_after_change=sum(r['off_goal_after_change'] for r in rows),
                memory_changed=sum(r['memory_before'] != r['memory_after'] for r in rows), statuses=statuses,
                median_ticks=statistics.median(r['host_ticks'] for r in rows),
                median_route_ms=statistics.median(r['route_ns'] / 1e6 for r in rows),
                median_total_ms=statistics.median(r['elapsed_ns'] / 1e6 for r in rows),
                median_response_ticks=statistics.median(r['response_ticks'] for r in changed) if changed else None,
                median_cache_builds=statistics.median(r['builds'] for r in rows))


def _paired(rows: list[dict], family: str, left: str, right: str) -> dict:
    """Bootstrap paired graph-seed means, preserving within-graph scenario dependence."""
    selected = [r for r in rows if r['family'] == family]
    differences = []
    for seed in sorted({r['seed'] for r in selected}):
        a = [r for r in selected if r['seed'] == seed and r['selector'] == left]
        b = [r for r in selected if r['seed'] == seed and r['selector'] == right]
        differences.append(statistics.mean(r['correct'] for r in a) - statistics.mean(r['correct'] for r in b))
    rng = random.Random(913)
    samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
    return dict(left=left, right=right, graphs=len(differences), mean_correct_difference=statistics.mean(differences),
                graph_bootstrap_95=[samples[50], samples[1949]])


def build_summary(rows: list[dict]) -> dict:
    """Expose every preregistered cell, plus paired correctness contrasts per family."""
    families = sorted({r['family'] for r in rows})
    selectors = sorted({r['selector'] for r in rows})
    scenarios = sorted({r['scenario'] for r in rows})
    groups = {f'{f}/{s}/{c}': summarize([r for r in rows if (r['family'], r['selector'], r['scenario']) == (f, s, c)])
              for f in families for s in selectors for c in scenarios}
    totals = {s: summarize([r for r in rows if r['selector'] == s]) for s in selectors}
    contrasts = {f + '/' + s: _paired(rows, f, s, 'dijkstra_cached')
                 for f in families for s in selectors if s != 'dijkstra_cached'}
    return dict(totals=totals, groups=groups, contrasts=contrasts)


def markdown(summary: dict) -> str:
    """Render all cell outcomes with denominators and unsuccessful cases visible."""
    lines = ['# Topology and goal-change benchmark', '',
             '| Family / selector / scenario | Correct | Reached goal / reachable | Changed | Statuses | Route ms | Total ms |',
             '|---|---:|---:|---:|---|---:|---:|']
    for name, r in summary['groups'].items():
        lines.append(f"| {name} | {r['correct']}/{r['n']} | {r['success']}/{r['reachable']} | {r['delivered']} | "
                     f"{r['statuses']} | {r['median_route_ms']:.3f} | {r['median_total_ms']:.3f} |")
    return '\n'.join(lines) + '\n'
