import {persistentGraph} from './environment.mjs';
/** Experiment harness, never imported by either inference module. */
import {prepareCapability} from './capability-cases.mjs';
export function prepareImagery(value='2345'){
 const p=prepareCapability(9);
 return {engine:p.engine,operation:{kind:'imagine',goals:[{kind:'field',focus:'FIELD',value}]}};
}
export function runImageryExperiment(){
 const p=prepareImagery(),e=p.engine,frozen=JSON.stringify(persistentGraph(e.model.memory)),world=JSON.stringify(e.model.world);
 e.perform(p.operation);for(let i=0;i<12;i++)e.perform({kind:'tick'});
 const dry=JSON.stringify(e.model.world)===world&&!e.model.pending&&e.model.heldGoal&&e.model.imagery.match===0&&e.model.imagery.ready>.99;
 const ids=e.model.imagery.patterns[e.model.intent.goals[0].id].slice();
 e.perform({kind:'image-control',command:'rest'});for(let i=0;i<5;i++)e.perform({kind:'tick'});
 const faded=e.model.imagery.ready<.04&&e.model.world.effects.length===0;
 e.perform({kind:'image-control',command:'act'});
 for(let i=0;i<400&&!['complete','blocked','failed','timeout','ambiguous','limit'].includes(e.model.status);i++)e.perform({kind:'tick'});
 const sameVertices=ids.every(id=>e.model.imagery.nodes.some(n=>n.id===id&&n.present&&n.S>=.7));
 const confirmed=e.model.status==='complete'&&e.model.world.output==='2345'&&e.model.imagery.confirmations.length===1;
 const memoryUnchanged=JSON.stringify(persistentGraph(e.model.memory))===frozen;
 return {number:11,pass:dry&&faded&&sameVertices&&confirmed&&memoryUnchanged,dry,faded,sameVertices,confirmed,memoryUnchanged,
  output:e.model.world.output,clicks:e.model.world.effects.filter(r=>r.action.kind==='click').map(r=>r.action.object),ticks:e.model.tick,engine:e};
}
