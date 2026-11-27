import {persistentGraph} from './environment.mjs';
import {motorAction} from './targeting.mjs';
import {routeDecision} from './route-selection.mjs';
import {sensoryTick,demandFeatures,predicted,decayTraces,clearTransients,orientingChoice} from './dynamics.mjs';
import {experienceState,effectObserved,acknowledgeExperience,unconfirmedResult} from './experience.mjs';
import {teachLanguage,startLanguage,tickLanguage,languageWeight} from './language.mjs';
import {startImagery,controlImagery} from './imagery.mjs';
import {startGoalNetwork,tickGoalNetwork,acceptGoalReceipt} from './goal-network.mjs';
import {defaultWorld,validateWorld,observeWorld,observationKey,worldGuard,applyWorld,demonstration,iconDemonstrationActions} from './environment.mjs';
/** Experimental goal-biased spreading activation + acknowledged disinhibition.
 * Only the simulator knows window semantics. Inference never calls its transition rules. */
const sc=x=>structuredClone(x),clamp=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
const need=(v,message)=>{if(!v)throw Error(message);};
export const STATE_VERSION='kolos-states/2';
export const STATE_DEFAULTS=Object.freeze({decay:.5,weight:.9,threshold:.70,planThreshold:.65,margin:.04,
 discount:.90,stateCompetition:1,refractory:2,inputDrive:.65,inhibition:.95,historyGain:.04,ackMode:'auto',ackDelay:4,timeout:40,plasticity:1,learningRate:.05});
function fresh(){const w=defaultWorld();return {world:w,observed:observeWorld(w),memory:{nodes:[{id:'n0',kind:'context',label:'Начало запроса'}],edges:[],root:'n0',serial:1},
 config:{...STATE_DEFAULTS},lessons:[],exposures:[],commands:[],audit:[],tick:0,revision:0,attempt:0,serial:0,query:'',occ:[],heldGoal:false,
 phase:'idle',status:'idle',message:'Обучите переходам; сеть не знает, что делает крестик.',context:'n0',entry:null,recognitionLeft:0,
 pending:null,receipts:[],received:[],plan:null,detour:null,blockedTransitions:[],recoveries:0,activation:{},goalActivation:{},refractory:{},trace:{},last:null};}
function N(m,spec){const n={id:'n'+m.memory.serial++,...spec};m.memory.nodes.push(n);return n;}
function E(m,from,to,kind,weight=m.config.weight){const e=m.memory.edges.find(e=>e.from===from&&e.to===to&&e.kind===kind);if(e)return e;
 const n={id:'e'+m.memory.serial++,from,to,kind,weight};m.memory.edges.push(n);return n;}
const findN=(m,id)=>m.memory.nodes.find(n=>n.id===id);
const nextEdge=(m,id,kind='next')=>m.memory.edges.filter(e=>e.from===id&&e.kind===kind);
function stateOf(m,o,create=false){if(create)return experienceState(m,o);return m.memory.nodes.find(n=>n.kind==='state'&&n.key===observationKey(o));}
export function actionText(a){if(!a)return '—';return a.kind==='move'?`MOVE ${a.x}×${a.y}`:a.kind==='key'?`KEY ${a.value===' '?'␣':a.value}`:a.kind==='drive'?'Символы текущего запроса':a.kind==='finish'?'Подтверждённый конец':`${a.kind.toUpperCase()} ${a.object||''}`;}
/** Generic association from a demonstrated input symbol to the confirmed key effect.
 * No digit range or default alphabet: previously unobserved keys remain unknown. */
