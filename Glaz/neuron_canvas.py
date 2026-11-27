"""Native Tk view for the running Glaz child; never executes graph actions.

This renderer consumes detached telemetry. It does not compute neural dynamics,
replace observations, learn, click, or advance a simulator. Canvas motion only
illustrates a contribution that the engine has already calculated.
"""
from __future__ import annotations
import math
import time
import tkinter as tk
from tkinter import ttk
from kolos_states.neuron_projection import group_edges, number

BG = '#101c25'
COLORS = dict(I='#b997ff', S='#59d7cf', A='#afed80', inhibition='#fa7e8e', structure='#354a58')
LAYERS = {'Образ и переходы':'overview', 'Образ I / S':'image', 'Состояния и действия':'world',
          'Символы':'input', 'Язык':'language', 'Зрение и внимание':'visual', 'Вся память':'all'}


def fmt(value):
    return '—' if value is None else f'{number(value):.3f}'.rstrip('0').rstrip('.')


def blend(a, b, amount):
    t = max(0, min(1, amount))
    return '#'+''.join(f'{round(int(a[i:i+2],16)*(1-t)+int(b[i:i+2],16)*t):02x}' for i in (1,3,5))


class NeuronCanvas(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.frame = None; self.latest = None; self.positions = {}; self.camera = [20,20,1.0]
        self.selection = None; self.visible = False; self.closed = False; self.motion_started = 0.0
        self.anim_job = None; self.redraw_job = None; self.particles = []; self.hit = {}; self.drag = None
        self.node_ids = set(); self.rendered_nodes = []; self.rendered_edges = []
        self.frozen = tk.BooleanVar(value=False); self.only_active = tk.BooleanVar(value=False)
        self.layer = tk.StringVar(value='Образ и переходы'); self.search = tk.StringVar()
        self.banner = tk.StringVar(value='Выберите «Состояния и цели (ПК)». Здесь будет работа текущего ядра.')
        ttk.Label(self, textvariable=self.banner, anchor='w', wraplength=1100).pack(fill='x', padx=8, pady=5)
        tools = ttk.Frame(self); tools.pack(fill='x', padx=8, pady=3)
        selector = ttk.Combobox(tools, values=list(LAYERS), textvariable=self.layer, width=23, state='readonly')
        selector.pack(side='left'); selector.bind('<<ComboboxSelected>>', lambda e:self.refit())
        ttk.Entry(tools, textvariable=self.search, width=18).pack(side='left', padx=6)
        self.search.trace_add('write', lambda *args:self.schedule_draw())
        ttk.Checkbutton(tools, text='Активные', variable=self.only_active, command=self.refit).pack(side='left')
        ttk.Button(tools, text='Вписать', command=self.fit).pack(side='left', padx=4)
        ttk.Checkbutton(tools, text='Заморозить рисунок', variable=self.frozen, command=self.freeze_changed).pack(side='left')
        ttk.Label(self, text='I — образ   S — наблюдение   A — активация   C — кандидат   Красный — торможение   ☆ — выбор ядра', anchor='w').pack(fill='x', padx=8, pady=3)
        self.pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL); self.pane.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(self.pane, bg=BG, highlightthickness=0, width=780, height=260)
        self.inspector = tk.Text(self.pane, width=30, height=10, wrap='word', bg='#182731', fg='#d5e6eb', relief='flat',
                                 font=('Segoe UI', 10), padx=12, pady=10, state='disabled')
        self.pane.add(self.canvas, weight=4); self.pane.add(self.inspector, weight=0)
        self.footer = tk.StringVar(value='Ожидание снимка. Терминал и захват продолжают работать при переключении вида.')
        ttk.Label(self, textvariable=self.footer, anchor='w').pack(fill='x', padx=8, pady=3)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', lambda e:setattr(self,'drag',None))
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<Button-4>', lambda e:self.zoom(1.15,e.x,e.y))
        self.canvas.bind('<Button-5>', lambda e:self.zoom(1/1.15,e.x,e.y))
        self.canvas.bind('<Configure>', lambda e:self.schedule_draw())
        self._details('Нажмите на вершину или связь.\n\nЧисла приходят из работающего Python-ядра.\n\n«Заморозить рисунок» НЕ останавливает Kolos. Для остановки алгоритма используйте «Пауза» / F9 в Glaz.')

    def set_visible(self, visible):
        self.visible = bool(visible)
        if self.visible: self.schedule_draw()
        else: self._cancel_motion()

    def clear(self, message='Ожидание нового сеанса ядра.'):
        self._cancel_motion(); self.frame = self.latest = None; self.positions.clear(); self.node_ids.clear()
        self.canvas.delete('all'); self.banner.set(message); self.footer.set(message); self.last_runtime = None; self.selection = None
        self._details('Нет актуального снимка. Запустите новый запрос или представление в терминале.')

    def set_frame(self, frame, *, skipped=0, running=False, recording=False):
        self.latest = frame; self.latest_skipped = skipped
        if self.frozen.get():
            self.footer.set('РИСУНОК ЗАМОРОЖЕН — ядро не остановлено. Снимите галочку, чтобы вернуться к текущему такту.')
            return
        self.frame = frame
        state = 'ЗАПИСЬ ОБУЧЕНИЯ' if recording else 'РАБОТАЕТ' if running else 'ПАУЗА / ОЖИДАНИЕ'
        event = frame.get('event', {}).get('kind','')
        self.banner.set(f"{state}  ·  Такт {frame['tick']}  ·  {event}  ·  {frame.get('message','')[:155]}")
        self.runtime=(running,recording); self.skipped = skipped; self.motion_started = time.monotonic() if running else 0
        if self.visible: self.draw()

    def set_runtime(self, *, running=False, recording=False, connected=True):
        state=(running,recording,connected)
        if getattr(self,'last_runtime',None)==state:return
        self.last_runtime=state
        if not running:self._cancel_motion();self.motion_started=0.0
        if not connected:
            self.banner.set('Нет связи с процессом Kolos. Показан последний снимок, не текущее состояние.')
        elif self.frame and not self.frozen.get():
            label='ЗАПИСЬ ОБУЧЕНИЯ' if recording else 'РАБОТАЕТ' if running else 'ПАУЗА / ОЖИДАНИЕ'
            self.banner.set(f"{label} · Такт {self.frame['tick']} · {self.frame.get('message','')[:180]}")

    def freeze_changed(self):
        self._cancel_motion()
        if self.frozen.get():
            self.footer.set('РИСУНОК ЗАМОРОЖЕН — Kolos продолжает работу. Пауза ядра находится в терминале.')
        elif self.latest:
            runtime = getattr(self, 'last_runtime', None) or (False, False, True)
            self.set_frame(self.latest, skipped=getattr(self, 'latest_skipped', 0), running=runtime[0], recording=runtime[1])
            self.last_runtime = None
            self.set_runtime(running=runtime[0], recording=runtime[1], connected=runtime[2])

    def _details(self, text):
        self.inspector.configure(state='normal'); self.inspector.delete('1.0', 'end')
        self.inspector.insert('end', text); self.inspector.configure(state='disabled')

    def filtered(self):
        if not self.frame: return []
        nodes = self.frame['nodes']; layer = LAYERS[self.layer.get()]
        if layer == 'overview': nodes = [n for n in nodes if n['group'] in ('world','goals') or n['group']=='image' and (n.get('target') or n.get('present') or n['kind']=='source') or n['kind']=='occurrence']
        elif layer == 'image': nodes = [n for n in nodes if n['I'] is not None or n['group'] in ('image','goals')]
        elif layer == 'world': nodes = [n for n in nodes if n['group'] in ('world','actions','goals')]
        elif layer in ('input','language','visual'): nodes = [n for n in nodes if n['group']==layer]
        query = self.search.get().casefold()
        nodes = [n for n in nodes if query in (n['label']+' '+n['id']).casefold()]
        if self.only_active.get(): nodes = [n for n in nodes if n['energy']>.005 or n['current'] or n['held'] or n['winner']]
        return nodes

    def schedule_draw(self):
        if not self.closed and self.visible and self.redraw_job is None:
            self.redraw_job = self.after(60,self._scheduled_draw)

    def _scheduled_draw(self):
        self.redraw_job = None
        if self.visible and not self.closed: self.draw()

    def refit(self):
        self.positions.clear(); self.node_ids.clear(); self.draw(); self.fit()

    def draw(self):
        if self.closed or not self.visible or not self.frame: return
        self._cancel_motion()
        all_nodes = self.filtered(); nodes = all_nodes[:300]; ids = {n['id'] for n in nodes}
        new_ids = ids != self.node_ids; self.node_ids = ids
        counts = {}; taken = list(self.positions.values())
        for n in nodes:
            group = n['group']; idx = counts.get(group,0); counts[group] = idx+1
            if n['id'] in self.positions: continue
            col = {'image':0,'goals':0,'world':3,'actions':6,'input':9,'language':12,'memory':15}.get(group,15)
            x = (col+idx%3)*155+95; y = (idx//3)*145+90
            while any(math.hypot(x-a,y-b)<110 for a,b in taken): y += 145
            self.positions[n['id']] = (x,y); taken.append((x,y))
        self.rendered_nodes = nodes
        self.rendered_edges = group_edges([e for e in self.frame['edges'] if e['source'] in ids and e['target'] in ids])
        if new_ids: self._fit_camera()
        self.canvas.delete('all'); self.hit.clear(); self.particles.clear()
        for i,e in enumerate(self.rendered_edges):
            sx,sy = self._point(self.positions[e['source']]); tx,ty = self._point(self.positions[e['target']])
            z = self.camera[2]; dx=tx-sx;dy=ty-sy;length=math.hypot(dx,dy) or 1
            ux,uy=dx/length,dy/length; sx+=ux*27*z;sy+=uy*27*z;tx-=ux*30*z;ty-=uy*30*z
            bend=25*z; cx=(sx+tx)/2-uy*bend;cy=(sy+ty)/2+ux*bend
            active = e['provenance']!='structure' and number(e.get('flow'))>0
            color = COLORS['inhibition'] if e['kind']=='inhibition' else COLORS.get(e['kind'],COLORS['A']) if active else COLORS['structure']
            opts = dict(fill=color,width=2 if active else 1,smooth=True,arrow='last',arrowshape=(7,9,3))
            if e['provenance']=='structure': opts['dash']=(3,5)
            item=self.canvas.create_line(sx,sy,cx,cy,tx,ty,**opts);self.hit[item]=('edge',tuple(e['ids']))
            if z>.40 or active:
                label=', '.join(e['ids'])
                if all(id.startswith('view:') for id in e['ids']):
                    label={'order':'порядок','inhibition':'торможение','goal-drive':'цель','motor-drive':'вход','language-charge':'чтение'}.get(e['kind'],e['kind'])
                label=label[:27]+'…' if len(label)>28 else label
                if e['weight'] is not None: label+=' · '+fmt(e['weight'])
                item=self.canvas.create_text(cx,cy-9,text=label,fill='#7894a4',font=('Segoe UI',max(7,round(9*z))))
                self.hit[item]=('edge',tuple(e['ids']))
            if active:
                dot=self.canvas.create_oval(0,0,0,0,fill=color,outline='')
                self.particles.append((dot,(sx,sy,cx,cy,tx,ty)))
        for n in nodes:
            x,y=self._point(self.positions[n['id']]);z=self.camera[2];r=26*z
            energy=max(0,min(1,n['energy']));stroke=COLORS['inhibition'] if n['kind']=='error' else COLORS['A']
            color=blend('#1a2b38', stroke, energy*.7)
            ids_=[]
            if energy>.05: ids_.append(self.canvas.create_oval(x-r-6,y-r-6,x+r+6,y+r+6,outline=blend(BG,stroke,energy*.7),width=3))
            opts=dict(fill=color,outline=stroke if n['winner'] or n['current'] else '#526879',width=3 if n['winner'] else 1)
            if n['kind']=='source':opts['dash']=(3,3)
            ids_.append(self.canvas.create_oval(x-r,y-r,x+r,y+r,**opts))
            for channel,start in [('I',90),('S',-90)]:
                if n[channel] is not None and number(n[channel])>0:
                    ids_.append(self.canvas.create_arc(x-r-3,y-r-3,x+r+3,y+r+3,start=start,extent=180*number(n[channel]),style='arc',outline=COLORS[channel],width=3))
            central='☆' if n['winner'] else fmt(n['C'] if n['C'] is not None else n['A'])
            if n['I'] is not None:central=fmt(max(number(n['I']),number(n['S'])))
            ids_.append(self.canvas.create_text(x,y,text=central,fill='#e2f1f5',font=('Segoe UI',max(8,round(11*z)))))
            label=n['label'];label=label[:25]+'…' if len(label)>26 else label
            ids_.append(self.canvas.create_text(x,y+r+13,text=label,fill='#e2f1f5',font=('Segoe UI',max(8,round(10*z)))))
            signals=f"I {fmt(n['I'])} · S {fmt(n['S'])}" if n['I'] is not None else f"A {fmt(n['A'])} · C {fmt(n['C'])}"
            ids_.append(self.canvas.create_text(x,y+r+29,text=signals,fill='#a6bdc9',font=('Segoe UI',max(7,round(9*z)))))
            if n['R']:ids_.append(self.canvas.create_text(x,y-r-12,text='R '+str(n['R']),fill=COLORS['inhibition']))
            for item in ids_:self.hit[item]=('node',n['id'])
        self.footer.set(f"{len(nodes)} / {len(all_nodes)} вершин · {len(self.rendered_edges)} групп связей · Пропущено снимков: {getattr(self,'skipped',0)}. Колесо — масштаб; фон — перемещение; клик — параметры.")
        if len(all_nodes)>300:self.footer.set(self.footer.get()+' Лимит рисунка 300, память не обрезана.')
        self.details();self._animate()

    def _point(self, pos):
        x,y,z=self.camera; return pos[0]*z+x,pos[1]*z+y

    def _fit_camera(self):
        if not self.rendered_nodes: return
        ps=[self.positions[n['id']] for n in self.rendered_nodes]
        left=min(p[0] for p in ps)-75;right=max(p[0] for p in ps)+80
        top=min(p[1] for p in ps)-55;bottom=max(p[1] for p in ps)+75
        w=max(200,self.canvas.winfo_width());h=max(180,self.canvas.winfo_height())
        z=max(.08,min(1.4,(w-24)/(right-left),(h-24)/(bottom-top)))
        self.camera=[w/2-(left+right)*z/2,h/2-(top+bottom)*z/2,z]

    def fit(self):
        self._fit_camera();self.draw()

    def _animate(self):
        self.anim_job=None
        if not self.visible or self.closed: return
        dt=time.monotonic()-self.motion_started
        progress=min(1,dt/.65) if self.motion_started and not self.frozen.get() else .55
        for dot,(sx,sy,cx,cy,tx,ty) in self.particles:
            t=progress; x=(1-t)**2*sx+2*(1-t)*t*cx+t*t*tx;y=(1-t)**2*sy+2*(1-t)*t*cy+t*t*ty
            self.canvas.coords(dot,x-4,y-4,x+4,y+4)
        if progress<1 and self.motion_started and not self.frozen.get():self.anim_job=self.after(40,self._animate)

    def _cancel_motion(self):
        if self.anim_job is not None:
            self.after_cancel(self.anim_job);self.anim_job=None

    def details(self):
        if not self.selection or not self.frame:return
        kind,id=self.selection
        if kind=='node':
            n=next((n for n in self.frame['nodes'] if n['id']==id),None)
            if n is None:return self._details('Вершины нет в этом снимке.')
            text=f"{n['label']}\n\nID: {id}\nТип: {n['kind']}\n"
            for key in ('A','C','I','S','T','R','threshold'):text+=f"{key}: {fmt(n.get(key))}\n"
            text+='\nЕсть сейчас: '+str(n.get('present','—'))+'\nУдерживается: '+str(n.get('held','—'))
            if n.get('calculation'):
                c=n['calculation'];text+=f"\n\nВход: {fmt(c.get('input'))}\nОпыт: {fmt(c.get('history'))}\nТорможение: {fmt(c.get('inhibition'))}"
            if n['I'] is not None:text+='\n\nI и S не суммируются для подтверждения результата. Нужен принятый внешний признак.'
        else:
            e=next((edge for edge in self.rendered_edges if any(key in edge['ids'] for key in id)),None)
            if e is None:return self._details('Связи нет в этом слое или снимке.')
            text=', '.join(e['ids'])+f"\n\n{e['source']} → {e['target']}\nТип: {e['kind']}\nВес: {fmt(e['weight'])}\nПередача: {fmt(e['flow'])}\nПолезный вклад: {fmt(e['term'])}\nИсточник: {e['provenance']}\n\n{e.get('note','')}"
        obs=self.frame['observed'];text+='\n\nПРИНЯТОЕ НАБЛЮДЕНИЕ\n'+('«'+obs.get('output','')+'»' if obs.get('focus') else 'Поле скрыто')
        if self.frame.get('pending'):text+='\nОжидается подтверждение действия.'
        self._details(text)

    def press(self,e):
        items=self.canvas.find_overlapping(e.x-3,e.y-3,e.x+3,e.y+3)
        self.selection=next((self.hit[i] for i in reversed(items) if i in self.hit),None)
        self.drag=(e.x,e.y);self.details()

    def move(self,e):
        if self.drag is None:return
        self.camera[0]+=e.x-self.drag[0];self.camera[1]+=e.y-self.drag[1];self.drag=(e.x,e.y);self.draw()

    def zoom(self,factor,x,y):
        old=self.camera[2];z=max(.08,min(4,old*factor));self.camera=[x-(x-self.camera[0])*z/old,y-(y-self.camera[1])*z/old,z];self.draw()
        return 'break'

    def wheel(self,e):
        return self.zoom(1.12 if e.delta>0 else 1/1.12,e.x,e.y)

    def close(self):
        self.closed=True;self._cancel_motion()
        if self.redraw_job is not None:self.after_cancel(self.redraw_job);self.redraw_job=None
