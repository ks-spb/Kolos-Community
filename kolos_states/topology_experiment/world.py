"""Embed opaque graphs as UI observations; teach only individual transitions."""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..core import StateEngine
from ..protocol import clone
from ..simulator import demonstrate, icon_actions, observe
from .topologies import FAMILIES, graph


@dataclass
class TopologyLab:
    """Private environment specification; selectors never receive this object."""

    family: str
    seed: int
    world: dict
    labels: list[str]
    edges: list[tuple[int, int, float]]
    objects: dict[str, tuple[int, int, float]]
    goals: tuple[int, int]
    lessons: list[dict]

    def at(self, vertex: int = 0) -> dict:
        """Create a fresh world at a vertex, without exposing its label as a feature."""
        world = clone(self.world)
        world['surface'] = self.labels[vertex]
        return world

    def goal(self, vertex: int) -> dict:
        """Request a previously observed state through its visible features only."""
        return dict(kind='state', features=observe(self.at(vertex))['features'])


def make_lab(family: str, seed: int) -> TopologyLab:
    """Vary graph size, weights, labels, geometry and independent teaching order."""
    rng = random.Random(seed * 31 + FAMILIES.index(family))
    n, edges, a, b = graph(family, rng)
    labels = ['surface-' + str(x) for x in rng.sample(range(100000, 999999), n)]
    surfaces = {name: dict(field=None, icons=[]) for name in labels}
    objects: dict = {}
    for i, (source, target, weight) in enumerate(edges):
        obj = 'object-' + str(rng.randrange(10000000, 99999999)) + '-' + str(i)
        objects[obj] = (source, target, weight)
        surfaces[labels[source]]['icons'].append(dict(id=obj, click=labels[target]))
    _geometry(surfaces, rng)
    world = dict(surface=labels[0], selected='', focus='', output='', cursor=dict(x=1200, y=900),
                 version=0, effects=[], surfaces=surfaces)
    lab = TopologyLab(family, seed, world, labels, edges, objects, (a, b), [])
    for obj, (source, _, _) in objects.items():
        initial = lab.at(source)
        lab.lessons.append(demonstrate('fragment-' + obj, initial, icon_actions(initial, obj)))
    rng.shuffle(lab.lessons)
    return lab


def _geometry(surfaces: dict, rng: random.Random) -> None:
    """Give every state an inert visible marker and separated actionable icons."""
    for name, surface in surfaces.items():
        surface['icons'].append(dict(id='marker-' + name))
        cells = rng.sample([(x, y) for x in range(100, 1100, 160) for y in range(100, 850, 150)],
                           len(surface['icons']))
        for icon, (x, y) in zip(surface['icons'], cells):
            icon.update(x=x, y=y)


def teach(lab: TopologyLab) -> StateEngine:
    """Use native demonstrations; controlled backward confidence varies the graph costs."""
    engine = StateEngine()
    engine.configure(plasticity=0)
    for lesson in lab.lessons:
        engine.learn(lesson)
    weights = {'CLICK ' + obj: weight for obj, (_, _, weight) in lab.objects.items()}
    transitions = {n['id']: n for n in engine.model['memory']['nodes'] if n['kind'] == 'transition'}
    for edge in engine.model['memory']['edges']:
        transition = transitions.get(edge['to'])
        if edge['kind'] == 'backward' and transition:
            engine.set_weight(edge['id'], weights[transition['label']])
    engine.reset()
    return engine
