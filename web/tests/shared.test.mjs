import test from 'node:test';
import assert from 'node:assert/strict';
import {backwardWave} from '../states/backward.mjs';
import {StateEngine} from '../states/core.mjs';
import {demonstration,iconDemonstrationActions} from '../states/environment.mjs';
import {SHARED_FIXTURE} from '../shared/fixture.mjs';
import {SharedSession,sharedSignature,sharedWorld,runSharedTransfer,SHARED_STOP} from '../shared/suite.mjs';
import {neuronFrame} from '../neurons/snapshot.mjs';

const order=[12,3,10,1,8,5,11,2,6,9,7,4];
const untilStop=e=>{for(let i=0;i<1200&&!SHARED_STOP.has(e.model.status);i++)e.perform({kind:'tick'});};

test('shared: all twelve use exactly one engine, all memories and common settings remain available',()=>{
 const s=new SharedSession(),engine=s.engine,signature=sharedSignature(engine.model),ids=engine.model.memory.nodes.map(n=>n.id);
 let routes=0;s.onFrame=(m,ev)=>{if(ev.kind==='route'){routes++;assert.equal(sharedSignature(m),signature);assert.deepEqual(m.memory.nodes.map(n=>n.id),ids);}};
 const result=s.runAll();assert.equal(s.engine,engine);assert.ok(routes>12);
 assert.deepEqual(result.filter(r=>!r.pass),[]);assert.equal(new Set(result.map(r=>r.instance)).size,1);
 assert.equal(new Set(result.flatMap(r=>[r.memoryBefore,r.memoryAfter])).size,1);
 assert.equal(s.engine.model.lessons.length,18);assert.equal(s.engine.model.exposures.length,1);
 assert.equal(s.engine.model.languageMemory.lessons.length,6);
 assert.equal(engine.model.lessons.filter(l=>l.query==='добавь траты 1700').length,1);
 assert.ok(!engine.model.lessons.some(l=>l.query.includes('1354')||l.query.includes('2345')));
});

test('shared: reverse and mixed execution orders do not overwrite older capabilities',()=>{
 const s=new SharedSession();for(const run of [Array.from({length:12},(_,i)=>12-i),order]){
  const results=s.runAll(run);assert.ok(results.every(r=>r.pass),JSON.stringify(results.filter(r=>!r.pass)));
 }
 assert.equal(s.results.length,24);
});

test('shared: changed order of independent demonstrations preserves solutions',()=>{
 const n=SHARED_FIXTURE.episodes.length;
 const s=new SharedSession({episodeOrder:Array.from({length:n},(_,i)=>n-i-1)});
 const results=s.runAll(order);assert.ok(results.every(r=>r.pass),JSON.stringify(results.filter(r=>!r.pass)));
});

test('shared: baseline mean shows interference; one global competitive operator removes it',()=>{
 const old=new SharedSession({competition:0}),results=old.runAll();
 assert.deepEqual(results.filter(r=>!r.pass).map(r=>r.number),[5,7,9,11,12]);
 assert.ok(results.every(r=>r.checks.memoryUnchanged));
 const current=new SharedSession();assert.equal(current.engine.model.config.stateCompetition,1);
 assert.ok(current.runAll().every(r=>r.pass));
});

test('shared: input competition is degree invariant and equal inputs do not select by id',()=>{
 const nodes=[{id:'s',kind:'state'}],cfg={decay:.5,discount:.9,stateCompetition:1};
 const edge={id:'e',kind:'backward',from:'good',to:'s',weight:.9},old={good:1};
 const mem={edges:[edge]},flows=[];const initial=backwardWave(mem,nodes,old,cfg,flows);
 for(let i=0;i<40;i++)mem.edges.push({id:'x'+i,kind:'backward',from:'dormant'+i,to:'s',weight:1});
 assert.deepEqual(backwardWave(mem,nodes,old,cfg,[]),initial);
 mem.edges.push({id:'equal',kind:'backward',from:'twin',to:'s',weight:.9});old.twin=1;
 const equal=[];assert.deepEqual(backwardWave(mem,nodes,old,cfg,equal),initial);
 assert.equal(equal.length,2);assert.equal(equal[0].term,equal[1].term);
 assert.equal(equal.reduce((s,f)=>s+f.term,0),initial.s);
 assert.deepEqual(backwardWave({edges:mem.edges.slice().reverse()},nodes,old,cfg,[]),initial);
});

