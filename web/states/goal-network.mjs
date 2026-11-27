import {routeDecision} from './route-selection.mjs';
import {motorAction} from './targeting.mjs';
import {sensoryFeatures,observationKey} from './environment.mjs';
import {sensoryTick,predicted,decayTraces,clearTransients,orientingChoice} from './dynamics.mjs';
import {effectObserved,acknowledgeExperience,unconfirmedResult} from './experience.mjs';
import {updateImagery,imageSatisfied,imageDemand,imageConfirmation} from './imagery.mjs';
/** Optional goal dynamics on the existing learned graph. No access to world physics.
 * The input encoder supplies desired observations, not a plan or motor sequence.
 * Rate-based leaky units, inhibitory goal occurrences, acknowledgement-gated
 * execution, and mismatch-driven inhibitory traces. Not a biological brain claim.
 */
const gc=x=>structuredClone(x), gclip=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
const gneed=(v,s)=>{if(!v)throw Error(s);};
const gn=(m,id)=>m.memory.nodes.find(n=>n.id===id);
const gkey=observationKey;
const gnext=(m,id)=>m.memory.edges.filter(e=>e.from===id&&e.kind==='next');
export const GOAL_DEFAULTS=Object.freeze({decay:.5,discount:.90,stateCompetition:1,threshold:.70,routeThreshold:.55,
 margin:.04,goalGain:1,goalInhibition:1,errorDecay:.995,errorGain:1,traceDecay:.90,maxWaves:100,maxTicks:1800,refractory:2});

function validateGoals(m,raw){
 gneed(Array.isArray(raw)&&raw.length>0&&raw.length<=8,'Нужно 1–8 желаемых результатов');
 return raw.map((goal,i)=>{
  gneed(goal&&['state','field'].includes(goal.kind),'Цель — наблюдаемое состояние или значение поля');
  const p={id:`intent:${m.attempt}:${i}`,kind:goal.kind,held:true,a:0,previous:i?`intent:${m.attempt}:${i-1}`:null};
  if(goal.kind==='state'){
   gneed(Array.isArray(goal.features)&&goal.features.length>0&&goal.features.every(x=>typeof x==='string'),'Нет признаков цели');
   const keys=JSON.stringify(sensoryFeatures(goal.features));
   const states=m.memory.nodes.filter(n=>n.kind==='state'&&JSON.stringify([...n.features].sort())===keys);
   gneed(states.length===1,'Желаемое состояние ещё не наблюдалось или неоднозначно');
   return {...p,features:gc(states[0].features),targets:[states[0].id]};
  }
  gneed(typeof goal.focus==='string'&&goal.focus&&typeof goal.value==='string'&&Array.from(goal.value).length<=160,'Нужны известное поле и строка до 160 символов');
  const states=m.memory.nodes.filter(n=>n.kind==='state'&&n.features.includes('focus:'+goal.focus));
  gneed(states.length,'Это поле ещё не наблюдалось');
  const alphabet=m.memory.nodes.filter(n=>n.kind==='motor').map(n=>n.value);
  gneed(Array.from(goal.value).every(ch=>alphabet.includes(ch)),'Нет прежнего опыта одной из запрошенных клавиш');
  return {...p,focus:goal.focus,value:goal.value,targets:states.map(n=>n.id)};
 });
}

