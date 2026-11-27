import {persistentGraph} from '../states/environment.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {StateEngine} from '../states/core.mjs';
import {prepareCapability} from '../states/capability-cases.mjs';
import {prepareLanguage,runLanguageExperiment,LANGUAGE_PAIRS} from '../states/language-cases.mjs';
import {demonstration,defaultWorld,iconDemonstrationActions} from '../states/environment.mjs';
const copy=x=>structuredClone(x);
function decode(e,text,config={}){e.perform({kind:'language-start',phrase:text,config});for(let i=0;i<3200&&e.model.phase==='language'&&e.model.status==='running';i++)e.perform({kind:'tick'});return e;}
const goal=value=>({kind:'field',focus:'FIELD',value});
function pair(e,text,value){e.perform({kind:'language-teach',phrase:text,goal:goal(value)});}

test('12: unseen full phrase creates imagery then reaches 1354 with no target/route input',()=>{
 const {engine:e,...r}=runLanguageExperiment();assert.equal(r.pass,true);assert.deepEqual(r.clicks,['X','CALC']);
 assert.ok(!e.model.languageMemory.lessons.some(l=>l.phrase.includes('1354')));
 assert.deepEqual(e.operations.find(o=>o.kind==='language-start'),{kind:'language-start',phrase:'я хочу увидеть 1354 в поле'});
 assert.equal(e.model.imagery.source.kind,'language');assert.equal(e.model.imagery.confirmations[0].source,'external');
 assert.ok(e.model.language.readout.binding.every(b=>b.edge&&e.model.language.chars[b.source]===b.char));
});
for(const text of ['я хочу увидеть 54321 в поле','пусть в поле будет 1001','сделай в поле 1111 пожалуйста'])test('learned phrasing retains new value/order: '+text,()=>{
 const e=prepareLanguage().engine;decode(e,text);assert.equal(e.model.language.status,'imagined');assert.equal(e.model.world.effects.length,0);
});
for(const text of ['не хочу увидеть 1354 в поле','я хочу не увидеть 1354 в поле','я хочу увидеть 1354 в другом поле','я хочу увидеть в поле','я хочу увидеть 8345 в поле','я хочу увидеть 1354 в поле потом','Я хочу увидеть 1354 в поле','я хочу увидеть 1354 в поле.','я хочу увидеть 1354 1523 в поле'])test('unlearned or incomplete full wording has no image/action: '+text,()=>{
 const e=prepareLanguage().engine;decode(e,text);assert.equal(e.model.status,'unknown');assert.equal(e.model.imagery,null);assert.equal(e.model.world.effects.length,0);
});
test('world/motor lessons alone cannot supply language meaning',()=>{
 const e=prepareCapability(9).engine;decode(e,'я хочу увидеть 1354 в поле');assert.equal(e.model.status,'unknown');assert.equal(e.model.imagery,null);
});
test('a single pair and its duplicates cannot masquerade as evidence of variable role',()=>{
 const e=prepareCapability(9).engine;for(let i=0;i<4;i++)pair(e,'я хочу увидеть 1700 в поле','1700');decode(e,'я хочу увидеть 1001 в поле');
 assert.equal(e.model.status,'unknown');assert.equal(e.model.language.status,'below');
});
test('training changes only language memory, never world observations or motor memory',()=>{
 const e=prepareCapability(9).engine,w=copy(e.model.world),m=copy(e.model.memory),obs=copy(e.model.observed);
 pair(e,'я хочу увидеть 1700 в поле','1700');assert.deepEqual(e.model.world,w);assert.deepEqual(e.model.memory,m);assert.deepEqual(e.model.observed,obs);
});
test('value may precede the words; no suffix-number parser',()=>{
 const e=prepareCapability(9).engine;pair(e,'1700 пусть окажется здесь','1700');pair(e,'2345 пусть окажется здесь','2345');decode(e,'3521 пусть окажется здесь');assert.equal(e.model.language.goal.value,'3521');
});
test('letters work through exactly the same grounding without digit recognition',()=>{
 const e=new StateEngine(),w=defaultWorld();e.perform({kind:'teach',record:demonstration('teach AB',w,[...iconDemonstrationActions(w,'CALC'),{kind:'key',value:'A'},{kind:'key',value:'B'}])});
 pair(e,'zorp AB glip','AB');pair(e,'zorp BA glip','BA');decode(e,'zorp BBA glip');assert.equal(e.model.language.goal.value,'BBA');
});
test('a taught state phrase also creates an image from learned semantics',()=>{
 const e=prepareCapability(9).engine,features=e.model.memory.nodes.find(n=>n.kind==='state'&&n.features.includes('visible:A')&&!n.features.some(f=>f.startsWith('selected:'))).features;
 e.perform({kind:'language-teach',phrase:'покажи рабочий стол',goal:{kind:'state',features}});decode(e,'покажи рабочий стол');assert.deepEqual(e.model.language.goal,{kind:'state',features:features.slice().sort()});
});
test('contradictory phrase/image teaching stops competing semantics without ID tie-break',()=>{
 const e=prepareLanguage().engine;e.model.memory.nodes.push({id:'other-field-state',kind:'state',features:['focus:OTHER'],key:'["focus:OTHER"]'});
 for(const [text,value]of LANGUAGE_PAIRS.slice(0,2))e.perform({kind:'language-teach',phrase:text,goal:{kind:'field',focus:'OTHER',value}});
 decode(e,'я хочу увидеть 1354 в поле');assert.equal(e.model.status,'ambiguous');assert.equal(e.model.imagery,null);
});
for(const kind of ['literal','ground','readout','support'])test('causal lesion: zero '+kind+' edges removes the capability',()=>{
 const e=prepareLanguage().engine;for(const edge of e.model.languageMemory.edges.filter(e=>e.kind===kind))e.perform({kind:'language-weight',id:edge.id,value:0});
 decode(e,'я хочу увидеть 1354 в поле');assert.equal(e.model.status,'unknown');assert.equal(e.model.imagery,null);
});
test('grounding destination matters: swapping learned referent changes the decoded content',()=>{
 const e=prepareLanguage().engine,lex=e.model.languageMemory,glyph=lex.nodes.find(n=>n.kind==='glyph'&&n.char==='3');
 const edge=lex.edges.find(e=>e.kind==='ground'&&e.from===glyph.id);edge.to=e.model.memory.nodes.find(n=>n.kind==='symbol'&&n.value==='4').id;
 decode(e,'я хочу увидеть 1354 в поле');assert.equal(e.model.language.goal.value,'1454');
});
test('decay changes actual propagation time without changing inferred value',()=>{
 const ticks=[];for(const decay of [.2,.7]){const e=prepareLanguage().engine;decode(e,'я хочу увидеть 1354 в поле',{decay});ticks.push(e.model.tick);assert.equal(e.model.language.goal.value,'1354');}assert.notEqual(...ticks);
});
test('IDs and storage order do not decide language semantics',()=>{
 const e=prepareLanguage().engine,mem=e.model.languageMemory,map=new Map(mem.nodes.map((n,i)=>[n.id,'alias-'+(500-i*3)]));
 for(const n of mem.nodes)n.id=map.get(n.id);
 for(const edge of mem.edges){edge.from=map.get(edge.from)||edge.from;edge.to=map.get(edge.to)||edge.to;if(edge.glyph)edge.glyph=map.get(edge.glyph);if(edge.assembly)edge.assembly=map.get(edge.assembly);edge.id='x'+edge.id;}
 mem.nodes.reverse();mem.edges.reverse();decode(e,'я хочу увидеть 1354 в поле');assert.equal(e.model.language.goal.value,'1354');
});
test('preview and history never execute or teach live world, export/replay deterministic',()=>{
 const e=prepareLanguage().engine;decode(e,'я хочу увидеть 1354 в поле');const before=copy(e.model),p=e.preview();assert.deepEqual(e.model,before);e.at(4);assert.deepEqual(e.model,before);assert.deepEqual(StateEngine.import(e.export()).model,before);
 e.commit(p);assert.throws(()=>e.commit(p));
});
test('training rejects ambiguous/missing alignment transactionally',()=>{
 for(const text of ['1700 и 1700','нет нужных символов']){const e=prepareCapability(9).engine,before=e.export();assert.throws(()=>pair(e,text,'1700'));assert.deepEqual(e.export(),before);}
});
test('partial linguistic activation never creates image before complete text has won',()=>{
 const e=prepareLanguage().engine;e.perform({kind:'language-start',phrase:'я хочу увидеть 1354 в поле'});
 for(let i=0;i<60;i++){e.perform({kind:'tick'});assert.equal(e.model.imagery,null);assert.equal(e.model.world.effects.length,0);}
});
test('imagined language output cannot complete without sensory evidence',()=>{
 const e=prepareLanguage().engine;decode(e,'я хочу увидеть 1354 в поле');for(let i=0;i<16;i++)e.perform({kind:'tick'});
 assert.ok(e.model.imagery.ready>.99);assert.equal(e.model.imagery.match,0);assert.equal(e.model.imagery.confirmations.length,0);assert.equal(e.model.world.effects.length,0);
});
