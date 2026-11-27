"""States terminal used by Glaz's existing subprocess controller.

No live I/O before explicit permission. /selftest runs isolated tests, not a
calculator on the user's desktop. Uncertain effects are never retried.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any
from cv_core.glaz_ipc import read_last_confirmed_target
from .core import StateEngine, STOP
from .commands import AmbiguousCommand
from .ipc import ScanClient, read_json, atomic_json, AtomicReplaceBlocked
from .accessibility import Accessibility
from .desktop import DesktopObserver, DesktopAdapter, WindowsMotor
from .storage import Store
from .recorder import Recorder
from .neuron_trace import NeuronTraceWriter
from .learned_tasks import confirmed_tasks
from .targeting import click_followup

HELP='''Состояния и цели / Python / ПК — старый main.py не используется.
Введите команду. Неизвестная команда останется для обучения.
3 — запись демонстрации (пауза 2 с для возврата в нужное окно). Перед следующим действием дождитесь сообщения о записи предыдущего в терминале Kolos.
Esc — остановить запись; 5 — подготовить; 1 — подтвердить и сохранить.
/expose — подтвердить запись только прежних клавиш (без команды).
/pause — пауза; /run — продолжить; /step — одна операция; /reset — отменить попытку.
/stop или F9 — аварийная остановка; /speed 1 — секунды между тактами.
/plasticity on|off — обучение по собственному опыту (по умолчанию on).
/selftest — прежние 4 теста; /acceptance — все 10 проверок без настоящих кликов.
/goals [{"kind":"field","focus":"известный ID поля","value":"2345"}] — задать результат.
Эти цели также доступны в диалоге «Задать цель». Это не парсер естественного языка.
/imagine <JSON целей> — образ без действий; /image-act — достичь; /image-rest — снять поддержку.
/imagerytest — безопасная модельная проверка опыта 11.
/sharedtest — 12 опытов на одной учебной Python-базе (без действий на ПК).
/say ФРАЗА — языковые связи → образ без действий; /say-run ФРАЗА — затем достичь.
/language-teach JSON — подтверждённая пара фраза/образ; /languagetest — опыт 12 без ПК.
/vision on|off — зрительный режим без UI Automation / прежний наблюдатель полей.
/visual-help — как дообучить O1, добавить образ, подпись или ещё один вид.
Значок с подписью обучается в «Опыты и инструменты → Обучить составной объект».
/episodetest — проверка этапа 1; /episodepad — настоящее окно с несколькими полями.
Эпизоды обучаются в «Опыты и инструменты → Рабочий эпизод и роли»; общая память сохраняется.
/status — диагностика; /help — справка. Вводите демонстрацию медленно, по одному действию.
Реальный ввод требует галочки «Разрешить управление ПК» в Glaz.
'''


def _recording_symbol(key: Any) -> str | None:
    """Decode Windows NumPad digits even when pynput's layout cache has no char."""
    vk=getattr(key,'vk',None)
    if isinstance(vk,int) and 0x60<=vk<=0x69:return str(vk-0x60)
    char=getattr(key,'char',None)
    return char if isinstance(char,str) and char.isprintable() else None


def _physical_key(key: Any) -> Any:
    """Match press/release by virtual key even if modifiers change the char."""
    vk=getattr(key,'vk',None)
    return ('vk',vk) if vk is not None else key


