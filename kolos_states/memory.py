"""Validation of the native learned graph snapshot, including online experience."""
import math
import re
from .protocol import action, compact, require, sensory_features, persistent_graph
from .episodes import descriptor, MAX_VALUE


def validate_graph(raw: dict, commands: list[dict], episode_commands=None) -> dict:
    """Reject a broken graph before making any stored action executable."""
    require(isinstance(raw, dict), 'Нет графа памяти')
    ns, es = raw.get('nodes'), raw.get('edges')
    require(isinstance(ns, list) and 0 < len(ns) <= 5000 and isinstance(es, list) and len(es) <= 50000, 'Неверный размер графа')
    ids = [x.get('id') for x in ns + es if isinstance(x, dict)]
    require(len(ids) == len(ns) + len(es) and all(isinstance(x, str) and re.fullmatch('[ne][0-9]+', x) for x in ids)
            and len(ids) == len(set(ids)), 'Неверные идентификаторы графа')
    require(isinstance(raw.get('serial'), int) and raw['serial'] > max(int(x[1:]) for x in ids), 'Неверный счётчик графа')
    nodes = {n['id']: n for n in ns}
    require(raw.get('root') in nodes and nodes[raw['root']]['kind'] == 'context', 'Нет корня памяти')
    for n in ns:validate_node(n, nodes)
    for e in es:validate_edge(e, nodes)
    require(len({(e['from'],e['to'],e['kind']) for e in es}) == len(es), 'Дублирующая связь')
    require(isinstance(commands, list), 'Нет команд')
    for c in commands:
        require(isinstance(c, dict) and nodes.get(c.get('context'), {}).get('kind') == 'context'
                and nodes.get(c.get('first'), {}).get('kind') == 'step' and isinstance(c.get('data'), bool)
                and isinstance(c.get('label'), str) and isinstance(c.get('focus'), str)
                and isinstance(c.get('signature'), str), 'Повреждена команда')
    episode_commands = [] if episode_commands is None else episode_commands
    require(isinstance(episode_commands, list) and len(episode_commands) <= 20, 'Неверный список рабочих эпизодов')
    for c in episode_commands:
        require(isinstance(c, dict) and nodes.get(c.get('node'), {}).get('kind') == 'episode_command'
                and c.get('query') == nodes[c['node']]['label'], 'Повреждена команда рабочего эпизода')
        roles, protected = c.get('roles'), c.get('protected')
        require(isinstance(roles, list) and isinstance(protected, list)
                and all(isinstance(r, str) and nodes.get(r, {}).get('kind') == 'episode_role' for r in roles + protected),
                'Повреждены роли рабочего эпизода')
        require(len(set(roles)) == len(roles) and set(protected).issubset(roles), 'Неверные защищённые роли')
    require(len({c['query'] for c in episode_commands}) == len(episode_commands)
            and {c['node'] for c in episode_commands} == {n['id'] for n in ns if n['kind'] == 'episode_command'},
            'Неполный или неоднозначный список рабочих эпизодов')
    validate_paths(nodes, es)
    return persistent_graph(raw)


def validate_edge(e: dict, nodes: dict) -> None:
    """Stored synapses must connect the existing compatible kinds of ensembles."""
    require(e.get('from') in nodes and e.get('to') in nodes, 'Разорванная связь')
    pair=(nodes[e['from']]['kind'],nodes[e['to']]['kind']);kind=e.get('kind')
    allowed={'recognize':{('context','context')},'starts':{('context','step'),('transition','step')},
             'next':{('step','step')},'backward':{('state','transition'),('transition','state')},
             'applicable':{('state','transition')},'experienced':{('transition','step')},
             'observes':{('observation','state')},'corresponds':{('symbol','motor')},
             'episode_command':{('context','episode_command')},'episode_role':{('episode_command','episode_role')},
             'episode_next':{('episode_command','episode_step'),('episode_step','episode_step'),('episode_step','episode_finish')},
             'episode_binds':{('episode_role','episode_step')},'episode_produces':{('episode_step','episode_slot')},
             'episode_value':{('episode_slot','episode_step')},'episode_effect':{('episode_step','episode_role')}}
    from .perception.types import EDGES
    allowed.update(EDGES)
    from .concept_graph import EDGES as CONCEPT_EDGES
    allowed.update(CONCEPT_EDGES)
    require(pair in allowed.get(kind,set()), 'Несовместимые вершины связи')
    require(isinstance(e.get('weight'), (int, float)) and math.isfinite(e['weight']) and 0 <= e['weight'] <= 1, 'Неверный вес')


