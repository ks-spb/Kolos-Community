"""Eleventh capability: pure evidence harness, never used by live inference."""
import json
from .core import STOP
from .protocol import persistent_graph, clone
from .capabilities import prepare
from .simulator import observe, apply


def run():
    e,w,req=prepare(9);memory=persistent_graph(e.model['memory']);before=clone(w)
    e.imagine(req['goals'],observe(w))
    for _ in range(12):e.tick()
    i=e.model['imagery'];ids=list(i['patterns'][e.model['intent']['goals'][0]['id']])
    dry=w==before and not e.model['pending'] and e.model['heldGoal'] and i['ready']>.99 and i['match']==0
    e.control_image('rest')
    for _ in range(5):e.tick()
    faded=i['ready']<.04 and not w['effects']
    e.control_image('act');physical={}
    for _ in range(400):
        if e.model['status'] in STOP:break
        ev=e.tick()
        if ev['kind']=='waiting':
            p=e.model['pending']
            if p['id'] not in physical:physical[p['id']]=apply(w,p)
            else:e.accept_receipt(physical[p['id']])
    shared=all(any(n['id']==id and n['present'] and n['S']>=.7 for n in i['nodes']) for id in ids)
    confirmed=e.model['status']=='complete' and w['output']=='2345' and len(i['confirmations'])==1
    frozen=persistent_graph(e.model['memory'])==memory
    report=dict(number=11,passed=dry and faded and shared and confirmed and frozen,dry=dry,faded=faded,sameVertices=shared,confirmed=confirmed,memoryUnchanged=frozen,output=w['output'],ticks=e.model['tick'],scope='native kernel with observed simulator, not live OS')
    return report,e,w


def main():
    from .console import configure_console
    configure_console()
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path);args=parser.parse_args()
    r,e,w=run();print(json.dumps(r,ensure_ascii=False,indent=2))
    if args.evidence:
        args.evidence.mkdir(parents=True,exist_ok=True)
        (args.evidence/'imagery-python.json').write_text(json.dumps(dict(result=r,events=e.events,imagery=e.model['imagery']),ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if r['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
