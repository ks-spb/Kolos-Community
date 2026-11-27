"""Pure test double; never imported by the live desktop adapter."""
from .protocol import persistent_graph, clone, guard
from .core import StateEngine


def default_world():
    return dict(surface='desk', selected='', focus='', output='', cursor=dict(x=500,y=300), version=0,effects=[],surfaces={
        'desk':dict(field=None,icons=[dict(id='A',x=200,y=190,enter='window'),dict(id='B',x=500,y=190),dict(id='CALC',x=780,y=190,click='calculator')]),
        'window':dict(field=None,icons=[dict(id='X',x=920,y=75,click='desk'),dict(id='D',x=260,y=260),dict(id='E',x=630,y=260)]),
        'calculator':dict(field='FIELD',icons=[dict(id='X',x=920,y=75,click='desk'),dict(id='DIGITS',x=250,y=240),dict(id='RESULT',x=660,y=240)])})


def observe(w):
    icons=[{k:o[k] for k in ('id','x','y')} for o in w['surfaces'][w['surface']]['icons'] if not o.get('hidden')]
    return dict(icons=icons,features=sorted(['visible:'+o['id'] for o in icons]+['selected:'+w['selected'],'focus:'+w['focus']]),selected=w['selected'],focus=w['focus'],output=w['output'],cursor=clone(w['cursor']),version=w['version'])


def apply(w, req):
    old=next((r for r in w['effects'] if r['id']==req['id']),None)
    if old:return clone(old)
    a=req['action'];before=observe(w);reason=guard(before,a)
    if not reason:
        if a['kind']=='move':w['cursor']=dict(x=a['x'],y=a['y'])
        elif a['kind'] in ('click','enter'):
            icon=next(o for o in w['surfaces'][w['surface']]['icons'] if o['id']==a['object'])
            target=icon.get(a['kind'])
            if target:w.update(surface=target,selected='',focus=w['surfaces'][target]['field'] or '',output='')
            elif a['kind']=='click':w['selected']=icon['id']
        elif a['kind']=='key':w['output']+=a['value']
        w['version']+=1
    receipt=dict(id=req['id'],action=clone(a),ok=not reason,reason=reason,before=before,after=observe(w))
    w['effects'].append(clone(receipt));return receipt


def icon_actions(w, id):
    o=next(o for o in w['surfaces'][w['surface']]['icons'] if o['id']==id)
    return [dict(kind='move',x=o['x'],y=o['y']),dict(kind='check',object=id),dict(kind='click',object=id)]


def demonstrate(query,world,actions):
    w=clone(world);w['effects']=[];receipts=[]
    for a in actions:
        r=apply(w,dict(id='demo:'+str(len(receipts)),action=a))
        if not r['ok']:raise ValueError(r['reason'])
        receipts.append(r)
    return dict(query=query,initial=clone(world),receipts=receipts)


def prepare_case(number):
    e=StateEngine();e.configure(plasticity=0);w=default_world()
    if number==4:
        prior=default_world();prior.update(surface='calculator',focus='FIELD')
        e.learn(demonstrate('Прежний ввод символов',prior,[dict(kind='key',value=v) for v in '5432']),exposure=True)
        e.learn(demonstrate('добавь траты 1700',w,icon_actions(w,'CALC')+[dict(kind='key',value=v) for v in '1700']))
        query='добавь траты 2345'
    else:
        e.learn(demonstrate('открой окно',w,icon_actions(w,'A')+[dict(kind='enter',object='A')]))
        w['surface']='window';e.learn(demonstrate('закрой окно',w,icon_actions(w,'X')))
        query='закрой окно' if number==2 else 'открой окно'
        if number==1:w['surface']='desk'
    return e,w,query


def run_case(number):
    e,w,query=prepare_case(number);frozen=persistent_graph(e.model['memory']);e.start(query,observe(w))
    for _ in range(1200):
        if e.model['status'] in ('complete','blocked','failed','unknown','ambiguous','timeout','limit'):break
        e.tick()
        if e.model['pending']:
            r=apply(w,e.model['pending'])
            # Separate logical effect and receipt ticks; no inference in adapter.
            e.tick();e.tick();e.accept_receipt(r)
    keys=''.join(r['action']['value'] for r in w['effects'] if r['ok'] and r['action']['kind']=='key')
    passed=e.model['status']=='complete' and persistent_graph(e.model['memory'])==frozen
    passed=passed and (keys=='2345' if number==4 else w['surface']==('desk' if number==2 else 'window'))
    if number==3:passed=passed and any(x['kind']=='route' for x in e.events)
    return dict(number=number,passed=passed,status=e.model['status'],output=keys,ticks=e.model['tick']),e,w
