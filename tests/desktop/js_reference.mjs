// Produce independent expected traces from the unchanged browser kernel.
import {prepareCase} from '../../web/states/core.mjs';
const projection=e=>({tick:e.model.tick,status:e.model.status,phase:e.model.phase,entry:e.model.entry,context:e.model.context,
 active:e.model.goalActivation,activation:e.model.activation,heldGoal:e.model.heldGoal,
 occ:e.model.occ.map(q=>({id:q.id,held:q.held,a:q.a})),recoveries:e.model.recoveries});
const all=[];
for (let n=1;n<=4;n++) {
 const {engine:e,query}=prepareCase(n);
 const record={n,query,lessons:e.model.lessons,exposures:e.model.exposures,observation:e.model.observed,trace:[]};
 e.perform({kind:'start',query});
 for(let i=0;i<1200&&!['complete','blocked','failed','unknown','ambiguous','timeout','limit'].includes(e.model.status);i++) {
  const event=e.perform({kind:'tick'});record.trace.push({event,state:projection(e)});
 }
 all.push(record);
}
console.log(JSON.stringify(all));