class Terminal:
    def __init__(self,args):
        self.args=args;self.queue=queue.Queue();self.abort=threading.Event();self.pause=threading.Event();self.pause.set()
        self.path=Path(args.ipc);self.neuron_trace=NeuronTraceWriter(self.path,args.session);self.store=Store(Path(args.memory));self.engine=self.store.load()
        self.observer=DesktopObserver(ScanClient(self.path,args.session,stop=self.abort),Accessibility(args.glaz_pid))
        self.observer.model_provider = lambda: self.engine.model
        self.adapter=None;self.running=False;self.receipt=None;self.last_query='';self.recorder=None;self.record=None;self.staged=None
        self.recording=False;self.seconds=1.0;self.single=False;self.closed=False;self.schedule=None;self.hooks=[];self.hooks_ready=False
        self.modified=False;self.pending_goals=None;self.pending_phrase='';self.language_auto=False
        self._status_write_blocked=False
        self._click_down_at=None;self._click_down_target=None;self._click_down_recorder=None

    def allowed(self):
        p=read_json(self.path/'permission.json')
        return bool(p and p.get('session')==self.args.session and p.get('live') and 0<=time.time()-p.get('stamp',0)<2.0)

    def publish(self):
        self.neuron_trace.capture(self.engine)
        m=self.engine.model
        payload=dict(session=self.args.session,running=self.running and not self.pause.is_set(),recording=self.recording,
            status=m['status'],message=m['message'],tick=m['tick'],query=m['query'],pending=m['pending'],nodes=m['memory']['nodes'],edges=m['memory']['edges'],
            occ=m['occ'],activation=m['activation'],goalActivation=m['goalActivation'],trace=m['trace'],refractory=m['refractory'],heldGoal=m['heldGoal'],imagery=m.get('imagery'),intent=m.get('intent'),language=m.get('language'),languageMemory=m.get('languageMemory'),episode=m.get('episode'),
            episodeObjects=getattr(getattr(self,'episode_observer',None),'latest',{}).get('objects',[]),
            episodeRecording=bool(getattr(self,'episode_recorder',None)),
            episodeRecordedCount=len(self.episode_recorder.receipts) if getattr(self,'episode_recorder',None) else 0,
            episodeSlots=list(self.episode_recorder.slots) if getattr(self,'episode_recorder',None) else [],
            confirmedTasks=confirmed_tasks(m['lessons']), objectQuestion=m.get('objectQuestion'))
        from .perception.console import catalog
        # Full per-instance currents belong to the bounded neuron trace, not status IPC.
        perception = {k:v for k,v in (m.get('perception') or {}).items() if k not in ('neurons','flows')}
        payload.update(visualCatalog=catalog(self.engine), perception=perception,
                       visualTeaching=getattr(self, 'visual_teaching', None), visualOnly=getattr(self, 'visual_only', False))
        try:
            atomic_json(self.path/'status.json',payload)
        except AtomicReplaceBlocked:
            # Status is a replaceable snapshot. Keep the last complete file and
            # publish the latest model on the next loop, including during quit.
            if not getattr(self,'_status_write_blocked',False):
                print('Статус пока не обновлён: Windows запрещает замену status.json. '
                      'Текущее состояние: '+m['status']+'. Запись будет повторена автоматически.',flush=True)
            self._status_write_blocked=True
        else:
            self._status_write_blocked=False

    def input_reader(self):
        for line in sys.stdin:
            text=line.rstrip('\r\n')
            if text in ('/stop','/quit'):self.abort.set()
            if text=='/pause':self.pause.set()
            self.queue.put(('command',text))
        self.abort.set();self.queue.put(('command','/quit'))

    def hook(self):
        # Global hooks never type or click. They are for the explicitly active
        # demonstration and emergency F9; no input is saved outside recording.
        try:
            # PyAutoGUI loads NumPy through PyScreeze. On Windows its native
            # import can wait on stdin's CRT lock if input_reader is already
            # blocked on the pipe. Import before starting that reader; actual
            # controllers and all input remain behind _arm's permission checks.
            WindowsMotor.prepare()
            from pynput import keyboard,mouse
            self.hooks=[self._keyboard_listener(keyboard),self._mouse_listener(mouse)]
            for listener in self.hooks:listener.start()
            self.hooks_ready=True
        except Exception as exc:print('Глобальные клавиши и средства управления ПК недоступны: '+str(exc),flush=True)

    def _keyboard_listener(self, keyboard: Any) -> Any:
        """Timestamp physical press before a release can enqueue its observation."""
        held=set();presses={}
        def pressed(key):
            if key==keyboard.Key.f9:
                self.abort.set();self.queue.put(('command','/stop'));return
            if key in (keyboard.Key.ctrl,keyboard.Key.ctrl_l,keyboard.Key.ctrl_r,keyboard.Key.alt,keyboard.Key.alt_l,keyboard.Key.alt_r):
                held.add(key);return
            symbol=_recording_symbol(key)
            if self.recording and (key==keyboard.Key.enter or symbol is not None):
                _,at,_=presses.setdefault(_physical_key(key),(self.recorder,time.time(),symbol))
                self.recorder.begin_action(at)
        def released(key):
            held.discard(key);press=presses.pop(_physical_key(key),None)
            if not self.recording:return
            if press and press[0] is not self.recorder:return
            pressed_at=press[1] if press else None
            if key==keyboard.Key.esc:self.recording=False;self.queue.put(('stop-record',None));return
            if self.observer.accessibility.read().get('own'):
                self.recorder.cancel_action(pressed_at);return
            if key in (keyboard.Key.shift,keyboard.Key.shift_l,keyboard.Key.shift_r):return
            if held:self.queue.put(('bad-record','Комбинации Ctrl/Alt в этой версии записи не поддерживаются'));return
            symbol=press[2] if press else _recording_symbol(key)
            if (key==keyboard.Key.enter or symbol is not None) and press is None:return
            if key==keyboard.Key.enter:a={'kind':'enter'}
            elif symbol is not None:a={'kind':'key','value':symbol}
            else:self.queue.put(('bad-record','Эта клавиша не поддерживается; демонстрация не сохранена'));return
            self.queue.put(('record-action',(a,time.time(),None,pressed_at)))
        return keyboard.Listener(on_press=pressed,on_release=released)

    def _mouse_listener(self, mouse: Any) -> Any:
        """Keep the pre-press target and close the preceding effect's interval."""
        def clicked(x,y,button,pressed):
            if not self.recording:return
            if pressed:
                self._click_down_at=time.time() if button==mouse.Button.left else None
                self._click_down_recorder=self.recorder
                if self._click_down_at is not None:self.recorder.begin_action(self._click_down_at)
                self._click_down_target=(read_last_confirmed_target(max_age_sec=10,now=self._click_down_at)
                    if self._click_down_at is not None else None)
                return
            at=time.time();pressed_at=self._click_down_at;target=self._click_down_target
            recorder=self._click_down_recorder
            self._click_down_at=None;self._click_down_target=None;self._click_down_recorder=None
            if recorder is not self.recorder:return
            if self.observer.accessibility.read().get('own'):
                self.recorder.cancel_action(pressed_at);return
            if button!=mouse.Button.left:self.queue.put(('bad-record','Поддерживается только левая кнопка'));return
            if pressed_at is None:return
            self.queue.put(('record-action',({'kind':'click'},at,(x,y),pressed_at,target)))
        return mouse.Listener(on_click=clicked)

    def _discard_recording(self) -> None:
        """Drop demonstration state and unfinished hook presses before a new attempt."""
        self.recording=False;self.recorder=None;self.record=None;self.staged=None
        self._click_down_at=None;self._click_down_target=None;self._click_down_recorder=None

    def _arm(self):
        if not self.hooks_ready:raise PermissionError('Нет аварийной клавиши F9; установите зависимости и перезапустите Glaz')
        if not self.allowed():raise PermissionError('В Glaz выключено разрешение управления ПК')
        self.observer.accessibility.ensure_available()
        self.abort.clear()
        if self.adapter is None:self.adapter=DesktopAdapter(self.observer,WindowsMotor(),stop=self.abort,allow=self.allowed,paused=self.pause.is_set)

    def _record_event(self,kind,data):
        if kind=='record-action':
            if self.recorder and not self.recorder.invalid:
                self.recorder.capture(*data)
                if data[0]['kind']=='click':print('Клик зарегистрирован, исходное наблюдение следующего шага получено. Можно продолжить; для обучения результата дождитесь его появления.',flush=True)
                else:print('Наблюдение записано: '+str(data[0]),flush=True)
        elif kind=='bad-record':
            if self.recorder and not self.recorder.invalid:self.recorder.invalid=data
            self.recording=False;print(data,flush=True)
        elif kind=='stop-record':
            if self.recorder and not self.recorder.invalid:
                self.record=self.recorder.finish()
                if self.record['receipts'][-1].get('effect_observed') is False:
                    print('Результат не удалось наблюдать. Сохранён моторный шаг, связь с изменением среды не обучена.',flush=True)
                else:print('Результат наблюдён.',flush=True)
                print('Запись остановлена. 5 — подготовить, 1 — подтвердить.',flush=True)

    def command(self,text):
        from .concept_console import command as concept_command
        if concept_command(self, text):return
        from .perception.console import command as visual_command
        if visual_command(self, text):return
        from .episode_console import command as episode_command
        if episode_command(self, text):return
        if text in ('/quit','/stop'):
            from .object_concepts import clear as clear_objects
            clear_objects(self.engine.model)
            if getattr(self,'adapter',None):self.adapter.clear_click('Выбор отменён остановкой')
            self.abort.set();self.pause.set();self.running=False;self.recording=False;self.schedule=None;self.language_auto=False
            self.closed=text=='/quit';print('Остановлено. Неподтверждённое действие НЕ повторяется. /reset отменяет попытку.',flush=True);return
        if text=='/help':print(HELP,flush=True);return
        if text=='/end':
            self.recording=False
            if self.recorder:self.record=self.recorder.finish();print('Запись остановлена. 5 → 1 для сохранения.',flush=True)
            return
        if text=='/testpad':
            import subprocess
            subprocess.Popen([sys.executable,'-m','kolos_states.test_pad'])
            return
        if text=='/acceptance':
            from .capabilities import run
            for n in range(1,11):
                r,_,_=run(n);print(json.dumps(r,ensure_ascii=False),flush=True)
            return
        if text=='/languagetest':
            from .language_experiment import run_language
            r,_,_=run_language();print(json.dumps(r,ensure_ascii=False),flush=True);return
        if text.startswith('/language-teach '):
            if self.running or self.recording or self.schedule:raise ValueError('Сначала остановите попытку и запись')
            pair=json.loads(text[len('/language-teach '):])
            self.engine.teach_language(pair['phrase'],pair['goal']);self.store.save(self.engine)
            print('Языковая пара сохранена. Для переменного содержания нужны две разные пары этой формулировки.',flush=True);return
        if text.startswith('/say ') or text.startswith('/say-run '):
            if self.engine.model['pending']:raise ValueError('Сначала разрешите неподтверждённое действие')
            auto=text.startswith('/say-run ')
            if auto:self._arm()
            else:self.abort.clear()
            if self.recording:raise ValueError('Сначала закончите запись демонстрации')
            self.language_auto=auto
            self.pending_phrase=text.split(' ',1)[1]
            self.running=False;self.pause.set();self.schedule=('language',time.monotonic()+2)
            print('Через 2 с фраза начнёт возбуждать языковые связи. Неоднозначный образ не запускает действия.',flush=True);return
        if text=='/sharedtest':
            from .shared_experiment import SharedSession
            s=SharedSession()
            for n in range(1,13):print(json.dumps(s.run(n),ensure_ascii=False),flush=True)
            return
        if text=='/imagerytest':
            from .imagery_experiment import run
            r,_,_=run();print(json.dumps(r,ensure_ascii=False),flush=True);return
        if text.startswith('/imagine '):
            if self.engine.model['pending']:raise ValueError('Сначала разрешите неподтверждённое действие')
            goals=json.loads(text[len('/imagine '):])
            if not isinstance(goals,list) or not 0<len(goals)<=8:raise ValueError('Нужно 1–8 целей')
            self.abort.clear();self.pause.set();self.running=False;self.pending_goals=goals
            self.schedule=('imagine',time.monotonic()+2)
            print('Через 2 с сформируется образ по свежему наблюдению. Мышь и клавиатура выключены.',flush=True);return
        if text=='/image-act':
            if not self.engine.model.get('imagery'):raise ValueError('Сначала задайте образ')
            self._arm();self.schedule=('image-act',time.monotonic()+2)
            print('Через 2 с образ будет направлять действия. F9 — стоп.',flush=True);return
        if text=='/image-rest':
            self.engine.control_image('rest');self.running=True;self.pause.clear();return
        if text.startswith('/goals '):
            if self.engine.model['pending']:raise ValueError('Сначала разрешите неподтверждённое действие')
            goals=json.loads(text[len('/goals '):])
            if not isinstance(goals,list) or not 0<len(goals)<=8:raise ValueError('Нужно 1–8 целей')
            self._arm();self.pending_goals=goals;self.schedule=('goal',time.monotonic()+2)
            print('Через 2 с запуск удерживаемых целей. Вернитесь в целевое окно. F9 — стоп.',flush=True);return
        if text=='/selftest':
            from .simulator import run_case
            for n in range(1,5):
                r,_,_=run_case(n);print(json.dumps(r,ensure_ascii=False),flush=True)
            return
        if text=='/pause':self.pause.set();self.running=False;self.language_auto=False;self.schedule=None;return
        if text=='/reset':
            if getattr(self,'adapter',None):self.adapter.clear_click()
            self._discard_recording()
            self.abort.clear();self.engine.reset();self.receipt=None;self.running=False;self.pause.set();self.schedule=None;self.language_auto=False;self.store.save(self.engine);return
        if text=='/status':
            print(json.dumps(dict(mode='states-python',permission=self.allowed(),status=self.engine.model['status'],pending=self.engine.model['pending'],lessons=len(self.engine.model['lessons'])),ensure_ascii=False),flush=True);return
        if text.startswith('/plasticity '):
            value=text.split()[1]
            if value not in ('on','off'):raise ValueError('/plasticity on или /plasticity off')
            self.engine.configure(plasticity=int(value=='on'));self.store.save(self.engine)
            print('Обучение на собственном опыте '+('включено.' if value=='on' else 'выключено.'),flush=True);return
        if text.startswith('/speed '):
            self.seconds=max(.1,min(5,float(text.split()[1])));return
        if text in ('/step','/run'):
            if self.engine.model['phase']!='language' and (self.engine.model.get('imagery') or {}).get('mode')!='imagine':self._arm()
            else:self.abort.clear()
            if self.engine.model['status'] == 'needs-help':
                self.engine.model.update(status='running')
                self.engine.model.pop('perception', None)
                self.engine.model.pop('objectQuestion', None)
                self.engine.model.pop('objectCurrents', None)
            self.pause.clear();self.single=text=='/step';self.running=True;return
        if text in ('3','/record'):
            if not self.last_query:raise ValueError('Сначала введите текст обучаемой команды')
            if self.engine.model['pending']:raise ValueError('Не завершено действие: сначала /reset с проверкой экрана')
            self._arm();self._discard_recording();self.pause.set();self.running=False;self.engine.reset()
            self.schedule=('record',time.monotonic()+2.0)
            print('Через 2 с начинается запись. Вернитесь в рабочее окно, наведите курсор и дождитесь ID объекта в Glaz. После клика ждите строку «Клик зарегистрирован» здесь, в терминале Kolos; после Enter — «Наблюдение записано».',flush=True);return
        if text in ('5','/save'):
            if self.recording:raise ValueError('Сначала остановите запись Esc')
            if not self.record:raise ValueError('Нет завершённой наблюдаемой демонстрации')
            self.staged=self.record;print('Демонстрация подготовлена. 1 — подтвердить; /expose — только прежние клавиши.',flush=True);return
        if text in ('1','/approve','/expose'):
            if not self.staged:raise ValueError('Сначала 3 → действия → Esc → 5')
            self.engine.learn(self.staged,exposure=text=='/expose');self.store.save(self.engine);self.staged=None
            print('Память сохранена отдельно от db_v4.db.',flush=True);return
        if text.startswith('/query '):self.last_query=text[7:];return
        if text.startswith('/'):raise ValueError('Неизвестная команда; /help')
        if self.engine.model['pending']:raise ValueError('Ожидается результат прошлого действия. /reset — явная отмена')
        self.last_query=text
        # Unknown commands can be staged for teaching even with live input disabled.
        try:self.engine.inspect(text)
        except AmbiguousCommand as exc:
            print(str(exc)+'. Ввод не запущен; «Язык → образ» не устраняет расхождение демонстраций.',flush=True)
            return
        except ValueError as exc:
            if (self.engine.model.get('languageMemory') or {}).get('lessons'):
                self.command('/say '+text)
            else:print(str(exc)+' Для обучения действиям нажмите 3; для языка — «Язык → образ».',flush=True)
            return
        from .perception.console import configure_query
        configure_query(self, text)
        self._arm();self.schedule=('start',time.monotonic()+2);print('Через 2 с запуск; вернитесь в целевое окно. F9 — стоп.',flush=True)

    def tick_once(self):
        if self.engine.model.get('phase') == 'episode' and self.engine.model.get('episode'):
            from .episode_console import tick_once
            return tick_once(self)
        if self.engine.model['pending']:
            if self.receipt is None:
                self.engine.tick()
                if self.engine.model['status'] in STOP:
                    self.running=False;self.pause.set();self.store.save(self.engine);return
                p=self.engine.model['pending'];step=self.engine.node(p.get('step'))
                post=self.engine.node(step['post']) if step and step.get('post') else None
                assume_click=bool(step and p['action']['kind']=='click' and step.get('dispatch_only'))
                visual_ack=bool(step and p['action']['kind']=='enter' and step.get('visual_ack'))
                expected=post['key'] if post and p['action']['kind'] in ('click','enter') and not assume_click and not visual_ack else None
                target_focus=(p.get('target_focus') if p.get('network') else self.engine.model['selectedCommand']['focus']) if p['action']['kind']=='key' else None
                followup=click_followup(self.engine.model['memory'],step) if not p.get('relocate') else None
                if followup and p.get('object_concept'): followup=dict(followup, object=p['action']['object'])
                episode=(self.engine.model.get('intent') or {}).get('episode')
                if p.get('network') and episode and step['id']==episode['last']:followup=None
                self.receipt=self.adapter.execute(p,expected=expected,target_focus=target_focus,allow_unexpected=True,assume_click=assume_click,visual_ack=visual_ack,followup=followup)
                message=('Клик отправлен; следующий шаг — Enter без повторного распознавания.'
                         if self.receipt.get('verified_by')=='verified-target-click' else
                         'Результат наблюдён.' if self.receipt.get('effect_observed') else
                         'Клик зарегистрирован, изменение среды не наблюдено.' if assume_click else 'Действие подтверждено свежим наблюдением.')
                print(message+('' if self.receipt.get('verified_by')=='verified-target-click' else
                               ' Подтверждение доставится следующим тактом.'),flush=True)
                self.store.save(self.engine)
                return
            self.engine.tick();ev=self.engine.accept_receipt(self.receipt);self.receipt=None
        else:
            if self.engine.model['phase'] in ('execute','intent'):
                observer=self.adapter or self.observer
                self.engine.observe(observer.observe())
            ev=self.engine.tick()
        print(f"Такт {self.engine.model['tick']}: {ev['kind']} · {ev.get('message','')}",flush=True)
        if ev['kind']=='language-image' and self.language_auto:
            # Recheck explicit live permission after the entire phrase resolves.
            self._arm();self.engine.control_image('act');self.language_auto=False
        if self.engine.model['status'] in STOP:self.running=False;self.pause.set();self.language_auto=False
        self.store.save(self.engine)

    def run(self):
        print(HELP,flush=True)
        print(self.engine.model['message'],flush=True)
        if read_json(self.store.path/'last-attempt.json',) and read_json(self.store.path/'last-attempt.json').get('pending'):
            print('В предыдущем запуске был неподтверждённый эффект. Автовозобновление запрещено; проверьте экран.',flush=True)
        self.hook();threading.Thread(target=self.input_reader,daemon=True).start();next_tick=0
        try:
            while not self.closed:
                try:
                    kind,data=self.queue.get(timeout=.05)
                    if kind=='command':self.command(data)
                    elif kind in ('record-action','bad-record','stop-record'):
                        self._record_event(kind,data)
                except queue.Empty:
                    if self.recording and self.recorder:
                        try:
                            if self.recorder.poll():
                                print('Результат наблюдён в двух свежих кадрах. Можно продолжить или завершить запись.',flush=True)
                        except Exception as exc:
                            self.recorder.invalid=str(exc);self.recording=False
                            print('ОСТАНОВКА НАБЛЮДЕНИЯ: '+str(exc),flush=True)
                except Exception as exc:
                    self.running=False;self.pause.set();self.recording=False
                    if self.recorder:self.recorder.invalid=str(exc)
                    print('ОСТАНОВКА ЗАПИСИ: '+str(exc),flush=True)
                if self.schedule and time.monotonic()>=self.schedule[1]:
                    what=self.schedule[0];self.schedule=None
                    if what != 'object-answer':self.abort.clear()
                    try:
                        if self.adapter:self.adapter.clear_click()
                        if what=='object-answer':
                            from .concept_console import scheduled
                            scheduled(self)
                        elif what=='record':
                            self.recorder=Recorder(self.observer,self.last_query);self.recording=True
                            print('Запись включена. Дождитесь ID объекта в Glaz перед кликом. Esc — закончить.',flush=True)
                        elif what=='imagine':self.engine.imagine(self.pending_goals,self.observer.observe());self.running=True;self.pause.clear()
                        elif what=='image-act':self.engine.observe(self.observer.observe());self.engine.control_image('act');self.running=True;self.pause.clear()
                        elif what=='language':self.engine.start_language(self.pending_phrase,self.observer.observe());self.running=True;self.pause.clear()
                        elif what=='goal':self.engine.start_goals(self.pending_goals,self.observer.observe());self.running=True;self.pause.clear()
                        else:self.engine.start(self.last_query,self.observer.observe());self.running=True;self.pause.clear()
                    except Exception as exc:
                        self.running=False;self.pause.set();self.recording=False
                        print('НЕ ЗАПУЩЕНО: '+str(exc),flush=True)
                if self.running and not self.pause.is_set() and not self.abort.is_set() and time.monotonic()>=next_tick:
                    self.tick_once();next_tick=time.monotonic()+self.seconds
                    if self.single or ((self.engine.model.get('imagery') or {}).get('mode')=='imagine' and ((self.engine.model['tick']-(self.engine.model.get('language') or {}).get('handoffTick',0)>=8) if self.engine.model.get('language') else self.engine.model['tick']%8==0)):self.single=False;self.running=False;self.pause.set()
                self.publish()
        except KeyboardInterrupt:pass
        finally:
            self.abort.set();self.running=False;self.recording=False;self.publish();self.store.save(self.engine)
            for listener in self.hooks:listener.stop()
            self.store.close()


