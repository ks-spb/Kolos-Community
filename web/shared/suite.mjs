import {persistentGraph} from '../states/environment.mjs';
/** One engine, one persistent graph, twelve capability probes.
 * This is TEST INFRASTRUCTURE. The engine sees only observations and goals/text.
 * Scenario IDs/expected actions are not passed into inference. In between probes
 * only working state and external starting conditions are reset, never memory.
 */
import {StateEngine} from '../states/core.mjs';
import {SHARED_FIXTURE} from './fixture.mjs';
import {demonstration,iconDemonstrationActions,observeWorld,observationKey} from '../states/environment.mjs';
export const SHARED_SCHEMA='kolos-shared-memory/1';
export const SHARED_NAMES=['Открыть окно','Закрыть окно','Найти обход','Новые цифры','Две цели','Слабый путь','Внешняя помеха','Три перехода','Цель-результат','Ошибка прогноза','Образ I / S','Язык → образ'];
export const SHARED_STOP=new Set(['complete','blocked','failed','unknown','ambiguous','timeout','limit','idle']);
const shClone=x=>structuredClone(x),shNeed=(v,s)=>{if(!v)throw Error(s);};
export function sharedWorld(surface='desk'){
 const w=shClone(SHARED_FIXTURE.world);shNeed(w.surfaces[surface],'Неизвестное начальное состояние');
 w.surface=surface;w.focus=w.surfaces[surface].field||'';return w;
}
export const sharedStateGoal=surface=>({kind:'state',features:observeWorld(sharedWorld(surface)).features});
export function sharedPersistent(model){
 return {memory:persistentGraph(model.memory),languageMemory:model.languageMemory||null,commands:model.commands,
  lessons:model.lessons,exposures:model.exposures,config:model.config};
}
export function sharedSignature(model){return JSON.stringify(sharedPersistent(model));}
/** UI checksum only. Tests compare the whole serialization and reports use SHA256. */
export function sharedStamp(model){let h=2166136261;for(const ch of sharedSignature(model)){h^=ch.charCodeAt(0);h=Math.imul(h,16777619);}return (h>>>0).toString(16).padStart(8,'0');}
export function buildShared({competition=1,episodeOrder=null}={}){
 const e=new StateEngine(),ops=[],perform=op=>{e.perform(op);ops.push(shClone(op));};
 perform({kind:'config',values:{stateCompetition:competition,plasticity:0}});
 perform({kind:'expose',record:demonstration('Прежний ввод символов',sharedWorld('calculator'),Array.from(SHARED_FIXTURE.exposure,value=>({kind:'key',value})))});
 const order=episodeOrder||SHARED_FIXTURE.episodes.map((_,i)=>i);
 shNeed(order.length===SHARED_FIXTURE.episodes.length&&new Set(order).size===order.length&&order.every(i=>Number.isInteger(i)&&i>=0&&i<order.length),'Нужна перестановка всех показов');
 for(const i of order){
  const ep=SHARED_FIXTURE.episodes[i],w=sharedWorld(ep.surface);
  const actions=[...iconDemonstrationActions(w,ep.object),...(ep.enter?[{kind:'enter',object:ep.object}]:[]),...Array.from(ep.keys||'',value=>({kind:'key',value}))];
  perform({kind:'teach',record:demonstration(ep.query,w,actions)});
  if(ep.weight!==undefined){
   const state=e.model.memory.nodes.find(n=>n.kind==='state'&&n.key===observationKey(observeWorld(w)));
   const transition=e.model.memory.nodes.find(n=>n.kind==='transition'&&n.from===state.id&&n.label==='CLICK '+ep.object);
   const edge=e.model.memory.edges.find(ed=>ed.kind==='backward'&&ed.to===transition.id);
   shNeed(edge,'В опыте отсутствует подтверждённый переход');perform({kind:'weight',id:edge.id,value:ep.weight});
  }
 }
 for(const p of SHARED_FIXTURE.language)perform({kind:'language-teach',...p});
 e.perform({kind:'world',world:sharedWorld()});e.perform({kind:'reset'});
 return {engine:e,learning:ops};
}
export function sharedProbe(number){
 shNeed(Number.isInteger(number)&&number>=1&&number<=12,'Номер опыта 1–12');
 const surface=number===2||number===3||number===9||number>=11?'window':number===6?'old':number===10?'new':number===8?'L0':'desk';
 let operation;
 if(number<=4)operation={kind:'start',query:number===2?'закрой окно':number===4?'добавь траты 2345':'открой окно'};
 else if(number===12)operation={kind:'language-start',phrase:'я хочу увидеть 1354 в поле'};
 else operation={kind:number===11?'imagine':'goal',goals:number===5?[sharedStateGoal('window'),{kind:'field',focus:'FIELD',value:'3521'}]:[number===6||number===10?sharedStateGoal('target'):number===8?sharedStateGoal('L3'):{kind:'field',focus:'FIELD',value:'2345'}]};
 return {number,surface,operation};
}
const shExpected={1:['A'],2:['X'],3:['X','A'],4:['CALC'],5:['A','X','CALC'],6:['VIA','NEXT'],7:['CALC','X','CALC'],8:['GO0','GO1','GO2'],9:['X','CALC'],10:['FAST','RETURN','VIA','NEXT'],11:['X','CALC'],12:['X','CALC']};
export class SharedSession{
 constructor(options={}){
  const b=options.database?SharedSession.decode(options.database):buildShared(options);
  this.engine=b.engine;this.learning=b.learning;this.signature=sharedSignature(this.engine.model);this.stamp=sharedStamp(this.engine.model);
  this.results=[];this.active=null;this.onFrame=null;this.instanceId='shared-'+Math.random().toString(36).slice(2);this.totalTicks=0;
 }
 static decode(raw){
  shNeed(raw?.schema===SHARED_SCHEMA&&Array.isArray(raw.learning)&&raw.learning.length<=200,'Нужен файл общей памяти');
  shNeed(JSON.stringify(raw).length<=4e6,'Общая память слишком велика');
  const e=new StateEngine();
  for(const op of raw.learning){shNeed(['teach','expose','config','weight','language-teach','language-weight'].includes(op?.kind),'В импортируемой базе запрещены запускающие операции');e.perform(shClone(op));}
  shNeed(e.model.lessons.length>0,'Нет опыта среды');e.perform({kind:'world',world:sharedWorld()});e.perform({kind:'reset'});
  if(raw.signature!==undefined)shNeed(sharedSignature(e.model)===raw.signature,'Содержимое базы не совпало с контрольным снимком');
  return {engine:e,learning:shClone(raw.learning)};
 }
 export(){return {schema:SHARED_SCHEMA,learning:shClone(this.learning),signature:this.signature};}
 verifyMemory(){shNeed(sharedSignature(this.engine.model)===this.signature,'Память или общие настройки изменились во время выполнения!');return true;}
 perform(op){const before=this.onFrame?shClone(this.engine.model):null;const event=this.engine.perform(op);if(this.onFrame)this.onFrame(this.engine.model,event,before,this.active);return event;}
 begin(number){
  shNeed(!this.engine.model.pending,'Есть неподтверждённое действие. Сначала явно отмените текущую попытку.');this.verifyMemory();
  const p=sharedProbe(number);
  this.perform({kind:'reset'});
  // Bounded event/log storage only; never clears the learned graph or weights.
  this.engine.operations=[];this.engine.events=[];
  this.perform({kind:'world',world:sharedWorld(p.surface)});
  this.active={...p,startEvent:this.engine.events.length,startSignature:this.signature,stage:number===11?'imagine':number===12?'language':'execute',count:0,
   injected:false,dry:false,faded:false,ids:[],finished:false,initialWorld:JSON.stringify(this.engine.model.world),memoryStamp:this.stamp};
  this.perform(p.operation);return this.active;
 }
 abort(){this.perform({kind:'reset'});if(this.active&&!this.active.finished){this.active.finished=true;this.active.aborted=true;}this.verifyMemory();}
 step(){
  const a=this.active;shNeed(a&&!a.finished,'Выберите незавершённый опыт');const e=this.engine,m=e.model;
  if(SHARED_STOP.has(m.status))return this.finish();
  // These perturbations belong to the environment and are visible in the trace.
  // They do not change an edge, configuration, command or desired outcome.
  const last=e.events.at(-1);
  if(a.number===7&&!a.injected&&last?.kind==='ack'&&last.receipt?.action.kind==='click'&&last.receipt.action.object==='CALC'){
   const w=shClone(m.world);w.surface='window';w.selected='';w.focus='';w.output='';a.injected=true;
   return this.perform({kind:'disturb',world:w});
  }
  if(a.number===10&&!a.injected&&m.pending?.action.kind==='click'&&m.pending.action.object==='FAST'&&!m.pending.applied){
   const w=shClone(m.world);w.surfaces.new.icons.find(i=>i.id==='FAST').click='trap';a.injected=true;
   return this.perform({kind:'disturb',world:w});
  }
  if(a.stage==='imagine'&&a.count>=8){
   a.dry=JSON.stringify(m.world)===a.initialWorld&&!m.pending&&m.imagery.ready>.99&&m.imagery.match===0;
   a.ids=shClone(m.imagery.patterns[m.intent.goals[0].id]);a.count=0;
   if(a.number===11){a.stage='fade';return this.perform({kind:'image-control',command:'rest'});}
   a.stage='execute';return this.perform({kind:'image-control',command:'act'});
  }
  if(a.stage==='fade'&&a.count>=5){a.faded=m.imagery.ready<.04&&m.world.effects.length===0;a.stage='execute';return this.perform({kind:'image-control',command:'act'});}
  const event=this.perform({kind:'tick'});this.totalTicks++;a.count++;
  if(a.stage==='language'&&event.kind==='language-image'){a.stage='imagine';a.count=0;}
  if(SHARED_STOP.has(e.model.status))this.finish();return event;
 }
 finish(){
  const a=this.active;if(!a||a.finished)return a?.result;
  const m=this.engine.model,events=this.engine.events.slice(a.startEvent),actions=m.world.effects.filter(r=>r.ok).map(r=>r.action),clicks=actions.filter(a=>a.kind==='click').map(a=>a.object),keys=actions.filter(a=>a.kind==='key').map(a=>a.value).join('');
  const unchanged=sharedSignature(m)===a.startSignature;
  const checks={completed:m.status==='complete',memoryUnchanged:unchanged,settingsUnchanged:m.config.stateCompetition===JSON.parse(this.signature).config.stateCompetition,
   allKnowledgeAvailable:m.lessons.length===JSON.parse(this.signature).lessons.length,
   expectedActions:JSON.stringify(clicks)===JSON.stringify(shExpected[a.number]),goalReleased:!m.heldGoal,decay:m.config.decay>0&&m.config.decay<1};
  if([1,2,3].includes(a.number))checks.expectedState=m.world.surface===(a.number===2?'desk':'window');
  if([4,5,7,9,11,12].includes(a.number))checks.expectedText=keys=== (a.number===5?'3521':a.number===12?'1354':'2345') && m.world.output===keys;
  if(a.number===3||a.number>=5)checks.activationRoute=events.some(ev=>ev.kind==='route')&&events.some(ev=>ev.flows?.some(f=>f.value>0));
  if(a.number===5)checks.orderedGoals=m.intent.goalHistory.length===2&&m.intent.goalHistory[0].tick<m.intent.goalHistory[1].tick;
  if(a.number===7||a.number===10)checks.externalIntervention=a.injected;
  if(a.number===10)checks.predictionError=m.intent.errorHistory.length===1&&events.some(ev=>ev.kind==='prediction-error');
  if(a.number===11||a.number===12){
   checks.imaginedWithoutEffects=a.dry;checks.externalConfirmation=m.imagery?.confirmations.length===1&&m.imagery.confirmations[0].source==='external';
   checks.sharedContent=a.ids.length>0&&a.ids.every(id=>m.imagery.nodes.some(n=>n.id===id&&n.present&&n.S>=.7));
  }
  if(a.number===11)checks.fadedWithoutEffects=a.faded;
  if(a.number===12)checks.novelLanguage=m.language?.goal?.value==='1354'&&!m.languageMemory.lessons.some(l=>l.phrase.includes('1354'));
  const result={number:a.number,name:SHARED_NAMES[a.number-1],pass:Object.values(checks).every(Boolean),status:m.status,ticks:m.tick,checks,clicks,keys,output:m.world.output,
   memoryBefore:this.stamp,memoryAfter:sharedStamp(m),instance:this.instanceId,nodes:m.memory.nodes.length,edges:m.memory.edges.length,languageNodes:m.languageMemory?.nodes.length||0,
   errors:m.intent?.errorHistory.length||0,routes:events.filter(ev=>ev.kind==='route').map(ev=>ev.winner),message:m.message};
  a.result=result;a.finished=true;this.results.push(shClone(result));return result;
 }
 run(number){this.begin(number);for(let i=0;i<2500&&!this.active.finished;i++)this.step();shNeed(this.active.finished,'Лимит стенда');return this.active.result;}
 runAll(order=Array.from({length:12},(_,i)=>i+1)){return order.map(n=>this.run(n));}
}
/** Cross-family transfer, one attempt, no environment resets in the solution. */
export function runSharedTransfer(session){
 session.verifyMemory();shNeed(!session.engine.model.pending,'Ожидается действие');session.perform({kind:'reset'});session.engine.operations=[];session.engine.events=[];
 session.perform({kind:'world',world:sharedWorld('L0')});
 session.perform({kind:'goal',goals:[sharedStateGoal('L3'),{kind:'field',focus:'FIELD',value:'4512'}]});
 for(let i=0;i<1600&&!SHARED_STOP.has(session.engine.model.status);i++)session.perform({kind:'tick'});
 const m=session.engine.model,clicks=m.world.effects.filter(r=>r.action.kind==='click'&&r.ok).map(r=>r.action.object);
 return {pass:m.status==='complete'&&m.world.output==='4512'&&JSON.stringify(clicks)===JSON.stringify(['GO0','GO1','GO2','HOME','CALC'])&&session.verifyMemory(),
  name:'Уровни → общий рабочий стол → поле',clicks,output:m.world.output,ticks:m.tick,memoryBefore:session.stamp,memoryAfter:sharedStamp(m)};
}
