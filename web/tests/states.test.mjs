import {persistentGraph} from '../states/environment.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {StateEngine,teachExamples,prepareCase,runCase} from '../states/core.mjs';
import {defaultWorld,observeWorld,observationKey,demonstration,iconDemonstrationActions,visibleIcons,worldGuard} from '../states/environment.mjs';
const stop=new Set(['complete','blocked','failed','unknown','ambiguous','timeout','limit']);
function advance(e,predicate=()=>stop.has(e.model.status),max=1500){for(let i=0;i<max&&!predicate();i++)e.perform({kind:'tick'});return e;}
function start(e,q){e.perform({kind:'start',query:q});return e;}
function successful(e){return e.model.world.effects.filter(r=>r.ok).map(r=>r.action);}
test('confirmed motor trace permits Enter without inventing a visible target',()=>{
 const o=observeWorld(defaultWorld());o.icons=[];o.features=[];o.last_clicked='A';
 assert.equal(worldGuard(o,{kind:'enter',object:'A'}),'');
 assert.match(worldGuard(o,{kind:'click',object:'A'}),/Не видна/);
 assert.match(worldGuard(o,{kind:'check',object:'A'}),/Не видна/);
 o.selected='B';assert.match(worldGuard(o,{kind:'enter',object:'A'}),/Не видна/);
 o.selected='';o.object_issues={A:'ambiguous'};assert.equal(worldGuard(o,{kind:'enter',object:'A'}),'');
 assert.match(worldGuard(o,{kind:'click',object:'A'}),/Не видна/);
 o.selected='A';assert.equal(worldGuard(o,{kind:'enter',object:'A'}),'');
 delete o.last_clicked;assert.match(worldGuard(o,{kind:'enter',object:'A'}),/Не видна/);
});
for(let i=1;i<=4;i++)test(`Required test ${i}: state/goal/input experiment passes`,()=>{const r=runCase(i);assert.equal(r.pass,true);if(i===4){assert.equal(r.engine.model.lessons.length,1);assert.equal(r.output,'2345');}});
test('test 1: selection does not open window until Enter, window occludes all desktop icons',()=>{
 const {engine:e,query}=prepareCase(1);start(e,query);advance(e,()=>e.model.world.selected==='A');assert.equal(e.model.world.surface,'desk');
 advance(e);assert.equal(e.model.world.surface,'window');assert.deepEqual(visibleIcons(e.model.world).map(x=>x.id),['X','D','E']);
 assert.equal(successful(e).filter(a=>a.kind==='enter').length,1);
});
test('test 3 composes only two observed lessons; no X A Enter demonstration',()=>{
 const r=runCase(3),e=r.engine;
 assert.equal(e.model.lessons.length,2);assert.deepEqual(e.model.lessons.map(l=>l.receipts.filter(r=>r.action.kind==='click').map(r=>r.action.object)),[['A'],['X']]);
 assert.deepEqual(successful(e).filter(a=>a.kind==='click').map(a=>a.object),['X','A']);
 const route=e.events.find(ev=>ev.kind==='route');assert.ok(route);assert.ok(e.events.some(ev=>ev.kind==='spread'&&ev.flows.length));
 assert.equal(e.model.recoveries,1);assert.equal(e.model.heldGoal,false);
});

