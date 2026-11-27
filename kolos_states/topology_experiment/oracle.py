"""Independent environment oracle; never passed to route selectors."""
from __future__ import annotations

import heapq
import math

from .world import TopologyLab


def costs(lab: TopologyLab, target: int) -> dict[int, float]:
    """Compute true weighted reachability for scoring, using private environment edges."""
    incoming: dict[int, list] = {}
    for a, b, weight in lab.edges:
        incoming.setdefault(b, []).append((a, -math.log(.9 * weight)))
    result = {target: 0.0}
    queue = [(0.0, target)]
    while queue:
        value, vertex = heapq.heappop(queue)
        if value > result[vertex]:
            continue
        for source, edge in incoming.get(vertex, []):
            candidate = value + edge
            if candidate < result.get(source, math.inf):
                result[source] = candidate
                heapq.heappush(queue, (candidate, source))
    return result


def click_regret(lab: TopologyLab, target: int, action: dict) -> float:
    """Count goal-inconsistent edges without penalizing valid equal-cost alternatives."""
    if action['kind'] != 'click':
        return 0.0
    source, destination, weight = lab.objects[action['object']]
    distance = costs(lab, target)
    if source not in distance or destination not in distance:
        return math.inf
    return max(0.0, -math.log(.9 * weight) + distance[destination] - distance[source])
