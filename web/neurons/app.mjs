import {neuronFrame,NEURON_SCHEMA} from './snapshot.mjs';
import {NeuronView} from './view.mjs';
import {prepareImagery} from '../states/imagery-cases.mjs';
import {prepareLanguage} from '../states/language-cases.mjs';
const nvClone=x=>structuredClone(x);
const nvStop=new Set(['idle','trained','complete','failed','blocked','unknown','ambiguous','timeout','limit']);
export class NeuronScope {
 constructor(root,{host=null,live=false,close=null}={}){
  this.root=root;root.classList.add('nv-root');this.host=host;this.live=live;this.frames=[];this.cursor=0;this.playing=false;this.speed=1000;this.frameTime=0;this.previewCount=0;this.lastLive=0;this.follow=true;this.polling=false;this.closed=false;
  root.innerHTML=`<header class="nv-top"><div><div class="nv-brand">KOLOS <em>НЕЙРОННЫЙ ПРОСМОТР</em></div><div class="nv-sub">Вершины существующего алгоритма · не биологическая модель мозга</div></div><span class="nv-source" data-scope="source">Движок States · браузер</span>${close?'<button data-scope="close">Закрыть</button>':''}</header><div class="nv-controls"><select data-scope="demo" aria-label="Эксперимент"><option value="11">11 · Образ → действие</option><option value="12">12 · Язык → образ</option></select><input class="nv-query" data-scope="value" value="2345" aria-label="Желаемый текст"><button data-scope="reset">Новый опыт</button><i class="nv-control-separator"></i><button class="nv-primary" data-scope="play">▶ Пуск</button><button data-scope="step">Один такт →</button><button data-scope="rest">Снять поддержку</button><button data-scope="act">Достичь образа</button><label>Интервал <input data-scope="speed" type="range" min="100" max="3000" step="100" value="1000" aria-label="Интервал тактов"><b data-scope="speed-label">1,0 с</b></label></div><div class="nv-stage"><strong data-scope="stage">Сначала представление, затем действие</strong><span data-scope="tick">Такт 0</span></div><div data-scope="view"></div><div class="nv-bottom"><button data-scope="back">←</button><input data-scope="timeline" type="range" min="0" max="0" value="0" aria-label="История просмотра"><span data-scope="position">0 / 0</span><button data-scope="latest">К последнему</button><button data-scope="export">Сохранить просмотр</button><button data-scope="import">Открыть запись</button><input data-scope="file" type="file" accept=".json,application/json" hidden></div><details class="nv-help"><summary>Что показывают круги и движущиеся точки</summary><p>Круг — вершина графа, яркость — уровень её сигнала. I — внутренний образ, S — принятое наблюдение, A — хранимая активация, C — сигнал кандидата при выборе. Звезда отмечает выбранного кандидата; высокий сигнал сам по себе не доказывает действие. R — число тактов запрета повторного срабатывания.</p><p>Частицы движутся по зарегистрированным передачам и явно обозначенным членам уравнений. Это показ уже рассчитанного такта, не новая физика импульсов. Пунктир «порядок» — структурная связь образа: ядро НЕ передаёт через неё I/S. Нажмите стрелку, чтобы увидеть происхождение числа. История и открытые JSON-записи никогда не повторяют клики.</p><p>В режиме Glaz просмотр только читает данные. Пауза просмотра не останавливает Kolos; настоящая пауза и F9 находятся в Glaz. На одном мониторе окно браузера может закрывать наблюдаемые иконки — используйте второй монитор или снимайте запись для просмотра после опыта.</p></details>`;
  this.$=id=>root.querySelector(`[data-scope="${id}"]`);this.view=new NeuronView(this.$('view'));
  if(close)this.$('close').onclick=()=>{this.destroy();close();};
  this.$('demo').onchange=()=>{this.$('value').value=this.$('demo').value==='12'?'я хочу увидеть 1354 в поле':'2345';};
  this.$('reset').onclick=()=>this.reset();this.$('play').onclick=()=>this.toggle();this.$('step').onclick=()=>{this.stop();this.follow=false;this.step();};
  this.$('rest').onclick=()=>this.control('rest');this.$('act').onclick=()=>this.control('act');
  this.$('speed').oninput=e=>{this.speed=Number(e.target.value);this.$('speed-label').textContent=(this.speed/1000).toFixed(1).replace('.',',')+' с';};
  this.$('timeline').oninput=e=>{this.stop();this.follow=false;this.cursor=Number(e.target.value);this.show();};
  this.$('back').onclick=()=>{this.stop();this.follow=false;this.cursor=Math.max(0,this.cursor-1);this.show();};
  this.$('latest').onclick=()=>{this.follow=true;this.cursor=Math.max(0,this.frames.length-1);this.show();};
  this.$('export').onclick=()=>this.export();this.$('import').onclick=()=>this.$('file').click();
  this.$('file').onchange=async e=>{const file=e.target.files?.[0];try{if(!file)return;if(file.size>24e6)throw Error('Запись не больше 24 МБ');this.openRecord(JSON.parse(await file.text()));}catch(err){this.error(err);}e.target.value='';};
  if(live){this.token=location.hash.slice(1);this.modeLabel('Glaz · только чтение');for(const id of ['demo','value','reset','rest','act','import'])this.$(id).hidden=true;this.$('step').textContent='Следующий снимок →';this.$('stage').textContent='Ожидаются снимки Glaz. Управление алгоритмом — в Glaz.';this.$('play').textContent='Ⅱ Пауза просмотра';this.$('speed').parentElement.hidden=true;this.poll();}
  else if(host){for(const id of ['demo','value','reset'])this.$(id).hidden=true;this.record(host.model(),host.event()||{},null);}
  else this.reset();
  this.loop=ts=>{if(this.closed)return;if(this.playing){if(ts-this.frameTime>=this.speed){this.frameTime=ts;this.step();}this.view.animate(Math.min(1,(ts-this.frameTime)/this.speed));}else if(this.live&&this.follow&&this.liveTime){this.view.animate(Math.min(1,(ts-this.liveTime)/700));}this.raf=requestAnimationFrame(this.loop);};this.raf=requestAnimationFrame(this.loop);
 }
 modeLabel(text){this.$('source').textContent=text;}
 model(){return this.host?this.host.model():this.engine?.model;}
 stop(){this.playing=false;this.$('play').textContent=this.live?'▶ Просмотр':'▶ Пуск';}
 toggle(){if(this.live){this.follow=!this.follow;if(this.follow){this.cursor=Math.max(0,this.frames.length-1);this.show();}this.$('play').textContent=this.follow?'Ⅱ Пауза просмотра':'▶ К потоку';return;}if(this.playing){this.stop();return;}this.playing=true;this.frameTime=performance.now()-this.speed;this.$('play').textContent=this.live?'Ⅱ Пауза просмотра':'Ⅱ Пауза';}
 error(e){this.stop();this.$('stage').textContent=e.message||String(e);this.$('stage').classList.add('nv-error');}
 reset(){this.stop();this.readonly=false;this.$('stage').classList.remove('nv-error');try{
   const isLanguage=this.$('demo').value==='12',p=isLanguage?prepareLanguage(this.$('value').value):prepareImagery(this.$('value').value);
   this.engine=p.engine;this.engine.perform(p.operation);this.frames=[];this.cursor=0;this.previewCount=0;this.previous=null;this.view.positions={};this.view.first=true;
   this.record(this.engine.model,this.engine.events.at(-1),null);this.modeLabel('Движок States · браузер');
  }catch(e){this.error(e);}}
 perform(op){const prior=nvClone(this.model());let event;
  if(this.host)event=this.host.perform(op);else event=this.engine.perform(op);
  this.record(this.model(),event||{},prior);
 }
 record(m,event,previous){const frame=neuronFrame(m,event,previous);this.frames.push(frame);if(this.frames.length>500)this.frames.shift();this.cursor=this.frames.length-1;this.show();}
 control(command){if(this.readonly||this.live)return;this.stop();if(this.cursor!==this.frames.length-1){this.error(Error('Вернитесь к последнему снимку: история не исполняет действия.'));return;}
  try{this.previewCount=0;this.perform({kind:'image-control',command});this.toggle();}catch(e){this.error(e);}}
 step(){try{
  if(this.cursor<this.frames.length-1){this.cursor++;this.show();return;}
  if(this.live||this.readonly){this.stop();return;}
  if(nvStop.has(this.model()?.status)){this.stop();return;}
  this.perform({kind:'tick'});
  const m=this.model();if(m.imagery?.mode==='imagine'){this.previewCount++;if(this.previewCount>=8)this.stop();}
  if(nvStop.has(m.status))this.stop();
 }catch(e){this.error(e);}}
 show(){const f=this.frames[this.cursor];if(!f)return;this.view.setFrame(f);
  this.$('tick').textContent=`Такт ${f.tick} · ${f.event.kind||'снимок'}`;this.$('timeline').max=Math.max(0,this.frames.length-1);this.$('timeline').value=this.cursor;this.$('position').textContent=`${this.cursor+1} / ${this.frames.length}`;
  const history=this.cursor!==this.frames.length-1;
  this.$('stage').classList.remove('nv-error');this.$('stage').textContent=history?'История — просмотр без исполнения':this.live?'Glaz: только чтение. Пауза здесь НЕ останавливает движок.':this.readonly?'Запись: только просмотр. Действия не воспроизводятся.':f.status==='complete'?'Цель подтверждена внешним наблюдением':f.phase==='language'?'Фраза возбуждает выученные языковые связи':f.mode==='imagine'?'Представление без действий · после 8 тактов автопауза':f.mode==='act'?'Достижение образа · каждый эффект ждёт подтверждения':'Просмотр текущего алгоритма';
  for(const id of ['rest','act'])this.$(id).disabled=this.live||this.readonly||history||!this.model()?.imagery||!!this.model()?.pending;
 }
 export(){const blob=new Blob([JSON.stringify({schema:'kolos-neuron-recording/1',frames:this.frames})],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='kolos-neurons-recording.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
 openRecord(record){if(this.host)throw Error('Откройте запись в отдельном просмотрщике, не поверх работающей лаборатории.');
  if(record?.schema!=='kolos-neuron-recording/1'||!Array.isArray(record.frames)||!record.frames.length||record.frames.length>500)throw Error('Неверный формат записи');
  for(const f of record.frames){if(f.schema!==NEURON_SCHEMA||!Array.isArray(f.nodes)||!Array.isArray(f.edges)||f.nodes.length>20000||f.edges.length>50000||!f.nodes.every(n=>typeof n.id==='string'&&typeof n.label==='string')||!f.edges.every(e=>typeof e.id==='string'&&typeof e.from==='string'&&typeof e.to==='string'))throw Error('Повреждён снимок графа');}
  this.stop();this.readonly=true;this.frames=nvClone(record.frames);this.cursor=0;this.view.positions={};this.view.first=true;this.modeLabel('JSON · только чтение');this.show();
 }
 async poll(){if(this.closed||!this.live)return;try{
   const reply=await fetch(`/api/frames?after=${this.lastLive}`,{headers:{'X-Kolos-View':this.token},cache:'no-store'});
   if(!reply.ok)throw Error(reply.status===403?'Нет доступа к сеансу Glaz. Откройте просмотр кнопкой в Glaz.':'Не удалось прочитать снимки');
   const data=await reply.json();if(data.gap)this.lastRaw=null;for(const raw of data.frames){this.lastLive=raw.seq;const contiguous=this.lastRaw&&raw.model.tick>=this.lastRaw.tick&&raw.model.attempt===this.lastRaw.attempt&&raw.model.revision===this.lastRaw.revision+1;const f=neuronFrame(raw.model,raw.event,contiguous?this.lastRaw:null);this.lastRaw=raw.model;this.frames.push(f);if(this.frames.length>500){this.frames.shift();this.cursor=Math.max(0,this.cursor-1);}}
   if(this.follow&&data.frames.length){this.cursor=this.frames.length-1;this.show();this.liveTime=performance.now();}
   if(data.gap)this.$('stage').textContent='Часть старых снимков уже удалена из буфера. Непрерывность не гарантируется.';
   if(!data.frames.length&&data.closed)this.$('stage').textContent='Glaz завершён; сохранены последние снимки.';
  }catch(e){this.$('stage').textContent='Связь с Glaz: '+e.message;}
  if(!this.closed)this.pollTimer=setTimeout(()=>this.poll(),350);
 }
 destroy(){this.closed=true;this.stop();clearTimeout(this.pollTimer);cancelAnimationFrame(this.raf);this.view.destroy();}
}
// Importing the viewer in the main laboratory must not start a second engine.
if(typeof document!=='undefined'&&document.getElementById('neuron-app')){
 window.kolosNeuronScope=new NeuronScope(document.getElementById('neuron-app'),{live:new URLSearchParams(location.search).get('live')==='1'});
}