test('recovery recalls learned MOVE before checking a recognizable but ambiguous instance',()=>{
 const {engine:e,query}=prepareCase(3);start(e,query);
 advance(e,()=>successful(e).some(a=>a.kind==='click'&&a.object==='X')&&!e.model.pending);
 e.model.observed.icons=e.model.observed.icons.filter(i=>i.id!=='A');
 e.model.observed.object_issues={A:'ambiguous instances'};
 advance(e,()=>!!e.model.pending,10);
 const ev=e.events.at(-1);
 assert.equal(ev.kind,'dispatch');assert.deepEqual(e.model.pending.action,{kind:'move',x:200,y:190});
 assert.equal(e.model.pending.relocate,true);assert.equal(e.model.heldGoal,true);
 assert.ok(ev.flows.some(f=>f.aggregation==='motor-demand'));
 advance(e);assert.equal(e.model.status,'complete');
 assert.deepEqual(successful(e).filter(a=>a.kind==='move').map(a=>[a.x,a.y]),[[200,190],[920,75],[200,190]]);
 assert.deepEqual(successful(e).filter(a=>a.kind==='click').map(a=>a.object),['X','A']);
 const recalled=e.events.findIndex(ev=>ev.kind==='dispatch'&&ev.flows?.some(f=>f.aggregation==='motor-demand'));
 assert.equal(e.events.slice(recalled+1).find(ev=>ev.kind==='dispatch').action.kind,'check');
});
test('without observed close transition the hidden target is not clicked',()=>{
 const e=new StateEngine(),w=defaultWorld();e.perform({kind:'teach',record:demonstration('open',w,[...iconDemonstrationActions(w,'A'),{kind:'enter',object:'A'}])});w.surface='window';e.perform({kind:'world',world:w});advance(start(e,'open'));
 assert.equal(e.model.status,'blocked');assert.equal(successful(e).filter(a=>a.kind==='click').length,0);assert.equal(e.model.heldGoal,true);
});
test('zero backward edge suppresses recovery instead of triggering hardcoded close',()=>{
 const {engine:e,query}=prepareCase(3),t=e.model.memory.nodes.find(n=>n.kind==='transition'&&n.label==='CLICK X');
 const edge=e.model.memory.edges.find(x=>x.kind==='backward'&&x.to===t.id);e.perform({kind:'weight',id:edge.id,value:0});advance(start(e,query));
 assert.equal(e.model.status,'blocked');assert.equal(successful(e).filter(a=>a.kind==='click').length,0);
});
test('state signatures ignore icon coordinates and cursor but distinguish selected icon',()=>{
 const w=defaultWorld(),key=observationKey(observeWorld(w));w.cursor.x=50;w.surfaces.desk.icons[0].x=300;assert.equal(observationKey(observeWorld(w)),key);
 w.selected='A';assert.notEqual(observationKey(observeWorld(w)),key);
});
test('moved close button is found through observation and checked before click',()=>{
 const {engine:e,query}=prepareCase(3);e.perform({kind:'perturb',id:'X',x:70,y:70});advance(start(e,query));assert.equal(e.model.status,'complete');
 const clicks=e.model.world.effects.filter(r=>r.action.kind==='click'&&r.action.object==='X');assert.equal(clicks.length,1);assert.equal(clicks[0].before.cursor.x,70);
});
test('hidden close button has no executable route',()=>{const {engine:e,query}=prepareCase(3);e.perform({kind:'perturb',id:'X',hidden:true});advance(start(e,query));assert.equal(e.model.status,'blocked');assert.equal(successful(e).filter(a=>a.kind==='click').length,0);});

test('fresh target resumes a suspended check despite unrelated desktop changes',()=>{
 const e=new StateEngine(),w=defaultWorld();
 e.perform({kind:'teach',record:demonstration('o1',w,iconDemonstrationActions(w,'A'))});
 start(e,'o1');advance(e,()=>successful(e).length===1&&!e.model.pending);
 e.perform({kind:'perturb',id:'A',hidden:true});e.perform({kind:'tick'});
 assert.ok(e.model.plan);assert.equal(e.model.pending,null);
 e.perform({kind:'tick'});assert.equal(e.model.pending,null);
 const fresh=structuredClone(e.model.world);fresh.surfaces.desk.icons[0].hidden=false;
 fresh.surfaces.desk.icons.push({id:'NEW',label:'New',x:600,y:450});
 e.perform({kind:'disturb',world:fresh});
 assert.equal(e.perform({kind:'tick'}).kind,'dispatch');
 assert.deepEqual(e.model.pending.action,{kind:'check',object:'A'});
 assert.equal(e.model.plan,null);assert.deepEqual(successful(e).map(a=>a.kind),['move']);
});

