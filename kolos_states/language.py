"""Experiment 12. Learned sequence assemblies ground language in image content.

Same equations/topology as web/states/language.mjs. No fixed vocabulary, digit
parser, LLM, world model or OS input. A unique paired span is a stated general
inductive bias; productive fields require two distinct supervision examples.
"""
import math
from .protocol import sensory_features, clone, compact, clamp, require

DEFAULTS = dict(decay=.5, threshold=.7, margin=.04, maxWaves=12, maxFrontier=128)


def memory(m):
    return m.setdefault('languageMemory', dict(schema='kolos-language/1', serial=0, nodes=[], edges=[], lessons=[]))


def node(mem, **spec):
    require(len(mem['nodes']) < 12000, 'Лимит языковых вершин')
    n = dict(id='lang:n'+str(mem['serial']), **spec); mem['serial'] += 1; mem['nodes'].append(n); return n


def edge(mem, source, target, kind, weight=.9, **extra):
    e = dict(id='lang:e'+str(mem['serial']), to=target, kind=kind, weight=weight, **extra)
    e['from'] = source; mem['serial'] += 1; mem['edges'].append(e); return e


def glyph(mem, char):
    return next((n for n in mem['nodes'] if n['kind'] == 'glyph' and n['char'] == char), None) or node(mem, kind='glyph', char=char, label='␣' if char == ' ' else char)


def goal_check(m, raw):
    require(isinstance(raw, dict) and raw.get('kind') in ('field','state'), 'Языковой паре нужен образ поля или состояния')
    if raw['kind'] == 'state':
        require(isinstance(raw.get('features'), list) and all(isinstance(x,str) for x in raw['features']), 'Нужны признаки состояния')
        features = sensory_features(raw['features'])
        require(any(n['kind'] == 'state' and sorted(n['features']) == features for n in m['memory']['nodes']), 'Состояние ещё не наблюдалось')
        return dict(kind='state', features=features)
    require(isinstance(raw.get('focus'),str) and raw['focus'] and isinstance(raw.get('value'),str) and 0 < len(raw['value']) <= 160, 'Поле и непустой текст до 160 символов')
    require(any(n['kind'] == 'state' and 'focus:'+raw['focus'] in n['features'] for n in m['memory']['nodes']), 'Поле ещё не наблюдалось')
    require(all(any(n['kind'] == 'symbol' and n['value'] == ch for n in m['memory']['nodes']) and any(n['kind'] == 'motor' and n['value'] == ch for n in m['memory']['nodes']) for ch in raw['value']), 'Сначала покажите эти символы в среде')
    return dict(kind='field', focus=raw['focus'], value=raw['value'])


def teach(m, phrase, raw_goal):
    require(not m['pending'] and m['status'] not in ('running','waiting'), 'Остановите текущую попытку перед обучением')
    require(isinstance(phrase,str) and 0 < len(phrase) <= 240, 'Фраза: 1–240 символов')
    goal = goal_check(m,raw_goal); chars = list(phrase); prefix = chars; suffix = []
    if goal['kind'] == 'field':
        value = list(goal['value']); starts = [i for i in range(len(chars)-len(value)+1) if chars[i:i+len(value)] == value]
        require(len(starts) == 1, 'Содержимое образа должно ровно один раз совпасть с непрерывным участком фразы')
        prefix = chars[:starts[0]]; suffix = chars[starts[0]+len(value):]
        require(prefix or suffix, 'Нужен языковой контекст, не только содержимое')
    mem = memory(m); require(len(mem['lessons']) < 100, 'Лимит 100 языковых пар')
    meaning = dict(kind='field',focus=goal['focus']) if goal['kind'] == 'field' else dict(kind='state',features=goal['features'])
    shape = compact([prefix,suffix,meaning]); assembly = next((n for n in mem['nodes'] if n['kind']=='assembly' and n['shape']==shape),None)
    semantic = next((n for n in mem['nodes'] if n['kind']=='meaning' and n['goal']==meaning),None) or node(mem,kind='meaning',goal=meaning,label='Поле '+meaning['focus'] if meaning['kind']=='field' else 'Известное состояние')
    if not assembly:
        assembly = node(mem,kind='assembly',shape=shape,label=''.join(prefix)+('□' if goal['kind']=='field' else '')+''.join(suffix),data=goal['kind']=='field')
        prev = assembly['id']
        for char in prefix:
            g = glyph(mem,char); n = node(mem,kind='context',label=char); edge(mem,prev,n['id'],'literal',.9,glyph=g['id']); prev=n['id']
        if goal['kind']=='field':edge(mem,prev,prev,'bind',.9)
        for char in suffix:
            g=glyph(mem,char);n=node(mem,kind='context',label=char);edge(mem,prev,n['id'],'literal',.9,glyph=g['id']);prev=n['id']
        edge(mem,prev,semantic['id'],'readout',.9,assembly=assembly['id'])
    witness_key=compact([assembly['id'],goal['value'] if goal['kind']=='field' else None])
    if not any(n['kind']=='witness' and n['key']==witness_key for n in mem['nodes']):
        w=node(mem,kind='witness',key=witness_key,label='Показ №'+str(len(mem['lessons'])+1))
        edge(mem,w['id'],assembly['id'],'support',.4 if goal['kind']=='field' else .9)
    if goal['kind']=='field':
        for char in goal['value']:
            g=glyph(mem,char);symbol=next(n for n in m['memory']['nodes'] if n['kind']=='symbol' and n['value']==char)
            if not any(e['kind']=='ground' and e['from']==g['id'] and e['to']==symbol['id'] for e in mem['edges']):edge(mem,g['id'],symbol['id'],'ground',1)
    mem['lessons'].append(dict(phrase=phrase,goal=clone(goal),assembly=assembly['id']))
    m.update(language=None,status='trained',message='Фраза связана с образом. Действия и маршрут не добавлены.')
    return dict(kind='language-teach',assembly=assembly['id'],goal=clone(goal))


