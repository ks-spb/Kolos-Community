import {SignalEngine,calculatorDemo,DEFAULTS,actionLabel,underCursor,SIGNAL_VERSION} from './core.mjs';
const sg$ = id => document.getElementById('sg-'+id);
const sx = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const percent = n => Math.round((n||0)*100);
const sfmt = n => Number(n||0).toFixed(2);
const cloneSignal = x => structuredClone(x);
const STOP = new Set(['unknown','blocked','below','ambiguous','limit','complete','recall-complete','idle','trained']);
const markup = `
<div class="sg-top"><div><span class="sg-kicker">KOLOS / SIGNAL LAB</span><h1>Распространение сигнала</h1></div>
 <div class="sg-top-actions"><span id="sg-save-status">Локальная память</span><button id="sg-demo">Пример CALC → 1700</button><button id="sg-copy">Из последовательного</button><button id="sg-import">Импорт</button><button id="sg-export">Экспорт JSON</button><button id="sg-help">?</button></div></div>
<div class="sg-composer"><input id="sg-query" aria-label="Запрос в сигнальном режиме" placeholder="Введите полный запрос или его начало" maxlength="300"><button id="sg-send" class="sg-primary">Передать запрос →</button><button id="sg-recall">Продолжить по памяти</button><button id="sg-continue">Продолжить выполнение</button></div>
<div id="sg-message" role="status">Начните с примера или обучите свою последовательность. Этот режим не использует ID + 1.</div>
<div id="sg-recognition" class="sg-recognition" hidden></div>
<div id="sg-recall-result" class="sg-recall-result" hidden><div><span class="sg-kicker">ПРОДОЛЖЕНИЕ ПО ПАМЯТИ</span><small id="sg-recall-state"></small></div><div class="sg-recall-values"><span>Введено <code id="sg-recall-prefix"></code></span><span>Сгенерировано <strong id="sg-recall-text">—</strong></span><span>Путь в графе <code id="sg-recall-raw">—</code></span></div></div>
<div class="sg-workspace">
 <section class="sg-canvas"><div class="sg-graph-toolbar"><span id="sg-count">Нет обученных цепочек</span><div><select id="sg-view" aria-label="Вид графа"><option value="actions">Действия</option><option value="contexts">Все контексты</option><option value="all">Контексты + понятия</option></select><button id="sg-zoom-in" title="Приблизить">+</button><button id="sg-zoom-out" title="Отдалить">−</button><button id="sg-fit" title="Уместить граф">⌗</button></div></div>
 <div class="sg-stage"><svg id="sg-graph" aria-label="Взвешенный граф контекстов" role="group"></svg><div id="sg-empty"><h2>Порядок — в связях.<br>Выбор — по сигналу.</h2><p>Два нуля — два контекста одного действия.<br>Порог и условия определяют, кто может сработать.</p><button id="sg-empty-demo" class="sg-primary">Открыть пример</button></div>
 <div class="sg-legend"><span>● Последняя сработавшая</span><span>○ Сигнал / порог · R: запрет · T: след</span><span>Пунктир — условия и понятия</span></div></div>
 <div class="sg-candidates"><div class="sg-section-title">КАНДИДАТЫ НА ШАГ <span id="sg-phase"></span></div><div id="sg-candidates"></div></div>
 </section>
 <aside class="sg-side">
  <div class="sg-section-title">ВИРТУАЛЬНЫЙ ЭКРАН <span id="sg-scene-version"></span></div>
  <svg id="sg-screen" viewBox="0 0 1000 600" aria-label="Объекты виртуального экрана" role="group"></svg>
  <div class="sg-readout"><span id="sg-under"></span><span id="sg-coords"></span></div>
  <div class="sg-app"><span id="sg-app">Рабочий стол</span><strong id="sg-output">—</strong></div>
  <div class="sg-controls"><button id="sg-shuffle">Переставить</button><button id="sg-hide">Скрыть выбранный</button><button id="sg-show">Показать все</button><button id="sg-reset-screen">Закрыть приложение</button></div>
  <div class="sg-add"><input id="sg-object-name" placeholder="Имя объекта" maxlength="40"><button id="sg-add">+ объект</button></div>
  <details id="sg-training" open><summary>Обучение <span id="sg-training-state">не записывается</span></summary>
   <p class="sg-hint">Запрос сверху → начать → клик по объекту → клавиши → Escape → сохранить → «Правильно».</p>
   <div class="sg-controls"><button id="sg-record">● Начать</button><button id="sg-stop">■ Закончить</button><button id="sg-learn" class="sg-primary">Сохранить</button><button id="sg-discard">Сброс записи</button></div>
   <input id="sg-keys" placeholder="Клавиатура демонстрации: 1700" aria-label="Клавиши демонстрации" autocomplete="off">
   <div id="sg-buffer" class="sg-buffer"></div>
  </details>
  <details id="sg-parameters"><summary>Параметры сети</summary><div id="sg-config"></div><button id="sg-defaults">Начальные параметры</button><p class="sg-hint">Значения — инженерные настройки. Один такт не зависит от скорости анимации.</p></details>
  <details id="sg-selection" open><summary>Выбранная вершина / связь</summary><div id="sg-selected">Нажмите на вершину или стрелку графа.</div></details>
  <details><summary>Тормозящая связь</summary><label>Источник<select id="sg-inhibit-from"></select></label><label>Цель<select id="sg-inhibit-to"></select></label><button id="sg-add-inhibit">Добавить торможение 0,50</button></details>
  <div class="sg-feedback"><button id="sg-positive">+ Правильно</button><button id="sg-negative">− Неправильно</button></div><p class="sg-hint">Награда — только по вашей оценке. Достижение конца не усиливает сеть автоматически.</p>
 </aside>
</div>
<div id="sg-history-banner" hidden>Просмотр истории: среда и веса не изменяются. <button id="sg-live">К текущему состоянию →</button></div>
<div class="sg-playbar"><div class="sg-controls"><button id="sg-play" class="sg-primary">▶ Пуск</button><button id="sg-step">Один такт</button><button id="sg-to-action">До действия</button><button id="sg-reset">Новая попытка</button><button id="sg-replay">↺ Повтор</button></div>
 <label class="sg-speed">Интервал <output id="sg-speed-label">1,00 с</output><input id="sg-speed" type="range" min="250" max="5000" step="250" value="1000"></label>
 <span id="sg-state-label">На паузе</span><button id="sg-journal-toggle">Журнал</button><button id="sg-clear">Очистить режим</button>
</div>
<div class="sg-timeline"><span id="sg-operation-count">0 / 0</span><input id="sg-timeline" type="range" min="0" max="0" value="0" aria-label="История сигнального режима"><span id="sg-tick-label">Такт 0</span></div>
<div class="sg-progress"><div id="sg-progress"></div></div><div id="sg-journal" hidden></div>
<input id="sg-file" type="file" accept=".json,application/json" hidden><div id="sg-toast" hidden role="status"></div>
<dialog id="sg-help-dialog"><button id="sg-close-help" class="sg-close">×</button><h2>Сигнал выбирает следующий шаг</h2>
 <p>Каждый такт: затухание → передача по весам → обязательные условия → максимум выше порога → подтверждение действия → новый импульс.</p>
 <p><b>Полная команда:</b> «Пример CALC → 1700» → «Передать запрос» → дождитесь распознавания → «Продолжить выполнение». Результат виртуального ввода: 1700.</p>
 <p><b>Продолжение текста:</b> оставьте в поле «добавь траты» и нажмите «Продолжить по памяти» — каждый следующий символ выбирается отдельным тактом. Ответ: 1700. Для «добавь» ответ: траты 1700.</p>
 <p><b>Свой сценарий:</b> напишите запрос, начните обучение, кликните объект и введите клавиши. Escape → «Сохранить» → «Правильно». Затем «Новая попытка» и передайте тот же запрос.</p>
 <p><b>Проверка среды:</b> после новой попытки переставьте CALC или скройте его. В первом случае появятся шаги поиска и повторной проверки; во втором клик и клавиши заблокируются.</p>
 <p><b>Настоящая конкуренция:</b> обучите два разных действия одному запросу. При близких сигналах сеть остановится. Измените вес входящей связи и повторите попытку — выбор изменится.</p>
 <p>A — текущая активация; θ — порог; R — оставшиеся запрещённые такты; T — след. После срабатывания A сбрасывается, T=1, R=2 по умолчанию. Последняя сработавшая не обязана иметь максимальную A.</p>
 <p>Режимы независимы. «Из последовательного» копирует только явные демонстрации действий с положительной реакцией. «Конец» — ожидание, не проверка реальной финансовой операции. Подстановка 2500 вместо 1700 и распознавание перефразированных команд не реализованы.</p>
 <p>Это экспериментальная контекстная сеть, а не точная модель мозга. Веса не заменяют обязательные условия безопасности. Внешних запросов и действий операционной системы нет.</p>
</dialog>`;

