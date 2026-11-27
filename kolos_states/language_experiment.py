"""Isolated model evidence for test 12. No OS actions or screen capture."""
import argparse
import json
from pathlib import Path
from .capabilities import prepare
from .protocol import persistent_graph, clone
from .simulator import observe, apply
from .core import STOP

PAIRS=[('я хочу увидеть 1700 в поле','1700'),('я хочу увидеть 2345 в поле','2345'),
       ('пусть в поле будет 1700','1700'),('пусть в поле будет 2345','2345'),
       ('сделай в поле 1700 пожалуйста','1700'),('сделай в поле 2345 пожалуйста','2345')]


def prepare_language(phrase='я хочу увидеть 1354 в поле'):
    e,w,_=prepare(9)
    for text,value in PAIRS:e.teach_language(text,dict(kind='field',focus='FIELD',value=value))
    return e,w,phrase


def run_language():
    e,w,phrase=prepare_language();world=clone(w);mem=persistent_graph(e.model['memory']);lex=clone(e.model['languageMemory'])
    e.start_language(phrase,observe(w))
    for _ in range(1200):
        if e.model['phase']!='language' or e.model['status']!='running':break
        e.tick()
    decoded=e.model['language']['goal']==dict(kind='field',focus='FIELD',value='1354')
    for _ in range(8):
        if e.model['status']=='running':e.tick()
    dry=w==world and bool(e.model.get('imagery')) and e.model['imagery']['ready']>=.7 and e.model['imagery']['match']==0
    if e.model.get('imagery'):e.control_image('act')
    for _ in range(600):
        if e.model['status'] in STOP:break
        e.observe(observe(w));e.tick()
        if e.model['pending']:
            r=apply(w,e.model['pending']);e.tick();e.tick();e.accept_receipt(r)
    observed=e.model['status']=='complete' and w['output']=='1354' and len(e.model['imagery']['confirmations'])==1
    unchanged=mem==persistent_graph(e.model['memory']) and lex==e.model['languageMemory']
    return dict(number=12,passed=bool(decoded and dry and observed and unchanged),decoded=decoded,dry=dry,observed=observed,unchanged=unchanged,
                phrase=phrase,goal=e.model['language']['goal'],output=w['output']),e,w


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--evidence');args=p.parse_args(argv)
    r,e,w=run_language()
    if args.evidence:
        out=Path(args.evidence);out.mkdir(parents=True,exist_ok=True)
        (out/'language-report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'language-trace.json').write_text(json.dumps(e.events,ensure_ascii=False),encoding='utf-8')
    from .console import configure_console
    configure_console()
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
