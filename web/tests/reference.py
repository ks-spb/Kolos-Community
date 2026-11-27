"""SQLite reference for the three original Kolos v4 text rules.
Read against main.py @35aed01e: obrabotka_symbol, sozdat_svyaz, online_svyaz.
Only log statements are omitted. Reserved link 3 bootstraps MAX(id), is never
reachable and is excluded from snapshots. Reactions are tested separately,
because the browser adapter deliberately fixes that legacy code path.
"""
import json
import sqlite3
import sys
c = sqlite3.connect(':memory:')
c.execute('CREATE TABLE points(id INTEGER PRIMARY KEY, name TEXT, type TEXT, signal INTEGER)')
c.execute('CREATE TABLE svyazi(id INTEGER PRIMARY KEY, id_start INTEGER, id_finish INTEGER)')
c.executemany('INSERT INTO points VALUES (?,?,?,?)', [(1,'poz','REAC',0),(2,'neg','REAC',0),(3,'ney','REAC',1)])
c.execute('INSERT INTO svyazi VALUES (3,0,0)')
online = []
result = []
for symbol in json.load(sys.stdin)['text']:
    maximum = c.execute('SELECT MAX(signal) FROM points').fetchone()[0]
    prev = c.execute('SELECT id FROM points WHERE signal=?', (maximum,)).fetchone()[0]
    row = c.execute('SELECT id FROM points WHERE name=?', (symbol,)).fetchone()
    if row:
        point = row[0]
        c.execute('UPDATE points SET signal=? WHERE id=?', (maximum+1,point))
    else:
        point = c.execute('SELECT MAX(id) FROM points').fetchone()[0]+1
        c.execute('INSERT INTO points VALUES (?,?,?,?)', (point,symbol,'in',maximum+1))
    edge = c.execute('SELECT MAX(id) FROM svyazi').fetchone()[0]+1
    c.execute('INSERT INTO svyazi VALUES (?,?,?)', (edge,prev,point))
    available = [r[0] for r in c.execute('SELECT id FROM svyazi WHERE id_start=?', (point,))]
    i=0
    while i < len(online):
        if online[i]+1 in available:
            online[i] += 1
            available.remove(online[i])
            i += 1
        else:
            online.pop(i)
    online.extend(available)
    result.append({'nodes':[dict(zip(('id','name','type','signal'),r)) for r in c.execute('SELECT * FROM points ORDER BY id')],
                   'edges':[dict(zip(('id','from','to'),r)) for r in c.execute('SELECT * FROM svyazi WHERE id>3 ORDER BY id')],
                   'activeId':point,'online':online.copy()})
json.dump(result,sys.stdout,ensure_ascii=False)
