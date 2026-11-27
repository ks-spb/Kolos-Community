import {NeuronScope} from '../neurons/app.mjs';
import {prepareLanguage,runLanguageExperiment} from './language-cases.mjs';
import {prepareImagery,runImageryExperiment} from './imagery-cases.mjs';
import {CAPABILITY_NAMES,prepareCapability,runCapability,capabilityIntervention} from './capability-cases.mjs';
import {StateEngine,STATE_DEFAULTS,prepareCase,runCase,actionText} from './core.mjs';
import {defaultWorld,validateWorld,observeWorld,observationKey,visibleIcons,worldUnder,applyWorld,demonstration,iconDemonstrationActions} from './environment.mjs';
const st$=id=>document.getElementById('st-'+id),stCopy=x=>structuredClone(x);
const stEscape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stPercent=x=>Math.round((x||0)*100),stFormat=x=>Number(x||0).toFixed(2);
const stStops=new Set(['idle','trained','complete','unknown','failed','timeout','ambiguous','blocked','limit']);
const caseNames=CAPABILITY_NAMES;
const stateMarkup=`
<header class="st-header"><div><span class="st-eyebrow">KOLOS · НАБЛЮДАЕМАЯ СРЕДА</span><h1>Состояния и цели</h1><p>Опыт связывает состояния. Сигнал выбирает переход. Подтверждение освобождает следующий шаг.</p></div><div class="st-header-actions"><span id="st-storage">Память браузера</span><button id="st-neurons">Нейроны · живой граф</button><button id="st-import">Импорт</button><button id="st-export">Экспорт</button><button id="st-help">?</button></div></header>
<section class="st-cases" aria-label="Десять контрольных сценариев">${caseNames.map((label,i)=>`<button id="st-case-${i+1}" data-case="${i+1}"><b>${String(i+1).padStart(2,'0')}</b><span>${label}</span></button>`).join('')}<button id="st-suite" class="st-primary">Проверить 4 теста</button><button id="st-suite-ten" class="st-primary">Проверить 10 тестов</button></section>
<div class="st-image-controls"><button id="st-image-demo"><b>11</b> Образ цели</button><button id="st-image-test">Проверить опыт 11</button><span>Образ ≠ наблюдение. Один код содержимого, независимые источники.</span></div>
<details id="st-language-panel"><summary><b>12 · Язык → образ</b> — обучение фразам и новый запрос</summary>
<div class="st-controls"><button id="st-language-demo">12 Язык → образ: пример</button><button id="st-language-test">Проверить опыт 12</button></div>
<div class="st-language-composer"><input id="st-language-phrase" aria-label="Фраза для образа" placeholder="я хочу увидеть 1354 в поле" maxlength="240"><button id="st-language-read" class="st-primary">Понять и представить</button><button id="st-language-act">Понять и достичь</button></div>
<p id="st-language-progress" role="status">Для вывода образа нужны обученные пары. Поле и значение здесь выбирать не требуется.</p>
<div id="st-language-chars"></div><svg id="st-language-graph" aria-label="Активные языковые связи"></svg><div id="st-language-decoded"></div>
<details id="st-language-training"><summary>Обучить связь фразы с образом</summary><p>Выбор поля/состояния нужен только при обучении. Для переменного содержимого покажите два разных значения с одинаковым окружением. Слова, регистр и пробелы значимы.</p><div class="st-controls"><input id="st-language-train-phrase" aria-label="Фраза обучающего примера" placeholder="я хочу увидеть 1700 в поле" maxlength="240"><select id="st-language-target" aria-label="Образ обучающего примера"></select><input id="st-language-value" aria-label="Содержимое обучающего образа" placeholder="1700" maxlength="160"><button id="st-language-teach">Запомнить подтверждённую пару</button></div><div id="st-language-lessons"></div><details><summary>Выученные связи и веса</summary><div id="st-language-weights"></div></details></details></details>
<div id="st-case-note">Выберите контрольный сценарий или запишите свои демонстрации. Загрузка теста заменяет только память этого режима.</div>
<div id="st-suite-results" hidden></div>
<details id="st-goal-builder"><summary>Задать желаемый результат без команды</summary><p>Выберите ранее наблюдавшееся состояние или читаемое поле. Это явное задание цели, не понимание произвольной фразы. Действия и маршрут сеть выбирает из опыта.</p><div class="st-controls"><select id="st-goal-target" aria-label="Наблюдаемая цель"></select><input id="st-goal-value" aria-label="Желаемое содержимое поля" placeholder="Например: 2345" maxlength="160"><button id="st-goal-add">Добавить цель</button><button id="st-goal-clear">Очистить цели</button><button id="st-goal-start" class="st-primary">Выполнить цели</button><button id="st-image-build">Представить без действий</button></div><div id="st-goal-draft">Нет целей</div></details>
<section id="st-image-panel" hidden aria-label="Внутренний образ и внешнее наблюдение">
<div class="st-image-controls"><strong>Образ и наблюдение</strong><span id="st-image-mode"></span><button id="st-image-act" class="st-primary">Достичь образа</button><button id="st-image-rest">Снять поддержку</button></div>
<p id="st-image-summary" role="status"></p><div id="st-image-nodes"></div><small>Каждая карточка — одна вершина. I — внутренний вход, S — сенсорный. Только S при наличии признака сейчас может подтвердить результат.</small>
</section><div id="st-intent-status" hidden></div>
<div class="st-query"><input id="st-query" aria-label="Команда в режиме состояний" placeholder="Например: открой окно" maxlength="160"><button id="st-start" class="st-primary">Передать запрос</button></div>
<div class="st-status"><span id="st-message" role="status">Нет показанных переходов.</span><span id="st-goal">Цель не задана</span></div>
<div class="st-workspace"><main class="st-main"><div class="st-graphbar"><span id="st-state-label">Наблюдаемое состояние</span><div><select id="st-view" aria-label="Слой графа"><option value="states">Состояния и переходы</option><option value="actions">Действия и состояния</option><option value="all">Все вершины</option></select><button id="st-zoom-in">+</button><button id="st-zoom-out">−</button><button id="st-fit" title="Уместить граф">Уместить</button></div></div>
<div class="st-stage"><svg id="st-graph" aria-label="Граф состояний и распространения активации" role="group"></svg><div class="st-legend">Зелёная рамка — наблюдаемое состояние · янтарная — удерживаемая цель · импульсы — обратное возбуждение</div></div>
<div class="st-input-panel"><div class="st-small-title">ТЕКУЩИЙ НЕОТРАБОТАННЫЙ ЗАПРОС <span id="st-input-count"></span></div><div id="st-input"></div></div>
<div class="st-candidate-panel"><div class="st-small-title">КАНДИДАТЫ И ИСТОЧНИКИ СИГНАЛА</div><div id="st-candidates"></div></div></main>
<aside class="st-side"><div class="st-small-title">ВИРТУАЛЬНЫЙ РАБОЧИЙ СТОЛ <span id="st-surface"></span></div>
<svg id="st-screen" viewBox="0 0 1000 600" role="group" aria-label="Рабочий стол или перекрывающее его окно"></svg>
<div class="st-screen-meta"><span id="st-under"></span><span id="st-selected-icon"></span></div><div class="st-output"><span id="st-focus">Нет поля ввода</span><strong id="st-output">—</strong></div>
<div class="st-controls"><button id="st-desk">Рабочий стол</button><button id="st-window">Открытое окно</button><button id="st-calc">CALC</button></div><p class="st-hint">Эти кнопки задают условия стенда. Они не обучают переходам.</p>
<div class="st-controls"><button id="st-move-icon">Переставить выбранную</button><button id="st-hide-icon">Скрыть</button><button id="st-show-icons">Показать все</button></div>
<details id="st-teaching"><summary>Своё обучение</summary><p class="st-hint">Запрос сверху → начать → клик по иконке → Enter при необходимости → закончить → сохранить и подтвердить. Клик по A лишь выделяет её; окно открывает Enter.</p><div class="st-controls"><button id="st-record">● Начать</button><button id="st-stop">■ Закончить</button><button id="st-enter">Enter ↵</button></div><input id="st-keys" placeholder="Клавиши в открытом поле" aria-label="Клавиатура демонстрации" autocomplete="off"><div id="st-demo-list"></div><div class="st-controls"><button id="st-learn" class="st-primary">Сохранить + подтвердить</button><button id="st-discard">Сбросить запись</button></div></details>
<details id="st-prior"><summary>Прежние вводы символов</summary><p class="st-hint">Соответствия неизвестных клавиш не встроены. Укажите прежний ввод в поле отдельного виртуального CALC. Это не обучение команде «добавь траты».</p><input id="st-prior-text" placeholder="Например: 5432" aria-label="Прежний ввод"><button id="st-expose">Подтвердить прежний ввод</button><div id="st-alphabet"></div></details>
<details id="st-ack-settings" open><summary>Подтверждение от среды</summary><select id="st-ack-mode" aria-label="Режим подтверждения"><option value="auto">Автоматически</option><option value="manual">Доставить вручную</option><option value="delay">С задержкой</option><option value="drop">Потерять подтверждение</option><option value="reject">Отклонить действие</option></select><div class="st-settings"><label>Задержка, такты<input id="st-ack-delay" type="number" min="0" max="150" value="4"></label><label>Тайм-аут, такты<input id="st-timeout" type="number" min="2" max="200" value="40"></label></div><div id="st-pending"></div></details>
<details id="st-parameters"><summary>Параметры возбуждения</summary><div id="st-config"></div><p class="st-hint">Изменяются реальные коэффициенты, а не только цвет графа. Скорость показа не входит в расчёт.</p></details>
<details id="st-selection"><summary>Выбранная вершина / связь</summary><div id="st-selection-detail">Нажмите на граф.</div></details>
<details id="st-evidence"><summary>Опыт и соответствия</summary><div id="st-audit"></div></details>
</aside></div>
<div id="st-history-banner" hidden>Просмотр истории — без действий в живой среде. <button id="st-live">К текущему состоянию</button></div>
<div class="st-playbar"><div class="st-controls"><button id="st-play" class="st-primary">▶ Пуск</button><button id="st-step">Один такт</button><button id="st-deliver">Доставить подтверждение</button><button id="st-reset">Новая попытка</button></div><label class="st-speed">Интервал <output id="st-speed-label">0,50 с</output><input id="st-speed" type="range" min="100" max="3000" step="100" value="500"></label><span id="st-play-state">На паузе</span><button id="st-clear">Очистить</button></div>
<div class="st-timeline"><span id="st-operation">0 / 0</span><input id="st-timeline" type="range" min="0" max="0" value="0" aria-label="История состояний"><span id="st-tick">Такт 0</span><button id="st-journal-toggle">Журнал</button></div><div class="st-progress"><div id="st-progress"></div></div><div id="st-journal" hidden></div>
<input type="file" id="st-file" accept=".json,application/json" hidden><div id="st-toast" hidden role="status"></div>
<dialog id="st-help-dialog"><button id="st-help-close">Закрыть</button><h2>Что проверяет модель</h2><p><b>Тесты 1 и 2:</b> две наблюдённые демонстрации учат прямому и обратному переходам. Выделенная иконка — отдельный наблюдаемый контекст, поэтому Enter не смешивается с кликом.</p><p><b>Тест 3:</b> цель исходной команды остаётся активной. Возбуждение идёт от нужного состояния назад по связям ранее наблюдённых переходов. Исполнимый переход с максимальным сигналом выбирается; после его подтверждения возобновляется исходное действие. Комбинация X → A → Enter не показывалась.</p><p><b>Тест 4:</b> клавиши 5, 4, 3, 2 вводились ранее в отдельном поле; затем один раз показаны «добавь траты 1700» и действия. Новый запрос 2345 обрабатывается по временным вхождениям, которые гасятся только после подтверждения. Неизвестные символы не выдумываются.</p><p>Модель использует веса, утечку активации, пороги, конкуренцию и refractory. Это инженерный эксперимент с нейроноподобной динамикой, не доказанная модель человеческого мозга. Состояния определяются набором видимых объектов, выделением и фокусом. Их имена и правила среды движку выбора маршрута недоступны.</p><p>Память этого режима отдельная. Экспортируйте её перед заменой тестовым примером. Интервал регулирует только анимацию. На паузе не идут расчёты и тайм-ауты.</p></dialog>`;

