import {ResidualEngine} from './core.mjs';
import {observeResidualDemonstration} from './environment.mjs';

/** Fixtures only: no knowledge of these strings or objects lives in the engine. */
export function residualDemo(prefix='добавь траты ',values=['1700','2345'],object='CALC') {
  const e=new ResidualEngine(),o=e.model.scene.objects.find(o=>o.name===object);
  for(const value of values) {
    const actions=[{kind:'move',x:o.x,y:o.y},{kind:'check',object},{kind:'click',object},
      ...Array.from(value,value=>({kind:'key',value}))];
    e.perform({kind:'teach',record:observeResidualDemonstration(prefix+value,actions),approved:true});
  }
  return e;
}
export function settleResidual(e,max=1000) {
  for(let i=0;i<max;i++) {
    if(['complete','unknown','ambiguous','blocked','timeout','failed','limit','below'].includes(e.model.status))break;
    e.perform({kind:'tick'});
  }
  return e;
}
export function runResidualChecks() {
  const results=[];
  for(const text of ['1354','4315','1001','1111','54321']) {
    const e=residualDemo(),memory=JSON.stringify(e.model.memory);
    e.perform({kind:'start',query:'добавь траты '+text});settleResidual(e);
    results.push({name:text,ok:e.model.status==='complete'&&e.model.scene.output===text&&JSON.stringify(e.model.memory)===memory,
      observed:e.model.scene.output,ticks:e.model.tick});
  }
  const missing=residualDemo();const s=structuredClone(missing.model.scene);s.objects.find(o=>o.name==='CALC').visible=false;
  missing.perform({kind:'scene',scene:s});missing.perform({kind:'start',query:'добавь траты 1354'});settleResidual(missing);
  results.push({name:'CALC отсутствует',ok:missing.model.status==='blocked'&&missing.model.scene.output===''&&missing.model.scene.effects.every(x=>x.action.kind!=='click'&&x.action.kind!=='key'),observed:missing.model.status});
  const manual=residualDemo();manual.perform({kind:'config',values:{ackMode:'manual'}});manual.perform({kind:'start',query:'добавь траты 1354'});
  for(let i=0;i<100;i++){manual.perform({kind:'tick'});if(manual.model.pending?.action.kind==='key'&&manual.model.pending.applied)break;}
  const held=manual.model.input.nodes.filter(n=>n.held).length,id=manual.model.pending?.sourceId;
  for(let i=0;i<5;i++)manual.perform({kind:'tick'});
  results.push({name:'Нет подтверждения → остаток не расходуется',ok:held===4&&manual.model.input.nodes.filter(n=>n.held).length===4&&manual.model.pending?.sourceId===id&&manual.model.scene.output==='1',observed:manual.model.scene.output});
  return results;
}
