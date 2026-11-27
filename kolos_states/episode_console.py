"""Optional commands for the existing Glaz States terminal and its SAME Store.

No second execution engine or replacement user memory. Observation is explicitly
scoped to a selected accessible window. Learning records generic operations the
user chooses in order; the module contains no task-specific route.
"""
from __future__ import annotations
import json
import subprocess
import sys
from .protocol import clone, require
from .episode_desktop import UIAObserver, EpisodeAdapter, EpisodeRecorder


def _idle(t):
    require(not t.running and not t.recording and not t.schedule and not t.engine.model['pending'],
            'Остановите текущий опыт. При неподтверждённом действии сначала проверьте окно и выполните Reset.')


def _permission(t):
    require(t.hooks_ready, 'Нет аварийной клавиши F9; перезапустите Glaz после установки зависимостей')
    if not t.allowed():
        raise PermissionError('В Glaz выключено разрешение управления ПК')
    t.abort.clear()
    t.pause.clear()


def command(t, text):
    recorder = getattr(t, 'episode_recorder', None)
    if text in ('/reset', '/stop', '/quit'):
        t.episode_recorder = None
        return False  # The original terminal still owns stop/reset semantics.
    if not text.startswith('/episode'):
        if recorder and text not in ('/pause', '/help', '/status', '/speed 1'):
            raise ValueError('Сначала сохраните или явно сбросьте запись рабочего эпизода')
        return False
    if text == '/episodetest':
        from .episode_experiment import report
        print(json.dumps(report(), ensure_ascii=False), flush=True)
        return True
    if text == '/episodepad':
        subprocess.Popen([sys.executable, '-m', 'kolos_states.episode_pad'])
        return True
    if text.startswith('/episode-window '):
        _idle(t)
        require(recorder is None, 'Сначала сохраните или сбросьте демонстрацию')
        observer = UIAObserver(int(text.split(' ', 1)[1]), own_pid=t.args.glaz_pid)
        obs = observer.observe()  # Read and validate before replacing the selection.
        t.episode_observer = observer
        t.episode_adapter = EpisodeAdapter(observer, allow=t.allowed, stop=t.abort, paused=t.pause.is_set)
        print(json.dumps(dict(episodeObjects=obs['objects']), ensure_ascii=False), flush=True)
        return True
    observer = getattr(t, 'episode_observer', None)
    require(observer is not None, 'В диалоге «Рабочий эпизод» сначала выберите и прочитайте окно')
    if text == '/episode-objects':
        print(json.dumps(dict(episodeObjects=observer.observe()['objects']), ensure_ascii=False), flush=True)
        return True
    if text.startswith('/episode-begin '):
        _idle(t)
        require(recorder is None, 'Демонстрация уже записывается')
        _permission(t)
        t.engine.reset()
        t.episode_recorder = EpisodeRecorder(t.episode_adapter, text.split(' ', 1)[1])
        print('Запись эпизода: выбирайте чтение, ввод и активацию по одному. Маршрут задаётся вашим показом. Reset — отбросить.', flush=True)
        return True
    if text.startswith(('/episode-read ', '/episode-write ', '/episode-activate ')):
        require(recorder is not None and not t.running, 'Сначала начните демонстрацию эпизода')
        _permission(t)
        op, argument = text.split(' ', 1)
        if op == '/episode-write':
            spec = json.loads(argument)
            receipt = recorder.capture('write', spec['object'], spec['source'])
        else:
            receipt = recorder.capture('read' if op == '/episode-read' else 'activate', argument)
        print(json.dumps(dict(episodeRecorded=receipt['action']['kind'], slots=list(recorder.slots),
                              actions=len(recorder.receipts)), ensure_ascii=False), flush=True)
        return True
    if text == '/episode-save':
        _idle(t)
        require(recorder is not None, 'Нет записи эпизода')
        t.engine.learn_episode(recorder.finish())
        t.store.save(t.engine)
        t.episode_recorder = None
        t.pause.set()
        print('Рабочий эпизод сохранён в той же памяти Kolos. Для проверки измените данные/компоновку и запустите выученную фразу.', flush=True)
        return True
    if text.startswith('/episode-run '):
        _idle(t)
        require(recorder is None, 'Сначала сохраните или сбросьте демонстрацию')
        _permission(t)
        t.engine.start_episode(text.split(' ', 1)[1], observer.observe())
        t.receipt = None
        t.running = True
        t.store.save(t.engine)
        print('Эпизод запущен. Данные считываются из выбранного окна. Пауза / Шаг / F9 действуют как прежде.', flush=True)
        return True
    raise ValueError('Неизвестная команда рабочего эпизода')


def tick_once(t):
    m = t.engine.model
    if m['status'] not in ('running', 'waiting'):
        t.running = False
        t.pause.set()
        return
    if m['pending']:
        if t.receipt is None:
            event = t.engine.tick()
            if m['status'] == 'waiting':
                t.receipt = t.episode_adapter.execute(clone(m['pending']))
        else:
            event = t.engine.accept_receipt(t.receipt)
            t.receipt = None
    else:
        t.engine.observe(t.episode_observer.observe())
        event = t.engine.tick()
    print(f"Такт {m['tick']}: {event['kind']} · {m['message']}", flush=True)
    if m['status'] not in ('running', 'waiting'):
        t.running = False
        t.pause.set()
    t.store.save(t.engine)
