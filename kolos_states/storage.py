"""Separate native memory; never reads/writes db_v4.db or legacy Glaz objects."""
from __future__ import annotations
import os
import json
import shutil
import time
from pathlib import Path
from .ipc import atomic_json, read_json, MAX_BYTES
from .protocol import SCHEMA, clone, persistent_graph, require
from .memory import validate_graph
from .core import StateEngine


class Store:
    def __init__(self,path: Path):
        self.path=path;self.path.mkdir(parents=True,exist_ok=True)
        lock_path=path/'process.lock';lock_path.touch(exist_ok=True)
        self.lock=lock_path.open('r+b')
        if lock_path.stat().st_size==0:self.lock.write(b'0');self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.lock.close();raise RuntimeError('Другой States-процесс уже использует эту память')

    def load(self):
        raw=read_json(self.path/'memory.json');e=StateEngine()
        if raw is None:
            if (self.path/'memory.json').exists():raise ValueError('Повреждена memory.json; исходный файл не перезаписан')
            return e
        if raw.get('schema')=='kolos-desktop-states/1':
            backup=self.path/('memory-v1-'+str(time.time_ns())+'.json')
            shutil.copy2(self.path/'memory.json',backup)
            e.model['message']='Память v1 сохранена в '+backup.name+'. Заново покажите O1/O2 с наблюдением результата.'
            self.save(e)
            return e
        e = self._restore(raw, e)
        if raw.get('schema') in ('kolos-desktop-states/2', 'kolos-desktop-states/3'):
            shutil.copy2(self.path/'memory.json', self.path/('memory-v'+raw['schema'].rsplit('/', 1)[1]+'-'+str(time.time_ns())+'.json'))
            atomic_json(self.path/'memory.json', dict(raw, schema=SCHEMA))
        return e

    @staticmethod
    def restore_snapshot(raw: dict) -> StateEngine:
        """Restore current-format frozen memory without writing or leasing its directory."""
        require(isinstance(raw, dict) and raw.get('schema') == SCHEMA, 'Invalid frozen memory snapshot')
        return Store._restore(raw, StateEngine())

    @staticmethod
    def _restore(raw: dict, e: StateEngine) -> StateEngine:
        if raw.get('schema') not in (SCHEMA, 'kolos-desktop-states/2', 'kolos-desktop-states/3'):raise ValueError('Несовместимый формат памяти; исходный файл не перезаписан')
        memory=validate_graph(raw.get('memory'),raw.get('commands'),raw.get('episodeCommands',[]))
        for key in ('commands','lessons','exposures','learningLog','audit','episodeCommands'):
            require(isinstance(raw.get(key,[]),list),'Неверный журнал памяти')
            e.model[key]=clone(raw.get(key,[]))
        e.model['memory']=memory
        from .perception.persistence import validate_lessons
        e.model['visualLessons'] = clone(validate_lessons(raw.get('visualLessons', []), memory))
        for pair in raw.get('languageLessons',[]):e.teach_language(pair['phrase'],pair['goal'])
        for id,value in raw.get('languageWeights',{}).items():e.set_language_weight(id,value)
        e.configure(**raw.get('config',{}));e.reset()
        return e

    def save(self,engine, *, preserve_attempt: bool = False):
        m=engine.model
        from .perception.persistence import without_samples
        payload = dict(schema=SCHEMA,memory=persistent_graph(m['memory']),commands=m['commands'],
            lessons=m['lessons'],exposures=m['exposures'],audit=m['audit'],episodeCommands=m.get('episodeCommands',[]),
            config=m['config'],learningLog=m.get('learningLog'),visualLessons=m.get('visualLessons', []),
            languageLessons=(m.get('languageMemory') or {}).get('lessons',[]),
            languageWeights={e['id']:e['weight'] for e in (m.get('languageMemory') or {}).get('edges',[])})
        payload = without_samples(payload)
        require(len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')) <= MAX_BYTES,
                'Память превышает лимит 4 МБ; прежний файл сохранён')
        atomic_json(self.path/'memory.json', payload)
        # Outstanding side effects are an audit, not something to auto-replay.
        if not preserve_attempt:
            atomic_json(self.path/'last-attempt.json',dict(schema=SCHEMA,pending=clone(m['pending']),status=m['status'],query=m['query'],tick=m['tick']))

    def close(self):
        self.lock.close()
