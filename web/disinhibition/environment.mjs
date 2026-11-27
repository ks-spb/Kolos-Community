/** Virtual environment only. An action proposal is NOT a confirmation. No OS I/O. */
export function defaultResidualScene() {
  return {version:0, cursor:{x:500,y:300}, objects:[
    {name:'DOC',x:180,y:150,visible:true},{name:'CALC',x:500,y:150,visible:true},
    {name:'SET',x:820,y:150,visible:true},{name:'MAIL',x:340,y:420,visible:true}],
    app:'', output:'', checked:'', effects:[]};
}
export function residualUnder(scene) {
  const hits=scene.objects.filter(o=>o.visible&&Math.abs(o.x-scene.cursor.x)<=75&&Math.abs(o.y-scene.cursor.y)<=44);
  return hits.length===1?hits[0].name:hits.length?'[неоднозначно]':'';
}
export function residualGuard(scene,a) {
  const obj=a.object&&scene.objects.find(o=>o.visible&&o.name===a.object);
  if(['check','seek','click'].includes(a.kind)&&!obj)return `${a.object} отсутствует: действие запрещено`;
  if(a.kind==='click'&&(residualUnder(scene)!==a.object||scene.checked!==a.object))return `Нет актуальной проверки ${a.object} под курсором`;
  if(a.kind==='key'&&(scene.app!==a.object||!obj))return `Нет фокуса подтверждённого объекта ${a.object}`;
  return '';
}
export function cleanResidualAction(a) {
  if(!a||typeof a!=='object')throw Error('Нет действия');
  if(a.kind==='move'&&Number.isFinite(a.x)&&Number.isFinite(a.y)&&a.x>=0&&a.x<=1000&&a.y>=0&&a.y<=600)
    return {kind:'move',x:Math.round(a.x),y:Math.round(a.y)};
  if(['check','click','seek'].includes(a.kind)&&typeof a.object==='string'&&a.object.length&&a.object.length<=40)
    return {kind:a.kind,object:a.object};
  if(a.kind==='key'&&typeof a.value==='string'&&Array.from(a.value).length===1) {
    const out={kind:'key',value:a.value};
    if(a.object!==undefined){if(typeof a.object!=='string'||!a.object||a.object.length>40)throw Error('Нет объекта для клавиши');out.object=a.object;}
    return out;
  }
  throw Error('Некорректное действие');
}
export function validateResidualScene(raw) {
  if(!raw||!Array.isArray(raw.objects)||raw.objects.length>24)throw Error('Некорректный экран');
  const names=new Set();const objects=raw.objects.map(o=>{
    if(!o||typeof o.name!=='string'||!o.name.trim()||o.name.length>40||names.has(o.name)||typeof o.visible!=='boolean'||
      !Number.isFinite(o.x)||!Number.isFinite(o.y)||o.x<75||o.x>925||o.y<60||o.y>540)throw Error('Некорректный объект экрана');
    names.add(o.name);return {name:o.name,x:o.x,y:o.y,visible:o.visible};
  });
  if(!raw.cursor||![raw.cursor.x,raw.cursor.y].every(Number.isFinite)||raw.cursor.x<0||raw.cursor.x>1000||raw.cursor.y<0||raw.cursor.y>600)throw Error('Некорректный курсор');
  if(typeof raw.app!=='string'||raw.app.length>40||typeof raw.output!=='string'||raw.output.length>500)throw Error('Некорректное состояние ввода');
  return {objects,cursor:{...raw.cursor},app:raw.app,output:raw.output};
}
/** Applies an effect once, records the observed before/after, and returns a receipt.
 * The caller may withhold delivery of this receipt; it cannot pretend the effect never happened. */
export function applyResidualEffect(scene,request) {
  const existing=scene.effects.find(e=>e.requestId===request.id);
  if(existing)return structuredClone(existing);
  const a=request.action;
  const receipt={requestId:request.id,attempt:request.attempt,sourceId:request.sourceId??null,
    candidateId:request.candidateId,action:structuredClone(a),ok:false,reason:'',
    before:{app:scene.app,output:scene.output,cursor:{...scene.cursor},version:scene.version},after:null};
  const fail=residualGuard(scene,a);
  if(fail){receipt.reason=fail;receipt.after=structuredClone(receipt.before);scene.effects.push(receipt);return receipt;}
  if(a.kind==='move'){scene.cursor={x:a.x,y:a.y};scene.checked='';}
  if(a.kind==='check') {
    scene.checked=residualUnder(scene)===a.object?a.object:'';
    if(!scene.checked)receipt.reason='mismatch';
  }
  if(a.kind==='seek') {
    const found=scene.objects.find(o=>o.visible&&o.name===a.object);
    scene.cursor={x:found.x,y:found.y};scene.checked='';
  }
  if(a.kind==='click'){scene.app=a.object;scene.output='';scene.checked='';}
  if(a.kind==='key') {
    if(Array.from(scene.output).length>=500)receipt.reason='Лимит ввода';
    else scene.output+=a.value;
  }
  scene.version++;
  receipt.ok=!receipt.reason;
  receipt.after={app:scene.app,output:scene.output,cursor:{...scene.cursor},version:scene.version};
  scene.effects.push(structuredClone(receipt));return receipt;
}
/** Make a training record from an actually simulated demonstration (same checks as execution). */
export function observeResidualDemonstration(query,actions,initial=defaultResidualScene()) {
  if(typeof query!=='string'||!query||Array.from(query).length>200)throw Error('Запрос: 1–200 символов');
  if(!Array.isArray(actions)||!actions.length||actions.length>100)throw Error('Демонстрация: 1–100 действий');
  const scene={...defaultResidualScene(),...validateResidualScene(initial),effects:[],checked:'',version:0};
  const confirmations=[];const clean=[];
  actions.forEach((raw,index)=>{
    const a=cleanResidualAction(raw);if(a.kind==='key')a.object=a.object||scene.app;
    const request={id:`demo:${index}`,attempt:0,candidateId:`demo-node:${index}`,sourceId:null,action:a};
    const receipt=applyResidualEffect(scene,request);
    if(!receipt.ok)throw Error(`Демонстрация не подтверждена: ${receipt.reason}`);
    clean.push(a);confirmations.push(receipt);
  });
  return {query,actions:clean,initial:validateResidualScene(initial),confirmations};
}
