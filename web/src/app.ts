import { Engine, initialState, pointTitle, visibleName, actionTitle, exportExperiment, importExperiment, MAX_EVENTS } from './engine.js';
import type { Command, Trace, State } from './engine.js';
import { VirtualLab } from './simulator-ui.js';
import { GraphView, escapeHTML } from './graph.js';
import { ExperimentStore } from './storage.js';
const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
const icon = (name: string): string => ({ play: '▶', pause: 'Ⅱ', step: '▹' }[name] || name);
let engine = new Engine();
const graph = new GraphView(document.querySelector<SVGSVGElement>('#graph')!);
const store = new ExperimentStore();
let pending: Command[] = [];
let preview: Trace | null = null;
let fromQueue = false;
let playing = false;
let single = false;
let continuing = false;
let progress = 0;
let previousTime = 0;
let historyStep: number | null = null;
let seconds = 1;
let batch = '';
let batchDone = 0;
let lastCommitted: Trace | null = null;
let ready = false;
let savingFailed = false;
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let toastTimer: ReturnType<typeof setTimeout> | undefined;
let lastSavedCommands = -1;
let storageOwned = true;
const input = $<HTMLTextAreaElement>('text-input');
const speed = $<HTMLInputElement>('speed');
const timeline = $<HTMLInputElement>('timeline');
function toast(message: string, error = false): void {
  const el = $('toast'); el.textContent = message; el.classList.toggle('error', error); el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, error ? 6500 : 3500);
}
function getExperiment() {
  return exportExperiment(engine, { seconds, positions: graph.positions, input: input.value, simulator: virtualLab.snapshot() }, pending);
}
async function saveNow(): Promise<void> {
  if (!ready || !storageOwned) return;
  try {
    await store.save(getExperiment()); savingFailed = false;
    lastSavedCommands = engine.events.length;
    $('save-label').textContent = 'Сохранено в браузере'; $('save-state').classList.remove('warning');
  } catch {
    if (!savingFailed) toast('Браузер не разрешил сохранение. Используйте «Экспорт JSON», чтобы не потерять эксперимент.', true);
    savingFailed = true; $('save-label').textContent = 'Сохраните JSON'; $('save-state').classList.add('warning');
  }
}
function scheduleSave(): void { clearTimeout(saveTimer); saveTimer = setTimeout(() => { void saveNow(); }, 180); }
const virtualLab = new VirtualLab({
  onSave: commands => {
    if (historyStep !== null || pending.length || preview || continuing || playing || single) {
      toast('Остановите другие переходы перед сохранением демонстрации.');
      return false;
    }
    enqueue(commands);
    return true;
  },
  onChange: scheduleSave,
  toast,
  canTrain: () => ready && historyStep === null && !pending.length && !preview && !continuing && !playing && !single &&
    !!engine.state.runtime.memory && !engine.state.runtime.terminal,
});
function shownState(): State { return historyStep === null ? engine.state : engine.at(historyStep); }
function halt(): void { playing = false; single = false; previousTime = 0; updateControls(); }
function cancelPreview(): void { preview = null; progress = 0; previousTime = 0; }
function goLive(): void { halt(); cancelPreview(); historyStep = null; render(); }
function seek(step: number): void {
  halt(); cancelPreview(); historyStep = Math.max(0, Math.min(engine.events.length, step)); render();
}
function enqueue(commands: Command[], autoplay = true): void {
  if (historyStep !== null) { toast('Вернитесь к текущему состоянию, чтобы изменить память.'); return; }
  if (pending.length || preview || continuing) { toast('Дождитесь конца очереди или отмените её.'); return; }
  pending = commands; playing = autoplay; single = false; previousTime = 0; render(); scheduleSave();
}
function submit(): void {
  if (!input.value) { toast('Введите текст для записи.'); return; }
  if (Array.from(input.value).length > 2000) { toast('За один ввод — не более 2000 символов.', true); return; }
  const busy = !!preview || pending.length > 0 || continuing;
  if (busy) {
    if (playing || single) { toast('Сначала поставьте выполнение на паузу.'); return; }
    if (!confirm('Отменить оставшуюся очередь и передать новый текст? Уже записанные шаги останутся в памяти.')) return;
    halt(); cancelPreview(); pending = []; continuing = false; batch = ''; batchDone = 0;
  }
  batch = input.value; batchDone = 0;
  enqueue(Array.from(batch, value => ({ kind: 'input', value })));
}
function updateControls(): void {
  const history = historyStep !== null;
  const busy = !!preview || pending.length > 0 || continuing;
  const training = virtualLab.isTraining();
  $('play').innerHTML = `<span aria-hidden="true">${icon(playing ? 'pause' : 'play')}</span> ${playing ? 'Пауза' : 'Пуск'}`;
  $('play').setAttribute('aria-label', playing ? 'Пауза' : 'Пуск');
  $<HTMLButtonElement>('play').disabled = !ready || (!history && !busy) || (history && historyStep! >= engine.events.length);
  $<HTMLButtonElement>('step').disabled = !ready || (!history && !busy) || (history && historyStep! >= engine.events.length);
  // Во время паузы поле остаётся доступным: пользователь может заменить
  // остаток очереди новым текстом. Во время активного движения менять ввод нельзя.
  $<HTMLButtonElement>('submit').disabled = !ready || history || training || (busy && (playing || single));
  $<HTMLButtonElement>('continue').disabled = !ready || history || training || busy || !engine.state.runtime.memory || engine.state.runtime.terminal;
  for (const id of ['positive', 'negative']) $<HTMLButtonElement>(id).disabled = !ready || history || training || busy || engine.state.nodes.find(n => n.id === engine.state.runtime.activeId)?.type === 'REAC';
  $<HTMLButtonElement>('new-attempt').disabled = !ready || history;
  $<HTMLButtonElement>('replay').disabled = !ready || engine.events.length === 0;
  $<HTMLButtonElement>('back').disabled = !ready || (history ? historyStep! <= 0 : engine.events.length === 0);
  $<HTMLButtonElement>('cancel').disabled = !ready || history || !busy;
  input.disabled = !ready || history || training || (busy && (playing || single));
  $('live').hidden = !history;
  $('history-banner').hidden = !history;
  $('live-mode').textContent = history ? 'ПРОСМОТР ИСТОРИИ' : (continuing || preview?.command.kind === 'continue' ? 'ПРОДОЛЖЕНИЕ' : 'ЗАПИСЬ ПАМЯТИ');
  $('live-mode').classList.toggle('history', history);
  $('play-state').textContent = playing || single ? 'Выполняется' : busy ? 'На паузе' : history ? 'История' : 'Ожидание';
  $('play-dot').classList.toggle('on', playing || single);
  timeline.max = String(engine.events.length); timeline.value = String(historyStep ?? engine.events.length);
  $('step-count').textContent = `${historyStep ?? engine.events.length} / ${engine.events.length}`;
  $('speed-label').textContent = `${seconds.toFixed(2).replace('.', ',')} с / шаг`;
  $('pending-label').textContent = pending.length ? `В очереди: ${pending.length}` : continuing ? 'Поиск продолжения' : 'Очередь пуста';
  $('step-progress').style.width = `${progress * 100}%`;
  const completed = Array.from(batch).slice(0, batchDone).map(visibleName).join('');
  const remaining = Array.from(batch).slice(batchDone).map(visibleName).join('');
  $('input-progress').innerHTML = batch ? `<span class="done">${escapeHTML(completed.slice(-36))}</span><span class="remaining">${escapeHTML(remaining.slice(0, 36))}</span>` : '<span>Enter — передать текст · Shift + Enter — новая строка</span>';
  virtualLab.setMemoryState(history, playing || single);
}
function renderInspector(state: State, event: Trace | null): void {
  const current = state.nodes.find(n => n.id === state.runtime.activeId)!;
  $('current-name').textContent = pointTitle(current);
  $('current-number').textContent = `#${current.id}`;
  $('current-signal').textContent = String(current.signal);
  $('count-nodes').textContent = String(state.nodes.length);
  $('count-edges').textContent = String(state.edges.length);
  const isPreview = !!preview;
  $('event-phase').textContent = isPreview ? 'СЛЕДУЮЩИЙ ШАГ' : 'ПОСЛЕДНЕЕ СОБЫТИЕ';
  $('event-title').textContent = event ? ({ input: 'Обработка символа', action: 'Запись действия', continue: 'Выбор продолжения', complete: 'Цепочка завершена', positive: 'Положительная реакция', negative: 'Отрицательная реакция', reset: 'Новая попытка' }[event.kind] || 'Изменение памяти') : 'Готов к первому символу';
  $('event-description').textContent = event?.explanation || 'Введите текст. Каждая буква станет точкой, а порядок ввода — направленными связями.';
  $('edge-used').textContent = event?.usedEdgeId ? `№${event.usedEdgeId}` : '—';
  $('edge-new').textContent = event?.edge ? `№${event.edge.id}` : '—';
  const change = event?.changes.find(c => c.after.type === 'in') || event?.changes[0];
  $('signal-change').textContent = change ? `${change.before?.signal ?? 0} → ${change.after.signal}` : '—';
  $('answer').textContent = state.runtime.answer || 'Здесь появится продолжение';
  $('answer').classList.toggle('placeholder', !state.runtime.answer);
  const runtime = isPreview && event ? event.after : state.runtime;
  $('candidates').textContent = runtime.online.length ? runtime.online.map(n => `№${n}`).join(', ') : 'Нет кандидатов';
  $('path').textContent = runtime.path.length ? runtime.path.map(p => `№${p.edgeId} → #${p.nodeId}`).join('  ·  ') : 'Путь не выбран';
  $('blocked').textContent = runtime.blocked.length ? runtime.blocked.map(n => `#${n}`).join(', ') : 'Нет';
  $('rejected').textContent = event?.rejected.length ? event.rejected.map(r => `№${r.edgeId}: ${r.reason}`).join('\n') : 'Нет отклонённых кандидатов';
  const selection = graph.selected;
  if (!selection) { $('selection').innerHTML = '<p class="muted">Нажмите на точку или стрелку, чтобы увидеть все её данные.</p>'; return; }
  if (selection.kind === 'node') {
    const point = state.nodes.find(n => n.id === selection.id) || preview?.changes.find(c => c.after.id === selection.id)?.after;
    if (!point) { $('selection').textContent = 'На этом шаге точка ещё не создана.'; return; }
    const incoming = state.edges.filter(e => e.to === point.id).map(e => e.id);
    const outgoing = state.edges.filter(e => e.from === point.id).map(e => e.id);
    $('selection').innerHTML = `<div class="selection-name">${escapeHTML(pointTitle(point))}<span>#${point.id}</span></div><dl><dt>Имя в памяти</dt><dd>${escapeHTML(JSON.stringify(point.name))}</dd><dt>Тип</dt><dd>${point.type}</dd><dt>Сигнал</dt><dd>${point.signal}</dd></dl><p class="micro">Входящие связи</p><p class="id-list">${incoming.join(', ') || '—'}</p><p class="micro">Исходящие связи</p><p class="id-list">${outgoing.join(', ') || '—'}</p>`;
  } else {
    const links = state.edges.filter(e => e.from === selection.from && e.to === selection.to);
    $('selection').innerHTML = `<div class="selection-name">#${selection.from} → #${selection.to}</div><p class="muted">Одна стрелка на рисунке. В памяти: ${links.length} отдельных связей.</p><p class="id-list">${links.map(e => `№${e.id}`).join(', ') || 'Связь ещё не записана'}</p><p class="micro">Сигнал принадлежит точке, не связи. Весов в текстовом ядре нет.</p>`;
  }
}
function renderJournal(): void {
  const shown = historyStep ?? engine.events.length;
  const events = engine.events.slice(Math.max(0, shown - 60), shown).reverse();
  $('journal-list').innerHTML = events.map(e => `<button class="journal-row" data-step="${e.step}"><span class="journal-step">${String(e.step).padStart(3, '0')}</span><span class="journal-kind ${e.kind}">${escapeHTML(e.command.kind === 'input' ? visibleName(e.command.value) : e.command.kind === 'action' ? actionTitle(e.command.action) : e.kind === 'complete' ? 'Успех' : e.kind === 'reset' ? 'Старт' : e.command.kind === 'positive' ? '+' : e.command.kind === 'negative' ? '−' : 'Ответ')}</span><span class="journal-text">${escapeHTML(e.explanation)}</span><span class="journal-edge">${e.edge ? '№' + e.edge.id : '—'}</span></button>`).join('') || '<p class="muted journal-empty">Здесь появится точная история переходов. Нажатие на шаг открывает его состояние без изменения памяти.</p>';
  $('journal-total').textContent = `${engine.events.length} событий · последние 60 в списке`;
}
function render(): void {
  const state = shownState();
  const event = preview || (historyStep !== null ? engine.events[historyStep - 1] || null : lastCommitted);
  graph.render(state, preview);
  if (preview) graph.animate(preview, progress);
  renderInspector(state, event); updateControls(); renderJournal();
  $('empty-hint').hidden = state.edges.length > 0 || !!preview || historyStep !== null;
  $('status-text').textContent = state.runtime.status;
}
function prepare(): boolean {
  if (preview) return true;
  try {
    if (historyStep !== null) {
      if (historyStep >= engine.events.length) { halt(); return false; }
      preview = engine.events[historyStep]; fromQueue = false;
    } else {
      const command = pending[0] || (continuing ? { kind: 'continue' as const } : null);
      if (!command) { halt(); return false; }
      fromQueue = pending.length > 0; preview = engine.preview(command);
      if (command.kind === 'continue' && !virtualLab.guard(preview)) {
        continuing = false;
        cancelPreview();
        halt();
        render();
        return false;
      }
    }
    progress = 0; render(); return true;
  } catch (error) { halt(); continuing = false; toast((error as Error).message, true); render(); return false; }
}
function tick(now: number): void {
  requestAnimationFrame(tick);
  if ((!playing && !single) || !ready) { previousTime = now; return; }
  const elapsed = previousTime ? Math.min(80, now - previousTime) : 0; previousTime = now;
  if (!prepare() || !preview) return;
  progress = Math.min(1, progress + elapsed / (seconds * 1000));
  graph.animate(preview, progress); virtualLab.animate(preview, progress); $('step-progress').style.width = `${progress * 100}%`;
  if (progress < 1) return;
  const event = preview;
  if (historyStep !== null) historyStep++;
  else {
    engine.commit(event); lastCommitted = event; virtualLab.commit(event);
    if (fromQueue) { pending.shift(); if (event.command.kind === 'input') batchDone++; }
    if (continuing && (event.after.terminal || !event.after.memory)) continuing = false;
    scheduleSave();
  }
  cancelPreview();
  if (single) halt();
  if (historyStep !== null ? historyStep >= engine.events.length : !pending.length && !continuing) halt();
  render();
}
$('submit').addEventListener('click', submit);
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
input.addEventListener('input', scheduleSave);
$('play').addEventListener('click', () => { if (playing) halt(); else { playing = true; single = false; previousTime = 0; updateControls(); } });
$('step').addEventListener('click', () => { playing = false; single = true; previousTime = 0; updateControls(); });
$('continue').addEventListener('click', () => { continuing = true; playing = true; previousTime = 0; render(); });
$('positive').addEventListener('click', () => enqueue([{ kind: 'positive' }]));
$('negative').addEventListener('click', () => enqueue([{ kind: 'negative' }]));
$('new-attempt').addEventListener('click', () => {
  if ((pending.length || preview) && !confirm('Отменить необработанный ввод и начать новую попытку? Записанные точки останутся.')) return;
  halt(); cancelPreview(); pending = []; continuing = false; batch = ''; batchDone = 0;
  enqueue([{ kind: 'reset' }]);
});
$('cancel').addEventListener('click', () => { halt(); cancelPreview(); pending = []; continuing = false; batch = ''; render(); scheduleSave(); });
speed.addEventListener('input', () => { seconds = Number(speed.value) / 1000; updateControls(); scheduleSave(); });
$('replay').addEventListener('click', () => { seek(0); playing = true; previousTime = 0; updateControls(); });
$('back').addEventListener('click', () => seek((historyStep ?? engine.events.length) - 1));
$('live').addEventListener('click', goLive);
timeline.addEventListener('input', () => seek(Number(timeline.value)));
$('journal-list').addEventListener('click', e => { const button = (e.target as Element).closest<HTMLElement>('[data-step]'); if (button) seek(Number(button.dataset.step)); });
$('journal-toggle').addEventListener('click', () => { const open = document.body.classList.toggle('journal-open'); $('journal-toggle').setAttribute('aria-expanded', String(open)); setTimeout(() => graph.fit(), 230); });
$('inspector-toggle').addEventListener('click', () => { const open = document.body.classList.toggle('inspector-open'); $('inspector-toggle').setAttribute('aria-expanded', String(open)); });
$('fit').addEventListener('click', () => graph.fit());
$('zoom-in').addEventListener('click', () => graph.zoom(1.2));
$('zoom-out').addEventListener('click', () => graph.zoom(1 / 1.2));
$<HTMLInputElement>('neighborhood').addEventListener('change', e => { graph.neighborhood = (e.target as HTMLInputElement).checked; render(); graph.fit(); });
$<HTMLInputElement>('search').addEventListener('input', e => {
  graph.query = (e.target as HTMLInputElement).value; render();
  const match = shownState().nodes.find(n => `${n.id} ${n.name} ${pointTitle(n)}`.toLowerCase().includes(graph.query.toLowerCase()));
  if (graph.query && match) graph.focus(match.id);
});
graph.onSelect = () => { render(); };
graph.onMove = scheduleSave;
$('export').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(getExperiment(), null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = `kolos-experiment-${new Date().toISOString().slice(0, 10)}.json`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000); toast('Эксперимент экспортирован. История и координаты включены.');
});
$('import').addEventListener('click', () => $<HTMLInputElement>('import-file').click());
$<HTMLInputElement>('import-file').addEventListener('change', async e => {
  const target = e.target as HTMLInputElement; const file = target.files?.[0]; if (!file) return;
  halt();
  try {
    if (file.size > 5 * 1024 * 1024) throw new Error('Файл больше 5 МБ.');
    const loaded = importExperiment(JSON.parse(await file.text()));
    if (engine.events.length && !confirm('Заменить текущий эксперимент импортированным? Перед заменой его можно экспортировать.')) return;
    cancelPreview(); engine = loaded.engine; graph.positions = loaded.view.positions; graph.selected = null;
    seconds = loaded.view.seconds; speed.value = String(seconds * 1000); input.value = loaded.view.input; virtualLab.restore(loaded.view.simulator);
    pending = loaded.pending; continuing = false; historyStep = null; batch = pending.filter(c => c.kind === 'input').map(c => (c as { value: string }).value).join(''); batchDone = 0;
    lastCommitted = engine.events.at(-1) || null; render(); graph.fit(); scheduleSave(); toast('Эксперимент восстановлен и поставлен на паузу.');
  } catch (error) { toast(`Импорт не выполнен: ${(error as Error).message}`, true); }
  finally { target.value = ''; }
});
function clearAll(): void {
  if ((engine.events.length || pending.length) && !confirm('Удалить текущий эксперимент из браузера? Это не затронет исходный Kolos или файлы JSON.')) return;
  halt(); cancelPreview(); engine = new Engine(); pending = []; continuing = false; historyStep = null; graph.positions = {}; graph.selected = null;
  batch = ''; batchDone = 0; lastCommitted = null; input.value = ''; virtualLab.restore(undefined); render(); graph.fit(); scheduleSave();
}
$('clear').addEventListener('click', clearAll);
function demo(): void {
  if (engine.events.length && !confirm('Заменить текущий эксперимент учебным примером «абв»?')) return;
  halt(); cancelPreview(); engine = new Engine(); graph.positions = {}; graph.selected = null; pending = []; continuing = false; historyStep = null;
  lastCommitted = null; virtualLab.restore(undefined); batch = 'абв → + → новая попытка → аб'; batchDone = 0; input.value = 'аб';
  const commands: Command[] = [{ kind: 'input', value: 'а' }, { kind: 'input', value: 'б' }, { kind: 'input', value: 'в' },
    { kind: 'positive' }, { kind: 'reset' }, { kind: 'input', value: 'а' }, { kind: 'input', value: 'б' }, { kind: 'continue' }, { kind: 'continue' }];
  batch = ''; enqueue(commands); graph.fit(); toast('Пример: запомнить «абв», затем по «аб» получить «в».');
}
$('demo').addEventListener('click', demo); $('empty-demo').addEventListener('click', demo);
const help = $<HTMLDialogElement>('help-dialog');
$('help').addEventListener('click', () => help.showModal());
$('close-help').addEventListener('click', () => help.close());
help.addEventListener('click', e => { if (e.target === help) { const r = help.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) help.close(); } });
document.addEventListener('visibilitychange', () => { if (document.hidden) { halt(); void saveNow(); } });
window.addEventListener('pagehide', () => { void saveNow(); });
window.addEventListener('beforeunload', e => { if (savingFailed && engine.events.length !== lastSavedCommands) { e.preventDefault(); e.returnValue = ''; } });
document.addEventListener('keydown', e => {
  if ((e.target as Element).closest('input, textarea, button, select, dialog, [data-node]')) return;
  if (e.code === 'Space') { e.preventDefault(); if (!$<HTMLButtonElement>('play').disabled) $('play').click(); }
  if (e.code === 'ArrowRight' && !$<HTMLButtonElement>('step').disabled) { e.preventDefault(); $('step').click(); }
});
async function initialize(): Promise<void> {
  render(); graph.fit();
  // Two tabs must not silently overwrite each other's autosave.
  if (navigator.locks) {
    await new Promise<void>(resolve => {
      void navigator.locks.request('kolos-graph-lab-autosave', { ifAvailable: true }, async lock => {
        storageOwned = !!lock; resolve();
        if (lock) await new Promise<void>(() => {});
      });
    });
  }
  if (!storageOwned) {
    $('save-label').textContent = 'Другая вкладка · только экспорт'; $('save-state').classList.add('warning');
    toast('Автосохранение принадлежит другой вкладке. Здесь изменения можно экспортировать в JSON.', true);
  }
  try {
    const saved = await store.load();
    if (saved) {
      const restored = importExperiment(saved); engine = restored.engine; graph.positions = restored.view.positions;
      seconds = restored.view.seconds; speed.value = String(seconds * 1000); input.value = restored.view.input; virtualLab.restore(restored.view.simulator);
      pending = restored.pending; lastCommitted = engine.events.at(-1) || null;
      lastSavedCommands = engine.events.length;
      if (engine.events.length || pending.length) toast('Память восстановлена. Выполнение остановлено; нажмите «Пуск» для очереди.');
    }
  } catch { savingFailed = true; $('save-label').textContent = 'Автосохранение недоступно'; $('save-state').classList.add('warning'); toast('Локальную память прочитать не удалось. Экспортируйте новый эксперимент в JSON.', true); }
  ready = true; render(); graph.fit();
  requestAnimationFrame(tick);
}
void initialize();
