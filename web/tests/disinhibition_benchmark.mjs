/** Full-request held-out benchmark. No training/update on any test input. */
import {writeFileSync} from 'node:fs';
import {ResidualEngine} from '../disinhibition/core.mjs';
import {residualDemo,settleResidual} from '../disinhibition/demo.mjs';
const baseline=residualDemo(),memory=JSON.stringify(baseline.model.memory),values='0123457';
const failures=[];let count=0,passed=0;const start=Date.now();
for(const a of values.slice(1))for(const b of values)for(const c of values)for(const d of values) {
  const value=a+b+c+d;if(['1700','2345'].includes(value))continue;
  const e=new ResidualEngine();e.model=structuredClone(baseline.model);e.operations=structuredClone(baseline.operations);e.events=structuredClone(baseline.events);
  e.perform({kind:'start',query:'добавь траты '+value});settleResidual(e);
  const emitted=e.model.scene.effects.filter(r=>r.ok&&r.action.kind==='key').map(r=>r.action.value).join('');
  const ok=e.model.status==='complete'&&emitted===value&&e.model.scene.output===value&&
    e.model.input.nodes.every(n=>n.held===0&&n.consumedBy)&&JSON.stringify(e.model.memory)===memory;
  count++;if(ok)passed++;else failures.push({value,actual:emitted,status:e.model.status});
}
const report={test:'full-request disinhibition held-out benchmark',training:['добавь траты 1700','добавь траты 2345'],
  total:count,passed,failed:failures.length,failures,duration_ms:Date.now()-start,weights_frozen:true,
  boundary_inferred_from_demonstrations:true,scope:'one unique contiguous final confirmed keystroke span; same observed control context; known symbol/key correspondences',
  caveat:'This verifies the implemented generic alignment and disinhibition mechanism. It does not prove a biological model or unconstrained discovery of semantics.'};
writeFileSync(process.argv[2]||'.test-output/disinhibition-benchmark.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
if(failures.length)process.exitCode=1;
