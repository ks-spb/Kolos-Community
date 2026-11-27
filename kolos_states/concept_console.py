"""Correlated teacher replies, durable learning and resumption of the held step."""
from __future__ import annotations

import json
import time
from .protocol import clone, require
from .object_concepts import answer


def command(terminal: object, text: str) -> bool:
    if not text.startswith('/object-answer '):
        return False
    require(len(text) < 1024, 'Ответ слишком длинный')
    payload = json.loads(text.split(' ', 1)[1])
    require(isinstance(payload, dict) and set(payload) == {'id', 'choice'}, 'Неверный ответ на вопрос')
    q = terminal.engine.model.get('objectQuestion')
    require(q and payload['id'] == q['id'] and payload['choice'] in ('yes', 'no', 'unsure'), 'Вопрос не активен')
    require(not terminal.running and not terminal.recording and not terminal.schedule,
            'Ответ уже обрабатывается или выполняется другая операция')
    if payload['choice'] != 'yes':
        answer(terminal.engine, payload['id'], payload['choice'])
        terminal.store.save(terminal.engine, preserve_attempt=True)
        print(terminal.engine.model['message'], flush=True)
        return True
    terminal._arm()  # Existing F9 and explicit input permission remain mandatory.
    terminal.object_answer = payload
    terminal.schedule = ('object-answer', time.monotonic()+1.0)
    print('Ответ принят. Возвращаюсь к наблюдению исходного окна; перед действием объект будет проверен заново.', flush=True)
    return True


def scheduled(terminal: object) -> None:
    require(not terminal.abort.is_set(), 'Ответ отменён аварийной остановкой')
    terminal._arm()
    payload = terminal.object_answer
    engine = terminal.engine; backup = clone(engine.model); count = len(engine.events)
    try:
        observed = terminal.observer.observe()
        answer(engine, payload['id'], payload['choice'], observed)
        # Failure leaves both graph and held step unmodified and sends no input.
        terminal.store.save(engine, preserve_attempt=True)
    except Exception:
        engine.model = backup; del engine.events[count:]
        raise
    terminal.object_answer = None
    terminal.running = True; terminal.pause.clear()
    print(engine.model['message'], flush=True)
