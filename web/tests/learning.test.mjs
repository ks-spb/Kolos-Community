import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Script,createContext} from 'node:vm';
import {StateEngine} from '../states/core.mjs';
import {defaultWorld,demonstration,iconDemonstrationActions,persistentGraph} from '../states/environment.mjs';
import {transitionCandidates} from '../states/dynamics.mjs';

function lesson(){
 const e=new StateEngine(),w=defaultWorld();w.surface='window';
 e.perform({kind:'teach',record:demonstration('close',w,iconDemonstrationActions(w,'X'))});
 return {e,w};
}
function run(e,w,until=()=>false){
 e.perform({kind:'world',world:w});e.perform({kind:'start',query:'close'});
 for(let i=0;i<140&&!until(e)&&!['complete','blocked','failed','ambiguous','timeout','limit'].includes(e.model.status);i++)e.perform({kind:'tick'});
}
test('online confirmation updates only the causal outcome, once per receipt',()=>{
 const {e,w}=lesson(),before=persistentGraph(e.model.memory);run(e,w);
 assert.equal(e.model.status,'complete');
 const changes=e.model.memory.edges.filter(x=>before.edges.find(y=>y.id===x.id)?.weight!==x.weight);
 assert.equal(changes.length,1);assert.equal(changes[0].kind,'backward');assert.ok(changes[0].weight>.9);
 const frozen=persistentGraph(e.model.memory),receipt=e.events.findLast(x=>x.kind==='ack').receipt;
 e.perform({kind:'receipt',receipt});assert.deepEqual(persistentGraph(e.model.memory),frozen);
 assert.deepEqual(persistentGraph(StateEngine.import(e.export()).model.memory),frozen);
});
test('unexpected known action inhibits its expectation and remembers the actual outcome',()=>{
 const {e,w}=lesson(),old=e.model.memory.nodes.find(n=>n.kind==='transition');
 w.surfaces.window.icons[0].click='calculator';run(e,w,e=>e.events.at(-1)?.kind==='prediction-error');
 const ev=e.events.find(x=>x.kind==='prediction-error');assert.ok(ev);assert.ok(e.model.heldGoal);
 assert.ok(ev.plasticity.changes[0].after<.9);assert.ok(ev.plasticity.learned);
 assert.equal(e.model.commands.length,1);
 const t=e.model.memory.nodes.find(n=>n.id===old.id);t.inhibition=1;
 const source=e.model.memory.nodes.find(n=>n.id===t.from);source.sensory=1;e.model.observed=ev.receipt.before;
 const c=transitionCandidates(e.model,{[t.id]:1},e.model.config,.65).find(c=>c.id===t.id);
 assert.equal(c.a,0);assert.equal(c.inhibition,1);
});
test('new context is stored once and disabling plasticity freezes persistent memory',()=>{
 for(const plasticity of [0,1]){
  const {e,w}=lesson();e.perform({kind:'config',values:{plasticity}});const before=persistentGraph(e.model.memory);
  w.surfaces.window.icons[1].id='new-1';w.surfaces.window.icons[2].id='new-2';run(e,w);
  const count=e.model.memory.nodes.length;
  if(plasticity)assert.ok(count>before.nodes.length);else assert.deepEqual(persistentGraph(e.model.memory),before);
  run(e,w);assert.equal(e.model.memory.nodes.length,count);
 }
});
test('dispatched click without evidence of its learned result remains unconfirmed',()=>{
 const {e,w}=lesson(),before=persistentGraph(e.model.memory);
 delete w.surfaces.window.icons[0].click;w.selected='X';run(e,w);
 assert.equal(e.model.status,'timeout');assert.ok(e.model.heldGoal);assert.ok(e.model.pending);
 assert.deepEqual(persistentGraph(e.model.memory),before);
});
test('standalone bundles contain the same executable dynamics without name collisions',()=>{
 for(const name of ['index','neurons','shared']){
  const html=readFileSync(new URL('../dist/'+name+'.html',import.meta.url),'utf8');
  const source=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(x=>x[1]).find(s=>s.includes('class StateEngine'));
  assert.ok(source);const context=createContext({structuredClone});
  const probe=name==='shared'?'globalThis.result=new SharedSession().run(3).pass;':'globalThis.result=runCase(3).pass;';
  const code=source.replace('mountStateLab();','').replace(/\}\)\(\);\s*$/,probe+'})();');
  new Script(code,{filename:name+'.html'}).runInContext(context,{timeout:15000});assert.equal(context.result,true);
 }
});
