import {ResidualEngine,RESIDUAL_DEFAULTS} from './core.mjs';
import {observeResidualDemonstration,residualUnder} from './environment.mjs';
import {residualPrevious} from './learning.mjs';
import {residualDemo,runResidualChecks} from './demo.mjs';

const rx=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rp=v=>(100*(v||0)).toFixed(0);
const rq=id=>document.getElementById('rg-'+id);
const RSTOP=new Set(['complete','unknown','ambiguous','blocked','timeout','failed','limit','below','idle','trained']);
const rmarkup=`
<header class="rg-heading"><div><span class="rg-eyebrow">KOLOS / EXPERIMENT 03</span><h1>Снятие торможения</h1><p>Текущий вход → максимум готовности → действие → подтверждение → погашение</p></div>
<div class="rg-actions"><span id="rg-save-status">Локальная память</span><button id="rg-demo">Два примера: 1700 и 2345</button><button id="rg-export">Экспорт</button><button id="rg-import">Импорт</button><button id="rg-help">?</button></div></header>
<section class="rg-query-row"><input id="rg-query" aria-label="Новый полный запрос" placeholder="Введите третий запрос, например: добавь траты 1354" maxlength="200"><button id="rg-start" class="rg-primary">Передать запрос</button><button id="rg-checks">Проверить гипотезу</button></section>
<div id="rg-message" role="status"></div>
<section class="rg-residue"><div class="rg-row"><b>НЕОТРАБОТАННЫЙ ЗАПРОС</b><span id="rg-count"></span><span class="rg-frozen">Веса фиксированы при выполнении</span></div><div id="rg-tokens"></div></section>
<main class="rg-workspace"><section class="rg-canvas"><div class="rg-toolbar"><label>Граф <select id="rg-view"><option value="input">Вхождения текущего запроса</option><option value="memory">Выученные связи и подтверждения</option></select></label><span id="rg-graph-count"></span><button id="rg-minus" aria-label="Отдалить">−</button><button id="rg-plus" aria-label="Приблизить">+</button><button id="rg-fit">Уместить</button></div>
<div class="rg-stage"><svg id="rg-graph" role="group" aria-label="Граф удерживаемых следов и торможения"></svg><div id="rg-empty"><h2>Первый шаг — два показа.</h2><p>Нажмите «Два примера: 1700 и 2345».<br>Затем передайте новый полный запрос с 1354.</p><p>Граница слов и вводимых символов выводится из соответствий входа подтверждённым клавишам.</p></div><div class="rg-legend">H — удерживаемый след · A — готовность · красная стрелка тормозит · подтверждение снимает торможение</div></div>
<section class="rg-decision"><div class="rg-row"><b>ПОЧЕМУ ВЫБРАН СЛЕДУЮЩИЙ ШАГ</b><span id="rg-pending-label"></span></div><div id="rg-flow-summary" class="rg-note"></div><div id="rg-candidates"></div></section>
<section id="rg-selected" class="rg-selected">Нажмите на вхождение, вершину или связь для объяснения.</section></section>
<aside class="rg-side"><div class="rg-row"><b>ВИРТУАЛЬНАЯ СРЕДА</b><span id="rg-scene-version"></span></div><svg id="rg-screen" viewBox="0 0 1000 600" role="group" aria-label="Виртуальный экран"></svg>
<div class="rg-row rg-small"><span id="rg-under"></span><span id="rg-coords"></span></div><div class="rg-display"><span id="rg-app"></span><strong id="rg-output">—</strong></div><div class="rg-ack-output">Подтверждено сетью: <b id="rg-confirmed">—</b></div>
<div class="rg-actions"><button id="rg-shuffle">Переставить</button><button id="rg-hide">Скрыть выбранный</button><button id="rg-show">Показать все</button></div><div class="rg-actions rg-add"><input id="rg-object-name" maxlength="40" placeholder="Новый объект"><button id="rg-add-object">Добавить</button></div>
<details id="rg-receipts" open><summary>Проверка подтверждений</summary><label>Режим <select id="rg-ack-mode"><option value="auto">Автоматически</option><option value="delay">С задержкой</option><option value="manual">Доставить вручную</option><option value="reject">Отклонить до выполнения</option><option value="drop">Потерять подтверждение</option></select></label><label>Применять к <select id="rg-fault-scope"><option value="key">Клавишам</option><option value="click">Кликам</option><option value="all">Всем внешним действиям</option></select></label><label>Задержка, тактов <input id="rg-delay" type="number" min="0" max="150" value="4"></label><label>Тайм-аут, тактов <input id="rg-timeout" type="number" min="2" max="200" value="30"></label>
<button id="rg-deliver" class="rg-primary">Доставить подтверждение</button><button id="rg-duplicate">Повторить последнее</button><p id="rg-receipt-text" class="rg-note">Выбор клавиши не равен подтверждённому вводу.</p></details>
<details id="rg-training"><summary>Свои демонстрации</summary><label>Полный обучающий запрос <input id="rg-demo-query" maxlength="200" placeholder="Например, добавь траты 1700"></label><div class="rg-actions"><button id="rg-record">● Начать</button><button id="rg-stop">Закончить / Esc</button><button id="rg-learn">Сохранить</button><button id="rg-discard">Сброс записи</button></div><input id="rg-keys" aria-label="Клавиатура демонстрации" autocomplete="off" placeholder="Кликните объект, затем введите символы"><div id="rg-buffer"></div><button id="rg-approve">+ Правильно: подтвердить пример</button><p class="rg-note">Один пример или повтор того же ввода не обосновывает обобщение. Нужны два отличающихся согласованных примера.</p></details>
<details id="rg-audit" open><summary>Что выведено из примеров</summary><div id="rg-evidence"></div><p class="rg-note">Правило сопоставления задано разработчиком: уникальный упорядоченный участок подтверждённых клавиш в конце запроса. Слова, их число, объект и вводимые символы не зашиты в движок.</p></details>
<details><summary>Параметры расчёта</summary><div id="rg-config"></div><p class="rg-note">Настройки — инженерный эксперимент, не биологическая модель. Торможение по умолчанию сильнее возбуждения удерживаемого следа.</p></details>
</aside></main>
<div id="rg-history-banner" hidden>Просмотр истории: живая среда и память не меняются.<button id="rg-live">К текущему состоянию</button></div>
<footer class="rg-playbar"><div class="rg-actions"><button id="rg-play" class="rg-primary">▶ Пуск</button><button id="rg-step">Один такт</button><button id="rg-next-effect">До действия</button><button id="rg-reset">Новая попытка</button><button id="rg-deliver-main" class="rg-primary" hidden>Доставить подтверждение</button></div><label class="rg-speed">Интервал <output id="rg-speed-label"></output><input id="rg-speed" type="range" min="100" max="3000" step="100" value="600"></label><span id="rg-state"></span><button id="rg-log-toggle">Журнал</button><button id="rg-clear">Очистить режим</button></footer>
<div class="rg-timeline"><span id="rg-index">0 / 0</span><input id="rg-timeline" type="range" min="0" max="0" value="0" aria-label="История экспериментального режима"><span id="rg-tick">Такт 0</span></div><div class="rg-progress"><div id="rg-progress"></div></div><div id="rg-log" hidden></div>
<input id="rg-file" type="file" accept=".json,application/json" hidden><div id="rg-toast" hidden role="status"></div>
<dialog id="rg-help-dialog"><button id="rg-close-help">Закрыть</button><h2>Проверяем не только ответ, но и причину</h2><p>«Два примера» создаёт подтверждённые демонстрации 1700 и 2345. Передайте 1354 — в графе временных вхождений наблюдайте, как следы слов расходуются по распознаванию, а цифры остаются до подтверждения каждой клавиши.</p><p>H сохраняет содержание. A показывает готовность. Неотработанный предшественник тормозит следующее вхождение. Побеждает максимальное допустимое A выше порога; затем требуется отдельное подтверждение. Новое число не обучается и веса не меняются.</p><p>Выберите «Доставить вручную». Когда в среде появится первая цифра, её след ещё удерживается. Без подтверждения вторая цифра не вводится, а первая не повторяется. «Доставить подтверждение» освобождает следующее вхождение.</p><p>Система сопоставляет только один непрерывный заключительный участок клавиатурного ввода. Два разных примера должны иметь одинаковый предшествующий контекст и согласованные действия. Неизвестный символ, неоднозначная граница или неверная команда останавливают запуск. Регистр и пробелы значимы. Это явное ограничение гипотезы, не всеобщее понимание команд.</p><p>При ошибке подтверждения или тайм-ауте не посылается автоматический повтор. При потере подтверждения действие уже могло произойти в среде. Сброс попытки — явная отмена, не доказательство успеха.</p></dialog>`;

