"""Fresh instance guards independent from excitation and old mouse coordinates."""
from __future__ import annotations

from ..protocol import under, click_continues


def visual_guard(observed: dict, action: dict) -> str:
    """A pointer or an old click alone cannot identify a composite visual target."""
    if click_continues(observed, action):
        return ''
    proof = observed.get('visual_bindings', {}).get(action['visual'])
    if not proof or proof.get('frame') != observed.get('version') or proof.get('session') != observed.get('session'):
        return 'Составной объект не подтверждён в текущем кадре'
    if proof.get('captured_at') != observed.get('captured_at'):
        return 'Зрительное подтверждение устарело'
    bbox = proof.get('bbox')
    if not isinstance(bbox, list) or len(bbox) != 4:
        return 'Нет границ подтверждённого экземпляра'
    if action['kind'] == 'move':
        return '' if bbox[0] <= action['x'] <= bbox[2] and bbox[1] <= action['y'] <= bbox[3] else 'Цель переместилась до наведения'
    if action['kind'] == 'enter':
        trace = observed.get('last_clicked_visual') or {}
        confirmed = (observed.get('last_clicked') == action.get('object')
                     and trace.get('target') == action['visual'] and trace.get('bbox') == bbox)
        return '' if confirmed else 'Не подтверждён клик по этому экземпляру'
    return '' if under(observed, dict(bbox=bbox)) else 'Под курсором нет подтверждённого составного объекта'
