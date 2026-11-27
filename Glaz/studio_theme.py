"""Neural Studio: native Tk design tokens, no engine or I/O dependencies.

System dialog chrome remains owned by Windows. No fonts are bundled and no
private Tk widgets/classes are monkey-patched. Tk scaling follows the display.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, font

P = dict(bg='#12141f', panel='#191c2a', canvas='#10121d', border='#30364d',
         text='#e7eaf5', muted='#9da6c2', accent='#a0acff', active='#2b3253',
         hover='#262b40', disabled='#687086', I='#bda0ff', S='#68d7d1',
         good='#b6e995', danger='#fa8797')


def install(root):
    """Install a coherent, OS-independent ttk theme within this Tk interpreter."""
    families = set(font.families(root))
    sans = 'Segoe UI' if 'Segoe UI' in families else 'DejaVu Sans'
    mono = 'Cascadia Code' if 'Cascadia Code' in families else 'Consolas' if 'Consolas' in families else 'DejaVu Sans Mono'
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont','TkCaptionFont','TkSmallCaptionFont','TkTooltipFont','TkIconFont'):
        font.nametofont(name).configure(family=sans, size=10)
    font.nametofont('TkFixedFont').configure(family=mono, size=9)
    root.option_add('*tearOff', False)
    for name,val in [('Background',P['panel']),('Foreground',P['text']),('selectBackground',P['active']),
                     ('selectForeground',P['text']),('insertBackground',P['accent']),('highlightBackground',P['border'])]:
        root.option_add('*'+name,val)
    # Native combo popup is a Tk listbox, not a ttk widget.
    root.option_add('*TCombobox*Listbox.background',P['panel'])
    root.option_add('*TCombobox*Listbox.foreground',P['text'])
    root.option_add('*TCombobox*Listbox.selectBackground',P['active'])
    style=ttk.Style(root)
    if 'neural-studio' not in style.theme_names():style.theme_create('neural-studio',parent='clam')
    style.theme_use('neural-studio')
    style.configure('.',background=P['bg'],foreground=P['text'],bordercolor=P['border'],
                    lightcolor=P['border'],darkcolor=P['border'],troughcolor=P['canvas'],font=(sans,10))
    style.configure('TFrame',background=P['bg'])
    style.configure('Panel.TFrame',background=P['panel'])
    style.configure('TLabel',background=P['bg'],foreground=P['text'])
    style.configure('Muted.TLabel',foreground=P['muted'])
    style.configure('Title.TLabel',font=(sans,15,'bold'))
    style.configure('Brand.TLabel',background=P['panel'],font=(sans,11,'bold'))
    style.configure('Panel.TLabel',background=P['panel'])
    style.configure('Kicker.TLabel',foreground=P['muted'],font=(sans,9))
    style.configure('TLabelframe',background=P['bg'],borderwidth=1,relief='solid')
    style.configure('TLabelframe.Label',background=P['bg'],foreground=P['muted'],font=(sans,9))
    style.configure('TButton',background=P['panel'],foreground=P['text'],padding=(11,7),borderwidth=1,
                    relief='flat',focuscolor=P['accent'],anchor='center')
    style.map('TButton',background=[('disabled',P['bg']),('pressed',P['active']),('active',P['hover'])],
              foreground=[('disabled',P['disabled'])],bordercolor=[('focus',P['accent'])])
    style.configure('Accent.TButton',background=P['accent'],foreground=P['canvas'],font=(sans,10,'bold'))
    style.map('Accent.TButton',background=[('disabled',P['panel']),('pressed','#8898f0'),('active','#b4bfff')],
              foreground=[('disabled',P['disabled']),('!disabled',P['canvas'])])
    style.configure('Danger.TButton',foreground=P['danger'])
    style.map('Danger.TButton',foreground=[('disabled',P['disabled']),('!disabled',P['danger'])])
    style.configure('Small.TButton',padding=(8,5),font=(sans,9))
    style.configure('Tab.TRadiobutton',padding=(14,8),background=P['bg'],foreground=P['muted'],focuscolor=P['accent'])
    style.layout('Tab.TRadiobutton',[('Radiobutton.padding',{'sticky':'nswe','children':[('Radiobutton.label',{'sticky':'nswe'})]})])
    style.map('Tab.TRadiobutton',background=[('selected',P['active']),('active',P['hover'])],
              foreground=[('selected',P['accent']),('active',P['text'])])
    style.configure('TEntry',fieldbackground=P['canvas'],foreground=P['text'],insertcolor=P['accent'],
                    padding=(9,7),borderwidth=1,selectbackground=P['active'])
    style.map('TEntry',bordercolor=[('focus',P['accent'])],foreground=[('disabled',P['disabled'])])
    style.configure('TCombobox',fieldbackground=P['panel'],background=P['panel'],foreground=P['text'],arrowcolor=P['muted'],padding=(8,6),borderwidth=1)
    style.map('TCombobox',fieldbackground=[('readonly',P['panel'])],foreground=[('disabled',P['disabled']),('readonly',P['text'])],selectbackground=[('readonly',P['panel'])],selectforeground=[('readonly',P['text'])])
    style.configure('TSpinbox',fieldbackground=P['canvas'],background=P['panel'],foreground=P['text'],arrowcolor=P['muted'],padding=5)
    style.configure('TCheckbutton',padding=(5,4),background=P['bg'],foreground=P['muted'],indicatorbackground=P['canvas'],indicatorforeground=P['accent'])
    style.map('TCheckbutton',background=[('active',P['bg'])],foreground=[('disabled',P['disabled']),('selected',P['text'])],indicatorbackground=[('selected',P['accent'])])
    style.configure('TRadiobutton',background=P['bg'],foreground=P['muted'])
    style.configure('TMenubutton',background=P['panel'],foreground=P['text'],padding=(10,6),arrowcolor=P['muted'],borderwidth=1)
    style.configure('Treeview',background=P['canvas'],fieldbackground=P['canvas'],foreground=P['text'],
                    rowheight=30,borderwidth=0,font=(sans,10))
    style.configure('Treeview.Heading',background=P['panel'],foreground=P['muted'],padding=(10,9),font=(sans,9))
    style.map('Treeview',background=[('selected',P['active'])],foreground=[('selected',P['text'])])
    style.map('Treeview.Heading',background=[('active',P['hover'])])
    style.configure('Vertical.TScrollbar',background=P['border'],troughcolor=P['canvas'],arrowcolor=P['muted'],borderwidth=0,arrowsize=12)
    style.configure('Horizontal.TScrollbar',background=P['border'],troughcolor=P['canvas'],arrowcolor=P['muted'],borderwidth=0,arrowsize=12)
    style.configure('TSeparator',background=P['border'])
    style.configure('TPanedwindow',background=P['border']);style.configure('Sash',sashthickness=5,gripcount=0)
    style.configure('Horizontal.TScale',background=P['accent'],troughcolor=P['border'],borderwidth=0,sliderlength=16)
    style.configure('TNotebook',background=P['bg'],borderwidth=0)
    style.configure('TNotebook.Tab',padding=(14,8),background=P['panel'],foreground=P['muted'])
    style.map('TNotebook.Tab',background=[('selected',P['active'])],foreground=[('selected',P['accent'])])
    # Rounded native ttk button surfaces, generated from Pillow already used by Glaz.
    # No WebView, downloaded artwork or font files.
    from PIL import Image, ImageDraw, ImageTk
    root._studio_button_images=[]
    for prefix,normal,hover,pressed in [('Studio',P['panel'],P['hover'],P['active']),
                                       ('StudioAccent',P['accent'],'#b4bfff','#8898f0')]:
        images=[]
        for color in (normal,hover,pressed,P['bg']):
            img=Image.new('RGBA',(120,120),(0,0,0,0));draw=ImageDraw.Draw(img)
            draw.rounded_rectangle((2,2,118,118),radius=28,fill=color,
                                   outline=P['border'] if prefix=='Studio' else color,width=4)
            photo=ImageTk.PhotoImage(img.resize((30,30),Image.Resampling.LANCZOS),master=root)
            images.append(photo);root._studio_button_images.append(photo)
        element=prefix+'.button'
        style.element_create(element,'image',images[0],('disabled',images[3]),('pressed',images[2]),('active',images[1]),border=8,sticky='nswe')
        layout=[(element,{'sticky':'nswe','children':[('Button.focus',{'sticky':'nswe','children':[('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})]})]
        style.layout('TButton' if prefix=='Studio' else 'Accent.TButton',layout)
    root.configure(background=P['bg'])
    return dict(sans=sans,mono=mono)


def style_tree(widget):
    """Theme classic text/list/menu widgets without touching data or image pixels."""
    try:
        if isinstance(widget,tk.Toplevel):widget.configure(background=P['bg'])
        elif isinstance(widget,tk.Text):
            widget.configure(bg=P['canvas'],fg=P['muted'],selectbackground=P['active'],selectforeground=P['text'],
                             insertbackground=P['accent'],relief='flat',highlightthickness=0,padx=12,pady=8)
        elif isinstance(widget,tk.Listbox):
            widget.configure(bg=P['canvas'],fg=P['text'],selectbackground=P['active'],selectforeground=P['text'],
                             relief='flat',highlightthickness=1,highlightbackground=P['border'],borderwidth=0)
        elif isinstance(widget,tk.Menu):
            widget.configure(bg=P['panel'],fg=P['text'],activebackground=P['active'],activeforeground=P['text'],borderwidth=0)
        elif isinstance(widget,tk.Frame):widget.configure(bg=P['bg'])
        elif isinstance(widget,tk.Scrollbar):widget.configure(bg=P['border'],troughcolor=P['canvas'],activebackground=P['muted'],borderwidth=0)
        for child in widget.winfo_children():style_tree(child)
    except tk.TclError:pass


class RailButton(tk.Canvas):
    """Keyboard-accessible narrow navigation with a real label and vector icon."""
    def __init__(self,parent,key,label,command):
        super().__init__(parent,width=62,height=65,background=P['panel'],highlightthickness=0,takefocus=True,cursor='hand2')
        self.key,self.label,self.command=key,label,command;self.selected=False;self.hover=False
        self.bind('<Button-1>',lambda e:self.command())
        self.bind('<Return>',lambda e:self.command());self.bind('<space>',lambda e:self.command())
        self.bind('<Enter>',lambda e:self._hover(True));self.bind('<Leave>',lambda e:self._hover(False))
        self.bind('<FocusIn>',lambda e:self._hover(True));self.bind('<FocusOut>',lambda e:self._hover(False));self.draw()
    def _hover(self,on):self.hover=on;self.draw()
    def select(self,on):self.selected=on;self.draw()
    def draw(self):
        self.delete('all');color=P['accent'] if self.selected else P['text'] if self.hover else P['muted']
        if self.selected or self.hover:self.create_rectangle(6,4,56,47,fill=P['active'] if self.selected else P['hover'],outline='')
        if self.key=='graph':
            pts=[(22,17),(40,19),(25,35),(42,34)]
            for a,b in [(0,1),(0,2),(1,2),(2,3)]:self.create_line(*pts[a],*pts[b],fill=color)
            for x,y in pts:self.create_oval(x-2,y-2,x+2,y+2,outline=color,width=1.5)
        elif self.key=='learn':
            self.create_polygon(17,23,31,17,45,23,31,30,outline=color,fill='');self.create_line(22,26,22,35,31,39,40,35,40,26,fill=color)
        elif self.key=='tests':self.create_line(21,26,28,33,43,18,fill=color,width=2)
        elif self.key=='memory':
            self.create_oval(21,17,43,24,outline=color);self.create_line(21,20,21,36,43,36,43,20,fill=color)
            self.create_arc(21,27,43,35,start=180,extent=180,style='arc',outline=color)
        else:
            for y,x in [(19,26),(27,38),(35,25)]:self.create_line(19,y,44,y,fill=color);self.create_rectangle(x-2,y-2,x+2,y+2,fill=P['panel'],outline=color)
        self.create_text(31,55,text=self.label,fill=color,font=('TkDefaultFont',8))
