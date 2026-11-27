import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { Engine, initialState, exportExperiment, importExperiment, visibleName } from '../.build/engine.js';
const input = (engine, text) => Array.from(text).forEach(value => engine.execute({kind:'input',value}));
const command = (engine,kind) => engine.execute({kind});
const view = {seconds:1,positions:{},input:''};
function trained(){ const e=new Engine();input(e,'абв');command(e,'positive');command(e,'reset');input(e,'аб');return e; }
test('deterministic seeded state; reserved IDs',()=>{const e=new Engine();assert.deepEqual(e.state,initialState());const v=e.execute({kind:'input',value:'а'});assert.equal(v.edge.id,4);assert.equal(v.to,4);assert.equal(v.after.activeId,4);});
test('preview never mutates live state; one commit per event',()=>{const e=new Engine();const s=JSON.stringify(e.state);const ev=e.preview({kind:'input',value:'а'});assert.equal(JSON.stringify(e.state),s);assert.equal(e.events.length,0);e.commit(ev);assert.throws(()=>e.commit(ev),/устарел/);assert.equal(e.events.length,1);});
for (const text of ['абв','абабаба','ааааа','кот котик кот','01239\n\t😀😀Aа']) {
 test(`SQL reference parity after every symbol: ${JSON.stringify(text)}`,()=>{
  const expected=JSON.parse(execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),['tests/reference.py'],{input:JSON.stringify({text}),encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}}));
  const e=new Engine();Array.from(text).forEach((value,i)=>{e.execute({kind:'input',value});assert.deepEqual({nodes:e.state.nodes,edges:e.state.edges,activeId:e.state.runtime.activeId,online:e.state.runtime.online},expected[i]);});
 });
}
test('points reused, self-loops and duplicate links remain separate',()=>{const e=new Engine();input(e,'ааа');assert.equal(e.state.nodes.length,4);assert.equal(e.state.edges.length,3);assert.deepEqual(e.state.edges.slice(1).map(v=>[v.from,v.to]),[[4,4],[4,4]]);assert.equal(e.state.nodes.find(n=>n.id===4).signal,4);});
test('opposite directions not merged in memory',()=>{const e=new Engine();input(e,'абаб');assert.deepEqual(e.state.edges.map(v=>[v.from,v.to]),[[3,4],[4,5],[5,4],[4,5]]);});
test('old selected link and new recorded link are distinct',()=>{const e=trained();const ev=command(e,'continue');assert.equal(e.state.runtime.answer,'в');assert.equal(ev.usedEdgeId,6);assert.equal(ev.edge.id,11);assert.equal(e.state.runtime.terminal,false);command(e,'continue');assert.equal(e.state.runtime.terminal,true);assert.equal(e.state.runtime.activeId,1);assert.equal(e.state.runtime.answer,'в');});
test('no invented continuation or graph change without a successful path',()=>{const e=new Engine();input(e,'аб');const before=JSON.stringify(e.state.edges);command(e,'continue');assert.equal(e.state.runtime.status,'Продолжение не найдено');assert.equal(JSON.stringify(e.state.edges),before);});
test('a negative branch is rejected; next confirmed candidate is used',()=>{const e=new Engine();input(e,'абв');command(e,'negative');command(e,'reset');input(e,'абг');command(e,'positive');command(e,'reset');input(e,'аб');const ev=command(e,'continue');assert.equal(e.state.runtime.answer,'г');assert.ok(ev.rejected.some(r=>r.reason.includes('отрицательной')));});
test('negative feedback resets only current signal and finds real max',()=>{const e=new Engine();input(e,'абв');const ev=command(e,'negative');assert.equal(e.state.nodes.find(n=>n.name==='в').signal,0);assert.equal(e.state.runtime.activeId,e.state.nodes.find(n=>n.name==='б').id);assert.equal(ev.edge.to,2);});
test('replay snapshots do not add events or links',()=>{const e=trained();command(e,'continue');const before=JSON.stringify(e.state);for(let i=0;i<=e.events.length;i++)e.at(i);assert.equal(JSON.stringify(e.state),before);assert.equal(e.at(0).edges.length,0);});
test('export/import reproduces every state and restores paused queue',()=>{const e=trained();command(e,'continue');const data=exportExperiment(e,{...view,positions:{4:{x:11,y:-2}},input:'hello'},[{kind:'input',value:'Я'}]);const result=importExperiment(JSON.parse(JSON.stringify(data)));assert.deepEqual(result.engine.state,e.state);assert.deepEqual(result.engine.events,e.events);assert.equal(result.pending.length,1);assert.deepEqual(result.view.positions,{4:{x:11,y:-2}});});
test('invalid imports rejected transactionally',()=>{for(const patch of [{schema:'sqlite'},{algorithm:'other'},{commands:[{kind:'eval',value:'alert(1)'}]},{view:{...view,seconds:-1}},{view:{...view,positions:{4:{x:Infinity,y:0}}}},{pending:[{kind:'input',value:'ab'}]}])assert.throws(()=>importExperiment({...exportExperiment(new Engine(),view),...patch}));});
test('digits are input, not commands; Unicode code points preserved',()=>{const e=new Engine();input(e,'19😀');assert.equal(e.state.nodes.length,6);assert.equal(e.events.length,3);assert.equal(visibleName(' '),'␣');assert.equal(visibleName('\n'),'↵');});
test('signals do not decay on an ordinary transition',()=>{const e=new Engine();input(e,'аба');assert.equal(e.state.nodes.find(n=>n.name==='а').signal,4);assert.equal(e.state.nodes.find(n=>n.name==='б').signal,3);});
test('path must remain contiguous, not just consecutive IDs',()=>{const e=trained();e.state.edges.find(l=>l.id===7).from=3;const v=e.preview({kind:'continue'});assert.equal(v.edge,null);assert.equal(v.after.status,'Продолжение не найдено');});
test('invalid multi-character commands rejected',()=>{const e=new Engine();assert.throws(()=>e.preview({kind:'input',value:'abc'}));assert.throws(()=>e.preview({kind:'input',value:''}));});

test('action points are distinct from user text and preserve action identity',()=>{
  const e=new Engine();
  input(e,'1');
  const textPoint=e.state.nodes.find(n=>n.name==='1'&&n.type==='in');
  const action=e.execute({kind:'action',action:{kind:'key',value:'1'}});
  const keyPoint=e.state.nodes.find(n=>n.type==='ACTION');
  assert.ok(textPoint);assert.ok(keyPoint);assert.notEqual(textPoint.id,keyPoint.id);
  assert.equal(action.action.kind,'key');assert.equal(action.action.value,'1');
});
test('trained virtual action chain is recalled in order and ends in success',()=>{
  const e=new Engine();
  input(e,'добавь траты 1700');
  const actions=[
    {kind:'move',x:500,y:150},
    {kind:'check',object:'CALC'},
    {kind:'click',object:'CALC'},
    {kind:'key',value:'1'},
    {kind:'key',value:'7'},
    {kind:'key',value:'0'},
    {kind:'key',value:'0'},
  ];
  for(const action of actions)e.execute({kind:'action',action});
  command(e,'positive');command(e,'reset');input(e,'добавь траты 1700');
  const replay=[];
  for(let i=0;i<actions.length;i++){const ev=command(e,'continue');replay.push(ev.action);}
  assert.deepEqual(replay,actions);
  const done=command(e,'continue');
  assert.equal(done.kind,'complete');assert.equal(e.state.runtime.activeId,1);assert.equal(e.state.runtime.terminal,true);
});
