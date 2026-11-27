"""Native States integration around the unchanged Glaz application.

run_main.bat still launches Glaz/main.py. States is the default; its child
process never opens the legacy SQLite database. Only the States engine is executable.
"""
from __future__ import annotations
import os
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from app import ScreenCaptureApp
from states_bridge import GlazStatesBridge
from kolos_subprocess import KolosSubprocessController, project_root_from_glaz_file
from kolos_states.ipc import read_json
from neuron_canvas import NeuronCanvas
from neuron_feed import InlineNeuronFeed
from utils import get_cursor_pos
from Glaz.cursor_target import bbox_contains_point, pointed_bbox_index
from Glaz.objects_repository import recognized_ids


class IntegratedScreenCaptureApp(ScreenCaptureApp):
    def __init__(self,root):
        self._states_bridge=None;self._states_frame=None;self._states_frame_timestamp=0.0
        self._states_controls_owned=False;self._state_table=None;self._image_table=None;self._neuron_server=None
        self._states_hover_bbox=None
        self._inline_feed=None; self._workspace_mode="vision"; self._closing=False
        use_states=True  # Legacy is no longer an executable application mode.
        self._engine_var=tk.StringVar(master=root,value='Состояния и цели (ПК)')
        self._states_allow=tk.BooleanVar(master=root,value=use_states)
        super().__init__(root)
        self._inline_feed=InlineNeuronFeed(self._states_bridge.path,self._states_bridge.session)
        self.root.after(100,self._inline_poll)
        self.root.after(300,self._states_status)

    def _setup_ui(self):
        outer=ttk.Frame(self.root); outer.pack(fill='both',expand=True)
        bar=ttk.Frame(outer);bar.pack(fill='x',padx=10,pady=5)
        ttk.Label(bar,text='Рабочий экран:').pack(side='left',padx=(0,10))
        self._workspace_var=tk.StringVar(value='vision')
        for label,value in [('Пики и элементы','vision'),('Нейроны','neurons'),('Что умеет Colossus','capabilities')]:
            ttk.Radiobutton(bar,text=label,value=value,variable=self._workspace_var,
                            command=lambda:self._select_workspace(self._workspace_var.get())).pack(side='left',padx=6)
        ttk.Label(bar,text='Переключение вида не останавливает захват и Kolos').pack(side='right')
        monitor_host=ttk.Frame(outer);monitor_host.pack(fill='x')
        self._left_frame=monitor_host; self._setup_monitor_frame()
        self._vertical_pane=ttk.PanedWindow(outer,orient=tk.VERTICAL)
        self._vertical_pane.pack(fill='both',expand=True)
        self._visual_host=ttk.Frame(self._vertical_pane)
        self._terminal_host=ttk.Frame(self._vertical_pane)
        self._vertical_pane.add(self._visual_host,weight=3)
        self._vertical_pane.add(self._terminal_host,weight=1)
        self._main_pane=ttk.PanedWindow(self._visual_host,orient=tk.HORIZONTAL)
        self._main_pane.pack(fill='both',expand=True)
        self._left_frame=ttk.Frame(self._main_pane)
        self._middle_frame=ttk.Frame(self._main_pane,width=200)
        self._right_frame=ttk.Frame(self._main_pane,width=330)
        self._middle_frame.pack_propagate(False);self._right_frame.pack_propagate(False)
        for widget,weight in [(self._left_frame,3),(self._middle_frame,0),(self._right_frame,1)]:
            self._main_pane.add(widget,weight=weight)
        self._setup_peaks_frame();self._setup_error_frame();self._setup_status_bar()
        self._setup_screenshot_previews();self._setup_objects_table();self._update_objects_table()
        self._kolos_text.configure(height=5)
        self._neuron_canvas=NeuronCanvas(self._visual_host)
        self._setup_learned_tasks()
        self.root.after_idle(self._initial_workspace_size)
        self.log_message('Glaz готов. Виды «Пики и элементы» и «Нейроны» используют один терминал.')

    def _initial_workspace_size(self):
        if not self._closing:
            h=self._vertical_pane.winfo_height()
            if h>350:self._vertical_pane.sashpos(0,max(200,h-245))

    def _select_workspace(self,mode):
        if mode not in ('vision','neurons','capabilities') or self._closing:return
        # Deliberately no engine start/reset/pause/capture.stop here.
        self._workspace_mode=mode;self._workspace_var.set(mode)
        self._main_pane.pack_forget();self._neuron_canvas.pack_forget();self._tasks_host.pack_forget()
        if mode=='neurons':self._neuron_canvas.pack(fill='both',expand=True)
        elif mode=='capabilities':
            self._tasks_host.pack(fill='both',expand=True)
            self._refresh_learned_tasks()
        else:self._main_pane.pack(fill='both',expand=True)
        self._neuron_canvas.set_visible(mode=='neurons')
        if self._inline_feed:
            self._inline_feed.set_enabled(mode=='neurons' and self._states_bridge.enabled)
        if mode=='neurons' and not self._states_bridge.enabled:
            self._neuron_canvas.clear('Нет подключения к снимкам States. Перезапустите движок.')

    def _setup_learned_tasks(self):
        self._tasks_host=ttk.Frame(self._visual_host,padding=12)
        ttk.Label(self._tasks_host,text='Что умеет Colossus',font=('Segoe UI',13,'bold')).pack(anchor='w')
        ttk.Label(self._tasks_host,text='Задачи из сохранённой памяти после записи → Esc → 5 → 1.',wraplength=760).pack(anchor='w',pady=(4,6))
        self._tasks_summary=tk.StringVar(value='Ожидание снимка памяти…')
        ttk.Label(self._tasks_host,textvariable=self._tasks_summary,wraplength=760).pack(anchor='w',pady=(0,6))
        rows=ttk.Frame(self._tasks_host);rows.pack(fill='both',expand=True)
        rows.rowconfigure(0,weight=1);rows.columnconfigure(0,weight=1)
        self._tasks_table=ttk.Treeview(rows,columns=('query','confirmed','demos','actions'),show='headings',height=4)
        for key,label,width in [('query','Задача',440),('confirmed','Подтверждение',145),('demos','Записей',85),('actions','Действий',85)]:
            self._tasks_table.heading(key,text=label);self._tasks_table.column(key,width=width,minwidth=70,stretch=key=='query')
        self._tasks_table.grid(row=0,column=0,sticky='nsew')
        for orient,row,column,command in [('vertical',0,1,self._tasks_table.yview),('horizontal',1,0,self._tasks_table.xview)]:
            scroll=ttk.Scrollbar(rows,orient=orient,command=command);scroll.grid(row=row,column=column,sticky='ns' if orient=='vertical' else 'ew')
            self._tasks_table.configure(**{('yscrollcommand' if orient=='vertical' else 'xscrollcommand'):scroll.set})
        self._tasks_details=scrolledtext.ScrolledText(self._tasks_host,height=3,wrap=tk.WORD,font=('Consolas',9))
        self._tasks_details.pack(fill='x',pady=(6,0))
        self._configure_copyable_readonly_text(self._tasks_details);self._make_text_readonly(self._tasks_details)
        self._tasks_table.bind('<<TreeviewSelect>>',self._show_learned_task_details)
        self._tasks_snapshot=None;self._tasks_rows=[]
        self._show_learned_task_details()

    def _refresh_learned_tasks(self, raw=None):
        if self._workspace_mode!='capabilities':return
        if not self._states_bridge.enabled:
            raw=None;message='Выберите движок «Состояния и цели (ПК)» для просмотра обученных задач.'
        else:
            if raw is None:raw=read_json(self._states_bridge.path/'status.json')
            if not raw or raw.get('session')!=self._states_bridge.session:
                raw=None;message='Ожидание актуального снимка памяти Kolos…'
            elif 'confirmedTasks' not in raw:
                raw=None;message='Перезапустите движок, чтобы получить список подтверждённых задач.'
            else:
                tasks=raw['confirmedTasks']
                message=f'Задач: {len(tasks)} · Подтверждённых записей: {sum(t["demonstrations"] for t in tasks)}' if tasks else 'Подтверждённых задач пока нет. Введите команду, запишите действия (3), завершите (Esc), сохраните (5) и подтвердите (1).'
        tasks=raw['confirmedTasks'] if raw else []
        self._tasks_summary.set(message)
        if tasks==self._tasks_snapshot:return
        selected=self._tasks_table.selection()
        query=self._tasks_rows[int(selected[0])]['query'] if selected else None
        self._tasks_table.delete(*self._tasks_table.get_children())
        self._tasks_rows=tasks;self._tasks_snapshot=tasks
        for index,task in enumerate(tasks):
            self._tasks_table.insert('','end',iid=str(index),values=(task['query'],'1 · Правильно',task['demonstrations'],len(task['actions'])))
            if task['query']==query:self._tasks_table.selection_set(str(index))
        self._show_learned_task_details()

    def _show_learned_task_details(self,event=None):
        selected=self._tasks_table.selection()
        if selected:
            task=self._tasks_rows[int(selected[0])]
            text=task['query']+'\nДействия последней подтверждённой записи:\n'+'\n'.join(f'{i}. {action}' for i,action in enumerate(task['actions'],1))
        else:text='Выберите задачу, чтобы увидеть её полный текст и записанные действия.'
        self._tasks_details.delete('1.0','end');self._tasks_details.insert('1.0',text)

    def _inline_poll(self):
        if self._closing:return
        try:
            if self._inline_feed and self._inline_feed.enabled:
                result=self._inline_feed.poll()
                raw=read_json(self._states_bridge.path/'status.json') or {}
                if raw.get('session')!=self._states_bridge.session:raw={}
                if result:
                    self._neuron_canvas.set_frame(result['frame'],skipped=result['skipped'],
                        running=bool(raw.get('running')),recording=bool(raw.get('recording')))
                self._neuron_canvas.set_runtime(running=bool(raw.get('running')),recording=bool(raw.get('recording')),
                    connected=bool(self._kolos_controller and self._kolos_controller.is_running))
                if self._inline_feed.error:
                    self._neuron_canvas.footer.set('Нет нового снимка: '+self._inline_feed.error)
        finally:
            if not self._closing:self.root.after(100,self._inline_poll)

    def _update_display(self):
        if self._workspace_mode!='vision':
            # Recognition uses source coordinates, not the hidden canvas size.
            self._hold_cursor_if_active()
            if self.current_image is not None:self._process_mouse_over_object(self.current_image.size)
            return
        super()._update_display()

    def _update_peaks_display(self):
        if self._workspace_mode=='vision':super()._update_peaks_display()

    def _setup_objects_table(self):
        # Both workspaces share one terminal, outside the replaceable top panel.
        objects=ttk.LabelFrame(self._right_frame,text='Элементы · ID и горящие сегменты',padding=5)
        objects.pack(fill='both',expand=True)
        self._zoomed_tree=ttk.Treeview(objects,columns=('id','segments'),show='headings',height=8)
        for key,label,width in [('id','ID',70),('segments','Сегменты',240)]:
            self._zoomed_tree.heading(key,text=label);self._zoomed_tree.column(key,width=width)
        scroll=ttk.Scrollbar(objects,orient='vertical',command=self._zoomed_tree.yview)
        self._zoomed_tree.configure(yscrollcommand=scroll.set)
        self._zoomed_tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        terminal=ttk.LabelFrame(self._terminal_host,text='Kolos · один терминал для обоих экранов',padding=5)
        terminal.pack(fill='both',expand=True)
        self._kolos_text=scrolledtext.ScrolledText(terminal,height=5,wrap=tk.WORD,font=('Consolas',9))
        self._kolos_text.tag_configure('kolos_red',foreground='#b71c1c')
        self._kolos_text.tag_configure('kolos_user_input',foreground='#176b35')
        self._configure_copyable_readonly_text(self._kolos_text);self._make_text_readonly(self._kolos_text)
        inp=ttk.Frame(terminal);inp.pack(side='bottom',fill='x',pady=(6,0))
        ttk.Label(inp,text='Ввод → Kolos (Enter):').pack(side='left')
        self._kolos_input_var=tk.StringVar()
        self._kolos_entry=ttk.Entry(inp,textvariable=self._kolos_input_var)
        self._kolos_entry.pack(side='left',fill='x',expand=True,padx=(6,0))
        self._kolos_entry.bind('<Return>',self._on_kolos_input_return)
        self._kolos_text.pack(fill='both',expand=True)
        # ScrolledText exposes an outer frame; its .master is the inner frame.
        anchor=self._kolos_text.frame
        parent=anchor.master
        toolbar=ttk.Frame(parent);toolbar.pack(fill='x',before=anchor,pady=(0,5))
        ttk.Label(toolbar,text='Состояния и цели (ПК)').pack(side='left',padx=(0,8))
        ttk.Button(toolbar,text='Перезапустить',command=self._switch_engine).pack(side='left',padx=3)
        ttk.Checkbutton(toolbar,text='Разрешить управление ПК',variable=self._states_allow,command=self._states_permission).pack(side='left')
        menu_button=ttk.Menubutton(toolbar,text='Опыты и инструменты')
        menu_button.pack(side='right',padx=4)
        menu=tk.Menu(menu_button,tearoff=False);menu_button['menu']=menu
        for label,callback in [('Задать цель',self._show_goal_dialog),('Язык → образ',self._show_language_dialog),
            ('Образ I / S',self._show_image),('Сигналы (таблица)',self._show_states),
            ('Нейроны в браузере',self._show_neurons),('Общая учебная база · 12 опытов',self._show_shared_lab),
            ('Рабочий эпизод и роли',self._show_episode_dialog),
            ('Обучить составной объект',self._show_visual_teacher),
            ('Уточнение объекта',self._show_object_question),
            ('Подсказки по зрительному обучению',self._show_visual_help)]:
            menu.add_command(label=label,command=callback)
        menu.add_separator()
        menu.add_command(label='Зрительный режим без UI Automation', command=lambda:self._states_send('/vision on'))
        menu.add_command(label='Вернуть наблюдатель текстовых полей', command=lambda:self._states_send('/vision off'))
        for label,command in [('4 теста','/selftest'),('10 тестов','/acceptance'),('11: тест образа','/imagerytest'),
                              ('12: тест языка','/languagetest'),('Тестовое окно','/testpad'),('13–14: рабочий эпизод','/episodetest')]:
            menu.add_command(label=label,command=lambda c=command:self._states_send(c))
        row=ttk.Frame(parent);row.pack(fill='x',before=anchor,pady=(0,5))
        for i,(label,command) in enumerate([('Запись (3)','3'),('Закончить','/end'),('Сохранить (5)','5'),('Правильно (1)','1'),
                                          ('Пауза','/pause'),('Шаг','/step'),('Пуск','/run'),('СТОП F9','/stop'),('Reset','/reset')]):
            ttk.Button(row,text=label,command=lambda c=command:self._states_send(c)).grid(row=0,column=i,sticky='ew',padx=1)
            row.columnconfigure(i,weight=1)
        self._setup_kolos_task(parent,before=anchor)
        self._states_bridge=GlazStatesBridge(self)
        self._states_bridge.enabled=True

    def _states_send(self,line):
        if line=='/stop':self._states_allow.set(False);self._states_permission()
        if self._states_bridge and self._states_bridge.enabled and line in ('/reset','/stop','3','/record'):
            self._states_controls_owned=False;self._reset_object_state()
        self._send_kolos_line(line)

    def _show_object_question(self):
        from Glaz.concept_dialog import show_pending
        show_pending(self)

    def _show_visual_teacher(self):
        """Teach spatial parts through a frozen image, without clicking the desktop."""
        if not self._states_bridge.enabled:
            messagebox.showinfo('Обучение', 'Выберите «Состояния и цели (ПК)».')
            return
        from Glaz.perception.dialog import VisualTeacher
        VisualTeacher(self)

    def _show_visual_help(self) -> None:
        """Open the shared visual teaching guide directly from either workspace."""
        from kolos_states.perception.help import VISUAL_HELP
        messagebox.showinfo('Как обучить значок и подпись', VISUAL_HELP, parent=self.root)

    def _states_permission(self):
        if self._states_allow.get():
            ok=messagebox.askokcancel('Управление ПК','Kolos сможет двигать мышь, кликать и печатать.\nПроверяйте на тестовом окне без важных данных. F9 — стоп.\nРазрешить для текущего сеанса?')
            if not ok:self._states_allow.set(False)
        self._states_bridge.permission(self._states_allow.get())

    def _start_kolos_embedded(self):
        mode='states'
        self._engine_var.set('Состояния и цели (ПК)')
        self._states_bridge.permission(mode=='states' and self._states_allow.get())
        self._kolos_controller=KolosSubprocessController(project_root_from_glaz_file(__file__),self._kolos_thread_event)
        options=dict(monitor_idx=self.capture.selected_monitor,engine=mode)
        if mode=='states':options.update(ipc_dir=str(self._states_bridge.path),session=self._states_bridge.session,glaz_pid=os.getpid())
        error=self._kolos_controller.start(**options)
        if error:self._kolos_append_main_thread('Kolos: '+error+'\n')
        else:self._kolos_entry.focus_set()

    def _switch_engine(self):
        if self._inline_feed:self._inline_feed.set_enabled(False)
        self._neuron_canvas.clear()
        if self._neuron_server:self._neuron_server.close();self._neuron_server=None
        self._states_allow.set(False);self._states_bridge.permission(False)
        if self._kolos_controller:self._kolos_controller.stop()
        if self._inline_feed:self._inline_feed.reset()
        self._states_bridge.enabled=True;self._states_controls_owned=False
        self._start_kolos_embedded()
        if self._inline_feed:self._inline_feed.set_enabled(self._workspace_mode=="neurons" and self._states_bridge.enabled)
        self._refresh_learned_tasks()

    def _on_frame_captured(self,image):
        stamp=time.time();monitor=dict(self.capture.monitor_info or {})
        self._states_frame=(image,stamp,monitor)
        self._states_frame_timestamp=stamp
        super()._on_frame_captured(image)

    def _stop_capture(self):
        self._states_frame=None;self._states_frame_timestamp=0.0
        super()._stop_capture()

    def _on_escape_pressed(self,event=None):
        if self._states_bridge and self._states_bridge.enabled:
            self._states_send('/end');return 'break'
        return super()._on_escape_pressed(event)

    def _hold_cursor_if_active(self):
        if self._states_controls_owned:
            self._cursor_hold_position=None;self._cursor_hold_until=0.0;return
        super()._hold_cursor_if_active()

    def _reset_object_state(self) -> None:
        """Discard both the States hover instance and the Glaz recognition attempt."""
        self._states_hover_bbox=None
        super()._reset_object_state()

    def _process_mouse_over_object(self,display_size):
        if not self._states_controls_owned:
            super()._process_mouse_over_object(display_size)
            return
        # Kolos owns the mouse. Compute the usual centered hover signature
        # from the frame without cursor-centering or database writes.
        point=self._mouse_to_peaks_coords(*display_size)
        target=self._recognized_cursor_target(point) if self.capture.is_capturing else None
        if target is None:
            self._reset_object_state();return
        obj,refined_id=target;cursor=get_cursor_pos();now=time.time()
        # Detector IDs are per-frame ordinals, not stable object identities.
        # UI changes elsewhere can renumber this same stationary object.
        previous_id=self._last_hovered_object_id
        if previous_id!=obj.id:self._object_id_to_refined.pop(previous_id,None)
        self._last_hovered_object_id=obj.id
        if obj.bbox!=self._states_hover_bbox or cursor!=self._last_cursor_pos:
            self._object_id_to_refined.pop(obj.id,None)
            self._states_hover_bbox=obj.bbox
            self._last_cursor_pos=cursor
            self._cursor_stable_since=now;self._object_already_recognized=False
            return
        if self._cursor_stable_since is None or now-self._cursor_stable_since<self._cursor_stable_delay:return
        recognized=self._object_already_recognized
        self._object_id_to_refined[obj.id]=refined_id;self._object_already_recognized=True
        if not recognized:self._event_bus.emit('object_recognized',refined_id=refined_id,is_new=False)

    def _recognized_cursor_target(self, point: tuple | None) -> tuple | None:
        """Resolve the cursor among freshly recognized objects, as the IPC bridge does."""
        if point is None:return None
        known=[]
        for obj in self._detected_objects:
            if not bbox_contains_point(obj.bbox,point):continue
            signature=self._signature_for_object_center(frame=self.current_image,obj=obj,
                loupe_size=int(self.loupe_controller.loupe_size),threshold=int(self.peaks_threshold.get()),
                invert=bool(self.peaks_invert.get()),segment_threshold=int(self.segment_peak_threshold.get()),
                monitor=self.capture.monitor_info)
            ids,_=recognized_ids(self._objects_repo,signature,self._zoomed_signature_to_ids,self._signature_match_max_pct)
            if len(ids)==1:known.append((obj,ids[0]))
        index=pointed_bbox_index([obj.bbox for obj,_ in known],point)
        return known[index] if index is not None else None

    def _process_signature_if_pending(self):
        if self._states_controls_owned:
            if self._recognition_state.is_step1:
                self._reset_object_state()
            return
        super()._process_signature_if_pending()

    def _set_states_controls_owned(self, owned: bool) -> None:
        """Release stale hover evidence when mouse ownership changes."""
        if owned!=self._states_controls_owned:
            self._reset_object_state()
        self._states_controls_owned=owned

    def _poll_scan_request_and_maybe_run(self):
        if not(self._states_bridge and self._states_bridge.enabled):super()._poll_scan_request_and_maybe_run()

    def _states_status(self):
        if not self._states_bridge or self._states_bridge.closed:return
        raw=read_json(self._states_bridge.path/'status.json')
        if hasattr(self,'_tasks_host'):self._refresh_learned_tasks(raw)
        if raw and raw.get('session')==self._states_bridge.session:
            self._set_states_controls_owned(bool(raw.get('running') and not raw.get('recording')))
            from Glaz.concept_dialog import poll_question
            poll_question(self, raw)
            if self._image_table and self._image_table.winfo_exists():
                table=self._image_table;table.delete(*table.get_children())
                for n in (raw.get('imagery') or {}).get('nodes',[]):
                    table.insert('','end',values=(n['label'],round(n['I']*100,2),round(n['S']*100,2),'да' if n['present'] else 'нет'))
            if self._state_table and self._state_table.winfo_exists():
                table=self._state_table;selected=table.selection();table.delete(*table.get_children())
                for n in raw.get('nodes',[]):
                    id=n['id'];a=max(raw.get('activation',{}).get(id,0),raw.get('goalActivation',{}).get(id,0))
                    table.insert('', 'end', iid=id,values=(id,n['kind'],n.get('label',''),round(a*100,2),round(raw.get('trace',{}).get(id,0),3),raw.get('refractory',{}).get(id,0)))
                for n in raw.get('occ',[]):table.insert('','end',iid=n['id'],values=(n['id'],'текущий ввод',n['value'],round(n['a']*100,2),'нужен' if n['held'] else 'погашен',''))
                for id in selected:
                    if table.exists(id):table.selection_add(id)
        self.root.after(300,self._states_status)

    def _show_states(self):
        win=tk.Toplevel(self.root);win.title('Kolos: сигналы Python-ядра');win.geometry('800x600')
        ttk.Label(win,text='A — активация (0…100); T — след; R — refractory. Обновление не продвигает ядро.').pack(fill='x')
        self._state_table=ttk.Treeview(win,columns=('id','kind','label','a','t','r'),show='headings')
        for key,title,width in [('id','ID',70),('kind','Тип',100),('label','Вершина',260),('a','A',90),('t','T / H',90),('r','R',60)]:
            self._state_table.heading(key,text=title);self._state_table.column(key,width=width)
        self._state_table.pack(fill='both',expand=True)

    def _show_image(self):
        win=tk.Toplevel(self.root);win.title('Kolos: внутренний образ / наблюдение');win.geometry('720x520')
        ttk.Label(win,text='Одна строка — одна вершина. I не подтверждает реальность. S учитывается только при наличии признака сейчас.',wraplength=670).pack(padx=10,pady=10)
        self._image_table=ttk.Treeview(win,columns=('content','I','S','present'),show='headings')
        for key,label in [('content','Представление'),('I','Образ I'),('S','Сенсорный S'),('present','Есть сейчас')]:self._image_table.heading(key,text=label)
        self._image_table.pack(fill='both',expand=True)
        row=ttk.Frame(win);row.pack(fill='x')
        ttk.Button(row,text='Достичь образа',command=lambda:self._states_send('/image-act')).pack(side='left')
        ttk.Button(row,text='Снять поддержку',command=lambda:self._states_send('/image-rest')).pack(side='left')
        ttk.Button(row,text='Пауза',command=lambda:self._states_send('/pause')).pack(side='left')

    def _show_goal_dialog(self):
        if not self._states_bridge.enabled:
            messagebox.showinfo('Цели', 'Выберите «Состояния и цели (ПК)».'); return
        raw = read_json(self._states_bridge.path / 'status.json')
        if not raw or raw.get('session') != self._states_bridge.session:
            messagebox.showinfo('Цели', 'Пока нет состояния нового движка.'); return
        nodes = [n for n in raw.get('nodes', []) if n['kind'] == 'state']
        fields = sorted({f[6:] for n in nodes for f in n['features'] if f.startswith('focus:') and len(f) > 6})
        choices = [(n['label'] + ' · ' + ', '.join(f[8:] for f in n['features'] if f.startswith('visible:')), dict(kind='state', features=n['features'])) for n in nodes]
        choices += [('Поле ' + f, dict(kind='field', focus=f)) for f in fields]
        if not choices:
            messagebox.showinfo('Цели', 'Сначала покажите действия и состояния.'); return
        win = tk.Toplevel(self.root); win.title('Задать наблюдаемый результат'); win.geometry('660x420')
        ttk.Label(win, text='Это явное задание результата. Порядок действий выбирается по графу опыта.', wraplength=620).pack(padx=12, pady=10)
        selector = ttk.Combobox(win, values=[c[0] for c in choices], state='readonly'); selector.pack(fill='x', padx=12); selector.current(0)
        value = ttk.Entry(win); value.pack(fill='x', padx=12, pady=8)
        ttk.Label(win, text='Строка выше — желаемый текст для цели «поле». Для состояния она не используется.').pack(padx=12)
        display = tk.Listbox(win); display.pack(fill='both', expand=True, padx=12, pady=8); goals = []
        def add():
            if len(goals) >= 8: return
            g = dict(choices[selector.current()][1])
            if g['kind'] == 'field': g['value'] = value.get()
            goals.append(g); display.insert('end', choices[selector.current()][0] + (' = ' + g['value'] if g['kind'] == 'field' else ''))
        def clear():
            goals.clear(); display.delete(0, 'end')
        def send(imagine=False):
            if not goals: return
            self._states_send(('/imagine ' if imagine else '/goals ') + json.dumps(goals, ensure_ascii=False)); win.destroy()
        row = ttk.Frame(win); row.pack(fill='x', padx=12, pady=8)
        ttk.Button(row, text='Добавить результат', command=add).pack(side='left')
        ttk.Button(row, text='Очистить', command=clear).pack(side='left', padx=8)
        ttk.Button(row, text='Представить без действий', command=lambda:send(True)).pack(side='right',padx=4)
        ttk.Button(row, text='Передать цели', command=send).pack(side='right')

    def _show_language_dialog(self):
        raw=read_json(self._states_bridge.path/'status.json') or {}
        win=tk.Toplevel(self.root);win.title('Kolos: язык возбуждает образ');win.geometry('780x600')
        ttk.Label(win,text='Новый запрос: поле и значение выбираются по обученным языковым связям, а не вручную.',wraplength=740).pack(padx=12,pady=10)
        phrase=ttk.Entry(win);phrase.pack(fill='x',padx=12,pady=6)
        row=ttk.Frame(win);row.pack(fill='x',padx=12)
        def say(act=False):
            text=phrase.get()
            if not text:return
            self._states_send(('/say-run ' if act else '/say ')+text);win.destroy()
        ttk.Button(row,text='Понять и представить',command=say).pack(side='left')
        ttk.Button(row,text='Понять и достичь',command=lambda:say(True)).pack(side='left',padx=8)
        ttk.Label(win,text='Обучение: ниже выбор образа — это подпись к обучающей фразе, не указание маршрута.\nДля поля покажите два разных значения в одинаковой формулировке.',wraplength=740).pack(padx=12,pady=14)
        training=ttk.Entry(win);training.pack(fill='x',padx=12)
        choices=[]
        for n in raw.get('nodes',[]):
            if n['kind']=='state':choices.append((n['label']+' · состояние',dict(kind='state',features=n['features'])))
        fields=sorted({f[6:] for n in raw.get('nodes',[]) if n['kind']=='state' for f in n['features'] if f.startswith('focus:') and len(f)>6})
        choices.extend(('Поле '+f,dict(kind='field',focus=f)) for f in fields)
        target=ttk.Combobox(win,values=[c[0] for c in choices],state='readonly');target.pack(fill='x',padx=12,pady=6)
        if choices:target.current(0)
        value=ttk.Entry(win);value.pack(fill='x',padx=12,pady=6)
        ttk.Label(win,text='Содержимое поля (для образа состояния оставьте пустым)').pack(padx=12)
        def teach():
            if not choices or target.current()<0:return
            g=dict(choices[target.current()][1])
            if g['kind']=='field':g['value']=value.get()
            self._states_send('/language-teach '+json.dumps(dict(phrase=training.get(),goal=g),ensure_ascii=False))
        ttk.Button(win,text='Запомнить подтверждённую пару',command=teach).pack(padx=12,pady=8)
        lessons=tk.Listbox(win);lessons.pack(fill='both',expand=True,padx=12,pady=8)
        for pair in (raw.get('languageMemory') or {}).get('lessons',[]):
            lessons.insert('end',pair['phrase']+' → '+json.dumps(pair['goal'],ensure_ascii=False))
        ttk.Label(win,text='Только выученные формулировки; неизвестные слова не игнорируются. Новая комбинация известных символов поддерживается.',wraplength=740).pack(padx=12,pady=6)

    def _show_neurons(self):
        if not self._states_bridge.enabled:
            messagebox.showinfo('Нейроны','Выберите «Состояния и цели (ПК)».');return
        import webbrowser
        from kolos_states.neuron_server import NeuronServer
        try:
            if self._neuron_server is None:
                self._neuron_server=NeuronServer(project_root_from_glaz_file(__file__),self._states_bridge.path,self._states_bridge.session)
            webbrowser.open(self._neuron_server.url)
            self._kolos_append_main_thread('Открыт граф только для чтения. Пауза просмотра не останавливает ядро. Окно браузера не должно перекрывать рабочую область Glaz.\n')
        except (OSError,ValueError) as exc:
            messagebox.showerror('Нейроны',str(exc))

    def _show_episode_dialog(self):
        from episode_dialog import show
        return show(self)

    def _show_shared_lab(self):
        """Separate safe virtual curriculum, never replaces the PC memory."""
        import webbrowser
        from kolos_states.neuron_server import NeuronServer
        if not self._states_bridge.enabled:
            messagebox.showinfo('Общая база','Выберите «Состояния и цели (ПК)».');return
        try:
            if self._neuron_server is None:
                self._neuron_server=NeuronServer(project_root_from_glaz_file(__file__),self._states_bridge.path,self._states_bridge.session)
            url=f'http://127.0.0.1:{self._neuron_server.server.server_port}/web/shared/index.html'
            webbrowser.open(url)
            self._kolos_append_main_thread('Открыта общая УЧЕБНАЯ база 12 опытов. Она не загружена вместо вашей памяти ПК и не управляет Windows.\n')
        except (OSError,ValueError) as exc:
            messagebox.showerror('Общая база',str(exc))

    def _on_root_close(self):
        self._closing=True
        if self._inline_feed:self._inline_feed.close()
        self._neuron_canvas.close()
        if self._neuron_server:self._neuron_server.close()
        if self._states_bridge:self._states_bridge.close()
        super()._on_root_close()
