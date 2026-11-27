"""Visible, time-bounded notice for an explicitly requested live desktop test."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
import subprocess
import sys
import threading
from typing import Iterator


def watch_notice(process: subprocess.Popen, ready: Queue, stop: threading.Event) -> None:
    """Signal readiness or an explicit stop without touching other applications."""
    for line in process.stdout:
        if line.strip() == 'READY':
            ready.put(True)
        elif line.strip() == 'STOP':
            stop.set()
    stop.set()


@contextmanager
def testing_notice(minutes: int = 3) -> Iterator[threading.Event]:
    """Show an owned banner before input and close it after the test completes."""
    until = (datetime.now() + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    command = [sys.executable, '-B', '-m', 'tests.desktop.experiment_notice',
               '--until', until.isoformat()]
    process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    ready, stop = Queue(), threading.Event()
    threading.Thread(target=watch_notice, args=(process, ready, stop), daemon=True).start()
    try:
        ready.get(timeout=10)
        print('Visible testing notice until ' + until.strftime('%H:%M'), flush=True)
        yield stop
    finally:
        if process.poll() is None:
            process.terminate()  # Only the notice process created above.
        process.wait(timeout=8)
        process.stdout.close()
        process.stderr.close()


def show_notice(until: datetime) -> None:
    """Keep the notice visible; closing it requests a stop at the next safe boundary."""
    import tkinter as tk
    root = tk.Tk()
    root.title('Колос — идёт тестирование')
    root.attributes('-topmost', True)
    root.resizable(False, False)
    root.configure(bg='#fff3bd')
    root.geometry(f'660x170+{max(0, root.winfo_screenwidth() - 690)}+12')
    label = tk.Label(root, text='Идёт тестирование Колоса\nНе пользуйтесь ПК до ' + until.strftime('%H:%M'),
                     font=('Segoe UI', 17, 'bold'), bg='#fff3bd', fg='#292410')
    label.pack(pady=(15, 4))
    tk.Label(root, text='Окно закроется после завершения. Настройки рекламы не меняются.',
             bg='#fff3bd', font=('Segoe UI', 10)).pack()

    def stop() -> None:
        """Request cancellation without killing or controlling any user application."""
        print('STOP', flush=True)
        root.destroy()

    def deadline() -> None:
        """End the allowed testing interval instead of silently overrunning it."""
        print('STOP', flush=True)
        label.configure(text='Время теста истекло — завершаем проверку')

    tk.Button(root, text='Остановить тест', command=stop).pack(pady=8)
    root.protocol('WM_DELETE_WINDOW', stop)
    root.after(max(1, int((until - datetime.now()).total_seconds() * 1000)), deadline)
    root.update()
    print('READY', flush=True)
    root.mainloop()


def main() -> None:
    """Run only the explicitly created notice window."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--until', required=True)
    args = parser.parse_args()
    show_notice(datetime.fromisoformat(args.until))


if __name__ == '__main__':
    main()
