"""Nonmodal, correlated object question. This UI cannot click or modify memory."""
from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox


def restore_window(handle: int) -> bool:
    """Restore the question's original window only; the motor rechecks it later."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.IsWindow.argtypes = [w.HWND]
        user.SetForegroundWindow.argtypes = [w.HWND]
        return bool(user.IsWindow(handle) and user.SetForegroundWindow(handle))
    except (OSError, TypeError, ValueError):
        return False


class ObjectQuestionDialog(tk.Toplevel):
    def __init__(self, app: object, question: dict):
        super().__init__(app.root)
        self.app = app; self.question = question; self.replied = False; self.images = []
        self.title('Kolos · уточнение объекта')
        self.geometry('660x490'); self.minsize(580, 450)
        self.transient(app.root)
        self.protocol('WM_DELETE_WINDOW', lambda: self.reply('unsure'))
        self.bind('<Escape>', lambda event: (self.reply('unsure'), 'break')[1])
        # Enter deliberately does not approve a pending motor target.
        body = ttk.Frame(self, padding=18); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Это нужный объект?', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Задача: '+question['query'], wraplength=610).pack(anchor='w', pady=(5, 12))
        text = ('Ожидался '+question['expected']+', но в выбранной области распознан '+question['actual']+
                '. Ожидаемый ID не найден в полном наблюдении. Действие остановлено.')
        ttk.Label(body, text=text, wraplength=610).pack(anchor='w')
        previews = ttk.Frame(body); previews.pack(fill='both', expand=True, pady=12)
        for column, (label, identifier) in enumerate([('Ожидаемый образ', question['expected']), ('Наблюдаемый образ', question['actual'])]):
            frame = ttk.LabelFrame(previews, text=label+' · '+identifier, padding=8)
            frame.grid(row=0, column=column, sticky='nsew', padx=(0, 8) if column == 0 else (8, 0))
            previews.columnconfigure(column, weight=1)
            self.preview(frame, identifier, current=column == 1)
        previews.rowconfigure(0, weight=1)
        ttk.Label(body, text='«Да» добавит зрительный вид к общему ансамблю только для этого участка задачи и контекста. '
                  'Это не подтверждение успешного результата. Перед действием будет новый осмотр.',
                  wraplength=610).pack(anchor='w', pady=(0, 12))
        buttons = ttk.Frame(body); buttons.pack(fill='x')
        self.yes = ttk.Button(buttons, text='Да, запомнить', command=lambda: self.reply('yes'))
        self.yes.pack(side='left')
        ttk.Button(buttons, text='Нет', command=lambda: self.reply('no')).pack(side='left', padx=8)
        unsure = ttk.Button(buttons, text='Не знаю / остановить', command=lambda: self.reply('unsure'))
        unsure.pack(side='right'); unsure.focus_set()
        ttk.Label(body, text='Срок ответа — 2 минуты. F9 — аварийная остановка.', wraplength=610).pack(anchor='w', pady=(12, 0))

    def preview(self, parent: object, identifier: str, *, current: bool) -> None:
        from PIL import Image, ImageTk
        image = None; note = 'Нет сохранённого изображения'
        if current:
            frame = getattr(self.app._states_bridge, '_preview_frame', None)
            if frame and frame[1] == self.question['captured_at']:
                source, _, monitor = frame; l, t, r, b = self.question['bbox']
                region = (max(0, int(l-monitor['left']-10)), max(0, int(t-monitor['top']-10)),
                          min(source.width, int(r-monitor['left']+10)), min(source.height, int(b-monitor['top']+10)))
                if region[2] > region[0] and region[3] > region[1]:
                    image = source.crop(region); note = 'Фрагмент кадра, вызвавшего вопрос'
        if image is None:
            directory = Path(getattr(self.app, '_screenshots_dir', Path(__file__).parent/'object_screenshots'))
            path = directory/('object_'+identifier.split('.')[-1]+'_zoomed.png')
            if path.is_file():
                try:
                    with Image.open(path) as source: image = source.copy()
                    note = 'Сохранённый зрительный образ'
                except OSError:
                    pass
        if image is not None:
            image.thumbnail((230, 135))
            if image.width < 80 and image.height < 80:
                image = image.resize((image.width*3, image.height*3), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(image, master=self); self.images.append(photo)
            ttk.Label(parent, image=photo).pack(expand=True)
        ttk.Label(parent, text=note, wraplength=240, anchor='center').pack(pady=8)

    def reply(self, choice: str) -> None:
        if self.replied:
            return
        self.replied = True
        self.destroy()
        if choice == 'yes':
            restore_window(self.question['foreground'])
        self.app._states_send('/object-answer '+json.dumps(dict(id=self.question['id'], choice=choice)))

    def dismiss(self) -> None:
        self.replied = True
        if self.winfo_exists(): self.destroy()


def poll_question(app: object, status: dict, *, force: bool = False) -> None:
    if status.get('session') != app._states_bridge.session:
        return
    question = status.get('objectQuestion')
    old = getattr(app, '_object_question_dialog', None)
    if not question:
        if old and old.winfo_exists(): old.dismiss()
        return
    if not force and getattr(app, '_object_question_shown', None) == question['id']:
        return
    if old and old.winfo_exists(): old.dismiss()
    app._object_question_shown = question['id']
    app._object_question_dialog = ObjectQuestionDialog(app, question)


def show_pending(app: object) -> None:
    from kolos_states.ipc import read_json
    status = read_json(app._states_bridge.path/'status.json') or {}
    if status.get('session') != app._states_bridge.session or not status.get('objectQuestion'):
        messagebox.showinfo('Kolos', 'Сейчас нет вопроса об объекте.', parent=app.root)
        return
    poll_question(app, status, force=True)
