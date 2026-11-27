import {neuronEdgeGroups} from './snapshot.mjs';
const nvEscape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nvFmt=n=>Number.isFinite(n)?n.toFixed(3).replace(/0+$/,'').replace(/\.$/,''):'—';
const nvUnit=n=>Number.isFinite(n)?Math.max(0,Math.min(1,n)):0;
const nvKinds={state:'Состояние',transition:'Изученный переход',step:'Шаг действия',symbol:'Известный символ',motor:'Моторное соответствие',occurrence:'Вхождение текущего ввода',goal:'Удерживаемая цель',slot:'Позиция символа',field:'Поле',end:'Конец строки',source:'Источник, не нейрон',error:'След ошибки',context:'Контекст',observation:'Признак',assembly:'Языковой контекст',meaning:'Значение',glyph:'Символ языка','language-candidate':'Кандидат чтения'};
const nvEvents={'image-start':'Создан внутренний образ','imagery-wave':'Образ возбуждает память; действия запрещены',spread:'Распространение по опыту переходов',route:'Выбран переход с наибольшим допустимым сигналом',dispatch:'Выбрано действие — результат ещё не подтверждён',effect:'Эффект в среде — ждём подтверждения',ack:'Доставлено подтверждение результата',waiting:'Ожидание подтверждения',charge:'Накопление сигнала','goal-confirmed':'Результат подтверждён внешним наблюдением',complete:'Цель достигнута','language-charge':'Накапливается языковой сигнал','language-symbol':'Прочитан символ фразы','language-image':'Языковой опыт активировал образ','prediction-error':'Наблюдение не совпало с прогнозом','image-control':'Изменён режим образа',stopped:'Расчёт остановлен'};
let nvViewSerial=0;
export class NeuronView {
 constructor(root,{maxNodes=220,compactOverview=false}={}){
  this.maxNodes=Math.max(1,Math.min(2000,maxNodes));this.compactOverview=compactOverview;
  this.root=root;this.uid=++nvViewSerial;this.layer='overview';this.selection=null;this.camera={x:0,y:0,z:1};this.positions={};this.first=true;this.motions=[];this.series=new Map();this.lastStamp=null;
  root.innerHTML=`<div class="nv-work"><section class="nv-graph-area"><div class="nv-filters"><label>Показать <select data-nv="layer"><option value="overview">Образ и переходы</option><option value="image">Только образ I / S</option><option value="world">Состояния и действия</option><option value="input">Символы и торможение</option><option value="language">Языковой граф</option><option value="all">Вся память</option></select></label><input data-nv="search" placeholder="Найти вершину или ID…" aria-label="Поиск вершины"><label><input type="checkbox" data-nv="only-active"> Активные</label><button data-nv="zoom-in" aria-label="Увеличить граф">+</button><button data-nv="zoom-out" aria-label="Уменьшить граф">−</button><button data-nv="fit">Вписать граф</button></div><div class="nv-legend"><span class="nv-i">● Внутренний I</span><span class="nv-s">● Внешний S</span><span class="nv-a">● Активация A</span><span class="nv-red">⊣ Торможение</span><span>★ Выбранный кандидат</span><span>┄ Связь структуры, без передачи</span></div><svg class="nv-svg" data-nv="svg" role="img" aria-label="Вершины и распространение сигналов"></svg><div class="nv-graph-note" data-nv="count"></div></section><aside class="nv-inspector"><div class="nv-kicker">ТЕКУЩЕЕ СОБЫТИЕ</div><h2 data-nv="event">Пауза</h2><p data-nv="message"></p><div class="nv-stat-grid"><div>I · готовность<b data-nv="ready">—</b></div><div>S · совпадение<b data-nv="match">—</b></div></div><div class="nv-world"><div class="nv-kicker">ПРИНЯТОЕ НАБЛЮДЕНИЕ</div><strong data-nv="screen"></strong><div class="nv-output" data-nv="output">—</div><small data-nv="pending"></small></div><div class="nv-kicker">ВЫБРАННАЯ ВЕРШИНА / СВЯЗЬ</div><div data-nv="details" class="nv-details">Нажмите на круг или стрелку. Здесь появятся ID, сигнал, порог и вклад связей.</div></aside></div>`;
  this.$=id=>root.querySelector(`[data-nv="${id}"]`);this.svg=this.$('svg');
  this.$('layer').onchange=e=>{this.layer=e.target.value;this.positions={};this.first=true;this.draw();};
  this.$('only-active').onchange=()=>{this.first=true;this.draw();};this.$('search').oninput=()=>{this.first=true;this.draw();};this.$('fit').onclick=()=>this.fit();for(const [id,factor]of [['zoom-in',1.3],['zoom-out',1/1.3]])this.$(id).onclick=()=>{const x=this.svg.clientWidth/2,y=this.svg.clientHeight/2;this.camera.x=x-(x-this.camera.x)*factor;this.camera.y=y-(y-this.camera.y)*factor;this.camera.z*=factor;this.transform();};
  this.svg.addEventListener('wheel',e=>{e.preventDefault();const box=this.svg.getBoundingClientRect(),x=e.clientX-box.left,y=e.clientY-box.top,z=this.camera.z,next=Math.max(.15,Math.min(4,z*(e.deltaY<0?1.12:1/1.12)));this.camera.x=x-(x-this.camera.x)*next/z;this.camera.y=y-(y-this.camera.y)*next/z;this.camera.z=next;this.transform();},{passive:false});
  this.svg.onpointerdown=e=>{const n=e.target.closest('[data-node]'),l=e.target.closest('[data-link]');if(n){this.selection={node:n.dataset.node};this.details();}else if(l){this.selection={edgeId:this.groups[Number(l.dataset.link)].ids[0]};this.details();}
   this.drag={id:n?.dataset.node,x:e.clientX,y:e.clientY};this.svg.setPointerCapture(e.pointerId);};
  this.svg.onpointermove=e=>{if(!this.drag)return;const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;this.drag.x=e.clientX;this.drag.y=e.clientY;if(this.drag.id){const p=this.positions[this.drag.id];p.x+=dx/this.camera.z;p.y+=dy/this.camera.z;this.draw();}else{this.camera.x+=dx;this.camera.y+=dy;this.transform();}};
  this.svg.onpointerup=this.svg.onpointercancel=()=>this.drag=null;
  this.svg.onkeydown=e=>{if(e.key==='Enter'&&e.target.dataset.node){this.selection={node:e.target.dataset.node};this.details();}};
  this.resize=new ResizeObserver(()=>this.fit());this.resize.observe(this.svg);
 }
 setFrame(frame){this.frame=frame;const stamp=`${frame.attempt}:${frame.revision}:${frame.tick}`;
  if(stamp!==this.lastStamp){for(const n of frame.nodes){const points=this.series.get(n.id)||[];points.push({I:n.I,S:n.S,a:n.a,C:n.C});if(points.length>60)points.shift();this.series.set(n.id,points);}this.lastStamp=stamp;}
  this.$('event').textContent=nvEvents[frame.event?.kind]||frame.event?.kind||'Наблюдение';this.$('message').textContent=frame.message;
  this.$('ready').textContent=nvFmt(frame.ready);this.$('match').textContent=nvFmt(frame.match);
  const o=frame.observed||{};this.$('screen').textContent=o.focus?'Поле: '+o.focus:'Видны: '+(o.icons||[]).map(i=>i.label||i.id).join(', ');
  this.$('output').textContent=o.focus?`«${o.output||''}»`:'Поле скрыто';
  this.$('pending').textContent=frame.pending?`Ждём ${frame.pending.id} · ${frame.pending.action.kind}${frame.pending.action.value?' '+frame.pending.action.value:''}. Источник ещё не погашен.`:frame.status==='complete'?'Результат подтверждён.':'Неподтверждённых действий нет.';
  if(frame.world&&frame.world.output!==o.output)this.$('pending').textContent+=` В стенде уже «${frame.world.output}», ядро ещё ждёт подтверждения.`;
  this.draw();this.details();
 }
 pickNodes(){const f=this.frame;if(!f)return [];let ns=f.nodes;const l=this.layer;
  if(l==='overview')ns=ns.filter(n=>(['goals','world'].includes(n.group)||n.group==='image'&&(n.synthetic||n.target||n.present))||n.kind==='occurrence'||n.kind==='motor'&&f.nodes.some(o=>o.kind==='occurrence'&&o.stored?.value===n.stored?.value));
  else if(l==='image')ns=ns.filter(n=>n.group==='image'||n.I!==null||n.group==='goals');
  else if(l==='world')ns=ns.filter(n=>['world','actions','goals'].includes(n.group));
  else if(l==='input')ns=ns.filter(n=>n.group==='input');
  else if(l==='language')ns=ns.filter(n=>n.group==='language'||n.kind==='symbol');
  const q=this.$('search').value.toLocaleLowerCase();if(q)ns=ns.filter(n=>(n.label+' '+n.id).toLocaleLowerCase().includes(q));
  if(this.$('only-active').checked)ns=ns.filter(n=>n.energy>.005||n.current||n.winner||n.held||n.R>0);
  const count=ns.length;return {nodes:ns.slice(0,this.maxNodes),count};
 }
 layout(nodes){const counts={};
  for(const n of nodes){const k=n.group;const i=counts[k]??0;counts[k]=i+1;if(this.positions[n.id])continue;let x,y;
   if(this.layer==='overview'&&this.compactOverview){
    if(k==='world'){const j=nodes.filter(a=>a.group==='world').findIndex(a=>a.id===n.id);x=780+(j%5)*200;y=100+Math.floor(j/5)*190;}
    else if(n.kind==='source'){x=n.id==='view:internal'?120:460;y=65;}
    else if(k==='image'){const j=nodes.filter(a=>a.group==='image'&&a.kind!=='source').findIndex(a=>a.id===n.id);x=120+(j%3)*190;y=235+Math.floor(j/3)*185;}
    else if(k==='goals'){x=150+i*200;y=820;}
    else{x=120+(i%3)*190;y=1050+Math.floor(i/3)*185;}
   }else if(this.layer==='overview'){
    if(n.kind==='source'){x=n.id==='view:internal'?115:455;y=65;}
    else if(k==='image'){const j=nodes.filter(a=>a.group==='image'&&a.kind!=='source').findIndex(a=>a.id===n.id);x=110+(j%3)*170;y=215+Math.floor(j/3)*160;}
    else if(k==='goals'){x=280+i*170;y=550;}
    else if(k==='world'){const states=nodes.filter(a=>a.kind==='state'),ts=nodes.filter(a=>a.kind==='transition');if(n.kind==='state'){const j=states.findIndex(a=>a.id===n.id);x=730+(j%2)*345;y=110+Math.floor(j/2)*280;}else{const j=ts.findIndex(a=>a.id===n.id);x=855+(Math.max(0,j)%2)*290;y=250+Math.floor(Math.max(0,j)/2)*280;}}
    else if(n.kind==='occurrence'){x=205+(n.index%6)*190;y=775+Math.floor(n.index/6)*180;}
    else{x=190+(i%6)*190;y=950+Math.floor(i/6)*160;}
   }else if(this.layer==='image'){
    if(n.kind==='source'){x=n.id==='view:internal'?180:1020;y=70;}
    else{const body=nodes.filter(a=>a.kind!=='source');const ordered=[...body.filter(a=>a.group==='image'),...body.filter(a=>a.group!=='image')];const j=ordered.findIndex(a=>a.id===n.id);x=150+(j%6)*205;y=250+Math.floor(j/6)*200;}
   }else{const groups=[...new Set(nodes.map(a=>a.group))],g=groups.indexOf(k),offset=groups.slice(0,g).reduce((v,key)=>v+Math.ceil(nodes.filter(a=>a.group===key).length/6)*180+100,0);x=110+(i%6)*205;y=100+offset+Math.floor(i/6)*180;}
   // Newly appearing nodes may not occupy a retained node's position.
   const occupied=nodes.filter(a=>a.id!==n.id&&this.positions[a.id]).map(a=>this.positions[a.id]);
   while(occupied.some(p=>Math.hypot(p.x-x,p.y-y)<125))y+=180;
   this.positions[n.id]={x,y};
  }
 }
 draw(){if(!this.frame)return;const {nodes,count}=this.pickNodes();this.nodes=nodes;this.layout(nodes);const ids=new Set(nodes.map(n=>n.id));
  if(this.lastNodeCount!==nodes.length){this.first=true;this.lastNodeCount=nodes.length;}
  this.groups=neuronEdgeGroups(this.frame.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)&&!(this.layer==='overview'&&['observes','experienced','applicable','starts','next'].includes(e.kind))));this.motions=[];
  const edges=this.groups.map((e,i)=>{const a=this.positions[e.from],b=this.positions[e.to],dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,ux=dx/len,uy=dy/len;
   const siblings=this.groups.filter(g=>g.from===e.from&&g.to===e.to),s=siblings.indexOf(e),bend=22+(s-(siblings.length-1)/2)*30;
   const x1=a.x+ux*37,y1=a.y+uy*37,x2=b.x-ux*40,y2=b.y-uy*40,cx=(x1+x2)/2-uy*bend,cy=(y1+y2)/2+ux*bend;
   const d=e.from===e.to?`M${a.x-20} ${a.y-24} C${a.x-90} ${a.y-135} ${a.x+90} ${a.y-135} ${a.x+20} ${a.y-24}`:`M${x1} ${y1} Q${cx} ${cy} ${x2} ${y2}`;
   const cls=e.kind==='inhibition'?'inhibit':e.channel==='I'?'internal':e.channel==='S'?'sensory':e.provenance==='structure'?'structure':'active';
   const flow=Number.isFinite(e.flow)&&e.flow>0&&e.provenance!=='structure';const pathId=`nv-path-${this.uid}-${i}`;
   if(flow)this.motions.push({pathId,i,value:e.flow,cls});
   const real=e.ids.filter(id=>!id.startsWith('view:'));const name=real.length?real.join(', '):e.kind==='order'?'порядок':e.kind==='inhibition'?'торможение':e.channel||e.kind==='goal-drive'&&'готовность'||'вклад';
   return `<g data-link="${i}" class="nv-edge ${cls}"><title>${nvEscape(name+' · '+e.note)}</title><path class="nv-hit" d="${d}"/><path id="${pathId}" class="nv-wire" d="${d}" marker-end="url(#nv-${e.kind==='inhibition'?'stop':'arrow'}-${this.uid})"/><text x="${(x1+2*cx+x2)/4}" y="${(y1+2*cy+y2)/4-8}">${nvEscape(name.length>34?name.slice(0,31)+'…':name)}${e.weight!==null?' · w '+nvFmt(e.weight):''}</text></g>`;
  }).join('');
  const html=nodes.map(n=>{const p=this.positions[n.id],image=n.I!==null,energy=nvUnit(n.energy),cls=n.kind==='error'?'inhibit':image?'image':n.group==='language'?'language':'normal';
   const one=n.label.length>23?n.label.slice(0,21)+'…':n.label,sub=image?`I ${nvFmt(n.I)}  S ${nvFmt(n.S)}`:n.C!==null?`C ${nvFmt(n.C)} / θ ${nvFmt(n.threshold)}`:n.a!==null?`A ${nvFmt(n.a)}`:'Нет отдельной A';
   return `<g data-node="${nvEscape(n.id)}" class="nv-node ${cls} ${n.synthetic?'synthetic':''} ${n.current?'current':''} ${n.winner?'winner':''} ${this.selection?.node===n.id?'selected':''}" transform="translate(${p.x} ${p.y})" tabindex="0" role="button" aria-label="${nvEscape(n.label)}" style="--energy:${energy}"><title>${nvEscape((nvKinds[n.kind]||n.kind)+' · '+n.id)}</title><circle class="nv-aura" r="44"/><circle class="nv-body" r="32"/>${image?`<path class="nv-ring-I" pathLength="1" stroke-dasharray="${nvUnit(n.I)} 1" d="M0 -37 A37 37 0 0 0 0 37"/><path class="nv-ring-S" pathLength="1" stroke-dasharray="${nvUnit(n.S)} 1" d="M0 -37 A37 37 0 0 1 0 37"/>`:''}<text class="nv-value" y="5">${n.synthetic?'↧':n.winner?'★':n.kind==='occurrence'?nvEscape(n.stored.value):nvFmt(image?Math.max(n.I,n.S,n.C??0,n.a??0):n.C??n.a)}</text><text class="nv-label" y="60">${nvEscape(one)}</text><text class="nv-signal" y="82">${nvEscape(sub)}</text>${image&&(n.a!==null||n.C!==null)?`<text class="nv-small" y="116">A ${nvFmt(n.a)} · C ${nvFmt(n.C)}</text>`:''}<text class="nv-small" y="100">${nvEscape(n.synthetic?'источник / расчёт':n.R>0?'ЗАПРЕТ '+n.R+' такт.':n.held===false?'погашено':n.current?(n.kind==='goal'?'цель активна':'наблюдается'):n.pending?'ждёт подтверждения':n.kind==='state'?(n.features||[]).filter(f=>f.startsWith('visible:')).map(f=>f.slice(8)).join(' · '):n.id.length<22?n.id:(nvKinds[n.kind]||n.kind))}</text></g>`;
  }).join('');
  this.svg.innerHTML=`<defs><pattern id="nv-grid-${this.uid}" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#1e323e"/></pattern><marker id="nv-arrow-${this.uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10" fill="#7994a4"/></marker><marker id="nv-stop-${this.uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M8 0V10" stroke="#ff7986" stroke-width="3"/></marker></defs><rect width="100%" height="100%" fill="url(#nv-grid-${this.uid})"/><g data-nv="world">${edges}${html}<g data-nv="particles"></g></g>`;
  this.$('count').textContent=`${nodes.length} / ${count} вершин · ${this.groups.length} направленных групп связей${count>this.maxNodes?' · лимит отображения '+this.maxNodes+': используйте поиск':''}. Колесо — масштаб, перетаскивание — перемещение. Частицы показывают вклад завершённого такта.`;
  this.transform();if(this.first)this.fit();this.animate(.55);
 }
 animate(p){const group=this.$('particles');if(!group)return;
  group.innerHTML=this.motions.map(m=>{const el=this.svg.querySelector('#'+m.pathId);if(!el)return '';const pos=el.getPointAtLength(el.getTotalLength()*Math.max(0,Math.min(1,p)));
   return `<g class="nv-particle ${m.cls}" transform="translate(${pos.x} ${pos.y})"><circle r="6"/><text x="9" y="-10">${m.cls==='inhibit'?'−':'+'}${nvFmt(m.value)}</text></g>`;}).join('');
 }
 fit(){if(!this.nodes?.length||this.svg.clientWidth<10||this.svg.clientHeight<10)return;const ps=this.nodes.map(n=>this.positions[n.id]);
  const minX=Math.min(...ps.map(p=>p.x))-105,maxX=Math.max(...ps.map(p=>p.x))+115,minY=Math.min(...ps.map(p=>p.y))-60,maxY=Math.max(...ps.map(p=>p.y))+130;
  this.camera.z=Math.min(1.7,(this.svg.clientWidth-24)/(maxX-minX),(this.svg.clientHeight-24)/(maxY-minY));
  this.camera.x=this.svg.clientWidth/2-(minX+maxX)/2*this.camera.z;this.camera.y=this.svg.clientHeight/2-(minY+maxY)/2*this.camera.z;this.first=false;this.transform();
 }
 transform(){this.$('world')?.setAttribute('transform',`translate(${this.camera.x} ${this.camera.y}) scale(${this.camera.z})`);}
 details(){const el=this.$('details'),f=this.frame,s=this.selection;if(!f||!s)return;
  if(s.node){const n=f.nodes.find(n=>n.id===s.node);if(!n){el.textContent='На этом такте вершины ещё нет.';return;}
   const pairs=[['ID',n.id],['Тип',nvKinds[n.kind]||n.kind],['A · хранится',nvFmt(n.a)],['C · кандидат',nvFmt(n.C)],['Порог θ',nvFmt(n.threshold)],['I · внутренний',nvFmt(n.I)],['S · внешний',nvFmt(n.S)],['Признак сейчас',n.present===undefined?'—':n.present?'да':'нет'],['След T',nvFmt(n.T)],['Запрет R',n.R],['Удерживается',n.held===null?'—':n.held?'да':'нет']];
   let equation='';if(n.I!==null&&n.oldI!==null)equation=`I: ${nvFmt(n.oldI)} × ${nvFmt(n.imageDecay)} + ${nvFmt(1-n.imageDecay)} × ${nvFmt(n.internalInput)} → ${nvFmt(n.I)}<br>S: ${nvFmt(n.oldS)} × ${nvFmt(n.imageDecay)} + ${nvFmt(1-n.imageDecay)} × ${nvFmt(n.sensoryInput)} → ${nvFmt(n.S)}`;
   else if(n.I!==null)equation='Предыдущего снимка нет. Показаны текущие I и S, без восстановления отсутствующего такта.';
   else if(n.calculation)equation=`Вклад входа: ${nvFmt(n.calculation.input)}<br>Вклад опыта: ${nvFmt(n.calculation.history)}<br>Торможение: −${nvFmt(n.calculation.inhibition)}<br>Кандидат C: ${nvFmt(n.C)}. После выбора хранимая A может быть сброшена.`;
   const series=this.series.get(n.id)||[],graph=['I','S','a'].map((key,i)=>{const pts=series.map((p,j)=>[10+j*250/Math.max(1,series.length-1),75-nvUnit(p[key])*65]);return `<polyline class="nv-chart-${i}" points="${pts.map(p=>p.join(',')).join(' ')}"/>`;}).join('');
   el.innerHTML=`<h3>${nvEscape(n.label)}</h3><dl>${pairs.map(([k,v])=>`<dt>${nvEscape(k)}</dt><dd>${nvEscape(v)}</dd>`).join('')}</dl>${equation?`<div class="nv-formula">${equation}</div>`:''}<svg class="nv-chart" viewBox="0 0 275 85"><path d="M10 5V75H265"/>${graph}</svg><small>Последние 60 показанных снимков · I / S / A.</small>${n.reason?`<p>${nvEscape(n.reason)}</p>`:''}${n.features?`<p>${n.features.map(nvEscape).join('<br>')}</p>`:''}`;
  }else{const e=this.groups?.find(e=>e.ids.includes(s.edgeId));if(!e){el.textContent='Связь не показана в текущем слое.';return;}
   el.innerHTML=`<h3>${nvEscape(e.ids.join(', '))}</h3><p>${nvEscape(e.from)} → ${nvEscape(e.to)}</p><dl><dt>Тип</dt><dd>${nvEscape(e.kind)}</dd><dt>Вес</dt><dd>${nvFmt(e.weight)}</dd><dt>Передача</dt><dd>${nvFmt(e.flow)}</dd><dt>Источник данных</dt><dd>${e.provenance==='recorded'?'Журнал движка':e.provenance==='equation'?'Член уравнения':'Только структура'}</dd></dl><p>${nvEscape(e.note)}</p>${e.members.map(x=>x.term!==null?`<p>После нормировки и утечки: ${nvFmt(x.term)} (до суммирования / ограничения).</p>`:'').join('')}`;
  }
 }
 destroy(){this.resize.disconnect();this.root.innerHTML='';}
}
