"""Neural Studio surface around the existing read-only neuron renderer.

The minimap, inspector and dot grid are presentation only. They never call the
engine. Telemetry values and edge provenance come from NeuronCanvas unchanged.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
import neuron_canvas as original
from neuron_canvas import NeuronCanvas, fmt
from studio_theme import P, style_tree


class StudioNeuronCanvas(NeuronCanvas):
    def __init__(self,parent):
        original.BG=P['canvas']
        original.COLORS.update(I=P['I'],S=P['S'],A=P['good'],inhibition=P['danger'],structure=P['border'])
        self._card=None;self._mini=None;self._mini_map=None
        super().__init__(parent)
        self.canvas.configure(background=P['canvas'],highlightbackground=P['border'],highlightthickness=1)
        self.pane.forget(self.inspector);self.inspector.destroy()
        self._card=tk.Frame(self.canvas,bg=P['panel'],highlightbackground=P['border'],highlightthickness=1)
        self._card.place(relx=1,x=-14,y=14,anchor='ne',width=242,height=370)
        tk.Label(self._card,text='ИНСПЕКТОР СИГНАЛА',bg=P['panel'],fg=P['muted'],font=('TkDefaultFont',9),anchor='w').pack(fill='x',padx=14,pady=(14,6))
        self._metrics=tk.Canvas(self._card,bg=P['panel'],height=92,highlightthickness=0)
        self._metrics.pack(fill='x',padx=14,pady=(0,4))
        self.inspector=tk.Text(self._card,wrap='word',bg=P['panel'],fg=P['muted'],relief='flat',
                               font=('TkDefaultFont',9),padx=14,pady=8,state='disabled',borderwidth=0,highlightthickness=0)
        self.inspector.pack(fill='both',expand=True)
        self.inspector.tag_configure('heading',foreground=P['text'],font=('TkDefaultFont',13,'bold'),spacing3=12)
        self._mini=tk.Canvas(self.canvas,width=145,height=88,bg=P['panel'],highlightbackground=P['border'],highlightthickness=1,cursor='hand2')
        self._mini.place(x=14,rely=1,y=-46,anchor='sw');self._mini.bind('<Button-1>',self._minimap_click)
        controls=ttk.Frame(self.canvas,style='Panel.TFrame');controls.place(x=14,rely=1,y=-12,anchor='sw')
        for label,callback in [('+',lambda:self.zoom(1.25,self.canvas.winfo_width()/2,self.canvas.winfo_height()/2)),
                               ('−',lambda:self.zoom(.8,self.canvas.winfo_width()/2,self.canvas.winfo_height()/2)),('Вписать',self.fit)]:
            ttk.Button(controls,text=label,command=callback,style='Small.TButton',width=5 if label!='Вписать' else 8).pack(side='left',padx=(0,2))
        self._inspector_on=tk.BooleanVar(value=True)
        self._toggle=ttk.Checkbutton(self,text='Инспектор',variable=self._inspector_on,command=self._toggle_card)
        # Reuse the existing toolbar instead of adding a second line.
        toolbar=next(w for w in self.winfo_children() if isinstance(w,ttk.Frame) and w not in (self.pane,))
        self._toggle.pack(in_=toolbar,side='right')
        style_tree(self);self.inspector.configure(bg=P['panel']);self._details('Выберите вершину\n\nI — внутренний образ\nS — наблюдение\nA — активация\nC — кандидат\n\nГраф получает реальные снимки текущего ядра. Без снимка здесь нет учебного примера.')
        self.canvas.bind('<Configure>',self._resize,add='+')

    def _resize(self,event=None):
        if self._card is None:return
        h=max(100,min(440,self.canvas.winfo_height()-28));self._card.configure(height=h)
        self._toggle_card(refit=False)

    def _toggle_card(self,refit=True):
        if self._card is None:return
        if self._inspector_on.get():self._card.place(relx=1,x=-14,y=14,anchor='ne',width=242)
        else:self._card.place_forget()
        if refit:self.fit()

    def _fit_camera(self):
        if not self.rendered_nodes:return
        ps=[self.positions[n['id']] for n in self.rendered_nodes]
        left=min(x for x,y in ps)-80;right=max(x for x,y in ps)+85
        top=min(y for x,y in ps)-55;bottom=max(y for x,y in ps)+82
        reserve=265 if self._card and self._inspector_on.get() else 0
        w=max(160,self.canvas.winfo_width()-reserve);h=max(160,self.canvas.winfo_height())
        z=max(.08,min(1.55,(w-30)/(right-left),(h-45)/(bottom-top)))
        self.camera=[w/2-(left+right)*z/2,h/2-(top+bottom)*z/2,z]

    def draw(self):
        if self.closed or not self.visible:return
        if not self.frame:
            self.canvas.delete('empty');w=self.canvas.winfo_width();h=self.canvas.winfo_height()
            self.canvas.create_text(max(140,(w-250)/2),max(90,h/2),text='Ожидание активности\n\nВведите команду в терминале ниже',
                                    fill=P['muted'],font=('TkDefaultFont',12),justify='center',tags='empty')
            return
        # Stable, compact rows in the chosen layer. These are only canvas coordinates.
        nodes=self.filtered()[:300];groups={}
        for n in nodes:groups.setdefault(n['group'],[]).append(n)
        if self.layer.get()=='Образ I / S':
            targets=[n for n in nodes if n['group']=='image' and n['kind']!='source']
            other=[n for n in nodes if n not in targets]
            for i,n in enumerate(targets):self.positions.setdefault(n['id'],(95+(i%6)*170,90+(i//6)*170))
            for i,n in enumerate(other):self.positions.setdefault(n['id'],(95+(i%6)*170,90+max(1,(len(targets)+5)//6)*170+(i//6)*170))
        elif self.layer.get()=='Образ и переходы':
            order=['image','world','goals','input'];row=0
            for group in order:
                block=groups.get(group,[])
                block=sorted(block,key=lambda n:n['kind']=='source')
                for i,n in enumerate(block):
                    self.positions.setdefault(n['id'],(95+(i%6)*170,90+row*165+(i//6)*165))
                row+=(len(block)+5)//6
        super().draw()
        # Signal hue preserves I/S distinctions instead of painting every node green.
        by_id={n['id']:n for n in self.rendered_nodes}
        for item,hit in self.hit.items():
            if hit[0]!='node' or self.canvas.type(item)!='oval':continue
            n=by_id[hit[1]]
            color=P['I'] if n['I'] is not None and n['I']>0.005 else P['S'] if n['S'] is not None and n['S']>0.005 else P['good'] if n['winner'] else P['accent']
            if n['kind']=='error':color=P['danger']
            fill=self.canvas.itemcget(item,'fill')
            if fill:self.canvas.itemconfigure(item,fill=original.blend('#23283c',color,max(0,min(1,n['energy']))*.25),outline=color if n['energy']>.005 else '#5d658d')
            else:self.canvas.itemconfigure(item,outline=original.blend(P['canvas'],color,.35))
        # Grid is a visual aid, not a source of neural activation.
        for x in range(14,self.canvas.winfo_width(),28):
            for y in range(14,self.canvas.winfo_height(),28):
                self.canvas.create_oval(x,y,x+1,y+1,fill='#24283d',outline='',tags='grid')
        self.canvas.tag_lower('grid')
        replacements={'#7894a4':P['muted'],'#526879':'#5d658d','#e2f1f5':P['text'],'#a6bdc9':P['muted']}
        for item in self.canvas.find_all():
            for prop in ('fill','outline'):
                try:
                    value=self.canvas.itemcget(item,prop)
                    if value in replacements:self.canvas.itemconfigure(item,**{prop:replacements[value]})
                except tk.TclError:pass
        self._draw_minimap()
        if self._card:self._card.lift()

    def clear(self,message='Ожидание нового сеанса ядра.'):
        super().clear(message)
        if self._mini:self._mini.delete('all');self._mini_map=None
        if self._card:self._metrics.delete('all')
        if self.visible:self.draw()

    def _details(self,text):
        super()._details(text)
        try:
            self.inspector.tag_add('heading','1.0','1.end')
            if self._card:
                self._metrics.delete('all')
                node=next((n for n in (self.frame or {}).get('nodes',[]) if self.selection==('node',n['id'])),None)
                for i,(key,label,color) in enumerate([('C','Сигнал кандидата',P['accent']),('I','Внутренний образ',P['I']),('S','Наблюдение',P['S'])]):
                    value=node.get(key) if node else None;y=8+i*29
                    self._metrics.create_text(0,y,text=label,anchor='w',fill=P['muted'],font=('TkDefaultFont',8))
                    self._metrics.create_text(209,y,text=fmt(value),anchor='e',fill=P['text'],font=('TkFixedFont',8))
                    self._metrics.create_line(0,y+12,209,y+12,fill=P['border'],width=3)
                    if value is not None:self._metrics.create_line(0,y+12,209*max(0,min(1,value)),y+12,fill=color,width=3)
        except tk.TclError:pass

    def _draw_minimap(self):
        if self._mini is None or not self.rendered_nodes:return
        self._mini.delete('all');ps=[self.positions[n['id']] for n in self.rendered_nodes]
        left=min(p[0] for p in ps)-60;top=min(p[1] for p in ps)-60
        width=max(p[0] for p in ps)-left+60;height=max(p[1] for p in ps)-top+60
        scale=min(129/max(1,width),70/max(1,height));self._mini_map=(left,top,scale)
        def xy(pos):return ((pos[0]-left)*scale+8,(pos[1]-top)*scale+8)
        for e in self.rendered_edges:
            self._mini.create_line(*xy(self.positions[e['source']]),*xy(self.positions[e['target']]),fill=P['border'])
        for n in self.rendered_nodes:
            x,y=xy(self.positions[n['id']]);self._mini.create_oval(x-1.5,y-1.5,x+1.5,y+1.5,fill=P['good'] if n['energy']>.05 else P['muted'],outline='')
        cx,cy,z=self.camera
        a=xy((-cx/z,-cy/z));b=xy(((self.canvas.winfo_width()-cx)/z,(self.canvas.winfo_height()-cy)/z))
        self._mini.create_rectangle(*a,*b,outline=P['accent'])

    def _minimap_click(self,event):
        if not self._mini_map:return
        left,top,scale=self._mini_map;x=(event.x-8)/scale+left;y=(event.y-8)/scale+top
        reserve=265 if self._inspector_on.get() else 0
        self.camera[0]=(self.canvas.winfo_width()-reserve)/2-x*self.camera[2]
        self.camera[1]=self.canvas.winfo_height()/2-y*self.camera[2];self.draw()
