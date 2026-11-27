/** Receipt-gated plasticity. Only existing node/edge kinds and executed actions. */
import {observationKey,sensoryFeatures} from './environment.mjs';
import {predicted} from './dynamics.mjs';
const exCopy=x=>structuredClone(x),exClip=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
const exNode=(m,id)=>m.memory.nodes.find(n=>n.id===id);
function exN(m,spec){const n={id:'n'+m.memory.serial++,...spec};m.memory.nodes.push(n);return n;}
function exE(m,from,to,kind,weight){let e=m.memory.edges.find(e=>e.from===from&&e.to===to&&e.kind===kind);if(e)return e;
 e={id:'e'+m.memory.serial++,to,kind,weight,from};m.memory.edges.push(e);return e;}
export function experienceState(m,obs){
 const key=observationKey(obs),found=m.memory.nodes.find(n=>n.kind==='state'&&n.key===key);if(found)return found;
 const features=sensoryFeatures(obs.features),s=exN(m,{kind:'state',key,label:'S'+m.memory.nodes.filter(n=>n.kind==='state').length,features});
 for(const feature of features){let f=m.memory.nodes.find(n=>n.kind==='observation'&&n.label===feature);
  if(!f)f=exN(m,{kind:'observation',label:feature});exE(m,f.id,s.id,'observes',1);}
 return s;
}
export function effectObserved(r){return r.ok===true&&['click','enter'].includes(r.action.kind)&&r.effect_observed!==false&&sensoryFeatures(r.before.features).length>0&&sensoryFeatures(r.after.features).length>0&&observationKey(r.before)!==observationKey(r.after);}
export function unconfirmedResult(m,p,r){const step=exNode(m,p.step);return !!(r.ok&&step&&['click','enter'].includes(r.action.kind)&&!step.dispatch_only&&!effectObserved(r)&&!predicted(m,exNode(m,step.post),r.after));}
function exActions(m,t){
 const result=[],seen=new Set();let current=t.first;
 while(!seen.has(current)){seen.add(current);const step=exNode(m,current);if(!step)return [];
  result.push(step.action);if(current===t.last)return result;
  const links=m.memory.edges.filter(e=>e.kind==='next'&&e.from===current);if(links.length!==1)return [];current=links[0].to;
 }return [];
}
function exRemember(m,seq){
 const before=seq[0].before,after=seq.at(-1).after;
 if(!sensoryFeatures(before.features).length||!sensoryFeatures(after.features).length)return [null,false];
 const signature=JSON.stringify(seq.filter(r=>!['move','check'].includes(r.action.kind)).map(r=>r.action));
 for(const t of m.memory.nodes)if(t.kind==='transition'&&predicted(m,exNode(m,t.from),before)&&predicted(m,exNode(m,t.to),after)&&JSON.stringify(exActions(m,t).filter(a=>!['move','check'].includes(a.kind)))===signature)return [t,false];
 const required=seq.length+1+seq.reduce((s,r)=>s+['before','after'].reduce((a,k)=>a+1+sensoryFeatures(r[k].features).length,0),0);
 if(m.memory.nodes.length+required>5000){m.audit.push({kind:'learning-limit',request:seq.at(-1).id});return [null,false];}
 const source=experienceState(m,before),target=experienceState(m,after);let first=null,previous=null;
 for(const r of seq){const a=r.action,pre=experienceState(m,r.before),post=experienceState(m,r.after);
  const step=exN(m,{kind:'step',label:a.kind.toUpperCase()+' '+(a.object||''),action:exCopy(a),pre:pre.id,post:post.id,
   dispatch_only:r.effect_observed===false,visual_ack:r.verified_by==='visual-change'});
  if(previous)exE(m,previous,step.id,'next',m.config.weight);first=first||step.id;previous=step.id;
 }
 const last=seq.at(-1).action,t=exN(m,{kind:'transition',label:last.kind.toUpperCase()+' '+(last.object||''),first,last:previous,to:target.id,from:source.id});
 exE(m,target.id,t.id,'backward',m.config.weight);exE(m,t.id,source.id,'backward',1);exE(m,source.id,t.id,'applicable',1);exE(m,t.id,previous,'experienced',1);exE(m,t.id,first,'starts',m.config.weight);
 return [t,true];
}
export function acknowledgeExperience(m,p,receipt){
 const r={...exCopy(receipt),step:p.step??null},existing=m.receipts.findIndex(x=>x.id===r.id);
 if(existing<0)m.receipts.push(r);else m.receipts[existing]=r;
 const step=exNode(m,p.step),result={changes:[],learned:null};
 if(!r.ok){m.experienceStart=m.receipts.length;return result;}
 if(p.relocate||p.source){if(p.source)m.experienceStart=m.receipts.length;return result;}
 if(!step||!effectObserved(r))return result;
 const expected=exNode(m,step.post),matched=predicted(m,expected,r.after);
 for(const t of m.memory.nodes.filter(n=>n.kind==='transition'&&n.last===step.id)){
  if(!matched)t.inhibition=1;if(!(m.config.plasticity??1))continue;
  const e=m.memory.edges.find(e=>e.kind==='backward'&&e.to===t.id),old=e.weight,eligibility=step.eligibility||0;
  const delta=(m.config.learningRate??.05)*eligibility*(matched?1-old:-old);e.weight=exClip(old+delta);
  result.changes.push({edge:e.id,before:old,after:e.weight,eligibility});
 }
 let seq=m.receipts.slice(m.experienceStart||0);
 for(let i=seq.length-1;i>0;i--)if(observationKey(seq[i-1].after)!==observationKey(seq[i].before)){seq=seq.slice(i);break;}
 if((m.config.plasticity??1)&&seq.length&&seq.every(r=>r.step)){const [t,created]=exRemember(m,seq);if(created)result.learned=t.id;}
 m.experienceStart=m.receipts.length;const evidence=exCopy(r);delete evidence.before.visual_sample;delete evidence.after.visual_sample;
 m.audit.push({kind:'experience',request:r.id,receipt:evidence,matched,...exCopy(result)});return result;
}
