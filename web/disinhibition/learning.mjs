import {observeResidualDemonstration} from './environment.mjs';

/** Generic input/receipt alignment. No numeric parser, command vocabulary,
 * word count, stored skill object, or execution-time string slicing. */
export function alignResidualEpisode(record) {
  const replay=observeResidualDemonstration(record.query,record.actions,record.initial);
  if(JSON.stringify(replay.confirmations)!==JSON.stringify(record.confirmations))throw Error('Подтверждения демонстрации не соответствуют среде');
  const keys=record.actions.filter(a=>a.kind==='key');
  if(!keys.length)return {ok:false,reason:'Нет подтверждённых клавиш для сопоставления'};
  const first=record.actions.findIndex(a=>a.kind==='key');
  if(record.actions.slice(first).some(a=>a.kind!=='key'))return {ok:false,reason:'В этой версии поддерживается один непрерывный заключительный участок клавиатурного ввода'};
  const chars=Array.from(record.query),values=keys.map(k=>k.value),matches=[];
  // Enumerate alignments during learning only. Do not assume where words/numbers end.
  for(let offset=0;offset+values.length<=chars.length;offset++) {
    if(values.every((ch,j)=>chars[offset+j]===ch))matches.push(offset);
  }
  if(matches.length!==1)return {ok:false,reason:matches.length?'Неоднозначно: введённые клавиши совпадают с несколькими участками запроса':'Подтверждённый ввод не совпадает с участком запроса'};
  const offset=matches[0];
  if(offset===0)return {ok:false,reason:'Нет различимого контекста перед вводимыми символами'};
  if(offset+values.length!==chars.length)return {ok:false,reason:'Выявлен внутренний участок, а не непрерывный хвост: требуется другая гипотеза'};
  const setup=record.actions.slice(0,first);
  if(!setup.length||setup.at(-1).kind!=='click')return {ok:false,reason:'Нет подтверждённого открытия объекта перед клавишами'};
  const target=keys[0].object;
  if(keys.some(k=>k.object!==target))return {ok:false,reason:'Несколько получателей ввода: неоднозначное соответствие'};
  const normalized=setup.map((a,i)=>a.kind==='move'?
    {kind:'move',object:setup.slice(i+1).find(x=>x.kind==='check')?.object||null}:{kind:a.kind,object:a.object});
  return {ok:true,prefix:chars.slice(0,offset).join(''),offset,length:values.length,target,setup,
    shape:JSON.stringify(normalized),values,
    alignment:values.map((value,j)=>({inputOccurrence:offset+j,action:first+j,value,receipt:record.confirmations[first+j].requestId}))};
}

/** Build durable vertices and evidence edges from approved demonstrations.
 * Grouping here is a comparison of examples, not an executable template. */
export function learnResidualGraph(episodes,previous=null) {
  const memory={nodes:[],edges:[],root:null,version:1};let nextNode=1,nextEdge=1;
  const oldWeights=new Map((previous?.edges||[]).map(e=>[e.key,e.weight]));
  const nodes=new Map(),edges=new Map();
  const N=(key,props)=>{
    if(nodes.has(key))return nodes.get(key);
    const n={id:`m${nextNode++}`,key,...props};nodes.set(key,n);memory.nodes.push(n);return n;
  };
  const E=(from,to,kind,evidence=[],weight=.85)=>{
    const key=JSON.stringify([from.key,to.key,kind]);
    if(edges.has(key)){const e=edges.get(key);e.evidence=[...new Set([...e.evidence,...evidence])];return e;}
    const e={id:`l${nextEdge++}`,key,from:from.id,to:to.id,kind,evidence:[...evidence],weight:oldWeights.get(key)??weight};
    edges.set(key,e);memory.edges.push(e);return e;
  };
  const root=N('root',{kind:'context',label:'Начало запроса',terminal:false,support:0,variants:0});memory.root=root.id;
  const rows=episodes.map(ep=>({id:ep.id,approved:ep.approved,...alignResidualEpisode(ep)}));
  const groups=new Map();
  for(const row of rows.filter(r=>r.ok&&r.approved)) {
    const key=JSON.stringify([row.prefix,row.shape,row.target]);
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);
  }
  const audits=[];
  for(const group of groups.values()) {
    const representative=group[0];
    const distinct=new Set(group.map(g=>JSON.stringify(g.values))).size;
    const support=group.map(g=>g.id);const qualified=distinct>=2;
    const audit={prefix:representative.prefix,distinct,target:representative.target,qualified,
      evidence:support,reason:qualified?'Два разных подтверждённых ввода: контекст и наблюдаемая процедура совпали':'Нужен второй отличный подтверждённый ввод'};
    audits.push(audit);
    let current=root;const prefix=[];
    for(const char of Array.from(representative.prefix)) {
      prefix.push(char);
      const next=N('context:'+JSON.stringify(prefix),{kind:'context',label:char===' '?'␣':char,token:char,terminal:false,support:0,variants:0});
      E(current,next,'recognize',support);current=next;
    }
    // Data becomes a gate on learned evidence, not a dedicated "amount"/"skill" vertex.
    if(!qualified)continue;
    current.terminal=true;current.support=Math.max(current.support,distinct);current.variants++;
    const endpoint=current;
    const routeKey=JSON.stringify([representative.prefix,representative.shape,representative.target]);
    for(let i=0;i<representative.setup.length;i++) {
      const a=structuredClone(representative.setup[i]);
      const n=N('event:'+routeKey+':'+i,{kind:'event',label:a.kind==='move'?`MOVE ${a.x}×${a.y}`:`${a.kind.toUpperCase()} ${a.object}`,action:a});
      E(current,n,'follows',support);current=n;
    }
    const ready=N('ready:'+routeKey,{kind:'ready',label:`Подтверждён фокус ${representative.target}`,target:representative.target});
    E(current,ready,'follows',support);E(endpoint,ready,'evidence',support,0);
    const obs=N('opened:'+representative.target,{kind:'observation',label:`Фокус ${representative.target}`,target:representative.target});
    E(obs,ready,'requires',support,0);
    for(const row of group)for(const value of new Set(row.values)) {
      const symbol=N('symbol:'+value,{kind:'symbol',label:value===' '?'␣':value,value});
      const key=N('motor:'+value,{kind:'motor',label:`KEY ${value===' '?'␣':value}`,value});
      E(symbol,key,'corresponds',[row.id]);E(ready,key,'allows',[row.id],0);
    }
  }
  // Frequency is only a bounded background, never permission to type an old value.
  for(const n of memory.nodes.filter(n=>n.kind==='motor')) {
    n.observations=rows.filter(r=>r.ok&&r.approved).reduce((v,r)=>v+r.values.filter(x=>x===n.value).length,0);
  }
  return {memory,audit:{episodes:rows,comparisons:audits,rule:'Уникальное упорядоченное совпадение подтверждённых клавиш с хвостом входа; общий контекст и подтверждённые действия. Это заданное правило сопоставления, не модель мозга.'}};
}