class SignalGraph {
 constructor(svg,onSelect,onMove){this.svg=svg;this.onSelect=onSelect;this.onMove=onMove;this.positions={};this.camera={x:0,y:0,z:1};this.selected=null;this.mode='actions';this.drag=null;
  svg.addEventListener('wheel',e=>{e.preventDefault();this.camera.z=Math.max(.12,Math.min(3,this.camera.z*(e.deltaY<0?1.1:.9)));this.transform();},{passive:false});
  svg.addEventListener('pointerdown',e=>{const n=e.target.closest('[data-sgn]'),l=e.target.closest('[data-sge]');
   this.drag={id:n?Number(n.dataset.sgn):null,x:e.clientX,y:e.clientY};svg.setPointerCapture(e.pointerId);
   if(n||l){this.selected=n?{kind:'node',id:Number(n.dataset.sgn)}:{kind:'edge',id:Number(l.dataset.sge)};this.onSelect();}
  });
  svg.addEventListener('pointermove',e=>{if(!this.drag)return;const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;this.drag.x=e.clientX;this.drag.y=e.clientY;
   if(this.drag.id){const p=this.positions[this.drag.id];p.x+=dx/this.camera.z;p.y+=dy/this.camera.z;this.render(this.m,this.event,this.previewing);}else{this.camera.x+=dx;this.camera.y+=dy;this.transform();}
  });
  const end=()=>{if(this.drag)this.onMove();this.drag=null;};svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);
  new ResizeObserver(()=>{if(this.m)this.fit();}).observe(svg);
 }
 point(n,index){if(!this.positions[n.id]){const col=index%4,row=Math.floor(index/4);this.positions[n.id]={x:(row%2?3-col:col)*230,y:row*145};}return this.positions[n.id];}
 curve(e){const a=this.positions[e.from],b=this.positions[e.to];if(!a||!b)return null;const dx=b.x-a.x,dy=b.y-a.y,l=Math.hypot(dx,dy)||1;
  const nx=dx/l,ny=dy/l,dist=Math.min(94/Math.max(1e-9,Math.abs(nx)),51/Math.max(1e-9,Math.abs(ny)));
  const x1=a.x+nx*dist,y1=a.y+ny*dist,x2=b.x-nx*(dist+3),y2=b.y-ny*(dist+3);
  if(e.from===e.to)return{d:`M${a.x-50},${a.y-46} C${a.x-135},${a.y-145} ${a.x+135},${a.y-145} ${a.x+50},${a.y-49}`,x:a.x,y:a.y-99};
  const bend=e.kind==='inhibit'?-60:24;const cx=(x1+x2)/2-dy/l*bend,cy=(y1+y2)/2+dx/l*bend;
  return{d:`M${x1},${y1} Q${cx},${cy} ${x2},${y2}`,x:(x1+2*cx+x2)/4,y:Math.abs(dy)<35?(y1+y2)/2-62:(y1+2*cy+y2)/4-9};
 }
 render(m,event,previewing=false){this.m=m;this.event=event;this.previewing=previewing;
  const showInput=this.mode==='actions'&&m.phase==='input';
  let list=m.nodes.filter(n=>this.mode==='all'||n.kind==='root'||n.kind==='context'&&(this.mode==='contexts'||n.phase==='execute'||n.token==='in:<END_REQUEST>'||(showInput&&n.phase==='input')));
  if(this.mode==='actions')list=[...list.filter(n=>!['recovery','recheck'].includes(n.role)),...list.filter(n=>['recovery','recheck'].includes(n.role))];
  // Contexts keep their positions between ticks. New concepts get a separate lower area.
  list.forEach((n,i)=>this.point(n,i));const ids=new Set(list.map(n=>n.id));
  const defs=`<defs><pattern id="sg-dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#283b33"/></pattern><marker id="sg-arrow" orient="auto" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"><path d="M0 0L10 5L0 10" fill="#8baf98"/></marker></defs><rect width="100%" height="100%" fill="url(#sg-dots)"/>`;
  const edgeHTML=m.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)).map(e=>{const p=this.curve(e),f=event?.flows?.find(f=>f.edgeId===e.id);const selected=this.selected?.kind==='edge'&&this.selected.id===e.id;
   return `<g data-sge="${e.id}" class="sg-edge ${e.kind} ${selected?'selected':''}"><path class="sg-hit" d="${p.d}"/><path id="sg-edge-${e.id}" d="${p.d}" marker-end="url(#sg-arrow)"/><text x="${p.x}" y="${p.y}">${sx(e.kind==='excite'||e.kind==='inhibit'?`№${e.id} · ${sfmt(e.weight)}${f?' · +'+percent(f.amount):''}`:e.kind==='requires'?'требуется':'понятие')}</text></g>`;}).join('');
  const nodeHTML=list.map(n=>{const p=this.positions[n.id],c=event?.candidates?.find(c=>c.id===n.id),score=c?c.activation:n.a;
   const chosen=event?.winner===n.id,active=m.lastFired===n.id,selected=this.selected?.kind==='node'&&this.selected.id===n.id;
   const label=n.label.length>19?n.label.slice(0,17)+'…':n.label;
   const aLine=c?(previewing?`A ${percent(n.a)} → ${percent(c.activation)} / θ ${percent(c.threshold)}`:`A ${percent(n.a)} · пик ${percent(c.activation)} / θ ${percent(c.threshold)}`):`A ${percent(n.a)} / θ ${percent(n.threshold??m.config.threshold)}`;
   return `<g data-sgn="${n.id}" tabindex="0" role="button" aria-label="${sx(n.label)}" transform="translate(${p.x},${p.y})" class="sg-node ${active?'last':''} ${chosen?'winner':''} ${selected?'selected':''} ${n.kind}" style="--energy:${Math.max(0,score)}"><title>${sx(n.label)} · ID ${n.id}</title><rect class="sg-aura" x="-101" y="-52" width="202" height="115" rx="18"/><rect class="sg-box" x="-90" y="-43" width="180" height="92" rx="12"/><text class="sg-n-label" y="-18">${sx(label)}</text><text class="sg-n-values" y="3">${aLine}</text><text class="sg-n-extra" y="24">R ${n.r} · T ${sfmt(n.trace)} · #${n.id}</text>${chosen?'<text class="sg-fired" y="-57">'+(previewing?'КАНДИДАТ':'СРАБОТАЛА')+'</text>':''}</g>`;}).join('');
  this.svg.innerHTML=defs+`<g id="sg-world">${edgeHTML}${nodeHTML}<g id="sg-waves"></g></g>`;this.transform();
 }
 animate(event,p){const world=this.svg.querySelector('#sg-waves');if(!world)return;
  world.innerHTML=(event?.flows||[]).map(f=>{const path=this.svg.querySelector('#sg-edge-'+f.edgeId);if(!path)return '';const pt=path.getPointAtLength(path.getTotalLength()*p);
   return `<circle cx="${pt.x}" cy="${pt.y}" r="${3+f.amount*3}" fill="${f.kind==='inhibit'?'#efa6a0':'#baf28a'}"/><text class="sg-wave-label" x="${pt.x}" y="${pt.y-12}">${f.kind==='inhibit'?'−':'+'}${percent(f.amount)}</text>`;}).join('');
 }
 transform(){const g=this.svg.querySelector('#sg-world');if(g)g.setAttribute('transform',`translate(${this.camera.x},${this.camera.y}) scale(${this.camera.z})`);}
 fit(){if(this.svg.clientWidth<40||this.svg.clientHeight<40)return;const points=[...this.svg.querySelectorAll('[data-sgn]')].map(n=>this.positions[n.dataset.sgn]);if(!points.length)return;
  const minX=Math.min(...points.map(p=>p.x))-120,maxX=Math.max(...points.map(p=>p.x))+120,minY=Math.min(...points.map(p=>p.y))-85,maxY=Math.max(...points.map(p=>p.y))+85;
  this.camera.z=Math.min(1.2,(this.svg.clientWidth-35)/(maxX-minX),(this.svg.clientHeight-30)/(maxY-minY));
  this.camera.x=this.svg.clientWidth/2-(minX+maxX)/2*this.camera.z;this.camera.y=this.svg.clientHeight/2-(minY+maxY)/2*this.camera.z;this.transform();
 }
}