export function startGoalNetwork(m,goals,config={}){
 gneed(!m.pending,'Сначала разрешите неподтверждённое действие');
 const cfg={...GOAL_DEFAULTS,decay:m.config.decay,discount:m.config.discount,stateCompetition:m.config.stateCompetition??1,refractory:m.config.refractory,...config};
 for(const [k,v]of Object.entries(cfg)){
  gneed(Object.hasOwn(GOAL_DEFAULTS,k)&&Number.isFinite(v)&&v>=0,'Неверная настройка сети цели');
  if(!['maxTicks','maxWaves','refractory'].includes(k))gneed(v<=1,'Коэффициент вне 0…1');
  else gneed(Number.isInteger(v)&&v<=(k==='refractory'?20:5000)&&v>=(k==='refractory'?0:1),'Некорректный предел');
 }
 const attempt=m.attempt+1;const saved=m.attempt;m.attempt=attempt;
 let encoded;try{encoded=validateGoals(m,goals);}catch(e){m.attempt=saved;throw e;}
 m.imagery=null;
 m.intent={schema:'kolos-goal-network/1',goals:encoded,config:cfg,active:null,episode:null,wave:0,
  error:{},errorHistory:[],predictions:[],acknowledged:[],goalHistory:[],lastCandidates:[],eligibility:{}};
 m.phase='intent';m.status='running';m.tick=0;m.heldGoal=true;m.entry=null;m.plan=null;m.detour=null;
 m.goalActivation={};m.activation={};m.refractory={};m.trace={};m.occ=[];m.recoveries=0;
 clearTransients(m);
 m.query='Желаемые результаты ('+encoded.length+')';m.message='Цель удерживается. Полный маршрут не задан и не вычисляется заранее.';
 return {kind:'goal-start',goals:gc(encoded)};
}

function currentState(m){return m.memory.nodes.find(n=>n.kind==='state'&&JSON.stringify([...n.features].sort())===gkey(m.observed));}
function clearWave(m){m.goalActivation={};m.intent.wave=0;delete m.intent.routeBounds;}
function suspendEpisode(m,reason){m.intent.episode=null;m.entry=null;m.activation={};clearWave(m);m.message=reason+'; цель остаётся активной.';}
function goalSatisfied(goal,o){return goal.kind==='state'?!!goal.features.length&&goal.features.every(f=>sensoryFeatures(o.features).includes(f)):o.focus===goal.focus&&o.output===goal.value;}

function choose(candidates,threshold,margin){
 const r=candidates.filter(c=>c.allowed).sort((a,b)=>b.a-a.a);
 if(!r[0]||r[0].a<threshold)return {};
 if(r[1]&&r[0].a-r[1].a<margin)return {ambiguous:true};
 return {winner:r[0]};
}
function dispatch(m,a,details){
 const step=gn(m,details.step);if(step&&!details.relocate)step.eligibility=1;
 m.serial++;const id=`${m.attempt}:${m.serial}`;
 const request={id,action:gc(a),sent:m.tick,applied:false,receipt:null,network:true,...details};
 m.pending=request;m.status='waiting';
 const prediction={id,action:gc(a),goal:m.intent.active,expected:gc(details.prediction||null),before:gkey(m.observed)};
 m.intent.predictions.push(prediction);
 m.message='Победитель: '+a.kind+' '+(a.object||a.value||'')+'. Результат ещё не подтверждён.';
 return {kind:'dispatch',winner:details.candidate||details.source||details.step,action:gc(a),request:id,prediction};
}
function markError(m,transition,reason,expected,actual,request){
 if(transition){m.intent.error[transition]=1;gn(m,transition).inhibition=1;}
 const fact={request,transition,expected,actual,reason,tick:m.tick};m.intent.errorHistory.push(fact);
 suspendEpisode(m,reason);m.status='running';
 return {kind:'prediction-error',error:fact,heldGoal:true};
}

