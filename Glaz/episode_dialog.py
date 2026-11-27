"""Explicit teaching controls for the optional working-episode engine.

This dialog sends user-selected primitives to the existing States subprocess.
It cannot execute a motor operation by itself or choose a task's solution.
"""
from __future__ import annotations
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from kolos_states.ipc import read_json


def show(app):
    if not app._states_bridge.enabled:
        messagebox.showinfo('Рабочий эпизод', 'Выберите «Состояния и цели (ПК)».')
        return None
    win = tk.Toplevel(app.root)
    win.title('Kolos · рабочий эпизод и роли')
    win.geometry('950x690')
    win.minsize(780, 560)
    host = ttk.Frame(win, padding=12)
    host.pack(fill='both', expand=True)
    ttk.Label(host, text='Покажите эпизод один раз: выберите объект и выполните чтение, ввод или активацию.\n'
              'При повторении значения читаются заново, а объекты связываются по признакам, не по координатам.',
              wraplength=890).pack(fill='x', pady=(0, 10))
    toolbar = ttk.Frame(host)
    toolbar.pack(fill='x')
    windows = ttk.Combobox(toolbar, state='readonly')
    windows.pack(side='left', fill='x', expand=True)
    window_ids = []
    status = tk.StringVar(value='Выберите отдельное тестовое окно. Эта панель использует доступные поля UI Automation.')

    def guarded(callback):
        def call():
            try:
                callback()
            except Exception as exc:
                status.set(str(exc))
        return call

    def refresh_windows():
        import uiautomation as auto
        found = []
        with auto.UIAutomationInitializerInThread():
            for c in auto.GetRootControl().GetChildren():
                if c.NativeWindowHandle and c.ProcessId != os.getpid() and c.Name and not c.IsOffscreen:
                    found.append((int(c.NativeWindowHandle), c.Name))
        window_ids[:] = [item[0] for item in found]
        windows.configure(values=[f'{name} · {hwnd}' for hwnd, name in found])
        if found:
            preferred = next((i for i, (_, name) in enumerate(found) if name == 'Kolos working episode'), 0)
            windows.current(preferred)

    def select_window():
        if windows.current() < 0:
            raise ValueError('Выберите окно и нажмите «Прочитать»')
        app._states_send('/episode-window ' + str(window_ids[windows.current()]))
        status.set('Выбранное окно передано ядру. Объекты появятся после свежего наблюдения.')

    ttk.Button(toolbar, text='Окна', command=guarded(refresh_windows)).pack(side='left', padx=4)
    ttk.Button(toolbar, text='Прочитать', command=guarded(select_window)).pack(side='left')
    ttk.Button(toolbar, text='Тестовое окно', command=lambda: app._states_send('/episodepad')).pack(side='left', padx=4)
    query = tk.StringVar(value='Перенеси содержимое поля и сохрани')
    ttk.Label(host, text='Фраза для этого эпизода (при запуске — та же, без самого значения):').pack(anchor='w', pady=(10, 2))
    ttk.Entry(host, textvariable=query).pack(fill='x')
    tree = ttk.Treeview(host, columns=('name', 'type', 'read', 'write', 'value'), show='headings', selectmode='browse', height=10)
    for key, label, width in [('name', 'Объект', 160), ('type', 'Тип', 70), ('read', 'Чтение', 70),
                              ('write', 'Ввод', 70), ('value', 'Наблюдаемое значение', 340)]:
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=key in ('name', 'value'))
    tree.pack(fill='both', expand=True, pady=10)
    row = ttk.Frame(host)
    row.pack(fill='x')
    slot = tk.StringVar(value='v0')
    slots = ttk.Combobox(row, textvariable=slot, values=['v0'], state='readonly', width=8)

    def selected():
        choice = tree.selection()
        if len(choice) != 1:
            raise ValueError('Выберите один объект в таблице')
        return choice[0]

    ttk.Button(row, text='Начать показ', command=lambda: app._states_send('/episode-begin ' + query.get())).pack(side='left')
    ttk.Button(row, text='Прочитать → значение', command=guarded(lambda: app._states_send('/episode-read ' + selected()))).pack(side='left', padx=4)
    slots.pack(side='left')
    ttk.Button(row, text='Ввести значение', command=guarded(lambda: app._states_send('/episode-write ' +
               json.dumps(dict(object=selected(), source=slot.get()), ensure_ascii=False)))).pack(side='left', padx=4)
    ttk.Button(row, text='Активировать', command=guarded(lambda: app._states_send('/episode-activate ' + selected()))).pack(side='left')
    row2 = ttk.Frame(host)
    row2.pack(fill='x', pady=8)
    for label, cmd in [('Сохранить показ', '/episode-save'), ('Обновить объекты', '/episode-objects'),
                       ('Пауза', '/pause'), ('Один такт', '/step'), ('СТОП F9', '/stop'), ('Reset', '/reset')]:
        ttk.Button(row2, text=label, command=lambda c=cmd: app._states_send(c)).pack(side='left', padx=2)
    ttk.Button(row2, text='Выполнить фразу', command=lambda: app._states_send('/episode-run ' + query.get())).pack(side='right')
    ttk.Label(host, textvariable=status, wraplength=890).pack(fill='x', pady=5)
    ttk.Label(host, text='Управление требует отдельного разрешения в главном окне Glaz. F9 — остановка.\n'
              'После ошибки осмотрите форму и выполните Reset: отправленное действие автоматически не повторяется.\n'
              'Нечитаемые, защищённые и неоднозначные поля не угадываются. Показ задаётся этими кнопками, не старой записью клавиш (3).',
              wraplength=890).pack(fill='x')
    last = [None]

    def poll():
        if not win.winfo_exists():
            return
        raw = read_json(app._states_bridge.path / 'status.json') or {}
        if raw.get('session') == app._states_bridge.session:
            items = raw.get('episodeObjects', [])
            signature = json.dumps(items, ensure_ascii=False, sort_keys=True)
            if signature != last[0]:
                choice = tree.selection()
                tree.delete(*tree.get_children())
                for obj in items:
                    desc = obj['descriptor']
                    tree.insert('', 'end', iid=obj['id'], values=(desc['name'] or desc['automation_id'], desc['kind'],
                                'да' if obj['readable'] else 'нет', 'да' if obj['writable'] else 'нет',
                                (obj['value'] or '')[:160] if obj['readable'] else '—'))
                if choice and tree.exists(choice[0]):
                    tree.selection_set(choice)
                last[0] = signature
            known = raw.get('episodeSlots', [])
            slots.configure(values=known or ['v0'])
            if known and slot.get() not in known:
                slot.set(known[-1])
            if raw.get('episodeRecording'):
                status.set('Записано действий: ' + str(raw.get('episodeRecordedCount', 0)) + '. Значения: ' + ', '.join(known))
            elif raw.get('episode'):
                status.set(raw.get('message', ''))
        win.after(350, poll)

    guarded(refresh_windows)()
    win.after(350, poll)
    return win
