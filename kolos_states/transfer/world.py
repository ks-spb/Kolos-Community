"""Seeded UI test worlds and independent demonstrations, without OS effects."""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..core import StateEngine
from ..protocol import clone
from ..simulator import demonstrate, icon_actions


@dataclass
class Lab:
    """World labels are private to the harness; controllers receive observations."""

    seed: int
    world: dict
    objects: dict[str, str]
    field: str
    lessons: list[dict]
    extra_lessons: list[dict]

    def at(self, surface: str, changed: bool = False) -> dict:
        """Create a fresh environment, optionally changing the fast button effect."""
        world = clone(self.world)
        world.update(surface=surface, focus=world['surfaces'][surface]['field'] or '')
        if changed:
            world['surfaces']['desk']['icons'][0]['click'] = 'error'
        return world


def make_lab(seed: int) -> Lab:
    """Generate one topology with random opaque labels, geometry and lesson order."""
    rng = random.Random(seed)
    names = ['fast', 'panel', 'next', 'back', 'close', 'return', 'focus']
    names += [f'noise{i}' for i in range(5)] + [f'home{i}' for i in range(5)]
    labels = rng.sample(range(10000, 99999), len(names) + 1)
    objects = {name: f'obj-{number}' for name, number in zip(names, labels)}
    field = f'field-{labels[-1]}'

    def icons(specs: list[tuple[str, str]]) -> list[dict]:
        """Use separated grid cells so pointer ambiguity is never accidental."""
        cells = rng.sample([(x, y) for x in (100, 300, 500, 700) for y in (100, 300, 500)], len(specs))
        return [dict(id=objects[name], x=x, y=y, click=target)
                for (name, target), (x, y) in zip(specs, cells)]

    specs = dict(desk=[('fast', 'form'), ('panel', 'panel')] + [(f'noise{i}', f'noise{i}') for i in range(5)],
                 panel=[('next', 'form')], form=[('focus', 'focused')],
                 focused=[('back', 'desk')], overlay=[('close', 'desk')], error=[('return', 'desk')])
    specs.update({f'noise{i}': [(f'home{i}', 'desk')] for i in range(5)})
    surfaces = {name: dict(field=field if name == 'focused' else None, icons=icons(items))
                for name, items in specs.items()}
    world = dict(surface='desk', selected='', focus='', output='', cursor=dict(x=900, y=700),
                 version=0, effects=[], surfaces=surfaces)
    lab = Lab(seed, world, objects, field, [], [])
    _lessons(lab, rng)
    return lab


def _lessons(lab: Lab, rng: random.Random) -> None:
    """Only single transitions are shown; distractor round trips are separate."""
    specs = [('desk', 'fast'), ('desk', 'panel'), ('panel', 'next'), ('focused', 'back'),
             ('overlay', 'close'), ('error', 'return'), ('form', 'focus')]
    for i, (surface, name) in enumerate(specs):
        world = lab.at(surface)
        lab.lessons.append(demonstrate(f'lesson-{i}', world, icon_actions(world, lab.objects[name])))
    rng.shuffle(lab.lessons)
    for i in range(5):
        world = lab.at('desk')
        actions = icon_actions(world, lab.objects[f'noise{i}'])
        actions += icon_actions(lab.at(f'noise{i}'), lab.objects[f'home{i}'])
        lab.extra_lessons.append(demonstrate(f'extra-{i}', world, actions))


def teach(lab: Lab) -> StateEngine:
    """Teach seven motor fragments and one alphabet exposure using native learning."""
    engine = StateEngine()
    engine.configure(plasticity=0)
    for record in lab.lessons:
        engine.learn(record)
    keys = [dict(kind='key', value=v) for v in '0123456789']
    engine.learn(demonstrate('alphabet', lab.at('focused'), keys), exposure=True)
    engine.reset()
    return engine


def cases(seed: int) -> list[dict]:
    """Held-out goals; seed stream is disjoint from teaching and training values."""
    rng = random.Random(seed + 900000)
    variants = [('overlay', False, False), ('desk', False, False), ('panel', False, False),
                ('desk', True, False), ('overlay', False, True)]
    return [dict(case=i, start=start, interrupt=interrupt, shifted=shifted,
                 value=''.join(rng.choices('0123456789', k=4)))
            for i, (start, interrupt, shifted) in enumerate(variants)]