def weight(m,id,value):
    require(not m['pending'] and m['phase']!='language', 'Сначала остановите распознавание')
    require(isinstance(value,(float,int)) and math.isfinite(value) and 0<=value<=1,'Вес 0…1')
    e=next((e for e in memory(m)['edges'] if e['id']==id),None);require(e,'Нет такой языковой связи');e['weight']=value


def start(m,phrase,options=None):
    require(not m['pending'], 'Сначала разрешите неподтверждённое действие')
    require(isinstance(phrase,str) and 0<len(phrase)<=240, 'Фраза: 1–240 символов')
    cfg={**DEFAULTS,**(options or {})}
    for k,v in cfg.items():
        require(k in DEFAULTS and isinstance(v,(float,int)) and math.isfinite(v),'Неизвестная настройка языка')
        if k.startswith('max'):require(int(v)==v and 1<=v<=512,'Некорректный предел')
        else:require(0<=v<=1,'Коэффициент 0…1')
    require(cfg['decay']<1 and cfg['threshold']>0,'Нужны затухание < 1 и положительный порог')
    mem=memory(m)
    m['language']=dict(schema='kolos-language-runtime/1',phrase=phrase,chars=list(phrase),index=0,config=cfg,wave=0,charges={},
        frontier=[dict(node=n['id'],assembly=n['id'],bound=[],path=[],strength=1) for n in mem['nodes'] if n['kind']=='assembly'],
        trace={},fired=[],candidates=[],status='reading',goal=None,readout=None)
    m.update(intent=None,imagery=None,plan=None,detour=None,entry=None,occ=[],activation={},goalActivation={},heldGoal=False,
             phase='language',status='running',tick=0,query=phrase,message='Фраза возбуждает выученные связи. До полного распознавания образ и действия не создаются.')
    return dict(kind='language-start',phrase=phrase)


def refuse(m,kind,message):
    m['language']['status']=kind;m['status']='ambiguous' if kind=='ambiguous' else 'unknown';m['message']=message
    return dict(kind='language-'+kind,message=message)


