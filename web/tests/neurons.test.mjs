import test from 'node:test';
import assert from 'node:assert/strict';
import {neuronFrame,neuronEdgeGroups} from '../neurons/snapshot.mjs';
import {prepareImagery,runImageryExperiment} from '../states/imagery-cases.mjs';
import {prepareLanguage} from '../states/language-cases.mjs';
import {persistentGraph} from '../states/environment.mjs';
const copy=x=>structuredClone(x);
function start(){const {engine:e,operation}=prepareImagery();e.perform(operation);return e;}
function advance(e){const before=copy(e.model),ev=e.perform({kind:'tick'});return neuronFrame(e.model,ev,before);}
test('projection never changes the engine, history, world, or weights',()=>{
 const e=start();for(let i=0;i<8;i++){const before=copy(e.model),ev=e.perform({kind:'tick'}),frozen=copy(e.model),ops=copy(e.operations);
 neuronFrame(e.model,ev,before);assert.deepEqual(e.model,frozen);assert.deepEqual(e.operations,ops);}
});
test('same I/S vertices and direct input terms are taken from the real equation',()=>{
 const e=start(),f=advance(e),i=e.model.imagery;
 for(const n of i.nodes){const v=f.nodes.find(v=>v.id===n.id);assert.equal(v.I,n.I);assert.equal(v.S,n.S);assert.equal(v.present,n.present);
  assert.ok(Math.abs(v.I-(v.oldI*v.imageDecay+(1-v.imageDecay)*v.internalInput))<1e-8);
  assert.ok(Math.abs(v.S-(v.oldS*v.imageDecay+(1-v.imageDecay)*v.sensoryInput))<1e-8);}
 assert.equal(f.world.effects,0);assert.equal(f.match,0);
});
test('order links are structural and are NEVER given invented particle flows',()=>{
 const e=start();for(let i=0;i<8;i++){const f=advance(e);const links=f.edges.filter(e=>e.kind==='order');assert.ok(links.length);for(const link of links){assert.equal(link.provenance,'structure');assert.equal(link.flow,null);}}
});
test('wave values exactly match registered events, raw and normalized are distinct',()=>{
 const e=start();let flows=0;for(let i=0;i<8;i++){const f=advance(e);for(const raw of f.event.flows||[]){const edge=f.edges.find(e=>e.id===raw.edge);assert.equal(edge.flow,raw.value);assert.equal(edge.provenance,'recorded');assert.ok(edge.term<=edge.flow);flows++;}}
 assert.ok(flows>5);
});
test('rest removes input, does not remove a fading I trace or create perception',()=>{
 const e=start();for(let i=0;i<8;i++)advance(e);e.perform({kind:'image-control',command:'rest'});
 const f=advance(e);assert.ok(f.nodes.some(n=>n.I>0));assert.ok(f.edges.filter(e=>e.channel==='I').every(e=>e.flow===null));assert.equal(f.match,0);
});
test('dispatch, effect and receipt remain separate; candidate is not stored activation',()=>{
 const e=start();e.perform({kind:'image-control',command:'act'});let found=false;
 for(let i=0;i<250;i++){const f=advance(e);if(f.event.kind==='dispatch'&&f.pending.action.kind==='key'){
  const source=f.nodes.find(n=>n.id===f.pending.source);assert.ok(source.held);assert.ok(source.C>=source.threshold);assert.equal(f.world.output,'');
  const fx=advance(e);assert.equal(fx.event.kind,'effect');assert.equal(fx.world.output,'2');assert.equal(fx.observed.output,'');assert.ok(fx.nodes.find(n=>n.id===source.id).held);
  const ack=advance(e);assert.equal(ack.event.kind,'ack');assert.equal(ack.nodes.find(n=>n.id===source.id).held,false);found=true;break;}}
 assert.ok(found);
});
test('complete projected trace reaches 2345 with frozen memory and source separation',()=>{
 const e=start(),memory=persistentGraph(e.model.memory);for(let i=0;i<8;i++)advance(e);e.perform({kind:'image-control',command:'act'});
 let f;for(let i=0;i<400&&e.model.status!=='complete';i++)f=advance(e);
 assert.equal(f.status,'complete');assert.equal(f.observed.output,'2345');assert.deepEqual(persistentGraph(e.model.memory),memory);assert.equal(e.model.imagery.confirmations[0].source,'external');
 assert.equal(runImageryExperiment().pass,true);
});
test('multi-links group by direction, kind and provenance, keep individual IDs',()=>{
 const base={from:'a',to:'b',kind:'backward',provenance:'recorded',flow:1,weight:.9};
 const groups=neuronEdgeGroups([{...base,id:'1'},{...base,id:'2'},{...base,id:'3',from:'b',to:'a'},{...base,id:'4',kind:'order',provenance:'structure'}]);
 assert.equal(groups.length,3);assert.deepEqual(groups[0].ids,['1','2']);assert.equal(groups[0].flow,2);
});
test('language has path candidates, not fabricated glyph activation',()=>{
 const {engine:e,operation}=prepareLanguage();e.perform(operation);const f=advance(e);
 assert.ok(f.nodes.some(n=>n.kind==='language-candidate'&&n.C>0));assert.ok(f.nodes.filter(n=>n.kind==='glyph').every(n=>n.a===null));
});
test('all edges in a projected frame have existing endpoints; no stored topology mutation',()=>{
 const e=start();e.perform({kind:'image-control',command:'act'});for(let i=0;i<85;i++){const f=advance(e),ids=new Set(f.nodes.map(n=>n.id));assert.equal(ids.size,f.nodes.length);assert.ok(f.edges.every(e=>ids.has(e.from)&&ids.has(e.to)));}
});