function digitCandidates(m,g,event){
 const o=m.observed;
 if(!g.value.startsWith(o.output)){
  m.status='blocked';m.message='Содержимое поля не является началом желаемой строки. Стирание не обучалось; догадок и перезаписи нет.';
  event.kind='content-conflict';return event;
 }
 // Observation is the comparator input, not an action list. Each character has
 // its own occurrence. Consuming after a key still requires its matching receipt.
 if(!m.occ.length||m.occ[0].goal!==g.id){
  const chars=Array.from(g.value),n=Array.from(o.output).length;
  m.occ=chars.map((value,i)=>({id:`${g.id}:symbol:${i}`,goal:g.id,value,held:i>=n,a:0,
   next:i+1<chars.length?`${g.id}:symbol:${i+1}`:null,consumedBy:i<n?'observed-existing':null}));
 }
 const consumed=m.occ.filter(q=>!q.held).map(q=>q.value).join('');
 if(consumed!==o.output){
  // External editing cannot be silently treated as success or replayed.
  m.status='blocked';m.message='Содержимое поля изменилось вне подтверждений. Цель удерживается.';event.kind='content-conflict';return event;
 }
 for(const q of m.occ.filter(q=>q.held)){
  const pred=m.occ.find(n=>n.next===q.id),blocked=!!pred?.held;
  const symbol=m.memory.nodes.find(n=>n.kind==='symbol'&&n.value===q.value);
  const edge=m.memory.edges.find(e=>e.kind==='corresponds'&&e.from===symbol?.id);
  const input=edge?m.config.inputDrive*edge.weight:0,history=edge?m.config.historyGain:0,inhibition=blocked?m.config.inhibition:0;
  q.a=gclip(m.intent.config.decay*q.a+input+history-inhibition);
  event.candidates.push({id:q.id,label:'KEY '+q.value,a:q.a,input,history,inhibition,threshold:m.intent.config.threshold,allowed:!!edge,reason:blocked?'Предыдущее вхождение не подтверждено':''});
 }
 const decision=choose(event.candidates,m.intent.config.threshold,m.intent.config.margin);
 if(decision.ambiguous){m.status='ambiguous';event.kind='ambiguous';return event;}
 if(decision.winner){
  const q=m.occ.find(q=>q.id===decision.winner.id);
  return {...event,...dispatch(m,{kind:'key',value:q.value},{source:q.id,prediction:{focus:g.focus,output:o.output+q.value},target_focus:g.focus})};
 }
 if(!event.candidates.some(c=>c.allowed&&c.input>0)){m.status='blocked';m.message='Нет возбуждающей моторной связи для остатка.';}
 return event;
}

function routeWave(m,goal,event,rehearsal=false){
 const b=m.intent,cfg=b.config;b.wave++;
 const choice=routeDecision(m,b,cfg,goal.kind==='state'?goal.features:['focus:'+goal.focus],
  cfg.routeThreshold,event,b.wave>=cfg.maxWaves,imageDemand(m,goal));
 const actual=currentState(m);
 event.kind='spread';event.goal=goal.targets[0];event.current=actual?.id;event.wave=b.wave;
 if(rehearsal){event.kind='imagery-wave';event.candidate=choice.winner?.id||null;m.message='Образ возбуждает переходы; моторика выключена.';return event;}
 if(choice.ambiguous){m.status='ambiguous';m.message='Границы оценок переходов пересекаются; победитель не подтверждён.';return event;}
 if(choice.winner){
  const n=gn(m,choice.winner.id);
  b.episode={transition:n.id,step:n.first,last:n.last,source:n.from,target:n.to};m.entry=n.first;m.recoveries++;
  m.refractory[n.id]=cfg.refractory;m.trace[n.id]=1;b.eligibility[n.id]=1;
  event.kind='route';event.winner=n.id;m.message=`По сигналу выбран ${n.label}, A=${choice.winner.a.toFixed(3)}. Будущий маршрут не сохранён.`;
 }else if(choice.blocked){m.status='blocked';m.message='За лимит волн не подтверждён переход выше порога. Цель не достигнута.';}
 return event;
}

