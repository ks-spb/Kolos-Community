"""Teach paired visual regions on a frozen screenshot, never on live controls."""
from __future__ import annotations

import time
import uuid
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from Glaz.cursor_target import pointed_bbox_index
from kolos_states.ipc import atomic_json, read_json
from kolos_states.perception.help import VISUAL_HELP
from .retina import lesson


class VisualTeacher:
    """Explicit human supervision of spatial parts and optional command grounding."""

    def __init__(self, app: object):
        self.app = app; self.bridge = app._states_bridge
        self.win = tk.Toplevel(app.root); self.win.title('Колос · Обучить составной объект')
        self.win.geometry('1120x850'); self.frame = None; self.boxes = []
        self.icon = None; self.label = None; self.photo = None; self.start = None; self.pending = None
        self.name = tk.StringVar(value='Новый объект'); self.target = tk.StringVar(value='Новый образ')
        self.query = tk.StringVar(); self.object_id = tk.StringVar(); self.mode = tk.StringVar(value='icon')
        self.clipped = tk.StringVar(value='Полная подпись'); self.message = tk.StringVar(value='Получите снимок целевого экрана.')
        self._controls(); self._catalog()
        self.win.protocol('WM_DELETE_WINDOW', self.win.destroy)

    def _controls(self) -> None:
        """Teach geometry through the snapshot; names are display-only annotations."""
        ttk.Label(self.win, text='На снимке: щёлкните по значку, затем выделите подпись рамкой. '
                  'Показывайте полную подпись первым примером.', wraplength=1060).pack(padx=12, pady=8)
        top = ttk.Frame(self.win); top.pack(fill='x', padx=12)
        ttk.Button(top, text='Снимок через 3 с', command=self._schedule).pack(side='left')
        ttk.Radiobutton(top, text='1. Значок', variable=self.mode, value='icon').pack(side='left', padx=10)
        ttk.Radiobutton(top, text='2. Подпись', variable=self.mode, value='label').pack(side='left')
        ttk.Button(top, text='Сбросить области', command=self._clear).pack(side='left', padx=10)
        ttk.Button(top, text='Подсказки', command=self._help).pack(side='left')
        form = ttk.Frame(self.win); form.pack(fill='x', padx=12, pady=8)
        self.targets = self._field(form, 0, 'Образ / новый вариант', self.target)
        self._field(form, 1, 'Имя для просмотра', self.name, combo=False)
        self.queries = self._field(form, 2, 'Команда (можно оставить пустой)', self.query)
        self.objects = self._field(form, 3, 'Объект команды', self.object_id)
        self.clips = self._field(form, 4, 'Видимость', self.clipped)
        self.clips.configure(values=['Полная подпись', 'Обрезано справа', 'Обрезано слева', 'Обрезано сверху', 'Обрезано снизу'], state='readonly')
        self.targets.bind('<<ComboboxSelected>>', self._target_changed)
        self.queries.bind('<<ComboboxSelected>>', self._query_changed)
        self.canvas = tk.Canvas(self.win, bg='#202932', height=460, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=12)
        self.canvas.bind('<ButtonPress-1>', self._press)
        self.canvas.bind('<B1-Motion>', self._drag)
        self.canvas.bind('<ButtonRelease-1>', self._release)
        ttk.Label(self.win, textvariable=self.message, wraplength=1060).pack(padx=12, pady=8)
        self.save = ttk.Button(self.win, text='Подтвердить показ и сохранить', command=self._save)
        self.save.pack(pady=(0, 12))

    def _help(self) -> None:
        """Show the same practical guide available in the terminal."""
        messagebox.showinfo('Как обучить значок и подпись', VISUAL_HELP, parent=self.win)

    @staticmethod
    def _field(parent: object, row: int, title: str, variable: object, *, combo: bool = True) -> object:
        """Build one consistent labelled input."""
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=2)
        widget = ttk.Combobox(parent, textvariable=variable, width=62) if combo else ttk.Entry(parent, textvariable=variable, width=65)
        widget.grid(row=row, column=1, sticky='ew', pady=2); parent.columnconfigure(1, weight=1)
        return widget

    def _status(self) -> dict:
        """Do not treat a stale status from another session as the current process."""
        raw = read_json(self.bridge.path/'status.json') or {}
        return raw if raw.get('session') == self.bridge.session else {}

    def _catalog(self) -> None:
        """List learned objects and commands without accessing application labels."""
        raw = self._status(); self.catalog = raw.get('visualCatalog', {})
        self.target_map = {'Новый образ': None}
        self.target_map.update({n['id']+' · '+n['name']: n['id'] for n in self.catalog.get('targets', [])})
        self.targets.configure(values=list(self.target_map), state='readonly')
        queries = [c['query'] for c in self.catalog.get('commands', [])]
        self.queries.configure(values=['']+queries)
        if raw.get('query') in queries:
            self.query.set(raw['query'])
        self._query_changed()

    def _query_changed(self, event: object = None) -> None:
        """An association is scoped to the explicitly selected learned command."""
        command = next((c for c in self.catalog.get('commands', []) if c['query'] == self.query.get()), {})
        choices = command.get('objects', []); self.objects.configure(values=choices)
        if self.object_id.get() not in choices:
            self.object_id.set(choices[0] if choices else '')

    def _target_changed(self, event: object = None) -> None:
        """Adding a view reuses the assembly, not a new global icon ID."""
        target = self.target_map.get(self.target.get())
        entry = next((n for n in self.catalog.get('targets', []) if n['id'] == target), None)
        if entry:
            self.name.set(entry['name'])
            self.message.set('Дополнительный вид знакомого объекта: получите снимок, '
                             'покажите значок и подпись в новом виде, затем подтвердите показ.')
        else:
            self.message.set('Новый объект: задайте имя, покажите значок и полную подпись. '
                             'Для ещё одного вида знакомого объекта выберите его образ в списке.')

    def _schedule(self) -> None:
        """Give the user time to expose the intended screen before freezing it."""
        if self.pending:
            return
        self.app._states_send('/pause')
        self.win.withdraw(); self.app.root.after(3000, self._snapshot)

    def _snapshot(self) -> None:
        """Snapshot source pixels and detector boxes using the same Glaz pipeline."""
        if not self.win.winfo_exists():
            return
        self.win.deiconify()
        capture = getattr(self.app, '_states_frame', None)
        if not capture or time.time()-capture[1] > 3 or not self.app.capture.is_capturing:
            self.message.set('Нет свежего снимка: включите захват нужного монитора.'); return
        self.frame = capture[0].copy(); self.threshold = int(self.app.peaks_threshold.get())
        detected = self.app._compute_peaks_and_objects(self.frame, self.threshold, bool(self.app.peaks_invert.get()))
        self.boxes = [list(obj.bbox) for obj in detected.objects]
        self.scale = min(1060/self.frame.width, 460/self.frame.height, 1)
        display = self.frame.resize((round(self.frame.width*self.scale), round(self.frame.height*self.scale)), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(display, master=self.win)
        self.canvas.delete('all'); self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        self._clear(); self.message.set('Щёлкните по центру значка. Затем обведите его подпись.')

    def _clear(self) -> None:
        """Discard only the unconfirmed example."""
        self.icon = None; self.label = None; self.start = None; self.mode.set('icon')
        self.canvas.delete('region'); self.canvas.delete('drag')

    def _point(self, event: object) -> tuple[int, int]:
        """Translate preview coordinates back to source pixels."""
        return round(event.x/self.scale), round(event.y/self.scale)

    def _press(self, event: object) -> None:
        """Choose a detector instance or begin a label rectangle."""
        if self.frame is None or self.pending:
            return
        point = self._point(event)
        if self.mode.get() == 'icon':
            index = pointed_bbox_index(self.boxes, point)
            if index is None:
                self.message.set('Здесь нет однозначного контура значка. Укажите его центр.'); return
            self.icon = self.boxes[index]; self.mode.set('label'); self._draw()
            self.message.set('Значок выбран. Обведите его подпись рамкой: нажмите в одном углу '
                             'и протяните до противоположного. Не захватывайте подписи соседей.')
        else:
            self.start = point

    def _drag(self, event: object) -> None:
        """Show a proposed region without teaching it yet."""
        if self.start is None:
            return
        x, y = self._point(event); self.canvas.delete('drag')
        self.canvas.create_rectangle(self.start[0]*self.scale, self.start[1]*self.scale,
                                     x*self.scale, y*self.scale, outline='#ffd166', width=2, tags='drag')

    def _release(self, event: object) -> None:
        """Freeze the selected label extent for explicit review."""
        if self.start is None:
            return
        x, y = self._point(event); sx, sy = self.start; self.start = None
        self.label = [min(x, sx), min(y, sy), max(x, sx), max(y, sy)]
        self.canvas.delete('drag'); self._draw()

    def _draw(self) -> None:
        """Display exactly the two regions that will produce learned features."""
        self.canvas.delete('region')
        for bbox, color in [(self.icon, '#59d7cf'), (self.label, '#ffd166')]:
            if bbox:
                self.canvas.create_rectangle(*(v*self.scale for v in bbox), outline=color, width=2, tags='region')
        if self.icon and self.label:
            self.message.set('Проверьте: бирюзовая рамка — значок, жёлтая — только его подпись. Подтвердите показ.')

    def _save(self) -> None:
        """Send a bounded lesson file; success is acknowledged by the live engine."""
        if self.frame is None or not self.icon or not self.label or self.pending:
            self.message.set('Сначала покажите значок и подпись.'); return
        try:
            shown = lesson(self.frame, self.icon, self.label, self.threshold)
            clipped = {'Полная подпись': 'none', 'Обрезано справа': 'right', 'Обрезано слева': 'left',
                       'Обрезано сверху': 'top', 'Обрезано снизу': 'bottom'}[self.clipped.get()]
            shown.update(name=self.name.get().strip(), target=self.target_map.get(self.target.get()), clipped=clipped)
            rid = uuid.uuid4().hex; filename = 'visual-lesson-'+rid+'.json'
            payload = dict(id=rid, session=self.bridge.session, lesson=shown,
                           query=self.query.get().strip(), object=self.object_id.get())
            atomic_json(self.bridge.path/filename, payload)
            self.pending = rid; self.wait_started = time.monotonic(); self.save.configure(state='disabled')
            self.app._states_send('/visual-teach-file '+filename)
            self.message.set('Ожидаю подтверждение сохранения от Колоса…'); self.win.after(200, self._ack)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Обучение', str(exc), parent=self.win)

    def _ack(self) -> None:
        """A queued message does not claim the graph or file has been saved."""
        if not self.win.winfo_exists():
            return
        result = self._status().get('visualTeaching') or {}
        if result.get('id') == self.pending:
            self.pending = None; self.save.configure(state='normal'); self.message.set(result['message'])
            self._catalog()
            if result.get('ok'):
                value = next((k for k, v in self.target_map.items() if v == result.get('target')), 'Новый образ')
                self.target.set(value)
            return
        if time.monotonic()-self.wait_started > 15:
            self.pending = None; self.save.configure(state='normal')
            self.message.set('Подтверждение не получено. Проверьте терминал и состояние записи; повтор автоматически не отправляется.')
            return
        self.win.after(200, self._ack)