export function mountSignalLab(){
 const root=document.getElementById('sg-root');root.innerHTML=markup;
 let engine=new SignalEngine(),proposal=null,progress=0,last=0,run=false,stopAtAction=false,recognitionOnly=false,speed=1000,history=null,historyEngine=null;
 let recording=false,stopped=false,buffer=[],trainingScene=null,selectedObject='',ready=false,saveTimer=null,db=null,owns=true,dirty=false;
 let mode='sequential';
 const graph=new SignalGraph(sg$('graph'),()=>renderSelection(),()=>saveSoon());
 const editable=()=>ready&&history===null&&!run&&!recording&&!stopped;
 function toast(text){sg$('toast').textContent=text;sg$('toast').hidden=false;setTimeout(()=>{sg$('toast').hidden=true;},5000);}
 function currentEngine(){return history===null?engine:historyEngine;}
 function snapshot(){return {schema:'kolos-signal-ui/1',engine:engine.export(),speed,positions:graph.positions,query:sg$('query').value,
   draft:recording||stopped?{buffer,scene:trainingScene,query:sg$('query').value}:null};}
 function saveSoon(){if(!ready)return;dirty=true;sg$('save-status').textContent=owns?'Сохранение…':'Другая вкладка · экспорт';clearTimeout(saveTimer);saveTimer=setTimeout(save,150);}
 async function save(){if(!db||!owns){sg$('save-status').textContent='Сохраните JSON';return;}try{const data=snapshot();await new Promise((resolve,reject)=>{const tx=db.transaction('state','readwrite');tx.objectStore('state').put(data,'signal');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});dirty=false;sg$('save-status').textContent='Сохранено в браузере';}catch{sg$('save-status').textContent='Ошибка сохранения · экспорт';}}
 function halt(){run=false;last=0;controls();}
 function invalidate(){proposal=null;progress=0;last=0;}
 function operate(op){if(history!==null){toast('Сначала вернитесь к текущему состоянию');return false;}halt();invalidate();try{engine.perform(op);render();saveSoon();return true;}catch(err){toast(err.message);render();return false;}}
 function setHistory(index){halt();invalidate();history=index;historyEngine=engine.at(index);render();}
 function live(){halt();invalidate();history=null;historyEngine=null;render();}
 function controls(){
  const viewing=history!==null,training=recording||stopped;
  sg$('play').textContent=run?'Ⅱ Пауза':'▶ Пуск';sg$('play').disabled=!ready||training;
  sg$('step').disabled=!ready||run||training;sg$('to-action').disabled=!ready||run||training||viewing;
  for(const id of ['send','recall','continue','reset','clear','demo','copy','import','defaults'])sg$(id).disabled=!ready||run||training||viewing;
  sg$('query').disabled=!ready||run||training||viewing;
  sg$('positive').disabled=!editable()||!engine.model.used.length;sg$('negative').disabled=sg$('positive').disabled;
  sg$('record').disabled=!ready||run||training||viewing;
  sg$('stop').disabled=!recording;sg$('learn').disabled=!stopped||!buffer.length;sg$('discard').disabled=!training;
  sg$('keys').disabled=!recording||!trainingScene?.app;
  for(const id of ['shuffle','hide','show','reset-screen','add','object-name'])sg$(id).disabled=!editable();
  sg$('export').disabled=!ready;
  sg$('history-banner').hidden=!viewing;
  sg$('state-label').textContent=viewing?'История':recording?'Запись демонстрации':run?'Выполняется':proposal?'На паузе · шаг не записан':'На паузе';
  sg$('speed-label').textContent=(speed/1000).toFixed(2).replace('.',',')+' с';
  sg$('timeline').max=engine.operations.length;sg$('timeline').value=history??engine.operations.length;
  sg$('operation-count').textContent=`${history??engine.operations.length} / ${engine.operations.length}`;
  sg$('replay').disabled=training||!engine.operations.length;sg$('timeline').disabled=training;
  root.querySelectorAll('[data-config]').forEach(e=>e.disabled=!editable());
  for(const id of ['inhibit-from','inhibit-to','add-inhibit'])sg$(id).disabled=!editable();
 }
 function sceneForView(){return recording||stopped?trainingScene:currentEngine().model.scene;}
 function renderScene(cursorOverride){const s=sceneForView();const c=cursorOverride||s.cursor;
  sg$('screen').innerHTML=`<rect width="1000" height="600" rx="15" fill="#13251d"/>`+s.objects.filter(o=>o.visible).map(o=>`<g data-sgo="${sx(o.name)}" role="button" tabindex="0" transform="translate(${o.x},${o.y})" class="sg-object ${o.name===selectedObject?'selected':''}"><rect x="-75" y="-44" width="150" height="88" rx="17"/><text text-anchor="middle" y="10">${sx(o.name)}</text></g>`).join('')+`<g id="sg-cursor" transform="translate(${c.x},${c.y})"><path d="M0 -16V16M-16 0H16" stroke="#d6ffad" stroke-width="5"/><circle r="20" fill="none" stroke="#baf28a" stroke-width="2"/></g>`;
  sg$('under').textContent='Под курсором: '+(underCursor(s)||'—');sg$('coords').textContent=`${Math.round(s.cursor.x)} × ${Math.round(s.cursor.y)}`;
  sg$('app').textContent=s.app?'Открыто: '+s.app:'Рабочий стол';sg$('output').textContent=s.output||'—';sg$('scene-version').textContent='v'+s.version;
  sg$('training-state').textContent=recording?'● записывается':stopped?'готово к сохранению':'не записывается';
  sg$('buffer').textContent=buffer.map(actionLabel).join(' → ')||'Демонстрация пуста.';
 }
 function renderSelection(){const e=currentEngine(),m=e.model,s=graph.selected;const out=sg$('selected');
  if(!s){out.textContent='Выберите вершину или стрелку. Вес влияет на выбор, ID — нет.';return;}
  if(s.kind==='node'){
   const n=m.nodes.find(n=>n.id===s.id);if(!n){out.textContent='На этом шаге вершины ещё нет.';return;}
   const incoming=m.edges.filter(e=>e.to===n.id&&(e.kind==='excite'||e.kind==='inhibit'));
   out.innerHTML=`<h3>${sx(n.label)} <small>#${n.id}</small></h3><p>A = ${sfmt(n.a)} · T = ${sfmt(n.trace)} · R = ${n.r}</p><p>Тип: ${sx(n.kind)}${n.role?' / '+sx(n.role):''}${n.parent?' · контекст #'+n.parent:''}</p>`+
    (n.kind==='context'?`<label>Порог θ<input type="number" id="sg-node-threshold" min="0" max="1" step="0.05" value="${n.threshold??m.config.threshold}" ${editable()?'':'disabled'}></label>`:'')+
    incoming.map(l=>`<label>Связь №${l.id} (${l.kind==='inhibit'?'−':'+'}) из #${l.from}<input type="number" data-weight="${l.id}" min="0" max="1" step="0.05" value="${l.weight}" ${editable()?'':'disabled'}></label>`).join('');
  }else{
   const l=m.edges.find(l=>l.id===s.id);if(!l)return;
   out.innerHTML=`<h3>Связь №${l.id}: #${l.from} → #${l.to}</h3><p>${sx(l.kind)} · след участия ${sfmt(l.eligibility)}</p>`+
    (['excite','inhibit'].includes(l.kind)?`<label>Вес<input type="number" data-weight="${l.id}" min="0" max="1" step="0.05" value="${l.weight}" ${editable()?'':'disabled'}></label>`:'<p>Обязательные условия безопасности не ослабляются обучением.</p>');
  }
 }
 function render(){const e=currentEngine(),m=e.model,event=proposal?.event||e.events.at(-1);
  graph.render(m,event,!!proposal&&history===null);if(proposal)graph.animate(proposal.event,progress);
  sg$('message').textContent=proposal&&history===null?'Рассчитан следующий такт. Память и действие зафиксируются по окончании импульса.':(event?.observation?event.observation+' · ':'')+m.message;
  const rec=sg$('recognition'),isRecall=m.runMode==='recall',typed=Array.from(m.query),chars=isRecall?typed:[...typed,'↵'];
  const total=chars.length,done=Math.min(m.inputIndex,total),freeRecall=isRecall&&m.inputIndex>=m.prefixLength;
  const recognitionVisible=m.phase==='input'||m.status==='ready'||m.status==='recall-complete';
  rec.hidden=!recognitionVisible;
  if(recognitionVisible){
    const winner=event?.winner?m.nodes.find(n=>n.id===event.winner):null;
    const wc=winner?event?.candidates?.find(c=>c.id===winner.id):null;
    const current=freeRecall?'сеть выбирает сама':m.phase==='input'?(chars[done]??'↵'):'—';
    rec.innerHTML=`<div class="sg-rec-head"><b>${isRecall?'Распознано префикса':'Распознавание запроса'}: ${done} / ${total}</b><span>Сейчас: ${sx(current===' ' ? '␣' : current)}</span><span>${winner?`Последний победитель: ${sx(winner.label)} · A ${percent(wc?.activation)} / θ ${percent(wc?.threshold)}`:'Ожидание первого такта'}</span></div><div class="sg-rec-chars">${chars.map((ch,i)=>`<i class="${i<done?'done':i===done&&m.phase==='input'&&!freeRecall?'current':''}">${sx(ch===' ' ? '␣' : ch)}</i>`).join('')}</div>`;
  }
  const recallBox=sg$('recall-result');recallBox.hidden=!isRecall;
  if(isRecall){
    const raw=Array.from(m.continuationRaw||'').map(ch=>ch===' '?'␣':ch).join('')||'—';
    sg$('recall-prefix').textContent=m.query;sg$('recall-text').textContent=m.continuation||'—';sg$('recall-raw').textContent=raw;
    sg$('recall-state').textContent=m.status==='recall-complete'?'END достигнут':freeRecall?'автономная генерация':'распознаётся префикс';
  }
  sg$('message').dataset.state=m.status;
  sg$('count').textContent=`${m.nodes.filter(n=>n.kind==='context').length} контекстов · ${m.edges.filter(e=>e.kind==='excite').length} возбуждающих связей`;
  sg$('empty').hidden=m.nodes.length>1;
  sg$('phase').textContent=m.phase==='input'?`Запрос: ${m.inputIndex} / ${Array.from(m.query).length+1}`:m.phase==='execute'?'Исполнение':m.phase==='done'?'Конец':'Обучение';
  sg$('tick-label').textContent='Такт '+m.tick;
  sg$('candidates').innerHTML=event?.candidates?.length?`<table><thead><tr><th>Кандидат</th><th>Остаток</th><th>Вход + контекст</th><th>Итог / θ</th><th>Решение</th></tr></thead><tbody>`+event.candidates.map(c=>`<tr data-candidate="${c.id}" class="${event.winner===c.id?'winner':!c.allowed?'blocked':''}"><td>${sx(c.label)}</td><td>${percent(c.residual)}</td><td>+${percent(c.excitation)} +${percent(c.context)} +${percent(c.observation)} −${percent(c.inhibition)}</td><td><b>${percent(c.activation)}</b> / ${percent(c.threshold)}</td><td>${sx(c.reason||(event.winner===c.id?'Максимум · сработала':c.activation<c.threshold?'Ниже порога':'Конкурент'))}</td></tr>`).join('')+'</tbody></table>':'<p class="sg-hint">На следующем такте здесь появятся входящие вклады, максимальный сигнал и причины блокировок.</p>';
  sg$('journal').innerHTML=e.events.slice(-50).map((r,i)=>`<button data-history="${Math.max(0,e.events.length-50)+i+1}"><span>${Math.max(0,e.events.length-50)+i+1}</span> ${sx(r.kind)} · ${sx(r.message)}${r.executionId?' · '+sx(r.executionId):''}</button>`).reverse().join('');
  for(const el of root.querySelectorAll('[data-config]'))if(document.activeElement!==el)el.value=m.config[el.dataset.config];
  const selects=[sg$('inhibit-from'),sg$('inhibit-to')];
  if(selects[0].options.length!==m.nodes.filter(n=>n.kind==='context'||n.kind==='root').length)for(const select of selects)select.innerHTML=m.nodes.filter(n=>n.kind==='context'||n.kind==='root').map(n=>`<option value="${n.id}">#${n.id} ${sx(n.label)}</option>`).join('');
  renderScene();renderSelection();controls();sg$('progress').style.width=percent(progress)+'%';
 }
 function begin(){if(recording||stopped){toast('Сначала сохраните или сбросьте демонстрацию');return;}if(operate({kind:'start',query:sg$('query').value})){run=true;recognitionOnly=true;last=0;render();graph.fit();controls();}}
 function beginRecall(){if(recording||stopped){toast('Сначала сохраните или сбросьте демонстрацию');return;}if(operate({kind:'recall',prefix:sg$('query').value})){run=true;recognitionOnly=false;stopAtAction=false;last=0;render();graph.fit();controls();}}
 function resume(toAction=false){if(history===null){if(!['input','execute'].includes(engine.model.phase)){toast('Сначала передайте запрос');return;}
   if(STOP.has(engine.model.status)) {if(!operate({kind:'wake'}))return;}
  }stopAtAction=toAction;recognitionOnly=false;run=true;last=0;controls();}
 function tick(now){requestAnimationFrame(tick);if(!run||mode!=='signal'){last=now;return;}const dt=last?Math.min(80,now-last):0;last=now;
  try{
   if(history!==null){progress+=dt/speed;if(progress>=1){if(history>=engine.operations.length){halt();return;}history++;historyEngine=engine.at(history);progress=0;render();}return;}
   if(!proposal){proposal=engine.preview();progress=0;render();}
   progress=Math.min(1,progress+dt/speed);graph.animate(proposal.event,progress);sg$('progress').style.width=percent(progress)+'%';
   const before=engine.model.scene.cursor,after=proposal.next.scene.cursor;
   if(before.x!==after.x||before.y!==after.y){const c=root.querySelector('#sg-cursor');c?.setAttribute('transform',`translate(${before.x+(after.x-before.x)*progress},${before.y+(after.y-before.y)*progress})`);}
   if(progress<1)return;const result=engine.commit(proposal);invalidate();saveSoon();
   if(stopAtAction&&result.effect||recognitionOnly&&engine.model.status==='ready'||STOP.has(engine.model.status))halt();render();
  }catch(err){halt();invalidate();toast(err.message);render();}
 }
 function oneTick(){if(recording||stopped)return;halt();if(history!==null){setHistory(Math.min(engine.operations.length,history+1));return;}
  try{const result=engine.commit(proposal||engine.preview());invalidate();render();saveSoon();}catch(err){invalidate();toast(err.message);render();}}
 function changeScene(fn){if(!editable())return;const s=cloneSignal(engine.model.scene);fn(s);operate({kind:'scene',scene:s});}
 sg$('send').onclick=begin;sg$('recall').onclick=beginRecall;sg$('query').onkeydown=e=>{if(e.key==='Enter')begin();};sg$('query').oninput=saveSoon;
 sg$('continue').onclick=()=>resume();sg$('play').onclick=()=>run?halt():resume();sg$('step').onclick=oneTick;sg$('to-action').onclick=()=>resume(true);
 sg$('speed').oninput=e=>{speed=Number(e.target.value);controls();saveSoon();};
 sg$('reset').onclick=()=>operate({kind:'reset'});sg$('live').onclick=live;
 sg$('timeline').oninput=e=>setHistory(Number(e.target.value));
 sg$('replay').onclick=()=>{setHistory(0);run=true;controls();};
 sg$('journal-toggle').onclick=()=>{sg$('journal').hidden=!sg$('journal').hidden;setTimeout(()=>graph.fit(),50);};
 sg$('journal').onclick=e=>{const row=e.target.closest('[data-history]');if(row)setHistory(Number(row.dataset.history));};
 sg$('candidates').onclick=e=>{const row=e.target.closest('[data-candidate]');if(row){graph.selected={kind:'node',id:Number(row.dataset.candidate)};render();}};
 sg$('zoom-in').onclick=()=>{graph.camera.z=Math.min(3,graph.camera.z*1.2);graph.transform();};sg$('zoom-out').onclick=()=>{graph.camera.z=Math.max(.12,graph.camera.z/1.2);graph.transform();};
 sg$('fit').onclick=()=>graph.fit();sg$('view').onchange=e=>{graph.mode=e.target.value;graph.positions={};render();graph.fit();saveSoon();};
 sg$('selected').onchange=e=>{if(e.target.dataset.weight)operate({kind:'weight',id:Number(e.target.dataset.weight),value:Number(e.target.value)});else if(e.target.id==='sg-node-threshold')operate({kind:'threshold',id:graph.selected.id,value:Number(e.target.value)});};
 sg$('positive').onclick=()=>operate({kind:'feedback',value:1});sg$('negative').onclick=()=>operate({kind:'feedback',value:-1});
 sg$('add-inhibit').onclick=()=>operate({kind:'inhibitory',from:Number(sg$('inhibit-from').value),to:Number(sg$('inhibit-to').value),weight:.5});
 const labels={threshold:'Порог θ',weight:'Вес новых связей',pulse:'Импульс P',decay:'Остаток активации λ',traceDecay:'Остаток следа T',refractory:'Refractory (такты)',inhibition:'Остаток проигравших',margin:'Минимальный отрыв',contextGain:'Вклад контекста',observationGain:'Вклад наблюдения',eligibilityDecay:'Остаток участия связи',rewardRate:'Усиление за +',penaltyRate:'Ослабление за −'};
 sg$('config').innerHTML=Object.entries(DEFAULTS).map(([k,v])=>`<label>${labels[k]}<input type="number" data-config="${k}" min="0" max="${k==='refractory'?10:1}" step="${k==='refractory'?1:.05}" value="${v}"></label>`).join('');
 sg$('config').onchange=e=>{if(e.target.dataset.config)operate({kind:'config',values:{[e.target.dataset.config]:Number(e.target.value)}});};sg$('defaults').onclick=()=>operate({kind:'config',values:{...DEFAULTS}});
 function loadExample(){if(engine.operations.length&&!confirm('Заменить только сигнальный эксперимент примером? Последовательный режим останется.'))return;
  halt();invalidate();history=null;engine=calculatorDemo();graph.positions={};graph.selected=null;sg$('query').value='добавь траты 1700';render();graph.fit();saveSoon();toast('Пример обучен. Полная команда: «Передать запрос». Префикс: «Продолжить по памяти».');}
 sg$('demo').onclick=loadExample;sg$('empty-demo').onclick=loadExample;
 sg$('clear').onclick=()=>{if(!confirm('Удалить только сигнальный эксперимент? Сначала экспортируйте нужные данные.'))return;halt();invalidate();engine=new SignalEngine();history=null;graph.positions={};graph.selected=null;sg$('query').value='';render();graph.fit();saveSoon();};
 sg$('shuffle').onclick=()=>changeScene(s=>{const visible=s.objects.filter(o=>o.visible);const slots=visible.map(o=>({x:o.x,y:o.y}));visible.forEach((o,i)=>Object.assign(o,slots[(i+1)%slots.length]));});
 sg$('hide').onclick=()=>{if(!selectedObject){toast('Выберите объект на виртуальном экране');return;}changeScene(s=>{const o=s.objects.find(o=>o.name===selectedObject);if(o)o.visible=false;});};
 sg$('show').onclick=()=>changeScene(s=>s.objects.forEach(o=>o.visible=true));sg$('reset-screen').onclick=()=>changeScene(s=>{s.app='';s.output='';s.cursor={x:500,y:300};});
 sg$('add').onclick=()=>{const name=sg$('object-name').value.trim();if(!name){toast('Введите имя объекта');return;}changeScene(s=>{s.objects.push({name,x:200+(s.objects.length%3)*270,y:420,visible:true});});sg$('object-name').value='';};
 let drag=null;
 const sceneCoords=e=>{const r=sg$('screen').getBoundingClientRect();return{x:Math.max(75,Math.min(925,(e.clientX-r.left)/r.width*1000)),y:Math.max(60,Math.min(540,(e.clientY-r.top)/r.height*600))};};
 sg$('screen').onpointerdown=e=>{if(run||history!==null||stopped)return;const target=e.target.closest('[data-sgo]');if(!target)return;selectedObject=target.dataset.sgo;drag={name:selectedObject,x:e.clientX,y:e.clientY,moved:false,scene:cloneSignal(sceneForView())};sg$('screen').setPointerCapture(e.pointerId);};
 sg$('screen').onpointermove=e=>{if(!drag||recording)return;const p=sceneCoords(e);if(Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y)>5)drag.moved=true;
  if(drag.moved){const o=drag.scene.objects.find(o=>o.name===drag.name);o.x=Math.round(p.x);o.y=Math.round(p.y);const g=[...sg$('screen').querySelectorAll('[data-sgo]')].find(g=>g.dataset.sgo===drag.name);g?.setAttribute('transform',`translate(${o.x},${o.y})`);}};
 sg$('screen').onpointerup=e=>{if(!drag)return;const d=drag;drag=null;if(sg$('screen').hasPointerCapture(e.pointerId))sg$('screen').releasePointerCapture(e.pointerId);
  if(d.moved){operate({kind:'scene',scene:d.scene});return;}
  const s=sceneForView(),o=s.objects.find(o=>o.name===d.name);if(!o)return;
  if(recording){trainingScene.cursor={x:o.x,y:o.y};trainingScene.checked=o.name;trainingScene.app=o.name;trainingScene.output='';
   buffer.push({kind:'move',x:o.x,y:o.y},{kind:'check',object:o.name},{kind:'click',object:o.name});renderScene();controls();sg$('keys').focus();saveSoon();
  }else changeScene(s=>{s.cursor={x:o.x,y:o.y};});
 };
 sg$('screen').onpointercancel=()=>{drag=null;renderScene();};
 sg$('record').onclick=()=>{if(!sg$('query').value.trim()){toast('Сначала напишите запрос сверху');return;}halt();invalidate();recording=true;stopped=false;buffer=[];trainingScene=cloneSignal(engine.model.scene);trainingScene.app='';trainingScene.output='';render();saveSoon();};
 function finishTraining(){if(recording){recording=false;stopped=true;render();saveSoon();}}
 sg$('stop').onclick=finishTraining;sg$('discard').onclick=()=>{recording=false;stopped=false;buffer=[];trainingScene=null;render();saveSoon();};
 function recordKeys(text){if(!recording||!trainingScene.app)return;for(const value of Array.from(text)){if(buffer.length>=100){toast('Лимит демонстрации: 100 действий');break;}buffer.push({kind:'key',value});trainingScene.output+=value;}sg$('keys').value='';renderScene();controls();saveSoon();}
 sg$('keys').oninput=e=>recordKeys(e.target.value);sg$('keys').onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();finishTraining();}};
 sg$('learn').onclick=()=>{if(!stopped||!buffer.length)return;const actions=cloneSignal(buffer);recording=false;stopped=false;if(operate({kind:'teach',query:sg$('query').value,actions})){buffer=[];trainingScene=null;graph.positions={};render();graph.fit();saveSoon();}else{stopped=true;render();}};
 document.addEventListener('keydown',e=>{if(mode==='signal'&&e.key==='Escape'){if(recording){finishTraining();e.preventDefault();}else halt();}});
 document.addEventListener('kolos:signal:snapshot',e=>{if(typeof e.detail?.reply==='function')e.detail.reply(cloneSignal(snapshot()));});
 function download(data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='kolos-signal-experiment.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);}
 sg$('export').onclick=()=>download(snapshot());sg$('import').onclick=()=>sg$('file').click();
 function loadSnapshot(raw){
  let loaded,saved=raw;
  if(raw.schema==='kolos-graph-lab/1'){loaded=SignalEngine.fromLegacy(raw);saved={};}
  else loaded=SignalEngine.import(raw.schema==='kolos-signal-ui/1'?raw.engine:raw);
  const positions={};if(saved.positions)for(const [id,p]of Object.entries(saved.positions)){if(/^\d+$/.test(id)&&p&&Number.isFinite(p.x)&&Number.isFinite(p.y)&&Math.abs(p.x)<100000&&Math.abs(p.y)<100000)positions[id]={x:p.x,y:p.y};}
  const nextSpeed=Number(saved.speed)||1000;if(nextSpeed<250||nextSpeed>5000)throw new Error('Некорректная скорость');
  let draft=null;if(saved.draft){const test=new SignalEngine();test.perform({kind:'scene',scene:saved.draft.scene});if(saved.draft.buffer?.length)test.perform({kind:'teach',query:saved.draft.query,actions:saved.draft.buffer});draft=saved.draft;}
  halt();invalidate();engine=loaded;history=null;graph.positions=positions;graph.selected=null;speed=nextSpeed;sg$('speed').value=speed;sg$('query').value=saved.query??loaded.model.query;
  recording=false;stopped=!!draft;buffer=draft?.buffer||[];trainingScene=draft?.scene||null;
  render();graph.fit();
 }
 sg$('file').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;halt();try{if(f.size>12*1024*1024)throw new Error('Файл больше 12 МБ');const raw=JSON.parse(await f.text());if(engine.operations.length&&!confirm('Заменить только сигнальный эксперимент?'))return;loadSnapshot(raw);saveSoon();toast('Восстановлено на паузе. Старые действия не выполнялись.');}catch(err){toast('Импорт: '+err.message);}finally{e.target.value='';}};
 sg$('copy').onclick=()=>{let data=null;document.dispatchEvent(new CustomEvent('kolos:legacy:snapshot',{detail:{reply:value=>{data=value;}}}));if(!data){toast('Экспортируйте JSON старого режима и импортируйте его здесь.');return;}
  try{const converted=SignalEngine.fromLegacy(data);if(engine.operations.length&&!confirm('Создать сигнальную копию вместо текущей?'))return;halt();invalidate();engine=converted;history=null;sg$('query').value=engine.model.query;graph.positions={};render();graph.fit();saveSoon();toast('Скопированы демонстрации. Старый граф не изменён.');}catch(err){toast(err.message);}};
 sg$('help').onclick=()=>sg$('help-dialog').showModal();sg$('close-help').onclick=()=>sg$('help-dialog').close();
 document.addEventListener('kolos:mode',e=>{const next=e.detail.mode;
  if(next!=='signal'&&(recording||stopped)){e.preventDefault();toast('Сначала сохраните или сбросьте демонстрацию');return;}
  halt();mode=next;if(mode==='signal'){render();requestAnimationFrame(()=>graph.fit());}});
 document.addEventListener('visibilitychange',()=>{if(document.hidden){halt();save();}});window.addEventListener('pagehide',()=>save());
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 async function init(){try{if(navigator.locks)await new Promise(resolve=>{navigator.locks.request('kolos-signal-autosave',{ifAvailable:true},async lock=>{owns=!!lock;resolve();if(lock)await new Promise(()=>{});}).catch(()=>{owns=false;resolve();});});
   db=await new Promise((resolve,reject)=>{const req=indexedDB.open('KolosSignalLab',1);req.onupgradeneeded=()=>req.result.createObjectStore('state');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});
   const data=await new Promise((resolve,reject)=>{const req=db.transaction('state').objectStore('state').get('signal');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});if(data)loadSnapshot(data);
   sg$('save-status').textContent=owns?'Сохранено в браузере':'Другая вкладка · экспорт';
  }catch{sg$('save-status').textContent='Автосохранение недоступно · экспорт';}
  ready=true;render();requestAnimationFrame(tick);
 }
 init();
}
