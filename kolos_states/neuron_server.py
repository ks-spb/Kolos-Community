"""Loopback-only, token-protected, GET-only telemetry viewer for Glaz.

This endpoint has NO command, motor, training or file-write action. It serves an
explicit static allowlist and a bounded ring of snapshots from the current IPC
session. Opening a browser can occlude a one-monitor desktop; use a second screen.
"""
from __future__ import annotations
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .ipc import atomic_json,read_json

STATIC_FILES = frozenset(
    ['web/neurons/'+f for f in ('index.html','style.css','snapshot.mjs','view.mjs','app.mjs')]+
    ['web/states/'+f+'.mjs' for f in ('environment','backward','dynamics','experience','targeting','imagery','goal-network','language','core',
                                   'capability-cases','imagery-cases','language-cases','route-selection')]+
    ['web/shared/'+f for f in ('index.html','style.css','app.mjs','fixture.mjs','suite.mjs')])


class NeuronServer:
    def __init__(self, root: Path, ipc: Path, session: str):
        self.root=Path(root).resolve();self.ipc=Path(ipc);self.session=session;self.token=secrets.token_urlsafe(32)
        if not (self.root/'web/neurons/index.html').is_file():
            raise FileNotFoundError('Не найден web/neurons/index.html. Обновите проект целиком.')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,code,data=b'',mime='text/plain; charset=utf-8'):
                self.send_response(code);self.send_header('Content-Type',mime)
                self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
                self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
                self.end_headers();self.wfile.write(data)
            def do_POST(self):self.reply(405,b'Read only')
            do_PUT=do_DELETE=do_PATCH=do_POST
            def do_OPTIONS(self):self.reply(405,b'Read only')
            def do_GET(self):
                expected=f'127.0.0.1:{owner.server.server_port}'
                if self.headers.get('Host')!=expected:return self.reply(403,b'Invalid host')
                request=urlsplit(self.path);path=request.path
                if path=='/api/frames':
                    if not secrets.compare_digest(self.headers.get('X-Kolos-View',''),owner.token):return self.reply(403,b'Invalid session')
                    origin=self.headers.get('Origin')
                    if origin and origin!='http://'+expected:return self.reply(403,b'Cross origin blocked')
                    try:
                        after=int(parse_qs(request.query).get('after',['0'])[0])
                        if after<0:raise ValueError()
                    except (ValueError,TypeError):return self.reply(400,b'Invalid cursor')
                    files=sorted((owner.ipc/'neuron-frames').glob('*.json'))
                    files=[p for p in files if p.stem.isdigit()]
                    earliest=int(files[0].stem) if files else 0
                    rows=[]
                    for p in files:
                        if int(p.stem)<=after:continue
                        raw=read_json(p)
                        if raw and raw.get('session')==owner.session:rows.append(raw)
                        if len(rows)>=8:break
                    data={'frames':rows,'gap':after>0 and earliest>after+1,'closed':owner.closed}
                    return self.reply(200,json.dumps(data,ensure_ascii=False,allow_nan=False).encode(),'application/json; charset=utf-8')
                rel=path.lstrip('/')
                if rel not in STATIC_FILES:return self.reply(404,b'Not found')
                p=owner.root/rel
                try:
                    if p.resolve().is_relative_to(owner.root):data=p.read_bytes()
                    else:return self.reply(404,b'Not found')
                except OSError:return self.reply(404,b'Not found')
                mime='text/javascript; charset=utf-8' if p.suffix=='.mjs' else 'text/css; charset=utf-8' if p.suffix=='.css' else 'text/html; charset=utf-8'
                self.reply(200,data,mime)
        self.closed=False
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='kolos-neuron-view')
        atomic_json(self.ipc/'neuron-watch.json',dict(session=session,enabled=True))
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}/web/neurons/index.html?live=1#{self.token}'

    def close(self):
        if self.closed:return
        self.closed=True;atomic_json(self.ipc/'neuron-watch.json',dict(session=self.session,enabled=False))
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
