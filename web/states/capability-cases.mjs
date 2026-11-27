import {persistentGraph} from './environment.mjs';
/** Acceptance fixtures and interventions. NOT imported by inference modules.
 * Expected answers are checked only by the harness, never supplied as actions.
 */
import {StateEngine,prepareCase,runCase,teachExamples} from './core.mjs';
import {defaultWorld,observeWorld,demonstration,iconDemonstrationActions} from './environment.mjs';
export const CAPABILITY_NAMES=['Рабочий стол → окно','Окно → рабочий стол','Составной обход','Новая последовательность цифр',
 'Два результата по очереди','Конкуренция маршрутов','Неожиданное препятствие','Три новых перехода подряд','Цель: значение поля','Ошибка предсказания'];
const cc=x=>structuredClone(x);
const ccstop=new Set(['complete','blocked','failed','unknown','ambiguous','timeout','limit']);
function teachAt(e,w,surface,query,id,enter=false){
 const world=cc(w);world.surface=surface;world.selected='';world.focus=world.surfaces[surface].field||'';world.output='';
 e.perform({kind:'teach',record:demonstration(query,world,[...iconDemonstrationActions(world,id),...(enter?[{kind:'enter',object:id}]:[])])});
}
function stateGoal(w,surface){const world=cc(w);world.surface=surface;world.selected='';world.focus=world.surfaces[surface].field||'';return {kind:'state',features:observeWorld(world).features};}
function routeWorld(){return {surface:'junction',version:0,selected:'',focus:'',output:'',cursor:{x:500,y:300},effects:[],surfaces:{
 junction:{label:'Развилка',field:null,icons:[{id:'FAST',label:'Прямой путь',x:240,y:170,click:'target'},{id:'VIA',label:'Другой путь',x:700,y:170,click:'middle'}]},
 middle:{label:'Промежуточное состояние',field:null,icons:[{id:'NEXT',label:'Далее',x:480,y:160,click:'target'}]},
 target:{label:'Целевое состояние',field:null,icons:[{id:'TARGET',label:'Цель',x:500,y:300}]},
 trap:{label:'Неожиданный исход',field:null,icons:[{id:'RETURN',label:'Вернуться',x:450,y:170,click:'junction'}]}
 }};}
function routeEvidence(error=false){
 const e=new StateEngine(),w=routeWorld();
 teachAt(e,w,'junction','первый отдельный показ','FAST');teachAt(e,w,'junction','второй отдельный показ','VIA');teachAt(e,w,'middle','третий отдельный показ','NEXT');
 if(error)teachAt(e,w,'trap','независимый возврат','RETURN');
 return {e,w};
}

export function prepareCapability(number){
 if(number<=4){const old=prepareCase(number);return {number,engine:old.engine,operation:{kind:'start',query:old.query},query:old.query,note:CAPABILITY_NAMES[number-1]};}
 let e,w,goals,note;
 if([5,7,9].includes(number)){
  e=teachExamples();teachExamples(e,'expense');w=defaultWorld();
  if(number===5){goals=[stateGoal(w,'window'),{kind:'field',focus:'FIELD',value:'3521'}];note='Два желаемых результата заданы по порядку. Связи торможения между целями, а не склеенный список действий.';}
  if(number===7){goals=[{kind:'field',focus:'FIELD',value:'2345'}];note='После открытия CALC стенд неожиданно показывает знакомое мешающее окно. Цель не меняется.';}
  if(number===9){w.surface='window';goals=[{kind:'field',focus:'FIELD',value:'2345'}];note='Задан только результат: FIELD = 2345. Текст команды не распознаётся; будущие клики не задаются.';}
 }
 if([6,10].includes(number)){
  ({e,w}=routeEvidence(number===10));goals=[stateGoal(w,'target')];
  if(number===6){
   const transition=e.model.memory.nodes.find(n=>n.kind==='transition'&&n.label==='CLICK FAST');
   const edge=e.model.memory.edges.find(x=>x.kind==='backward'&&x.to===transition.id);
   e.perform({kind:'weight',id:edge.id,value:.35});
   note='Прямой путь имеет слабую связь 0,35. Более сильный обход должен выиграть по активации.';
  }else note='FAST был изучен как переход к цели. На контрольном клике он даёт другой наблюдаемый результат; ошибка временно тормозит этот переход.';
 }
 if(number===8){
  e=new StateEngine();w={surface:'L0',version:0,selected:'',focus:'',output:'',cursor:{x:500,y:300},effects:[],surfaces:{}};
  for(let i=0;i<4;i++)w.surfaces['L'+i]={label:'Уровень '+i,field:null,icons:[{id:i===3?'DONE':'GO'+i,label:i===3?'Результат':'Переход '+i,x:300+i*100,y:150,...(i<3?{click:'L'+(i+1)}:{})}]};
  for(let i=0;i<3;i++)teachAt(e,w,'L'+i,'отдельный переход '+i,'GO'+i);
  goals=[stateGoal(w,'L3')];note='Три самостоятельные демонстрации. Маршрут L0 → L1 → L2 → L3 ни разу не показывался целиком.';
 }
 if(!e)throw Error('Неизвестный тест');
 e.perform({kind:'config',values:{plasticity:0}});
 e.perform({kind:'world',world:w});
 return {number,engine:e,operation:{kind:'goal',goals},query:goals.map(g=>g.kind==='field'?g.focus+' = '+g.value:'Наблюдаемое состояние').join(' → '),note};
}