test('shared: readout labels context rather than test number; weak and strong FAST coexist',()=>{
 const s=new SharedSession();s.run(6);const memory=s.engine.model.memory;
 const ts=memory.nodes.filter(n=>n.kind==='transition'&&n.label==='CLICK FAST');assert.equal(ts.length,2);
 assert.notEqual(ts[0].from,ts[1].from);
 assert.ok(memory.nodes.find(n=>n.id===ts[0].from).features.includes('visible:ARCHIVE'));
 assert.ok(memory.nodes.find(n=>n.id===ts[1].from).features.includes('visible:CURRENT'));
 assert.deepEqual(ts.map(t=>memory.edges.find(e=>e.kind==='backward'&&e.to===t.id).weight),[.35,.9]);
 assert.equal(s.run(10).pass,true);assert.equal(s.run(6).pass,true);
});

test('shared: export/import retains weights and knowledge but never executes saved task state',()=>{
 const s=new SharedSession();s.run(12);const data=s.export(),old=sharedSignature(s.engine.model);
 const restored=new SharedSession({database:JSON.parse(JSON.stringify(data))});assert.equal(sharedSignature(restored.engine.model),old);
 assert.equal(restored.engine.model.world.effects.length,0);assert.equal(restored.engine.model.pending,null);
 assert.ok(restored.runAll(order).every(r=>r.pass));
 data.learning.push({kind:'start',query:'открой окно'});assert.throws(()=>new SharedSession({database:data}),/запускающие/);
});

test('shared: a new connected task crosses old experiment boundaries without resetting the world',()=>{
 const s=new SharedSession();s.run(12);const r=runSharedTransfer(s);assert.equal(r.pass,true);assert.deepEqual(r.clicks,['GO0','GO1','GO2','HOME','CALC']);
 assert.equal(r.output,'4512');assert.equal(r.memoryBefore,r.memoryAfter);
});

test('shared: old visible labels cannot hide ambiguous command training or unknown language',()=>{
 const {engine:e}=new SharedSession();const w=sharedWorld('new');e.perform({kind:'teach',record:demonstration('открой окно',w,iconDemonstrationActions(w,'VIA'))});
 e.perform({kind:'world',world:sharedWorld()});e.perform({kind:'start',query:'открой окно'});
 assert.equal(e.model.status,'unknown');assert.equal(e.model.world.effects.length,0);
 const s=new SharedSession();s.engine.perform({kind:'language-start',phrase:'не хочу увидеть 1354 в поле'});untilStop(s.engine);
 assert.equal(s.engine.model.status,'unknown');assert.equal(s.engine.model.world.effects.length,0);
});

test('shared: frozen-memory assertion notices tampering; no per-scenario hidden reload repairs it',()=>{
 const s=new SharedSession();s.run(1);s.engine.model.memory.edges[0].weight=0;
 assert.throws(()=>s.begin(2),/изменились/);
});

test('shared: disabling an experienced connection still blocks the solution with a large base',()=>{
 const s=new SharedSession(),m=s.engine.model;
 const calc=m.memory.nodes.find(n=>n.kind==='transition'&&n.label==='CLICK CALC');
 for(const e of m.memory.edges)if(e.kind==='backward'&&e.to===calc.id)e.weight=0;
 s.signature=sharedSignature(m);const r=s.run(9);assert.equal(r.pass,false);assert.equal(r.status,'blocked');
 assert.equal(m.lessons.length,18);
});

test('shared: projection reports exact post-competition edge terms, never reintroduces a mean',()=>{
 const s=new SharedSession();s.begin(9);let witnessed=false;
 for(let i=0;i<40&&!s.active.finished;i++){
  const before=structuredClone(s.engine.model),ev=s.step();
  const f=neuronFrame(s.engine.model,ev,before);
  for(const flow of ev.flows||[]){const edge=f.edges.find(e=>e.id===flow.edge);if(edge&&flow.aggregation==='competitive-alternatives'){
   assert.equal(edge.term,flow.term);witnessed=true;
  }}
 }
 assert.ok(witnessed);
});
