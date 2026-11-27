"""Generate graph families before embedding them into independently taught UIs."""
from __future__ import annotations

import random

FAMILIES = ('chain', 'branches', 'equal_diamond', 'cycles', 'dense', 'disconnected')


def graph(family: str, rng: random.Random) -> tuple[int, list[tuple[int, int, float]], int, int]:
    """Return vertex count, directed weighted edges and two distinct goal vertices."""
    if family not in FAMILIES:
        raise ValueError('Unknown topology family: ' + family)
    n = rng.randint(9, 13)
    if family == 'cycles':
        n = rng.randint(9, 10)
    elif family == 'dense':
        n = rng.randint(6, 8)
    if family == 'equal_diamond':
        n = 9
        pairs = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (4, 5),
                 (5, 6), (6, 7), (7, 8), (8, 0)]
    elif family == 'branches':
        pairs = [(0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 5)]
        pairs += [(i, i + 1) for i in range(5, n - 1)] + [(n - 1, 0)]
    elif family == 'disconnected':
        cut = n // 2
        pairs = [(i, i + 1) for i in range(n - 1) if i != cut - 1]
        pairs += [(cut - 1, 0), (n - 1, cut)]
    else:
        pairs = [(i, i + 1) for i in range(n - 1)]
        if family != 'chain':
            pairs.append((n - 1, 0))
        if family in ('cycles', 'dense'):
            pairs += [(i, (i - 1) % n) for i in range(1, n)] + [(0, 2)]
        if family == 'dense':
            extra = [(i, j) for i in range(1, n) for j in range(n)
                     if i != j and (i, j) not in pairs]
            rng.shuffle(extra)
            pairs += extra[:20 - len(set(pairs))]
    pairs = sorted(set(pairs))
    edges = [(a, b, .9 if family == 'equal_diamond' else rng.uniform(.84, .98)) for a, b in pairs]
    return n, edges, n - 1, (n // 2 if family != 'disconnected' else n - 2)