export function inputResidualGraph(text,attempt) {
  if(typeof text!=='string'||!text||Array.from(text).length>200)throw Error('Запрос: 1–200 символов');
  const nodes=Array.from(text,(value,i)=>({id:`q${attempt}:${i}`,value,held:1,activation:0,refractory:0,state:'held',consumedBy:null}));
  const edges=[];
  for(let i=1;i<nodes.length;i++)edges.push({id:`i${attempt}:${i}`,from:nodes[i-1].id,to:nodes[i].id,kind:'next',weight:1});
  return {nodes,edges,head:nodes[0].id};
}
export function residualNext(input,id) {return input.edges.find(e=>e.kind==='next'&&e.from===id)?.to??null;}
export function residualPrevious(input,id) {return input.edges.find(e=>e.kind==='next'&&e.to===id)?.from??null;}

/** Audit the full new request before any external action. Traverses incoming data
 * and learned graph edges; never looks up/slices a stored answer or "amount". */
export function inspectResidualRequest(memory,input) {
  let context=memory.root,occ=input.head;const matches=[],walk=[],errors=[];
  const nodeById=new Map(memory.nodes.map(n=>[n.id,n]));
  const inputById=new Map(input.nodes.map(n=>[n.id,n]));
  const alphabet=new Set(memory.nodes.filter(n=>n.kind==='motor').map(n=>n.value));
  for(let steps=0;steps<=input.nodes.length;steps++) {
    const n=nodeById.get(context);
    if(n?.terminal) {
      if(n.variants!==1)errors.push('Один контекст связан с разными действиями: неоднозначность');
      else if(!occ)errors.push('Не осталось входных вхождений для подтверждённого ввода');
      else {
        let cursor=occ,ok=true;const seen=new Set();
        while(cursor) {
          if(seen.has(cursor))throw Error('Цикл в новом запросе');seen.add(cursor);
          const token=inputById.get(cursor);
          if(!alphabet.has(token.value)){errors.push(`Не обучено соответствие входа «${token.value===' '?'␣':token.value}» клавише`);ok=false;break;}
          cursor=residualNext(input,cursor);
        }
        if(ok)matches.push({endpoint:context,firstUnmatched:occ,recognized:[...walk]});
      }
    }
    if(!occ)break;
    const token=inputById.get(occ);
    const edges=memory.edges.filter(e=>e.kind==='recognize'&&e.from===context&&nodeById.get(e.to)?.token===token.value);
    if(edges.length!==1)break;
    walk.push({sourceId:occ,edgeId:edges[0].id});context=edges[0].to;occ=residualNext(input,occ);
  }
  if(matches.length===1)return {ok:true,...matches[0]};
  return {ok:false,reason:matches.length>1?'Несколько согласованных границ: не выбираем по длине или ID':errors[0]||'Не найден подтверждённый контекст. Нужны два отличающихся согласованных примера; регистр и пробелы значимы.'};
}
