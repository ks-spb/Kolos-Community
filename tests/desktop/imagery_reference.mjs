import {prepareImagery} from '../../web/states/imagery-cases.mjs';
const p=prepareImagery(),e=p.engine,copy=x=>structuredClone(x),out={setup:copy(e.operations),goals:p.operation.goals,trace:[]};
e.perform(p.operation);
function tick(){const before=copy(e.model.observed),event=e.perform({kind:'tick'});out.trace.push({before,event,image:copy(e.model.imagery),status:e.model.status,heldGoal:e.model.heldGoal});}
for(let i=0;i<12;i++)tick();
e.perform({kind:'image-control',command:'rest'});out.trace.push({command:'rest'});for(let i=0;i<5;i++)tick();
e.perform({kind:'image-control',command:'act'});out.trace.push({command:'act'});
for(let i=0;i<400&&e.model.status!=='complete';i++)tick();
process.stdout.write(JSON.stringify(out));