def main(argv=None):
    from .console import configure_console
    configure_console()
    parser=argparse.ArgumentParser();parser.add_argument('--ipc');parser.add_argument('--session');parser.add_argument('--memory');parser.add_argument('--glaz-pid',type=int,default=0)
    parser.add_argument('--selftest',action='store_true');parser.add_argument('--acceptance',action='store_true');args=parser.parse_args(argv)
    if args.acceptance:
        from .capabilities import run
        results=[run(n)[0] for n in range(1,11)];print(json.dumps(results,ensure_ascii=False,indent=2));return 0 if all(r['passed'] for r in results) else 1
    if args.selftest:
        from .simulator import run_case
        results=[run_case(n)[0] for n in range(1,5)];print(json.dumps(results,ensure_ascii=False,indent=2));return 0 if all(r['passed'] for r in results) else 1
    if not args.ipc or not args.session:parser.error('Запускайте States из Glaz: нужен отдельный IPC-сеанс')
    if not args.memory:
        root=hashlib.sha256(str(Path(__file__).resolve().parent.parent).encode()).hexdigest()[:12]
        args.memory=str(Path.home()/'.kolos'/'states-memory'/root)
    terminal=Terminal(args)
    # Command failures must not crash Glaz or restart pending OS effects.
    original_command=terminal.command
    def safe_command(text):
        try:original_command(text)
        except Exception as exc:
            terminal.running=False;terminal.pause.set();print('ОШИБКА: '+str(exc),flush=True)
    terminal.command=safe_command
    original_tick=terminal.tick_once
    def safe_tick():
        try:original_tick()
        except Exception as exc:
            terminal.running=False;terminal.pause.set();print('ОСТАНОВКА: '+str(exc)+'; автоматического повтора нет.',flush=True)
    terminal.tick_once=safe_tick
    terminal.run();return 0

if __name__=='__main__':raise SystemExit(main())
