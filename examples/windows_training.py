"""Teach a shared Kolos memory from real Windows applications and reuse it for new tasks."""

from __future__ import annotations

import argparse
import hashlib
import operator
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kolos_states.accessibility import Accessibility
from kolos_states.core import STOP, StateEngine
from kolos_states.desktop import DesktopAdapter, WindowsMotor
from kolos_states.ipc import atomic_json
from kolos_states.osworld.agent import Unconfirmed, run_agent
from kolos_states.protocol import persistent_graph
from kolos_states.recorder import Recorder
from kolos_states.storage import Store

OUTPUT = ROOT / 'tests' / 'desktop-output' / 'windows-training'
NOTE_LESSONS = ('заказ 12345', 'товар 67890', 'оплата готова', 'код для партии')
NOTE_TASKS = ('код товара 730', 'заказ 286', 'товар 904', 'оплата 147', 'партия 562')
CALC_LESSONS = ((2, '+', 3), (14, '+', 7), (9, '-', 5), (21, '-', 10), (3, '*', 4), (12, '*', 2))
CALC_TASKS = ((6, '+', 8), (31, '+', 29), (92, '+', 41), (22, '+', 22), (17, '+', 54),
              (24, '-', 7), (8, '-', 13), (55, '-', 55), (99, '-', 68), (43, '-', 19),
              (7, '*', 9), (24, '*', 6), (19, '*', 13), (17, '*', 17), (56, '*', 23))
OPERATOR_BUTTON = {'+': 'plusButton', '-': 'minusButton', '*': 'multiplyButton'}
OPERATOR_SCORE = {'+': operator.add, '-': operator.sub, '*': operator.mul}
SYMBOLS = str.maketrans({'−': '-', '×': '*', '✕': '*', '∗': '*'})


def store_memory(path, engine=None):
    store = Store(path)
    try:
        if engine is None:
            return store.load()
        store.save(engine)
    finally:
        store.close()


def digest(path):
    return hashlib.sha256((path / 'memory.json').read_bytes()).hexdigest()


@contextmanager
def notepad(output):
    import uiautomation as auto

    if auto.WindowControl(searchDepth=1, RegexName=r'.*(Блокнот|Notepad).*').Exists(0, 0):
        raise RuntimeError('Для опыта требуется временное окно. Сейчас в Блокноте уже открыто окно.')
    with TemporaryDirectory(prefix='note-', dir=output) as directory:
        path = Path(directory) / (Path(directory).name + '.txt')
        path.write_text('', encoding='utf-8')
        launcher = subprocess.Popen(['notepad.exe', str(path)])
        window = auto.WindowControl(searchDepth=1, RegexName='.*' + re.escape(path.stem) + '.*')
        if not window.Exists(12, .2):
            raise RuntimeError('Тестовое окно Блокнота не открылось.')
        try:
            window.SetActive()
            editor = window.EditControl(searchDepth=8)
            if not editor.Exists(3, .2):
                raise RuntimeError('Поле Блокнота недоступно через UI Automation.')
            editor.SetFocus()
            note = Note(window.NativeWindowHandle, editor)
            deadline = time.monotonic() + 3
            while True:
                try:
                    note.observe()
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.05)
            yield note
        finally:
            if window.Exists(0, 0):
                window.SetActive()
                window.SendKeys('{Ctrl}s', waitTime=.3)
                window.GetWindowPattern().Close()
            launcher.wait(timeout=5)


class Note:
    def __init__(self, handle, editor):
        self.handle, self.editor = handle, editor
        self.reader, self.motor = Accessibility(), WindowsMotor()
        self.version = 0
        self.focus = None

    def observe(self, **_kwargs):
        actual = self.reader.read()
        if actual.get('foreground') != self.handle:
            raise RuntimeError('Ввод остановлен. Фокус должен быть в тестовом поле Блокнота.')
        if not actual['readable']:
            raise RuntimeError('Блокнот не предоставил текст поля. ' + actual['reason'])
        if self.focus is None:
            self.focus = actual['focus']
        if self.focus != actual['focus']:
            raise RuntimeError('Ввод остановлен. В тестовом окне изменилось поле ввода.')
        self.version += 1
        timestamp = time.time()
        return dict(features=[actual['window'], 'focus:' + actual['focus']], icons=[], selected='',
                    focus=actual['focus'], output=actual['output'], readable=True, own_focus=False,
                    reason='', cursor=dict(x=0, y=0), version=self.version,
                    captured_at=timestamp, observed_at=timestamp)

    def reset(self):
        self.observe()
        self.editor.SendKeys('{Ctrl}a{Back}', waitTime=.1)
        initial = self.observe()
        if initial['output'] != '':
            raise RuntimeError('Не удалось очистить временный документ.')
        return initial

    def teach(self, engine, value):
        self.reset()
        recorder = Recorder(self, 'Впиши ' + value)
        for char in value:
            action = dict(kind='key', value=char)
            pressed = time.time()
            self.motor.send(action)
            recorder.capture(action, time.time(), pressed_at=pressed)
        if self.observe()['output'] != value:
            raise RuntimeError('Блокнот не подтвердил учебный ввод.')
        engine.learn(recorder.finish())

    def attempt(self, engine, value):
        query = 'Впиши ' + value
        initial = self.reset()
        adapter = DesktopAdapter(self, self.motor, allow=lambda: True)
        sent = 0
        try:
            engine.start(query, initial)
        except ValueError as exc:
            status, reason = 'unknown', str(exc)
        else:
            for _ in range(600):
                if engine.model['status'] in STOP:
                    break
                engine.tick()
                pending = engine.model['pending']
                if pending:
                    sent += 1
                    engine.accept_receipt(adapter.execute(pending, target_focus=initial['focus']))
            status, reason = engine.model['status'], engine.model['message']
        observed = self.observe()['output']
        return dict(app='Блокнот', task=query, expected=value, observed=observed, actions=sent,
                    status=status, reason=reason, passed=status == 'complete' and observed == value)


