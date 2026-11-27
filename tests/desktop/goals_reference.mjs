// Reference stream is produced by the unchanged-in-language JS implementation.
import {prepareCapability,capabilityIntervention} from '../../web/states/capability-cases.mjs';
const copy=x=>structuredClone(x),stop=new Set(['complete','blocked','failed','unknown','ambiguous','timeout','limit']);
const result=[];
for(let n=5;n<=10;n++){
 const p=prepareCapability(n),e=p.engine,out={number:n,setup:copy(e.operations),operation:p.operation,trace:[]},change={};e.perform(p.operation);
 for(let i=0;i<1700&&!stop.has(e.model.status);i++){
  capabilityIntervention(n,e,change);const before=copy(e.model.observed);const ev=e.perform({kind:'tick'}),m=e.model;
  out.trace.push({before,event:ev,state:{tick:m.tick,status:m.status,phase:m.phase,entry:m.entry,heldGoal:m.heldGoal,
   goalActivation:m.goalActivation,activation:m.activation,occ:m.occ,error:m.intent.error,goals:m.intent.goals,recoveries:m.recoveries}});
 }
 result.push(out);
}
process.stdout.write(JSON.stringify(result));
