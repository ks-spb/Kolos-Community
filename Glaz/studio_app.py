"""Native PC Neural Studio (design 02); the existing Glaz pipeline is inherited.

Only widgets and layout are replaced. run_main, engine selection, capture,
recording, receipts, F9 and all mathematical modules retain their contracts.
"""
from __future__ import annotations
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from states_app import IntegratedScreenCaptureApp
from states_bridge import GlazStatesBridge
from kolos_states.ipc import read_json
from studio_theme import P, install, style_tree, RailButton
from studio_canvas import StudioNeuronCanvas


class NeuralStudioApp(IntegratedScreenCaptureApp):
    def __init__(self,root):
        self._studio_fonts=install(root);self._dialogs={};self._rail_buttons={}
        super().__init__(root)
        self.root.title('Glaz / Kolos — Neural Studio')
        self.root.minsize(1024,680)
        self.root.bind_class('Toplevel','<Map>',self._theme_mapped_dialog,add='+')
        style_tree(self.root)
        self._neuron_canvas.inspector.configure(background=P['panel'])
        self._kolos_text.tag_configure('kolos_red',foreground=P['danger'])
        self._kolos_text.tag_configure('kolos_user_input',foreground=P['good'])
        self.error_text.tag_configure('green',foreground=P['good'])
        self._select_workspace('vision')

    def _theme_mapped_dialog(self,event):
        if isinstance(event.widget,tk.Toplevel):
            win=event.widget
            self.root.after_idle(lambda:style_tree(win) if win.winfo_exists() else None)

    def _setup_ui(self):
        outer=ttk.Frame(self.root);outer.pack(fill='both',expand=True)
        brand=ttk.Frame(outer,style='Panel.TFrame',padding=(20,12));brand.pack(fill='x')
        ttk.Label(brand,text='GLAZ / KOLOS',style='Brand.TLabel').pack(side='left')
        ttk.Label(brand,text='   /   NEURAL STUDIO',style='Brand.TLabel',foreground=P['muted']).pack(side='left',padx=12)
        ttk.Label(brand,text='ПК · ЛОКАЛЬНО',style='Panel.TLabel',foreground=P['muted'],font=(self._studio_fonts['sans'],9)).pack(side='right')
        ttk.Separator(outer).pack(fill='x')
        body=ttk.Frame(outer);body.pack(fill='both',expand=True)
        rail=ttk.Frame(body,style='Panel.TFrame',width=66);rail.pack(side='left',fill='y');rail.pack_propagate(False)
        for key,label,callback in [('graph','Работа',lambda:self._select_workspace(self._workspace_mode)),
                                    ('learn','Учить',self._show_training),('tests','Опыты',self._show_experiments),
                                    ('memory','Память',self._show_memory),('settings','Опции',self._show_settings)]:
            b=RailButton(rail,key,label,callback);b.pack(pady=(8,0));self._rail_buttons[key]=b
        self._rail_buttons['graph'].select(True)
        content=ttk.Frame(body,padding=(16,10,16,8));content.pack(side='left',fill='both',expand=True)
        heading=ttk.Frame(content);heading.pack(fill='x',pady=(2,10))
        ttk.Label(heading,text='Рабочее пространство',style='Title.TLabel').pack(side='left')
        self._monitor_host=ttk.Frame(heading);self._monitor_host.pack(side='right')
        self._setup_monitor_frame()
        tabs=ttk.Frame(content);tabs.pack(fill='x',pady=(0,10))
        self._workspace_var=tk.StringVar(value='vision')
        for label,mode in [('Нейроны','neurons'),('Пики и элементы','vision'),('Что умеет Colossus','capabilities')]:
            ttk.Radiobutton(tabs,text=label,variable=self._workspace_var,value=mode,style='Tab.TRadiobutton',
                command=lambda:self._select_workspace(self._workspace_var.get())).pack(side='left',padx=(0,3))
        self._runtime_badge=tk.StringVar(value='Ожидание Kolos')
        ttk.Label(tabs,textvariable=self._runtime_badge,style='Muted.TLabel',font=(self._studio_fonts['sans'],9)).pack(side='right')
        self._vertical_pane=ttk.PanedWindow(content,orient=tk.VERTICAL);self._vertical_pane.pack(fill='both',expand=True)
        self._visual_host=ttk.Frame(self._vertical_pane);self._terminal_host=ttk.Frame(self._vertical_pane)
        self._vertical_pane.add(self._visual_host,weight=1);self._vertical_pane.add(self._terminal_host,weight=1)
        self._main_pane=ttk.PanedWindow(self._visual_host,orient=tk.HORIZONTAL);self._main_pane.pack(fill='both',expand=True)
        self._left_frame=ttk.Frame(self._main_pane);self._middle_frame=ttk.Frame(self._main_pane,width=185)
        self._right_frame=ttk.Frame(self._main_pane,width=280)
        for w,weight in [(self._left_frame,4),(self._middle_frame,0),(self._right_frame,1)]:self._main_pane.add(w,weight=weight)
        self._middle_frame.pack_propagate(False);self._right_frame.pack_propagate(False)
        self._setup_peaks_frame();self._setup_error_frame();self._setup_status_bar()
        self._setup_screenshot_previews();self._setup_objects_table();self._update_objects_table()
        self._neuron_canvas=StudioNeuronCanvas(self._visual_host)
        self._setup_learned_tasks()
        self._vertical_pane.bind('<Map>',lambda event:self.root.after_idle(self._initial_workspace_size))
        self.log_message('Neural Studio готов. Один терминал; переключение вида не останавливает захват.')

    def _initial_workspace_size(self) -> None:
        """Give vision and the terminal equal space on the initial layout."""
        if not self._closing:
            h=self._vertical_pane.winfo_height()
            if h>350:self._vertical_pane.sashpos(0,max(220,h//2))

    def _setup_monitor_frame(self):
        host=self._monitor_host;monitors=self.capture.get_monitors();self.monitor_var=tk.StringVar()
        self.monitor_combo=ttk.Combobox(host,textvariable=self.monitor_var,values=monitors,state='readonly',width=22)
        self.monitor_combo.pack(side='left',padx=(0,6));self.monitor_combo.bind('<<ComboboxSelected>>',self._on_monitor_selected)
        if monitors:self.monitor_combo.current(0);self.capture.selected_monitor=1
        self.capture_btn=ttk.Button(host,text='Захват',command=self._start_capture,style='Small.TButton');self.capture_btn.pack(side='left')
        self.stop_btn=ttk.Button(host,text='Стоп захвата',command=self._stop_capture,state='disabled',style='Small.TButton');self.stop_btn.pack(side='left',padx=4)
        ttk.Button(host,text='Настройки',command=self._show_settings,style='Small.TButton').pack(side='left')

    def _setup_peaks_frame(self):
        header=ttk.Frame(self._left_frame,padding=(10,8));header.pack(fill='x')
        ttk.Label(header,text='ЗРЕНИЕ · ПИКИ',style='Kicker.TLabel').pack(side='left')
        ttk.Button(header,text='Параметры',command=self._show_settings,style='Small.TButton').pack(side='right')
        self._peaks_split=ttk.PanedWindow(self._left_frame,orient=tk.HORIZONTAL)
        self._peaks_split.pack(fill='both',expand=True)
        self._peaks_view_frame=ttk.Frame(self._peaks_split)
        self._peaks_log_frame=ttk.Frame(self._peaks_split)
        self._peaks_split.add(self._peaks_view_frame,weight=2)
        self._peaks_split.add(self._peaks_log_frame,weight=1)
        self.peaks_canvas=tk.Canvas(self._peaks_view_frame,bg=P['canvas'],highlightthickness=0);self.peaks_canvas.pack(fill='both',expand=True)
        self.peaks_canvas.create_text(22,30,text='Включите захват для просмотра пиков',anchor='w',fill=P['muted'])
        # Keep the original tuning widgets alive in a hidden settings window:
        # the capture/hotkey logic references these exact variables and controls.
        win=tk.Toplevel(self.root);win.withdraw();win.title('Neural Studio · Настройки зрения');win.geometry('680x510')
        win.protocol('WM_DELETE_WINDOW',win.withdraw);self._settings_window=win
        panel=ttk.Frame(win,padding=22);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Настройки зрения',style='Title.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(panel,text='Меняется обработка кадра. Математика Kolos здесь не настраивается.',style='Muted.TLabel',wraplength=600).pack(anchor='w',pady=(0,18))
        row=ttk.Frame(panel);row.pack(fill='x',pady=8)
        ttk.Label(row,text='Чувствительность',width=23).pack(side='left')
        self.threshold_scale=ttk.Scale(row,from_=1,to=255,variable=self.peaks_threshold,length=240);self.threshold_scale.pack(side='left')
        self.threshold_entry_var=tk.StringVar(value=str(self.peaks_threshold.get()))
        self.threshold_entry=ttk.Entry(row,textvariable=self.threshold_entry_var,width=5);self.threshold_entry.pack(side='left',padx=10)
        self.threshold_entry.bind('<Return>',self._apply_threshold_from_entry);self.threshold_entry.bind('<FocusOut>',self._apply_threshold_from_entry)
        self.peaks_threshold.trace_add('write',self._on_threshold_changed)
        row=ttk.Frame(panel);row.pack(fill='x',pady=8);ttk.Label(row,text='Масштаб пиков, %',width=23).pack(side='left')
        self.scale_combo=ttk.Combobox(row,textvariable=self.peaks_scale,values=[25,50,100],state='readonly',width=8);self.scale_combo.pack(side='left')
        ttk.Checkbutton(row,text='Инверсия',variable=self.peaks_invert).pack(side='left',padx=14)
        row=ttk.Frame(panel);row.pack(fill='x',pady=8);ttk.Label(row,text='Пикселей для сегмента',width=23).pack(side='left')
        spin=ttk.Spinbox(row,from_=1,to=30,width=8,textvariable=self.segment_peak_threshold);spin.pack(side='left')
        spin.bind('<Return>',self._apply_segment_threshold);spin.bind('<FocusOut>',self._apply_segment_threshold)
        ttk.Checkbutton(panel,text='Сохранять скриншоты распознавания',variable=self._do_screenshots_var).pack(anchor='w',pady=10)
        row=ttk.Frame(panel);row.pack(fill='x',pady=12)
        self.download_peaks_btn=ttk.Button(row,text='Сохранить пики',command=self._save_peaks_image);self.download_peaks_btn.pack(side='left')
        self.contours_all_btn=ttk.Button(row,text='Контуры bbox',command=self._detect_all_contours);self.contours_all_btn.pack(side='left',padx=6)
        self.contours_mass_btn=ttk.Button(row,text='Контуры масс',command=self._detect_all_contours_mass_center);self.contours_mass_btn.pack(side='left')
        ttk.Separator(panel).pack(fill='x',pady=14)
        self.clear_db_btn=ttk.Button(panel,text='Очистить базу объектов…',command=self._confirm_clear_objects,style='Danger.TButton');self.clear_db_btn.pack(anchor='w')
        ttk.Label(panel,text='Опасное действие: удаляет распознанные объекты Glaz. Потребуется подтверждение.',style='Muted.TLabel',wraplength=600).pack(anchor='w',pady=6)

    def _setup_error_frame(self):
        ttk.Label(self._peaks_log_frame,text='ОБЪЕКТЫ · ЖУРНАЛ ПИКОВ',style='Kicker.TLabel').pack(fill='x',padx=8,pady=(4,8))
        self.error_text=scrolledtext.ScrolledText(self._peaks_log_frame,width=32,height=8,wrap='word',state='disabled',font=(self._studio_fonts['mono'],9))
        self.error_text.pack(fill='both',expand=True,padx=(0,4),pady=(0,4));self.error_text.tag_configure('green',foreground=P['good'])

    def _setup_status_bar(self):
        self.status_var=tk.StringVar(value='Готов к работе')
        ttk.Label(self._peaks_view_frame,textvariable=self.status_var,style='Muted.TLabel',wraplength=450).pack(side='bottom',fill='x',padx=10,pady=4)

    def _setup_screenshot_previews(self):
        ttk.Label(self._middle_frame,text='ЛУПА · НАБЛЮДЕНИЕ',style='Kicker.TLabel').pack(fill='x',padx=10,pady=14)
        self._current_loupe_label=ttk.Label(self._middle_frame,text='—',anchor='center');self._current_loupe_label.pack(fill='x')
        self._current_loupe_photo=None
        ttk.Separator(self._middle_frame).pack(fill='x',padx=10,pady=18)
        ttk.Label(self._middle_frame,text='3  →  Esc  →  5  →  1',foreground=P['accent'],anchor='center').pack(fill='x')
        self._kolos_digits_hint=scrolledtext.ScrolledText(self._middle_frame,height=8,width=19,wrap='word',font=(self._studio_fonts['sans'],9),relief='flat')
        self._kolos_digits_hint.pack(fill='both',expand=True,padx=4,pady=10)
        self._kolos_digits_hint.insert('1.0','ОБУЧЕНИЕ\n\n3  Начать запись\nEsc  Закончить\n5  Подготовить\n1  Подтвердить\n\nПоказывайте каждое действие после наблюдения предыдущего.\n\nF9 — остановка States.')
        self._kolos_digits_hint.configure(state='disabled')

    def _setup_objects_table(self):
        ttk.Label(self._right_frame,text='ЭЛЕМЕНТЫ · ПАМЯТЬ ЗРЕНИЯ',style='Kicker.TLabel').pack(fill='x',padx=12,pady=14)
        self._zoomed_tree=ttk.Treeview(self._right_frame,columns=('id','segments'),show='headings',height=8)
        for key,label,width in [('id','ID',70),('segments','Горящие сегменты',180)]:self._zoomed_tree.heading(key,text=label);self._zoomed_tree.column(key,width=width,minwidth=50)
        scroll=ttk.Scrollbar(self._right_frame,orient='vertical',command=self._zoomed_tree.yview)
        self._zoomed_tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self._zoomed_tree.pack(fill='both',expand=True,padx=(8,0))
        terminal=ttk.Frame(self._terminal_host,padding=(12,8));terminal.pack(fill='both',expand=True)
        header=ttk.Frame(terminal);header.pack(fill='x',pady=(0,6))
        ttk.Label(header,text='Терминал Kolos',font=(self._studio_fonts['sans'],10,'bold')).pack(side='left')
        ttk.Label(header,text='Состояния и цели (ПК)').pack(side='left',padx=12)
        ttk.Checkbutton(header,text='Разрешить управление ПК',variable=self._states_allow,command=self._states_permission).pack(side='left')
        self._setup_tools_menu(header)
        # Pack fixed controls before the expandable log; they stay visible at 768p.
        controls=ttk.Frame(terminal);controls.pack(side='bottom',fill='x',pady=(7,0))
        self._command_buttons={}
        for label,command in [('3  Запись','3'),('Esc  Закончить','/end'),('5  Сохранить','5'),('1  Правильно','1'),('Пуск','/run'),('Пауза','/pause'),('Шаг','/step'),('F9  СТОП','/stop'),('Reset','/reset')]:
            b=ttk.Button(controls,text=label,command=lambda c=command:self._states_send(c),style='Danger.TButton' if command=='/stop' else 'Small.TButton')
            b.pack(side='left',padx=(0,4));self._command_buttons[command]=b
        self._speed_value=tk.DoubleVar(value=1)
        speed=ttk.Scale(controls,from_=.1,to=3,variable=self._speed_value,length=80);speed.pack(side='right')
        speed.bind('<ButtonRelease-1>',self._apply_speed);speed.bind('<KeyRelease>',self._apply_speed)
        self._speed_label=tk.StringVar(value='1,0 с / такт');ttk.Label(controls,textvariable=self._speed_label,style='Muted.TLabel',font=(self._studio_fonts['sans'],9)).pack(side='right',padx=4)
        inp=ttk.Frame(terminal);inp.pack(side='bottom',fill='x',pady=(6,0))
        ttk.Label(inp,text='>_',foreground=P['accent'],font=(self._studio_fonts['mono'],12)).pack(side='left',padx=(0,10))
        self._kolos_input_var=tk.StringVar();self._kolos_entry=ttk.Entry(inp,textvariable=self._kolos_input_var)
        self._kolos_entry.pack(side='left',fill='x',expand=True);self._kolos_entry.bind('<Return>',self._on_kolos_input_return)
        self._send_button=ttk.Button(inp,text='Передать в Kolos  →',command=self._on_kolos_input_return,style='Accent.TButton');self._send_button.pack(side='left',padx=(8,0))
        self._setup_kolos_task(terminal,foreground=P['good'],font=(self._studio_fonts['mono'],9))
        self._kolos_text=scrolledtext.ScrolledText(terminal,height=3,wrap='word',font=(self._studio_fonts['mono'],9))
        self._kolos_text.pack(fill='both',expand=True)
        self._configure_copyable_readonly_text(self._kolos_text);self._make_text_readonly(self._kolos_text)
        self._states_bridge=GlazStatesBridge(self);self._states_bridge.enabled=True

    def _setup_tools_menu(self, parent: object) -> None:
        """Expose teaching in the active Studio menu as well as the classic UI."""
        tools=ttk.Menubutton(parent,text='Опыты и инструменты');tools.pack(side='right')
        menu=tk.Menu(tools,tearoff=False);tools.configure(menu=menu);self._tools_menu=menu
        for label,callback in [('Обучение',self._show_training),
            ('Обучить составной объект',self._show_visual_teacher),
            ('Уточнение объекта',self._show_object_question),
            ('Подсказки по зрительному обучению',self._show_visual_help),
            ('Задать цель',self._show_goal_dialog),('Язык → образ',self._show_language_dialog),
            ('Образ I / S',self._show_image),('Сигналы (таблица)',self._show_states),('Память текущего ядра',self._show_memory),
            ('Эксперименты',self._show_experiments),('Настройки зрения',self._show_settings),
            ('Нейроны в браузере',self._show_neurons),('Перезапустить движок',self._switch_engine)]:
            menu.add_command(label=label,command=callback)
        menu.add_separator()
        menu.add_command(label='Зрительный режим без UI Automation',command=lambda:self._states_send('/vision on'))
        menu.add_command(label='Вернуть наблюдатель текстовых полей',command=lambda:self._states_send('/vision off'))

    def _select_workspace(self,mode):
        super()._select_workspace(mode)
        if self._rail_buttons:self._rail_buttons['graph'].select(True)

    def _states_status(self):
        super()._states_status()
        if self._closing:return
        raw=self._current_status()
        capture='Захват включён' if self.capture.is_capturing else 'Захват выключен'
        status='Запись' if raw.get('recording') else 'Выполнение' if raw.get('running') else 'Ожидание'
        self._runtime_badge.set(f'{capture}   /   {status}   /   Такт {raw.get("tick", "—")}')

    def _current_status(self):
        raw=read_json(self._states_bridge.path/'status.json') or {}
        return raw if raw.get('session')==self._states_bridge.session else {}

    def _apply_speed(self,event=None):
        value=round(self._speed_value.get(),1);self._speed_label.set(f'{value:.1f} с / такт'.replace('.',','))
        self._states_send('/speed '+str(value))

    def _dialog(self,key,title,size='690x490'):
        existing=self._dialogs.get(key)
        if existing and existing.winfo_exists():existing.deiconify();existing.lift();return None
        win=tk.Toplevel(self.root);win.configure(bg=P['bg']);win.title('Neural Studio · '+title);win.geometry(size);self._dialogs[key]=win
        panel=ttk.Frame(win,padding=22);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text=title,style='Title.TLabel').pack(anchor='w',pady=(0,14))
        return panel

    def _show_settings(self):
        if hasattr(self,'_settings_window'):
            self._settings_window.deiconify();self._settings_window.lift();style_tree(self._settings_window)

    def _confirm_clear_objects(self):
        raw=self._current_status()
        if self.capture.is_capturing or raw.get('running') or raw.get('recording') or raw.get('pending') or raw.get('objectQuestion'):
            messagebox.showinfo('База объектов','Сначала остановите захват и завершите попытку Kolos. Во время работы база не очищается.',parent=self._settings_window)
            return
        if messagebox.askyesno('Удалить объекты Glaz?',
                'Будут удалены все распознанные объекты и сохранённые скриншоты объектов.\n'
                'Обученные команды, использующие прежние ID, потребуется проверить заново.\n\n'
                'Продолжить?',parent=self._settings_window,default='no'):
            super()._clear_objects_db()

    def _show_training(self):
        panel=self._dialog('learn','Обучение по показу','720x650')
        if panel is None:return
        ttk.Label(panel,text='Значок и подпись · дообучение o1',font=(self._studio_fonts['sans'],11,'bold'),foreground=P['accent']).pack(anchor='w',pady=(0,5))
        ttk.Label(panel,text='Дополните знакомую команду образом значка и его подписи. '
                  'В окне обучения выберите команду o1 и покажите нужный объект.',wraplength=660,style='Muted.TLabel').pack(anchor='w')
        row=ttk.Frame(panel);row.pack(fill='x',pady=(10,14))
        ttk.Button(row,text='Обучить составной объект',command=lambda:self._open_visual_training(panel)).pack(side='left')
        ttk.Button(row,text='Подсказки',command=self._show_visual_help).pack(side='left',padx=8)
        ttk.Separator(panel).pack(fill='x',pady=(0,4))
        for title,detail in [('01 · Команда','Введите задачу в постоянном терминале. Текст станет контекстом демонстрации.'),
            ('02 · Запись — 3','Вернитесь в целевое приложение. Дождитесь определения ID, покажите действие и его результат.'),
            ('03 · Завершение — Esc','Остановите запись, прежде чем пользоваться кнопками Glaz.'),
            ('04 · Сохранить — 5, затем 1','Подготовьте и подтвердите демонстрацию. Повторный запрос использует эту память.')]:
            ttk.Label(panel,text=title,font=(self._studio_fonts['sans'],11,'bold'),foreground=P['accent']).pack(anchor='w',pady=(10,5))
            ttk.Label(panel,text=detail,wraplength=630,style='Muted.TLabel').pack(anchor='w')
        ttk.Label(panel,text='F9 — аварийная остановка States. Неизвестные цифры должны быть показаны ранее.\nЦелевое приложение должно быть видно на экране.',wraplength=620).pack(anchor='w',pady=20)
        ttk.Button(panel,text='Вернуться к вводу команды',command=lambda:(panel.winfo_toplevel().destroy(),self._kolos_entry.focus_set())).pack(anchor='w')

    def _open_visual_training(self, panel: object) -> None:
        """Replace the introduction with the existing visual teaching window."""
        panel.winfo_toplevel().destroy()
        self._show_visual_teacher()

    def _show_experiments(self):
        panel=self._dialog('tests','Эксперименты','680x470')
        if panel is None:return
        ttk.Label(panel,text='Модельные проверки не заменяют проверку реальных приложений.\nОни не загружают учебный граф вместо вашей памяти ПК.',style='Muted.TLabel',wraplength=620).pack(anchor='w',pady=(0,14))
        for label,cmd in [('01–04 · Действия и состояния','/selftest'),('01–10 · Цели и планирование','/acceptance'),
                          ('11 · Образ и восприятие','/imagerytest'),('12 · Язык → образ','/languagetest'),('01–12 · Одна общая память','/sharedtest'),
                          ('Открыть отдельное тестовое окно Windows','/testpad')]:
            ttk.Button(panel,text=label,command=lambda c=cmd:self._states_send(c)).pack(fill='x',pady=3)

    def _show_memory(self):
        panel=self._dialog('memory','Память текущего ядра','850x550')
        if panel is None:return
        subtitle=tk.StringVar();ttk.Label(panel,textvariable=subtitle,style='Muted.TLabel',wraplength=790).pack(anchor='w',pady=(0,12))
        table=ttk.Treeview(panel,columns=('id','type','label'),show='headings',height=12)
        for key,label,width in [('id','ID',110),('type','Тип',140),('label','Содержимое / название',460)]:table.heading(key,text=label);table.column(key,width=width)
        table.pack(fill='both',expand=True)
        def refresh():
            raw=self._current_status();table.delete(*table.get_children());nodes=raw.get('nodes',[])
            for n in nodes:table.insert('','end',values=(n['id'],n.get('kind',''),n.get('label',n.get('value',''))))
            subtitle.set(f'Вершин опыта: {len(nodes)}   ·   Связей: {len(raw.get("edges",[]))}   ·   Только чтение' if raw else 'Нет актуального снимка States. Выберите «Состояния и цели (ПК)».')
        ttk.Button(panel,text='Обновить снимок',command=refresh).pack(anchor='e',pady=(12,0));refresh()
