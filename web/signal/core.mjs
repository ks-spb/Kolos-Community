/** Kolos signal laboratory. Pure graph engine: no DOM, clocks, ID+1 or queued action path. */
export const SIGNAL_VERSION = 'kolos-signal/1';
export const DEFAULTS = Object.freeze({threshold:.70, weight:.85, pulse:1, decay:.60, traceDecay:.90,
  refractory:2, inhibition:.25, margin:.05, contextGain:.10, observationGain:.10,
  eligibilityDecay:.99, rewardRate:.05, penaltyRate:.10});
const copy = x => structuredClone(x);
const bound = x => Math.max(0, Math.min(1, Math.round(x * 1e9) / 1e9));
const END = '<END_REQUEST>';
const MAX_OPS = 2000;
const equal = (a,b) => JSON.stringify(a) === JSON.stringify(b);
const insist = (condition, message) => { if (!condition) throw new Error(message); };
export function defaultScene() {
  return {version:0, objects:[{name:'DOC',x:180,y:150,visible:true},{name:'CALC',x:500,y:150,visible:true},
    {name:'SET',x:820,y:150,visible:true},{name:'MAIL',x:340,y:420,visible:true}],
    cursor:{x:500,y:300}, app:'', output:'', checked:'', executions:[]};
}
export function underCursor(scene) {
  const hits = scene.objects.filter(o => o.visible && Math.abs(o.x-scene.cursor.x)<=75 && Math.abs(o.y-scene.cursor.y)<=44);
  return hits.length === 1 ? hits[0].name : hits.length ? '<неоднозначно>' : '';
}
function object(scene,name) { return scene.objects.find(o => o.name===name && o.visible); }
function cleanAction(raw) {
  insist(raw && typeof raw==='object','Некорректное действие');
  if(raw.kind==='move') {
    insist(Number.isFinite(raw.x)&&Number.isFinite(raw.y)&&raw.x>=0&&raw.x<=1000&&raw.y>=0&&raw.y<=600,'Координаты вне экрана');
    return {kind:'move',x:Math.round(raw.x),y:Math.round(raw.y)};
  }
  if(raw.kind==='check'||raw.kind==='click') {
    insist(typeof raw.object==='string'&&raw.object.trim()&&raw.object.length<=40,'Некорректное имя объекта');
    return {kind:raw.kind,object:raw.object.trim()};
  }
  if(raw.kind==='key'||raw.kind==='emit') {
    insist(typeof raw.value==='string'&&Array.from(raw.value).length===1,'Нужна одна клавиша / буква');
    return {kind:raw.kind,value:raw.value};
  }
  throw new Error('Неизвестное действие');
}
export function actionLabel(a) {
  if(!a) return '';
  return a.kind==='move'?`POS ${a.x}×${a.y}`:a.kind==='seek'?`Найти ${a.object}`:
    a.kind==='check'?`CHECK ${a.object}`:a.kind==='click'?`CLICK ${a.object}`:
    a.kind==='key'?`KEY ${a.value===' '?'␣':a.value}`:a.kind==='emit'?`Ответ ${a.value}`:'Конец';
}
function validateScene(raw) {
  insist(raw && Array.isArray(raw.objects)&&raw.objects.length<=24,'На экране не более 24 объектов');
  const names = new Set();
  const objects = raw.objects.map(o => {
    insist(o&&typeof o.name==='string'&&o.name.trim()&&o.name.length<=40&&!names.has(o.name),'Имена объектов должны быть уникальными');
    insist(Number.isFinite(o.x)&&Number.isFinite(o.y)&&o.x>=75&&o.x<=925&&o.y>=60&&o.y<=540&&typeof o.visible==='boolean','Некорректные координаты объекта');
    names.add(o.name);return {name:o.name,x:o.x,y:o.y,visible:o.visible};
  });
  const c=raw.cursor;
  insist(c&&Number.isFinite(c.x)&&Number.isFinite(c.y)&&c.x>=0&&c.x<=1000&&c.y>=0&&c.y<=600,'Некорректный курсор');
  insist(typeof raw.app==='string'&&raw.app.length<=40&&typeof raw.output==='string'&&raw.output.length<=500,'Некорректное состояние приложения');
  return {objects,cursor:{x:c.x,y:c.y},app:raw.app,output:raw.output};
}
function freshModel() {
  return {nodes:[{id:1,kind:'root',label:'Начало',phase:'input',a:0,trace:0,r:0}],edges:[],nextNode:2,nextEdge:1,
    config:{...DEFAULTS},scene:defaultScene(),revision:0,tick:0,active:1,lastFired:null,pulses:[],
    phase:'idle',query:'',inputIndex:0,status:'idle',message:'Обучите цепочку или запустите пример.',
    runMode:'none',prefixLength:0,continuationRaw:'',continuation:'',generatedCount:0,recallVisited:[],
    answer:'',lastObserved:-1,attemptTicks:0,attempt:0,executedSteps:0,used:[],lastActionEdge:null,lastRewardRevision:-1};
}
function resetDynamics(m) {
  for(const n of m.nodes){n.a=0;n.trace=0;n.r=0;}
  for(const e of m.edges)e.eligibility=0;
  m.active=m.nodes.find(n=>n.kind==='root').id;m.lastFired=null;m.pulses=[];m.used=[];
  m.lastActionEdge=null;m.inputIndex=0;m.answer='';m.attemptTicks=0;m.executedSteps=0;m.lastObserved=-1;
  m.prefixLength=0;m.continuationRaw='';m.continuation='';m.generatedCount=0;m.recallVisited=[];m.runMode='none';
}
function node(m,spec) {
  const found=m.nodes.find(n=>n.kind===spec.kind && n.parent===spec.parent && n.token===spec.token && n.phase===spec.phase && n.role===spec.role);
  if(found)return found;
  insist(m.nodes.length<1000,'Лимит: 1000 вершин. Экспортируйте эксперимент.');
  const n={id:m.nextNode++,...spec,a:0,trace:0,r:0};m.nodes.push(n);return n;
}
function link(m,from,to,kind='excite',weight=m.config.weight) {
  const found=m.edges.find(e=>e.from===from&&e.to===to&&e.kind===kind);
  if(found)return found;
  const e={id:m.nextEdge++,from,to,kind,weight,eligibility:0};m.edges.push(e);return e;
}
function concept(m,token,label,kind='concept') {return node(m,{kind,token,label,phase:'source'});}
function conditions(a) {
  if(a?.kind==='check')return [`visible:${a.object}`];
  if(a?.kind==='click')return [`under:${a.object}`,`verified:${a.object}`];
  if(a?.kind==='seek')return [`visible:${a.object}`,`mismatch:${a.object}`];
  if(a?.kind==='key')return [`opened:${a.app}`];
  return [];
}
function context(m,parent,token,label,phase,action=null,role='normal') {
  const n=node(m,{kind:'context',parent:parent.id,token,label,phase,action,role});
  link(m,parent.id,n.id);
  const c=concept(m,token,action?actionLabel(action):label);
  link(m,n.id,c.id,'denotes',0);
  for(const condition of conditions(action)) {
    const obs=concept(m,condition,condition,'observation');link(m,obs.id,n.id,'requires',0);
  }
  return n;
}
function teach(m,query,rawActions) {
  insist(typeof query==='string'&&Array.from(query).length>0&&Array.from(query).length<=200,'Запрос: от 1 до 200 символов');
  insist(Array.isArray(rawActions)&&rawActions.length>0&&rawActions.length<=100,'Демонстрация: от 1 до 100 действий');
  const actions=rawActions.map(cleanAction);let opened='',lastCheck='';
  for(const a of actions) {
    if(a.kind==='check')lastCheck=a.object;
    if(a.kind==='click'){insist(lastCheck===a.object,'Перед кликом нужна проверка того же объекта');opened=a.object;lastCheck='';}
    if(a.kind==='move')lastCheck='';
    if(a.kind==='key'){insist(opened,'Перед клавишами откройте объект');a.app=opened;}
  }
  let previous=m.nodes.find(n=>n.kind==='root');const learned=[];
  for(const char of [...Array.from(query),END]) {
    const n=context(m,previous,`in:${char}`,char===END?'Запрос введён':char===' '?'␣':char,'input');
    learned.push(link(m,previous.id,n.id).id);previous=n;
  }
  const alternatives=new Map();
  for(const a of [...actions,{kind:'end'}]) {
    const token=`action:${JSON.stringify(a)}`;
    const n=context(m,previous,token,actionLabel(a),'execute',a);
    learned.push(link(m,previous.id,n.id).id);
    if(alternatives.has(previous.id))link(m,alternatives.get(previous.id),n.id);
    if(a.kind==='check') {
      const recovery=context(m,n,`seek:${n.id}`,`Найти ${a.object}`,'execute',{kind:'seek',object:a.object},'recovery');
      const recheck=context(m,recovery,`recheck:${n.id}`,`Проверить ${a.object} снова`,'execute',a,'recheck');
      alternatives.set(n.id,recheck.id);
    }
    previous=n;
  }
  for(const e of m.edges)e.eligibility=learned.includes(e.id)?1:0;
  m.used=learned;m.lastActionEdge=learned.at(-2)??null;m.phase='idle';m.status='trained';m.message=`Демонстрация сохранена: ${actions.length} действий. «Правильно» усиливает показанные связи.`;
  m.query=query;m.runMode='none';m.prefixLength=0;m.continuationRaw='';m.continuation='';m.generatedCount=0;m.recallVisited=[];m.lastRewardRevision=-1;
}
function gate(m,n) {
  const a=n.action,scene=m.scene;
  if(!a)return '';
  if(a.kind==='check'&&!object(scene,a.object))return `${a.object} не найден. Клик запрещён.`;
  if(a.kind==='seek') {
    if(!object(scene,a.object))return `${a.object} не найден`;
    if(underCursor(scene)===a.object)return 'Коррекция не нужна';
  }
  if(a.kind==='click') {
    if(underCursor(scene)!==a.object)return `Под курсором не ${a.object}`;
    if(scene.checked!==a.object)return `Нет актуальной проверки ${a.object}`;
  }
  if(a.kind==='key'&&scene.app!==a.app)return `Нужен фокус ${a.app||'приложения'}, сейчас ${scene.app||'нет'}`;
  return '';
}
function executeAction(m,n,event) {
  const a=n.action,s=m.scene;
  if(!a)return;
  const id=`${m.attempt}:${m.revision+1}:${n.id}`;
  if(a.kind==='end') {
    m.status='complete';m.phase='done';m.pulses=[];
    m.message='Достигнут выученный конец. Это не новая награда; результат оценивает пользователь.';return;
  }
  if(a.kind==='move'){s.cursor={x:a.x,y:a.y};s.checked='';}
  if(a.kind==='check'){
    s.checked=underCursor(s)===a.object?a.object:'';
    event.observation=s.checked?`${a.object} подтверждён под курсором`:`Здесь ${underCursor(s)||'пусто'}. Нужна коррекция к ${a.object}`;
  }
  if(a.kind==='seek'){
    const found=object(s,a.object);insist(found,'Объект исчез');s.cursor={x:found.x,y:found.y};s.checked='';
    event.observation=`Курсор перенесён к ${a.object}: ${found.x} × ${found.y}. Нужна повторная проверка.`;
  }
  if(a.kind==='click'){s.app=a.object;s.output='';s.checked='';}
  if(a.kind==='key'){s.output+=a.value;insist(s.output.length<=500,'Лимит виртуального ввода');}
  if(a.kind==='emit')m.answer+=a.value;
  m.lastActionEdge=m.used.at(-1)??null;s.version++;m.executedSteps++;
  s.executions.push({id,kind:a.kind,object:a.object||a.app||'',value:a.value||''});
  event.effect=copy(a);event.executionId=id;
}
function stepModel(m) {
  const event={kind:'tick',tick:m.tick+1,candidates:[],flows:[],winner:null,effect:null,observation:'',decision:'',message:''};
  const oldNodes=new Map(m.nodes.map(n=>[n.id,copy(n)]));
  const spikes=new Map(m.pulses.map(id=>[id,m.config.pulse]));
  const newObservation=m.scene.version!==m.lastObserved;m.lastObserved=m.scene.version;m.pulses=[];
  m.tick++;m.attemptTicks++;
  for(const n of m.nodes){n.a=bound(n.a*m.config.decay);n.trace=bound(n.trace*m.config.traceDecay);n.r=Math.max(0,n.r-1);}
  for(const e of m.edges)e.eligibility=bound(e.eligibility*m.config.eligibilityDecay);
  if(m.attemptTicks>600){m.status='limit';m.message='Остановка: 600 тактов попытки. Проверьте цикл.';event.decision='limit';event.message=m.message;return event;}
  const queryChars=Array.from(m.query);
  const recalling=m.runMode==='recall';
  const freeRecall=recalling&&m.inputIndex>=m.prefixLength;
  const expected=freeRecall?null:[...queryChars,END][m.inputIndex];
  const activePhase=m.phase==='input'||m.phase==='execute';
  for(const n of m.nodes.filter(n=>n.kind==='context')) {
    const incoming=m.edges.filter(e=>e.to===n.id&&(e.kind==='excite'||e.kind==='inhibit'));
    const attached=incoming.some(e=>e.kind==='excite'&&e.from===m.active);
    const matches=n.phase!=='input'||expected===null||n.token===`in:${expected}`;
    const structural=activePhase&&n.phase===m.phase&&attached&&matches;
    if(!structural){n.a=0;continue;}
    let exc=0,inh=0,ctx=0;
    for(const e of incoming) {
      const amplitude=spikes.get(e.from)||0;
      const amount=amplitude*e.weight;
      if(e.kind==='inhibit')inh+=amount;else exc+=amount;
      if(amplitude&&e.kind==='excite')ctx+=m.config.contextGain*e.weight*(oldNodes.get(e.from)?.trace||0);
      if(amount)event.flows.push({edgeId:e.id,from:e.from,to:n.id,amount:bound(amount),kind:e.kind});
    }
    ctx=Math.min(m.config.contextGain,ctx);
    const reason=gate(m,n);
    const requires=m.edges.filter(e=>e.kind==='requires'&&e.to===n.id);
    const obs=(!reason&&requires.length&&newObservation)?m.config.observationGain:0;
    if(obs)for(const e of requires)event.flows.push({edgeId:e.id,from:e.from,to:n.id,amount:obs/requires.length,kind:'observe'});
    const residual=n.a;
    n.a=bound(residual+exc+ctx+obs-inh);
    const r=oldNodes.get(n.id).r;
    event.candidates.push({id:n.id,label:n.label,activation:n.a,threshold:n.threshold??m.config.threshold,
      residual,excitation:Number(exc.toFixed(9)),context:bound(ctx),observation:obs,inhibition:Number(inh.toFixed(9)),
      allowed:!reason&&!r,reason:reason||(r?`Refractory: ${r} такт.`:''),refractory:r});
  }
  const valid=event.candidates.filter(c=>c.allowed).sort((a,b)=>b.activation-a.activation);
  const best=valid[0],second=valid[1];
  if(!best || best.activation<best.threshold) {
    const blocked=event.candidates.filter(c=>!c.allowed);
    m.status=blocked.length?'blocked':event.candidates.length?'below':'unknown';
    m.message=blocked.length?blocked.map(c=>`${c.label}: ${c.reason}`).join(' · '):
      event.candidates.length?'Максимум ниже порога. Нового импульса нет.':
      m.phase==='input'?(recalling?'Такой префикс не найден в обученной памяти.':'Такой запрос не обучен. Покажите демонстрацию.'):'Нет доступных переходов.';
  } else if(second && (Math.abs(best.activation-second.activation)<1e-8 || best.activation-second.activation<m.config.margin)) {
    m.status='ambiguous';m.message=`${recalling&&freeRecall?'Неоднозначное продолжение':'Неоднозначно'}: ${best.label} ${Math.round(best.activation*100)} и ${second.label} ${Math.round(second.activation*100)}. ID не определяет победителя.`;
  } else {
    const n=m.nodes.find(n=>n.id===best.id);
    event.winner=n.id;
    for(const c of event.candidates)if(c.id!==n.id)m.nodes.find(v=>v.id===c.id).a=bound(c.activation*m.config.inhibition);
    n.a=0;n.trace=1;n.r=m.config.refractory;
    m.active=n.id;m.lastFired=n.id;m.pulses=[n.id];m.status='running';
    m.message=`Выбрана ${n.label}: ${Math.round(best.activation*100)} ≥ ${Math.round(best.threshold*100)}. Подтверждённое срабатывание.`;
    const generatedStep=n.phase==='input'&&recalling&&freeRecall;
    if(generatedStep&&m.generatedCount===0&&m.continuationRaw===''){m.used=[];for(const e of m.edges)e.eligibility=0;}
    for(const e of m.edges)if(e.to===n.id&&e.kind==='excite'&&spikes.has(e.from)){e.eligibility=1;m.used.push(e.id);}
    if(n.phase==='input') {
      m.inputIndex++;
      if(recalling&&!generatedStep&&m.inputIndex===m.prefixLength){
        m.used=[];for(const e of m.edges)e.eligibility=0;
        m.message='Префикс распознан. Дальше каждый символ выбирается сетью по максимальной активации.';
      }
      if(generatedStep) {
        if(n.token===`in:${END}`) {
          m.phase='done';m.status='recall-complete';m.pulses=[];
          m.message=m.continuation?`Продолжение завершено: «${m.continuation}».`:'Продолжение завершено: обученный конец уже достигнут.';
        } else {
          const char=n.token.slice(3);
          if(m.recallVisited.includes(n.id)){m.phase='done';m.status='limit';m.pulses=[];m.message='Продолжение остановлено: обнаружен цикл контекста.';}
          else {
            m.recallVisited.push(n.id);m.generatedCount++;m.continuationRaw+=char;
            m.continuation=m.continuationRaw.startsWith(' ')?m.continuationRaw.slice(1):m.continuationRaw;
            if(m.generatedCount>=200){m.phase='done';m.status='limit';m.pulses=[];m.message='Продолжение остановлено: лимит 200 символов.';}
            else m.message=`По памяти выбран символ «${char===' '?'␣':char}». Продолжение: «${m.continuation}».`;
          }
        }
      } else if(n.token===`in:${END}`) {
        m.phase='execute';m.status='ready';m.message='Запрос распознан. Можно продолжать по сигналу.';
      }
    } else executeAction(m,n,event);
  }
  event.decision=m.status;event.message=m.message;return event;
}
function applyOperation(m,raw) {
  insist(raw&&typeof raw.kind==='string','Нет операции');const op=copy(raw);let event={kind:op.kind,message:'',candidates:[],flows:[],winner:null};
  switch(op.kind) {
    case 'teach':teach(m,op.query,op.actions);break;
    case 'start':
      insist(typeof op.query==='string'&&op.query.length&&Array.from(op.query).length<=200,'Запрос: 1–200 символов');
      resetDynamics(m);m.attempt++;m.query=op.query;m.runMode='execute';m.phase='input';m.status='running';m.pulses=[m.active];
      m.scene.checked='';m.scene.version++;m.message='Распознаём запрос по контекстным переходам.';break;
    case 'recall':
      insist(typeof op.prefix==='string'&&op.prefix.length&&Array.from(op.prefix).length<=200,'Префикс: 1–200 символов');
      resetDynamics(m);m.attempt++;m.query=op.prefix;m.runMode='recall';m.prefixLength=Array.from(op.prefix).length;
      m.phase='input';m.status='running';m.pulses=[m.active];
      m.message='Распознаём введённый префикс. После него сеть сама выбирает каждый следующий символ по сигналу.';break;
    case 'reset':
      resetDynamics(m);m.phase='idle';m.status='idle';m.message='Динамика сброшена. Граф и веса сохранены.';
      m.scene.app='';m.scene.output='';m.scene.checked='';m.scene.executions=[];m.scene.version++;break;
    case 'wake':
      insist(m.phase==='input'||m.phase==='execute','Сначала введите запрос или префикс');
      for(const n of m.nodes)n.a=0; // Retry starts a new competition; old ambiguous charge is not added twice.
      m.pulses=[m.active];m.status='running';m.message='Повторная проверка из подтверждённого контекста.';break;
    case 'tick':event=stepModel(m);break;
    case 'scene':{
      const clean=validateScene(op.scene);m.scene={...m.scene,...clean,checked:'',version:m.scene.version+1};
      m.message='Среда изменена. Проверка перед действием будет выполнена заново.';break;
    }
    case 'config':
      insist(op.values&&typeof op.values==='object','Нет параметров');
      for(const [key,v]of Object.entries(op.values)) {
        insist(Object.hasOwn(DEFAULTS,key)&&typeof v==='number'&&Number.isFinite(v),'Неизвестный параметр');
        const limit=key==='refractory'?10:1;
        insist(v>=0&&v<=limit&&(key!=='refractory'||Number.isInteger(v)),'Параметр вне диапазона');m.config[key]=v;
      }
      m.message='Параметры изменены. Скорость анимации не входит в расчёт.';break;
    case 'weight':{
      const e=m.edges.find(e=>e.id===op.id&&(e.kind==='excite'||e.kind==='inhibit'));
      insist(e&&Number.isFinite(op.value)&&op.value>=0&&op.value<=1,'Некорректный вес');e.weight=op.value;
      m.message=`Вес связи №${e.id}: ${e.weight}.`;break;
    }
    case 'inhibitory':{
      insist(m.nodes.some(n=>n.id===op.from)&&m.nodes.some(n=>n.id===op.to),'Нет вершин для торможения');
      insist(Number.isFinite(op.weight)&&op.weight>=0&&op.weight<=1,'Некорректный вес');link(m,op.from,op.to,'inhibit',op.weight);
      m.message='Добавлена тормозящая связь.';break;
    }
    case 'threshold':{
      const n=m.nodes.find(n=>n.id===op.id&&n.kind==='context');insist(n&&Number.isFinite(op.value)&&op.value>=0&&op.value<=1,'Некорректный порог');
      n.threshold=op.value;m.message=`Порог вершины ${n.label}: ${op.value}`;break;
    }
    case 'feedback':{
      insist(op.value===1||op.value===-1,'Оценка: +1 или -1');
      const used=[...new Set(m.used)];insist(used.length,'Нет выполненных связей для оценки');
      const affected=op.value===-1&&op.scope!=='episode'?[m.lastActionEdge??m.used.at(-1)]:used;
      for(const e of m.edges)if(affected.includes(e.id)&&e.kind==='excite')e.weight=bound(e.weight+(op.value>0?m.config.rewardRate:-m.config.penaltyRate)*e.eligibility);
      m.used=[];for(const e of m.edges)e.eligibility=0;
      m.message=op.value>0?'Подтверждённые связи усилены. Повторной автоматической награды нет.':'Ошибочный переход ослаблен. Условия безопасности не изменены.';break;
    }
    default:throw new Error('Неизвестная операция');
  }
  m.revision++;event.message=m.message;return {op,event};
}
export class SignalEngine {
  constructor(){this.model=freshModel();this.operations=[];this.events=[];}
  preview(op={kind:'tick'}) {
    insist(this.operations.length<MAX_OPS,'Лимит: 2000 операций. Экспортируйте эксперимент.');
    const next=copy(this.model);const result=applyOperation(next,op);
    return {baseRevision:this.model.revision,sceneVersion:this.model.scene.version,next,...result};
  }
  commit(proposal) {
    insist(proposal.baseRevision===this.model.revision&&proposal.sceneVersion===this.model.scene.version,'Предварительный шаг устарел. Пересчитайте его.');
    this.model=copy(proposal.next);this.operations.push(copy(proposal.op));this.events.push(copy(proposal.event));return proposal.event;
  }
  perform(op){return this.commit(this.preview(op));}
  at(index){const e=new SignalEngine();for(const op of this.operations.slice(0,index))e.perform(op);return e;}
  export(){return {schema:SIGNAL_VERSION,operations:copy(this.operations)};}
  static import(raw) {
    insist(raw?.schema===SIGNAL_VERSION&&Array.isArray(raw.operations)&&raw.operations.length<=MAX_OPS,'Нужен эксперимент Kolos Signal v1');
    const e=new SignalEngine();for(const op of raw.operations)e.perform(op);return e;
  }
  static fromLegacy(raw) {
    insist(raw?.schema==='kolos-graph-lab/1'&&Array.isArray(raw.commands),'Нужен JSON последовательного режима');
    const e=new SignalEngine();let query='',actions=[],count=0;
    for(const c of raw.commands) {
      if(c.kind==='input'&&!actions.length)query+=c.value;
      else if(c.kind==='action')actions.push(c.action);
      else if(c.kind==='positive'&&query&&actions.length){e.perform({kind:'teach',query,actions});count++;query='';actions=[];}
      else if(c.kind==='reset'||c.kind==='continue'||c.kind==='negative'){query='';actions=[];}
    }
    insist(count,'Не найдены явные демонстрации действий с положительной реакцией. Покажите обучение заново.');return e;
  }
}
export function calculatorDemo() {
  const e=new SignalEngine();const actions=[{kind:'move',x:500,y:150},{kind:'check',object:'CALC'},{kind:'click',object:'CALC'},...Array.from('1700',value=>({kind:'key',value}))];
  e.perform({kind:'teach',query:'добавь траты 1700',actions});return e;
}