def tick(m):
    r=m['language'];mem=memory(m);cfg=r['config'];m['tick']+=1;r['wave']+=1
    for id in r['trace']:r['trace'][id]=clamp(r['trace'][id]*cfg['decay'])
    end=r['index']>=len(r['chars']);char=None if end else r['chars'][r['index']];candidates=[]
    for f in r['frontier']:
        for e in (e for e in mem['edges'] if e['from']==f['node']):
            assembly=next(n for n in mem['nodes'] if n['id']==f['assembly']);sensory=1;bound=f['bound']
            if end:
                if e['kind']!='readout' or e['assembly']!=f['assembly'] or assembly['data'] and not bound:continue
            elif e['kind']=='literal':
                g=next(n for n in mem['nodes'] if n['id']==e['glyph'])
                if g['char']!=char:continue
            elif e['kind']=='bind':
                g=next((n for n in mem['nodes'] if n['kind']=='glyph' and n['char']==char),None)
                ground=next((s for s in mem['edges'] if s['kind']=='ground' and g and s['from']==g['id']),None)
                referent=next((n for n in m['memory']['nodes'] if ground and n['id']==ground['to'] and n['kind']=='symbol'),None)
                if not referent or len(bound)>=160:continue
                sensory=ground['weight'];bound=bound+[dict(char=referent['value'],source=r['index'],edge=ground['id'])]
            else:continue
            key=compact([e['id'],f['assembly'],[b['source'] for b in bound]])
            support=1
            if end:
                support=min(1,sum(s['weight'] for s in mem['edges'] if s['kind']=='support' and s['to']==f['assembly']))
                drive=support*e['weight']*f['strength']
            else:drive=(e['weight']+sensory)*.5
            a=clamp(cfg['decay']*r['charges'].get(key,0)+(1-cfg['decay'])*drive);r['charges'][key]=a
            candidates.append(dict(id=key,label=next(n['label'] for n in mem['nodes'] if n['id']==e['to']) if end else ('␣' if char==' ' else char),
                edge=e['id'],assembly=f['assembly'],to=e['to'],a=a,input=0 if end else sensory*.5,history=drive if end else e['weight']*.5,
                inhibition=0,threshold=cfg['threshold'],allowed=True,role=e['kind'],bound=bound,path=f['path']+[e['id']],
                strength=min(f['strength'],e['weight']/.9,sensory),support=support))
    r['candidates']=candidates
    ev=dict(kind='language-charge',symbol=char,index=r['index'],wave=r['wave'],candidates=clone(candidates),flows=[dict(edge=c['edge'],to=c['to'],value=c['a']) for c in candidates],winner=None)
    if not candidates:return refuse(m,'unknown','Фраза не поддержана языковым опытом целиком. Ничего не выполнено.')
    def not_settled(c):
        w=next(e['weight'] for e in mem['edges'] if e['id']==c['edge'])
        d=c['support']*w*c['strength'] if end else (w+(c['input']*2 if c['role']=='bind' else 1))*.5
        return abs(d-c['a'])>.02
    if r['wave']<cfg['maxWaves'] and any(not_settled(c) for c in candidates):return ev
    viable=[c for c in candidates if c['a']>=cfg['threshold']]
    if not viable:return refuse(m,'below','Недостаточный сигнал: нужны разные подтверждённые языковые пары или более сильные связи.')
    if not end:
        unique={}
        for c in viable:
            key=compact([c['to'],c['assembly'],c['bound']])
            if key not in unique:unique[key]=dict(node=c['to'],assembly=c['assembly'],bound=c['bound'],path=c['path'],strength=c['strength'])
            r['trace'][c['to']]=1
        if len(unique)>cfg['maxFrontier']:return refuse(m,'limit','Слишком много одновременно допустимых языковых продолжений.')
        r['frontier']=list(unique.values());r['fired'].append(dict(index=r['index'],symbol=char,edges=[c['edge'] for c in viable]));r['index']+=1;r['wave']=0;r['charges']={}
        m['message']=f"Распознано {r['index']}/{len(r['chars'])}: «{'␣' if char==' ' else char}». Гипотез: {len(r['frontier'])}."
        ev.update(kind='language-symbol',winner=viable[0]['id'] if len(viable)==1 else None);return ev
    meanings={}
    for c in candidates:
        semantic=next(n for n in mem['nodes'] if n['id']==c['to'])
        goal={**semantic['goal'],'value':''.join(x['char'] for x in c['bound'])} if semantic['goal']['kind']=='field' else clone(semantic['goal'])
        key=compact(goal);old=meanings.get(key)
        if not old or c['a']>old['a']:meanings[key]={**c,'goal':goal}
    ranked=sorted(meanings.values(),key=lambda c:-c['a']);best=ranked[0]
    if len(ranked)>1 and best['a']-ranked[1]['a']<cfg['margin']:return refuse(m,'ambiguous','Несколько образов имеют близкий сигнал. Выберите правильную пару для обучения; действия не запущены.')
    r['goal']=clone(best['goal']);r['readout']=dict(semantic=best['to'],edge=best['edge'],activation=best['a'],assembly=best['assembly'],binding=clone(best['bound']),path=clone(best['path']));r['status']='decoded'
    m['message']='Языковые связи активировали образ. Это внутренний источник I, не наблюдение S.'
    ev.update(kind='language-image',winner=best['id'],goal=clone(best['goal']),readout=clone(r['readout']));return ev
