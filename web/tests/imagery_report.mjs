import {mkdirSync,writeFileSync} from 'node:fs';
import {runImageryExperiment} from '../states/imagery-cases.mjs';
const r=runImageryExperiment(),e=r.engine;delete r.engine;
mkdirSync('.test-output',{recursive:true});
writeFileSync('.test-output/imagery-js.json',JSON.stringify({result:r,scope:'11: simulator and graph, not natural-language grounding or live Windows certification',imagery:e.model.imagery,events:e.events},null,2));
console.log(JSON.stringify(r));if(!r.pass)process.exitCode=1;
