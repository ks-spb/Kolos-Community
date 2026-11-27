"""Encode sampled browser frames at their real timestamps, with a separate journal panel."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import textwrap

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tests.desktop.validate_xway_readonly import EVIDENCE, OUTPUT, RUNS, lines, read, sha_file

FPS = 4
FONT = 'C:/Windows/Fonts/segoeui.ttf'


def stamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def caption(draw: ImageDraw.ImageDraw, text: str, xy: tuple, *, size: int = 18, color: str = '#e5e7eb') -> None:
    font = ImageFont.truetype(FONT, size)
    draw.text(xy, text, font=font, fill=color)


def panel(frame: Image.Image, result: dict, records: list[dict], moment: float,
          content_size: tuple[int, int]) -> Image.Image:
    """Keep the original screenshot intact; the added panel is explicitly a log."""
    content_width, content_height = content_size
    width = content_width + 505
    width += width % 2
    height = content_height + 100
    height += height % 2
    canvas = Image.new('RGB', (width, height), '#111827')
    canvas.paste(frame, (0, 100))
    draw = ImageDraw.Draw(canvas)
    caption(draw, 'КОЛОС · ЖИВОЙ XWAY · ТОЛЬКО ЧТЕНИЕ', (16, 12), size=23)
    caption(draw, f"Условие: {result['condition']} · Задание: {result['task']['sku']}", (16, 46))
    elapsed = max(0, moment - stamp(result['started_utc']))
    caption(draw, f'Реальное время: +{elapsed:.2f} с · кадры сняты с переменным интервалом', (16, 74), size=15)
    x, y = content_width + 18, 118
    caption(draw, 'ЖУРНАЛ — ДОБАВЛЕННАЯ ПАНЕЛЬ', (x, y), size=18, color='#93c5fd')
    active = [r for r in records if stamp(r['utc']) <= moment]
    visible = [r for r in active if r['event'] in ('dispatch', 'ready', 'autonomous-start',
                                                 'autonomous-end', 'stopped', 'stage-result')][-11:]
    for item in visible:
        y += 35
        if item['event'] == 'dispatch':
            a = item['action']
            text = f"Ядро: {a['kind']} · {a['descriptor']['name']}"
            if 'value' in a:
                text += ' = ' + a['value']
        elif item['event'] == 'stopped':
            text = 'ОСТАНОВКА: ' + item['error']
        else:
            text = f"{item['actor']}: {item['event']} {item.get('stage', '')}"
        for line in textwrap.wrap(text, width=43):
            caption(draw, line, (x, y), size=17)
            y += 24
    caption(draw, 'Слева — неизменённый снимок браузера.', (x, height - 100), size=16)
    caption(draw, 'Справа — команды из сохранённого журнала.', (x, height - 75), size=16)
    caption(draw, 'Реклама не редактируется.', (x, height - 50), size=17, color='#86efac')
    return canvas


def encode(name: str, directory: str, extension: str = 'mp4') -> dict:
    """Use frame timestamps, never accelerate waiting or manufacture intermediate UI."""
    base = OUTPUT / directory
    frames = sorted(lines(base / 'frames.jsonl'), key=lambda f: stamp(f['utc']))
    events, result = lines(base / 'executor.jsonl'), read(base / 'result.json')
    start, end = stamp(result['started_utc']), stamp(result['finished_utc'])
    sizes = [Image.open(base / 'frames' / f['file']).size for f in frames]
    content_size = (max(s[0] for s in sizes), max(s[1] for s in sizes))
    first = Image.open(base / 'frames' / frames[0]['file']).convert('RGB')
    preview = panel(first, result, events, start, content_size)
    target = EVIDENCE / (name + '.' + extension)
    codec = 'VP80' if extension == 'webm' else 'mp4v'
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*codec), FPS, preview.size)
    if not writer.isOpened():
        raise RuntimeError('MP4 encoder unavailable')
    index, count, image = -1, 0, first
    try:
        while start + count / FPS <= end + .5:
            moment = min(start + count / FPS, end)
            while index + 1 < len(frames) and stamp(frames[index + 1]['utc']) <= moment:
                index += 1
                image = Image.open(base / 'frames' / frames[index]['file']).convert('RGB')
            rendered = panel(image, result, events, moment, content_size)
            writer.write(cv2.cvtColor(np.asarray(rendered), cv2.COLOR_RGB2BGR))
            count += 1
    finally:
        writer.release()
    capture = cv2.VideoCapture(str(target))
    try:
        assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == count
        ok, _frame = capture.read()
        assert ok, 'Encoded video cannot be decoded'
    finally:
        capture.release()
    last = panel(image, result, events, end, content_size)
    last.save(EVIDENCE / (name + '-preview.jpg'))
    return dict(file=target.name, sha256=sha_file(target), encoded_frames=count, fps=FPS,
                source_frames=len(frames), duration_seconds=round(count / FPS, 2),
                source_directory=directory, presentation='Original screenshots plus separate journal panel')


if __name__ == '__main__':
    EVIDENCE.mkdir(exist_ok=True)
    extension = 'webm' if '--webm' in sys.argv else 'mp4'
    manifest = {name: encode(name, directory, extension) for name, directory in RUNS.items()}
    manifest_name = 'videos-webm.json' if extension == 'webm' else 'videos.json'
    (EVIDENCE / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
