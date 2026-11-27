import {defaultResidualScene,residualGuard,residualUnder,applyResidualEffect,validateResidualScene,observeResidualDemonstration} from './environment.mjs';
import {learnResidualGraph,inputResidualGraph,inspectResidualRequest,residualPrevious} from './learning.mjs';

export const RESIDUAL_SCHEMA='kolos-disinhibition/1';
export const RESIDUAL_DEFAULTS=Object.freeze({threshold:.70,decay:.50,inputDrive:.65,historyGain:.04,
  inhibition:.90,margin:.035,refractory:2,ackDelay:4,timeout:30,ackMode:'auto',faultScope:'key'});
const rc=x=>structuredClone(x);
const sat=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
const requireR=(v,msg)=>{if(!v)throw Error(msg);};
const sameR=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function initialResidual() {
  const learned=learnResidualGraph([]);
  return {...learned,episodes:[],scene:defaultResidualScene(),input:{nodes:[],edges:[],head:null},
    config:{...RESIDUAL_DEFAULTS},revision:0,tick:0,attempt:0,requestSerial:0,pending:null,
    receipts:[],received:[],usedEdges:[],memoryActive:learned.memory.root,endpoint:null,activations:{},
    diagnosis:null,status:'idle',message:'Покажите два примера. Граница будет выведена из совпадений с подтверждениями, не из числа слов.',last:null};
}
function memoryNode(m,id) {return m.memory.nodes.find(n=>n.id===id);}
function inputNode(m,id) {return m.input.nodes.find(n=>n.id===id);}
function isKeyReady(m) {return memoryNode(m,m.memoryActive)?.kind==='ready';}
function targetFor(m) {return isKeyReady(m)?memoryNode(m,m.memoryActive).target:'';}
function eventR(kind,message,extra={}) {return {kind,message,tick:0,candidates:[],winner:null,flows:[],...extra};}
function faultApplies(m,p) {return m.config.faultScope==='all'||p.action.kind===m.config.faultScope;}
function pendingActionDescription(a) {
  if(a.kind==='recognize')return `Распознать «${a.value===' '?'␣':a.value}»`;
  if(a.kind==='finish')return 'Остаток отработан';
  if(a.kind==='ready')return `Фокус ${a.object} подтверждён`;
  return a.kind==='move'?`MOVE ${a.x}×${a.y}`:a.kind==='key'?`KEY ${a.value}`:`${a.kind.toUpperCase()} ${a.object}`;
}
function giveReceipt(m,p,result) {
  const receipt={...result,requestId:p.id,attempt:p.attempt,sourceId:p.sourceId??null,candidateId:p.candidateId,action:rc(p.action)};
  m.receipts.push(rc(receipt));p.receipt=receipt;return receipt;
}
function consumeReceipt(m,receipt) {
  if(m.received.includes(receipt.requestId))return eventR('duplicate','Повторное подтверждение проигнорировано: второе вхождение не погашено.');
  const p=m.pending;
  if(!p||p.id!==receipt.requestId||p.attempt!==receipt.attempt||p.sourceId!==(receipt.sourceId??null)||p.candidateId!==receipt.candidateId||!sameR(p.action,receipt.action))
    return eventR('ignored','Подтверждение не относится к ожидаемому действию. Следы запроса сохранены.');
  if(!m.receipts.some(r=>sameR(r,receipt)))return eventR('ignored','Нет подтверждённого события среды для этого сообщения.');
  m.received.push(receipt.requestId);m.pending=null;
  if(!receipt.ok) {
    if(p.sourceId){const q=inputNode(m,p.sourceId);q.state='held';q.activation=0;}
    if(receipt.reason==='mismatch'&&p.action.kind==='check') {
      m.recovery={nodeId:p.memoryTo,object:p.action.object,from:m.memoryActive};
      m.status='running';m.message=`Под курсором ${residualUnder(m.scene)||'пусто'}, а ожидается ${p.action.object}. Нужен отдельный переход поиска.`;
      return eventR('mismatch',m.message,{receipt:rc(receipt)});
    }
    m.status='failed';m.message=`Действие не выполнено: ${receipt.reason}. Ни один следующий элемент не освобождён.`;
    return eventR('failed',m.message,{receipt:rc(receipt)});
  }
  // Positive action delivery, not user reward, consumes only this request occurrence.
  if(p.sourceId) {
    const source=inputNode(m,p.sourceId);
    requireR(source&&source.held===1,'Источник подтверждения уже погашен');
    source.held=0;source.activation=0;source.refractory=m.config.refractory;source.state='consumed';
    source.consumedBy={requestId:p.id,tick:m.tick,kind:p.action.kind,receipt:rc(receipt)};
  }
  if(p.edgeId)m.usedEdges.push(p.edgeId);
  if(p.memoryTo)m.memoryActive=p.memoryTo;
  if(p.action.kind==='seek')m.recovery={...m.recovery,seekDone:true};
  if(p.action.kind==='check'&&m.recovery?.nodeId===p.memoryTo)m.recovery=null;
  if(p.action.kind==='finish') {
    m.status='complete';m.message='Все вхождения отработаны по подтверждениям. Долговременные веса не менялись.';
  } else {
    m.status='running';m.message=`Подтверждено: ${pendingActionDescription(p.action)}.${p.sourceId?' Погашено '+p.sourceId+'; торможение следующего снято.':''}`;
  }
  return eventR('ack',m.message,{receipt:rc(receipt),consumed:p.sourceId??null,winner:p.candidateId});
}
function processPending(m) {
  const p=m.pending;
  if(!p.applied) {
    if(['recognize','ready','finish'].includes(p.action.kind)) {
      const ok=p.action.kind!=='ready'||m.scene.app===p.action.object;
      p.applied=true;p.appliedAt=m.tick;
      const receipt=giveReceipt(m,p,{ok,reason:ok?'':'Фокус изменился',origin:'internal',before:null,after:null});
      return consumeReceipt(m,receipt);
    }
    p.applied=true;p.appliedAt=m.tick;
    if(faultApplies(m,p)&&m.config.ackMode==='reject') {
      giveReceipt(m,p,{ok:false,reason:'Симулятор отклонил действие до изменения среды',origin:'environment',before:null,after:null});
    } else {
      const observed=applyResidualEffect(m.scene,p);
      giveReceipt(m,p,{...observed,origin:'environment'});
    }
    m.message=`Среда обработала ${pendingActionDescription(p.action)}. Это ещё не доставленное подтверждение. След удерживается.`;
    return eventR('environment',m.message,{applied:p.receipt.ok,requestId:p.id,sourceId:p.sourceId,receipt:rc(p.receipt)});
  }
  const controlled=faultApplies(m,p),mode=controlled?m.config.ackMode:'auto';
  if(m.tick-p.sentAt>=m.config.timeout) {
    m.status='timeout';m.message='Тайм-аут подтверждения. Исход неизвестен сети: остаток удерживается, автоматического повтора действия нет.';
    return eventR('timeout',m.message,{requestId:p.id});
  }
  if(mode==='manual'||mode==='drop') {
    m.message=mode==='manual'?'Ожидание подтверждения среды. Нажмите «Доставить подтверждение».':'Подтверждение потеряно. Действие не посылается повторно; остаток удерживается.';
    return eventR('waiting',m.message,{requestId:p.id});
  }
  if(mode==='delay'&&m.tick-p.appliedAt<m.config.ackDelay) {
    m.message=`Подтверждение задержано: ${m.tick-p.appliedAt} / ${m.config.ackDelay} тактов. След удерживается.`;
    return eventR('waiting',m.message,{requestId:p.id});
  }
  return consumeReceipt(m,p.receipt);
}
function currentInputCandidates(m) {
  const candidates=[];const node=memoryNode(m,m.memoryActive);const ready=node?.kind==='ready';
  const envReason=ready?residualGuard(m.scene,{kind:'key',object:node.target}):'Фокус ещё не подтверждён';
  const motors=m.memory.nodes.filter(n=>n.kind==='motor');
  const maxObs=Math.max(1,...motors.map(n=>n.observations));
  for(const q of m.input.nodes) {
    if(!q.held)continue;
    const pred=inputNode(m,residualPrevious(m.input,q.id));
    const inhibited=pred?.held===1;const prior=q.activation*m.config.decay;
    let choice=null;
    if(!ready&&node?.kind==='context'&&m.memoryActive!==m.endpoint) {
      const edges=m.memory.edges.filter(e=>e.kind==='recognize'&&e.from===node.id&&memoryNode(m,e.to)?.token===q.value);
      if(edges.length===1)choice={id:`recognize:${q.id}:${edges[0].id}`,sourceId:q.id,edgeId:edges[0].id,memoryTo:edges[0].to,
        action:{kind:'recognize',value:q.value},input:q.held*m.config.inputDrive,history:.2*edges[0].weight,guard:''};
    } else {
      const motor=motors.find(n=>n.value===q.value);
      const map=motor&&m.memory.edges.find(e=>e.kind==='corresponds'&&e.to===motor.id);
      if(map)choice={id:`key:${q.id}`,sourceId:q.id,edgeId:map.id,memoryTo:null,
        action:{kind:'key',value:q.value,object:ready?node.target:''},
        input:q.held*m.config.inputDrive*map.weight,history:m.config.historyGain*(motor.observations/maxObs),guard:envReason};
    }
    if(!choice) {
      q.activation=0;
      candidates.push({id:'held:'+q.id,sourceId:q.id,label:`${q.value===' '?'␣':q.value} · удерживается`,activation:0,
        input:0,history:0,inhibition:0,residual:0,allowed:false,reason:'Нет совпадающей связи в текущем контексте',threshold:m.config.threshold});continue;
    }
    const inhibition=(inhibited?m.config.inhibition:0)+(choice.guard?1:0);
    const a=sat(prior+choice.input+choice.history-inhibition);
    q.activation=a;
    candidates.push({...choice,label:pendingActionDescription(choice.action),activation:a,
      inhibition,residual:prior,predecessor:inhibited?pred.id:null,
      allowed:!choice.guard&&!q.refractory,reason:choice.guard||(inhibited?`Тормозит неотработанное ${pred.id}`:q.refractory?'Refractory':''),threshold:m.config.threshold});
  }
  return candidates;
}
function memoryCandidates(m) {
  const active=memoryNode(m,m.memoryActive);const candidates=[];
  if(m.recovery) {
    const repair=m.recovery;
    const action=repair.seekDone?{kind:'check',object:repair.object}:{kind:'seek',object:repair.object};
    const reason=residualGuard(m.scene,action);
    candidates.push({id:repair.seekDone?'recheck:'+repair.nodeId:'seek:'+repair.nodeId,label:pendingActionDescription(action),
      action,memoryTo:repair.seekDone?repair.nodeId:null,sourceId:null,edgeId:null,input:0,history:.92,inhibition:reason?1:0,
      residual:0,activation:reason?0:.92,allowed:!reason,reason,threshold:m.config.threshold});return candidates;
  }
  if(active?.kind==='context'&&m.memoryActive!==m.endpoint)return candidates;
  for(const e of m.memory.edges.filter(e=>e.from===m.memoryActive&&e.kind==='follows')) {
    const to=memoryNode(m,e.to),action=to.kind==='ready'?{kind:'ready',object:to.target}:to.action;
    const reason=action.kind==='ready'?(m.scene.app===action.object?'':`Нет подтверждённого фокуса ${action.object}`):residualGuard(m.scene,action);
    const residual=(m.activations[to.id]||0)*m.config.decay;
    const a=sat(residual+e.weight-(reason?1:0));m.activations[to.id]=a;
    candidates.push({id:'event:'+to.id,label:pendingActionDescription(action),action,memoryTo:to.id,sourceId:null,edgeId:e.id,
      input:0,history:e.weight,residual,inhibition:reason?1:0,activation:a,allowed:!reason,reason,threshold:m.config.threshold});
  }
  if(active?.kind==='ready') {
    const count=m.input.nodes.filter(n=>n.held).length;
    candidates.push({id:'finish',label:'Конец неотработанного остатка',action:{kind:'finish'},sourceId:null,memoryTo:null,
      input:0,history:.85,residual:0,inhibition:count?1:0,activation:count?0:.85,allowed:true,
      reason:count?`Осталось вхождений: ${count}`:'',threshold:m.config.threshold});
    for(const motor of m.memory.nodes.filter(n=>n.kind==='motor')) {
      candidates.push({id:'old:'+motor.id,label:`Память: KEY ${motor.value}`,activation:0,input:0,history:m.config.historyGain,
        residual:0,inhibition:1,allowed:false,reason:'Нет источника — вхождения текущего запроса',threshold:m.config.threshold});
    }
  }
  return candidates;
}
function residualTick(m) {
  m.tick++;
  for(const n of m.input.nodes)n.refractory=Math.max(0,n.refractory-1);
  if(m.pending) {
    if(['timeout','failed'].includes(m.status))return eventR('halted',m.message);
    return processPending(m);
  }
  if(['idle','trained','unknown','ambiguous','failed','timeout','complete','limit','below'].includes(m.status))return eventR('halted',m.message);
  if(m.tick>1600){m.status='limit';m.message='Лимит 1600 тактов: остановка без расходования остатка';return eventR('limit',m.message);}
  const candidates=[...currentInputCandidates(m),...memoryCandidates(m)];
  const valid=candidates.filter(c=>c.allowed).sort((a,b)=>b.activation-a.activation);
  const [best,second]=valid;
  const details={candidates:rc(candidates),flows:candidates.filter(c=>c.edgeId).map(c=>({from:c.sourceId||m.memoryActive,to:c.id,edgeId:c.edgeId,amount:c.activation}))};
  if(!best||best.activation<m.config.threshold) {
    const viable=valid.some(c=>c.action?.kind==='recognize'||c.action?.kind==='key');
    const reasons=candidates.filter(c=>!c.allowed&&!c.id.startsWith('old:')).map(c=>c.reason);
    if(!viable&&reasons.length){m.status='blocked';m.message=[...new Set(reasons)].join(' · ');}
    else if(valid.length&&valid.every(c=>(c.input+c.history-c.inhibition)/(1-m.config.decay||1e-9)<m.config.threshold)) {
      m.status='below';m.message='Даже установившийся максимум ниже порога. Остаток удерживается, действие не выполнено.';
    } else m.message='Накопление готовности: ещё нет максимума выше порога. Неотработанные следы удерживаются.';
    return eventR('charge',m.message,details);
  }
  if(second&&Math.abs(best.activation-second.activation)<m.config.margin) {
    m.status='ambiguous';m.message=`Близкие максимумы: ${best.label} и ${second.label}. ID не выбирает победителя.`;
    return eventR('ambiguous',m.message,details);
  }
  const request={id:`attempt-${m.attempt}/request-${++m.requestSerial}`,attempt:m.attempt,candidateId:best.id,
    sourceId:best.sourceId??null,memoryTo:best.memoryTo??null,edgeId:best.edgeId??null,action:rc(best.action),
    sentAt:m.tick,applied:false,receipt:null};
  if(request.sourceId)inputNode(m,request.sourceId).state='waiting';
  m.pending=request;m.status='waiting';
  m.message=`Максимум ${(best.activation*100).toFixed(1)}: ${best.label}. Ожидаем отдельное подтверждение; след НЕ погашен.`;
  m.last={winner:best.id,sourceId:best.sourceId,activation:best.activation};
  return eventR('dispatch',m.message,{...details,winner:best.id,request:rc(request)});
}
function applyResidualOperation(m,op) {
  requireR(op&&typeof op.kind==='string','Нет операции');let ev;
  switch(op.kind) {
    case 'teach': {
      requireR(!m.pending,'Сначала завершите или сбросьте текущую попытку');
      requireR(m.episodes.length<16,'Не более 16 демонстраций');
      const record=rc(op.record);alignValidate(record);
      record.id=`episode-${m.episodes.length+1}`;record.approved=op.approved===true;
      m.episodes.push(record);Object.assign(m,learnResidualGraph(m.episodes,m.memory));
      m.memoryActive=m.memory.root;m.input={nodes:[],edges:[],head:null};m.endpoint=null;m.activations={};m.status='trained';
      m.message=record.approved?'Демонстрация и подтверждения сохранены. Сопоставление обновлено.':'Демонстрация сохранена. Нажмите «Правильно» для включения её в сравнение.';
      ev=eventR('teach',m.message);break;
    }
    case 'approve': {
      requireR(!m.pending,'Ожидается действие');const ep=m.episodes.find(e=>e.id===op.id)||m.episodes.at(-1);
      requireR(ep,'Нет демонстрации');ep.approved=true;Object.assign(m,learnResidualGraph(m.episodes,m.memory));
      m.memoryActive=m.memory.root;m.activations={};m.status='trained';m.message='Пользователь подтвердил демонстрацию. Веса исполнения остаются заморожены.';
      ev=eventR('approve',m.message);break;
    }
    case 'start': {
      requireR(!m.pending,'Есть неподтверждённое действие. Сбросьте попытку явно, не повторяйте действие.');
      m.attempt++;m.tick=0;m.input=inputResidualGraph(op.query,m.attempt);m.endpoint=null;m.activations={};m.last=null;m.usedEdges=[];m.recovery=null;
      m.memoryActive=m.memory.root;m.diagnosis=inspectResidualRequest(m.memory,m.input);
      m.status=m.diagnosis.ok?'running':'unknown';m.endpoint=m.diagnosis.endpoint??null;
      m.message=m.diagnosis.ok?'Полный вход проверен по связям. Начинаем распознавание, без извлечения числа.':m.diagnosis.reason;
      ev=eventR('start',m.message);break;
    }
    case 'tick':ev=residualTick(m);break;
    case 'deliver': {
      requireR(m.pending?.applied&&m.pending.receipt,'Среда ещё не обработала действие');
      ev=consumeReceipt(m,rc(m.pending.receipt));break;
    }
    case 'receipt':ev=consumeReceipt(m,rc(op.receipt));break;
    case 'reset': {
      // Explicit abandonment is not confirmation. Old receipts carry an old attempt/request identity.
      m.pending=null;m.input={nodes:[],edges:[],head:null};m.memoryActive=m.memory.root;m.endpoint=null;m.recovery=null;
      m.activations={};m.status='idle';m.last=null;m.tick=0;m.scene.app='';m.scene.output='';m.scene.checked='';m.scene.effects=[];m.scene.version++;
      m.message='Попытка сброшена явно. Примеры, связи и веса сохранены.';ev=eventR('reset',m.message);break;
    }
    case 'resume': {
      requireR(!m.pending,'Подтверждение ожидается: повторный запрос действия запрещён');
      requireR(m.diagnosis?.ok&&m.input.nodes.length,'Сначала передайте полный запрос');
      m.status='running';m.message='Повторная проверка среды. Неотработанный остаток сохранён.';ev=eventR('resume',m.message);break;
    }
    case 'scene': {
      const clean=validateResidualScene(op.scene);Object.assign(m.scene,clean);m.scene.checked='';m.scene.version++;
      m.message='Среда изменена. Непосредственно перед эффектом проверка будет выполнена заново.';ev=eventR('scene',m.message);break;
    }
    case 'config': {
      requireR(!m.pending,'Не меняйте условия посреди неподтверждённого действия');
      for(const [key,v]of Object.entries(op.values||{})) {
        requireR(Object.hasOwn(RESIDUAL_DEFAULTS,key),'Неизвестный параметр');
        if(key==='ackMode')requireR(['auto','delay','manual','reject','drop'].includes(v),'Неизвестный режим подтверждений');
        else if(key==='faultScope')requireR(['key','click','all'].includes(v),'Неизвестная область сбоя');
        else {
          const max=key==='timeout'?200:key==='ackDelay'?150:key==='refractory'?10:1;
          requireR(typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=max,'Параметр вне диапазона');
          if(['timeout','ackDelay','refractory'].includes(key))requireR(Number.isInteger(v),'Нужны целые такты');
          if(['timeout'].includes(key))requireR(v>=2,'Слишком короткий тайм-аут');
        }
        m.config[key]=v;
      }
      m.message='Изменены общие параметры, не скорость обучения.';ev=eventR('config',m.message);break;
    }
    case 'weight': {
      requireR(!m.pending&&['idle','trained','complete','unknown','ambiguous','blocked'].includes(m.status),'Изменение веса только на остановленном эксперименте');
      const e=m.memory.edges.find(e=>e.id===op.id);
      requireR(e&&['recognize','follows','corresponds'].includes(e.kind)&&Number.isFinite(op.value)&&op.value>=0&&op.value<=1,'Некорректный вес');
      e.weight=op.value;m.message='Вес изменён вручную. Контрольный запуск вновь использует неизменные веса.';ev=eventR('weight',m.message);break;
    }
    default:throw Error('Неизвестная операция');
  }
  m.revision++;ev.tick=m.tick;ev.revision=m.revision;return ev;
}
function alignValidate(record) {
  requireR(record&&Array.isArray(record.confirmations),'Нужны наблюдения демонстрации');
  const replay=observeResidualDemonstration(record.query,record.actions,record.initial);
  requireR(sameR(replay.confirmations,record.confirmations),'Подтверждения не соответствуют показанным действиям');
}
export class ResidualEngine {
  constructor(){this.model=initialResidual();this.operations=[];this.events=[];}
  preview(operation={kind:'tick'}) {
    requireR(this.operations.length<5000,'Лимит 5000 операций. Экспортируйте эксперимент');
    const op=rc(operation),next=rc(this.model),event=applyResidualOperation(next,op);
    return {base:this.model.revision,op,next,event};
  }
  commit(p) {
    requireR(p.base===this.model.revision,'Расчёт устарел: пересчитайте такт');
    this.model=rc(p.next);this.operations.push(rc(p.op));this.events.push(rc(p.event));return p.event;
  }
  perform(op){return this.commit(this.preview(op));}
  export(){return {schema:RESIDUAL_SCHEMA,operations:rc(this.operations)};}
  static import(raw) {
    requireR(raw?.schema===RESIDUAL_SCHEMA&&Array.isArray(raw.operations)&&raw.operations.length<=5000,'Нужен эксперимент «Снятие торможения» v1');
    const e=new ResidualEngine();for(const op of raw.operations)e.perform(op);return e;
  }
  at(index){const e=new ResidualEngine();for(const op of this.operations.slice(0,index))e.perform(op);return e;}
}
