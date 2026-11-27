/** Monotone lower/upper backward waves certify a local winner, without route search.
 * Transient bounds invalidate on topology, weights, desired input or dynamics edits.
 * Matches kolos_states/route_selection.py; tolerance is ten activity rounding units. */
import {backwardWave} from './backward.mjs';
import {seedDemand,transitionCandidates} from './dynamics.mjs';
const ROUNDING_GAP=1e-8;

function advance(m,owner,cfg,features,strength,flows){
 const nodes=m.memory.nodes.filter(n=>['state','transition'].includes(n.kind)),seed={};
 seedDemand(m,seed,features,strength);
 const stamp=JSON.stringify([nodes.map(n=>[n.id,n.kind]),
  m.memory.edges.filter(e=>e.kind==='backward').map(e=>[e.from,e.to,e.weight]),
  seed,cfg.decay,cfg.discount,cfg.stateCompetition??1]);
 const previous=owner.routeBounds||{},reset=!Object.keys(m.goalActivation).length||previous.stamp!==stamp;
 let lower=reset?{}:m.goalActivation,upper=reset?Object.fromEntries(nodes.map(n=>[n.id,1])):previous.upper;
 lower=backwardWave(m.memory,nodes,lower,cfg,flows);upper=backwardWave(m.memory,nodes,upper,cfg,[]);
 for(const [id,value]of Object.entries(seed)){lower[id]=Math.max(lower[id]||0,value);upper[id]=Math.max(upper[id]||0,value);}
 m.goalActivation=lower;owner.routeBounds={stamp,upper};return upper;
}

export function certifiedChoice(candidates,threshold,exhausted){
 const ranks=candidates.filter(c=>c.allowed).sort((a,b)=>b.a-a.a);
 if(ranks[0]?.a>=threshold){
  const rival=Math.max(-1,...ranks.slice(1).map(c=>c.upper));
  if(ranks[0].a>rival+ROUNDING_GAP)return {winner:ranks[0]};
 }
 if(exhausted)return ranks.filter(c=>c.upper>=threshold).length>1?{ambiguous:true}:{blocked:true};
 return {};
}

export function routeDecision(m,owner,cfg,features,threshold,event,exhausted,strength=1){
 const upper=advance(m,owner,cfg,features,strength,event.flows);
 const candidates=transitionCandidates(m,m.goalActivation,cfg,threshold);
 const ceiling=Object.fromEntries(transitionCandidates(m,upper,cfg,threshold).map(c=>[c.id,c.a]));
 for(const c of candidates)c.upper=ceiling[c.id];
 event.candidates=candidates;return certifiedChoice(candidates,threshold,exhausted);
}
