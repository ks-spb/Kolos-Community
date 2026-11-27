import {StateEngine} from '../../web/states/core.mjs';
import {defaultWorld,demonstration,iconDemonstrationActions,persistentGraph} from '../../web/states/environment.mjs';
const cases=[];
for(const scenario of ['same','novel','unexpected','orient']){
 const e=new StateEngine(),w=defaultWorld();w.surface='window';
 if(scenario==='orient'){
  w.surface='desk';e.perform({kind:'teach',record:demonstration('open',w,[...iconDemonstrationActions(w,'A'),{kind:'enter',object:'A'}])});w.surface='window';
 }
 e.perform({kind:'teach',record:demonstration('close',w,iconDemonstrationActions(w,'X'))});
 if(scenario==='novel'){w.surfaces.window.icons[1].id='new-1';w.surfaces.window.icons[2].id='new-2';}
 if(scenario==='unexpected')w.surfaces.window.icons[0].click='calculator';
 const query=scenario==='orient'?'open':'close';
 e.perform({kind:'world',world:w});const row={lessons:e.model.lessons,query,observed:e.model.observed,trace:[]};
 e.perform({kind:'start',query});let disturbed=false;
 for(let i=0;i<120&&!['complete','blocked','failed','ambiguous','timeout'].includes(e.model.status);i++){
  if(scenario==='orient'&&!disturbed&&!e.model.pending&&e.model.world.effects.some(r=>r.action.kind==='click'&&r.action.object==='X')){
   e.model.observed.icons=e.model.observed.icons.filter(i=>i.id!=='A');e.model.observed.object_issues={A:'ambiguous instances'};disturbed=true;
  }
  const before=structuredClone(e.model.observed),event=e.perform({kind:'tick'});
  row.trace.push({before,event,memory:persistentGraph(e.model.memory),goalActivation:e.model.goalActivation,activation:e.model.activation,
   currents:e.model.memory.nodes.map(n=>Object.fromEntries(['id','sensory','eligibility','inhibition'].map(k=>[k,n[k]??0])))});
 }cases.push(row);
}
console.log(JSON.stringify(cases));
