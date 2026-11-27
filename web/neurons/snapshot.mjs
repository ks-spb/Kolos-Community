/** Read-only projection of the existing States engine. Never makes a decision.
 * Recorded event flows and reconstructed equation terms are explicitly distinct.
 * Only logged transfers animate; order/experienced edges remain structure.
 */
import {sensoryFeatures} from '../states/environment.mjs';
const nvCopy=x=>structuredClone(x), nvNum=x=>Number.isFinite(x)?x:0;
const nvKey=x=>JSON.stringify(x);
export const NEURON_SCHEMA='kolos-neuron-frame/1';
export function neuronFrame(m, event={}, previous=null) {
 const mem=m.memory||{nodes:[],edges:[]}, image=m.imagery, intent=m.intent;
 const cfg=intent?.config||m.config||{}, before=previous||{};
 const imageBefore=new Map((before.imagery?.nodes||[]).map(n=>[n.id,n]));
 const known=new Map(mem.nodes.map(n=>[n.id,n]));
 const candidates=event.candidates||[], candidateMap=new Map(candidates.map(c=>[c.id,c]));
 const frame={schema:NEURON_SCHEMA,tick:m.tick||0,revision:m.revision||0,attempt:m.attempt||0,
  event:nvCopy(event),status:m.status,phase:m.phase,message:event.message||m.message||'',query:m.query||'',
  heldGoal:!!m.heldGoal,mode:image?.mode||'',ready:image?.ready??null,match:image?.match??null,
  gap:image?.gap??null,pending:m.pending?{id:m.pending.id,action:nvCopy(m.pending.action),source:m.pending.source||null,applied:!!m.pending.applied}:null,
  observed:nvCopy(m.observed||{}),world:m.world?{surface:m.world.surface,output:m.world.output,
    icons:(m.world.surfaces?.[m.world.surface]?.icons||[]).filter(n=>!n.hidden).map(n=>({id:n.id,label:n.label||n.id,x:n.x,y:n.y})),
    effects:m.world.effects?.length||0}:null,config:nvCopy(cfg),nodes:[],edges:[],candidates:nvCopy(candidates)};
 const map=new Map();
 function node(n){if(map.has(n.id)){Object.assign(map.get(n.id),n);return map.get(n.id);}
  const v={a:null,I:null,S:null,C:null,threshold:null,T:0,R:0,held:null,current:false,winner:false,synthetic:false,...n};
  map.set(n.id,v);frame.nodes.push(v);return v;}
 function edge(e){frame.edges.push({weight:null,flow:null,term:null,provenance:'structure',...e});}
 const visibleKey=m.observed?.features?nvKey(sensoryFeatures(m.observed.features)):null;
 const current=mem.nodes.find(n=>n.kind==='state'&&n.key===visibleKey)?.id;
 for(const n of mem.nodes){
  const c=candidateMap.get(n.id),a=Object.hasOwn(m.goalActivation||{},n.id)?m.goalActivation[n.id]:(m.activation?.[n.id]??null);
  const old=Object.hasOwn(before.goalActivation||{},n.id)?before.goalActivation[n.id]:(before.activation?.[n.id]??null);
  node({id:n.id,label:n.label||n.value||n.id,kind:n.kind,group:['state','transition'].includes(n.kind)?'world':n.kind==='step'?'actions':['symbol','motor'].includes(n.kind)?'input':'memory',
   a,S:n.sensory??null,oldA:old,C:c?.a??null,threshold:c?.threshold??null,allowed:c?.allowed??null,reason:c?.reason||'',current:current===n.id,winner:event.winner===n.id,
   inhibition:c?.inhibition??n.inhibition??0,eligibility:n.eligibility??0,
   T:nvNum(m.trace?.[n.id]),R:nvNum(m.refractory?.[n.id]),features:n.features||null,action:n.action||null,
   stored:nvCopy(n),calculation:c?{input:c.input,history:c.history,inhibition:c.inhibition}:null});
 }
 for(const n of image?.nodes||[]){
  const old=imageBefore.get(n.id);
  node({id:n.id,label:n.label,kind:n.kind,group:n.kind==='state'?'world':'image',I:n.I,S:n.S,oldI:previous?(old?.I??0):null,oldS:previous?(old?.S??0):null,
   target:n.target,present:n.present,threshold:image.config.threshold,index:n.index??null,memoryRef:n.memoryRef,
   imageDecay:image.config.decay,internalInput:n.target&&image.drive?image.config.internalGain:0,sensoryInput:n.present?image.config.sensoryGain:0,
   stored:nvCopy(n)});
 }
 if(image){
  node({id:'view:internal',label:image.drive?'Поддержка образа':'Поддержка снята',kind:'source',group:'image',a:image.drive?image.config.internalGain:0,synthetic:true});
  node({id:'view:external',label:'Наблюдение среды',kind:'source',group:'image',a:image.evidence?image.config.sensoryGain:0,synthetic:true});
  const updated=!!previous&&['intent'].includes(m.phase)&&m.tick===before.tick+1&&m.attempt===before.attempt;
  for(const n of image.nodes){
   if(n.target)edge({id:'view:I:'+n.id,from:'view:internal',to:n.id,kind:'internal-input',weight:1-image.config.decay,
    flow:updated&&image.drive?image.config.internalGain*(1-image.config.decay):null,channel:'I',provenance:'equation',note:'Прямой внутренний вход I; коэффициент (1 − decay), не выученный синапс.'});
   if(n.present||n.S>0)edge({id:'view:S:'+n.id,from:'view:external',to:n.id,kind:'sensory-input',weight:1-image.config.decay,
    flow:updated&&n.present?image.config.sensoryGain*(1-image.config.decay):null,channel:'S',provenance:'equation',note:'Сенсорный вход S из принятого наблюдения. Затухающий след без present не доказывает результат.'});
  }
  for(const [i,e] of image.edges.entries())edge({...nvCopy(e),id:'view:order:'+i,provenance:'structure',note:'Связь порядка из кодировщика образа. Через неё ядро не вычисляет передачу I/S; частицы не рисуются.'});
 }
 for(const [i,g] of (intent?.goals||[]).entries()){
  node({id:g.id,label:g.kind==='field'?'Цель: '+g.value:'Цель '+(i+1),kind:'goal',group:'goals',a:g.a,oldA:before.intent?.goals?.find(x=>x.id===g.id)?.a??0,
   held:g.held,winner:event.winner===g.id,current:intent.active===g.id,threshold:cfg.threshold,stored:nvCopy(g)});
  for(const id of g.targets)edge({id:'view:demand:'+g.id+':'+id,from:g.id,to:id,kind:'goal-drive',weight:null,
   flow:['spread','route','imagery-wave'].includes(event.kind)&&intent.active===g.id?(image?image.ready:1):null,
   provenance:'equation',note:image?'Целевому состоянию присваивается min(I компонентов образа). Это зависимость расчёта, не выученная связь.':'Поддерживаемая цель возбуждает целевое состояние.'});
  if(g.previous)edge({id:'view:goal-inhibition:'+g.id,from:g.previous,to:g.id,kind:'inhibition',weight:1.5*(cfg.goalInhibition??1),
   flow:intent.goals.find(x=>x.id===g.previous)?.held&&m.tick!==before.tick?1.5*(cfg.goalInhibition??1):null,provenance:'equation',note:'Торможение следующей цели удерживаемым предшественником.'});
 }
 for(const [id,a] of Object.entries(intent?.error||{})){
  node({id:'view:error:'+id,label:'Ошибка '+id,kind:'error',group:'world',a,oldA:before.intent?.error?.[id]??0,synthetic:true});
  edge({id:'view:error-edge:'+id,from:'view:error:'+id,to:id,kind:'inhibition',weight:cfg.errorGain,
   flow:candidateMap.get(id)?.inhibition||null,provenance:'equation',note:'Тормозящий след ошибки предсказания.'});
 }
 for(const [i,q] of (m.occ||[]).entries()){
  const c=candidateMap.get(q.id);
  node({id:q.id,label:`${i+1}: ${q.value===' '?'␣':q.value}`,kind:'occurrence',group:'input',index:i,a:q.a,oldA:before.occ?.find(x=>x.id===q.id)?.a??0,
   held:q.held,consumedBy:q.consumedBy,pending:m.pending?.source===q.id,C:c?.a??null,threshold:c?.threshold??cfg.threshold,allowed:c?.allowed??null,winner:event.winner===q.id,
   calculation:c?{input:c.input,history:c.history,inhibition:c.inhibition}:null,stored:nvCopy(q)});
  const symbol=mem.nodes.find(n=>n.kind==='symbol'&&n.value===q.value),motor=mem.edges.find(e=>e.kind==='corresponds'&&e.from===symbol?.id);
  if(motor)edge({id:'view:bind:'+q.id,from:motor.to,to:q.id,kind:'motor-drive',weight:motor.weight,flow:c?nvNum(c.input)+nvNum(c.history):null,
   provenance:'equation',note:'Вклад известного моторного соответствия: input + history из кандидата. Исполняется временное вхождение, не весь старый пример.'});
  const prior=(m.occ||[]).find(p=>p.next===q.id);
  if(prior)edge({id:'view:inhibit:'+q.id,from:prior.id,to:q.id,kind:'inhibition',weight:m.config?.inhibition,
   flow:c?.inhibition||null,provenance:'equation',note:'Предыдущее вхождение тормозит следующее до подтверждения.'});
 }
 for(const e of mem.edges){
  const flows=(event.flows||[]).filter(f=>f.edge===e.id);
  const c=candidateMap.get(e.to);
  let flow=flows.length?flows.reduce((s,f)=>s+nvNum(f.value),0):null,provenance=flows.length?'recorded':'structure',note='Связь памяти. Нет зарегистрированной передачи на этом такте.';
  if(flows.length)note='Передача из журнала движка. Для обратной волны это значение ДО нормировки и затухания получателя.';
  if(flow===null&&c&&['next','starts'].includes(e.kind)&&c.history!==undefined){flow=c.history;provenance='equation';note='Вклад веса контекстной связи в candidate.history; ядро не считает его как A источника × вес.';}
  const incoming=mem.edges.filter(x=>x.kind==='backward'&&x.to===e.to).length;
  const explicitTerms=flows.length&&flows.every(f=>Number.isFinite(f.term));
  const term=explicitTerms?flows.reduce((s,f)=>s+f.term,0):flow!==null&&e.kind==='backward'?flow*(1-(cfg.decay??.5))/Math.max(1,incoming):null;
  if(flows.some(f=>f.aggregation==='competitive-alternatives'))note='Взвешенный вход до конкуренции альтернатив. Полезный вклад после конкуренции и затухания указан отдельно; слабая ветвь может дать ноль.';
  edge({...nvCopy(e),flow,term,provenance,note});
 }
 // Language states contain path-specific charges. Do not call them activation
 // of static glyph vertices; path candidates are shown as separate occurrences.
 for(const n of m.languageMemory?.nodes||[])node({id:n.id,label:n.label||n.char||n.kind,kind:n.kind,group:'language',a:null,T:m.language?.trace?.[n.id]??0,stored:nvCopy(n)});
 for(const e of m.languageMemory?.edges||[])edge({...nvCopy(e),provenance:'structure',note:'Выученная языковая связь; активации принадлежат кандидатам пути, а не ID статической вершины.'});
 if(m.phase==='language'||String(event.kind).startsWith('language-')){
  for(const c of candidates){
   if(!c.edge)continue;
   node({id:c.id,label:c.label||'Чтение',kind:'language-candidate',group:'language',a:c.a,C:c.a,threshold:c.threshold,winner:event.winner===c.id,
    stored:nvCopy(c),calculation:{input:c.input,history:c.history,inhibition:c.inhibition}});
   const e=(m.languageMemory?.edges||[]).find(e=>e.id===c.edge);
   if(e)edge({id:'view:language:'+c.id,from:e.from,to:c.id,kind:'language-charge',weight:e.weight,
    flow:c.a,provenance:'equation',note:'Визуальная ветвь кандидата пути. Число — его накопленная активация, НЕ синаптический ток.'});
  }
 }
 frame.edges=frame.edges.filter(e=>map.has(e.from)&&map.has(e.to));
 frame.nodes.forEach(n=>{n.energy=Math.max(nvNum(n.a),nvNum(n.C),nvNum(n.I),nvNum(n.S));});
 return frame;
}
/** Group ONLY same directed endpoints AND kind/provenance. Reverse links stay separate. */
export function neuronEdgeGroups(edges){
 const groups=new Map();
 for(const e of edges){const k=nvKey([e.from,e.to,e.kind,e.provenance]);if(!groups.has(k))groups.set(k,{...e,ids:[],members:[],flow:null});
  const g=groups.get(k);g.ids.push(e.id);g.members.push(e);if(e.flow!==null)g.flow=(g.flow??0)+e.flow;}
 return [...groups.values()];
}
