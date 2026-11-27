import {persistentGraph} from '../states/environment.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareCapability,runCapability,capabilityIntervention} from '../states/capability-cases.mjs';
import {StateEngine} from '../states/core.mjs';
import {defaultWorld,demonstration,iconDemonstrationActions} from '../states/environment.mjs';
const copy=x=>structuredClone(x),stop=new Set(['complete','blocked','failed','unknown','ambiguous','timeout','limit']);
function drive(e,n=0,max=1700){const change={};for(let i=0;i<max&&!stop.has(e.model.status);i++){capabilityIntervention(n,e,change);e.perform({kind:'tick'});}return e;}
const clicks=e=>e.model.world.effects.filter(r=>r.ok&&r.action.kind==='click').map(r=>r.action.object);
const routeEdge=(e,label)=>{const n=e.model.memory.nodes.find(n=>n.kind==='transition'&&n.label===label);return e.model.memory.edges.find(e=>e.kind==='backward'&&e.to===n.id);};
test('goal episode holds its check while learned orienting activity recovers from cursor disturbance',()=>{
 const e=new StateEngine(),w=defaultWorld();
 const record=demonstration('open',w,[...iconDemonstrationActions(w,'A'),{kind:'enter',object:'A'}]);
 e.perform({kind:'teach',record});e.perform({kind:'world',world:w});
 e.perform({kind:'goal',goals:[{kind:'state',features:record.receipts.at(-1).after.features}]});
 for(let i=0;i<100;i++){
  const ep=e.model.intent.episode,step=e.model.memory.nodes.find(n=>n.id===ep?.step);
  if(!e.model.pending&&step?.action.kind==='check')break;
  e.perform({kind:'tick'});
 }
 e.model.world.cursor={x:920,y:75};e.model.observed.cursor={x:920,y:75};
 e.model.observed.icons=e.model.observed.icons.filter(i=>i.id!=='A');
 e.model.observed.object_issues={A:'ambiguous instances'};
 const held=e.model.intent.episode.step;
 const first=e.perform({kind:'tick'});
 assert.equal(first.kind,'charge');assert.equal(e.model.intent.episode.step,held);
 drive(e);assert.equal(e.model.status,'complete');assert.deepEqual(clicks(e),['A']);
 assert.deepEqual(e.model.world.effects.filter(r=>r.action.kind==='move').map(r=>[r.action.x,r.action.y]),[[200,190],[200,190]]);
 assert.equal(e.model.intent.errorHistory.length,0);
});
for(let n=5;n<=10;n++)test(`Capability ${n}: independent experience, observed outcome, frozen memory`,()=>{
 const r=runCapability(n);assert.equal(r.pass,true,JSON.stringify({status:r.status,clicks:r.clicks}));
 assert.ok(r.engine.events.some(e=>e.kind==='spread'&&e.flows.length));
 assert.ok(r.engine.model.intent.predictions.length>0);assert.ok(r.engine.model.intent.goals.every(g=>!g.held));
 assert.ok(!r.engine.model.lessons.some(r=>r.query.includes('2345')||r.query.includes('3521')));
});
test('route choice changes when the actual learned edge is strengthened',()=>{
 const p=prepareCapability(6),e=p.engine;const edge=routeEdge(e,'CLICK FAST');e.perform({kind:'weight',id:edge.id,value:.99});
 e.perform(p.operation);drive(e);assert.equal(e.model.status,'complete');assert.deepEqual(clicks(e),['FAST']);
});
test('removing goal-to-transition weights removes the route (no hidden planner)',()=>{
 const p=prepareCapability(9),e=p.engine;
 for(const edge of [...e.model.memory.edges].filter(e=>e.kind==='backward'))e.perform({kind:'weight',id:edge.id,value:0});
 e.perform(p.operation);drive(e);assert.equal(e.model.status,'blocked');assert.equal(clicks(e).length,0);assert.equal(e.model.heldGoal,true);
});
test('goal tonic drive is causally necessary, not decorative',()=>{
 const p=prepareCapability(9),e=p.engine;e.perform({...p.operation,config:{goalGain:0,maxTicks:120}});drive(e);
 assert.equal(e.model.status,'limit');assert.equal(e.model.world.effects.length,0);assert.equal(e.model.heldGoal,true);
});
test('inhibitory goal occurrences prevent the second task from executing first',()=>{
 const p=prepareCapability(5),e=p.engine;e.perform({...p.operation,config:{goalInhibition:0}});drive(e);
 assert.equal(e.model.status,'ambiguous');assert.equal(e.model.world.effects.length,0);
});
test('removing motor sequence inhibition destroys order selection instead of secretly advancing an index',()=>{
 const p=prepareCapability(9),e=p.engine;e.perform({kind:'config',values:{inhibition:0}});e.perform(p.operation);drive(e);
 assert.equal(e.model.status,'ambiguous');assert.equal(e.model.world.output,'');
});
test('error inhibition prevents repeated failed route; lesion makes the bad route recur',()=>{
 const p=prepareCapability(10),e=p.engine;e.perform({...p.operation,config:{errorGain:0,maxTicks:250}});drive(e,10);
 assert.equal(e.model.status,'limit');assert.ok(clicks(e).filter(x=>x==='FAST').length>1);assert.ok(e.model.intent.goals[0].held);
});
test('decay changes waves while preserving the supported target',()=>{
 const waves=[];
 for(const decay of [.25,.65]){const p=prepareCapability(8),e=p.engine;e.perform({...p.operation,config:{decay}});drive(e);assert.equal(e.model.status,'complete');waves.push(e.events.filter(x=>x.kind==='spread').length);}
 assert.notEqual(waves[0],waves[1]);
});
test('same-signal alternatives stop instead of using an ID tie-break',()=>{
 const p=prepareCapability(6),e=p.engine,n=e.model.memory.nodes.find(n=>n.kind==='transition'&&n.label==='CLICK VIA'),alt={...copy(n),id:'unrelated-id'};
 e.model.memory.nodes.push(alt);
 for(const edge of [...e.model.memory.edges].filter(x=>x.kind==='backward'&&x.to===n.id))e.model.memory.edges.push({...edge,id:'alternate-edge',to:alt.id});
 e.perform(p.operation);drive(e);assert.equal(e.model.status,'ambiguous');assert.deepEqual(clicks(e),[]);
});
test('renumbering and reordering graph storage preserves new goal decisions',()=>{
 for(const n of [5,6,8,9,10]){
  const p=prepareCapability(n),e=p.engine,mem=e.model.memory,map=new Map(mem.nodes.map((x,i)=>[x.id,'arbitrary-'+(10000-i*13)]));
  for(const x of mem.nodes){x.id=map.get(x.id);for(const k of ['from','to','first','last','pre','post'])if(x[k])x[k]=map.get(x[k]);}
  for(const x of mem.edges){x.from=map.get(x.from);x.to=map.get(x.to);x.id='edge-'+x.id;}
  mem.root=map.get(mem.root);for(const c of e.model.commands){c.context=map.get(c.context);c.first=map.get(c.first);}
  mem.nodes.reverse();mem.edges.reverse();e.perform(p.operation);drive(e,n);assert.equal(e.model.status,'complete',String(n));
  const original=runCapability(n);assert.deepEqual(clicks(e),original.clicks);assert.equal(e.model.world.output,original.output);
 }
});
test('unknown desired keys and states never cause blind actions',()=>{
 const p=prepareCapability(9),e=p.engine,before=e.export();
 assert.throws(()=>e.perform({kind:'goal',goals:[{kind:'field',focus:'FIELD',value:'989'}]}),/опыта/);
 assert.deepEqual(e.export(),before);
 assert.throws(()=>e.perform({kind:'goal',goals:[{kind:'state',features:['visible:unknown']}]}),/наблюдалось/);
 assert.equal(e.model.world.effects.length,0);
});
test('goal-specified typing preserves repetitions and length without learning the target',()=>{
 for(const text of ['1001','1111','54321','700005']){
  const p=prepareCapability(9),e=p.engine;e.perform({kind:'goal',goals:[{kind:'field',focus:'FIELD',value:text}]});drive(e);
  assert.equal(e.model.status,'complete');assert.equal(e.model.world.output,text);
  assert.equal(e.model.intent.predictions.filter(x=>x.action.kind==='key').length,text.length);
 }
});
test('existing correct prefix is observed, not blindly retyped',()=>{
 const p=prepareCapability(9),e=p.engine,w=copy(e.model.world);w.surface='calculator';w.focus='FIELD';w.output='23';
 e.perform({kind:'world',world:w});e.perform(p.operation);drive(e);
 assert.equal(e.model.world.output,'2345');assert.equal(e.model.world.effects.map(r=>r.action.value||'').join(''),'45');
});
test('wrong existing value is not overwritten by an unlearned erase procedure',()=>{
 const p=prepareCapability(9),e=p.engine,w=copy(e.model.world);w.surface='calculator';w.focus='FIELD';w.output='999';
 e.perform({kind:'world',world:w});e.perform(p.operation);drive(e);
 assert.equal(e.model.status,'blocked');assert.equal(e.model.world.output,'999');assert.equal(e.model.world.effects.length,0);
});
test('manual acknowledgment: observed effect does not consume the pending goal occurrence',()=>{
 const p=prepareCapability(9),e=p.engine;e.perform(p.operation);
 for(let i=0;i<400&&!e.model.pending?.source;i++)e.perform({kind:'tick'});
 // Switch delivery policy on the model only for the test (UI does not edit during pending).
 e.model.config.ackMode='manual';e.perform({kind:'tick'});
 const p0=copy(e.model.pending),q=e.model.occ.find(q=>q.id===p0.source);
 assert.equal(e.model.world.output,'2');assert.equal(q.held,true);
 for(let i=0;i<3;i++)e.perform({kind:'tick'});
 assert.equal(e.model.world.output,'2');const receipt=copy(e.model.pending.receipt);e.perform({kind:'deliver'});
 assert.equal(e.model.occ.find(q=>q.id===p0.source).held,false);
 const state=copy(e.model.occ);e.perform({kind:'receipt',receipt});assert.deepEqual(e.model.occ,state);
});
test('lost receipt never advances, repeats, or claims goal success',()=>{
 const p=prepareCapability(9),e=p.engine;e.perform({kind:'config',values:{ackMode:'drop',timeout:8}});e.perform(p.operation);drive(e);
 assert.equal(e.model.status,'timeout');assert.equal(e.model.world.effects.length,1);assert.equal(e.model.heldGoal,true);
});
test('mismatch record points to a prediction made before its effect',()=>{
 const r=runCapability(10),b=r.engine.model.intent,err=b.errorHistory[0];
 const prediction=b.predictions.find(p=>p.id===err.request);assert.ok(prediction);assert.equal(prediction.expected.state,err.expected);assert.notEqual(err.actual,err.expected);
 const errorIndex=r.engine.events.findIndex(e=>e.kind==='prediction-error'),dispatchIndex=r.engine.events.findIndex(e=>e.kind==='dispatch'&&e.request===err.request);
 assert.ok(errorIndex>dispatchIndex);assert.ok(b.error[err.transition]>0);
});
test('history replay and export never replay physical actions into the live world',()=>{
 const e=runCapability(10).engine,before=copy(e.model),exp=e.export();
 e.at(12);assert.deepEqual(e.model,before);assert.deepEqual(StateEngine.import(exp).model,e.model);
});
test('external unknown screen stops without accessing hidden simulator transitions',()=>{
 const p=prepareCapability(9),e=p.engine,w=copy(e.model.world);w.surfaces.unseen={label:'unknown',field:null,icons:[{id:'MYSTERY',label:'?',x:200,y:200,click:'calculator'}]};w.surface='unseen';
 e.perform({kind:'world',world:w});e.perform(p.operation);drive(e);
 assert.equal(e.model.status,'blocked');assert.equal(e.model.world.effects.length,0);
});
