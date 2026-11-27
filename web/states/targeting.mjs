/** Retarget a learned MOVE from fresh object coordinates without changing memory. */
export function motorAction(memory,step,observed){
 const result=structuredClone(step.action);
 if(result.kind!=='move'||result.visual)return result;
 const links=memory.edges.filter(edge=>edge.kind==='next'&&edge.from===step.id);
 if(links.length!==1)return result;
 const target=memory.nodes.find(node=>node.id===links[0].to)?.action;
 if(!['check','click'].includes(target?.kind)||target.visual)return result;
 const icon=observed.icons.find(icon=>icon.id===target.object);
 if(icon)Object.assign(result,{x:icon.x,y:icon.y});
 return result;
}
