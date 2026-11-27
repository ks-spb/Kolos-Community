import {sensoryFeatures} from './environment.mjs';
/** Experiment 12: grounded, learned sequence assemblies -> internal imagery.
 * No Russian vocabulary, digit parser, regular expressions, LLM or world physics.
 * Generic inductive bias: a unique contiguous symbol span in a paired example
 * binds to its field-content role. Two distinct examples support that assembly.
 * Literal surroundings, field/state meaning and glyph correspondences are learned.
 * This is a bounded associative transducer, not unrestricted language understanding.
 */
const lc=x=>structuredClone(x),lk=x=>JSON.stringify(x),lq=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
const lr=(v,s)=>{if(!v)throw Error(s);};
export const LANGUAGE_DEFAULTS=Object.freeze({decay:.5,threshold:.7,margin:.04,maxWaves:12,maxFrontier:128});
function lm(m){return m.languageMemory??={schema:'kolos-language/1',serial:0,nodes:[],edges:[],lessons:[]};}
function ln(mem,spec){lr(mem.nodes.length<12000,'Лимит языковых вершин');const n={id:'lang:n'+mem.serial++,...spec};mem.nodes.push(n);return n;}
function le(mem,from,to,kind,weight=.9,extra={}){const e={id:'lang:e'+mem.serial++,from,to,kind,weight,...extra};mem.edges.push(e);return e;}
function glyph(mem,char){return mem.nodes.find(n=>n.kind==='glyph'&&n.char===char)||ln(mem,{kind:'glyph',char,label:char===' '?'␣':char});}
function goalCheck(m,raw){
 lr(raw&&['field','state'].includes(raw.kind),'Языковой паре нужен образ поля или состояния');
 if(raw.kind==='state'){
  lr(Array.isArray(raw.features)&&raw.features.every(x=>typeof x==='string'),'Нужны признаки состояния');
  const features=sensoryFeatures(raw.features);lr(m.memory.nodes.some(n=>n.kind==='state'&&lk(n.features.slice().sort())===lk(features)),'Состояние ещё не наблюдалось');
  return {kind:'state',features};
 }
 lr(typeof raw.focus==='string'&&raw.focus&&typeof raw.value==='string'&&Array.from(raw.value).length>0&&Array.from(raw.value).length<=160,'Поле и непустой текст до 160 символов');
 lr(m.memory.nodes.some(n=>n.kind==='state'&&n.features.includes('focus:'+raw.focus)),'Поле ещё не наблюдалось');
 lr(Array.from(raw.value).every(ch=>m.memory.nodes.some(n=>n.kind==='symbol'&&n.value===ch)&&m.memory.nodes.some(n=>n.kind==='motor'&&n.value===ch)),'Сначала покажите эти символы в среде');
 return {kind:'field',focus:raw.focus,value:raw.value};
}
/** Supervision pairs a phrase with a desired image, never a motor demonstration. */
export function teachLanguage(m,phrase,rawGoal){
 lr(!m.pending&&m.status!=='running'&&m.status!=='waiting','Остановите текущую попытку перед обучением');
 lr(typeof phrase==='string'&&Array.from(phrase).length>0&&Array.from(phrase).length<=240,'Фраза: 1–240 символов');
 const goal=goalCheck(m,rawGoal),chars=Array.from(phrase);let prefix=chars,suffix=[];
 if(goal.kind==='field'){
  const value=Array.from(goal.value),starts=[];
  for(let i=0;i+value.length<=chars.length;i++)if(value.every((c,j)=>chars[i+j]===c))starts.push(i);
  lr(starts.length===1,'Содержимое образа должно ровно один раз совпасть с непрерывным участком фразы');
  prefix=chars.slice(0,starts[0]);suffix=chars.slice(starts[0]+value.length);
  lr(prefix.length+suffix.length>0,'Нужен языковой контекст, не только содержимое');
 }
 const mem=lm(m);lr(mem.lessons.length<100,'Лимит 100 языковых пар');
 const meaning=goal.kind==='field'?{kind:'field',focus:goal.focus}:{kind:'state',features:goal.features};
 const shape=lk([prefix,suffix,meaning]);let assembly=mem.nodes.find(n=>n.kind==='assembly'&&n.shape===shape);
 const semantic=mem.nodes.find(n=>n.kind==='meaning'&&lk(n.goal)===lk(meaning))||ln(mem,{kind:'meaning',goal:meaning,label:meaning.kind==='field'?'Поле '+meaning.focus:'Известное состояние'});
 if(!assembly){
  assembly=ln(mem,{kind:'assembly',shape,label:prefix.join('')+(goal.kind==='field'?'□':'')+suffix.join(''),data:goal.kind==='field'});
  let prev=assembly.id;
  for(const char of prefix){const g=glyph(mem,char),n=ln(mem,{kind:'context',label:char});le(mem,prev,n.id,'literal',.9,{glyph:g.id});prev=n.id;}
  if(goal.kind==='field')le(mem,prev,prev,'bind',.9);
  for(const char of suffix){const g=glyph(mem,char),n=ln(mem,{kind:'context',label:char});le(mem,prev,n.id,'literal',.9,{glyph:g.id});prev=n.id;}
  le(mem,prev,semantic.id,'readout',.9,{assembly:assembly.id});
 }
 // Separate evidence units: repeating an identical pair cannot fake diversity.
 const witnessKey=lk([assembly.id,goal.kind==='field'?goal.value:null]);
 if(!mem.nodes.some(n=>n.kind==='witness'&&n.key===witnessKey)){
  const w=ln(mem,{kind:'witness',key:witnessKey,label:'Показ №'+(mem.lessons.length+1)});
  le(mem,w.id,assembly.id,'support',goal.kind==='field'?.4:.9);
 }
 if(goal.kind==='field')for(const char of Array.from(goal.value)){
  const g=glyph(mem,char),symbol=m.memory.nodes.find(n=>n.kind==='symbol'&&n.value===char);
  if(!mem.edges.some(e=>e.kind==='ground'&&e.from===g.id&&e.to===symbol.id))le(mem,g.id,symbol.id,'ground',1);
 }
 mem.lessons.push({phrase,goal:lc(goal),assembly:assembly.id});
 m.language=null;m.status='trained';m.message='Фраза связана с образом. Действия и маршрут не добавлены.';
 return {kind:'language-teach',assembly:assembly.id,goal:lc(goal)};
}
export function languageWeight(m,id,value){
 lr(!m.pending&&m.phase!=='language','Сначала остановите распознавание');lr(Number.isFinite(value)&&value>=0&&value<=1,'Вес 0…1');
 const e=lm(m).edges.find(e=>e.id===id);lr(e,'Нет такой языковой связи');e.weight=value;
}
export function startLanguage(m,phrase,options={}){
 lr(!m.pending,'Сначала разрешите неподтверждённое действие');lr(typeof phrase==='string'&&Array.from(phrase).length>0&&Array.from(phrase).length<=240,'Фраза: 1–240 символов');
 const cfg={...LANGUAGE_DEFAULTS,...options};
 for(const [k,v]of Object.entries(cfg)){
  lr(Object.hasOwn(LANGUAGE_DEFAULTS,k)&&Number.isFinite(v),'Неизвестная настройка языка');
  if(k.startsWith('max'))lr(Number.isInteger(v)&&v>=1&&v<=512,'Некорректный предел');else lr(v>=0&&v<=1,'Коэффициент 0…1');
 }
 lr(cfg.decay<1&&cfg.threshold>0,'Нужны затухание < 1 и положительный порог');
 const mem=lm(m);
 m.language={schema:'kolos-language-runtime/1',phrase,chars:Array.from(phrase),index:0,config:cfg,wave:0,charges:{},
  frontier:mem.nodes.filter(n=>n.kind==='assembly').map(n=>({node:n.id,assembly:n.id,bound:[],path:[],strength:1})),
  trace:{},fired:[],candidates:[],status:'reading',goal:null,readout:null};
 m.intent=null;m.imagery=null;m.plan=null;m.detour=null;m.entry=null;m.occ=[];m.activation={};m.goalActivation={};m.heldGoal=false;
 m.phase='language';m.status='running';m.tick=0;m.query=phrase;m.message='Фраза возбуждает выученные связи. До полного распознавания образ и действия не создаются.';
 return {kind:'language-start',phrase};
}
function refuse(m,kind,message){m.language.status=kind;m.status=kind==='ambiguous'?'ambiguous':'unknown';m.message=message;m.language.candidates=m.language.candidates||[];return {kind:'language-'+kind,message};}
/** One leaky tick: input token is clamped while compatible assemblies charge.
 * Parallel paths preserve genuine alternatives until the full phrase is read.
 * No action or sensory evidence can originate here. */
