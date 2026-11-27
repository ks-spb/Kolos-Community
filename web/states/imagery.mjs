import {sensoryFeatures} from './environment.mjs';
/** Experiment 11: shared content, source-separated activation.
 * No world physics, language parser or motor operations. Internal excitation
 * never becomes sensory evidence. Content vertices are reused by both sources.
 */
const ic=x=>structuredClone(x),iq=x=>Math.max(0,Math.min(1,Math.round(x*1e9)/1e9));
const ik=x=>JSON.stringify(x),ireq=(v,s)=>{if(!v)throw Error(s);};
export const IMAGE_DEFAULTS=Object.freeze({decay:.5,internalGain:1,sensoryGain:1,threshold:.7});
function vertex(image,id,kind,label,extra={}){
 let n=image.nodes.find(n=>n.id===id);
 if(!n){ireq(image.nodes.length<6000,'Лимит вершин образа');n={id,kind,label,I:0,S:0,present:false,target:false,...extra};image.nodes.push(n);}
 return id;
}
function fieldPattern(image,focus,value,memory){
 const ids=[vertex(image,ik(['field',focus]),'field','Поле '+focus,{focus})];
 let previous=ids[0];
 for(const [index,char]of Array.from(value).entries()){
  const symbol=memory.nodes.find(n=>n.kind==='symbol'&&n.value===char);
  const id=vertex(image,ik(['slot',focus,index,char]),'slot',`${index+1}: ${char===' '?'␣':char}`,{focus,index,char,memoryRef:symbol?.id||null});
  if(!image.edges.some(e=>e.from===previous&&e.to===id))image.edges.push({from:previous,to:id,kind:'order',weight:1});
  ids.push(id);previous=id;
 }
 const end=vertex(image,ik(['end',focus,Array.from(value).length]),'end','Конец: '+Array.from(value).length,{focus,length:Array.from(value).length});
 if(!image.edges.some(e=>e.from===previous&&e.to===end))image.edges.push({from:previous,to:end,kind:'order',weight:1});
 return [...ids,end];
}
function pattern(image,goal,memory){
 if(goal.kind==='field')return fieldPattern(image,goal.focus,goal.value,memory);
 const n=memory.nodes.find(n=>n.kind==='state'&&ik([...n.features].sort())===ik([...goal.features].sort()));
 ireq(n,'Состояние образа ещё не наблюдалось');
 return [vertex(image,n.id,'state',n.label,{memoryRef:n.id})];
}
export function startImagery(m,options={}){
 ireq(m.intent&&!m.pending,'Образу нужна цель без ожидающего действия');
 const cfg={...IMAGE_DEFAULTS,decay:m.config.decay,...options};
 for(const [k,v]of Object.entries(cfg))ireq(Object.hasOwn(IMAGE_DEFAULTS,k)&&Number.isFinite(v)&&v>=0&&v<=1,'Неверная настройка образа');
 ireq(cfg.threshold>0&&cfg.decay<1,'Нужны положительный порог и затухание < 1');
 m.imagery={schema:'kolos-imagery/1',config:cfg,nodes:[],edges:[],patterns:{},mode:'imagine',drive:true,active:null,ready:0,match:0,gap:0,evidence:null,confirmations:[]};
 for(const goal of m.intent.goals)m.imagery.patterns[goal.id]=pattern(m.imagery,goal,m.memory);
 m.message='Образ задан. Моторика выключена: внутренний сигнал не подтверждает реальность.';
}
export function controlImagery(m,command){
 const image=m.imagery;ireq(image&&m.intent,'Сначала создайте образ');ireq(!m.pending,'Сначала разрешите ожидающее действие');
 ireq(['act','rest'].includes(command),'Неизвестное управление образом');
 image.mode=command==='act'?'act':'imagine';image.drive=command==='act';
 m.intent.episode=null;m.entry=null;m.intent.wave=0;m.goalActivation={};m.activation={};
 m.status='running';m.message=command==='act'?'Образ направляет действия. Подтверждение — только от среды.':'Поддержка образа снята. I затухает; мир не меняется.';
}
/** S reads only host observations. Retained S without a present sensory feature
 * is not evidence; neither I nor a predicted frame is ever copied into S. */
export function updateImagery(m,goal){
 const image=m.imagery;if(!image)return;
 const cfg=image.config,desired=new Set(goal?.held?image.patterns[goal.id]:[]),actual=new Set();
 const obs=m.observed;
 if(cfg.sensoryGain>0&&obs&&Array.isArray(obs.features)){
  const n=m.memory.nodes.find(n=>n.kind==='state'&&ik([...n.features].sort())===ik(sensoryFeatures(obs.features)));
  if(n)actual.add(vertex(image,n.id,'state',n.label,{memoryRef:n.id}));
  if(obs.focus&&typeof obs.output==='string'&&Array.from(obs.output).length<=160)
   for(const id of fieldPattern(image,obs.focus,obs.output,m.memory))actual.add(id);
  image.evidence={source:'external',version:obs.version??null,focus:obs.focus,output:obs.output};
 }else image.evidence=null;
 for(const n of image.nodes){
  n.target=desired.has(n.id);n.present=actual.has(n.id);
  n.I=iq(cfg.decay*n.I+(1-cfg.decay)*(n.target&&image.drive?cfg.internalGain:0));
  n.S=iq(cfg.decay*n.S+(1-cfg.decay)*(n.present?cfg.sensoryGain:0));
 }
 const relevant=image.nodes.filter(n=>desired.has(n.id));
 image.active=goal?.id||null;
 image.ready=relevant.length?Math.min(...relevant.map(n=>n.I)):0;
 image.match=relevant.length?Math.min(...relevant.map(n=>n.present?n.S:0)):0;
 image.gap=relevant.length?iq(relevant.reduce((s,n)=>s+Math.max(0,n.I-(n.present?n.S:0)),0)/relevant.length):0;
}
export function imageSatisfied(m){
 const i=m.imagery;return !!i&&!!i.evidence&&i.ready>=i.config.threshold&&i.match>=i.config.threshold;
}
export function imageDemand(m,goal){
 const i=m.imagery;if(!i)return 1;
 const ids=i.patterns[goal.id]||[];
 return ids.length?Math.min(...ids.map(id=>i.nodes.find(n=>n.id===id)?.I||0)):0;
}
export function imageConfirmation(m,goal){
 const i=m.imagery;if(!i)return;
 ireq(i.mode==='act'&&!m.pending&&imageSatisfied(m),'Образ не является подтверждением');
 i.confirmations.push({goal:goal.id,tick:m.tick,evidence:ic(i.evidence),vertices:ic(i.patterns[goal.id]),source:'external'});
}