class StateGraphView{
 constructor(svg,onSelect,onMove){this.svg=svg;this.onSelect=onSelect;this.onMove=onMove;this.positions={};this.view='states';this.selection=null;this.camera={x:0,y:0,z:1};this.drag=null;
  svg.addEventListener('wheel',e=>{e.preventDefault();this.camera.z=Math.max(.08,Math.min(3,this.camera.z*(e.deltaY<0?1.12:.89)));this.transform();},{passive:false});
  svg.onpointerdown=e=>{const n=e.target.closest('[data-stn]'),l=e.target.closest('[data-ste]');if(n||l){this.selection=n?{node:n.dataset.stn}:{edge:l.dataset.ste};this.onSelect();}this.drag={id:n?.dataset.stn,x:e.clientX,y:e.clientY};svg.setPointerCapture(e.pointerId);};
  svg.onpointermove=e=>{if(!this.drag)return;const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;Object.assign(this.drag,{x:e.clientX,y:e.clientY});if(this.drag.id){const p=this.positions[this.drag.id];p.x+=dx/this.camera.z;p.y+=dy/this.camera.z;this.render(this.m,this.ev,this.preview);}else{this.camera.x+=dx;this.camera.y+=dy;this.transform();}};
  const end=()=>{if(this.drag)this.onMove();this.drag=null;};svg.onpointerup=end;svg.onpointercancel=end;
  new ResizeObserver(()=>{if(this.m)this.fit();}).observe(svg);
 }
 render(m,ev,preview=false){this.m=m;this.ev=ev;this.preview=preview;
  const activeGoal=m.intent?.goals.find(g=>g.id===m.intent.active);
  const working=m.intent?[...m.intent.goals.map((g,i)=>({id:g.id,kind:'working-goal',label:'Результат '+(i+1),a:g.a})),...Object.entries(m.intent.error).map(([id,a])=>({id:'error:'+id,kind:'error',label:'Ошибка → '+id,a}))]:[];
  const list=[...working,...m.memory.nodes.filter(n=>this.view==='all'||['state','transition'].includes(n.kind)||this.view==='actions'&&n.kind==='step')];
  let state=0,transition=0,extra=0;
  for(const n of list){let p;if(n.kind==='state'){const i=state++;p={x:160+(i%3)*330,y:100+Math.floor(i/3)*430};}else if(n.kind==='transition'){const i=transition++;p={x:160+(i%3)*330,y:310+Math.floor(i/3)*430};}else{const i=extra++;p={x:160+(i%4)*245,y:640+Math.floor(i/4)*160};}if(!this.positions[n.id])this.positions[n.id]=p;}
  const ids=new Set(list.map(n=>n.id)),key=observationKey(m.observed),current=m.memory.nodes.find(n=>n.kind==='state'&&n.key===key)?.id;
  const workEdges=m.intent?[...m.intent.goals.flatMap(g=>g.targets.map(id=>({id:'goal:'+g.id+':'+id,from:g.id,to:id,kind:'goal-drive',weight:g.held?1:0}))),...m.intent.goals.filter(g=>g.previous).map(g=>({id:'wait:'+g.id,from:g.previous,to:g.id,kind:'inhibitory',weight:m.intent.goals.find(p=>p.id===g.previous).held?1:0})),...Object.keys(m.intent.error).map(id=>({id:'suppress:'+id,from:'error:'+id,to:id,kind:'inhibitory',weight:m.intent.config.errorGain}))]:[];
  const edges=[...workEdges,...m.memory.edges].filter(e=>ids.has(e.from)&&ids.has(e.to)&&(!['observes','experienced','applicable'].includes(e.kind)||this.view!=='states'));
  const edgeHTML=edges.map(e=>{const a=this.positions[e.from],b=this.positions[e.to],dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,ux=dx/len,uy=dy/len;
   const radius=52,reverse=edges.some(x=>x.from===e.to&&x.to===e.from),bend=reverse?36:18;
   const x1=a.x+ux*radius,y1=a.y+uy*radius,x2=b.x-ux*radius,y2=b.y-uy*radius,cx=(x1+x2)/2-uy*bend,cy=(y1+y2)/2+ux*bend;
   const d=`M${x1},${y1} Q${cx},${cy} ${x2},${y2}`,flow=ev?.flows?.find(f=>f.edge===e.id);
   return `<g data-ste="${e.id}" class="st-edge ${e.kind} ${this.selection?.edge===e.id?'selected':''}"><path class="st-hit" d="${d}"/><path id="st-edge-${e.id}" d="${d}" marker-end="url(#st-arrow)"/><text x="${(x1+2*cx+x2)/4}" y="${(y1+2*cy+y2)/4-10}">${stEscape(e.id)} · ${stFormat(e.weight)}${flow?' · +'+stPercent(flow.value):''}</text></g>`;
  }).join('');
  const nodeHTML=list.map(n=>{const p=this.positions[n.id],a=n.a??(m.goalActivation[n.id]||m.activation[n.id]||0),c=ev?.candidates?.find(c=>c.id===n.id),v=preview&&c?c.a:a;
   const suffix=n.kind==='state'?(n.features.find(f=>f.startsWith('selected:')&&f!=='selected:')?.slice(9)||''):'';
   const fullLabel=n.label+(suffix?' · выделена '+suffix:'');
   const label=fullLabel.length>25?fullLabel.slice(0,23)+'…':fullLabel,goal=m.plan?.goal===n.id||activeGoal?.targets.includes(n.id),now=current===n.id,win=ev?.winner===n.id;
   const hint=n.kind==='state'?n.features.filter(f=>f.startsWith('visible:')).map(f=>f.slice(8)).join(' · '):n.kind==='transition'?'наблюдённый переход':n.kind;
   return `<g data-stn="${n.id}" tabindex="0" role="button" aria-label="${stEscape(n.label)}" class="st-node ${n.kind} ${now?'current':''} ${goal?'goal':''} ${win?'winner':''} ${this.selection?.node===n.id?'selected':''}" transform="translate(${p.x},${p.y})" style="--energy:${v}"><title>${stEscape(hint)}</title><rect class="st-aura" x="-116" y="-57" width="232" height="116" rx="20"/><rect class="st-node-box" x="-108" y="-50" width="216" height="100" rx="14"/><text class="st-node-label" y="-25">${stEscape(label)}</text><text y="-4" class="st-node-detail">${stEscape(hint.length>29?hint.slice(0,27)+'…':hint)}</text><text y="18" class="st-node-signal">A ${stPercent(v)} · R ${m.refractory[n.id]||0} · T ${stFormat(m.trace[n.id])}</text><text y="36" class="st-node-id">${n.id}${now?' · НАБЛЮДАЕТСЯ':''}${goal?' · ЦЕЛЬ':''}${win?' · МАКСИМУМ':''}</text></g>`;
  }).join('');
  this.svg.innerHTML=`<defs><pattern id="st-dot" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#2b3d35"/></pattern><marker id="st-arrow" orient="auto" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"><path d="M0 0L10 5L0 10" fill="#bba776"/></marker></defs><rect width="100%" height="100%" fill="url(#st-dot)"/><g id="st-world">${edgeHTML}${nodeHTML}<g id="st-waves"></g></g>`;this.transform();
 }
 animate(ev,p){const group=this.svg.querySelector('#st-waves');if(!group)return;group.innerHTML=(ev?.flows||[]).map(f=>{const el=document.getElementById('st-edge-'+f.edge);if(!el||!this.svg.contains(el))return '';const point=el.getPointAtLength(el.getTotalLength()*p);return `<circle cx="${point.x}" cy="${point.y}" r="5" fill="#ffca73"/><text x="${point.x}" y="${point.y-12}" class="st-wave-label">+${stPercent(f.value)}</text>`;}).join('');}
 transform(){this.svg.querySelector('#st-world')?.setAttribute('transform',`translate(${this.camera.x},${this.camera.y}) scale(${this.camera.z})`);}
 fit(){if(this.svg.clientWidth<30||this.svg.clientHeight<30)return;const pts=[...this.svg.querySelectorAll('[data-stn]')].map(el=>this.positions[el.dataset.stn]);if(!pts.length)return;
  const minX=Math.min(...pts.map(p=>p.x))-135,maxX=Math.max(...pts.map(p=>p.x))+135,minY=Math.min(...pts.map(p=>p.y))-80,maxY=Math.max(...pts.map(p=>p.y))+90;
  this.camera.z=Math.min(1.25,(this.svg.clientWidth-35)/(maxX-minX),(this.svg.clientHeight-35)/(maxY-minY));this.camera.x=this.svg.clientWidth/2-(minX+maxX)/2*this.camera.z;this.camera.y=this.svg.clientHeight/2-(minY+maxY)/2*this.camera.z;this.transform();}
}

