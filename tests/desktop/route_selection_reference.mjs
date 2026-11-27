/** Compare Python's learned graph under the JS goal runtime, without world effects. */
import {readFileSync} from 'node:fs';
import {tickGoalNetwork} from '../../web/states/goal-network.mjs';
const model=JSON.parse(readFileSync(0,'utf8')),rows=[];
for(let i=0;i<100;i++){
 const event=tickGoalNetwork(model);
 rows.push({kind:event.kind,winner:event.winner??null,candidates:event.candidates??[]});
 if(event.kind==='route'||model.status!=='running')break;
}
process.stdout.write(JSON.stringify(rows));