def validate_node(n: dict, nodes: dict) -> None:
    """Check references read by inference, not display-only labels."""
    kind = n.get('kind')
    from .concept_graph import KINDS as CONCEPT_KINDS, validate_node as validate_concept
    if kind in CONCEPT_KINDS:
        validate_concept(n, nodes)
        return
    from .perception.types import KINDS
    if kind in KINDS:
        from .perception.validation import validate_node as validate_visual
        validate_visual(n, nodes)
        return
    require(kind in ('context','state','observation','step','transition','symbol','motor',
                    'episode_command','episode_role','episode_step','episode_slot','episode_finish'), 'Неизвестный тип вершины')
    if kind == 'state':
        features = n.get('features')
        require(isinstance(features, list) and all(isinstance(f, str) for f in features), 'Нет признаков ансамбля')
        require(features == sensory_features(features) and n.get('key') == compact(features), 'Повреждены признаки ансамбля')
    if kind == 'step':
        a = n.get('action'); require(isinstance(a, dict), 'Нет моторного шага')
        if a.get('kind') not in ('drive','finish'):action(a)
        require(nodes.get(n.get('pre'), {}).get('kind') == 'state', 'Нет исходного ансамбля шага')
        require(n.get('post') is None or nodes.get(n['post'], {}).get('kind') == 'state', 'Нет результата шага')
    if kind == 'transition':
        for key, expected in (('from','state'),('to','state'),('first','step'),('last','step')):
            require(nodes.get(n.get(key), {}).get('kind') == expected, 'Повреждён переход')
    if kind == 'observation':require(isinstance(n.get('label'), str), 'Нет сенсорного признака')
    if kind in ('symbol','motor'):require(isinstance(n.get('value'), str) and len(n['value']) == 1, 'Нет символа')
    if kind == 'context' and 'symbol' in n:require(isinstance(n['symbol'], str) and len(n['symbol']) == 1, 'Неверный контекст')
    if kind == 'episode_command':require(isinstance(n.get('label'), str) and 0 < len(n['label']) <= 160, 'Нет команды рабочего эпизода')
    if kind == 'episode_slot':require(isinstance(n.get('label'), str) and 0 < len(n['label']) <= 80, 'Нет имени ячейки эпизода')
    if kind == 'episode_role':descriptor(n.get('descriptor'))
    if kind == 'episode_step':
        operation = n.get('operation')
        require(operation in ('read','write','activate') and nodes.get(n.get('role'), {}).get('kind') == 'episode_role',
                'Повреждён шаг рабочего эпизода')
        if operation in ('read','write'):
            key = 'slot' if operation == 'read' else 'source'
            require(nodes.get(n.get(key), {}).get('kind') == 'episode_slot', 'Нет ячейки данных рабочего эпизода')
        effects = n.get('effects')
        require(isinstance(effects, list), 'Нет результатов рабочего эпизода')
        for effect in effects:
            require(isinstance(effect, dict) and nodes.get(effect.get('role'), {}).get('kind') == 'episode_role',
                    'Нет роли результата эпизода')
            if 'source' in effect:
                require('literal' not in effect and nodes.get(effect['source'], {}).get('kind') == 'episode_slot',
                        'Нет источника результата эпизода')
            else:
                require(isinstance(effect.get('literal'), str) and len(effect['literal']) <= MAX_VALUE, 'Неверный результат эпизода')


def validate_paths(nodes: dict, edges: list[dict]) -> None:
    """A transition must describe a finite known motor fragment."""
    from .perception.validation import validate_topology
    validate_topology(nodes, edges)
    from .concept_graph import validate_topology as validate_concepts
    validate_concepts(nodes, edges)
    following = {}
    episode_following = {}
    for e in edges:
        if e['kind'] == 'next':following.setdefault(e['from'], []).append(e['to'])
        if e['kind'] == 'episode_next':episode_following.setdefault(e['from'], []).append(e['to'])
    for t in nodes.values():
        if t['kind'] == 'episode_command':
            current, visited = t['id'], set()
            while nodes[current]['kind'] != 'episode_finish':
                require(current not in visited and len(episode_following.get(current, [])) == 1, 'Разрыв или цикл рабочего эпизода')
                visited.add(current); current = episode_following[current][0]
        if t['kind'] != 'transition':continue
        outcomes=[e for e in edges if e['kind']=='backward' and e['to']==t['id']]
        require(len(outcomes)==1 and outcomes[0]['from']==t['to'], 'Нет однозначной связи результата')
        current = t['first']; visited = set()
        while current != t['last']:
            require(current not in visited and len(following.get(current, [])) == 1, 'Разрыв или цикл моторного фрагмента')
            visited.add(current); current = following[current][0]
            require(nodes[current]['kind'] == 'step', 'В моторном фрагменте нет действия')