test('reappearing target is relocated using fresh coordinates',()=>{
 const e=new StateEngine(),w=defaultWorld();
 e.perform({kind:'teach',record:demonstration('o1',w,iconDemonstrationActions(w,'A'))});
 start(e,'o1');advance(e,()=>successful(e).length===1&&!e.model.pending);
 e.perform({kind:'perturb',id:'A',hidden:true});e.perform({kind:'tick'});
 e.perform({kind:'perturb',id:'A',hidden:false,x:300,y:400});e.perform({kind:'tick'});
 assert.deepEqual(e.model.pending.action,{kind:'move',x:300,y:400});
 assert.equal(e.model.pending.relocate,true);
});
test('renamed icons and surface IDs: no A/X/desktop semantics in planner',()=>{
 const e=new StateEngine(),w=defaultWorld();w.surfaces.desk.icons[0].id='OMEGA';w.surfaces.desk.icons[0].label='go';w.surfaces.window.icons[0].id='BACK';
 w.surfaces.worktop=w.surfaces.desk;delete w.surfaces.desk;w.surface='worktop';w.surfaces.window.icons[0].click='worktop';w.surfaces.calculator.icons[0].click='worktop';
 e.perform({kind:'teach',record:demonstration('команда один',w,[...iconDemonstrationActions(w,'OMEGA'),{kind:'enter',object:'OMEGA'}])});w.surface='window';e.perform({kind:'teach',record:demonstration('команда два',w,iconDemonstrationActions(w,'BACK'))});e.perform({kind:'world',world:w});advance(start(e,'команда один'));
 assert.equal(e.model.status,'complete');assert.deepEqual(successful(e).filter(a=>a.kind==='click').map(a=>a.object),['BACK','OMEGA']);
});
test('two-hop recovery spreads over two separately learned transitions',()=>{
 const e=new StateEngine(),w=defaultWorld();w.surfaces.outer={label:'Outer',field:null,icons:[{id:'RETURN',label:'R',x:500,y:120,click:'window'}]};
 e.perform({kind:'teach',record:demonstration('open',w,[...iconDemonstrationActions(w,'A'),{kind:'enter',object:'A'}])});
 w.surface='window';e.perform({kind:'teach',record:demonstration('close',w,iconDemonstrationActions(w,'X'))});
 w.surface='outer';e.perform({kind:'teach',record:demonstration('back',w,iconDemonstrationActions(w,'RETURN'))});e.perform({kind:'world',world:w});advance(start(e,'open'));
 assert.equal(e.model.status,'complete');assert.deepEqual(successful(e).filter(a=>a.kind==='click').map(a=>a.object),['RETURN','X','A']);assert.equal(e.model.recoveries,2);
});
test('same strength competing routes never tie-break by ID',()=>{
 const {engine:e,query}=prepareCase(3),t=e.model.memory.nodes.find(n=>n.kind==='transition'&&n.label==='CLICK X'),clone=structuredClone(t);clone.id='alternative';e.model.memory.nodes.push(clone);
 for(const edge of e.model.memory.edges.filter(x=>x.kind==='backward'&&x.to===t.id))e.model.memory.edges.push({...edge,id:'edge-alt',to:clone.id});
 advance(start(e,query));assert.equal(e.model.status,'ambiguous');assert.equal(successful(e).filter(a=>a.kind==='click').length,0);
});
test('IDs and array storage order do not encode route or digits',()=>{
 for(const i of [3,4]){const {engine:e,query}=prepareCase(i),mapping=new Map(e.model.memory.nodes.map((n,j)=>[n.id,'arbitrary-'+(10000-j*17)]));
 for(const n of e.model.memory.nodes){n.id=mapping.get(n.id);for(const k of ['from','to','first','last','pre','post'])if(n[k])n[k]=mapping.get(n[k]);}
 for(const edge of e.model.memory.edges){edge.from=mapping.get(edge.from);edge.to=mapping.get(edge.to);edge.id='permuted-'+edge.id;}
 e.model.memory.root=mapping.get(e.model.memory.root);for(const c of e.model.commands){c.first=mapping.get(c.first);c.context=mapping.get(c.context);}
 e.model.memory.nodes.reverse();e.model.memory.edges.reverse();advance(start(e,query));assert.equal(e.model.status,'complete');if(i===4)assert.equal(e.model.world.output,'2345');}
});
test('manual receipt: close effect does not release original goal before delivered',()=>{
 const {engine:e,query}=prepareCase(3);e.perform({kind:'config',values:{ackMode:'manual'}});start(e,query);
 for(let i=0;i<500;i++){e.perform({kind:'tick'});if(e.model.pending?.receipt){if(e.model.pending.action.kind==='click')break;e.perform({kind:'deliver'});}}
 assert.equal(e.model.pending.action.object,'X');assert.equal(e.model.world.surface,'desk');assert.equal(e.model.heldGoal,true);assert.ok(e.model.detour);
 const count=e.model.world.effects.length;e.perform({kind:'tick'});e.perform({kind:'tick'});assert.equal(e.model.world.effects.length,count);
 const receipt=structuredClone(e.model.pending.receipt);e.perform({kind:'deliver'});assert.equal(e.model.detour,null);const state=JSON.stringify(e.model.occ);
 e.perform({kind:'receipt',receipt});assert.equal(JSON.stringify(e.model.occ),state);
});
test('lost receipt: no repeated click, no false completion',()=>{
 const {engine:e,query}=prepareCase(1);e.perform({kind:'config',values:{ackMode:'drop',timeout:8}});advance(start(e,query));
 assert.equal(e.model.status,'timeout');assert.equal(e.model.world.effects.length,1);assert.equal(e.model.heldGoal,true);
});
test('observation changed after click dispatch: physical guard rejects action',()=>{
 const {engine:e,query}=prepareCase(1);start(e,query);advance(e,()=>e.model.pending?.action.kind==='click');e.perform({kind:'perturb',id:'A',hidden:true});advance(e);
 assert.equal(e.model.status,'failed');assert.equal(e.model.world.surface,'desk');assert.equal(e.model.heldGoal,true);
});
test('preview and repeated commit never duplicate actual action',()=>{
 const {engine:e,query}=prepareCase(1);start(e,query);advance(e,()=>!!e.model.pending);const original=e.export(),p=e.preview();assert.deepEqual(e.export(),original);
 e.commit(p);assert.throws(()=>e.commit(p),/устарел/);assert.equal(e.model.world.effects.length,1);
});
test('single expense 1700 demonstration plus earlier 5432 key exposure support new sequences',()=>{
 for(const text of ['2345','1354','1001','1111','54321','70005']){const {engine:e}=prepareCase(4),before=JSON.stringify(persistentGraph(e.model.memory));advance(start(e,'добавь траты '+text));
 assert.equal(e.model.status,'complete');assert.equal(e.model.world.output,text);assert.equal(JSON.stringify(persistentGraph(e.model.memory)),before);
 assert.ok(e.model.occ.filter(q=>q.consumedBy&&!q.consumedBy.startsWith('internal:')).every(q=>!q.held));}
});
test('the first learned MOVE uses the current icon coordinates without rewriting training',()=>{
 const {engine:e,query}=prepareCase(1),first=e.model.commands[0].first;
 const learnedMove=structuredClone(e.model.memory.nodes.find(n=>n.id===first).action);
 e.perform({kind:'perturb',id:'A',x:230,y:190});advance(start(e,query));
 assert.equal(e.model.status,'complete');
 assert.deepEqual(successful(e).filter(a=>a.kind==='move').map(a=>[a.x,a.y]),[[230,190]]);
 assert.deepEqual(e.model.memory.nodes.find(n=>n.id===first).action,learnedMove);
 assert.equal(successful(e).filter(a=>a.kind==='click').length,1);
 assert.equal(successful(e).filter(a=>a.kind==='enter').length,1);
});

