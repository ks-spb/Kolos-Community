import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';
import {SignalEngine,calculatorDemo,defaultScene,DEFAULTS,underCursor} from '../signal/core.mjs';

test('standalone scripts parse after bundling on Windows',()=>{
 const html=readFileSync(new URL('../dist/index.html',import.meta.url),'utf8');
 const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
 assert.ok(scripts.length>=2,'bundle should contain standalone scripts');
 for(const [,source] of scripts)assert.doesNotThrow(()=>new Script(source));
});

const query='добавь траты 1700';
function until(e,stop=()=>e.model.status==='complete') {
 for(let i=0;i<150;i++) {if(stop())return;const r=e.perform({kind:'tick'});if(['ambiguous','below','blocked','unknown','limit'].includes(r.decision))return;}
}
function start(e){e.perform({kind:'reset'});e.perform({kind:'start',query});}
function scene(e,fn){const s=structuredClone(e.model.scene);fn(s);e.perform({kind:'scene',scene:s});}
function run(e){start(e);until(e);return e;}
function keyOutput(e){return e.model.scene.executions.filter(x=>x.kind==='key').map(x=>x.value).join('');}
test('sequence with repeated zeros fires exactly 4 keys and reaches end',()=>{
 const e=run(calculatorDemo());assert.equal(keyOutput(e),'1700');assert.equal(e.model.scene.output,'1700');assert.equal(e.model.status,'complete');
 const zeros=e.model.nodes.filter(n=>n.kind==='context'&&n.action?.kind==='key'&&n.action.value==='0');assert.equal(zeros.length,2);assert.notEqual(zeros[0].id,zeros[1].id);
 assert.equal(e.model.scene.executions.filter(x=>x.kind==='click').length,1);
});
test('pure preview and duplicate commit cannot execute a click twice',()=>{
 const e=calculatorDemo();start(e);until(e,()=>e.model.scene.checked==='CALC');
 const before=JSON.stringify(e.export()),m=JSON.stringify(e.model),p=e.preview();assert.equal(p.event.effect?.kind,'click');
 assert.equal(JSON.stringify(e.model),m);assert.equal(JSON.stringify(e.export()),before);
 e.commit(p);assert.throws(()=>e.commit(p),/устарел/);assert.equal(e.model.scene.executions.filter(x=>x.kind==='click').length,1);
});
test('moved CALC uses graph recovery and recheck, never clicks SET at old coordinates',()=>{
 const e=calculatorDemo();scene(e,s=>{s.objects.find(x=>x.name==='CALC').x=820;s.objects.find(x=>x.name==='SET').x=500;});run(e);
 assert.equal(e.model.scene.output,'1700');assert.equal(e.model.status,'complete');assert.ok(e.events.some(x=>x.effect?.kind==='seek'));
 assert.deepEqual(e.model.scene.executions.filter(x=>x.kind==='click').map(x=>x.object),['CALC']);
});
test('hidden CALC stops before click/key, revealing and retrying resumes',()=>{
 const e=calculatorDemo();scene(e,s=>s.objects.find(x=>x.name==='CALC').visible=false);run(e);assert.equal(e.model.status,'blocked');assert.equal(keyOutput(e),'');
 assert.equal(e.model.scene.executions.filter(x=>x.kind==='click').length,0);
 scene(e,s=>s.objects.find(x=>x.name==='CALC').visible=true);e.perform({kind:'wake'});until(e);assert.equal(keyOutput(e),'1700');
});
test('environment changed after click preview invalidates it',()=>{
 const e=calculatorDemo();start(e);until(e,()=>e.model.scene.checked==='CALC');const p=e.preview();
 scene(e,s=>s.objects.find(x=>x.name==='CALC').visible=false);assert.throws(()=>e.commit(p),/устарел/);assert.equal(keyOutput(e),'');
 assert.equal(e.model.scene.executions.filter(x=>x.kind==='click').length,0);
});
test('wrong focused app blocks keys despite prior learned click',()=>{
 const e=calculatorDemo();start(e);until(e,()=>e.model.scene.app==='CALC');scene(e,s=>s.app='MAIL');
 e.perform({kind:'tick'});assert.equal(e.model.status,'blocked');assert.equal(keyOutput(e),'');
});
test('no request: visible icons do not cause actions',()=>{const e=calculatorDemo();e.perform({kind:'tick'});assert.equal(e.model.scene.executions.length,0);});
test('query 2500 is not silently converted to 1700',()=>{
 const e=calculatorDemo();e.perform({kind:'start',query:'добавь траты 2500'});until(e);assert.equal(e.model.status,'unknown');assert.equal(keyOutput(e),'');
});
test('all graph IDs may be permuted: inference still produces the same actions',()=>{
 const e=calculatorDemo();const ids=new Map(e.model.nodes.map(n=>[n.id,10000-n.id*3]));
 for(const n of e.model.nodes){n.id=ids.get(n.id);if(n.parent)n.parent=ids.get(n.parent);}
 for(const l of e.model.edges){l.from=ids.get(l.from);l.to=ids.get(l.to);l.id=20000-l.id*7;}
 const baseline=run(calculatorDemo());run(e);assert.equal(keyOutput(e),'1700');assert.equal(e.model.status,baseline.model.status);
});
test('storage order of nodes/edges does not affect decisions',()=>{
 const e=calculatorDemo();e.model.nodes.reverse();e.model.edges.reverse();run(e);assert.equal(keyOutput(e),'1700');assert.equal(e.model.status,'complete');
});
test('refractory resets the fired node and counts logical ticks only',()=>{
 const e=calculatorDemo();start(e);const ev=e.perform({kind:'tick'});let n=e.model.nodes.find(n=>n.id===ev.winner);assert.equal(n.a,0);assert.equal(n.r,2);assert.equal(n.trace,1);
 const frozen=JSON.stringify(e.model);e.preview();assert.equal(JSON.stringify(e.model),frozen);
 e.perform({kind:'tick'});n=e.model.nodes.find(n=>n.id===ev.winner);assert.equal(n.r,1);assert.equal(n.trace,.9);
});
test('threshold stops a chain; residual activation only decays without new spikes',()=>{
 const e=calculatorDemo();const first=e.model.edges.find(x=>x.from===1&&x.kind==='excite');e.perform({kind:'weight',id:first.id,value:.4});start(e);
 const ev=e.perform({kind:'tick'});assert.equal(ev.decision,'below');const id=ev.candidates[0].id;assert.equal(e.model.nodes.find(x=>x.id===id).a,.4);
 e.perform({kind:'tick'});assert.equal(e.model.nodes.find(x=>x.id===id).a,.24);assert.equal(keyOutput(e),'');
});
test('same context conflicting demonstrations tie, and a weight change changes actual winner',()=>{
 const e=new SignalEngine();const a=[{kind:'move',x:500,y:150},{kind:'check',object:'CALC'},{kind:'click',object:'CALC'}];
 const b=[{kind:'move',x:180,y:150},{kind:'check',object:'DOC'},{kind:'click',object:'DOC'}];
 e.perform({kind:'teach',query,actions:a});e.perform({kind:'teach',query,actions:b});run(e);assert.equal(e.model.status,'ambiguous');
 assert.equal(e.model.scene.executions.length,0);const candidates=e.events.at(-1).candidates;assert.equal(candidates.length,2);
 const doc=candidates.find(c=>c.label.includes('180'));const edge=e.model.edges.find(l=>l.to===doc.id&&l.kind==='excite');e.perform({kind:'weight',id:edge.id,value:.99});e.perform({kind:'wake'});until(e);
 assert.equal(e.model.scene.app,'DOC');
});
test('inhibitory link is a negative contribution, not a label',()=>{
 const e=calculatorDemo();const first=e.model.edges.find(x=>x.from===1&&x.kind==='excite');e.perform({kind:'inhibitory',from:1,to:first.to,weight:.5});start(e);
 const ev=e.perform({kind:'tick'});assert.equal(ev.decision,'below');assert.equal(ev.candidates[0].inhibition,.5);
});
test('weights update on explicit reward only; disappearance does not punish',()=>{
 const e=calculatorDemo();const weights=e.model.edges.map(x=>x.weight);run(e);assert.deepEqual(e.model.edges.map(x=>x.weight),weights);
 const last=e.model.used.at(-1),w=e.model.edges.find(x=>x.id===last).weight;e.perform({kind:'feedback',value:1});assert.ok(e.model.edges.find(x=>x.id===last).weight>w);
 assert.throws(()=>e.perform({kind:'feedback',value:1}),/Нет выполненных/);
 const c=calculatorDemo();const old=c.model.edges.map(x=>x.weight);scene(c,s=>s.objects.find(x=>x.name==='CALC').visible=false);run(c);assert.deepEqual(c.model.edges.map(x=>x.weight),old);
});
test('history and versioned JSON include environment and reproduce every decision',()=>{
 const e=calculatorDemo();scene(e,s=>s.objects.find(x=>x.name==='CALC').x=810);run(e);const before=JSON.stringify(e.model);
 const restored=SignalEngine.import(JSON.parse(JSON.stringify(e.export())));assert.deepEqual(restored.model,e.model);assert.deepEqual(restored.events,e.events);
 e.at(5);assert.equal(JSON.stringify(e.model),before);assert.throws(()=>SignalEngine.import({schema:'bad',operations:[]}));
});
test('invalid commands rejected without mutation',()=>{
 const e=calculatorDemo(),original=JSON.stringify(e.model);
 for(const op of [{kind:'config',values:{decay:2}},{kind:'teach',query:'',actions:[]},{kind:'threshold',id:42,value:NaN},{kind:'eval',text:'alert()'},
 {kind:'teach',query:'x',actions:[{kind:'click',object:'CALC'}]}])assert.throws(()=>e.perform(op));
 assert.equal(JSON.stringify(e.model),original);
});
test('repeated training reuses edges instead of multiplying current',()=>{
 const e=calculatorDemo(),q=e.operations[0],n=e.model.nodes.length,l=e.model.edges.length;e.perform(q);assert.equal(e.model.nodes.length,n);assert.equal(e.model.edges.length,l);run(e);assert.equal(keyOutput(e),'1700');
});
test('legacy conversion accepts demonstrated actions, never invented action sequences',()=>{
 const demo=calculatorDemo().operations[0];const commands=[...Array.from(query,value=>({kind:'input',value})),...demo.actions.map(action=>({kind:'action',action})),{kind:'positive'}];
 const e=SignalEngine.fromLegacy({schema:'kolos-graph-lab/1',commands});run(e);assert.equal(keyOutput(e),'1700');
 assert.throws(()=>SignalEngine.fromLegacy({schema:'kolos-graph-lab/1',commands:[{kind:'input',value:'a'},{kind:'positive'}]}),/Не найдены/);
});
test('two actual source pulses sum through separate excitatory edges',()=>{
 const e=calculatorDemo();start(e);until(e,()=>e.model.status==='ready');
 e.perform({kind:'config',values:{contextGain:0,observationGain:0}});
 const parent=e.model.active,l=e.model.edges.find(l=>l.from===parent&&l.kind==='excite');l.weight=.4;
 const root=e.model.nodes.find(n=>n.kind==='root').id;
 e.model.edges.push({id:99991,from:root,to:l.to,kind:'excite',weight:.4,eligibility:0});e.model.pulses=[root,parent];
 const ev=e.perform({kind:'tick'});assert.equal(ev.winner,l.to);assert.equal(ev.candidates.find(c=>c.id===l.to).activation,.8);
});
test('refractory prevents firing even with enough calculated activation',()=>{
 const e=calculatorDemo();start(e);const l=e.model.edges.find(l=>l.from===e.model.active&&l.kind==='excite');e.model.nodes.find(n=>n.id===l.to).r=2;
 const ev=e.perform({kind:'tick'});assert.equal(ev.winner,null);assert.equal(ev.candidates[0].allowed,false);assert.match(ev.candidates[0].reason,/Refractory/);
 e.perform({kind:'tick'});e.perform({kind:'wake'});const ok=e.perform({kind:'tick'});assert.equal(ok.winner,l.to);
});
test('attempt limit stops uncontrolled recurrence',()=>{
 const e=calculatorDemo();start(e);e.model.attemptTicks=600;const ev=e.perform({kind:'tick'});assert.equal(ev.decision,'limit');assert.equal(e.model.scene.executions.length,0);
});
test('negative feedback after completion penalizes last action, not the expected end',()=>{
 const e=run(calculatorDemo()),last=e.model.lastActionEdge,end=e.model.used.at(-1),before=new Map(e.model.edges.map(l=>[l.id,l.weight]));
 e.perform({kind:'feedback',value:-1});assert.ok(e.model.edges.find(l=>l.id===last).weight<before.get(last));assert.equal(e.model.edges.find(l=>l.id===end).weight,before.get(end));
});
test('zero weight does not pass a contextual pulse',()=>{
 const e=calculatorDemo();start(e);until(e,()=>e.model.status==='ready');const l=e.model.edges.find(l=>l.from===e.model.active&&l.kind==='excite');e.perform({kind:'weight',id:l.id,value:0});
 const ev=e.perform({kind:'tick'});assert.equal(ev.decision,'below');assert.equal(ev.candidates[0].activation,0);
});


