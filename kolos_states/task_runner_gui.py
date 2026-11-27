"""Windows desktop interface for choosing a task, running it and seeing its receipt."""
from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk

from . import task_runner
from .ipc import atomic_json

LABELS = {'Codex': 'codex', 'Claude Code': 'claude', 'Только локально': 'none'}
COLOR = '#163d34'


class App:
    def __init__(self, root: tk.Tk, state: Path):
        self.root, self.state = root, state
        self.settings = state / 'settings.json'
        self.completed = Queue()
        self.busy = False
        self.receipt = None
        try:
            settings = task_runner.read_json(self.settings)
        except (OSError, ValueError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        initial = next((name for name, value in LABELS.items() if value == settings.get('provider')), 'Codex')
        self.teacher = tk.StringVar(value=initial)
        self.model = tk.StringVar(value=str(settings.get('model') or ''))
        self.task = tk.StringVar()
        self.input = tk.StringVar()
        self.status = tk.StringVar(value='Выберите задачу и входной файл или откройте пример WB.')

        root.title('Колос')
        root.minsize(660, 565)
        root.geometry('810x660')
        root.configure(background='#f0f3f1')
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#f0f3f1')
        style.configure('TLabel', background='#f0f3f1', foreground='#1b2b26', font=('Segoe UI', 10))
        style.configure('Title.TLabel', foreground=COLOR, font=('Segoe UI', 25, 'bold'))
        style.configure('Hint.TLabel', foreground='#40564c')
        style.configure('TButton', font=('Segoe UI', 10), padding=(10, 6))
        style.configure('Run.TButton', foreground='white', background=COLOR, font=('Segoe UI', 10, 'bold'))
        style.map('Run.TButton', background=[('disabled', '#74827c'), ('active', '#236553')],
                  foreground=[('disabled', 'white')])

        content = ttk.Frame(root, padding=(22, 16, 22, 18))
        content.pack(fill='both', expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(8, weight=1)
        ttk.Label(content, text='Колос', style='Title.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')

        self.file_row(content, 1, 'Задача (JSON)', self.task)
        self.file_row(content, 2, 'Вход (JSON)', self.input)
        examples = ttk.Frame(content)
        examples.grid(row=3, column=1, columnspan=2, sticky='w', pady=(3, 10))
        ttk.Button(examples, text='WB · первый файл', command=lambda: self.example('first')).pack(side='left')
        ttk.Button(examples, text='WB · новый файл', command=lambda: self.example('next')).pack(side='left', padx=8)

        ttk.Label(content, text='Первый урок').grid(row=4, column=0, sticky='w', padx=(0, 14))
        settings_row = ttk.Frame(content)
        settings_row.grid(row=4, column=1, columnspan=2, sticky='ew')
        ttk.Combobox(settings_row, textvariable=self.teacher, values=tuple(LABELS), state='readonly', width=19).pack(side='left')
        ttk.Label(settings_row, text='Модель (необязательно)').pack(side='left', padx=(12, 6))
        ttk.Entry(settings_row, textvariable=self.model, width=19).pack(side='left', fill='x', expand=True)
        ttk.Label(content, text='При уроке модель получает инструкцию и схему. Вход и проверочные примеры остаются локально.',
                  style='Hint.TLabel', wraplength=590).grid(row=5, column=0, columnspan=3, sticky='w', pady=(6, 12))

        actions = ttk.Frame(content)
        actions.grid(row=6, column=0, columnspan=3, sticky='ew')
        self.run_button = ttk.Button(actions, text='Выполнить', style='Run.TButton', command=self.run)
        self.run_button.pack(side='left')
        self.open_button = ttk.Button(actions, text='Открыть отчёт', state='disabled', command=self.open_receipt)
        self.open_button.pack(side='left', padx=8)
        ttk.Label(content, textvariable=self.status, wraplength=590).grid(row=7, column=0, columnspan=3, sticky='w', pady=(11, 6))

        output = ttk.Frame(content)
        output.grid(row=8, column=0, columnspan=3, sticky='nsew')
        self.output = tk.Text(output, height=10, wrap='word', font=('Consolas', 11), background='#ffffff',
                              foreground='#132b21', relief='flat', padx=12, pady=10, borderwidth=0, state='disabled')
        scrollbar = ttk.Scrollbar(output, command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.output.pack(side='left', fill='both', expand=True)

    def file_row(self, parent, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 14), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky='ew')
        ttk.Button(parent, text='Выбрать…', command=lambda: self.browse(variable)).grid(row=row, column=2, padx=(8, 0))

    def browse(self, variable: tk.StringVar) -> None:
        result = filedialog.askopenfilename(parent=self.root, filetypes=[('JSON', '*.json')])
        if result:
            variable.set(result)

    def example(self, file: str) -> None:
        self.task.set(str(task_runner.SAMPLES / 'wb-task.json'))
        self.input.set(str(task_runner.SAMPLES / f'wb-{file}.json'))

    def run(self) -> None:
        if not self.task.get().strip() or not self.input.get().strip():
            self.status.set('Выберите задачу и входной файл.')
            return
        options = dict(provider=LABELS[self.teacher.get()], model=self.model.get().strip() or None)
        try:
            atomic_json(self.settings, options)
        except OSError as error:
            self.status.set(str(error))
            return
        task, data = Path(self.task.get()), Path(self.input.get())
        self.busy = True
        self.run_button.configure(state='disabled')
        self.open_button.configure(state='disabled')
        self.status.set('Выполняется проверка. Если правило новое, Колос запросит урок.')
        self.show(None)
        Thread(target=self.worker, args=(task, data, options), daemon=True).start()
        self.root.after(70, self.poll)

    def worker(self, task: Path, data: Path, options: dict) -> None:
        try:
            report = task_runner.run(task, data, state=self.state, **options)
        except (OSError, ValueError, RuntimeError) as error:
            report = dict(status='error', reason=str(error))
        self.completed.put(report)

    def poll(self) -> None:
        try:
            result = self.completed.get_nowait()
        except Empty:
            self.root.after(70, self.poll)
            return
        self.busy = False
        self.run_button.configure(state='normal')
        self.receipt = result.get('report_path')
        if self.receipt and os.name == 'nt':
            self.open_button.configure(state='normal')
        if result['status'] != 'ok':
            self.status.set(result['reason'])
            self.show(result)
            return
        usage = result['usage']
        counts = result['model_calls']
        tokens = (usage['input_tokens'], usage['output_tokens'])
        consumed = sum(tokens) if None not in tokens else 'нет данных'
        mode = 'Новый урок сохранён' if result['mode'] == 'lesson' else 'Применено сохранённое правило'
        self.status.set(f'{mode}. Вызовы модели: {counts}. Токены: {consumed}.')
        self.show(result['result'])

    def show(self, data: object) -> None:
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        if data is not None:
            self.output.insert('1.0', json.dumps(data, ensure_ascii=False, indent=2))
        self.output.configure(state='disabled')

    def open_receipt(self) -> None:
        if self.receipt:
            try:
                os.startfile(self.receipt)
            except OSError as error:
                self.status.set(str(error))

    def close(self) -> None:
        if self.busy:
            self.status.set('Дождитесь завершения текущего запуска.')
        else:
            self.root.destroy()


def launch(state: Path) -> int:
    root = tk.Tk()
    App(root, state)
    root.mainloop()
    return 0