function orientGoalStep(m,step,event){
 const b=m.intent,choice=orientingChoice(m,step,b.config,event.flows);event.candidates.push(...choice.candidates);
 if(choice.ambiguous){m.status='ambiguous';m.message='Два близких изученных наведения; экземпляр ещё не подтверждён.';event.kind='ambiguous';return true;}
 const move=choice.winner;if(!move){if(choice.charging)m.message='Изученное наведение набирает возбуждение; проверяемый шаг удерживается.';return !!choice.charging;}
 m.activation[move.id]=0;m.refractory[move.id]=b.config.refractory;
 Object.assign(event,dispatch(m,move.action,{step:step.id,transition:b.episode.transition,relocate:true,candidate:move.id,prediction:{cursor:{x:move.action.x,y:move.action.y}}}));
 m.message='Возбуждён изученный '+move.label+'; после наведения заново проверяем объект.';return true;
}
function episodeTick(m,event,guard){
 const b=m.intent,ep=b.episode,step=gn(m,ep.step);
 gneed(step&&step.action,'Нет показанного шага перехода');
 const a=motorAction(m.memory,step,m.observed);
 if(!predicted(m,gn(m,step.pre),m.observed)){
  // An externally observed state change isn't evidence that this action failed.
  const previous=ep.transition;suspendEpisode(m,'Наблюдаемое состояние изменилось до следующего действия');
  event.kind='reobserve';event.transition=previous;return event;
 }
 const reason=guard(m.observed,a);
 if(reason){
  const icon=m.observed.icons.find(o=>o.id===a.object);
  if(icon&&['check','click'].includes(a.kind))return {...event,...dispatch(m,{kind:'move',x:icon.x,y:icon.y},{step:step.id,transition:ep.transition,relocate:true,prediction:{cursor:{x:icon.x,y:icon.y}}})};
  if(orientGoalStep(m,step,event))return event;
  return {...event,...markError(m,ep.transition,reason,gn(m,step.pre).key,gkey(m.observed),null)};
 }
 const edge=m.memory.edges.find(e=>e.to===step.id&&['next','starts'].includes(e.kind)),weight=edge?.weight||0;
 const aNew=gclip(b.config.decay*(m.activation[step.id]||0)+weight);m.activation[step.id]=aNew;
 event.candidates.push({id:step.id,label:step.label,a:aNew,input:0,history:weight,inhibition:0,threshold:b.config.threshold,allowed:!m.refractory[step.id]});
 if(aNew>=b.config.threshold&&!m.refractory[step.id])return {...event,...dispatch(m,a,{step:step.id,transition:ep.transition,prediction:{state:gn(m,step.post)?.key||null}})};
 return event;
}

/** One logical network tick. Host owns fresh observations and physical effects. */
export function tickGoalNetwork(m,guard){
 const b=m.intent,cfg=b.config;m.tick++;decayTraces(m);
 for(const id of Object.keys(m.refractory))m.refractory[id]=Math.max(0,m.refractory[id]-1);
 for(const id of Object.keys(m.trace))m.trace[id]=gclip(m.trace[id]*cfg.traceDecay);
 for(const id of Object.keys(b.error))b.error[id]=gclip(b.error[id]*cfg.errorDecay);
 for(const id of Object.keys(b.eligibility))b.eligibility[id]=gclip(b.eligibility[id]*cfg.traceDecay);
 if(['complete','blocked','failed','unknown','ambiguous','timeout','limit','idle'].includes(m.status))return {kind:'stopped'};
 if(m.tick>cfg.maxTicks){m.status='limit';m.message='Лимит тактов. Незавершённая цель не погашена.';return {kind:'limit'};}
 if(m.pending){
  if(m.imagery)updateImagery(m,b.goals.find(g=>g.id===b.active));
  if(m.tick-m.pending.sent>=m.config.timeout){m.status='timeout';m.message='Нет квитанции. Повтора нет; источник удерживается.';}
  return {kind:'waiting'};
 }
 const event={kind:'charge',candidates:[],flows:[],winner:null};
 sensoryTick(m,event.flows);
 const remaining=b.goals.filter(g=>g.held);
 if(!remaining.length){if(m.imagery)updateImagery(m,null);m.heldGoal=false;m.status='complete';m.message='Все желаемые результаты подтверждены наблюдениями.';return {kind:'complete'};}
 const goalCandidates=remaining.map(g=>{
  const prior=b.goals.find(p=>p.id===g.previous),blocked=!!prior?.held;
  g.a=gclip(cfg.decay*g.a+cfg.goalGain-(blocked?1.5*cfg.goalInhibition:0));
  return {id:g.id,a:g.a,allowed:true};
 });
 const goalDecision=choose(goalCandidates,cfg.threshold,cfg.margin);
 if(goalDecision.ambiguous){m.status='ambiguous';m.message='Цели конкурируют без достаточного торможения.';return {kind:'ambiguous',candidates:goalCandidates};}
 const chosen=goalDecision.winner;
 if(!chosen)return event;
 const goal=b.goals.find(g=>g.id===chosen.id);
 if(b.active!==goal.id){b.active=goal.id;m.occ=[];suspendEpisode(m,'Активирован следующий удерживаемый результат');}
 if(m.imagery){
  updateImagery(m,goal);
  if(m.imagery.mode!=='act')return routeWave(m,goal,event,true);
  if(m.imagery.ready<m.imagery.config.threshold){event.kind='imagery-charge';return event;}
  if(!m.imagery.evidence){m.message='Нет внешнего наблюдения; образ не разрешает действие.';event.kind='imagery-no-evidence';return event;}
 }
 if(m.imagery?imageSatisfied(m):goalSatisfied(goal,m.observed)){
  if(m.imagery)imageConfirmation(m,goal);
  goal.held=false;goal.a=0;goal.confirmedAt=m.tick;
  b.goalHistory.push({id:goal.id,tick:m.tick,observed:gc(m.observed),receipt:b.acknowledged.at(-1)||null});
  suspendEpisode(m,'Желаемый результат наблюдается');
  event.kind='goal-confirmed';event.winner=goal.id;return event;
 }
 if(m.imagery&&goalSatisfied(goal,m.observed)){event.kind='imagery-confirming';m.message='Совпадение наблюдается; накапливается сенсорное подтверждение.';return event;}
 if(goal.kind==='field'&&m.observed.focus===goal.focus)return digitCandidates(m,goal,event);
 if(b.episode)return episodeTick(m,event,guard);
 return routeWave(m,goal,event);
}

