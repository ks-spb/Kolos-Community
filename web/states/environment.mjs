/** Simulation boundary. Only observeWorld() and receipts cross into the learner.
 * Surface names/rules below are simulator physics, NOT planning rules. */
const wc = x => structuredClone(x);
export function defaultWorld(){return {version:0,surface:'desk',selected:'',focus:'',output:'',cursor:{x:500,y:300},effects:[],surfaces:{
 desk:{label:'Рабочий стол',field:null,icons:[
  {id:'A',label:'A',x:200,y:190,enter:'window'}, {id:'B',label:'B',x:500,y:190},
  {id:'CALC',label:'CALC',x:780,y:190,click:'calculator'}]},
 window:{label:'Открытое окно',field:null,icons:[{id:'X',label:'×',x:920,y:75,click:'desk'},
  {id:'D',label:'D',x:260,y:260},{id:'E',label:'E',x:630,y:260}]},
 calculator:{label:'Калькулятор',field:'FIELD',icons:[{id:'X',label:'×',x:920,y:75,click:'desk'},
  {id:'DIGITS',label:'123',x:250,y:240},{id:'RESULT',label:'=',x:660,y:240}]}
}};}
export function validateWorld(raw){
 if(!raw||!raw.surfaces||Object.keys(raw.surfaces).length>16)throw Error('Некорректные поверхности');
 const w=wc(raw);
 for(const [id,s] of Object.entries(w.surfaces)){
  if(!id||typeof s.label!=='string'||!Array.isArray(s.icons)||s.icons.length>30||!(s.field===null||typeof s.field==='string'))throw Error('Некорректная поверхность');
  const ids=new Set();for(const o of s.icons){if(typeof o.id!=='string'||!o.id||o.id.length>40||ids.has(o.id)||typeof o.label!=='string'||!Number.isFinite(o.x)||!Number.isFinite(o.y)||o.x<50||o.x>950||o.y<50||o.y>550)throw Error('Некорректная иконка');ids.add(o.id);
   for(const k of ['click','enter'])if(o[k]&&!w.surfaces[o[k]])throw Error('Неизвестная цель перехода');}
 }
 if(!w.surfaces[w.surface]||typeof w.selected!=='string'||typeof w.focus!=='string'||typeof w.output!=='string'||w.output.length>500||!w.cursor||![w.cursor.x,w.cursor.y].every(Number.isFinite))throw Error('Некорректное состояние мира');
 w.version=Number.isInteger(w.version)?w.version:0;w.effects=[];return w;
}
export function visibleIcons(w){return w.surfaces[w.surface].icons.filter(o=>!o.hidden).map(o=>({id:o.id,label:o.label,x:o.x,y:o.y}));}
export function worldUnder(w){const hits=visibleIcons(w).filter(o=>Math.abs(o.x-w.cursor.x)<=65&&Math.abs(o.y-w.cursor.y)<=42);return hits.length===1?hits[0].id:'';}
export function observeWorld(w){
 const icons=visibleIcons(w),features=icons.map(o=>'visible:'+o.id);
 // Selection and focus are observable. Coordinates and output digits do not define state identity.
 features.push('selected:'+w.selected,'focus:'+w.focus);
 return {features:features.sort(),icons,selected:w.selected,focus:w.focus,output:w.output,cursor:wc(w.cursor),version:w.version};
}
export function sensoryFeatures(features){return [...new Set(features.filter(f=>!['focus:','selected:'].includes(f)&&!f.startsWith('clicked:')))].sort();}
export function observationKey(o){return JSON.stringify(sensoryFeatures(o.features));}
export function persistentGraph(memory){const result=wc(memory);for(const n of result.nodes)for(const k of ['sensory','eligibility','inhibition'])delete n[k];return result;}
export function worldAction(raw){
 if(!raw||typeof raw!=='object')throw Error('Нет действия');
 if(raw.kind==='move'&&Number.isFinite(raw.x)&&Number.isFinite(raw.y)&&raw.x>=0&&raw.x<=1000&&raw.y>=0&&raw.y<=600)return {kind:'move',x:Math.round(raw.x),y:Math.round(raw.y)};
 if(['check','click','enter'].includes(raw.kind)&&typeof raw.object==='string'&&raw.object&&raw.object.length<=40)return {kind:raw.kind,object:raw.object};
 if(raw.kind==='key'&&typeof raw.value==='string'&&Array.from(raw.value).length===1)return {kind:'key',value:raw.value};
 throw Error('Неизвестное действие');
}
export function worldGuard(o,a){
 if(a.kind==='move')return '';
 if(a.kind==='key')return o.focus?'':'Нет наблюдаемого фокуса ввода';
 if(a.kind==='enter'&&(!o.selected||o.selected===a.object)&&o.last_clicked===a.object)return '';
 const icon=o.icons.find(i=>i.id===a.object);
 if(!icon)return 'Не видна иконка '+a.object;
 if(a.kind==='enter')return o.selected===a.object?'':'Не выделена иконка '+a.object;
 const hits=o.icons.filter(i=>Math.abs(i.x-o.cursor.x)<=65&&Math.abs(i.y-o.cursor.y)<=42);
 return hits.length===1&&hits[0].id===a.object?'':'Под курсором не '+a.object;
}
export function applyWorld(w,request){
 const prior=w.effects.find(e=>e.id===request.id);if(prior)return wc(prior);
 const a=worldAction(request.action),before=observeWorld(w),reason=worldGuard(before,a);
 const r={id:request.id,action:a,ok:!reason,reason,before,after:null};
 if(!reason){
  if(a.kind==='move')w.cursor={x:a.x,y:a.y};
  if(a.kind==='click'||a.kind==='enter'){
   const icon=w.surfaces[w.surface].icons.find(i=>i.id===a.object&&!i.hidden),target=a.kind==='enter'?icon.enter:icon.click;
   if(target){w.surface=target;w.selected='';w.focus=w.surfaces[target].field||'';w.output='';}
   else if(a.kind==='click')w.selected=icon.id;
  }
  if(a.kind==='key'){if(w.output.length>=500){r.ok=false;r.reason='Лимит поля';}else w.output+=a.value;}
  w.version++;
 }
 r.after=observeWorld(w);w.effects.push(wc(r));return r;
}
export function demonstration(query,initial,actions){
 if(typeof query!=='string'||!query||Array.from(query).length>160||!Array.isArray(actions)||!actions.length||actions.length>100)throw Error('Проверьте запрос и действия демонстрации');
 const w=validateWorld(initial),receipts=[];
 for(const raw of actions){const action=worldAction(raw),r=applyWorld(w,{id:'demo:'+receipts.length,action});if(!r.ok)throw Error('Показ не выполнен: '+r.reason);receipts.push(r);}
 return {query,initial:validateWorld(initial),receipts};
}
export function iconDemonstrationActions(w,id){const o=visibleIcons(w).find(o=>o.id===id);if(!o)throw Error('Иконка не видна');return [{kind:'move',x:o.x,y:o.y},{kind:'check',object:id},{kind:'click',object:id}];}