function learnObservedKeys(m,receipts,origin){
 for(const r of receipts.filter(r=>r.action.kind==='key'&&r.ok)){
  const value=r.action.value;
  need(r.after.output===r.before.output+value&&r.after.focus===r.before.focus,'Нет наблюдаемого ввода символа');
  let symbol=m.memory.nodes.find(n=>n.kind==='symbol'&&n.value===value);
  let motor=m.memory.nodes.find(n=>n.kind==='motor'&&n.value===value);
  if(!symbol)symbol=N(m,{kind:'symbol',label:value,value});
  if(!motor)motor=N(m,{kind:'motor',label:'KEY '+value,value,evidence:[]});
  if(!motor.evidence.includes(origin))motor.evidence.push(origin);
  E(m,symbol.id,motor.id,'corresponds',1);
 }
}
/** A MOVE followed by CHECK targets that object; incidental hover pixels are not a new command. */
function setupSignature(context,data,focus,steps){
 return JSON.stringify([context,data,focus,steps.map((step,i)=>{
  const following=steps[i+1]?.action||{},action=step.action.kind==='move'&&following.kind==='check'?{kind:'move',object:following.object}:step.action;
  return [action,step.pre,step.post,step.visual_ack||false,step.dispatch_only||false];
 })]);
}
function demonstrationSignature(context,data,focus,setup,final){
 const steps=setup.map(r=>({action:r.action,pre:observationKey(r.before),post:observationKey(r.after),
  visual_ack:r.action.kind==='enter'&&r.verified_by==='visual-change',dispatch_only:r.effect_observed===false}));
 steps.push({action:{kind:data?'drive':'finish'},pre:observationKey(final),post:null});
 return setupSignature(context,data,focus,steps);
}
function commandSignature(m,command){
 const nodes=new Map(m.memory.nodes.map(n=>[n.id,n])),following=new Map(),seen=new Set(),steps=[];
 for(const edge of m.memory.edges)if(edge.kind==='next')following.set(edge.from,[...(following.get(edge.from)||[]),edge.to]);
 let current=command.first;
 while(!seen.has(current)){
  seen.add(current);const step=nodes.get(current);if(!step||step.kind!=='step')return null;
  const pre=nodes.get(step.pre),post=nodes.get(step.post);if(!pre||pre.kind!=='state'||(step.post!==null&&step.post!==undefined&&!post))return null;
  steps.push({action:step.action,pre:pre.key,post:post?.key??null,visual_ack:step.visual_ack||false,dispatch_only:step.dispatch_only||false});
  if(step.action.kind===(command.data?'drive':'finish'))return setupSignature(command.context,command.data,command.focus,steps);
  const links=following.get(current)||[];if(links.length!==1)return null;current=links[0];
 }
 return null;
}
function selectCommandMatch(m,matches){
 if(matches.length===1)return matches[0];
 const signatures=matches.map(match=>commandSignature(m,match.command));
 need(!signatures.includes(null)&&new Set(signatures).size===1,'Неоднозначная команда: демонстрации различаются по действиям, полям или состояниям');
 return matches[0];
}
function learn(m,record){
 need(!m.pending,'Сначала завершите ожидающее действие');need(m.lessons.length<20,'Лимит 20 демонстраций');
 const checked=demonstration(record.query,record.initial,record.receipts.map(r=>r.action));
 need(JSON.stringify(checked.receipts)===JSON.stringify(record.receipts),'Подтверждения демонстрации подменены');
 const seq=checked.receipts,firstKey=seq.findIndex(r=>r.action.kind==='key');let prefix=record.query,data=false,setup=seq,alignment=[];
 if(firstKey>=0){
  need(seq.slice(firstKey).every(r=>r.action.kind==='key'),'Поддерживается один заключительный блок клавиш');
  const values=seq.slice(firstKey).map(r=>r.action.value),chars=Array.from(record.query),offsets=[];
  for(let i=0;i+values.length<=chars.length;i++)if(values.every((v,j)=>v===chars[i+j]))offsets.push(i);
  need(offsets.length===1&&offsets[0]>0&&offsets[0]+values.length===chars.length,'Неоднозначное соответствие клавиш запросу');
  prefix=chars.slice(0,offsets[0]).join('');data=true;setup=seq.slice(0,firstKey);
  alignment=values.map((v,j)=>({symbol:v,input:offsets[0]+j,receipt:seq[firstKey+j].id}));
 }
 let context=m.memory.root;for(const ch of Array.from(prefix)){
  let edge=nextEdge(m,context,'recognize').find(e=>findN(m,e.to).symbol===ch);
  if(!edge){const n=N(m,{kind:'context',symbol:ch,label:ch===' '?'␣':ch});edge=E(m,context,n.id,'recognize');}context=edge.to;
 }
 const focus=data?seq[firstKey].before.focus:'',signature=demonstrationSignature(context,data,focus,setup,seq.at(-1).after);
 const old=m.commands.find(c=>commandSignature(m,c)===signature);
 if(old){learnObservedKeys(m,seq,'Повторная демонстрация: '+record.query);m.lessons.push(checked);m.audit.push({query:record.query,alignment,data,source:'Повторное подтверждение; связи не дублируются'});return;}
 let previous=context,first=null,segmentFirst=null,lastBoundaryState=null;
 for(const r of setup){
  const from=stateOf(m,r.before,true),to=stateOf(m,r.after,true);
  const step=N(m,{kind:'step',label:actionText(r.action),action:sc(r.action),pre:from.id,post:to.id,visual_ack:false,dispatch_only:r.effect_observed===false});
  E(m,previous,step.id,previous===context?'starts':'next');previous=step.id;if(!first)first=step.id;if(!segmentFirst){segmentFirst=step.id;lastBoundaryState=from.id;}
  if(effectObserved(r)){
   const trans=N(m,{kind:'transition',label:r.action.kind.toUpperCase()+' '+(r.action.object||''),from:lastBoundaryState,to:to.id,first:segmentFirst,last:step.id});
   E(m,to.id,trans.id,'backward');E(m,trans.id,lastBoundaryState,'backward',1);
   E(m,lastBoundaryState,trans.id,'applicable',1);E(m,trans.id,step.id,'experienced',1);
   segmentFirst=null;
  }
 }
 const finish=N(m,{kind:'step',label:data?'Символы текущего запроса':'Конец команды',action:{kind:data?'drive':'finish'},pre:stateOf(m,seq.at(-1).after,true).id,post:null});
 E(m,previous,finish.id,previous===context?'starts':'next');if(!first)first=finish.id;
 m.commands.push({context,first,data,signature,label:record.query,focus});
 learnObservedKeys(m,seq,'Демонстрация команды: '+record.query);
 m.lessons.push(checked);m.audit.push({query:record.query,data,prefix,alignment,source:data?'Гипотеза соответствия из одной демонстрации; это заданный индуктивный принцип':'Последовательность подтверждённых событий'});
 m.context=m.memory.root;m.entry=null;m.phase='idle';m.status='trained';m.message='Демонстрация сохранена. Связи состояний созданы только по её наблюдениям.';
}
function inspect(m,query){let cur=m.memory.root,index=0;const chars=Array.from(query),matches=[];
 while(true){for(const c of m.commands.filter(c=>c.context===cur)){
  if(!c.data&&index===chars.length)matches.push({command:c,recognized:index});
  if(c.data&&index<chars.length&&chars.slice(index).every(ch=>m.memory.nodes.some(n=>n.kind==='motor'&&n.value===ch)))matches.push({command:c,recognized:index});}
  if(index>=chars.length)break;const edges=nextEdge(m,cur,'recognize').filter(e=>findN(m,e.to).symbol===chars[index]);if(edges.length!==1)break;cur=edges[0].to;index++;
 }
 need(matches.length,'Нет полного согласованного запроса. Регистр значим; данным нужны входные вхождения.');return selectCommandMatch(m,matches);}
