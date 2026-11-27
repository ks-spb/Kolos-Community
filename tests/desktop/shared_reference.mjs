import {SharedSession} from '../../web/shared/suite.mjs';
const s=new SharedSession(),cases=[];
const project=m=>({tick:m.tick,status:m.status,phase:m.phase,entry:m.entry,context:m.context,heldGoal:m.heldGoal,
 goalActivation:m.goalActivation,activation:m.activation,occ:m.occ,refractory:m.refractory,
 image:m.imagery||null,language:m.language||null,error:m.intent?.error||null,observed:{features:m.observed.features,focus:m.observed.focus,output:m.observed.output,version:m.observed.version}});
for(const n of [1,2,3,4,5,6,7,8,9,10,11,12]){
 s.begin(n);const frames=[project(s.engine.model)];
 for(let i=0;i<2500&&!s.active.finished;i++){s.step();frames.push(project(s.engine.model));}
 cases.push({number:n,frames,result:s.active.result});
}
console.log(JSON.stringify(cases));