/** Only a matched, independently observed receipt can release a source. */
export function acceptGoalReceipt(m,raw,guard){
 gneed(!m.imagery||!raw.source||raw.source==='external','Воображаемая квитанция не принимается');
 const r=gc(raw),b=m.intent,p=m.pending;
 if(b.acknowledged.includes(r.id))return {kind:'duplicate'};
 if(!p||r.id!==p.id||JSON.stringify(r.action)!==JSON.stringify(p.action))return {kind:'ignored'};
 gneed(r.before&&r.after&&Array.isArray(r.after.features)&&typeof r.ok==='boolean','Некорректная квитанция');
 if(r.ok){gneed(!guard(r.before,p.action),'Квитанция нарушает предусловие');
  if(p.action.kind==='move')gneed(Math.abs(r.after.cursor.x-p.action.x)<=3&&Math.abs(r.after.cursor.y-p.action.y)<=3,'Нет наблюдаемого перемещения');
  if(p.action.kind==='check')gneed(!guard(r.after,p.action),'Проверка объекта не подтверждена');
 }
 if(p.source&&r.ok){
  gneed(r.after.focus===p.prediction.focus&&r.before.focus===p.prediction.focus&&r.after.output===p.prediction.output&&r.before.output+p.action.value===r.after.output,'Квитанция не подтверждает именно запрошенный ввод');
 }
 if(unconfirmedResult(m,p,r))return {kind:'unconfirmed'};
 m.pending=null;m.observed=gc(r.after);m.status='running';b.acknowledged.push(r.id);
 const learned=acknowledgeExperience(m,p,r);
 if(!r.ok)return markError(m,p.transition,r.reason||'Среда явно отклонила действие',p.prediction,gkey(r.after),r.id);
 if(p.source){
  const source=m.occ.find(q=>q.id===p.source);gneed(source?.held,'Вхождение уже погашено');source.held=false;source.a=0;source.consumedBy=r.id;
  m.message='Подтверждение погасило одно вхождение; снято торможение следующего.';
 }else if(p.relocate){
  gneed(Math.abs(r.after.cursor.x-p.action.x)<=3&&Math.abs(r.after.cursor.y-p.action.y)<=3,'Курсор не достиг цели');
 }else{
  const step=gn(m,p.step);
  if(effectObserved(r)&&!step.dispatch_only&&!predicted(m,gn(m,step.post),r.after)){
   return markError(m,p.transition,'Ожидание и наблюдение расходятся',p.prediction.state,gkey(r.after),r.id);
  }
  m.activation[p.step]=0;m.refractory[p.step]=b.config.refractory;m.trace[p.step]=1;
  if(step.id===b.episode.last){b.episode=null;m.entry=null;clearWave(m);}
  else{const links=gnext(m,step.id);gneed(links.length===1,'Неоднозначный следующий контекст показанного фрагмента');b.episode.step=links[0].to;m.entry=links[0].to;}
 }
 return {kind:'ack',receipt:r,source:p.source||null,predictionMatch:true,plasticity:learned};
}
