/** Shared leaky backward wave. Alternative ways out of a state COMPETE rather
 * than averaging a useful signal with unrelated dormant knowledge.
 * This max-pooling is an engineered rate-network competition, not a claim of a
 * measured biological circuit. stateCompetition=0 reproduces the old mean.
 * No goal, environment label, task number or route is used by this operator.
 */
const bwClip=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
export function backwardWave(memory,nodes,old,cfg,flows){
 const next={},pool=cfg.stateCompetition??1;
 for(const n of nodes){
  const incoming=memory.edges.filter(e=>e.kind==='backward'&&e.to===n.id), attenuation=n.kind==='transition'?cfg.discount:1;
  const signals=incoming.map(e=>(old[e.from]||0)*e.weight*attenuation);
  const count=Math.max(1,incoming.length), peak=Math.max(0,...signals),mean=signals.reduce((a,b)=>a+b,0)/count;
  const competition=n.kind==='state'?pool:0,winners=signals.filter(v=>v===peak&&v>0).length;
  const drive=Math.min(1,(1-competition)*mean+competition*peak);
  next[n.id]=bwClip(cfg.decay*(old[n.id]||0)+(1-cfg.decay)*drive);
  incoming.forEach((e,i)=>{
   if(!old[e.from])return;
   const share=(1-competition)/count+(competition&&signals[i]===peak&&winners?competition/winners:0);
   flows.push({from:e.from,to:e.to,edge:e.id,value:signals[i],term:signals[i]*share*(1-cfg.decay),
    aggregation:competition?'competitive-alternatives':'mean',stateCompetition:competition,share});
  });
 }
 return next;
}
