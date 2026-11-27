"""Optional read-only diagnostic frames. No import of desktop input APIs.

Enabled only while the user-opened Glaz viewer holds a session marker. A bounded
ring stores 80 snapshots. Failures in this observer never change engine state.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from .ipc import atomic_json, read_json

MODEL_KEYS = ('tick','revision','attempt','query','phase','status','message','heldGoal',
              'config','memory','activation','goalActivation','refractory','trace',
              'occ','observed','pending','imagery','language','languageMemory','plan','episode','perception','objectCurrents','objectQuestion','objectBinding')
INTENT_KEYS = ('config','goals','active','episode','error','wave')


class NeuronTraceWriter:
    def __init__(self, directory: Path, session: str, capacity=80):
        self.directory=Path(directory);self.session=session;self.capacity=capacity
        self.last_revision=None;self.error=''
        existing=[int(p.stem) for p in (self.directory/'neuron-frames').glob('*.json') if p.stem.isdigit()]
        self.sequence=max(existing,default=0)

    def capture(self, engine, *, event=None):
        markers=[read_json(self.directory/name) for name in ('neuron-watch.json','neuron-inline-watch.json')]
        if not any(marker and marker.get('session')==self.session and marker.get('enabled') for marker in markers):
            return False
        m=engine.model
        revision=m.get('revision')
        if revision==self.last_revision:return False
        try:
            # Serialization detaches the frame without retaining live references.
            data={k:m[k] for k in MODEL_KEYS if k in m}
            if m.get('intent'):data['intent']={k:m['intent'][k] for k in INTENT_KEYS if k in m['intent']}
            if data.get('pending'):
                data['pending']={k:v for k,v in data['pending'].items() if k not in ('receipt',)}
            if data.get('languageMemory'):
                data['languageMemory']={k:v for k,v in data['languageMemory'].items() if k!='lessons'}
            ev=event if event is not None else engine.events[-1] if engine.events else {}
            row={'seq':self.sequence+1,'session':self.session,'captured_at':time.time(),'model':data,'event':ev}
            from .perception.persistence import without_samples
            row = without_samples(row)
            # Bound diagnostic cost. Do not truncate into a falsely complete graph.
            encoded=json.dumps(row,ensure_ascii=False,allow_nan=False)
            if len(encoded.encode('utf-8'))>2_000_000:
                self.error='Граф больше лимита 2 МБ на снимок; снимок пропущен.';return False
            row=json.loads(encoded);folder=self.directory/'neuron-frames';folder.mkdir(exist_ok=True)
            self.sequence+=1;atomic_json(folder/f'{self.sequence:09d}.json',row)
            old=folder/f'{self.sequence-self.capacity:09d}.json';old.unlink(missing_ok=True)
            self.last_revision=revision;return True
        except (OSError,ValueError,TypeError) as exc:
            self.error=str(exc);return False
