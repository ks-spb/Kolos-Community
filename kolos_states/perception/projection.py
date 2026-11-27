"""Present recorded visual currents without influencing neural decisions."""
from __future__ import annotations


def project(model: dict, node: object, edge: object) -> None:
    """Instantiate the same learned ensembles separately for each observed location."""
    current = model.get('perception') or {}
    memory = {n['id']: n for n in model.get('memory', {}).get('nodes', [])}
    for n in memory.values():
        if n['kind'].startswith('visual_'):
            node(n['id'], group='visual', I=current.get('I') if n['id'] == current.get('target') else None)
    for key, values in current.get('neurons', {}).items():
        original = memory[values['memoryRef']]
        node('view:visual:'+key, label=original['label']+' @ '+values['instance'],
             kind='visual-instance', group='visual', stored=values, **values)
    for candidate in current.get('candidates', []):
        node('view:visual:c:'+candidate['id'], label=candidate['label'], kind='visual-candidate',
             group='visual', A=candidate['a'], C=candidate['a'], S=candidate['sensory'],
             inhibition=candidate['inhibition'], threshold=candidate['threshold'],
             winner=current.get('winner') == candidate['id'], calculation=candidate)
    for flow in current.get('flows', []):
        suffix = '@'+flow['instance']
        edge('view:visual:'+flow['edge']+suffix, 'view:visual:'+flow['from']+suffix,
             'view:visual:'+flow['to']+suffix, kind='visual-sensory', flow=flow['value'],
             provenance='recorded', note='Вклад вычисленной зрительной связи для данного экземпляра.')
    for look in current.get('attention', []):
        node(look['id'], A=look['a'], I=current.get('I'), inhibition=look['inhibition'],
             calculation=look, current=look['id'] in [r['id'] for r in current.get('requests', [])])
