"""Teaching and observation-mode commands, sharing the native Store transaction."""
from __future__ import annotations

import re
from ..ipc import read_json
from ..protocol import clone, require
from .learning import teach, bind, _path
from .observer import VisualAccessibility
from .help import VISUAL_HELP


def catalog(engine: object) -> dict:
    """Small UI catalog; prototypes and live screenshots are not duplicated here."""
    targets = [dict(id=n['id'], name=n['label']) for n in engine.model['memory']['nodes']
               if n['kind'] == 'visual_object']
    commands = []
    for command in engine.model['commands']:
        objects = sorted({s['action']['object'] for s in _path(engine, command['first'])
                          if s['action'].get('object')})
        commands.append(dict(query=command['label'], objects=objects))
    return dict(targets=targets, commands=commands)


def visual_mode(terminal: object, enabled: bool) -> None:
    """Retain the prior observer for existing text-field workflows."""
    if not hasattr(terminal, '_accessibility_observer'):
        terminal._accessibility_observer = terminal.observer.accessibility
    terminal.observer.accessibility = (VisualAccessibility(terminal.args.glaz_pid) if enabled
                                       else terminal._accessibility_observer)
    terminal.visual_only = enabled


def configure_query(terminal: object, query: str) -> None:
    """An explicitly grounded command uses image-only input automatically."""
    command = terminal.engine.inspect(query)['command']
    if any(s['action'].get('visual') for s in _path(terminal.engine, command['first'])):
        visual_mode(terminal, True)


def command(terminal: object, text: str) -> bool:
    """Human-confirmed teaching may resume a held goal but never a pending effect."""
    if text == '/visual-help':
        print(VISUAL_HELP, flush=True)
        return True
    if text.startswith('/vision '):
        require(not terminal.running and not terminal.recording and not terminal.schedule,
                'Остановите выполнение и запись перед сменой наблюдателя')
        require(text in ('/vision on', '/vision off'), '/vision on|off')
        visual_mode(terminal, text.endswith('on'))
        print('Зрительный режим без UI Automation.' if terminal.visual_only else 'Прежний наблюдатель полей включён.', flush=True)
        return True
    if not text.startswith('/visual-teach-file '):
        return False
    name = text.split(' ', 1)[1]
    require(re.fullmatch(r'visual-lesson-[a-f0-9]{32}\.json', name), 'Неверный файл показа')
    request = read_json(terminal.path/name)
    require(request and request.get('session') == terminal.args.session, 'Показ из другого сеанса')
    _commit(terminal, request)
    return True


def _commit(terminal: object, request: dict) -> None:
    """Teaching plus command binding is one reversible in-memory transaction."""
    engine = terminal.engine; backup = clone(engine.model); count = len(engine.events)
    try:
        require(not terminal.running and not terminal.recording and not terminal.schedule,
                'Сначала нажмите Пауза и завершите запись')
        require(not getattr(terminal, 'episode_recorder', None), 'Сначала завершите запись рабочего эпизода')
        target = teach(engine, request['lesson'])
        if request.get('query'):
            bind(engine, request['query'], request['object'], target)
        # One atomic durable write: a later audit-file failure cannot undo its ACK.
        terminal.store.save(engine, preserve_attempt=True)
    except Exception as exc:
        engine.model = backup; del engine.events[count:]
        terminal.visual_teaching = dict(id=request['id'], ok=False, message=str(exc))
        raise
    terminal.visual_teaching = dict(id=request['id'], ok=True, target=target,
                                    message='Образ сохранён'+(' и связан с командой.' if request.get('query') else '.'))
    print(terminal.visual_teaching['message'], flush=True)