function recall(e,prefix) {
 e.perform({kind:'recall',prefix});
 until(e,()=>e.model.status==='recall-complete');
 return e;
}
test('associative recall completes 1700 from prefix "добавь траты"',()=>{
 const e=recall(calculatorDemo(),'добавь траты');
 assert.equal(e.model.status,'recall-complete');
 assert.equal(e.model.continuationRaw,' 1700');
 assert.equal(e.model.continuation,'1700');
 assert.equal(e.model.scene.executions.length,0);
 assert.equal(e.model.phase,'done');
});
test('associative recall completes "траты 1700" from prefix "добавь"',()=>{
 const e=recall(calculatorDemo(),'добавь');
 assert.equal(e.model.continuationRaw,' траты 1700');
 assert.equal(e.model.continuation,'траты 1700');
 assert.equal(e.model.scene.executions.length,0);
});
test('a typed separator is not duplicated in displayed continuation',()=>{
 const e=recall(calculatorDemo(),'добавь ');
 assert.equal(e.model.continuationRaw,'траты 1700');
 assert.equal(e.model.continuation,'траты 1700');
});
test('recall emits each generated symbol through a separate winner tick, never by slicing stored text',()=>{
 const e=calculatorDemo(),before=e.events.length;
 recall(e,'добавь траты');
 const generated=e.events.slice(before).filter(ev=>ev.kind==='tick'&&ev.winner)
   .map(ev=>e.model.nodes.find(n=>n.id===ev.winner)?.label);
 assert.ok(generated.includes('1')&&generated.includes('7'));
 assert.equal(generated.filter(x=>x==='0').length,2);
 assert.equal(generated.at(-1),'Запрос введён');
});
test('two equally trained continuations stop as ambiguous instead of picking by ID',()=>{
 const e=new SignalEngine();
 const calc=[{kind:'move',x:500,y:150},{kind:'check',object:'CALC'},{kind:'click',object:'CALC'}];
 const doc=[{kind:'move',x:180,y:150},{kind:'check',object:'DOC'},{kind:'click',object:'DOC'}];
 e.perform({kind:'teach',query:'добавь траты 1700',actions:calc});
 e.perform({kind:'teach',query:'добавь доход 5000',actions:doc});
 e.perform({kind:'recall',prefix:'добавь '});
 until(e,()=>e.model.status==='ambiguous');
 assert.equal(e.model.status,'ambiguous');
 assert.match(e.model.message,/Неоднозначное продолжение/);
 assert.equal(e.model.continuation,'');
 assert.equal(e.model.used.length,0,'typed prefix must not remain eligible for reward');
});
test('recall rejects a prefix that is not present in learned input contexts',()=>{
 const e=calculatorDemo();e.perform({kind:'recall',prefix:'удали'});
 until(e,()=>e.model.status==='unknown');
 assert.equal(e.model.status,'unknown');
 assert.match(e.model.message,/префикс не найден/i);
 assert.equal(e.model.continuation,'');
});

test('positive feedback after recall strengthens generated suffix, not the typed prefix',()=>{
 const e=calculatorDemo(),rootEdge=e.model.edges.find(x=>x.from===1&&x.kind==='excite');
 const rootBefore=rootEdge.weight;
 recall(e,'добавь траты');
 const generatedIds=[...new Set(e.model.used)];
 assert.ok(generatedIds.length>=5);
 const generatedBefore=new Map(generatedIds.map(id=>[id,e.model.edges.find(x=>x.id===id).weight]));
 e.perform({kind:'feedback',value:1});
 assert.equal(rootEdge.weight,rootBefore);
 assert.ok(generatedIds.some(id=>e.model.edges.find(x=>x.id===id).weight>generatedBefore.get(id)));
});