@contextmanager
def calculator():
    import uiautomation as auto

    window = auto.WindowControl(searchDepth=1, RegexName=r'^(Calculator|Калькулятор)$')
    if window.Exists(0, 0):
        raise RuntimeError('Для опыта требуется временное окно. Сейчас Калькулятор уже открыт.')
    subprocess.Popen(['calc.exe'])
    if not window.Exists(12, .2):
        raise RuntimeError('Тестовое окно Калькулятора не открылось.')
    try:
        yield window
    finally:
        if window.Exists(0, 0):
            window.GetWindowPattern().Close()


class Calculation:
    """Use live UI Automation values to confirm each learned binding before continuing."""

    def __init__(self, window, case):
        self.window = window
        self.left, self.symbol, self.right = case
        self.display = window.TextControl(searchDepth=12, AutomationId='NormalOutput')
        self.expression = window.TextControl(searchDepth=12, AutomationId='CalculatorExpression')
        self.intent = self
        self.checkpoint = 'start'
        self.trace = []
        prefix = f'{self.left}{self.symbol}'
        self.rules = {
            'calculator.left': ('start', 'left', self.digits(self.left), ''),
            'calculator.operator': ('left', 'operator', ((OPERATOR_BUTTON[self.symbol], str(self.left)),), prefix),
            'calculator.right': ('operator', 'right', self.digits(self.right), prefix),
            'calculator.equals': ('right', 'done', (('equalButton', None),), f'{prefix}{self.right}='),
        }
        self.press('clearButton')
        self.wait_for('0', '')

    @staticmethod
    def digits(value):
        text = str(value)
        return tuple((f'num{digit}Button', text[:index + 1]) for index, digit in enumerate(text))

    def features(self, checkpoint):
        return [f'windows:calculator:{OPERATOR_BUTTON[self.symbol]}:{checkpoint}']

    def observe(self):
        return dict(features=self.features(self.checkpoint), gui_actions=list(self.rules), icons=[],
                    selected='', focus='', output='', cursor=dict(x=0, y=0))

    def actual(self):
        value = re.sub(r'\s+', '', self.display.Name.translate(SYMBOLS))
        if re.fullmatch(r'-?[0-9]{1,3}(?:,[0-9]{3})+', value):
            value = value.replace(',', '')
        label = re.sub(r'\b(?:минус|minus)\b', '-', self.expression.Name, flags=re.IGNORECASE)
        expression = re.sub(r'[^0-9+*=-]', '', label.translate(SYMBOLS))
        return value, expression

    def wait_for(self, display, expression):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            actual, observed_expression = self.actual()
            if observed_expression == expression and (actual == display or display is None and re.fullmatch(r'-?[0-9]+', actual)):
                return actual, observed_expression
            time.sleep(.025)
        raise Unconfirmed(f'Калькулятор не подтвердил ожидаемое состояние. Дисплей {self.display.Name!r}, '
                          f'выражение {self.expression.Name!r}')

    def press(self, button_id):
        button = self.window.ButtonControl(searchDepth=12, AutomationId=button_id)
        if not button.Exists(3, .1) or not button.IsEnabled:
            raise Unconfirmed(f'Кнопка Калькулятора недоступна: {button_id}')
        button.GetInvokePattern().Invoke()

    def perform(self, request_id, action):
        binding = action['binding']
        old, new, presses, expression = self.rules[binding]
        if self.checkpoint != old:
            raise Unconfirmed(f'Действие {binding} неприменимо в состоянии {self.checkpoint}')
        before = self.observe()
        entry = dict(binding=binding, presses=[])
        self.trace.append(entry)
        for button, display in presses:
            self.press(button)
            entry['presses'].append(button)
            entry['display'], entry['expression'] = self.wait_for(display, expression)
        self.checkpoint = new
        return dict(id=request_id, action=action, before=before, after=self.observe(), ok=True,
                    effect_observed=True, verified_by='windows-uia')

    def teach(self, engine):
        receipts = [self.perform(f'learning:{index}', dict(kind='gui', binding=binding))
                    for index, binding in enumerate(self.rules)]
        expected = str(OPERATOR_SCORE[self.symbol](self.left, self.right))
        if self.actual()[0] != expected:
            raise RuntimeError('Учебный результат Калькулятора не подтверждён.')
        engine.learn(dict(query='Операция ' + self.symbol, receipts=receipts))

    def attempt(self, engine):
        result = run_agent(engine, self)
        observed, expression = self.actual()
        expected = str(OPERATOR_SCORE[self.symbol](self.left, self.right))
        return dict(app='Калькулятор', task=f'{self.left} {self.symbol} {self.right}', expected=expected,
                    observed=observed, expression=expression, status=result['agent_status'],
                    reason=result['reason'], actions=sum(len(step['presses']) for step in self.trace),
                    trace=self.trace, passed=result['agent_status'] == 'complete' and observed == expected)


