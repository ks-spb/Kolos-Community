import test from 'node:test';
import assert from 'node:assert/strict';
import {ResidualEngine} from '../disinhibition/core.mjs';
import {observeResidualDemonstration} from '../disinhibition/environment.mjs';
import {residualDemo,settleResidual} from '../disinhibition/demo.mjs';
import {residualPrevious} from '../disinhibition/learning.mjs';
const q='добавь траты ';
const clone=x=>structuredClone(x);
const keys=e=>e.model.scene.effects.filter(x=>x.ok&&x.action.kind==='key').map(x=>x.action.value).join('');
const start=(e,text=q+'1354')=>e.perform({kind:'start',query:text});
function until(e,predicate,limit=500){for(let i=0;i<limit;i++){if(predicate(e))return;e.perform({kind:'tick'});}throw Error('Condition not reached');}
const scene=(e,fn)=>{const s=clone(e.model.scene);fn(s);e.perform({kind:'scene',scene:s});};
const outRun=(e,text)=>{start(e,text);settleResidual(e);return e;};
const actions=(value,object='CALC',x=500,y=150)=>[{kind:'move',x,y},{kind:'check',object},{kind:'click',object},...Array.from(value,value=>({kind:'key',value}))];

test('disinhibition: full 1354 request generalizes from two actual confirmed demonstrations',()=>{
 const e=residualDemo(),before=JSON.stringify(e.model.memory);outRun(e,q+'1354');
 assert.equal(e.model.status,'complete');assert.equal(keys(e),'1354');assert.equal(e.model.scene.output,'1354');
 assert.equal(JSON.stringify(e.model.memory),before);assert.ok(e.model.input.nodes.every(n=>n.held===0&&n.consumedBy));
 assert.equal(e.model.input.nodes.filter(n=>n.consumedBy.kind==='key').length,4);
 assert.equal(e.model.scene.effects.filter(e=>e.action.kind==='click').length,1);
});
for(const value of ['1001','1111','54321','4315'])test(`disinhibition: distinct live occurrences preserve repeats and length (${value})`,()=>{
 const e=outRun(residualDemo(),q+value);assert.equal(keys(e),value);assert.equal(e.model.status,'complete');
 const sources=e.model.input.nodes.filter(n=>n.consumedBy?.kind==='key');assert.equal(new Set(sources.map(n=>n.id)).size,value.length);
});
test('disinhibition: successive requests do not reuse the old output or occurrences',()=>{
 const e=outRun(residualDemo(),q+'1354');const old=e.model.input.nodes.map(n=>n.id);start(e,q+'4315');settleResidual(e);
 assert.equal(e.model.scene.output,'4315');assert.ok(e.model.input.nodes.every(n=>!old.includes(n.id)));
});
for(const prefix of ['ввод ','прошу вывести на экран '])test(`disinhibition: context length is inferred, not two hardcoded words (${prefix})`,()=>{
 const e=outRun(residualDemo(prefix,undefined,'DOC'),prefix+'1354');assert.equal(e.model.status,'complete');assert.equal(e.model.scene.app,'DOC');assert.equal(keys(e),'1354');
 assert.equal(e.model.audit.comparisons[0].prefix,prefix);
});
test('disinhibition: arbitrary observed symbols work without digit extraction',()=>{
 const e=outRun(residualDemo('печатай ',['ABBA','BAAB']),'печатай AABBBA');assert.equal(e.model.status,'complete');assert.equal(keys(e),'AABBBA');
});
test('disinhibition: a single example does not license an unseen command',()=>{
 const e=outRun(residualDemo(q,['1700']),q+'1354');assert.equal(e.model.status,'unknown');assert.equal(e.model.scene.effects.length,0);
});
test('disinhibition: duplicate same input is not two independent examples',()=>{
 const e=outRun(residualDemo(q,['1700','1700']),q+'1354');assert.equal(e.model.status,'unknown');assert.equal(e.model.audit.comparisons[0].distinct,1);
});
test('disinhibition: a wrong output invalidates correspondence rather than pretending to learn',()=>{
 const e=residualDemo(q,['1700']);const record=observeResidualDemonstration(q+'2345',actions('4321'));
 e.perform({kind:'teach',record,approved:true});start(e,q+'1354');assert.equal(e.model.status,'unknown');assert.equal(e.model.audit.episodes.at(-1).ok,false);
});
test('disinhibition: ambiguous input-to-receipt span is reported, never longest-match guessed',()=>{
 const e=new ResidualEngine();e.perform({kind:'teach',approved:true,record:observeResidualDemonstration('11 11',actions('11'))});
 assert.equal(e.model.audit.episodes[0].ok,false);assert.match(e.model.audit.episodes[0].reason,/Неоднозначно/);
});
test('disinhibition: conflicting object demonstrations do not silently choose a target',()=>{
 const e=residualDemo();for(const v of ['1700','2345'])e.perform({kind:'teach',approved:true,record:observeResidualDemonstration(q+v,actions(v,'DOC',180))});
 start(e,q+'1354');assert.equal(e.model.status,'unknown');assert.match(e.model.message,/неоднозначность/);assert.equal(e.model.scene.effects.length,0);
});
for(const input of ['удали траты 1354','добавь траты','добавь траты ','добавь траты 13 54','добавь траты 1384'])test(`disinhibition: reject unsupported full input before external actions (${input})`,()=>{
 const e=outRun(residualDemo(),input);assert.equal(e.model.status,'unknown');assert.equal(e.model.scene.effects.length,0);assert.ok(e.model.input.nodes.every(n=>n.held===1));
});
test('disinhibition: pending key is held through effect and consumed only on receipt delivery',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{ackMode:'manual'}});start(e);
 until(e,e=>e.model.pending?.action.kind==='key');const id=e.model.pending.sourceId;
 assert.equal(keys(e),'');assert.equal(e.model.input.nodes.find(n=>n.id===id).held,1);
 e.perform({kind:'tick'});assert.equal(keys(e),'1');assert.equal(e.model.input.nodes.find(n=>n.id===id).held,1);
 for(let i=0;i<5;i++)e.perform({kind:'tick'});assert.equal(keys(e),'1');assert.equal(e.model.input.nodes.filter(n=>n.held).length,4);
 e.perform({kind:'deliver'});assert.equal(e.model.input.nodes.find(n=>n.id===id).held,0);assert.equal(e.model.input.nodes.filter(n=>n.held).length,3);
});
test('disinhibition: delay does not leak to next digit or send the first twice',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{ackMode:'delay',ackDelay:6}});start(e);
 until(e,e=>e.model.pending?.action.kind==='key'&&e.model.pending.applied);
 const id=e.model.pending.sourceId;for(let i=0;i<5;i++){e.perform({kind:'tick'});assert.equal(e.model.input.nodes.find(n=>n.id===id).held,1);assert.equal(keys(e),'1');}
 settleResidual(e);assert.equal(keys(e),'1354');assert.equal(e.model.status,'complete');
});
test('disinhibition: lost receipt times out without consuming source or resending; late delivery is explicit',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{ackMode:'drop',timeout:10}});start(e);settleResidual(e);
 assert.equal(e.model.status,'timeout');assert.equal(keys(e),'1');assert.equal(e.model.input.nodes.filter(n=>n.held).length,4);
 assert.throws(()=>start(e),/неподтверждённое/);
 e.perform({kind:'deliver'});e.perform({kind:'config',values:{ackMode:'auto'}});settleResidual(e);assert.equal(keys(e),'1354');
});
test('disinhibition: negative receipt never consumes or advances the first failed key',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{ackMode:'reject'}});start(e);settleResidual(e);
 assert.equal(e.model.status,'failed');assert.equal(keys(e),'');assert.equal(e.model.input.nodes.filter(n=>n.held).length,4);
 e.perform({kind:'config',values:{ackMode:'auto'}});e.perform({kind:'resume'});settleResidual(e);assert.equal(keys(e),'1354');
});
test('disinhibition: duplicate receipt cannot consume a second equal symbol',()=>{
 const e=residualDemo();start(e,q+'1111');until(e,e=>e.model.input.nodes.some(n=>n.consumedBy?.kind==='key'));
 const receipt=e.model.receipts.find(r=>r.action.kind==='key');const held=e.model.input.nodes.filter(n=>n.held).length;
 e.perform({kind:'receipt',receipt});assert.equal(e.model.input.nodes.filter(n=>n.held).length,held);settleResidual(e);assert.equal(keys(e),'1111');
});
test('disinhibition: wrong request/source/fabricated confirmation ignored',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{ackMode:'manual'}});start(e);until(e,e=>e.model.pending?.action.kind==='key'&&e.model.pending.applied);
 const r=clone(e.model.pending.receipt),count=e.model.input.nodes.filter(n=>n.held).length;
 e.perform({kind:'receipt',receipt:{...r,requestId:'wrong'}});e.perform({kind:'receipt',receipt:{...r,sourceId:'wrong'}});
 e.perform({kind:'receipt',receipt:{...r,after:{...r.after,output:'wrong'}}});
 assert.equal(e.model.input.nodes.filter(n=>n.held).length,count);assert.equal(e.model.pending.id,r.requestId);
});
test('disinhibition: moved CALC uses separate seek and repeat check with receipts',()=>{
 const e=residualDemo();scene(e,s=>{s.objects.find(o=>o.name==='CALC').x=820;s.objects.find(o=>o.name==='SET').x=500;});outRun(e,q+'1354');
 assert.equal(keys(e),'1354');assert.ok(e.model.scene.effects.some(r=>r.action.kind==='seek'&&r.ok));assert.deepEqual(e.model.scene.effects.filter(r=>r.action.kind==='click').map(r=>r.action.object),['CALC']);
});
test('disinhibition: missing CALC blocks before click and preserves all data occurrences',()=>{
 const e=residualDemo();scene(e,s=>s.objects.find(o=>o.name==='CALC').visible=false);outRun(e,q+'1354');
 assert.equal(e.model.status,'blocked');assert.equal(keys(e),'');assert.equal(e.model.input.nodes.filter(n=>n.held).length,4);
 assert.ok(e.model.scene.effects.every(r=>!['click','key'].includes(r.action.kind)));
 scene(e,s=>s.objects.find(o=>o.name==='CALC').visible=true);e.perform({kind:'resume'});settleResidual(e);assert.equal(keys(e),'1354');
});
test('disinhibition: environment change after selected click is checked again at effect application',()=>{
 const e=residualDemo();start(e);until(e,e=>e.model.pending?.action.kind==='click');scene(e,s=>s.objects.find(o=>o.name==='CALC').visible=false);
 e.perform({kind:'tick'});e.perform({kind:'tick'});assert.equal(e.model.status,'failed');assert.equal(keys(e),'');assert.equal(e.model.scene.app,'');
});
test('disinhibition: preview, replay and duplicate commit do not execute external actions',()=>{
 const e=residualDemo();start(e);until(e,e=>e.model.pending?.action.kind==='key');const before=clone(e.model),p=e.preview();
 assert.deepEqual(e.model,before);e.commit(p);assert.throws(()=>e.commit(p),/устарел/);const saved=clone(e.model);e.at(3);assert.deepEqual(e.model,saved);assert.equal(keys(e),'1');
});
test('disinhibition: full operation-log roundtrip includes pending delivery and observations',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{ackMode:'manual'}});start(e);until(e,e=>e.model.pending?.action.kind==='key'&&e.model.pending.applied);
 const restored=ResidualEngine.import(JSON.parse(JSON.stringify(e.export())));assert.deepEqual(restored.model,e.model);restored.perform({kind:'deliver'});assert.equal(restored.model.input.nodes.filter(n=>n.held).length,3);
});
test('disinhibition: ordering does not depend on numeric IDs or array position',()=>{
 const e=residualDemo(),ids=new Map(e.model.memory.nodes.map((n,i)=>[n.id,'random-'+(1000-i*7)]));
 e.model.memory.root=ids.get(e.model.memory.root);for(const n of e.model.memory.nodes)n.id=ids.get(n.id);
 for(const edge of e.model.memory.edges){edge.from=ids.get(edge.from);edge.to=ids.get(edge.to);edge.id='edge-'+edge.id.split('').reverse().join('');}
 e.model.memory.nodes.reverse();e.model.memory.edges.reverse();start(e);
 const qids=new Map(e.model.input.nodes.map((n,i)=>[n.id,'occ-'+(400-i*11)]));e.model.input.head=qids.get(e.model.input.head);
 for(const n of e.model.input.nodes)n.id=qids.get(n.id);for(const edge of e.model.input.edges){edge.from=qids.get(edge.from);edge.to=qids.get(edge.to);}
 e.model.input.nodes.reverse();e.model.input.edges.reverse();settleResidual(e);assert.equal(keys(e),'1354');
});
test('disinhibition: no predecessor inhibition leads to ambiguity rather than a concealed next-index',()=>{
 const e=residualDemo();e.perform({kind:'config',values:{inhibition:0}});start(e);settleResidual(e);assert.equal(e.model.status,'ambiguous');assert.notEqual(keys(e),'1354');
});
test('disinhibition: zero correspondence weight cannot be overridden by current content',()=>{
 const e=residualDemo();const motor=e.model.memory.nodes.find(n=>n.kind==='motor'&&n.value==='1'),map=e.model.memory.edges.find(x=>x.to===motor.id&&x.kind==='corresponds');
 e.perform({kind:'weight',id:map.id,value:0});start(e);settleResidual(e);assert.equal(e.model.status,'below');assert.equal(keys(e),'');
});
test('disinhibition: unapproved demonstrations do not participate; receipts cannot be forged',()=>{
 const e=new ResidualEngine(),r=observeResidualDemonstration(q+'1700',actions('1700'));e.perform({kind:'teach',record:r});assert.equal(e.model.audit.comparisons.length,0);
 const bad=clone(r);bad.confirmations[0].ok=false;const saved=clone(e.model);assert.throws(()=>e.perform({kind:'teach',record:bad}),/Подтверждения/);assert.deepEqual(e.model,saved);
});
test('disinhibition: bad import/config/scene changes are transactional',()=>{
 const e=residualDemo(),before=clone(e.model);for(const op of [{kind:'config',values:{inhibition:99}},{kind:'eval'},{kind:'scene',scene:{objects:[]}}])assert.throws(()=>e.perform(op));assert.deepEqual(e.model,before);
});
