"""Twelve probes on ONE native graph. Only the harness knows expected outcomes.

No desktop input. Reuses the same engine between probes; only goals/working
activity and initial world observations are reset. Weights and learned vertices
remain identical. Fixture states are distinguished by visible features, not IDs
of tests. This module is never imported by the inference kernels.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from .core import StateEngine
from .protocol import persistent_graph, clone, observation_key
from .simulator import observe, apply, demonstrate, icon_actions
from .console import configure_console

FIXTURE = json.loads(Path(__file__).with_name('shared_fixture.json').read_text(encoding='utf-8'))
STOP = {'complete', 'blocked', 'failed', 'unknown', 'ambiguous', 'timeout', 'limit', 'idle'}
EXPECTED = {1:['A'], 2:['X'], 3:['X','A'], 4:['CALC'], 5:['A','X','CALC'], 6:['VIA','NEXT'],
            7:['CALC','X','CALC'], 8:['GO0','GO1','GO2'], 9:['X','CALC'],
            10:['FAST','RETURN','VIA','NEXT'], 11:['X','CALC'], 12:['X','CALC']}


def world_at(surface='desk'):
    w = clone(FIXTURE['world'])
    w.update(surface=surface, focus=w['surfaces'][surface]['field'] or '')
    return w


def state_goal(surface):
    return dict(kind='state', features=observe(world_at(surface))['features'])


def persistent(e):
    m = e.model
    data = {k:(persistent_graph(m[k]) if k=='memory' else m.get(k)) for k in ('memory','languageMemory','commands','lessons','exposures','config')}
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def stamp(e):
    return hashlib.sha256(persistent(e).encode()).hexdigest()


def build_shared(competition=1, episode_order=None):
    e = StateEngine()
    e.configure(stateCompetition=competition,plasticity=0)
    e.learn(demonstrate('Прежний ввод символов', world_at('calculator'),
                        [dict(kind='key',value=v) for v in FIXTURE['exposure']]), exposure=True)
    order = list(range(len(FIXTURE['episodes']))) if episode_order is None else episode_order
    if sorted(order) != list(range(len(FIXTURE['episodes']))):
        raise ValueError('Нужна перестановка всех демонстраций')
    for i in order:
        ep = FIXTURE['episodes'][i]
        w = world_at(ep['surface'])
        actions = icon_actions(w, ep['object'])
        if ep.get('enter'):
            actions.append(dict(kind='enter',object=ep['object']))
        actions.extend(dict(kind='key',value=v) for v in ep.get('keys',''))
        e.learn(demonstrate(ep['query'], w, actions))
        if 'weight' in ep:
            state = e.state(observe(w))
            t = next(n for n in e.model['memory']['nodes'] if n['kind']=='transition' and n['from']==state['id'] and n['label']=='CLICK '+ep['object'])
            edge = next(x for x in e.model['memory']['edges'] if x['kind']=='backward' and x['to']==t['id'])
            e.set_weight(edge['id'], ep['weight'])
    for p in FIXTURE['language']:
        e.teach_language(p['phrase'], p['goal'])
    e.reset()
    return e


class SharedSession:
    def __init__(self, competition=1, engine=None, episode_order=None):
        self.engine = engine if engine is not None else build_shared(competition, episode_order)
        self.signature = persistent(self.engine)
        self.hash = stamp(self.engine)
        self.results = []
        self.active = None
        self.world = world_at()
        self.receipt = None
        self.on_tick = None

    def begin(self, number):
        if number not in EXPECTED:
            raise ValueError('Номер теста 1–12')
        if self.engine.model['pending']:
            raise ValueError('Действие не подтверждено')
        if persistent(self.engine) != self.signature:
            raise ValueError('Долговременная память изменена')
        e = self.engine
        e.reset()
        e.events.clear()  # Audit buffer only. Never clears learned data.
        self.world = world_at('window' if number in (2,3,9,11,12) else 'old' if number==6 else 'new' if number==10 else 'L0' if number==8 else 'desk')
        self.receipt = None
        self.active = dict(number=number,stage='imagine' if number==11 else 'language' if number==12 else 'execute',
                           count=0,injected=False,dry=False,faded=False,ids=[],finished=False,initial=clone(self.world))
        obs = observe(self.world)
        if number<=4:
            e.start('закрой окно' if number==2 else 'добавь траты 2345' if number==4 else 'открой окно', obs)
        elif number==12:
            e.start_language('я хочу увидеть 1354 в поле', obs)
        else:
            goals = [state_goal('window'),dict(kind='field',focus='FIELD',value='3521')] if number==5 else [state_goal('target') if number in (6,10) else state_goal('L3') if number==8 else dict(kind='field',focus='FIELD',value='2345')]
            if number==11:
                e.imagine(goals,obs)
            else:
                e.start_goals(goals,obs)
        return self.active

    def tick_host(self):
        e = self.engine
        p = e.model['pending']
        if p:
            event = e.tick()
            if self.receipt is None:
                self.receipt = apply(self.world, p)
                event = dict(kind='effect', action=clone(p['action']), receipt=clone(self.receipt))
                e.events.append(event)
            else:
                event = e.accept_receipt(self.receipt)
                self.receipt = None
        else:
            event = e.tick()
        if self.on_tick:
            self.on_tick(e,event)
        return event

    def step(self):
        a = self.active
        if not a or a['finished']:
            raise ValueError('Нет текущего теста')
        e = self.engine
        m = e.model
        if m['status'] in STOP:
            return self.finish()
        last = e.events[-1] if e.events else {}
        if a['number']==7 and not a['injected'] and last.get('kind')=='ack' and last.get('receipt',{}).get('action')==dict(kind='click',object='CALC'):
            self.world.update(surface='window',focus='',selected='',output='')
            self.world['version']+=1
            e.observe(observe(self.world))
            a['injected']=True
            event=dict(kind='external-observation')
            e.events.append(event)
            return event
        if a['number']==10 and not a['injected'] and m['pending'] and m['pending']['action']==dict(kind='click',object='FAST') and self.receipt is None:
            next(i for i in self.world['surfaces']['new']['icons'] if i['id']=='FAST')['click']='trap'
            self.world['version']+=1
            e.observe(observe(self.world))
            a['injected']=True
            event=dict(kind='external-observation')
            e.events.append(event)
            return event
        if a['stage']=='imagine' and a['count']>=8:
            a['dry']=self.world==a['initial'] and not m['pending'] and m['imagery']['ready']>.99 and m['imagery']['match']==0
            a['ids']=clone(m['imagery']['patterns'][m['intent']['goals'][0]['id']])
            a['count']=0
            if a['number']==11:
                a['stage']='fade'
                return e.control_image('rest')
            a['stage']='execute'
            return e.control_image('act')
        if a['stage']=='fade' and a['count']>=5:
            a['faded']=m['imagery']['ready']<.04 and not self.world['effects']
            a['stage']='execute'
            return e.control_image('act')
        event=self.tick_host()
        a['count']+=1
        if a['stage']=='language' and event['kind']=='language-image':
            a.update(stage='imagine',count=0)
        if e.model['status'] in STOP:
            self.finish()
        return event

    def finish(self):
        a=self.active
        if a.get('finished'):
            return a['result']
        m=self.engine.model
        actions=[r['action'] for r in self.world['effects'] if r['ok']]
        clicks=[a['object'] for a in actions if a['kind']=='click']
        keys=''.join(a['value'] for a in actions if a['kind']=='key')
        n=a['number']
        checks=dict(completed=m['status']=='complete',memoryUnchanged=persistent(self.engine)==self.signature,
                    expectedActions=clicks==EXPECTED[n],goalReleased=not m['heldGoal'],decay=0<m['config']['decay']<1)
        if n<=3:
            checks['expectedState']=self.world['surface']==('desk' if n==2 else 'window')
        if n in (4,5,7,9,11,12):
            expected='3521' if n==5 else '1354' if n==12 else '2345'
            checks['expectedText']=keys==expected and self.world['output']==expected
        if n>=5 or n==3:
            checks['activationRoute']=any(ev['kind']=='route' for ev in self.engine.events) and any(ev.get('flows') for ev in self.engine.events)
        if n==5:
            h=m['intent']['goalHistory']
            checks['orderedGoals']=len(h)==2 and h[0]['tick']<h[1]['tick']
        if n in (7,10):
            checks['externalIntervention']=a['injected']
        if n==10:
            checks['predictionError']=len(m['intent']['errorHistory'])==1
        if n>=11:
            checks['imaginedWithoutEffects']=a['dry']
            checks['externalConfirmation']=len(m['imagery']['confirmations'])==1 and m['imagery']['confirmations'][0]['source']=='external'
            checks['sharedContent']=bool(a['ids']) and all(any(n['id']==id and n['present'] and n['S']>=.7 for n in m['imagery']['nodes']) for id in a['ids'])
        if n==11:
            checks['fadedWithoutEffects']=a['faded']
        if n==12:
            checks['novelLanguage']=m['language']['goal']['value']=='1354' and not any('1354' in l['phrase'] for l in m['languageMemory']['lessons'])
        r=dict(number=n,pass_=all(checks.values()),status=m['status'],ticks=m['tick'],clicks=clicks,keys=keys,output=self.world['output'],checks=checks,
               memoryBefore=self.hash,memoryAfter=stamp(self.engine),nodes=len(m['memory']['nodes']),edges=len(m['memory']['edges']))
        r['pass']=r.pop('pass_')
        a.update(finished=True,result=r)
        self.results.append(r)
        return r

    def run(self, number):
        self.begin(number)
        for _ in range(2500):
            if self.active['finished']:
                break
            self.step()
        if not self.active['finished']:
            raise RuntimeError('Лимит стенда')
        return self.active['result']

    def run_all(self, order=range(1,13)):
        return [self.run(n) for n in order]


def main(argv=None):
    configure_console()
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence')
    parser.add_argument('--legacy-mean',action='store_true',help='Causal control: disable competitive state inputs')
    args=parser.parse_args(argv)
    session=SharedSession(competition=0 if args.legacy_mean else 1)
    results=session.run_all()
    report=dict(schema='kolos-shared-native-evidence/1',passed=all(r['pass'] for r in results),competition=session.engine.model['config']['stateCompetition'],
                singleEngine=True,lessons=len(session.engine.model['lessons']),results=results)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    print(text)
    if args.evidence:
        out=Path(args.evidence)
        out.mkdir(parents=True,exist_ok=True)
        (out/'shared-python.json').write_text(text,encoding='utf-8')
    return 0 if report['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
