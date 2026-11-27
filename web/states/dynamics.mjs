/** Currents on existing observes/backward edges; recognition never authorizes a click. */
import {sensoryFeatures,worldGuard} from './environment.mjs';
const dyClip=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
export function conflict(expected,actual){
 for(const prefix of ['focus:','selected:','window:']){
  const left=expected.filter(f=>f.startsWith(prefix)),right=actual.filter(f=>f.startsWith(prefix));
  if(left.length&&right.length&&!left.some(f=>right.includes(f)))return true;
 }return false;
}
export function support(memory,state,observed){
 const actual=sensoryFeatures(observed.features);if(!state||conflict(state.features,actual))return 0;
 const labels=new Map(memory.nodes.filter(n=>n.kind==='observation').map(n=>[n.id,n.label]));
 const inputs=memory.edges.filter(e=>e.kind==='observes'&&e.to===state.id),total=inputs.reduce((s,e)=>s+e.weight,0);
 return total?dyClip(inputs.filter(e=>actual.includes(labels.get(e.from))).reduce((s,e)=>s+e.weight,0)/total):0;
}
export function sensoryTick(m,flows){
 const cfg=m.intent?.config||m.config;
 for(const n of m.memory.nodes){if(n.kind!=='state')continue;
  const drive=support(m.memory,n,m.observed);n.sensory=dyClip(cfg.decay*(n.sensory||0)+(1-cfg.decay)*drive);
  const inputs=m.memory.edges.filter(e=>e.kind==='observes'&&e.to===n.id),total=inputs.reduce((s,e)=>s+e.weight,0);
  const labels=new Map(m.memory.nodes.filter(f=>f.kind==='observation').map(f=>[f.id,f.label]));
  for(const e of inputs)if(drive&&m.observed.features.includes(labels.get(e.from)))flows.push({edge:e.id,to:n.id,value:e.weight,term:(1-cfg.decay)*e.weight/total,aggregation:'sensory',from:e.from});
 }
}
export function demandFeatures(m,step){
 const a=step.action;if(a.kind==='drive')return ['focus:'+m.selectedCommand.focus];
 return a.object?[(a.kind==='enter'?'selected:':'visible:')+a.object]:[];
}
export function seedDemand(m,activity,features,strength=1){
 const needed=sensoryFeatures(features);if(!needed.length)return;
 const labels=new Map(m.memory.nodes.filter(n=>n.kind==='observation').map(n=>[n.id,n.label]));
 for(const n of m.memory.nodes){
  if(n.kind!=='state'||!needed.every(f=>n.features.includes(f)))continue;
  const weights=m.memory.edges.filter(e=>e.kind==='observes'&&e.to===n.id&&needed.includes(labels.get(e.from))).map(e=>e.weight);
  if(weights.length===needed.length)activity[n.id]=Math.max(activity[n.id]||0,dyClip(strength*Math.min(...weights)));
 }
}
export function transitionCandidates(m,activity,cfg,threshold){
 const nodes=new Map(m.memory.nodes.map(n=>[n.id,n])),result=[];
 for(const t of nodes.values()){
  if(t.kind!=='transition')continue;
  const source=nodes.get(t.from),current=support(m.memory,source,m.observed),sensory=source.sensory||0;
  const first=nodes.get(t.first).action,ready=first.kind==='move'||(['check','click'].includes(first.kind)?m.observed.icons.some(i=>i.id===first.object):!worldGuard(m.observed,first));
  const allowed=ready&&current>=cfg.threshold&&sensory>=cfg.threshold;
  const inhibition=(cfg.errorGain??1)*Math.max(t.inhibition||0,m.intent?.error?.[t.id]||0),input=allowed?.25*sensory:0,history=.75*(activity[t.id]||0);
  result.push({id:t.id,label:t.label,a:allowed?dyClip(input+history-inhibition):0,input,history,sensory,
   inhibition:allowed?inhibition:1,threshold,allowed:allowed&&!m.refractory[t.id],reason:allowed?'':'Недостаточно сенсорного возбуждения'});
 }return result;
}
export function predicted(m,state,observed){return !!state&&support(m.memory,state,observed)>=m.config.threshold;}
function orientingInputs(memory,step){
 const nodes=new Map(memory.nodes.map(n=>[n.id,n])),result=[];
 for(const edge of memory.edges.filter(e=>e.kind==='next'&&e.to===step.id)){
  const previous=nodes.get(edge.from),a=previous.action||{};
  if(a.kind==='move')result.push([previous,[edge]]);
  else if(step.action.kind==='click'&&a.kind==='check'&&a.object===step.action.object){
   for(const before of memory.edges.filter(e=>e.kind==='next'&&e.to===previous.id)){
    const move=nodes.get(before.from);if(move.action?.kind==='move')result.push([move,[before,edge]]);
   }
  }
 }
 return result;
}
export function orientingChoice(m,step,cfg,flows){
 const obs=m.observed,a=step.action,candidates=[];let charging=false;
 if(!['check','click'].includes(a.kind)||!obs.features.includes('visible:'+a.object))return {candidates:[]};
 const nodes=new Map(m.memory.nodes.map(n=>[n.id,n]));
 for(const [move,links] of orientingInputs(m.memory,step)){
  const target=move.action;
  if(Math.abs(obs.cursor.x-target.x)<=3&&Math.abs(obs.cursor.y-target.y)<=3)continue;
  const source=nodes.get(move.pre),sensory=source.sensory||0,weight=links.reduce((v,e)=>v*e.weight,1);
  const allowed=weight>0&&support(m.memory,source,obs)>=cfg.threshold&&sensory>=cfg.threshold;
  const drive=allowed?weight*sensory:0,score=dyClip(cfg.decay*(m.activation[move.id]||0)+drive);
  m.activation[move.id]=score;
  charging||=allowed&&(drive>cfg.threshold*(1-cfg.decay)||score>=cfg.threshold);
  const inhibition=m.refractory[move.id]||!allowed?1:0;
  candidates.push({id:move.id,label:move.label,a:score,input:sensory,history:weight,inhibition,threshold:cfg.threshold,allowed:allowed&&!inhibition});
  for(const edge of links)flows.push({edge:edge.id,from:edge.to,to:edge.from,value:drive,term:drive,aggregation:'motor-demand'});
 }
 const result={candidates,charging},ranks=candidates.filter(c=>c.allowed).sort((a,b)=>b.a-a.a);
 if(ranks[0]?.a>=cfg.threshold){
  if(ranks[1]&&ranks[0].a-ranks[1].a<cfg.margin)result.ambiguous=true;
  else result.winner=nodes.get(ranks[0].id);
 }
 return result;
}
export function decayTraces(m){for(const n of m.memory.nodes){
 if('eligibility'in n)n.eligibility=dyClip(n.eligibility*.90);if('inhibition'in n)n.inhibition=dyClip(n.inhibition*.995);
}}
export function clearTransients(m){for(const n of m.memory.nodes)for(const k of ['sensory','eligibility','inhibition'])delete n[k];m.experienceStart=m.receipts.length;}