export function tickLanguage(m){
 const r=m.language,mem=lm(m),cfg=r.config;m.tick++;r.wave++;
 for(const id of Object.keys(r.trace))r.trace[id]=lq(r.trace[id]*cfg.decay);
 const end=r.index>=r.chars.length,char=end?null:r.chars[r.index],candidates=[];
 for(const f of r.frontier)for(const e of mem.edges.filter(e=>e.from===f.node)){
  const assembly=mem.nodes.find(n=>n.id===f.assembly);let sensory=1,bound=f.bound;
  if(end){if(e.kind!=='readout'||e.assembly!==f.assembly||(assembly.data&&!bound.length))continue;}
  else if(e.kind==='literal'){
   const g=mem.nodes.find(n=>n.id===e.glyph);if(g?.char!==char)continue;
  }else if(e.kind==='bind'){
   const g=mem.nodes.find(n=>n.kind==='glyph'&&n.char===char);
   const ground=mem.edges.find(s=>s.kind==='ground'&&s.from===g?.id);
   const referent=ground&&m.memory.nodes.find(n=>n.id===ground.to&&n.kind==='symbol');
   if(!referent||bound.length>=160)continue;
   sensory=ground.weight;bound=[...bound,{char:referent.value,source:r.index,edge:ground.id}];
  }else continue;
  const key=lk([e.id,f.assembly,bound.map(b=>b.source)]);
  let support=1,drive;
  if(end){support=Math.min(1,mem.edges.filter(s=>s.kind==='support'&&s.to===f.assembly).reduce((s,e)=>s+e.weight,0));drive=support*e.weight*f.strength;}
  else drive=(e.weight+sensory)*.5;
  const a=lq(cfg.decay*(r.charges[key]||0)+(1-cfg.decay)*drive);r.charges[key]=a;
  candidates.push({id:key,label:end?mem.nodes.find(n=>n.id===e.to).label:(char===' '?'␣':char),edge:e.id,assembly:f.assembly,to:e.to,a,
   input:end?0:sensory*.5,history:end?drive:e.weight*.5,inhibition:0,threshold:cfg.threshold,allowed:true,
   role:e.kind,bound,path:[...f.path,e.id],strength:Math.min(f.strength,e.weight/.9,sensory),support});
 }
 r.candidates=candidates;
 const ev={kind:'language-charge',symbol:char,index:r.index,wave:r.wave,candidates:lc(candidates),flows:candidates.map(c=>({edge:c.edge,to:c.to,value:c.a})),winner:null};
 if(!candidates.length)return refuse(m,'unknown','Фраза не поддержана языковым опытом целиком. Ничего не выполнено.');
 // Hold the token until all structurally live populations have settled. Weak
 // associations must not disappear just because a stronger one crossed first.
 if(r.wave<cfg.maxWaves&&candidates.some(c=>Math.abs((end?c.support*mem.edges.find(e=>e.id===c.edge).weight*c.strength:(mem.edges.find(e=>e.id===c.edge).weight+(c.role==='bind'?c.input*2:1))*.5)-c.a)>.02))return ev;
 const viable=candidates.filter(c=>c.a>=cfg.threshold);
 if(!viable.length)return refuse(m,'below','Недостаточный сигнал: нужны разные подтверждённые языковые пары или более сильные связи.');
 if(!end){
  const unique=new Map();for(const c of viable){const key=lk([c.to,c.assembly,c.bound]);if(!unique.has(key))unique.set(key,{node:c.to,assembly:c.assembly,bound:c.bound,path:c.path,strength:c.strength});r.trace[c.to]=1;}
  if(unique.size>cfg.maxFrontier)return refuse(m,'limit','Слишком много одновременно допустимых языковых продолжений.');
  r.frontier=[...unique.values()];r.fired.push({index:r.index,symbol:char,edges:viable.map(c=>c.edge)});r.index++;r.wave=0;r.charges={};
  m.message=`Распознано ${r.index}/${r.chars.length}: «${char===' '?'␣':char}». Гипотез: ${r.frontier.length}.`;
  return {...ev,kind:'language-symbol',winner:viable.length===1?viable[0].id:null};
 }
 // Equivalent meaning from different formulations is one candidate, not a tie.
 const meanings=new Map();for(const c of candidates){
  const semantic=mem.nodes.find(n=>n.id===c.to),goal=semantic.goal.kind==='field'?{...semantic.goal,value:c.bound.map(x=>x.char).join('')}:lc(semantic.goal);
  const key=lk(goal),old=meanings.get(key);if(!old||c.a>old.a)meanings.set(key,{...c,goal});
 }
 const ranked=[...meanings.values()].sort((a,b)=>b.a-a.a),best=ranked[0];
 if(ranked[1]&&best.a-ranked[1].a<cfg.margin)return refuse(m,'ambiguous','Несколько образов имеют близкий сигнал. Выберите правильную пару для обучения; действия не запущены.');
 r.goal=lc(best.goal);r.readout={semantic:best.to,edge:best.edge,activation:best.a,assembly:best.assembly,binding:lc(best.bound),path:lc(best.path)};r.status='decoded';
 m.message='Языковые связи активировали образ. Это внутренний источник I, не наблюдение S.';
 return {...ev,kind:'language-image',winner:best.id,goal:lc(best.goal),readout:lc(r.readout)};
}
