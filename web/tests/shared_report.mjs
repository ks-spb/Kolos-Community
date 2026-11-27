import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {SharedSession,sharedSignature,runSharedTransfer} from '../shared/suite.mjs';
const srRoot=resolve(dirname(fileURLToPath(import.meta.url)),'..'),srDir=resolve(srRoot,'.test-output/shared');mkdirSync(srDir,{recursive:true});
const s=new SharedSession(),before=sharedSignature(s.engine.model),forward=s.runAll(),reverse=s.runAll(Array.from({length:12},(_,i)=>12-i));
const mixed=s.runAll([12,3,10,1,8,5,11,2,6,9,7,4]),transfer=runSharedTransfer(s);
const old=new SharedSession({competition:0}),legacy=old.runAll();
const report={schema:'kolos-shared-acceptance/1',pass:[...forward,...reverse,...mixed].every(r=>r.pass)&&transfer.pass,
 singleInstance:new Set([...forward,...reverse,...mixed].map(r=>r.instance)).size===1,persistentUnchanged:sharedSignature(s.engine.model)===before,
 sha256:createHash('sha256').update(before).digest('hex'),database:s.stamp,lessons:s.engine.model.lessons.length,
 worldNodes:s.engine.model.memory.nodes.length,worldEdges:s.engine.model.memory.edges.length,languageNodes:s.engine.model.languageMemory.nodes.length,languageEdges:s.engine.model.languageMemory.edges.length,
 forward,reverse,mixed,transfer,legacyMeanControl:{passed:legacy.filter(r=>r.pass).length,failed:legacy.filter(r=>!r.pass).map(r=>r.number),results:legacy},
 scope:'One unified training memory; sequential independent probes and cross-family transfer. Not twelve concurrent tasks or certification of real desktop applications.',
 sourceSha256:Object.fromEntries(['states/backward.mjs','states/core.mjs','states/goal-network.mjs','shared/fixture.mjs','shared/suite.mjs'].map(p=>[p,createHash('sha256').update(readFileSync(resolve(srRoot,p))).digest('hex')]))};
writeFileSync(resolve(srDir,'report.json'),JSON.stringify(report,null,2));writeFileSync(resolve(srDir,'database.json'),JSON.stringify(s.export()));
console.log(JSON.stringify({pass:report.pass,database:report.database,singleInstance:report.singleInstance,checks:36,legacyFailed:report.legacyMeanControl.failed,transfer:transfer.pass}));
if(!report.pass||!report.singleInstance||!report.persistentUnchanged)process.exitCode=1;
