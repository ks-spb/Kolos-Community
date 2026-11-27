"""Controlled pixels, independent of recognizer internals and target names."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from Glaz.perception.retina import lesson, collect
from kolos_states.perception.learning import teach
from kolos_states.perception.types import views


def font(size: int = 16) -> ImageFont.ImageFont:
    """Use an installed renderer; no downloaded font or OCR dependency."""
    for name in ['C:/Windows/Fonts/arial.ttf', 'DejaVuSans.ttf']:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def scene(names: tuple = ('Contracts', 'Documents', 'Reports'), *, right: bool = False,
          order: tuple = (0, 1, 2), factor: int = 1) -> tuple:
    """Move the complete object; all three icons have identical pixels."""
    frame = Image.new('RGB', (600*factor, 230*factor), 'white'); draw = ImageDraw.Draw(frame)
    boxes, labels = [], []
    for index in range(3):
        x, y = (30+order[index]*190)*factor, 35*factor; w = 30*factor
        draw.rectangle([x, y, x+w-1, y+w-1], fill='#447799')
        draw.rectangle([x+5*factor, y+8*factor, x+24*factor, y+21*factor], outline='white', width=2*factor)
        lx, ly = (x+40*factor, y) if right else (x-10*factor, y+40*factor)
        draw.text((lx+3*factor, ly+3*factor), names[index], fill='black', font=font(16*factor))
        boxes.append([x, y, x+w, y+w]); labels.append([lx, ly, lx+140*factor, ly+28*factor])
    return frame, boxes, labels


def learned(engine: object, *, right: bool = False, names: tuple = ('Contracts', 'Documents', 'Reports')) -> tuple:
    """Human annotation selects only the first example's two visual regions."""
    frame, boxes, labels = scene(names, right=right)
    shown = dict(lesson(frame, boxes[0], labels[0], 40), name='Chosen folder')
    return teach(engine, shown), shown


def arranged_scene(position: str, order: tuple = (0,1,2)) -> tuple:
    """Independent layouts include two-line labels and negative relative offsets."""
    frame=Image.new('RGB',(900,400),'white');draw=ImageDraw.Draw(frame);boxes=[];labels=[]
    names=('Договоры\nза год','Документы\nза год','Отчёты\nза год')
    for index in range(3):
        x=145+order[index]*290;y=180
        draw.rectangle([x,y,x+29,y+29],fill='#447799')
        draw.rectangle([x+5,y+8,x+24,y+21],outline='white',width=2)
        lx,ly={'left':(x-140,y),'above':(x-10,y-70),'multiline':(x-10,y+40)}[position]
        draw.multiline_text((lx+3,ly+3),names[index],font=font(),fill='black')
        boxes.append([x,y,x+30,y+30]);labels.append([lx,ly,lx+132,ly+60])
    return frame,boxes,labels


def observation(engine: object, target: str, frame: Image.Image, boxes: list,
                *, cursor: tuple = (0, 0), version: int = 1, requests: list | None = None) -> dict:
    """Only bitmap evidence reaches the network; fixture labels are never passed."""
    planned = views(engine.model['memory'], target, fine_only=True) if requests is None else requests
    samples = collect(frame, boxes, planned, 40, dict(left=0, top=0))
    return dict(features=['visible:A'], icons=[], focus='', selected='', output='',
                cursor=dict(x=cursor[0], y=cursor[1]), version=version, session='test',
                captured_at=float(version), perception_samples=samples)
