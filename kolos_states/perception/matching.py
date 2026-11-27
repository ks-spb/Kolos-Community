"""Bottom-up evidence propagated through learned spatial and assembly links."""
from __future__ import annotations

from ..protocol import clamp
from .types import views, TILE


def _incoming(memory: dict, target: str, kind: str) -> list[dict]:
    """Read synapses rather than reconstructing membership from node IDs."""
    return [e for e in memory['edges'] if e['to'] == target and e['kind'] == kind]


def _fragment(prototype: dict, sample: dict) -> float:
    """Soft intersection-over-union retains spatial order and empty regions."""
    try:
        width = sample['width']; pixels = bytes.fromhex(sample['data'])
        l, t, r, b = prototype['rect']; expected = bytes.fromhex(prototype['data'])
        if width*sample['height'] != len(pixels) or r > width or b > sample['height']:
            return 0.0
        actual = bytes(pixels[y*width+x] for y in range(t, b) for x in range(l, r))
        union = sum(max(a, b) for a, b in zip(expected, actual))
        return sum(min(a, b) for a, b in zip(expected, actual))/union if union else 1.0
    except (KeyError, TypeError, ValueError, IndexError):
        return 0.0


def _part(memory: dict, nodes: dict, part: dict, sample: dict, trace: dict) -> float:
    """A missing or contradictory informative fragment cannot be averaged away."""
    links = _incoming(memory, part['id'], 'visual_contains'); values = []
    width, height = sample.get('width', 0), sample.get('height', 0)
    required = {(x, y, min(x+TILE, width), min(y+TILE, height))
                for y in range(0, height, TILE) for x in range(0, width, TILE)}
    if not required or {tuple(nodes[e['from']]['rect']) for e in links} != required:
        return 0.0
    for edge in links:
        feature = nodes[edge['from']]
        signal = _fragment(feature, sample) if sample.get('valid') else 0.0
        trace[feature['id']] = signal
        values.append(min(edge['weight'], signal))
    value = min(values) if values else 0.0
    trace[part['id']] = value
    return value


def _score(memory: dict, nodes: dict, view: dict, sample: dict) -> tuple[float, dict]:
    """All parts and relations belong to this one candidate and learned variant."""
    variant = nodes[view['variant']]; trace = {}; values = []
    parts = _incoming(memory, variant['id'], 'visual_contains')
    if sorted(nodes[e['from']]['role'] for e in parts) != ['icon', 'label']:
        return 0.0, trace
    for edge in parts:
        part = nodes[edge['from']]
        signal = _part(memory, nodes, part, sample.get('parts', {}).get(part['role'], {}), trace)
        values.append(min(edge['weight'], signal))
    relations = _incoming(memory, variant['id'], 'visual_spatial')
    if len(relations) != 1:
        return 0.0, trace
    relation = relations[0]; trace[relation['from']] = 1.0
    values.append(relation['weight'])
    links = [e for e in memory['edges'] if (e['kind'] == 'visual_attention' and
             (e['to'] == view['id'] or e['from'] == view['id'])) or
             (e['kind'] == 'visual_contains' and e['from'] == variant['id'] and e['to'] == view['target'])]
    values.extend(e['weight'] for e in links)
    score = clamp(min(values)) if len(links) == 3 else 0.0
    trace[variant['id']] = score; trace[view['target']] = score
    icon_parts = [p for p in nodes.values() if p['kind'] == 'visual_part' and p.get('role') == 'icon' and p['id'] in trace]
    if not icon_parts or trace[icon_parts[0]['id']] < .7:
        trace = {variant['id']: score, view['target']: score}
    return score, trace


def evaluate(memory: dict, target: str, evidence: dict) -> dict:
    """Score every instance across all learned fine views, without goal current."""
    requests = views(memory, target, fine_only=True)
    samples = evidence.get('views', {})
    if not evidence.get('complete') or not requests or any(v['id'] not in samples for v in requests):
        return dict(complete=False, candidates=[])
    nodes = {n['id']: n for n in memory['nodes']}; instances = {}
    for view in requests:
        for sample in samples[view['id']]:
            score, trace = _score(memory, nodes, view, sample)
            key = tuple(sample['bbox'])
            candidate = dict(id=str(key), bbox=list(key), a=score, sensory=score, trace=trace,
                             view=view['id'], variant=view['variant'], label_bbox=sample['label_bbox'])
            if key not in instances or score > instances[key]['a']:
                instances[key] = candidate
    return dict(complete=True, candidates=list(instances.values()))


def winner(candidates: list, cfg: dict) -> dict | None:
    """Ties never use IDs, old coordinates, cursor position or list ordering."""
    ranked = sorted(candidates, key=lambda c: -c['a'])
    if not ranked or ranked[0]['a'] < cfg['threshold']:
        return None
    if len(ranked) > 1 and ranked[0]['a']-ranked[1]['a'] < cfg['margin']:
        return None
    return ranked[0]


def binding(memory: dict, target: str, observed: dict, cfg: dict) -> dict | None:
    """Independent, current sensory verification used at the motor boundary."""
    result = evaluate(memory, target, observed.get('perception_samples', {}))
    chosen = winner(result['candidates'], cfg) if result['complete'] else None
    if chosen is None:
        return None
    return dict(target=target, bbox=chosen['bbox'], score=chosen['a'], view=chosen['view'],
                frame=observed.get('version'), session=observed.get('session'),
                captured_at=observed.get('captured_at'), label_bbox=chosen['label_bbox'])