test('two typing lessons with varied hover positions generalize across both observed digit sets',()=>{
 for(const separator of ['', ' ']){
  const e=new StateEngine(),w=defaultWorld();e.perform({kind:'config',values:{plasticity:0}});
  for(const [digits,shift]of [['12345',0],['6789',9]]){
   const shown=structuredClone(w);shown.surfaces.desk.icons[2].y+=shift;const value=Array.from(digits).join(separator);
   e.perform({kind:'teach',record:demonstration('впиши '+value,shown,[...iconDemonstrationActions(shown,'CALC'),...Array.from(value,value=>({kind:'key',value}))])});
  }
  assert.equal(e.model.commands.length,1);const before=persistentGraph(e.model.memory),target=Array.from('1346').join(separator);
  advance(start(e,'впиши '+target));assert.equal(e.model.status,'complete');assert.equal(e.model.world.output,target);
  assert.equal(e.model.lessons.length,2);assert.deepEqual(persistentGraph(e.model.memory),before);
 }
});

test('legacy duplicate command paths ignore hover position while retaining different field conflicts',()=>{
 for(const conflict of [false,true]){
  const e=new StateEngine(),w=defaultWorld();e.perform({kind:'config',values:{plasticity:0}});
  e.perform({kind:'teach',record:demonstration('впиши 12345',w,[...iconDemonstrationActions(w,'CALC'),...Array.from('12345',value=>({kind:'key',value}))])});
  const saved=structuredClone(e.model.commands);e.model.commands=[];
  const shown=structuredClone(w);shown.surfaces.desk.icons[2].y+=9;if(conflict)shown.surfaces.calculator.field='OTHER';
  e.perform({kind:'teach',record:demonstration('впиши 6789',shown,[...iconDemonstrationActions(shown,'CALC'),...Array.from('6789',value=>({kind:'key',value}))])});
  e.model.commands=[...saved,...e.model.commands];e.model.commands.forEach((c,i)=>{c.signature='legacy-coordinate-signature-'+i;});
  advance(start(e,'впиши 1346'));
  assert.equal(e.model.status,conflict?'unknown':'complete');
  assert.equal(e.model.world.output,conflict?'':'1346');assert.equal(e.model.commands.length,2);
  if(conflict)assert.equal(e.model.world.effects.length,0);
 }
});
test('missing input, wrong command, wrong case, unseen alphabet never substitute 1700',()=>{
 for(const q of ['добавь траты','добавь траты ','ДОБАВЬ траты 2345','удали траты 2345','добавь траты Z']){const {engine:e}=prepareCase(4);start(e,q);assert.equal(e.model.status,'unknown');assert.equal(e.model.world.effects.length,0);}
});
test('generic learned prefix has no fixed word count or numeric parser',()=>{
 const e=new StateEngine(),w=defaultWorld();e.perform({kind:'teach',record:demonstration('ввести сейчас тест AB',w,[...iconDemonstrationActions(w,'CALC'),{kind:'key',value:'A'},{kind:'key',value:'B'}])});advance(start(e,'ввести сейчас тест BBA'));assert.equal(e.model.world.output,'BBA');
});
test('keyboard waits for acknowledgment before consuming occurrence',()=>{
 const {engine:e,query}=prepareCase(4);start(e,query);advance(e,()=>e.model.entry&&e.model.memory.nodes.find(n=>n.id===e.model.entry)?.action.kind==='drive'&&!e.model.pending);
 e.perform({kind:'config',values:{ackMode:'manual'}});advance(e,()=>e.model.pending?.receipt);assert.equal(e.model.world.output,'2');
 const q=e.model.occ.find(q=>q.held);assert.equal(q.value,'2');assert.equal(q.held,true);e.perform({kind:'deliver'});assert.equal(e.model.occ.find(q=>q.held).value,'3');
});
test('four-case suite does not teach the test input or update any weight',()=>{for(let i=1;i<=4;i++){const r=runCase(i);assert.equal(r.pass,true);assert.ok(!r.engine.model.lessons.some(l=>l.query.includes('2345')));}});
test('export/import and history are deterministic and cause no live effects',()=>{const e=runCase(3).engine,snapshot=e.export(),before=JSON.stringify(e.model);const other=StateEngine.import(snapshot);assert.deepEqual(other.model,e.model);e.at(20);assert.equal(JSON.stringify(e.model),before);assert.throws(()=>StateEngine.import({schema:'bad'}));});
test('unknown command invalidates an earlier preview revision',()=>{const e=prepareCase(1).engine,p=e.preview({kind:'start',query:'открой окно'});e.perform({kind:'start',query:'nonsense'});assert.throws(()=>e.commit(p),/устарел/);});
test('training cannot accept forged observation of a successful outcome',()=>{const w=defaultWorld(),r=demonstration('open',w,iconDemonstrationActions(w,'A'));r.receipts.at(-1).after.selected='B';assert.throws(()=>new StateEngine().perform({kind:'teach',record:r}),/подменены/);});


