"""Validate persisted visual assemblies before they can ground motor actions."""
from __future__ import annotations

from ..protocol import require
from .types import HEIGHT, MAX_WIDTH, TILE, rectangle


def validate_node(node: dict, nodes: dict) -> None:
    """Check all stored geometry, fragment sizes and references."""
    kind = node['kind']
    require(isinstance(node.get('label'), str), 'Нет имени зрительного ансамбля')
    if kind in ('visual_variant', 'visual_relation'):
        rect = rectangle(node.get('relative'))
        require(all(abs(v) <= 32 for v in rect), 'Неверное взаимное расположение частей')
    if kind == 'visual_variant':
        if node.get('source_size') is not None:
            require(isinstance(node['source_size'], list) and len(node['source_size']) == 2, 'Нет размера значка')
            rectangle([0, 0, *node['source_size']])
        require(node.get('clipped') in ('none', 'left', 'right', 'top', 'bottom'), 'Неверное обрезание')
        for role in ('icon', 'label'):
            shape = node.get('shapes', {}).get(role)
            require(isinstance(shape, list) and len(shape) == 2 and type(shape[0]) is int
                    and 1 <= shape[0] <= MAX_WIDTH and shape[1] == HEIGHT, 'Неверный размер части')
    if kind == 'visual_part':
        require(node.get('role') in ('icon', 'label'), 'Неизвестная зрительная часть')
    if kind == 'visual_fragment':
        rect = rectangle(node.get('rect')); l, t, r, b = rect
        require(all(type(v) is int for v in rect) and 0 <= l < r <= MAX_WIDTH and 0 <= t < b <= HEIGHT,
                'Фрагмент вне области')
        data = node.get('data')
        require(isinstance(data, str) and len(data) == 2*(r-l)*(b-t), 'Повреждён фрагмент')
        try:
            require(len(bytes.fromhex(data)) == (r-l)*(b-t), 'Повреждён фрагмент')
        except ValueError as exc:
            raise ValueError('Повреждён зрительный фрагмент') from exc
    if kind == 'visual_look':
        require(nodes.get(node.get('variant'), {}).get('kind') == 'visual_variant'
                and node.get('detail') in (0, 1), 'Повреждён осмотр')


def validate_topology(nodes: dict, edges: list) -> None:
    """Missing required evidence must not make a malformed object easier to recognize."""
    for node in nodes.values():
        incoming = [e for e in edges if e['to'] == node['id']]
        parts = [nodes[e['from']] for e in incoming if e['kind'] == 'visual_contains']
        if node['kind'] == 'visual_variant':
            require(sorted(p['role'] for p in parts) == ['icon', 'label'], 'Нужны обе части образа')
            require(sum(e['kind'] == 'visual_spatial' for e in incoming) == 1, 'Нет пространственной связи')
            for part in parts:
                _coverage(nodes, edges, part, node['shapes'][part['role']])
        if node['kind'] in ('visual_part', 'visual_object'):
            require(bool(parts), 'Пустой зрительный ансамбль')
        if node['kind'] == 'step' and node['action'].get('visual'):
            target = node['action']['visual']
            require(nodes.get(target, {}).get('kind') == 'visual_object', 'Нет зрительной цели шага')
            require(any(e['kind'] == 'visual_ground' and e['from'] == node['id'] and e['to'] == target
                        for e in edges), 'Нет обученной связи шага с образом')


def _coverage(nodes: dict, edges: list, part: dict, shape: list) -> None:
    """Deleted fragments cannot turn a full-label assembly into an accidental prefix."""
    width, height = shape
    expected = {(x, y, min(x+TILE, width), min(y+TILE, height))
                for y in range(0, height, TILE) for x in range(0, width, TILE)}
    actual = [tuple(nodes[e['from']]['rect']) for e in edges
              if e['kind'] == 'visual_contains' and e['to'] == part['id']]
    require(set(actual) == expected and len(actual) == len(expected), 'Неполная карта зрительной части')