export function mountStateLab(){
 const root=document.getElementById('st-root');root.innerHTML=stateMarkup;
 let engine=new StateEngine(),mode='sequential',running=false,proposal=null,progress=0,last=0,speed=500,ready=false,history=null,historyEngine=null;
 let recording=false,draft=null,selectedIcon='',selectedCase=0,db=null,saveTimer=null,storageOwner=true;
 let caseOperation=null,interventionState={},goalDraft=[],languageAutoAct=false;
 const graph=new StateGraphView(st$('graph'),()=>renderSelection(),()=>saveSoon());
 const live=()=>history===null,editable=()=>ready&&live()&&!running&&!recording&&!draft&&!engine.model.pending;
 const current=()=>live()?engine:historyEngine;
 function toast(message){st$('toast').textContent=message;st$('toast').hidden=false;setTimeout(()=>st$('toast').hidden=true,4500);}
 function snapshot(){return {schema:'kolos-state-ui/1',engine:engine.export(),speed,query:st$('query').value,positions:graph.positions,view:graph.view,languagePhrase:st$('language-phrase').value,draft:stCopy(draft),selectedCase,caseOperation:stCopy(caseOperation),interventionState:stCopy(interventionState),goalDraft:stCopy(goalDraft)};}
 function saveSoon(){if(!ready)return;clearTimeout(saveTimer);saveTimer=setTimeout(save,220);}
 async function save(){if(!db||!storageOwner){st$('storage').textContent='Экспорт JSON — резервная копия';return;}try{const value=snapshot();await new Promise((res,rej)=>{const tx=db.transaction('state','readwrite');tx.objectStore('state').put(value,'current');tx.oncomplete=res;tx.onerror=()=>rej(tx.error);});st$('storage').textContent='Сохранено в браузере';}catch{st$('storage').textContent='Ошибка памяти — экспортируйте JSON';}}
 function halt(){languageAutoAct=false;running=false;last=0;controls();}
 function invalidate(){proposal=null;progress=0;last=0;}
 function operate(op){if(!live()){toast('Вернитесь к текущему состоянию');return false;}halt();invalidate();try{engine.perform(op);render();saveSoon();return true;}catch(e){toast(e.message);render();return false;}}
 function controls(){const training=recording||!!draft,busy=running||training||!live();
  for(const id of ['start','reset','clear','suite','suite-ten','import','record','expose','goal-add','goal-clear','goal-start','image-demo','image-test','image-build','image-act','image-rest'])st$(id).disabled=!ready||busy;
  for(let i=1;i<=10;i++)st$('case-'+i).disabled=!ready||busy;
  for(const id of ['language-demo','language-test','language-read','language-act','language-teach','language-phrase','language-train-phrase','language-target','language-value'])st$(id).disabled=!ready||busy||!!engine.model.pending;
  st$('start').disabled||=!!engine.model.pending;
  st$('image-build').disabled||=!goalDraft.length||!!engine.model.pending;
  for(const id of ['image-act','image-rest'])st$(id).disabled||=!engine.model.imagery||!!engine.model.pending;
  st$('query').disabled=!ready||running||training||!live();st$('query').readOnly=['goal','imagine'].includes(caseOperation?.kind);st$('goal-start').disabled||=!goalDraft.length;st$('goal-target').disabled=!editable();st$('goal-value').disabled=!editable();st$('play').textContent=running?'Ⅱ Пауза':'▶ Пуск';st$('play').disabled=!ready||training||!live();
  st$('step').disabled=!ready||running||training;st$('deliver').disabled=!ready||running||training||!live()||!engine.model.pending?.receipt;
  st$('play-state').textContent=history!==null?'История':recording?'Запись демонстрации':running?'Выполняется':'На паузе';
  st$('stop').disabled=!recording;st$('enter').disabled=!recording||!draft?.world.selected;st$('learn').disabled=recording||!draft?.actions.length;st$('discard').disabled=!draft;
  st$('keys').disabled=!recording||!draft?.world.focus;st$('export').disabled=!ready;
  for(const id of ['desk','window','calc','move-icon','hide-icon','show-icons','ack-mode','ack-delay','timeout','prior-text'])st$(id).disabled=!editable();
  root.querySelectorAll('[data-stconfig]').forEach(el=>el.disabled=!editable());
  for(const [id,surface] of [['desk','desk'],['window','window'],['calc','calculator']])st$(id).disabled||=!scene().surfaces[surface];
  st$('speed-label').textContent=(speed/1000).toFixed(2).replace('.',',')+' с';st$('history-banner').hidden=live();
  st$('timeline').max=engine.operations.length;st$('timeline').value=history??engine.operations.length;st$('timeline').disabled=training;
  st$('operation').textContent=`${history??engine.operations.length} / ${engine.operations.length}`;
 }
 function scene(){return draft?draft.world:current().model.world;}
 function renderScreen(){const w=scene(),o=observeWorld(w),s=w.surfaces[w.surface];
  st$('screen').innerHTML=`<rect width="1000" height="600" rx="16" fill="${w.surface==='desk'?'#152c24':'#253035'}"/><rect x="15" y="15" width="970" height="570" rx="12" fill="none" stroke="#54726a" stroke-width="2"/><text x="36" y="57" class="st-surface-title">${stEscape(s.label)}</text>${visibleIcons(w).map(i=>`<g data-stobj="${stEscape(i.id)}" role="button" tabindex="0" aria-label="Иконка ${stEscape(i.id)}" transform="translate(${i.x},${i.y})" class="st-icon ${o.selected===i.id?'active':''} ${selectedIcon===i.id?'selected':''}"><rect x="-65" y="-42" width="130" height="84" rx="13"/><text text-anchor="middle" y="10">${stEscape(i.label)}</text><title>${stEscape(i.id)} · ${i.x} × ${i.y}</title></g>`).join('')}${s.field?`<rect x="130" y="430" width="740" height="104" rx="12" fill="#0b1918" stroke="#5b816c" stroke-width="2"/><text x="170" y="491" class="st-field-text">${stEscape(w.output||'0')}</text>`:''}<g id="st-cursor" transform="translate(${o.cursor.x},${o.cursor.y})"><path d="M-18 0H18M0-18V18" stroke="#ceffae" stroke-width="5"/><circle r="22" fill="none" stroke="#ceffae" stroke-width="2"/></g>`;
  st$('surface').textContent=s.label;st$('screen').dataset.surface=w.surface;st$('under').textContent='Под курсором: '+(worldUnder(w)||'—');st$('selected-icon').textContent='Выделено: '+(o.selected||'—');
  st$('focus').textContent=o.focus?'Фокус: '+o.focus:'Нет поля ввода';st$('output').textContent=o.output||'—';
  st$('demo-list').textContent=draft?draft.actions.map(actionText).join(' → '):'Демонстрация не записывается.';
 }
 function renderSelection(){const m=current().model,s=graph.selection,el=st$('selection-detail');if(!s){el.textContent='Нажмите на вершину или стрелку';return;}
  if(s.node){const n=m.memory.nodes.find(n=>n.id===s.node);if(!n){const goal=m.intent?.goals.find(g=>g.id===s.node);if(goal){el.textContent='Временная цель · A '+stPercent(goal.a)+' · '+(goal.held?'удерживается':'подтверждена');return;}if(s.node.startsWith('error:')){el.textContent='Тормозящий след ошибки · A '+stPercent(m.intent?.error[s.node.slice(6)]);return;}el.textContent='На этом шаге вершины ещё нет';return;}el.innerHTML=`<b>${stEscape(n.label)} · ${n.id}</b><p>${stEscape(n.kind)} · A ${stFormat(m.goalActivation[n.id]||m.activation[n.id])}</p>${n.features?`<p>${n.features.map(stEscape).join('<br>')}</p>`:''}${n.evidence?`<p>${n.evidence.map(stEscape).join('<br>')}</p>`:''}`;}
  else{const e=m.memory.edges.find(e=>e.id===s.edge);if(!e){el.textContent='Временная связь рабочей памяти; не изменяет долговременные веса.';return;}el.innerHTML=`<b>${e.id}: ${e.from} → ${e.to}</b><p>${stEscape(e.kind)}</p><label>Вес<input id="st-edge-weight" type="number" min="0" max="1" step="0.05" value="${e.weight}" ${editable()?'':'disabled'}></label>`;}
 }
 function render(){const e=current(),m=e.model,ev=proposal&&live()?proposal.event:e.events.at(-1);graph.render(m,ev,!!proposal&&live());if(proposal)graph.animate(proposal.event,progress);
  st$('message').textContent=proposal?'Расчёт следующего такта: '+(proposal.event.message||m.message):m.message;st$('message').dataset.state=m.status;
  st$('goal').textContent=m.heldGoal?'Цель удерживается: '+m.query:m.status==='complete'?'Цель подтверждена':'Цель не задана';st$('goal').dataset.held=String(m.heldGoal);
  const observed=m.memory.nodes.find(n=>n.kind==='state'&&n.key===observationKey(m.observed));st$('state-label').textContent='Наблюдается: '+(observed?.label||'неизвестный набор признаков')+(m.plan?' · нужно '+m.memory.nodes.find(n=>n.id===m.plan.goal)?.label:'');
  st$('input').innerHTML=m.occ.length?m.occ.map(q=>`<span data-stocc="${q.id}" class="${!q.held?'consumed':m.pending?.source===q.id?'waiting':'held'}" title="${q.id} · H ${q.held?100:0} · A ${stPercent(q.a)}">${stEscape(q.value===' '?'␣':q.value)}</span>`).join(''):'<small>Вхождения запроса появятся после передачи.</small>';
  st$('input-count').textContent=m.occ.length?`${m.occ.filter(q=>!q.held).length} / ${m.occ.length}`:'';
  st$('tick').textContent='Такт '+m.tick;
  st$('candidates').innerHTML=ev?.candidates?.length?`<table><thead><tr><th>Кандидат</th><th>Вход</th><th>Опыт / цель</th><th>Торможение</th><th>A / θ</th><th>Состояние</th></tr></thead><tbody>${ev.candidates.map(c=>`<tr class="${ev.winner===c.id?'winner':!c.allowed?'blocked':''}"><td>${stEscape(c.label)}</td><td>${stPercent(c.input)}</td><td>${stPercent(c.history)}</td><td>−${stPercent(c.inhibition)}</td><td>${stPercent(c.a)} / ${stPercent(c.threshold)}</td><td>${stEscape(c.reason||(!c.allowed?'Refractory':ev.winner===c.id?'Максимум':c.a<c.threshold?'Ниже порога':'Конкурент'))}</td></tr>`).join('')}</tbody></table>`:`<p class="st-hint">${m.pending?'Ожидается отдельное подтверждение. Исходная цель не погашена.':'Кандидаты появятся при очередном расчёте возбуждения.'}</p>`;
  const p=m.pending;st$('pending').textContent=p?`${p.id} · ${actionText(p.action)} · ${p.applied?'Эффект обработан, подтверждение не доставлено':'Действие выбрано, эффект ещё не выполнен'}`:'Неподтверждённых действий нет';
  st$('audit').innerHTML=`<p>Демонстраций команд: ${m.lessons.length}. Прежних вводов: ${m.exposures.length}.</p>`+m.audit.map(a=>`<p><b>${stEscape(a.query)}</b><br>${stEscape(a.source)}${a.data?'<br>Показанные символы: '+a.alignment.map(x=>stEscape(x.symbol)).join(''):''}</p>`).join('');
  st$('alphabet').textContent='Наблюдённые клавиши: '+(m.memory.nodes.filter(n=>n.kind==='motor').map(n=>n.value).join(' · ')||'нет');
  for(const el of root.querySelectorAll('[data-stconfig]'))if(el!==document.activeElement)el.value=m.intent?.config[el.dataset.stconfig==='planThreshold'?'routeThreshold':el.dataset.stconfig]??m.config[el.dataset.stconfig];
  if(st$('ack-mode')!==document.activeElement)st$('ack-mode').value=m.config.ackMode;
  if(st$('ack-delay')!==document.activeElement)st$('ack-delay').value=m.config.ackDelay;
  if(st$('timeout')!==document.activeElement)st$('timeout').value=m.config.timeout;
  st$('journal').innerHTML=e.events.slice(-70).map((v,i)=>`<button data-sthistory="${Math.max(0,e.events.length-70)+i+1}"><b>${v.tick||0}</b> ${stEscape(v.kind)} · ${stEscape(v.message||'')}</button>`).reverse().join('');
  const chosen=st$('goal-target').value, states=m.memory.nodes.filter(n=>n.kind==='state'),fields=[...new Set(states.flatMap(n=>n.features.filter(f=>f.startsWith('focus:')&&f!=='focus:').map(f=>f.slice(6))))];
  st$('goal-target').innerHTML=states.map(n=>`<option value="state:${n.id}">${stEscape(n.label+' · '+n.features.filter(f=>f.startsWith('visible:')).map(f=>f.slice(8)).join(', '))}</option>`).join('')+fields.map(f=>`<option value="field:${stEscape(f)}">Поле ${stEscape(f)}</option>`).join('');
  if([...st$('goal-target').options].some(o=>o.value===chosen))st$('goal-target').value=chosen;
  st$('goal-draft').textContent=goalDraft.map((g,i)=>`${i+1}. ${g.kind==='field'?g.focus+' = '+g.value:g.features.join(', ')}`).join(' → ')||'Нет целей';
  const intent=m.intent;st$('intent-status').hidden=!intent;
  if(intent){const err=intent.errorHistory.at(-1),prediction=m.pending?.prediction;
   st$('intent-status').innerHTML=`<b>Результаты: ${intent.goals.filter(g=>!g.held).length}/${intent.goals.length}</b> `+intent.goals.map(g=>`<span class="${g.held?'held':'done'}">${stEscape(g.kind==='field'?g.focus+' = '+g.value:'Наблюдаемое состояние')} · A ${stPercent(g.a)} · ${g.held?'удерживается':'подтверждено'}</span>`).join(' ')+
    (prediction?`<p>Прогноз до действия: <code>${stEscape(JSON.stringify(prediction))}</code></p>`:'')+
    (err?`<p>Ошибка прогноза: ${stEscape(err.transition||'ввод')} · ожидаемое ≠ наблюдаемому. Тормозящий след: ${stFormat(intent.error[err.transition])}.</p>`:'');
  }
  renderLanguage(m);renderImage(m);renderScreen();renderSelection();controls();st$('progress').style.width=stPercent(progress)+'%';
 }
 function renderLanguage(m){
  const r=m.language,mem=m.languageMemory;
  const chosen=st$('language-target').value;
  st$('language-target').innerHTML=st$('goal-target').innerHTML;
  if([...st$('language-target').options].some(o=>o.value===chosen))st$('language-target').value=chosen;
  st$('language-lessons').innerHTML=(mem?.lessons||[]).map(l=>`<p>${stEscape(l.phrase)} → ${stEscape(l.goal.kind==='field'?l.goal.focus+' = '+l.goal.value:'состояние')}</p>`).join('')||'Языковых пар пока нет.';
  st$('language-weights').innerHTML=(mem?.edges||[]).filter(e=>['readout','support','ground'].includes(e.kind)).map(e=>`<label>${stEscape(e.id+' · '+e.kind)} <input data-language-weight="${stEscape(e.id)}" type="number" min="0" max="1" step=".1" value="${e.weight}" ${editable()&&m.phase!=='language'?'':'disabled'}></label>`).join('');
  if(!r){st$('language-graph').innerHTML='';st$('language-graph').style.height='0px';st$('language-chars').innerHTML='';st$('language-decoded').textContent='';st$('language-progress').textContent='Пары обучают языковые связи; при новом запросе поле и значение определяются по ним.';return;}
  st$('language-progress').textContent=`Распознано ${r.index}/${r.chars.length} · ${r.status==='imagined'?'образ активирован':r.status==='reading'?'распространение по выученным связям':'остановлено: '+r.status}`;
  st$('language-chars').innerHTML=r.chars.map((ch,i)=>`<span class="${i<r.index?'done':i===r.index?'now':''}">${stEscape(ch===' '?'␣':ch)}</span>`).join('');
  const display=(proposal?.event?.kind.startsWith('language-')?proposal.event.candidates:null)||r.candidates;
  const rows=display.slice(0,3),height=rows.length*68;
  st$('language-graph').setAttribute('viewBox',`0 0 820 ${Math.max(1,height)}`);st$('language-graph').style.height=height+'px';
  st$('language-graph').innerHTML=rows.map((c,i)=>{const e=mem.edges.find(e=>e.id===c.edge),from=mem.nodes.find(n=>n.id===e.from),to=mem.nodes.find(n=>n.id===e.to);return `<g data-language-edge="${e.id}" transform="translate(0,${i*68})"><rect x="2" y="5" width="235" height="50" rx="8"/><text x="12" y="25">${stEscape((from?.label||e.from).slice(0,28))}</text><text x="12" y="44">${stEscape(e.from)}</text><path d="M 240 30 L 580 30 L 570 24 M 580 30 L 570 36"/><text x="250" y="20">${stEscape(e.kind)} · ${e.id} · вес ${e.weight}</text><text x="260" y="51">A ${stPercent(c.a)} / θ ${stPercent(c.threshold)}</text><rect x="585" y="5" width="230" height="50" rx="8"/><text x="595" y="25">${stEscape((to?.label||e.to).slice(0,24))}</text><text x="595" y="44">${stEscape(e.to)}</text></g>`;}).join('');
  st$('language-decoded').textContent=r.goal?`Из текста: ${r.goal.kind==='field'?r.goal.focus+' = '+r.goal.value:'образ состояния'}. Источник образа: языковая связь ${r.readout.edge}, A ${stPercent(r.readout.activation)}. Это не внешнее подтверждение.`:'Образ ещё не выбран; моторика выключена.';
 }
 function readLanguage(perform=false){
  if(!editable())return;
  selectedCase=12;caseOperation=null;interventionState={};
  if(operate({kind:'language-start',phrase:st$('language-phrase').value})){languageAutoAct=perform;running=true;st$('language-panel').open=true;controls();}
 }
 st$('language-read').onclick=()=>readLanguage(false);st$('language-act').onclick=()=>readLanguage(true);
 st$('language-phrase').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();readLanguage(false);}};st$('language-phrase').oninput=saveSoon;
 st$('language-demo').onclick=()=>{
  if(!editable())return;if(engine.operations.length&&!confirm('Загрузить языковые пары и опыт мира в этот режим?'))return;
  halt();invalidate();const p=prepareLanguage();engine=p.engine;history=null;selectedCase=12;caseOperation=null;goalDraft=[];interventionState={};graph.positions={};graph.selection=null;
  st$('language-phrase').value=p.phrase;st$('query').value='';st$('case-note').textContent='12: обучены три формулировки с 1700/2345. Новый текст с 1354 возбуждает образ, а не готовый моторный маршрут.';
  speed=100;st$('speed').value=100;render();graph.fit();readLanguage(false);
 };
 st$('language-test').onclick=()=>{try{const r=runLanguageExperiment();st$('suite-results').hidden=false;st$('suite-results').innerHTML=`<span data-language-result="${r.pass?'PASS':'FAIL'}"><b>12 · ${r.pass?'PASS':'FAIL'}</b> Фраза → образ: ${r.decoded}; без действий: ${r.dry}; результат: ${r.output}; память неизменна: ${r.unchanged}.</span>`;}catch(e){toast(e.message);}};
 st$('language-teach').onclick=()=>{
  if(!editable())return;const v=st$('language-target').value;let goal;
  if(v.startsWith('field:'))goal={kind:'field',focus:v.slice(6),value:st$('language-value').value};
  else {const n=engine.model.memory.nodes.find(n=>n.id===v.slice(6));if(!n)return toast('Выберите ранее наблюдённый образ');goal={kind:'state',features:stCopy(n.features)};}
  if(operate({kind:'language-teach',phrase:st$('language-train-phrase').value,goal}))toast('Пара сохранена. Для нового содержимого нужны два разных значения в этой формулировке.');
 };
 st$('language-weights').onchange=e=>{if(e.target.dataset.languageWeight)operate({kind:'language-weight',id:e.target.dataset.languageWeight,value:Number(e.target.value)});};
 function renderImage(m){
  const im=m.imagery;st$('image-panel').hidden=!im;if(!im)return;
  st$('image-mode').textContent=im.mode==='act'?'Действия разрешены':'Только образ · клики выключены';
  st$('image-panel').dataset.mode=im.mode;
  st$('image-summary').textContent=(m.status==='complete'?'Результат подтверждён извне; поддержка I снята. ':'')+`Готовность I: ${stPercent(im.ready)} · совпадение S: ${stPercent(im.match)} · рассогласование: ${stPercent(im.gap)}. Подтверждений от среды: ${im.confirmations.length}.`;
  const nodes=im.nodes.filter(n=>n.target||n.present||n.I>.01||n.S>.01);
  st$('image-nodes').innerHTML=nodes.slice(0,32).map(n=>`<div class="st-image-cell" data-repr="${stEscape(n.id)}" data-i="${n.I}" data-s="${n.S}" data-present="${n.present}"><b>${stEscape(n.label)}</b><div class="st-image-meter internal"><span style="width:${stPercent(n.I)}%"></span></div><div class="st-image-meter sensory"><span style="width:${stPercent(n.S)}%"></span></div><code>I ${stPercent(n.I)} / S ${stPercent(n.S)}</code><small>${n.target?'В образе':'Вне образа'} · ${n.present?'наблюдается':'не наблюдается'}</small></div>`).join('')+(nodes.length>32?`<small>Ещё ${nodes.length-32} вершин в JSON.</small>`:'');
 }
 st$('image-demo').onclick=()=>{
  if(!editable())return;if(engine.operations.length&&!confirm('Загрузить опыт 11 в этом режиме?'))return;
  halt();invalidate();const p=prepareImagery();engine=p.engine;history=null;selectedCase=11;caseOperation=p.operation;goalDraft=stCopy(p.operation.goals);interventionState={};graph.positions={};graph.selection=null;
  st$('query').value='Образ FIELD = 2345';st$('case-note').textContent='11: сначала только представьте 2345, не меняя мир. Затем «Достичь образа». Реальность подтверждается отдельно.';
  operate(p.operation);render();graph.fit();running=true;controls();
 };
 st$('image-build').onclick=()=>{if(!editable()||!goalDraft.length)return;selectedCase=11;caseOperation={kind:'imagine',goals:stCopy(goalDraft)};interventionState={};if(operate(caseOperation)){running=true;controls();}};
 st$('image-act').onclick=()=>{if(operate({kind:'image-control',command:'act'})){running=true;controls();}};
 st$('image-rest').onclick=()=>{if(operate({kind:'image-control',command:'rest'})){running=true;controls();}};
 st$('image-test').onclick=()=>{try{const r=runImageryExperiment();st$('suite-results').hidden=false;st$('suite-results').innerHTML=`<span data-imagery-result="${r.pass?'PASS':'FAIL'}"><b>11 · ${r.pass?'PASS':'FAIL'}</b> Образ без эффектов: ${r.dry}; затухание: ${r.faded}; общие вершины: ${r.sameVertices}; внешнее подтверждение: ${r.confirmed}; память неизменна: ${r.memoryUnchanged}.</span>`;}catch(e){toast(e.message);}};
 function loadCase(number){if(engine.operations.length&&!confirm('Заменить только этот эксперимент контрольным сценарием '+number+'? Другие режимы останутся без изменений.'))return;
  halt();invalidate();const r=prepareCapability(number);caseOperation=stCopy(r.operation);interventionState={};goalDraft=[];engine=r.engine;history=null;draft=null;recording=false;selectedCase=number;selectedIcon='';graph.positions={};graph.selection=null;st$('query').value=r.query;
  st$('case-note').textContent=number===3?'Показаны только A → Enter и X → рабочий стол. Цепочка X → A → Enter НЕ обучалась. Передайте «открой окно» из окна.':number===4?'Ранее наблюдался ввод 5432 в отдельном поле. Единственная демонстрация трат — 1700. Контрольный запрос 2345 не обучался.':'Контроль '+number+': '+caseNames[number-1]+'. Нажмите «Передать запрос». Анимация показывает реальные такты.';
  if(number>4)st$('case-note').textContent=r.note+' Нажмите «Передать запрос»: будет передана структурированная цель.';
  render();graph.fit();saveSoon();
 }
 for(let i=1;i<=10;i++)st$('case-'+i).onclick=()=>loadCase(i);
 function start(){if(!editable())return;interventionState={};const op=['goal','imagine'].includes(caseOperation?.kind)?stCopy(caseOperation):{kind:'start',query:st$('query').value};if(operate(op)&&!stStops.has(engine.model.status)){running=true;controls();}}
 st$('start').onclick=start;st$('query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();start();}};st$('query').oninput=saveSoon;
 function resume(){if(!live()||recording||draft)return;if(stStops.has(engine.model.status)){toast('Передайте запрос заново или измените условия стенда.');return;}running=true;last=0;controls();}
 st$('play').onclick=()=>running?halt():resume();
 st$('step').onclick=()=>{halt();if(!live()){setHistory(Math.min(engine.operations.length,history+1));return;}try{if(capabilityIntervention(selectedCase,engine,interventionState))invalidate();engine.commit(proposal||engine.preview());invalidate();render();saveSoon();}catch(e){toast(e.message);}};
 st$('deliver').onclick=()=>operate({kind:'deliver'});st$('reset').onclick=()=>{if(engine.model.pending&&!confirm('Отменить попытку с неподтверждённым действием? Это не подтверждает его выполнение.'))return;operate({kind:'reset'});};
 st$('speed').oninput=e=>{speed=Number(e.target.value);controls();saveSoon();};
 function frame(now){requestAnimationFrame(frame);if(!running||mode!=='states'){last=now;return;}const elapsed=last?Math.min(100,now-last):0;last=now;
  try{if(!proposal){capabilityIntervention(selectedCase,engine,interventionState);proposal=engine.preview();progress=0;render();}progress=Math.min(1,progress+elapsed/speed);graph.animate(proposal.event,progress);st$('progress').style.width=stPercent(progress)+'%';
   const a=engine.model.world.cursor,b=proposal.next.world.cursor;if(a.x!==b.x||a.y!==b.y)st$('cursor')?.setAttribute('transform',`translate(${a.x+(b.x-a.x)*progress},${a.y+(b.y-a.y)*progress})`);
   if(progress<1)return;const ended=proposal.event.kind;engine.commit(proposal);invalidate();if(ended==='language-image'&&languageAutoAct){engine.perform({kind:'image-control',command:'act'});languageAutoAct=false;}if(stStops.has(engine.model.status)||(engine.model.config.ackMode==='manual'&&engine.model.pending?.receipt)||(engine.model.imagery?.mode==='imagine'&&(engine.model.language?engine.model.tick-(engine.model.language.handoffTick||0)>=8:engine.model.tick%8===0)))halt();render();saveSoon();
  }catch(e){halt();invalidate();toast(e.message);render();}}
 function setHistory(i){halt();invalidate();history=i;historyEngine=engine.at(i);render();}
 st$('timeline').oninput=e=>setHistory(Number(e.target.value));st$('live').onclick=()=>{halt();invalidate();history=null;historyEngine=null;render();};
 st$('journal-toggle').onclick=()=>{st$('journal').hidden=!st$('journal').hidden;};st$('journal').onclick=e=>{const button=e.target.closest('[data-sthistory]');if(button)setHistory(Number(button.dataset.sthistory));};
 st$('view').onchange=e=>{graph.view=e.target.value;graph.positions={};render();graph.fit();saveSoon();};st$('fit').onclick=()=>graph.fit();
 st$('zoom-in').onclick=()=>{graph.camera.z=Math.min(3,graph.camera.z*1.2);graph.transform();};st$('zoom-out').onclick=()=>{graph.camera.z=Math.max(.08,graph.camera.z/1.2);graph.transform();};
 st$('selection-detail').onchange=e=>{if(e.target.id==='st-edge-weight')operate({kind:'weight',id:graph.selection.edge,value:Number(e.target.value)});};
 for(const [id,surface] of [['desk','desk'],['window','window'],['calc','calculator']])st$(id).onclick=()=>{if(!editable())return;const w=stCopy(engine.model.world);w.surface=surface;w.selected='';w.focus=w.surfaces[surface].field||'';w.output='';w.cursor={x:500,y:300};operate({kind:'world',world:w});};
 st$('move-icon').onclick=()=>{if(!selectedIcon)return toast('Выберите иконку');const o=visibleIcons(scene()).find(o=>o.id===selectedIcon);if(o)operate({kind:'perturb',id:o.id,x:o.x>500?120:850,y:o.y>350?110:440});};
 st$('hide-icon').onclick=()=>selectedIcon?operate({kind:'perturb',id:selectedIcon,hidden:true}):toast('Выберите иконку');
 st$('show-icons').onclick=()=>{const w=stCopy(engine.model.world);w.surfaces[w.surface].icons.forEach(o=>o.hidden=false);operate({kind:'world',world:w});};
 let iconDrag=null;st$('screen').onpointerdown=e=>{if(!editable()&&!recording)return;const n=e.target.closest('[data-stobj]');if(!n)return;selectedIcon=n.dataset.stobj;iconDrag={id:selectedIcon,x:e.clientX,y:e.clientY,moved:false};st$('screen').setPointerCapture(e.pointerId);};
 st$('screen').onpointermove=e=>{if(!iconDrag||recording)return;if(Math.abs(e.clientX-iconDrag.x)+Math.abs(e.clientY-iconDrag.y)>6)iconDrag.moved=true;};
 st$('screen').onpointerup=e=>{if(!iconDrag)return;const d=iconDrag;iconDrag=null;if(st$('screen').hasPointerCapture(e.pointerId))st$('screen').releasePointerCapture(e.pointerId);
  if(recording){trainActions(iconDemonstrationActions(draft.world,d.id));return;}
  if(d.moved){const svg=st$('screen'),pt=new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());operate({kind:'perturb',id:d.id,x:Math.max(50,Math.min(950,Math.round(pt.x))),y:Math.max(50,Math.min(550,Math.round(pt.y)))});return;}renderScreen();};
 st$('screen').onpointercancel=()=>iconDrag=null;
 st$('record').onclick=()=>{if(!st$('query').value.trim())return toast('Напишите обучаемую команду сверху');halt();invalidate();recording=true;draft={query:st$('query').value,initial:stCopy(engine.model.world),world:stCopy(engine.model.world),actions:[]};render();};
 function trainActions(actions){try{for(const action of actions){const receipt=applyWorld(draft.world,{id:'record:'+draft.actions.length,action});if(!receipt.ok)throw Error(receipt.reason);draft.actions.push(action);}renderScreen();controls();if(draft.world.focus)st$('keys').focus();saveSoon();}catch(e){toast(e.message);}}
 function enter(){if(recording&&draft?.world.selected)trainActions([{kind:'enter',object:draft.world.selected}]);}
 st$('enter').onclick=enter;st$('stop').onclick=()=>{recording=false;render();saveSoon();};
 st$('keys').oninput=e=>{if(!recording)return;const value=e.target.value;e.target.value='';trainActions(Array.from(value,value=>({kind:'key',value})));};
 st$('discard').onclick=()=>{recording=false;draft=null;render();saveSoon();};
 st$('learn').onclick=()=>{if(!draft||recording)return;try{const record=demonstration(draft.query,draft.initial,draft.actions);const saved=draft;draft=null;if(!operate({kind:'teach',record}))draft=saved;else {graph.positions={};graph.fit();}render();saveSoon();}catch(e){toast(e.message);}};
 st$('expose').onclick=()=>{try{const text=st$('prior-text').value;if(!text||Array.from(text).length>100)throw Error('Введите 1–100 ранее показанных символов');const w=defaultWorld();w.surface='calculator';w.focus='FIELD';operate({kind:'expose',record:demonstration('Прежний ввод символов',w,Array.from(text,value=>({kind:'key',value})))});}catch(e){toast(e.message);}};
 document.addEventListener('keydown',e=>{if(mode!=='states')return;if(e.key==='Escape'){if(recording){recording=false;render();saveSoon();}else halt();}if(e.key==='Enter'&&recording&&e.target!==st$('keys')){e.preventDefault();enter();}});
 st$('ack-mode').onchange=e=>operate({kind:'config',values:{ackMode:e.target.value}});st$('ack-delay').onchange=e=>operate({kind:'config',values:{ackDelay:Number(e.target.value)}});st$('timeout').onchange=e=>operate({kind:'config',values:{timeout:Number(e.target.value)}});
 const labels={plasticity:'Обучение опытом: 0 выкл., 1 вкл.',decay:'Остаток активации',weight:'Начальный вес',threshold:'Порог действия',planThreshold:'Порог выбора перехода',margin:'Минимальный отрыв',discount:'Передача цели',refractory:'Refractory, такты',inputDrive:'Текущий ввод',inhibition:'Торможение',historyGain:'Фон прошлого опыта'};
 st$('config').innerHTML=Object.entries(labels).map(([k,l])=>`<label>${l}<input type="number" data-stconfig="${k}" min="0" max="${k==='refractory'?10:1}" step="${['refractory','plasticity'].includes(k)?1:.05}" value="${STATE_DEFAULTS[k]}"></label>`).join('');
 st$('config').onchange=e=>{if(e.target.dataset.stconfig)operate({kind:'config',values:{[e.target.dataset.stconfig]:Number(e.target.value)}});};
 st$('suite-ten').onclick=()=>{try{const rows=Array.from({length:10},(_,i)=>runCapability(i+1));st$('suite-results').hidden=false;st$('suite-results').innerHTML=rows.map(r=>`<span data-capability="${r.number}" data-result="${r.pass?'PASS':'FAIL'}"><b>${r.pass?'PASS':'FAIL'} · ${r.number}</b> ${stEscape(caseNames[r.number-1])}${r.output?' → '+stEscape(r.output):''}</span>`).join('')+'<small>Изолированные копии. Это проверка алгоритма, не реальных окон Windows и не доказательство AGI.</small>';}catch(e){toast(e.message);}};
 st$('suite').onclick=()=>{try{const rows=[1,2,3,4].map(i=>runCase(i));st$('suite-results').hidden=false;st$('suite-results').innerHTML=rows.map(r=>`<span data-suite="${r.number}" data-result="${r.pass?'PASS':'FAIL'}"><b>${r.pass?'PASS':'FAIL'} · ${r.number}</b> ${stEscape(caseNames[r.number-1])}${r.output?' → '+stEscape(r.output):''}</span>`).join('')+'<small>Проверено на изолированных копиях; ваш текущий граф не изменён.</small>';}catch(e){toast(e.message);}};
 function restore(raw){const e=StateEngine.import(raw.schema==='kolos-state-ui/1'?raw.engine:raw);const v=Number(raw.speed)||500;needView(v>=100&&v<=3000,'Некорректный интервал');const positions={};for(const [id,p] of Object.entries(raw.positions||{}))if(p&&Number.isFinite(p.x)&&Number.isFinite(p.y)&&Math.abs(p.x)<100000&&Math.abs(p.y)<100000)positions[id]={x:p.x,y:p.y};
  let loadedDraft=null;if(raw.draft){const d=raw.draft;needView(Array.isArray(d.actions)&&d.actions.length<=100,'Некорректный черновик');if(d.actions.length)demonstration(d.query,d.initial,d.actions);loadedDraft={...stCopy(d),initial:validateWorld(d.initial),world:validateWorld(d.world)};}
  halt();invalidate();engine=e;history=null;recording=false;draft=loadedDraft;speed=v;st$('speed').value=v;st$('query').value=raw.query??e.model.query;st$('language-phrase').value=raw.languagePhrase??e.model.language?.phrase??'';selectedCase=raw.selectedCase||0;caseOperation=raw.caseOperation||null;interventionState=raw.interventionState||{};goalDraft=Array.isArray(raw.goalDraft)?raw.goalDraft:[];graph.positions=positions;graph.view=['states','actions','all'].includes(raw.view)?raw.view:'states';st$('view').value=graph.view;render();graph.fit();}
 function needView(c,msg){if(!c)throw Error(msg);}
 function download(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);}
 st$('export').onclick=()=>download(snapshot(),'kolos-states-experiment.json');st$('import').onclick=()=>st$('file').click();
 st$('file').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;halt();try{if(f.size>16*1024*1024)throw Error('Лимит файла 16 МБ');const data=JSON.parse(await f.text());if(engine.operations.length&&!confirm('Заменить память только этого режима?'))return;restore(data);saveSoon();}catch(err){toast('Импорт: '+err.message);}finally{e.target.value='';}};
 st$('clear').onclick=()=>{if(!confirm('Очистить только режим состояний?'))return;halt();invalidate();engine=new StateEngine();history=null;selectedCase=0;caseOperation=null;interventionState={};goalDraft=[];graph.positions={};graph.selection=null;st$('query').value='';render();saveSoon();};
 st$('goal-add').onclick=()=>{const value=st$('goal-target').value,m=engine.model;if(goalDraft.length>=8){toast('Не более 8 целей');return;}if(value.startsWith('state:')){const n=m.memory.nodes.find(n=>n.id===value.slice(6));if(n)goalDraft.push({kind:'state',features:stCopy(n.features)});}else if(value.startsWith('field:'))goalDraft.push({kind:'field',focus:value.slice(6),value:st$('goal-value').value});render();saveSoon();};
 st$('goal-clear').onclick=()=>{goalDraft=[];render();saveSoon();};
 st$('goal-start').onclick=()=>{if(!editable()||!goalDraft.length)return;selectedCase=0;caseOperation={kind:'goal',goals:stCopy(goalDraft)};interventionState={};st$('query').value='Явно заданные результаты';start();graph.fit();};
 st$('neurons').onclick=()=>{
  if(!ready||recording||draft){toast('Завершите демонстрацию перед просмотром');return;}
  if(!live()){toast('Вернитесь к текущему состоянию');return;}
  halt();invalidate();const dialog=document.createElement('dialog');dialog.className='nv-modal';const holder=document.createElement('div');dialog.append(holder);root.append(dialog);dialog.showModal();
  const scope=new NeuronScope(holder,{host:{model:()=>engine.model,event:()=>engine.events.at(-1),perform:op=>{if(!operate(op))throw Error('Операция не выполнена');return engine.events.at(-1);}},close:()=>{dialog.close();dialog.remove();}});
  dialog.addEventListener('cancel',e=>{e.preventDefault();scope.destroy();dialog.close();dialog.remove();});
 };
 st$('help').onclick=()=>st$('help-dialog').showModal();st$('help-close').onclick=()=>st$('help-dialog').close();
 document.addEventListener('kolos:state:snapshot',e=>{if(typeof e.detail?.reply==='function')e.detail.reply(stCopy(snapshot()));});
 document.addEventListener('kolos:mode',e=>{if(e.detail.mode!==mode&&(recording||draft)){e.preventDefault();toast('Сохраните или сбросьте демонстрацию');return;}halt();mode=e.detail.mode;if(mode==='states')requestAnimationFrame(()=>{render();graph.fit();});saveSoon();});
 async function initialize(){try{
  if(navigator.locks){const gate=await new Promise(res=>{navigator.locks.request('kolos-state-autosave',{ifAvailable:true},async lock=>{storageOwner=!!lock;res();if(lock)await new Promise(()=>{});}).catch(()=>res());});}
  db=await new Promise((res,rej)=>{const req=indexedDB.open('KolosStateLab',1);req.onupgradeneeded=()=>req.result.createObjectStore('state');req.onsuccess=()=>res(req.result);req.onerror=()=>rej(req.error);});
  const raw=await new Promise((res,rej)=>{const req=db.transaction('state').objectStore('state').get('current');req.onsuccess=()=>res(req.result);req.onerror=()=>rej(req.error);});if(raw)restore(raw);
 }catch{st$('storage').textContent='Автосохранение недоступно — экспортируйте JSON';}ready=true;render();requestAnimationFrame(()=>graph.fit());}
 render();requestAnimationFrame(frame);void initialize();
}
