/** Deterministic evidence. The query/output assertion never supplies motor actions to inference. */
import {writeFileSync,mkdirSync} from 'node:fs';
import {StateEngine,prepareCase,runCase} from '../states/core.mjs';
const out=new URL('../.test-output/',import.meta.url);mkdirSync(out,{recursive:true});
const four=[1,2,3,4].map(i=>{const r=runCase(i);writeFileSync(new URL(`states-case${i}-trace.json`,out),JSON.stringify({query:r.query,pass:r.pass,events:r.engine.events},null,2));return {number:i,pass:r.pass,query:r.query,output:r.output,status:r.status,actions:r.actions,lessons:r.engine.model.lessons.map(l=>l.query),priorKeys:r.engine.model.exposures.map(x=>x.receipts.map(r=>r.action.value).join(''))};});
const base=prepareCase(4).engine.export(),alphabet=['0','1','2','3','4','5','7'];let checked=0,passed=0;const failures=[];
const start=Date.now();for(const a of alphabet.slice(1))for(const b of alphabet)for(const c of alphabet)for(const d of alphabet){
 const text=a+b+c+d;if(['1700','2345'].includes(text))continue;
 const e=StateEngine.import(base),frozen=JSON.stringify(e.model.memory);e.perform({kind:'start',query:'добавь траты '+text});
 for(let tick=0;tick<300&&!['complete','blocked','unknown','failed','timeout','ambiguous','limit'].includes(e.model.status);tick++)e.perform({kind:'tick'});
 const keys=e.model.world.effects.filter(r=>r.ok&&r.action.kind==='key').map(r=>r.action.value).join('');
 const ok=e.model.status==='complete'&&keys===text&&e.model.world.output===text&&frozen===JSON.stringify(e.model.memory);
 checked++;if(ok)passed++;else failures.push({text,status:e.model.status,keys});
}
const report={four,combinationChecks:{checked,passed,failures,alphabet,excluded:['1700','2345'],milliseconds:Date.now()-start},note:'Only expense 1700 was taught; prior independent typing 5432 supplied the other known keys. No builtin digit alphabet.'};
writeFileSync(new URL('states-benchmark.json',out),JSON.stringify(report,null,2));console.log(JSON.stringify(report));if(four.some(r=>!r.pass)||passed!==checked)process.exitCode=1;