function goalStart(m,step,reason){
 if(m.plan?.goal===step.pre)return;
 m.experienceStart=m.receipts.length;
 m.plan={goal:step.pre,suspended:step.id,round:0};m.goalActivation={};m.activation={};
 m.message=`${reason}. Исходная цель удерживается; возбуждаем состояние ${findN(m,step.pre).label}.`;
}
/** Resume only an unsent step; dispatch still checks the current observation. */
function resumeObservedStep(m){
 if(!m.plan||m.detour||m.pending)return false;
 const step=findN(m,m.plan.suspended),a=step.action,obs=m.observed;
 let ready=false;
 if(a.kind==='drive')ready=!!obs.focus&&obs.focus===m.selectedCommand.focus;
 else if(['check','click'].includes(a.kind))ready=obs.icons.some(i=>i.id===a.object);
 else if(a.kind==='enter')ready=!worldGuard(obs,a);
 if(!ready){
  const reason=a.kind==='drive'?'Нет нужного фокуса ввода':worldGuard(obs,a);
  m.message=reason+'. Исходная цель удерживается.';return false;
 }
 m.entry=step.id;m.plan=null;m.goalActivation={};m.activation={};
 m.message='Нужный объект или фокус снова наблюдается; продолжаем исходный шаг.';
 return true;
}
function orientCommandStep(m,step,event){
 const choice=orientingChoice(m,step,m.config,event.flows);event.candidates.push(...choice.candidates);
 if(choice.ambiguous){m.status='ambiguous';m.message='Два близких изученных наведения; экземпляр ещё не подтверждён.';event.kind='ambiguous';return true;}
 const move=choice.winner;if(!move){if(choice.charging)m.message='Изученное наведение набирает возбуждение; проверяемый шаг удерживается.';return !!choice.charging;}
 m.activation[move.id]=0;m.refractory[move.id]=m.config.refractory;
 Object.assign(event,request(m,move.action,{relocate:true,step:step.id,candidate:move.id}));
 m.message='Возбуждён изученный '+move.label+'; после наведения заново проверяем объект.';return true;
}
function planTick(m,event){
 const g=m.plan;g.round++;
 const choice=routeDecision(m,g,m.config,demandFeatures(m,findN(m,g.suspended)),m.config.planThreshold,event,g.round>=60);
 const current=stateOf(m,m.observed);event.goal=g.goal;event.current=current?.id;event.kind='spread';
 m.message=`Цель ${findN(m,g.goal).label} удерживается. Волна ${g.round}: результат → переход → исходное состояние.`;
 if(choice.ambiguous){m.status='ambiguous';m.message='Границы оценок переходов пересекаются; победитель не подтверждён.';return;}
 if(choice.winner){
  const best=choice.winner;
  const t=findN(m,best.id);m.detour={transition:t.id,last:t.last,target:t.to};m.entry=t.first;m.recoveries++;m.plan.active=true;
  event.kind='route';event.winner=t.id;m.refractory[t.id]=m.config.refractory;m.trace[t.id]=1;
  m.message=`Максимум ${best.a.toFixed(3)}: ${t.label}. Выбран ранее наблюдавшийся переход, не команда 2. Исходная цель не погашена.`;
 }else if(choice.blocked){m.status='blocked';m.message='За лимит волн не подтверждён путь выше порога.';}
}
function request(m,a,details={}){
 const step=findN(m,details.step);if(step&&!details.relocate)step.eligibility=1;
 m.pending={id:`${m.attempt}:${++m.serial}`,action:sc(a),sent:m.tick,applied:false,receipt:null,...details};m.status='waiting';
 return {kind:'dispatch',winner:details.candidate||details.step||null,action:sc(a),request:m.pending.id};
}
function deliver(m,r){
 if(m.intent){if(m.intent.acknowledged.includes(r.id))return {kind:'duplicate'};need(m.receipts.some(x=>JSON.stringify(x)===JSON.stringify(r)),'Нет наблюдаемой квитанции среды');return acceptGoalReceipt(m,r,worldGuard);}
 if(m.received.includes(r.id))return {kind:'duplicate',message:'Повторное подтверждение проигнорировано'};
 const p=m.pending;
 if(!p||r.id!==p.id||JSON.stringify(r.action)!==JSON.stringify(p.action)||!m.receipts.some(x=>JSON.stringify(x)===JSON.stringify(r)))return {kind:'ignored',message:'Чужое подтверждение не изменяет цель'};
 if(unconfirmedResult(m,p,r))return {kind:'unconfirmed'};
 const learned=acknowledgeExperience(m,p,r);m.received.push(r.id);m.pending=null;
 if(!r.ok){m.status='failed';m.message='Действие не выполнено: '+r.reason;return {kind:'failed',receipt:r};}
 m.observed=sc(r.after);m.status='running';
 if(p.source){const q=m.occ.find(n=>n.id===p.source);need(q?.held,'Вхождение уже погашено');
  need(r.after.focus===r.before.focus&&r.after.output===r.before.output+p.action.value,'Подтверждение не содержит ожидаемого изменения поля');
  q.held=false;q.a=0;q.consumedBy=r.id;m.message=`Подтверждён ${actionText(p.action)}. ${q.id} погашено; снято торможение следующего.`;
 }else if(p.relocate){m.message='Курсор исправлен по видимому объекту. Проверяем иконку снова.';}
 else {
  const step=findN(m,p.step);
  if(effectObserved(r)&&!step.dispatch_only&&step.post&&!predicted(m,findN(m,step.post),m.observed)){
   if(m.detour){findN(m,m.detour.transition).inhibition=1;m.entry=m.plan.suspended;m.detour=null;m.plan=null;}
   goalStart(m,findN(m,m.entry),'Наблюдён другой результат; ошибочный переход заторможен');return {kind:'prediction-error',receipt:r,plasticity:learned};
  }
  m.activation[p.step]=0;m.trace[p.step]=1;m.refractory[p.step]=m.config.refractory;
  if(m.detour&&step.id===m.detour.last){
   const suspended=m.plan.suspended;m.detour=null;m.plan=null;m.goalActivation={};m.entry=suspended;
   m.message='Переход среды подтверждён. Возвращаемся к незавершённому действию исходной команды.';
  }else{const next=nextEdge(m,step.id);need(next.length===1,'Нарушена последовательность подтверждённых шагов');m.entry=next[0].to;m.message='Подтверждён '+actionText(p.action)+'. Следующий шаг освобождён.';}
 }
 return {kind:'ack',receipt:r,source:p.source||null,current:stateOf(m,m.observed)?.id,plasticity:learned};
}
function processPending(m){const p=m.pending;
 if(!p.applied){p.applied=true;p.appliedAt=m.tick;
  const r=m.config.ackMode==='reject'?{id:p.id,action:sc(p.action),ok:false,reason:'Симулятор отклонил действие',before:observeWorld(m.world),after:observeWorld(m.world)}:applyWorld(m.world,p);
  p.receipt=sc(r);m.receipts.push(sc(r));m.message='Эффект в среде получен; подтверждение ещё не доставлено. Цель удерживается.';return {kind:'effect',action:p.action,receipt:sc(r)};}
 if(m.tick-p.sent>=m.config.timeout){m.status='timeout';m.message='Тайм-аут подтверждения. Без повторной отправки и погашения.';return {kind:'timeout'};}
 if(['manual','drop'].includes(m.config.ackMode)){m.message='Ждём подтверждение среды, не повторяем действие.';return {kind:'waiting'};}
 if(m.config.ackMode==='delay'&&m.tick-p.appliedAt<m.config.ackDelay)return {kind:'waiting',message:'Подтверждение задержано'};
 return deliver(m,p.receipt);
}
function tick(m){
 if(m.phase==='language'&&m.language?.status==='reading'){
  const ev=tickLanguage(m);
  if(ev.kind==='language-image'){const ticks=m.tick,text=m.query;startGoalNetwork(m,[ev.goal]);startImagery(m);m.tick=ticks;m.query=text;m.language.status='imagined';m.language.handoffTick=ticks;m.imagery.source={kind:'language',readout:sc(ev.readout)};}
  return ev;
 }
 if(m.intent&&m.phase==='intent'){
  const event=tickGoalNetwork(m,worldGuard);
  if(m.pending&&event.kind==='waiting'&&m.status!=='timeout')return processPending(m);
  return event;
 }
 m.tick++;decayTraces(m);for(const id of Object.keys(m.refractory))m.refractory[id]=Math.max(0,m.refractory[id]-1);
 for(const id of Object.keys(m.trace))m.trace[id]=clamp(m.trace[id]*.9);
 if(['idle','trained','complete','unknown','failed','timeout','ambiguous','blocked','limit'].includes(m.status))return {kind:'stopped'};
 if(m.tick>1800||m.recoveries>12){m.status='limit';m.message='Ограничитель циклов: цель не считается выполненной';return {kind:'limit'};}
 if(m.pending)return processPending(m);
 const event={kind:'charge',candidates:[],flows:[],winner:null};
 if(m.phase==='recognize'){
  const q=m.occ.find(n=>n.held);need(q,'Нет входа распознавания');
  const links=nextEdge(m,m.context,'recognize').filter(e=>findN(m,e.to).symbol===q.value);need(links.length===1,'Нарушен контекст');
  const e=links[0];q.a=clamp(q.a*m.config.decay+m.config.inputDrive+.2*e.weight);
  event.candidates=[{id:q.id,label:q.value===' '?'␣':q.value,a:q.a,input:m.config.inputDrive,history:.2*e.weight,inhibition:0,allowed:true,threshold:m.config.threshold}];
  event.flows=[{from:e.from,to:e.to,edge:e.id,value:q.a}];
  if(q.a>=m.config.threshold){q.held=false;q.a=0;q.consumedBy='internal:recognition';m.context=e.to;m.recognitionLeft--;event.winner=q.id;event.kind='recognized';
   m.message='Распознан символ «'+(q.value===' '?'␣':q.value)+'». Цель команды удерживается.';
   if(m.recognitionLeft===0)m.phase='execute';}
  return event;
 }
 sensoryTick(m,event.flows);
 if(m.plan&&!m.detour&&!resumeObservedStep(m)){
  if(orientCommandStep(m,findN(m,m.plan.suspended),event))return event;
  planTick(m,event);return event;
 }
 const step=findN(m,m.entry);need(step,'Нет активного шага');const a=motorAction(m.memory,step,m.observed);
 if(a.kind==='finish'){m.heldGoal=false;m.status='complete';m.message='Исходная команда завершена по подтверждениям среды.';return {kind:'complete',winner:step.id};}
 if(a.kind==='drive'){
  const remain=m.occ.filter(q=>q.held);
  if(!remain.length){m.heldGoal=false;m.status='complete';m.message='Новые цифры введены и подтверждены.';return {kind:'complete'};}
  if(m.observed.focus!==m.selectedCommand.focus){goalStart(m,step,'Нет нужного фокуса ввода');return {kind:'need-state',goal:step.pre};}
  for(const q of remain){const predecessor=m.occ.find(n=>n.next===q.id),blocked=predecessor?.held;
   const symbol=m.memory.nodes.find(n=>n.kind==='symbol'&&n.value===q.value),edge=m.memory.edges.find(e=>e.kind==='corresponds'&&e.from===symbol?.id);
   const input=edge?m.config.inputDrive*edge.weight:0,history=edge?m.config.historyGain:0,inhibition=blocked?m.config.inhibition:0;
   q.a=clamp(m.config.decay*q.a+input+history-inhibition);
   event.candidates.push({id:q.id,label:'KEY '+q.value,a:q.a,input,history,inhibition,allowed:!!edge&&!blocked,reason:blocked?'Неотработан предшественник '+predecessor.id:'',threshold:m.config.threshold});
  }
  const ranks=event.candidates.filter(c=>c.allowed).sort((a,b)=>b.a-a.a),[best,second]=ranks;
  if(best?.a>=m.config.threshold){if(second&&best.a-second.a<m.config.margin){m.status='ambiguous';return event;}
   const q=remain.find(q=>q.id===best.id);return {...event,...request(m,{kind:'key',value:q.value},{source:q.id,step:step.id,candidate:q.id})};}
  m.message='Неотработанные вхождения сохраняются; накапливается готовность первой разрешённой цифры.';return event;
 }
 const reason=worldGuard(m.observed,a);
 if(reason){
  const visible=m.observed.icons.find(o=>o.id===a.object);
  if(visible&&['check','click'].includes(a.kind))return {...event,...request(m,{kind:'move',x:visible.x,y:visible.y},{relocate:true,step:step.id})};
  if(orientCommandStep(m,step,event))return event;
  if(m.detour){findN(m,m.detour.transition).inhibition=1;m.detour=null;m.entry=m.plan.suspended;m.plan=null;}
  goalStart(m,findN(m,m.entry),reason);return {...event,kind:'need-state',goal:m.plan.goal};
 }
 const edge=m.memory.edges.find(e=>e.to===step.id&&['starts','next'].includes(e.kind));
 const old=m.activation[step.id]||0,input=0,history=edge?.weight||0;
 const score=clamp(old*m.config.decay+history);m.activation[step.id]=score;
 event.candidates=[{id:step.id,label:step.label,a:score,input,history,inhibition:0,allowed:!m.refractory[step.id],threshold:m.config.threshold}];
 if(edge)event.flows=[{from:edge.from,to:edge.to,edge:edge.id,value:history}];
 if(score>=m.config.threshold&&!m.refractory[step.id])return {...event,...request(m,a,{step:step.id})};
 return event;
}
function apply(m,op){let event={kind:op.kind};
 switch(op.kind){
 case 'language-teach':event=teachLanguage(m,op.phrase,op.goal);break;
 case 'language-start':event=startLanguage(m,op.phrase,op.config);break;
 case 'language-weight':languageWeight(m,op.id,op.value);break;
 case 'teach':learn(m,sc(op.record));break;
 case 'expose':{
  need(!m.pending,'Ожидается действие');need(m.exposures.length<20,'Лимит 20 записей прежнего ввода');
  const r=sc(op.record),check=demonstration(r.query,r.initial,r.receipts.map(x=>x.action));
  need(JSON.stringify(check.receipts)===JSON.stringify(r.receipts),'Подменены подтверждения прежнего ввода');
  need(r.receipts.every(x=>x.action.kind==='key'),'Прежний ввод содержит только клавиши в уже открытом поле');
  learnObservedKeys(m,r.receipts,'Прежний ввод №'+(m.exposures.length+1));m.exposures.push(check);
  m.status='trained';m.message='Сохранены наблюдённые соответствия символов клавишам. Команда и порядок нового запроса не обучались.';break;}

 case 'imagine':{m.language=null;m.observed=observeWorld(m.world);event=startGoalNetwork(m,op.goals,op.config);startImagery(m,op.imageOptions);event.kind='image-start';break;}
 case 'image-control':controlImagery(m,op.command);break;
 case 'goal':{m.language=null;m.observed=observeWorld(m.world);event=startGoalNetwork(m,op.goals,op.config);break;}
 case 'disturb':{const effects=sc(m.world.effects),version=m.world.version;m.world=validateWorld(op.world);m.world.effects=effects;m.world.version=version+1;m.observed=observeWorld(m.world);event.kind='external-observation';break;}
 case 'start':{m.language=null;
  need(!m.pending,'Есть неподтверждённое действие. Нужна доставка или явный сброс');
  need(typeof op.query==='string'&&op.query.length&&Array.from(op.query).length<=160,'Запрос: 1–160 символов');
  m.intent=null;m.imagery=null;const query=op.query;let result;try{result=inspect(m,query);}catch(e){m.status='unknown';m.phase='idle';m.entry=null;m.plan=null;m.detour=null;m.message=e.message;m.query=query;m.heldGoal=false;m.revision++;event.message=m.message;return event;}
  m.attempt++;m.tick=0;m.query=query;m.heldGoal=true;m.observed=observeWorld(m.world);m.context=m.memory.root;m.entry=result.command.first;m.selectedCommand=sc(result.command);
  m.recognitionLeft=result.recognized;m.occ=Array.from(query,(value,i)=>({id:`q${m.attempt}:${i}`,value,next:i+1<Array.from(query).length?`q${m.attempt}:${i+1}`:null,held:true,a:0,consumedBy:null}));
  m.phase='recognize';m.status='running';m.plan=null;m.detour=null;m.blockedTransitions=[];m.recoveries=0;m.activation={};m.trace={};m.refractory={};m.goalActivation={};clearTransients(m);m.message='Запрос удерживается; обучение только по наблюдённым результатам.';break;}
 case 'tick':event=tick(m);break;
 case 'deliver':need(m.pending?.receipt,'Нет квитанции среды');event=deliver(m,m.pending.receipt);break;
 case 'receipt':event=deliver(m,sc(op.receipt));break;
 case 'world':need(!m.pending,'Нельзя менять весь стенд при ожидающем действии');m.world=validateWorld(op.world);m.observed=observeWorld(m.world);break;
 case 'perturb':{ // Deliberately allow sensory changes between proposal and application.
  const icons=m.world.surfaces[m.world.surface].icons,o=icons.find(o=>o.id===op.id);need(o,'Нет объекта');
  if(op.hidden!==undefined){need(typeof op.hidden==='boolean','Скрытие: да/нет');o.hidden=op.hidden;}
  if(op.x!==undefined){need(Number.isFinite(op.x)&&op.x>=50&&op.x<=950,'Координата X');o.x=op.x;}
  if(op.y!==undefined){need(Number.isFinite(op.y)&&op.y>=50&&op.y<=550,'Координата Y');o.y=op.y;}
  m.world.version++;if(!m.pending)m.observed=observeWorld(m.world);break;}
 case 'reset':clearTransients(m);m.language=null;m.intent=null;m.imagery=null;m.pending=null;m.heldGoal=false;m.plan=null;m.detour=null;m.entry=null;m.occ=[];m.status='idle';m.tick=0;m.message='Попытка отменена явно; память сохранена.';break;
 case 'config':need(!m.pending,'Ожидается подтверждение');for(const [k,v]of Object.entries(op.values||{})){
  need(Object.hasOwn(STATE_DEFAULTS,k),'Неизвестная настройка');
  if(k==='ackMode')need(['auto','manual','delay','drop','reject'].includes(v),'Режим подтверждения');
  else need(Number.isFinite(v)&&v>=0&&v<=(['timeout','ackDelay'].includes(k)?200:k==='refractory'?10:1),'Настройка вне диапазона');
  if(['timeout','ackDelay','refractory'].includes(k))need(Number.isInteger(v),'Нужно целое количество тактов');
  if(k==='timeout')need(v>=2,'Тайм-аут не менее 2 тактов');
  m.config[k]=v;if(m.intent&&m.phase==='intent'){const key=k==='planThreshold'?'routeThreshold':k;if(Object.hasOwn(m.intent.config,key))m.intent.config[key]=v;}}break;
 case 'weight':{need(!m.pending,'Ожидается действие');const e=m.memory.edges.find(e=>e.id===op.id);need(e&&Number.isFinite(op.value)&&op.value>=0&&op.value<=1,'Вес связи');e.weight=op.value;break;}
 default:throw Error('Неизвестная операция');
 }
 m.revision++;event.tick=m.tick;event.message=event.message||m.message;return event;
}
export class StateEngine{
 constructor(){this.model=fresh();this.operations=[];this.events=[];}
 preview(op={kind:'tick'}){need(this.operations.length<6000,'Лимит 6000 событий');const next=sc(this.model),event=apply(next,sc(op));return {base:this.model.revision,next,event,op:sc(op)};}
 commit(p){need(p.base===this.model.revision,'Предварительный расчёт устарел');this.model=sc(p.next);this.operations.push(sc(p.op));this.events.push(sc(p.event));return p.event;}
 perform(op){return this.commit(this.preview(op));}
 export(){return {schema:STATE_VERSION,operations:sc(this.operations)};}
 static import(raw){need(raw?.schema===STATE_VERSION&&Array.isArray(raw.operations)&&raw.operations.length<=6000,'Нужен States v2; прежний файл сохраните отдельно и повторите обучение');const e=new StateEngine();for(const op of raw.operations)e.perform(op);return e;}
 at(i){const e=new StateEngine();for(const op of this.operations.slice(0,i))e.perform(op);return e;}
}
export function teachExamples(engine=new StateEngine(),kind='states'){
 const w=defaultWorld();if(kind==='states'){
  engine.perform({kind:'teach',record:demonstration('открой окно',w,[...iconDemonstrationActions(w,'A'),{kind:'enter',object:'A'}])});
  w.surface='window';engine.perform({kind:'teach',record:demonstration('закрой окно',w,iconDemonstrationActions(w,'X'))});
 }else{
  // Earlier, independent keyboard input: not an expense command and not the target order 2345.
  const prior=defaultWorld();prior.surface='calculator';prior.focus='FIELD';
  engine.perform({kind:'expose',record:demonstration('Прежний ввод символов',prior,Array.from('5432',value=>({kind:'key',value})))});
  engine.perform({kind:'teach',record:demonstration('добавь траты 1700',w,[...iconDemonstrationActions(w,'CALC'),...Array.from('1700',value=>({kind:'key',value}))])});}
 return engine;
}
export function prepareCase(number){const e=teachExamples(new StateEngine(),number===4?'expense':'states'),w=defaultWorld();
 e.perform({kind:'config',values:{plasticity:0}});
 if(number===2||number===3)w.surface='window';e.perform({kind:'world',world:w});
 return {engine:e,query:number===2?'закрой окно':number===4?'добавь траты 2345':'открой окно'};
}
export function runCase(number){const {engine:e,query}=prepareCase(number),memory=JSON.stringify(persistentGraph(e.model.memory));e.perform({kind:'start',query});
 for(let i=0;i<1200&&!['complete','blocked','failed','unknown','ambiguous','timeout','limit'].includes(e.model.status);i++)e.perform({kind:'tick'});
 const actions=e.model.world.effects.filter(r=>r.ok).map(r=>r.action),changes=e.model.world.effects.filter(r=>observationKey(r.before)!==observationKey(r.after));
 const pass=e.model.status==='complete'&&JSON.stringify(persistentGraph(e.model.memory))===memory&&(number===4?e.model.world.output==='2345':e.model.world.surface===(number===2?'desk':'window'))&&(number!==3||e.events.some(ev=>ev.kind==='route'));
 return {number,pass,status:e.model.status,query,actions,changes:changes.length,output:e.model.world.output,engine:e};
}
