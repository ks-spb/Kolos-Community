import {persistentGraph} from '../states/environment.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {StateEngine} from '../states/core.mjs';
import {prepareCapability} from '../states/capability-cases.mjs';
import {prepareImagery,runImageryExperiment} from '../states/imagery-cases.mjs';
import {imageSatisfied,updateImagery} from '../states/imagery.mjs';
const copy=x=>structuredClone(x);
function ticks(e,n){for(let i=0;i<n;i++)e.perform({kind:'tick'});}
function setup(value='2345',options={}){const p=prepareImagery(value);p.engine.perform({...p.operation,imageOptions:options});return p.engine;}
function act(e){e.perform({kind:'image-control',command:'act'});for(let i=0;i<500&&!['complete','blocked','failed','ambiguous','timeout','limit'].includes(e.model.status);i++)e.perform({kind:'tick'});return e;}
test('11: internal image, fading, same content under perception, externally confirmed result',()=>{const r=runImageryExperiment();assert.equal(r.pass,true);assert.deepEqual(r.clicks,['X','CALC']);});
test('strong internal excitation cannot invent an effect or sensory evidence',()=>{const e=setup(),before=copy(e.model.world);ticks(e,80);assert.deepEqual(e.model.world,before);assert.equal(e.model.imagery.ready,1);assert.equal(e.model.imagery.match,0);assert.equal(e.model.heldGoal,true);assert.equal(e.model.intent.predictions.length,0);assert.equal(e.model.imagery.confirmations.length,0);});
test('internal representation controls actions: zero internal gain prevents execution',()=>{const e=setup('2345',{internalGain:0});act(e);assert.equal(e.model.world.effects.length,0);assert.equal(e.model.heldGoal,true);});
test('no sensory source means no success even if the imagined value exists in memory',()=>{const e=setup('1700',{sensoryGain:0});ticks(e,10);act(e);assert.equal(e.model.world.effects.length,0);assert.equal(e.model.imagery.confirmations.length,0);});
test('image cannot replace disabled learned backward synapses',()=>{const e=setup();for(const edge of e.model.memory.edges.filter(x=>x.kind==='backward'))e.perform({kind:'weight',id:edge.id,value:0});act(e);assert.equal(e.model.status,'blocked');assert.equal(e.model.world.effects.length,0);assert.equal(e.model.heldGoal,true);});
test('same learned state vertex is used for internally and externally stimulated state',()=>{const p=prepareCapability(8),e=p.engine;e.perform({...p.operation,kind:'imagine'});ticks(e,6);const id=e.model.intent.goals[0].targets[0];assert.equal(e.model.imagery.nodes.find(n=>n.id===id).memoryRef,id);act(e);const n=e.model.imagery.nodes.find(n=>n.id===id);assert.ok(n.S>=.7&&n.present);assert.equal(e.model.status,'complete');});
for(const value of ['1001','1111','54321',''])test(`position, order and END encode ${JSON.stringify(value)} without content collisions`,()=>{const e=setup(value);ticks(e,4);act(e);assert.equal(e.model.world.output,value);assert.equal(e.model.status,'complete');const goal=e.model.intent.goals[0],ids=e.model.imagery.patterns[goal.id];assert.equal(ids.length,Array.from(value).length+2);assert.equal(new Set(ids).size,ids.length);});
for(const wrong of ['2435','234','23450'])test(`observed ${wrong} is not the imagined 2345`,()=>{const e=setup();const w=copy(e.model.world);w.surface='calculator';w.focus='FIELD';w.output=wrong;e.perform({kind:'world',world:w});ticks(e,6);assert.equal(imageSatisfied(e.model),false);assert.equal(e.model.imagery.match,0);assert.equal(e.model.heldGoal,true);});
test('same text in another field is not confirmation',()=>{const e=setup();e.model.observed.focus='OTHER';e.model.observed.output='2345';for(let i=0;i<6;i++)updateImagery(e.model,e.model.intent.goals[0]);assert.equal(imageSatisfied(e.model),false);});
test('sensory trace surviving disappearance cannot confirm a goal',()=>{const e=setup();const g=e.model.intent.goals[0];e.model.observed.focus='FIELD';e.model.observed.output='2345';for(let i=0;i<8;i++)updateImagery(e.model,g);assert.equal(imageSatisfied(e.model),true);e.model.observed.output='2435';updateImagery(e.model,g);assert.equal(imageSatisfied(e.model),false);assert.ok(e.model.imagery.nodes.some(n=>n.S>0&&!n.present));});
test('correct preexisting observed value completes without new typing after act, not during imagery',()=>{const e=setup();const w=copy(e.model.world);w.surface='calculator';w.focus='FIELD';w.output='2345';e.perform({kind:'world',world:w});ticks(e,5);assert.equal(e.model.heldGoal,true);assert.equal(e.model.imagery.match>.9,true);act(e);assert.equal(e.model.status,'complete');assert.equal(e.model.world.effects.length,0);});
test('actual effect without delivered receipt cannot consume a source or complete the image',()=>{
 const e=setup();e.perform({kind:'config',values:{ackMode:'manual'}});e.perform({kind:'image-control',command:'act'});
 for(let i=0;i<400;i++){e.perform({kind:'tick'});if(e.model.pending?.receipt){if(e.model.pending.action.kind==='key')break;e.perform({kind:'deliver'});}}
 assert.equal(e.model.world.output,'2');assert.equal(e.model.observed.output,'');const source=e.model.occ.find(q=>q.id===e.model.pending.source);assert.equal(source.held,true);
 ticks(e,3);assert.equal(e.model.world.output,'2');assert.equal(e.model.imagery.match,0);assert.equal(e.model.imagery.confirmations.length,0);
 const receipt=copy(e.model.pending.receipt);assert.throws(()=>e.perform({kind:'receipt',receipt:{...receipt,source:'imagined'}}));assert.equal(e.model.pending.source,source.id);
 e.perform({kind:'deliver'});assert.equal(e.model.occ.find(q=>q.id===source.id).held,false);
});
test('invalid image is transactional; unknown digits are not learned from imagination',()=>{const {engine:e}=prepareImagery();const before=e.export();assert.throws(()=>e.perform({kind:'imagine',goals:[{kind:'field',focus:'FIELD',value:'899'}]}));assert.deepEqual(e.export(),before);});
test('JSON reload and history never execute mental predictions on the live world',()=>{const e=setup();ticks(e,10);const original=copy(e.model);assert.deepEqual(StateEngine.import(e.export()).model,original);e.at(3);assert.deepEqual(e.model,original);});
test('changing imagery decay changes charge time, not the target or required confirmation',()=>{const counts=[];for(const decay of [.25,.8]){const e=setup('2345',{decay});let n=0;while(e.model.imagery.ready<.7&&n<20){ticks(e,1);n++;}counts.push(n);assert.equal(e.model.world.effects.length,0);act(e);assert.equal(e.model.world.output,'2345');}assert.notEqual(counts[0],counts[1]);});
test('reset and ordinary commands discard internal imagery',()=>{const e=setup();e.perform({kind:'reset'});assert.equal(e.model.imagery,null);assert.equal(e.model.heldGoal,false);});
