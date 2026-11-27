"""Human Ready/Stop gate for a bounded, visible XWAY browser experiment."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tkinter as tk

MOSCOW = timezone(timedelta(hours=3))
OUTPUT = Path(__file__).resolve().parents[2] / 'tests' / 'desktop-output'


def directory(value: str) -> Path:
    """Keep every gate and experiment artifact inside the test output directory."""
    path = Path(value).resolve()
    if path == OUTPUT.resolve() or not path.is_relative_to(OUTPUT.resolve()):
        raise ValueError('Experiment directory must be inside tests/desktop-output')
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, value: dict) -> None:
    """Publish one small local state atomically."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def check_gate(path: Path) -> dict:
    """Never equate elapsed time, a displayed window, or agent input with Ready."""
    gate = json.loads((path / 'gate.json').read_text(encoding='utf-8'))
    if gate.get('state') != 'running' or not gate.get('human_ready_utc'):
        raise PermissionError('Waiting for the human Ready button, or test stopped')
    if datetime.now(timezone.utc).timestamp() >= gate['deadline']:
        raise PermissionError('The testing interval expired')
    return gate


class ReadyWindow:
    """An owned notice window; it never sends input to the browser."""

    def __init__(self, path: Path, minutes: int, *, browser: str = 'Встроенный браузер Codex',
                 preflight: bool = False) -> None:
        self.path, self.minutes = path, minutes
        self.browser, self.preflight = browser, preflight
        self.state = dict(state='waiting', human_ready_utc=None, deadline=None)
        self.root = tk.Tk()
        self.root.title('Колос — подготовка опыта XWAY')
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#fff3bd')
        self.root.geometry(f'700x340+{max(0, self.root.winfo_screenwidth()-730)}+15')
        self.root.resizable(False, False)
        self.heading = tk.Label(self.root, text='Откройте вкладку XWAY и нажмите «Готово»',
                                font=('Segoe UI', 16, 'bold'), bg='#fff3bd', wraplength=665)
        self.heading.pack(padx=15, pady=(15, 8))
        self.message = tk.Label(self.root, font=('Segoe UI', 11), bg='#fff3bd',
                                justify='left', wraplength=665,
                                text=self._instructions())
        self.message.pack(padx=15, pady=5)
        self.ready_button = tk.Button(self.root, text='Готово', font=('Segoe UI', 14), command=self.ready)
        self.ready_button.pack(pady=5)
        self.stop_button = tk.Button(self.root, text='Остановить / отменить', command=self.stop)
        self.stop_button.pack()
        self.root.protocol('WM_DELETE_WINDOW', self.stop)
        write_json(self.path / 'gate.json', self.state)
        self.root.after(300, self.poll)

    def _instructions(self) -> str:
        """Describe the selected browser and the real first stage of this run."""
        stage = ('Сначала проверка доступа; затем показ и самостоятельный повтор.\n'
                 if self.preflight else 'Показ → обновление → повторный поиск и чтение.\n')
        return (self.browser + ' → магазин Кузьменко С. В. ИП.\n'
                'Разверните окно браузера и выберите вкладку XWAY.\n'
                'Товар 11016-70х12 · WB ID 1391386148.\n' + stage +
                'Дневной бюджет: 100 → 105 → 100 ₽.\n'
                'До нажатия кнопки опыт не начнётся.')

    def ready(self) -> None:
        """Only this user button arms the experiment and starts its time limit."""
        if self.state['state'] != 'waiting':
            return
        now = datetime.now(timezone.utc)
        end = now + timedelta(minutes=self.minutes)
        self.state.update(state='running', human_ready_utc=now.isoformat(), deadline=end.timestamp())
        write_json(self.path / 'gate.json', self.state)
        self.heading.configure(text='Идёт тестирование Колоса\nНе пользуйтесь ПК до ' + end.astimezone(MOSCOW).strftime('%H:%M'))
        self.message.configure(text=('Проверка чтения окна. Реклама пока не изменяется.\n' if self.preflight else
                               'Тест запущен. Бюджет: 100 → 105 → 100 ₽.\n') +
                               'Окно закроется после завершения.\n'
                               'При остановке проверьте итоговый бюджет в отчёте.')
        self.ready_button.configure(state='disabled', text='Тест начат')
        print('HUMAN_READY', flush=True)

    def stop(self) -> None:
        """Revoke further dispatch; never perform an unconfirmed compensating action."""
        if self.state['state'] not in ('blocked', 'complete'):
            self.state['state'] = 'stopped'
        write_json(self.path / 'gate.json', self.state)
        print('STOP', flush=True)
        self.root.destroy()

    def _block(self, message: str) -> None:
        """Revoke the gate while leaving a clear diagnostic visible to the user."""
        self.state.update(state='blocked', reason=message)
        write_json(self.path / 'gate.json', self.state)
        self.heading.configure(text='Опыт остановлен — ПК свободен')
        self.message.configure(text=message)
        self.ready_button.configure(state='disabled', text='Проверка не пройдена')
        self.stop_button.configure(text='Закрыть')

    def poll(self) -> None:
        """Display host progress and close only on an explicit completion message."""
        control = self.path / 'notice-control.json'
        if control.exists():
            message = json.loads(control.read_text(encoding='utf-8'))
            if message.get('blocked'):
                self._block(message.get('message', 'Доступ не подтверждён.'))
                return
            if message.get('done'):
                self.state['state'] = 'complete'
                write_json(self.path / 'gate.json', self.state)
                self.root.destroy()
                return
            if message.get('message'):
                self.message.configure(text=message['message'])
        if self.state['state'] == 'running' and datetime.now(timezone.utc).timestamp() >= self.state['deadline']:
            self.stop()
            return
        self.root.after(300, self.poll)


def main() -> None:
    """Launch the requested Ready dialog, with no browser-control capabilities."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--minutes', type=int, default=20)
    parser.add_argument('--browser', default='Встроенный браузер Codex')
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.minutes <= 30:
        parser.error('Testing window must be 1-30 minutes')
    ReadyWindow(directory(args.directory), args.minutes, browser=args.browser, preflight=args.preflight).root.mainloop()


if __name__ == '__main__':
    main()
