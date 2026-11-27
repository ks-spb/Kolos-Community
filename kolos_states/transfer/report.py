"""Descriptive paired benchmark summaries; no population-wide reliability claims."""
from __future__ import annotations

import random
import statistics


def summarize(rows: list[dict]) -> dict:
    """Aggregate success, erroneous effects and timing without discarding failures."""
    if not rows:
        return dict(n=0)
    return dict(n=len(rows), success=sum(r['success'] for r in rows),
                false_success=sum(r['false_success'] for r in rows),
                bad_keys=sum(r['bad_keys'] for r in rows), wrong_fast=sum(r['wrong_fast'] for r in rows),
                memory_changed=sum(r['memory_before'] != r['memory_after'] for r in rows),
                median_ticks=statistics.median(r['ticks'] for r in rows),
                median_route_ms=statistics.median(r['route_ns'] / 1e6 for r in rows),
                median_elapsed_ms=statistics.median(r['elapsed_ns'] / 1e6 for r in rows),
                median_actions=statistics.median(len(r['actions']) for r in rows))


def paired_interval(left: list[dict], right: list[dict], metric: str) -> dict:
    """Bootstrap mean differences by world, keeping all within-world trials together."""
    def means(rows: list[dict]) -> dict:
        """Compute per-world means; repeated trials are not independent samples."""
        seeds = {r['seed'] for r in rows}
        return {seed: statistics.mean(r[metric] for r in rows if r['seed'] == seed) for seed in seeds}

    a, b = means(left), means(right)
    if a.keys() != b.keys() or not a:
        raise ValueError('Paired worlds required')
    differences = [a[seed] - b[seed] for seed in sorted(a)]
    rng = random.Random(731)
    samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
    return dict(metric=metric, mean_left_minus_right=statistics.mean(differences),
                world_bootstrap_95=[samples[50], samples[1949]], worlds=len(differences))


def build_summary(data: dict) -> dict:
    """Report each arm and the preregistered contrasts, including negative results."""
    groups = {key: summarize(rows) for key, rows in data['groups'].items()}
    contrasts = {}
    for selector in ('native', 'planner'):
        contrasts[selector + '_plasticity'] = paired_interval(
            data['groups'][selector + '_post_on'], data['groups'][selector + '_post_off'], 'wrong_fast')
    contrasts['planner_vs_native_success'] = paired_interval(
        data['groups']['planner_transfer'], data['groups']['native_transfer'], 'success')
    contrasts['planner_vs_native_ticks'] = paired_interval(
        data['groups']['planner_transfer'], data['groups']['native_transfer'], 'ticks')
    if 'early_post_from_native' in data['groups']:
        contrasts['early_vs_native_same_memory_errors'] = paired_interval(
            data['groups']['early_post_from_native'], data['groups']['native_post_on'], 'wrong_fast')
    restarts = data['restarts']
    return dict(groups=groups, contrasts=contrasts,
                restarts=dict(total=len(restarts), different_pid=all(r['different_pid'] for r in restarts),
                              transient_clean=all(r['transient_clean'] for r in restarts),
                              graph_equal=all(r['graph_equal'] for r in restarts)),
                retention=dict(passed=sum(r['retention']['passed'] for r in restarts),
                               total=sum(r['retention']['total'] for r in restarts)))


def markdown(data: dict) -> str:
    """Create a durable, inspectable result table with the scope visible."""
    summary = data['summary']
    lines = ['# Transfer benchmark results', '',
             'Scope: symbolic simulator; one topology family, randomized IDs/layout/teaching order. No live desktop or LLM competitors.', '',
             '| Arm | Success | False success | Wrong fast | Median ticks | Median selector ms | Median total ms |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for name, group in summary['groups'].items():
        lines.append(f"| {name} | {group['success']}/{group['n']} | {group['false_success']} | {group['wrong_fast']} | "
                     f"{group['median_ticks']} | {group['median_route_ms']:.3f} | {group['median_elapsed_ms']:.3f} |")
    lines.extend(['', 'Restart validation: ' + str(summary['restarts']),
                  'Original lessons retained: ' + str(summary['retention']), '',
                  'Paired contrasts (bootstrap over worlds, descriptive for this family):', ''])
    lines.extend(f'- {key}: {value}' for key, value in summary['contrasts'].items())
    lines.extend(['', 'Timing includes Python diagnostic instrumentation and is not a production throughput estimate.',
                  'A blocked lesion trial is expected; success rates there are not acceptance targets.', ''])
    return '\n'.join(lines)