test('test 4 alphabet is learned from prior typing, not preinstalled or target-query training',()=>{
 const {engine:e}=prepareCase(4);
 assert.equal(e.model.lessons.length,1);assert.equal(e.model.lessons[0].query,'добавь траты 1700');
 assert.equal(e.model.exposures.length,1);assert.equal(e.model.exposures[0].receipts.map(r=>r.action.value).join(''),'5432');
 assert.deepEqual(e.model.memory.nodes.filter(n=>n.kind==='motor').map(n=>n.value).sort(),['0','1','2','3','4','5','7']);
 assert.ok(e.model.memory.nodes.filter(n=>n.kind==='motor').every(n=>n.evidence.length));
});
test('without prior keyboard exposure, a single 1700 lesson cannot silently invent KEY 2 or KEY 8',()=>{
 const w=defaultWorld(),e=new StateEngine();
 e.perform({kind:'teach',record:demonstration('добавь траты 1700',w,[...iconDemonstrationActions(w,'CALC'),...Array.from('1700',value=>({kind:'key',value}))])});
 advance(start(e,'добавь траты 2345'));assert.equal(e.model.status,'unknown');assert.equal(e.model.world.effects.length,0);
 assert.ok(!e.model.memory.nodes.some(n=>n.kind==='motor'&&n.value==='2'));
 const {engine:f}=prepareCase(4);advance(start(f,'добавь траты 8345'));assert.equal(f.model.status,'unknown');
});
test('exposure receipt validation rejects forged prior key evidence transactionally',()=>{
 const w=defaultWorld();w.surface='calculator';w.focus='FIELD';const e=new StateEngine();
 const r=demonstration('earlier',w,[{kind:'key',value:'5'}]);r.receipts[0].after.output='4';
 const before=e.export();assert.throws(()=>e.perform({kind:'expose',record:r}),/Подменены/);assert.deepEqual(e.export(),before);
});


test('window recovery and new expense digits compose in one combined memory',()=>{
 const e=teachExamples();teachExamples(e,'expense');e.perform({kind:'config',values:{plasticity:0}});const w=defaultWorld();w.surface='window';e.perform({kind:'world',world:w});
 const memory=JSON.stringify(persistentGraph(e.model.memory));advance(start(e,'добавь траты 2345'));
 assert.equal(e.model.status,'complete');assert.equal(e.model.world.output,'2345');assert.equal(JSON.stringify(persistentGraph(e.model.memory)),memory);
 assert.deepEqual(e.model.world.effects.filter(r=>r.ok&&r.action.kind==='click').map(r=>r.action.object),['X','CALC']);
});
test('decay changes propagation time but not learned detour target',()=>{
 const rounds=[];for(const decay of [.25,.65]){const {engine:e,query}=prepareCase(3);e.perform({kind:'config',values:{decay}});advance(start(e,query));assert.equal(e.model.status,'complete');rounds.push(e.events.filter(x=>x.kind==='spread').length);}
 assert.notEqual(rounds[0],rounds[1]);
});
