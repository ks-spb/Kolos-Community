/** Full evidence is separate from the quick edit/test cycle. */
import {mkdirSync,writeFileSync} from 'node:fs';
import {runCapability,CAPABILITY_NAMES} from '../states/capability-cases.mjs';
const out=new URL('../.test-output/capabilities/',import.meta.url);mkdirSync(out,{recursive:true});
const cases=[];
for(let i=1;i<=10;i++){
 const r=runCapability(i),e=r.engine;
 const summary={number:i,name:CAPABILITY_NAMES[i-1],pass:r.pass,status:r.status,output:r.output,ticks:e.model.tick,
  clicks:e.model.world.effects.filter(x=>x.ok&&x.action.kind==='click').map(x=>x.action.object),
  lessons:e.model.lessons.map(l=>l.query),prior:e.model.exposures.map(r=>r.receipts.map(x=>x.action.value).join('')),
  routes:e.events.filter(x=>x.kind==='route').length,predictions:e.model.intent?.predictions.length||0,errors:e.model.intent?.errorHistory.length||0};
 cases.push(summary);writeFileSync(new URL(`case-${String(i).padStart(2,'0')}.json`,out),JSON.stringify({summary,events:e.events},null,2));
}
const report={schema:'kolos-ten-capabilities/1',scope:'isolated JS graph engine and observed environment; not AGI or live-desktop certification',cases};
writeFileSync(new URL('summary.json',out),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
if(cases.some(r=>!r.pass))process.exitCode=1;
