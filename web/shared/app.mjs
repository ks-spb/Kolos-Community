import {SharedSession,SHARED_NAMES,sharedSignature,sharedWorld,sharedStamp,runSharedTransfer} from './suite.mjs';
import {neuronFrame} from '../neurons/snapshot.mjs';
import {NeuronView} from '../neurons/view.mjs';
const shEsc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shNotes=[
 'Знакомая команда → A → Enter. Остальные знания не убираются из памяти.',
 'То же окно → X → рабочий стол. X определяется наблюдаемым состоянием.',
 'A скрыта. Исходная цель сохраняется, изученный X возвращает к A.',
 'Команда обучена с 1700. Вход 2345 новый, символы были показаны отдельно.',
 'Два результата: открытое окно, затем FIELD=3521. Не готовая цепочка кликов.',
 'Видна архивная панель. Прямой переход слабый; рядом в памяти есть сильный переход новой панели.',
 'После открытия поля среда показывает мешающее окно. Граф и цель не меняются.',
 'Новый маршрут из трёх независимо показанных переходов. В памяти остаются и все прочие задачи.',
 'Задано FIELD=2345, не команда и не список действий. Исходно поле скрыто.',
 'Видна новая панель. Прямой переход даёт неожиданный исход; ошибку тормозит временный след.',
 '8 тактов образа без действий → 5 тактов затухания → достижение → подтверждение S.',
 'Новая фраза с 1354 → выученные языковые связи → образ I → действия → внешнее S.'
];
const shSave=(name,value,type='application/json')=>{const u=URL.createObjectURL(new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
export class SharedLab{
 constructor(root){
  this.root=root;this.speed=800;this.playing=false;this.busy=false;this.current=11;this.frames=[];this.records={};this.cursor=0;this.queue=[];this.report=[];this.runToken=0;this.previousTime=0;
  root.innerHTML=`<header class="sh-top"><div><div class="sh-eyebrow">KOLOS / ОБЩАЯ ПАМЯТЬ</div><h1>Один граф. Двенадцать опытов.</h1><p>Все знания доступны одновременно. Меняются наблюдение и текущая цель — не база.</p></div><div class="sh-score"><strong data-sh="score">0 / 12</strong><span>подтверждено на этой базе</span></div></header>
  <div class="sh-memory"><strong>● Память не переключается</strong><span data-sh="stats"></span><code data-sh="hash"></code><small data-sh="saved"></small></div>
  <section class="sh-tests" data-sh="tests">${SHARED_NAMES.map((s,i)=>`<button data-case="${i+1}"><span>${String(i+1).padStart(2,'0')}</span>${shEsc(s)}<b>—</b></button>`).join('')}</section>
  <div class="sh-controls"><button class="sh-primary" data-sh="watch">▶ Смотреть тест</button><button data-sh="step">Один такт →</button><button data-sh="all-watch">Смотреть 1–12</button><button data-sh="check">Проверить все</button><button data-sh="transfer">Сквозной опыт</button><button data-sh="abort">Отменить попытку</button><label>Интервал <input type="range" min="50" max="2000" step="50" value="800" data-sh="speed" aria-label="Интервал тактов"><b data-sh="speed-label">0,8 с</b></label></div>
  <div class="sh-stage"><span data-sh="stage"></span><code data-sh="tick"></code></div>
  <div data-sh="graph"></div>
  <div class="nv-bottom"><button data-sh="back">←</button><input type="range" min="0" max="0" value="0" data-sh="timeline" aria-label="История текущего опыта"><span data-sh="position"></span><button data-sh="latest">К текущему</button><small>История только для чтения</small></div>
  <section class="sh-results"><h2>Результаты — одна база, неизменные веса</h2><p data-sh="status" role="status" aria-live="polite">«Проверить все» выполнит 1–12 последовательно на текущей общей памяти. Результаты не заготовлены.</p><div class="sh-table-wrap"><table><thead><tr><th>Тест</th><th>Результат</th><th>Подтверждённые клики</th><th>Поле</th><th>Тактов</th><th>База до / после</th><th>Сигналы</th></tr></thead><tbody data-sh="results"></tbody></table></div>
  <div class="sh-file-controls"><button data-sh="export">Сохранить общую базу</button><button data-sh="import">Открыть базу</button><button data-sh="report">Сохранить отчёт</button><button data-sh="fresh">Заново создать учебную базу</button><input data-sh="file" type="file" accept="application/json,.json" hidden></div></section>
  <details class="sh-help"><summary>Что объединено, что изменено и что этот стенд не доказывает</summary>
  <p>18 независимых показов действий, один прежний ввод 5432 и шесть языковых пар создают одну память до первого теста. Общие состояния, символы, моторные и языковые связи переиспользуются. Сценарий не передаёт ядру свой номер или ожидаемые клики.</p>
  <p>Архивная и новая панели — два наблюдаемых контекста: на одной видна ARCHIVE, на другой CURRENT. Это нужно, чтобы слабая и сильная связи FAST не противоречили друг другу. Их веса не переключаются при смене теста. NEXT, целевой результат, HOME и рабочий стол общие.</p>
  <p>При буквальном объединении прежнее усреднение размывало сигнал среди дополнительных переходов. Теперь альтернативные входы состояния конкурируют (максимальный взвешенный сигнал с утечкой), а конечные действия по-прежнему выбираются по порогу, допустимости и разрыву активаций. Порог не меняется для отдельного теста. Условия и математика одинаковы в JavaScript и Python.</p>
  <p>«Сквозной опыт» соединяет ранее раздельные группы знаний: уровни → HOME → общий рабочий стол → CALC → 4512, без перезапуска среды внутри решения. «Проверить все» проверяет последовательные задачи, не двенадцать одновременных независимых намерений.</p>
  <p>Это виртуальная среда и инженерная нейроноподобная сеть, не доказанная модель человеческого мозга. База Glaz и реальные файлы ПК не меняются. Импорт сохраняет знания, но не возобновляет старые действия. I не подменяет S. Линии порядка без фактической передачи остаются пунктирными. Переключатели слоёв меняют только рисунок.</p></details>`;
  this.$=id=>root.querySelector(`[data-sh="${id}"]`);
  this.view=new NeuronView(this.$('graph'),{maxNodes:1000,compactOverview:true});
  let restored=false;try{const raw=localStorage.getItem('kolos-shared-memory-v1');this.session=raw?new SharedSession({database:JSON.parse(raw)}):new SharedSession();restored=!!raw;}catch(err){this.session=new SharedSession();this.$('status').textContent='Сохранённая база не загружена: '+err.message;}
  this.bind();this.persist(restored);this.choose(11);
  const loop=ts=>{if(this.closed)return;if(this.playing&&!this.busy){if(ts-this.previousTime>=this.speed){this.previousTime=ts;this.tick();}this.view.animate(Math.min(1,(ts-this.previousTime)/this.speed));}this.raf=requestAnimationFrame(loop);};this.raf=requestAnimationFrame(loop);
 }
 bind(){
  this.session.onFrame=(m,ev,prior)=>{const f=neuronFrame(m,ev,prior);f.sharedDatabase=this.session.stamp;
   // Read-only display names; none of these labels are fed to inference.
   for(const n of f.nodes.filter(n=>n.kind==='state'&&n.features)){
    const surfaces=Object.values(m.world.surfaces);const shown=n.features.filter(s=>s.startsWith('visible:')).map(s=>s.slice(8)).sort().join('|');
    const s=surfaces.find(s=>s.icons.filter(i=>!i.hidden).map(i=>i.id).sort().join('|')===shown);
    if(s)n.label=s.label+(n.features.includes('selected:A')?' · выбрана A':'');
   }
   this.frames.push(f);if(this.frames.length>600)this.frames.shift();this.cursor=this.frames.length-1;
   if(!this.busy)this.show();
  };
  this.$('tests').onclick=e=>{const b=e.target.closest('[data-case]');if(b&&!this.busy){if(this.session.engine.model.pending&&!confirm('Отменить незавершённую виртуальную попытку? Память сохранится.'))return;this.session.abort();this.choose(Number(b.dataset.case));}};
  this.$('watch').onclick=()=>{if(this.busy)return;if(this.playing){this.pause();return;}if(this.readonly||this.cursor<this.frames.length-1)this.historyPlayback=true;else if(this.session.active?.finished)this.choose(this.current);this.playing=true;this.previousTime=performance.now()-this.speed;this.$('watch').textContent='Ⅱ Пауза';};
  this.$('step').onclick=()=>{this.pause();if(this.cursor<this.frames.length-1){this.cursor++;this.show();return;}if(!this.readonly)this.tick();};
  this.$('all-watch').onclick=()=>{if(this.busy)return;this.session.abort();this.queue=Array.from({length:11},(_,i)=>i+2);this.choose(1,false);this.playing=true;this.$('watch').textContent='Ⅱ Пауза';};
  this.$('check').onclick=()=>this.checkAll();this.$('transfer').onclick=()=>this.transfer();
  this.$('abort').onclick=()=>{this.pause();this.queue=[];this.runToken++;if(!this.busy)this.session.abort();this.$('status').textContent='Попытка отменена. Общая память сохранена.';};
  this.$('speed').oninput=e=>{this.speed=Number(e.target.value);this.$('speed-label').textContent=(this.speed/1000).toFixed(2).replace('.',',')+' с';};
  this.$('timeline').oninput=e=>{this.pause();this.queue=[];this.cursor=Number(e.target.value);this.show();};
  this.$('back').onclick=()=>{this.pause();this.queue=[];this.cursor=Math.max(0,this.cursor-1);this.show();};
  this.$('latest').onclick=()=>{if(this.readonly){this.readonly=false;this.frames=this.liveFrames||this.frames;}this.cursor=this.frames.length-1;this.show();};
  this.$('results').onclick=e=>{const b=e.target.closest('[data-record]');if(!b||this.busy)return;this.pause();const n=Number(b.dataset.record);this.liveFrames=this.readonly?this.liveFrames:this.frames;this.frames=this.records[n]||[];this.cursor=0;this.readonly=true;this.show();};
  this.$('export').onclick=()=>shSave('kolos-shared-memory.json',this.session.export());
  this.$('report').onclick=()=>shSave('kolos-shared-report.json',{schema:'kolos-shared-ui-report/1',database:this.session.stamp,results:this.report,transfer:this.transferResult||null});
  this.$('import').onclick=()=>this.$('file').click();this.$('file').onchange=async e=>{try{const file=e.target.files?.[0];if(!file)return;if(file.size>4e6)throw Error('База не больше 4 МБ');const s=new SharedSession({database:JSON.parse(await file.text())});this.replace(s);}catch(err){this.error(err);}e.target.value='';};
  this.$('fresh').onclick=()=>{if(confirm('Создать учебную базу заново? Перед этим можно сохранить текущую.'))this.replace(new SharedSession());};
 }
 persist(restored=false){const m=this.session.engine.model;this.$('stats').textContent=`${m.memory.nodes.length} вершин опыта + ${m.languageMemory?.nodes.length||0} языковых · ${m.memory.edges.length+(m.languageMemory?.edges.length||0)} связей · ${m.lessons.length} показов`;
  this.$('hash').textContent='БАЗА '+this.session.stamp;
  try{localStorage.setItem('kolos-shared-memory-v1',JSON.stringify(this.session.export()));this.$('saved').textContent=restored?'Общая база восстановлена; новая проверка ещё не выполнена':'Общая база сохранена в браузере';}catch{this.$('saved').textContent='Сохранение в браузере недоступно; используйте экспорт';}
 }
 replace(session){if(this.busy)return;this.pause();this.runToken++;this.session=session;this.report=[];this.records={};this.frames=[];this.queue=[];this.bind();this.persist();this.choose(11);this.renderResults();}
 pause(){this.playing=false;this.historyPlayback=false;this.$('watch').textContent='▶ Смотреть тест';}
 choose(n,clearQueue=true){this.pause();if(clearQueue)this.queue=[];this.readonly=false;this.liveFrames=null;this.current=n;this.frames=[];this.cursor=0;this.view.first=true;this.session.begin(n);this.show();
  for(const b of this.$('tests').querySelectorAll('[data-case]'))b.classList.toggle('selected',Number(b.dataset.case)===n);
 }
 tick(){try{
  if(this.historyPlayback){if(this.cursor<this.frames.length-1){this.cursor++;this.show();}else this.pause();return;}
  if(this.cursor<this.frames.length-1){this.cursor++;this.show();return;}
  if(this.readonly){this.pause();return;}
  if(!this.session.active||this.session.active.finished){this.pause();return;}
  this.session.step();
  if(this.session.active.finished){const n=this.current;this.recordResult(n);if(this.queue.length){const next=this.queue.shift();this.choose(next,false);this.playing=true;}else this.pause();}
 }catch(err){this.error(err);}}
 recordResult(n){const r=this.session.active.result;if(!r)return;this.report=this.report.filter(r=>r.number!==n);this.report.push(r);this.records[n]=this.frames.slice();this.renderResults();}
 renderResults(){const passed=this.report.filter(r=>r.pass).length;this.$('score').textContent=passed+' / 12';
  for(const b of this.$('tests').querySelectorAll('[data-case]')){const r=this.report.find(r=>r.number===Number(b.dataset.case));b.querySelector('b').textContent=r?r.pass?'✓':'×':'—';b.classList.toggle('pass',!!r?.pass);b.classList.toggle('fail',r&&!r.pass);}
  this.$('results').innerHTML=this.report.slice().sort((a,b)=>a.number-b.number).map(r=>`<tr><td>${String(r.number).padStart(2,'0')} ${shEsc(r.name)}</td><td class="${r.pass?'sh-pass':'sh-fail'}">${r.pass?'ПРОЙДЕН':'НЕ ПРОЙДЕН'}</td><td>${shEsc(r.clicks.join(' → '))}</td><td>${shEsc(r.output||'—')}</td><td>${r.ticks}</td><td><code>${shEsc(r.memoryBefore)} / ${shEsc(r.memoryAfter)}</code></td><td><button data-record="${r.number}">Запись</button></td></tr>`).join('');
 }
 show(){const f=this.frames[this.cursor];if(!f)return;this.view.setFrame(f);const past=this.readonly||this.cursor!==this.frames.length-1;
  this.$('tick').textContent=`Такт ${f.tick} · ${f.event.kind}`;this.$('stage').textContent=past?'Запись сигналов — без повторного исполнения':`${String(this.current).padStart(2,'0')} · ${shNotes[this.current-1]}`;
  this.$('timeline').max=Math.max(0,this.frames.length-1);this.$('timeline').value=this.cursor;this.$('position').textContent=`${this.cursor+1} / ${this.frames.length}`;
 }
 error(err){this.pause();this.$('status').textContent='Остановка: '+err.message;this.$('status').classList.add('sh-fail');}
 async checkAll(){if(this.busy)return;this.pause();this.queue=[];this.session.abort();this.busy=true;const token=++this.runToken;
  this.$('status').classList.remove('sh-fail');this.setBusy(true);
  try{for(let n=1;n<=12;n++){
   if(token!==this.runToken)break;
   this.choose(n);this.$('status').textContent=`Проверка ${n}/12 на базе ${this.session.stamp}. Новая база не создаётся.`;
   for(let i=0;i<2500&&!this.session.active.finished;i++){if(token!==this.runToken)break;this.session.step();if(i%18===0)await new Promise(resolve=>setTimeout(resolve,0));}
   if(!this.session.active.finished)break;this.recordResult(n);this.show();await new Promise(resolve=>setTimeout(resolve,0));
  }
  this.session.verifyMemory();this.$('status').textContent=`${this.report.filter(r=>r.pass).length}/12 пройдены. Одна и та же база ${this.session.stamp}; прежние знания и веса не менялись. «Запись» открывает сигналы выбранного опыта.`;
  }catch(err){this.error(err);}finally{if(token!==this.runToken){this.session.abort();this.$('status').textContent='Проверка прервана. Общая память не изменена.';}this.busy=false;this.setBusy(false);this.show();}
 }
 setBusy(value){for(const id of ['watch','step','all-watch','check','transfer','import','fresh'])this.$(id).disabled=value;}
 async transfer(){if(this.busy)return;this.pause();this.session.abort();this.busy=true;this.setBusy(true);this.frames=[];this.readonly=false;
  try{await new Promise(resolve=>setTimeout(resolve,0));this.transferResult=runSharedTransfer(this.session);this.$('status').textContent=(this.transferResult.pass?'Сквозной опыт пройден: ':'Сквозной опыт не пройден: ')+this.transferResult.clicks.join(' → ')+' → '+this.transferResult.output+'. База '+this.session.stamp+' не менялась.';this.cursor=this.frames.length-1;this.show();this.$('stage').textContent='Сквозной опыт: две цели, один запуск, без перестановки среды внутри решения.';}catch(err){this.error(err);}finally{this.busy=false;this.setBusy(false);}
 }
 destroy(){this.closed=true;this.runToken++;this.pause();cancelAnimationFrame(this.raf);this.view.destroy();}
}
if(typeof document!=='undefined'&&document.getElementById('shared-app'))globalThis.kolosSharedLab=new SharedLab(document.getElementById('shared-app'));