def train(output):
    engine = StateEngine()
    engine.configure(plasticity=0)
    store_memory(output / 'cold', engine)
    with notepad(output) as note:
        for value in NOTE_LESSONS:
            note.teach(engine, value)
    with calculator() as window:
        for case in CALC_LESSONS:
            Calculation(window, case).teach(engine)
    store_memory(output / 'trained', engine)
    return dict(lessons=len(engine.model['lessons']), notepad=list(NOTE_LESSONS), calculator=list(CALC_LESSONS),
                sha256=digest(output / 'trained'))


def frozen_attempt(path, execute):
    engine = store_memory(path)
    initial = persistent_graph(engine.model['memory'])
    result = execute(engine)
    if persistent_graph(engine.model['memory']) != initial:
        raise RuntimeError('Память изменилась во время контрольной попытки.')
    return result


def verify(output):
    report = dict(snapshots={arm: digest(output / arm) for arm in ('cold', 'trained')}, trials=[])
    for application, cases in ((notepad, NOTE_TASKS), (calculator, CALC_TASKS)):
        opener = notepad(output) if application is notepad else calculator()
        with opener as window:
            for case in cases:
                for arm in ('cold', 'trained'):
                    if application is notepad:
                        outcome = frozen_attempt(output / arm, lambda engine: window.attempt(engine, case))
                    else:
                        outcome = frozen_attempt(output / arm, Calculation(window, case).attempt)
                    report['trials'].append(dict(arm=arm, **outcome))
                    atomic_json(output / 'verification.json', report)
    if any(digest(output / arm) != fingerprint for arm, fingerprint in report['snapshots'].items()):
        raise RuntimeError('Сохранённый снимок памяти изменился во время проверки.')
    report['tasks'] = len(report['trials']) // 2
    report['solved'] = {arm: sum(row['arm'] == arm and row['passed'] for row in report['trials'])
                        for arm in report['snapshots']}
    atomic_json(output / 'verification.json', report)
    return dict(tasks=report['tasks'], solved=report['solved'])


def execute_task(output, query):
    if not (output / 'trained' / 'memory.json').is_file():
        raise RuntimeError('Сначала запустите обучение в режиме train.')
    if query.casefold().startswith('впиши ') and 1 <= len(query[6:]) <= 48 and query[6:].isprintable():
        with notepad(output) as note:
            return frozen_attempt(output / 'trained', lambda engine: note.attempt(engine, query[6:]))
    expression = re.fullmatch(r'(?:Посчитай\s+)?([1-9][0-9]?)\s*([+*\-])\s*([1-9][0-9]?)', query.translate(SYMBOLS), re.IGNORECASE)
    if expression:
        left, symbol, right = expression.groups()
        with calculator() as window:
            return frozen_attempt(output / 'trained', Calculation(window, (int(left), symbol, int(right))).attempt)
    raise ValueError('Поддерживаются «Впиши <строка>» и выражения вроде «Посчитай 24 * 7».')


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('train', 'verify', 'task'))
    parser.add_argument('query', nargs='?')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Для запуска нужны нативные приложения Windows.')
    if (args.mode == 'task') != bool(args.query):
        parser.error('Укажите задание в кавычках для режима task.')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if args.mode == 'train':
            result = train(args.output)
            atomic_json(args.output / 'training.json', result)
        elif args.mode == 'verify':
            result = verify(args.output)
        else:
            result = execute_task(args.output, args.query)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps(result, ensure_ascii=True))
    if args.mode == 'verify':
        return int(result['solved']['trained'] != result['tasks'])
    return int(args.mode == 'task' and not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