export function mountResidualLab() {
  const root=rq('root');root.innerHTML=rmarkup;
  let engine=new ResidualEngine(),proposal=null,run=false,progress=0,lastTime=0,speed=600,history=null,historyEngine=null;
  let ready=false,mode='sequential',db=null,owns=true,saveTimer=null,selected=null,selectedObject='';
  let recording=false,stopped=false,recordActions=[],recordInitial=null,recordScene=null,view='input',stopAtEffect=false;
  let camera={x:0,y:0,z:1},graphDrag=null,screenDrag=null,lastGraphSignature='';
  const current=()=>history===null?engine:historyEngine;
  const screen=()=>recording||stopped?recordScene:current().model.scene;
  function toast(text){rq('toast').textContent=text;rq('toast').hidden=false;setTimeout(()=>rq('toast').hidden=true,5500);}
  function snapshot(){return {schema:'kolos-disinhibition-ui/1',engine:engine.export(),query:rq('query').value,speed,
    draft:recording||stopped?{query:rq('demo-query').value,actions:recordActions,initial:recordInitial}:null};}
  async function save(){if(!ready)return;try{if(!db||!owns)throw Error();const data=snapshot();await new Promise((res,rej)=>{const tx=db.transaction('state','readwrite');tx.objectStore('state').put(data,'residual');tx.oncomplete=res;tx.onerror=rej;});rq('save-status').textContent='Сохранено в браузере';}catch{rq('save-status').textContent=owns?'Сохраните JSON':'Другая вкладка · экспорт';}}
  function saveSoon(){clearTimeout(saveTimer);saveTimer=setTimeout(save,180);}
  function halt(){run=false;lastTime=0;controls();}
  function invalidate(){proposal=null;progress=0;}
  function op(operation){halt();invalidate();if(history!==null){toast('Вернитесь к текущему состоянию');return false;}try{engine.perform(operation);render();saveSoon();return true;}catch(e){toast(e.message);render();return false;}}
  function controls() {
    const training=recording||stopped,edit=ready&&!run&&history===null&&!training;
    rq('play').textContent=run?'Ⅱ Пауза':'▶ Пуск';rq('play').disabled=!ready||training;
    for(const id of ['step','next-effect','start','checks','demo','import','clear','record','reset'])rq(id).disabled=!edit;
    rq('start').disabled=!edit||!!engine.model.pending;
    rq('query').disabled=!edit;rq('record').disabled=!edit||!!engine.model.pending;
    rq('demo-query').disabled=run||training||history!==null;
    rq('stop').disabled=!recording;rq('learn').disabled=!stopped||!recordActions.length;
    rq('discard').disabled=!training;rq('keys').disabled=!recording||!recordScene?.app;
    rq('approve').disabled=!edit||!!engine.model.pending||!engine.model.episodes.some(e=>!e.approved);
    for(const id of ['shuffle','hide','show','add-object','object-name'])rq(id).disabled=!edit;
    for(const id of ['ack-mode','fault-scope','delay','timeout'])rq(id).disabled=!edit||!!engine.model.pending;
    root.querySelectorAll('[data-rconfig],[data-rweight]').forEach(e=>e.disabled=!edit||!!engine.model.pending);
    rq('deliver').disabled=!edit||!engine.model.pending?.receipt;
    rq('duplicate').disabled=!edit||!engine.model.received.length;
    rq('deliver-main').hidden=!engine.model.pending?.receipt||history!==null;rq('deliver-main').disabled=!edit;
    rq('timeline').disabled=training;rq('history-banner').hidden=history===null;
    rq('state').textContent=recording?'Запись демонстрации':history!==null?'История':run?'Выполняется':'На паузе';
    rq('index').textContent=`${history??engine.operations.length} / ${engine.operations.length}`;
    rq('timeline').max=engine.operations.length;rq('timeline').value=history??engine.operations.length;
    rq('tick').textContent='Такт '+current().model.tick;
    rq('speed-label').textContent=(speed/1000).toFixed(1).replace('.',',')+' с';
    rq('export').disabled=!ready;
  }
  function drawScene() {
    const s=screen();if(!s)return;
    rq('screen').innerHTML='<rect width="1000" height="600" fill="#102321" rx="14"/>'+s.objects.filter(o=>o.visible).map(o=>`<g data-rgo="${rx(o.name)}" role="button" tabindex="0" transform="translate(${o.x},${o.y})" class="rg-object ${selectedObject===o.name?'selected':''}"><rect x="-75" y="-44" width="150" height="88" rx="13"/><text text-anchor="middle" y="10">${rx(o.name)}</text></g>`).join('')+`<g id="rg-cursor" transform="translate(${s.cursor.x},${s.cursor.y})"><circle r="22"/><path d="M-30 0H30M0 -30V30"/></g>`;
    rq('under').textContent='Под курсором: '+(residualUnder(s)||'—');rq('coords').textContent=`${s.cursor.x} × ${s.cursor.y}`;
    rq('scene-version').textContent='v'+s.version;rq('app').textContent=s.app?'Открыто: '+s.app:'Рабочий стол';rq('output').textContent=s.output||'—';
    rq('confirmed').textContent=current().model.input.nodes.filter(n=>n.consumedBy?.kind==='key').map(n=>n.value).join('')||'—';
    rq('buffer').textContent=recordActions.map(a=>a.kind==='key'?'KEY '+a.value:a.kind.toUpperCase()+(a.object?' '+a.object:'')).join(' → ')||'Демонстрация пуста';
  }
  function positionsFor(nodes) {
    const result=new Map();nodes.forEach((n,i)=>{const row=Math.floor(i/5),col=i%5;result.set(n.id,{x:(row%2?4-col:col)*210,y:row*152});});return result;
  }
  function drawGraph(event,preview=false) {
    const m=current().model,isInput=view==='input';
    const nodes=isInput?m.input.nodes:m.memory.nodes;
    const edges=isInput?m.input.edges:m.memory.edges;
    const pos=positionsFor(nodes),find=new Map(nodes.map(n=>[n.id,n]));
    const paths=edges.map(e=>{
      const a=pos.get(e.from),b=pos.get(e.to);if(!a||!b)return '';
      const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,nx=dx/len,ny=dy/len;
      const p1={x:a.x+nx*82,y:a.y+ny*48},p2={x:b.x-nx*86,y:b.y-ny*50};
      const bend=dy?35:0,cx=(p1.x+p2.x)/2-ny*bend,cy=(p1.y+p2.y)/2+nx*bend;
      const blocking=isInput&&find.get(e.from)?.held;
      return `<g class="rg-edge ${blocking?'blocking':''}" data-rge="${rx(e.id)}"><path id="rg-path-${rx(e.to.replace(/[^\w-]/g,'_'))}" d="M${p1.x} ${p1.y} Q${cx} ${cy} ${p2.x} ${p2.y}" marker-end="url(#rg-arrow)"/><text x="${cx}" y="${cy-8}">${isInput?(blocking?'−'+rp(m.config.inhibition):'снято'):`${rx(e.id)} · ${e.weight.toFixed(2)}`}</text></g>`;
    }).join('');
    const svgNodes=nodes.map(n=>{
      const p=pos.get(n.id),c=event?.candidates?.find(c=>c.sourceId===n.id||c.memoryTo===n.id);
      const a=preview&&c?c.activation:isInput?n.activation:m.activations[n.id]||0;
      const chosen=event?.winner&&(event.candidates?.find(c=>c.id===event.winner)?.sourceId===n.id||event.winner==='event:'+n.id);
      const consumed=isInput&&!n.held,waiting=isInput&&n.state==='waiting',active=!isInput&&m.memoryActive===n.id;
      const label=isInput?(n.value===' '?'␣':n.value):n.label;
      const line=isInput?`H ${rp(n.held)} · A ${rp(a)} / ${rp(m.config.threshold)}`:`${rx(n.kind)} · A ${rp(a)}`;
      return `<g data-rgn="${rx(n.id)}" tabindex="0" role="button" class="rg-node ${consumed?'consumed':''} ${waiting?'waiting':''} ${chosen||active?'active':''}" transform="translate(${p.x} ${p.y})"><title>${rx(label)} · ${n.id}</title><rect x="-85" y="-46" width="170" height="96" rx="12"/><text class="rg-nlabel" y="-18">${rx(label.length>19?label.slice(0,17)+'…':label)}</text><text class="rg-nvalues" y="4">${line}</text><text class="rg-nstate" y="23">${isInput?(consumed?'подтверждено':waiting?'ждёт подтверждения':'ещё нужно'):(active?'текущий контекст':'выученная вершина')}</text><text class="rg-nid" y="40">${rx(n.id)}${isInput?' · R '+n.refractory:''}</text></g>`;
    }).join('');
    rq('graph').innerHTML=`<defs><marker id="rg-arrow" markerWidth="6" markerHeight="6" refX="8" refY="5" viewBox="0 0 10 10" orient="auto"><path d="M0 0L10 5L0 10" fill="#769c96"/></marker><pattern id="rg-dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#293d38"/></pattern></defs><rect width="100%" height="100%" fill="url(#rg-dots)"/><g id="rg-world">${paths}${svgNodes}<circle id="rg-pulse" r="7" fill="#baf4cb" visibility="hidden"/></g>`;
    rq('graph')._positions=pos;transform();rq('graph-count').textContent=`${nodes.length} вершин · ${edges.length} связей`;
    const signature=view+':'+nodes.map(n=>n.id).join('|');
    if(lastGraphSignature!==signature){lastGraphSignature=signature;requestAnimationFrame(fit);}
    rq('empty').hidden=nodes.length>0;
  }
  function transform(){rq('world')?.setAttribute('transform',`translate(${camera.x},${camera.y}) scale(${camera.z})`);}
  function fit(){const ps=[...(rq('graph')._positions?.values()||[])];if(!ps.length||rq('graph').clientWidth<50)return;
    const minX=Math.min(...ps.map(p=>p.x))-112,maxX=Math.max(...ps.map(p=>p.x))+112,minY=Math.min(...ps.map(p=>p.y))-65,maxY=Math.max(...ps.map(p=>p.y))+82;
    camera.z=Math.min(1.15,(rq('graph').clientWidth-20)/(maxX-minX),(rq('graph').clientHeight-35)/(maxY-minY));
    camera.x=rq('graph').clientWidth/2-(minX+maxX)/2*camera.z;camera.y=rq('graph').clientHeight/2-(minY+maxY)/2*camera.z;transform();}
  function selection() {
    const m=current().model,out=rq('selected');if(!selected)return;
    const q=m.input.nodes.find(n=>n.id===selected);
    if(q){const pred=residualPrevious(m.input,q.id);out.innerHTML=`<b>${rx(q.value===' '?'Пробел':q.value)} · ${rx(q.id)}</b><p>Удерживаемый след: ${rp(q.held)}. Готовность: ${rp(q.activation)}. Предшественник: ${rx(pred||'нет')}.</p><p>${q.consumedBy?`Погашено только по ${rx(q.consumedBy.requestId)} · ${rx(q.consumedBy.receipt.origin==='internal'?'подтверждению распознавания':'подтверждению среды')}`:'Подтверждения выполнения нет: содержание сохраняется.'}</p>`;return;}
    const e=m.memory.edges.find(e=>e.id===selected);
    if(e){out.innerHTML=`<b>${rx(e.id)}: ${rx(e.from)} → ${rx(e.to)} · ${rx(e.kind)}</b><p>Основания: ${e.evidence.map(rx).join(', ')}</p>`+(['recognize','follows','corresponds'].includes(e.kind)?`<label>Вес <input data-rweight="${rx(e.id)}" type="number" min="0" max="1" step="0.05" value="${e.weight}"></label>`:'');return;}
    const n=m.memory.nodes.find(n=>n.id===selected);if(n)out.innerHTML=`<b>${rx(n.label)} · ${n.id}</b><p>Тип ${rx(n.kind)}. ${n.support?'Различных подтверждённых вводов: '+n.support:''}</p>`;
  }
  function evidence() {
    const a=current().model.audit;
    rq('evidence').innerHTML=a.comparisons.map(g=>`<div class="rg-evidence ${g.qualified?'ok':''}"><b>${rx(g.qualified?'Сопоставление подтверждено':'Недостаточно примеров')}</b><p>Контекст: <code>${rx(g.prefix)}</code></p><p>${rx(g.target)} · различных вводов: ${g.distinct}</p><small>${rx(g.reason)}</small></div>`).join('')||'<p class="rg-note">Нет сопоставленных подтверждённых примеров.</p>';
    rq('evidence').innerHTML+=a.episodes.map(ep=>`<details><summary>${rx(ep.id)} · ${ep.approved?'Правильно':'без оценки'}</summary>${ep.ok?`<p>Граница найдена после ${ep.offset} вхождений, не задана числом слов.</p><div class="rg-align">${ep.alignment.map(x=>`<span>#${x.inputOccurrence} «${rx(x.value)}» ↔ ${rx(x.receipt)}</span>`).join('')}</div>`:`<p>${rx(ep.reason)}</p>`}</details>`).join('');
  }
  function render() {
    const e=current(),m=e.model,event=history===null&&proposal?proposal.event:e.events.at(-1);
    rq('message').textContent=(proposal?'Расчёт следующего такта: ':'')+(event?.message||m.message);rq('message').dataset.state=m.status;
    rq('count').textContent=`Подтверждено ${m.input.nodes.filter(n=>!n.held).length} / ${m.input.nodes.length}`;
    rq('tokens').innerHTML=m.input.nodes.map(n=>`<button data-rselect="${rx(n.id)}" class="rg-token ${!n.held?'done':n.state==='waiting'?'waiting':'held'}" title="${rx(n.id)} · H=${rp(n.held)} · A=${rp(n.activation)}">${rx(n.value===' '?'␣':n.value)}</button>`).join('')||'<span class="rg-note">Весь новый запрос появится здесь: ни один символ не выделяется готовой функцией извлечения числа.</span>';
    drawGraph(event,!!proposal&&history===null);drawScene();selection();evidence();
    const decision=event?.candidates?.length?event:[...e.events].reverse().find(ev=>ev.candidates?.length);
    const cs=decision?.candidates?.filter(c=>!c.id.startsWith('held:'))||[];
    const lastWinner=decision?.candidates?.find(c=>c.id===decision.winner),source=lastWinner?.sourceId&&m.input.nodes.find(n=>n.id===lastWinner.sourceId);
    rq('flow-summary').textContent=lastWinner?`Последний максимум: ${lastWinner.label} · A ${rp(lastWinner.activation)} ≥ ${rp(lastWinner.threshold)}. ${source?`Источник ${source.id}: H ${rp(source.held)}, ${source.consumedBy?'погашен по '+source.consumedBy.receipt.origin+'-подтверждению':'ещё удерживается'}.`:''}`:'';
    rq('candidates').innerHTML=cs.length?'<table><thead><tr><th>Кандидат / источник</th><th>Вход</th><th>Опыт</th><th>Торможение</th><th>A / порог</th><th>Причина</th></tr></thead><tbody>'+cs.map(c=>`<tr class="${decision.winner===c.id?'winner':''}" data-rselect="${rx(c.sourceId||c.memoryTo||'')}"><td>${rx(c.label)}<small>${rx(c.sourceId||c.memoryTo||'без текущего источника')}</small></td><td>+${rp(c.input)}</td><td>+${rp(c.history)}</td><td>−${rp(c.inhibition)}</td><td><b>${rp(c.activation)}</b> / ${rp(c.threshold)}</td><td>${rx(c.reason||(decision.winner===c.id?'Максимум':'Накапливается'))}</td></tr>`).join('')+'</tbody></table>':`<p class="rg-note">${rx(m.pending?'Запрос действия в ожидании. Новая команда не отправляется.':'На следующем такте появятся вклады и причины торможения.')}</p>`;
    rq('pending-label').textContent=m.pending?m.pending.id:'';
    rq('receipt-text').textContent=m.pending?`${m.pending.id} · ${m.pending.applied?'среда обработала, доставка подтверждения ожидается':'только выбрано, эффекта ещё нет'}`:'Нет неподтверждённого действия.';
    rq('log').innerHTML=e.events.slice(-100).map((ev,i)=>`<button data-rhistory="${Math.max(0,e.events.length-100)+i+1}"><b>${Math.max(0,e.events.length-100)+i+1} · ${rx(ev.kind)}</b> ${rx(ev.message)}</button>`).reverse().join('');
    for(const el of root.querySelectorAll('[data-rconfig]'))if(document.activeElement!==el)el.value=m.config[el.dataset.rconfig];
    rq('ack-mode').value=m.config.ackMode;rq('fault-scope').value=m.config.faultScope;rq('delay').value=m.config.ackDelay;rq('timeout').value=m.config.timeout;
    rq('progress').style.width=rp(progress)+'%';controls();
  }
  function begin(){if(recording||stopped){toast('Сначала сохраните или сбросьте демонстрацию');return;}}
  function shouldStop(){return RSTOP.has(engine.model.status)||(engine.model.config.ackMode==='manual'&&engine.model.pending?.applied&&(engine.model.config.faultScope==='all'||engine.model.pending.action.kind===engine.model.config.faultScope));}
  function animate() {
    const candidate=proposal?.event.candidates?.find(c=>c.id===proposal.event.winner);
    const target=candidate?.sourceId||proposal?.event.consumed;
    const path=target&&document.getElementById('rg-path-'+target.replace(/[^\w-]/g,'_'));
    if(path&&rq('pulse')) {const pt=path.getPointAtLength(path.getTotalLength()*progress);rq('pulse').setAttribute('cx',pt.x);rq('pulse').setAttribute('cy',pt.y);rq('pulse').setAttribute('visibility','visible');}
  }
  function frame(now) {
    requestAnimationFrame(frame);if(!run||mode!=='disinhibition'){lastTime=now;return;}
    const dt=lastTime?Math.min(100,now-lastTime):0;lastTime=now;
    try {
      if(history!==null){progress+=dt/speed;if(progress>=1){history=Math.min(engine.operations.length,history+1);historyEngine=engine.at(history);progress=0;render();if(history===engine.operations.length)halt();}return;}
      if(!proposal){proposal=engine.preview();progress=0;render();}
      progress=Math.min(1,progress+dt/speed);rq('progress').style.width=rp(progress)+'%';animate();
      if(progress<1)return;
      const result=engine.commit(proposal);invalidate();render();saveSoon();
      if(shouldStop()||(stopAtEffect&&result.kind==='environment'))halt();
    }catch(err){halt();invalidate();toast(err.message);render();}
  }
  function go() {
    if(history!==null){run=true;lastTime=0;controls();return;}
    if(['idle','trained','unknown','complete'].includes(engine.model.status)){toast('Сначала передайте полный запрос');return;}
    if(['blocked','failed','ambiguous','below'].includes(engine.model.status)&&!op({kind:'resume'}))return;
    if(engine.model.status==='timeout'){toast('Подтверждение потеряно: доставьте его явно или сбросьте попытку');return;}
    run=true;lastTime=0;controls();
  }
  rq('start').onclick=()=>{if(op({kind:'start',query:rq('query').value})&&engine.model.status==='running'){run=true;stopAtEffect=false;lastTime=0;controls();}};
  rq('query').onkeydown=e=>{if(e.key==='Enter')rq('start').click();};rq('query').oninput=saveSoon;
  rq('play').onclick=()=>{stopAtEffect=false;run?halt():go();};rq('next-effect').onclick=()=>{stopAtEffect=true;go();};
  rq('step').onclick=()=>{halt();if(history!==null){history=Math.min(engine.operations.length,history+1);historyEngine=engine.at(history);render();return;}try{engine.commit(proposal||engine.preview());invalidate();render();saveSoon();}catch(e){toast(e.message);}};
  rq('reset').onclick=()=>op({kind:'reset'});
  rq('speed').oninput=e=>{speed=Number(e.target.value);controls();saveSoon();};
  rq('demo').onclick=()=>{if(engine.operations.length&&!confirm('Заменить только эксперимент «Снятие торможения» двумя примерами?'))return;halt();invalidate();engine=residualDemo();history=null;selected=null;lastGraphSignature='';rq('query').value='добавь траты 1354';render();saveSoon();};
  rq('clear').onclick=()=>{if(!confirm('Очистить только эксперимент «Снятие торможения»?'))return;halt();invalidate();engine=new ResidualEngine();history=null;selected=null;rq('query').value='';render();saveSoon();};
  rq('checks').onclick=()=>{halt();try{const results=runResidualChecks();toast(`Проверки на отдельной копии: ${results.filter(r=>r.ok).length} / ${results.length}`);rq('selected').innerHTML='<b>Результат проверок на отдельных копиях</b>'+results.map(r=>`<p>${r.ok?'PASS':'FAIL'} · ${rx(r.name)} → ${rx(r.observed)}</p>`).join('');}catch(e){toast(e.message);}};
  function config(values){op({kind:'config',values});}
  rq('ack-mode').onchange=e=>config({ackMode:e.target.value});rq('fault-scope').onchange=e=>config({faultScope:e.target.value});
  rq('delay').onchange=e=>config({ackDelay:Number(e.target.value)});rq('timeout').onchange=e=>config({timeout:Number(e.target.value)});
  rq('deliver').onclick=()=>op({kind:'deliver'});rq('deliver-main').onclick=()=>op({kind:'deliver'});
  rq('duplicate').onclick=()=>{const id=engine.model.received.at(-1),receipt=engine.model.receipts.find(r=>r.requestId===id);if(receipt)op({kind:'receipt',receipt});};
  const labels={threshold:'Порог',decay:'Остаток A за такт',inputDrive:'Подпитка текущего входа',historyGain:'Фон прошлого опыта',inhibition:'Торможение предшественником',margin:'Минимальный отрыв',refractory:'Refractory, тактов'};
  rq('config').innerHTML=Object.entries(labels).map(([key,title])=>`<label>${title}<input data-rconfig="${key}" type="number" min="0" max="${key==='refractory'?10:1}" step="${key==='refractory'?1:.05}" value="${RESIDUAL_DEFAULTS[key]}"></label>`).join('');
  rq('config').onchange=e=>{if(e.target.dataset.rconfig)config({[e.target.dataset.rconfig]:Number(e.target.value)});};
  rq('selected').onchange=e=>{if(e.target.dataset.rweight)op({kind:'weight',id:e.target.dataset.rweight,value:Number(e.target.value)});};
  function sceneChange(fn){const s=structuredClone(engine.model.scene);fn(s);op({kind:'scene',scene:s});}
  rq('shuffle').onclick=()=>sceneChange(s=>{const obs=s.objects.filter(o=>o.visible),positions=obs.map(o=>({x:o.x,y:o.y}));obs.forEach((o,i)=>Object.assign(o,positions[(i+1)%positions.length]));});
  rq('hide').onclick=()=>{if(!selectedObject){toast('Выберите объект');return;}sceneChange(s=>{s.objects.find(o=>o.name===selectedObject).visible=false;});};
  rq('show').onclick=()=>sceneChange(s=>s.objects.forEach(o=>o.visible=true));
  rq('add-object').onclick=()=>{const name=rq('object-name').value.trim();if(!name)return;sceneChange(s=>s.objects.push({name,x:300,y:430,visible:true}));rq('object-name').value='';};
  function recordAction(a) {
    try{const next=[...recordActions,a],d=observeResidualDemonstration(rq('demo-query').value,next,recordInitial);recordActions=d.actions;
      const last=d.confirmations.at(-1);recordScene={...recordScene,app:last.after.app,output:last.after.output,cursor:last.after.cursor,version:last.after.version};drawScene();controls();saveSoon();
    }catch(e){toast(e.message);}
  }
  rq('record').onclick=()=>{if(!rq('demo-query').value){toast('Введите обучающий запрос');return;}halt();invalidate();recording=true;stopped=false;recordActions=[];recordInitial=structuredClone(engine.model.scene);recordInitial.app='';recordInitial.output='';recordInitial.checked='';recordScene=structuredClone(recordInitial);render();saveSoon();};
  function stopRecord(){if(recording){recording=false;stopped=true;render();saveSoon();}}
  rq('stop').onclick=stopRecord;rq('discard').onclick=()=>{recording=false;stopped=false;recordActions=[];recordScene=null;recordInitial=null;render();saveSoon();};
  rq('keys').oninput=e=>{if(!recording)return;const text=e.target.value;e.target.value='';for(const value of Array.from(text))recordAction({kind:'key',value});};
  rq('learn').onclick=()=>{try{const record=observeResidualDemonstration(rq('demo-query').value,recordActions,recordInitial);recording=false;stopped=false;if(op({kind:'teach',record})){recordActions=[];recordScene=null;recordInitial=null;}else stopped=true;render();}catch(e){toast(e.message);}};
  rq('approve').onclick=()=>{const ep=engine.model.episodes.filter(e=>!e.approved).at(-1);if(ep)op({kind:'approve',id:ep.id});};
  rq('screen').onpointerdown=e=>{if(run||history!==null||stopped)return;const hit=e.target.closest('[data-rgo]');if(!hit)return;selectedObject=hit.dataset.rgo;screenDrag={x:e.clientX,y:e.clientY,name:selectedObject,moved:false,scene:structuredClone(screen())};rq('screen').setPointerCapture(e.pointerId);};
  rq('screen').onpointermove=e=>{if(!screenDrag||recording)return;const d=screenDrag,r=rq('screen').getBoundingClientRect();if(Math.abs(e.clientX-d.x)+Math.abs(e.clientY-d.y)>5)d.moved=true;if(d.moved){const o=d.scene.objects.find(o=>o.name===d.name);o.x=Math.round(Math.max(75,Math.min(925,(e.clientX-r.left)/r.width*1000)));o.y=Math.round(Math.max(60,Math.min(540,(e.clientY-r.top)/r.height*600)));const g=[...rq('screen').querySelectorAll('[data-rgo]')].find(x=>x.dataset.rgo===d.name);g.setAttribute('transform',`translate(${o.x},${o.y})`);}};
  rq('screen').onpointerup=e=>{if(!screenDrag)return;const d=screenDrag;screenDrag=null;if(rq('screen').hasPointerCapture(e.pointerId))rq('screen').releasePointerCapture(e.pointerId);if(d.moved){op({kind:'scene',scene:d.scene});return;}
    if(recording){const o=recordScene.objects.find(o=>o.name===d.name);recordAction({kind:'move',x:o.x,y:o.y});recordAction({kind:'check',object:o.name});recordAction({kind:'click',object:o.name});rq('keys').focus();}else drawScene();};
  rq('screen').onpointercancel=()=>{screenDrag=null;drawScene();};
  rq('graph').onpointerdown=e=>{const n=e.target.closest('[data-rgn]'),edge=e.target.closest('[data-rge]');if(n||edge){selected=n?n.dataset.rgn:edge.dataset.rge;selection();controls();}graphDrag={x:e.clientX,y:e.clientY};rq('graph').setPointerCapture(e.pointerId);};
  rq('graph').onpointermove=e=>{if(!graphDrag)return;camera.x+=e.clientX-graphDrag.x;camera.y+=e.clientY-graphDrag.y;graphDrag={x:e.clientX,y:e.clientY};transform();};
  rq('graph').onpointerup=()=>graphDrag=null;rq('graph').onpointercancel=()=>graphDrag=null;
  rq('graph').addEventListener('wheel',e=>{e.preventDefault();camera.z=Math.max(.08,Math.min(3,camera.z*(e.deltaY<0?1.1:.9)));transform();},{passive:false});
  for(const id of ['tokens','candidates'])rq(id).onclick=e=>{const n=e.target.closest('[data-rselect]');if(n){selected=n.dataset.rselect;selection();controls();}};
  rq('view').onchange=e=>{view=e.target.value;lastGraphSignature='';render();fit();};rq('fit').onclick=fit;
  rq('plus').onclick=()=>{camera.z=Math.min(3,camera.z*1.2);transform();};rq('minus').onclick=()=>{camera.z=Math.max(.08,camera.z/1.2);transform();};
  new ResizeObserver(()=>{if(mode==='disinhibition')fit();}).observe(rq('graph'));
  function seek(i){halt();invalidate();history=i;historyEngine=engine.at(i);render();}
  rq('timeline').oninput=e=>seek(Number(e.target.value));rq('live').onclick=()=>{halt();invalidate();history=null;historyEngine=null;render();};
  rq('log-toggle').onclick=()=>{rq('log').hidden=!rq('log').hidden;};rq('log').onclick=e=>{const n=e.target.closest('[data-rhistory]');if(n)seek(Number(n.dataset.rhistory));};
  rq('help').onclick=()=>rq('help-dialog').showModal();rq('close-help').onclick=()=>rq('help-dialog').close();
  function restore(raw) {
    const e=ResidualEngine.import(raw.schema==='kolos-disinhibition-ui/1'?raw.engine:raw);
    if(raw.speed!==undefined&&(!Number.isFinite(raw.speed)||raw.speed<100||raw.speed>3000))throw Error('Некорректная скорость');
    let draft=null;if(raw.draft){const d=raw.draft;if(!d.query||!Array.isArray(d.actions))throw Error('Некорректный черновик');if(d.actions.length)observeResidualDemonstration(d.query,d.actions,d.initial);draft=d;}
    halt();invalidate();engine=e;history=null;selected=null;speed=raw.speed||600;rq('speed').value=speed;rq('query').value=raw.query||'';
    recording=false;stopped=!!draft;recordActions=draft?.actions||[];recordInitial=draft?.initial||null;recordScene=recordInitial&&structuredClone(recordInitial);
    if(draft){rq('demo-query').value=draft.query;if(draft.actions.length){const d=observeResidualDemonstration(draft.query,draft.actions,draft.initial),last=d.confirmations.at(-1).after;Object.assign(recordScene,last);}}
    render();
  }
  rq('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot(),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='kolos-disinhibition-experiment.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);};
  rq('import').onclick=()=>rq('file').click();rq('file').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;halt();try{if(f.size>15*1024*1024)throw Error('Файл больше 15 МБ');const raw=JSON.parse(await f.text());if(engine.operations.length&&!confirm('Заменить только эксперимент «Снятие торможения»?'))return;restore(raw);saveSoon();}catch(err){toast('Импорт: '+err.message);}finally{e.target.value='';}};
  document.addEventListener('kolos:residual:snapshot',e=>{if(typeof e.detail?.reply==='function')e.detail.reply(structuredClone(snapshot()));});
  document.addEventListener('kolos:mode',e=>{if(e.detail.mode!=='disinhibition'&&(recording||stopped)){e.preventDefault();toast('Сохраните или сбросьте демонстрацию');return;}halt();mode=e.detail.mode;if(mode==='disinhibition'){render();requestAnimationFrame(fit);}});
  document.addEventListener('keydown',e=>{if(mode!=='disinhibition')return;if(e.key==='Escape'){recording?stopRecord():halt();}if(e.key===' '&&!['INPUT','TEXTAREA','SELECT','BUTTON'].includes(document.activeElement?.tagName)){e.preventDefault();rq('play').click();}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){halt();save();}});window.addEventListener('pagehide',save);
  async function init(){try{
    if(navigator.locks)await new Promise(resolve=>{navigator.locks.request('kolos-disinhibition-save',{ifAvailable:true},async lock=>{owns=!!lock;resolve();if(lock)await new Promise(()=>{});}).catch(()=>{owns=false;resolve();});});
    db=await new Promise((res,rej)=>{const r=indexedDB.open('KolosDisinhibition',1);r.onupgradeneeded=()=>r.result.createObjectStore('state');r.onsuccess=()=>res(r.result);r.onerror=rej;});
    const raw=await new Promise((res,rej)=>{const r=db.transaction('state').objectStore('state').get('residual');r.onsuccess=()=>res(r.result);r.onerror=rej;});if(raw)restore(raw);
    rq('save-status').textContent=owns?'Сохранено в браузере':'Другая вкладка · экспорт';
  }catch{rq('save-status').textContent='Сохраните JSON';}ready=true;render();requestAnimationFrame(frame);}
  init();
}