/** Physical perturbations are deliberately injected by the test environment. */
export function capabilityIntervention(number,engine,state){
 if(state.injected)return false;
 const m=engine.model,last=engine.events.at(-1);
 if(number===7&&last?.kind==='ack'&&last.receipt?.action.kind==='click'&&last.receipt.action.object==='CALC'){
  const w=cc(m.world);w.surface='window';w.selected='';w.focus='';w.output='';engine.perform({kind:'disturb',world:w});state.injected=true;return true;
 }
 if(number===10&&m.pending?.action.kind==='click'&&m.pending.action.object==='FAST'&&!m.pending.applied){
  const w=cc(m.world);w.surfaces.junction.icons.find(i=>i.id==='FAST').click='trap';engine.perform({kind:'disturb',world:w});state.injected=true;return true;
 }
 return false;
}

export function assessCapability(number,e,frozen,intervention={}){
 const m=e.model,actions=m.world.effects.filter(r=>r.ok).map(r=>r.action),clicks=actions.filter(a=>a.kind==='click').map(a=>a.object);
 let pass=m.status==='complete'&&JSON.stringify(persistentGraph(m.memory))===frozen;
 const b=m.intent;
 if(number===5)pass=pass&&m.world.output==='3521'&&b.goalHistory.length===2&&b.goalHistory[0].tick<b.goalHistory[1].tick&&JSON.stringify(clicks)===JSON.stringify(['A','X','CALC']);
 if(number===6)pass=pass&&JSON.stringify(clicks)===JSON.stringify(['VIA','NEXT']);
 if(number===7)pass=pass&&intervention.injected&&m.world.output==='2345'&&JSON.stringify(clicks)===JSON.stringify(['CALC','X','CALC']);
 if(number===8)pass=pass&&JSON.stringify(clicks)===JSON.stringify(['GO0','GO1','GO2']);
 if(number===9)pass=pass&&m.world.output==='2345'&&JSON.stringify(clicks)===JSON.stringify(['X','CALC']);
 if(number===10)pass=pass&&intervention.injected&&b.errorHistory.length===1&&JSON.stringify(clicks)===JSON.stringify(['FAST','RETURN','VIA','NEXT']);
 if(number>=5)pass=pass&&e.events.some(ev=>ev.kind==='spread'&&ev.flows.length)&&b.goals.every(g=>!g.held);
 return {number,pass,status:m.status,actions,clicks,output:m.world.output,ticks:m.tick,routeCount:e.events.filter(e=>e.kind==='route').length,
  predictions:b?.predictions.length||0,errors:b?.errorHistory.length||0,memoryUnchanged:JSON.stringify(persistentGraph(m.memory))===frozen,engine:e};
}
export function runCapability(number){
 if(number<=4)return {...runCase(number),ticks:undefined};
 const p=prepareCapability(number),e=p.engine,frozen=JSON.stringify(persistentGraph(e.model.memory)),intervention={};e.perform(p.operation);
 for(let i=0;i<1700&&!ccstop.has(e.model.status);i++){capabilityIntervention(number,e,intervention);e.perform({kind:'tick'});}
 return assessCapability(number,e,frozen,intervention);
}
