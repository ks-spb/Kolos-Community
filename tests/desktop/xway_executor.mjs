/** Mechanical browser motor for Kolos requests; no model, planner or fallback route. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const XWAY_ORIGIN = 'https://am.xway.ru';
const SHOP_BINDING = path.join(ROOT, '.local-data', 'xway-readonly.json');
const shopPath = task => '/wb/shop/' + task.shop_id;
const searchScope = task => 'XWAY shop ' + task.shop_id + ' search';
const EDITOR = 'Введите артикулы через enter';
const sha = value => createHash('sha256').update(value).digest('hex');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const requireThat = (condition, message) => { if (!condition) throw Error(message); };

async function bindShop(task) {
  const binding = JSON.parse(await fs.readFile(SHOP_BINDING, 'utf8'));
  const { shop_id, shop_name } = binding;
  requireThat(typeof shop_id === 'string' && /^[1-9][0-9]{0,11}$/.test(shop_id)
    && typeof shop_name === 'string' && shop_name.trim().length > 0,
    'Invalid XWAY shop binding');
  return { ...task, shop_id, shop_name };
}

export function validateMotor(request, task) {
  const { action: a, motor } = request;
  requireThat(a && a.descriptor && ['teacher', 'learned-graph'].includes(request.origin), 'Unknown request origin');
  const d = a.descriptor;
  if (motor === 'read' && a.kind === 'read') return;
  if (motor === 'local-report' && a.kind === 'write' && d.scope === 'Local XWAY report' &&
      ['Report SKU', 'Report WB ID', 'Report budget'].includes(d.name) && typeof a.value === 'string') return;
  requireThat(d.scope === searchScope(task), 'Browser write outside search');
  if (motor === 'search-fill' && a.kind === 'write' && d.name === 'Product search' && a.value === task.sku) return;
  if (motor === 'search-apply' && a.kind === 'activate' && d.name === 'Apply search') return;
  throw Error('Motor action denied');
}

class Kernel {
  constructor(output) {
    this.directory = path.join(output, 'ipc'); this.sequence = 0; this.pending = false;
  }
  async call(request) {
    requireThat(!this.pending, 'Concurrent kernel request');
    this.pending = true;
    const sequence = ++this.sequence;
    const temporary = path.join(this.directory, `in-${sequence}.tmp`);
    await fs.writeFile(temporary, JSON.stringify(request));
    await fs.rename(temporary, path.join(this.directory, `in-${sequence}.json`));
    const deadline = Date.now() + 20000;
    let answer;
    while (Date.now() < deadline) {
      try { answer = JSON.parse(await fs.readFile(path.join(this.directory, `out-${sequence}.json`), 'utf8')); break; }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      await pause(30);
    }
    this.pending = false;
    requireThat(answer, 'Kernel IPC timeout; request will not be resent');
    if (!answer.ok) throw Error(`${answer.error.type}: ${answer.error.message}`);
    return answer.result;
  }
  async close() { await fs.writeFile(path.join(this.directory, 'close.json'), '{}'); }
}

/** Extract visible DOM only. No application state, cookies, APIs, or network calls. */
function readDom() {
  const visible = e => !!e.getClientRects().length;
  const clean = s => s.replace(/\s+/g, ' ').trim();
  const header = document.querySelector('tr');
  if (!header) throw Error('Catalogue header not ready');
  const labels = Array.from(header.cells).map(c => clean(c.innerText));
  const skuIndex = labels.findIndex(s => s.includes('Артикул продавца'));
  const aiIndex = labels.findIndex(s => s === 'XWAY AI');
  if (skuIndex < 0 || aiIndex < 0) throw Error('Required columns missing');
  const rows = Array.from(document.querySelectorAll('tr'))
    .filter(r => /WB ID:\s*\d+/.test(r.innerText) && visible(r)).map(r => {
      const ai = r.cells[aiIndex];
      const captions = Array.from(ai.querySelectorAll('button')).filter(visible)
        .map(b => b.innerText.trim()).filter(s => /^\d[\d\s]*(?:[,.]\d{1,2})?\s*₽$/.test(s));
      return { sku: r.cells[skuIndex].innerText.trim(), wb_id: r.innerText.match(/WB ID:\s*(\d+)/)[1],
        budget: captions.length === 1 ? captions[0] : '',
        ai_enabled: !!ai.querySelector('input[type="checkbox"]')?.checked };
    });
  const editors = Array.from(document.querySelectorAll('textarea'))
    .filter(e => e.placeholder === 'Введите артикулы через enter' && visible(e));
  const apply = Array.from(document.querySelectorAll('button'))
    .filter(e => e.innerText.trim() === 'Применить' && visible(e));
  const exact = Array.from(document.querySelectorAll('input[type="radio"]'))
    .some(e => e.value === 'vendor_code' && e.checked);
  return { url: location.href, shop: document.querySelector('h1')?.innerText.trim(),
    result_count: rows.length, rows, search: editors.length === 1 ? editors[0].value : '',
    editor_visible: editors.length === 1, apply_count: apply.length, exact };
}

export class XwayExecutor {
  constructor(tab, options) {
    requireThat(/^[a-zA-Z0-9_-]+$/.test(options.name), 'Invalid evidence directory');
    this.tab = tab; this.options = { ...options };
    this.output = path.join(ROOT, 'tests', 'desktop-output', options.name);
    this.session = options.name; this.version = 0; this.sequence = 0;
    this.tail = Promise.resolve(); this.frameCount = 0; this.label = 'preparation';
    this.motorEvents = []; this.dispatched = new Set(); this.frameErrors = [];
  }
  serial(fn) {
    const work = this.tail.then(fn);
    this.tail = work.catch(() => {});
    return work;
  }
  async event(actor, event, data = {}) {
    this.label = `${actor}: ${event}`;
    const item = { sequence: ++this.sequence, utc: new Date().toISOString(),
      actor, event, ...data, previous: this.previous || '' };
    item.sha256 = sha(JSON.stringify(item)); this.previous = item.sha256;
    await fs.appendFile(path.join(this.output, 'executor.jsonl'), JSON.stringify(item) + '\n');
  }
  async initialize() {
    this.options.task = await bindShop(this.options.task);
    await fs.mkdir(path.join(this.output, 'frames'), { recursive: true });
    this.kernel = new Kernel(this.output);
    const files = ['tests/desktop/xway_executor.mjs', 'kolos_states/xway_readonly/worker.py',
      'kolos_states/xway_readonly/protocol.py', 'kolos_states/episode_browser.py',
      'kolos_states/episodes.py', 'kolos_states/core.py'];
    this.sources = Object.fromEntries(await Promise.all(files.map(async file =>
      [file, sha(await fs.readFile(path.join(ROOT, file)))])));
    this.loaded = await this.kernel.call({ op: 'load', task: this.options.task,
      memory: this.options.memory, mode: this.options.mode || 'trained' });
    await this.event('runner', 'loaded', this.loaded);
  }
  async frame() {
    const bytes = await this.serial(() => this.tab.screenshot({ fullPage: false }));
    const filename = `${String(++this.frameCount).padStart(6, '0')}.png`;
    await fs.writeFile(path.join(this.output, 'frames', filename), bytes);
    const item = { file: filename, utc: new Date().toISOString(), label: this.label,
      sha256: sha(bytes) };
    await fs.appendFile(path.join(this.output, 'frames.jsonl'), JSON.stringify(item) + '\n');
  }
  async record() {
    this.recording = true;
    this.pump = (async () => {
      while (this.recording) {
        try { await this.frame(); } catch (error) { this.frameErrors.push(String(error)); }
        if (this.recording) await pause(500);
      }
    })();
  }
  async survey() {
    const raw = await this.serial(() => this.tab.playwright.evaluate(readDom));
    raw.session = this.session; raw.version = ++this.version;
    raw.captured_at = Date.now() / 1000;
    const url = new URL(raw.url);
    requireThat(url.origin === XWAY_ORIGIN &&
      url.pathname === shopPath(this.options.task) && raw.shop === this.options.task.shop_name,
    'Wrong shop or URL');
    return raw;
  }
  async openFilter(actor) {
    const raw = await this.survey();
    if (raw.editor_visible) return;
    const filter = this.tab.playwright.locator('th').filter({ hasText: 'Артикул продавца', visible: true })
      .locator('span[data-id] button');
    requireThat(await filter.count() === 1, 'Ambiguous seller SKU filter');
    await this.event(actor, 'open-filter', { reason: 'Make the observed editor available; no search value chosen' });
    await this.serial(() => filter.click());
    const after = await this.survey();
    requireThat(after.editor_visible && after.exact && after.apply_count === 1, 'Exact filter unavailable');
  }
  async bootstrap() {
    const url = XWAY_ORIGIN + shopPath(this.options.task) + '?tab=product';
    await this.event('bootstrap', 'reset-view', { url });
    await this.serial(() => this.tab.goto(url));
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      try {
        const raw = await this.survey();
        this.baseline = raw.rows.filter(r => r.sku === this.options.task.sku && r.wb_id === this.options.task.wb_id);
        if (this.baseline.length === 1 && this.baseline[0].budget) break;
      } catch (error) { await this.event('bootstrap', 'not-ready', { error: String(error) }); }
      await this.frame();
    }
    requireThat(this.baseline?.length === 1 && this.baseline[0].budget, 'Target not visible in initial catalogue');
    await this.openFilter('bootstrap');
    await this.event('bootstrap', 'ready', { baseline: this.baseline[0], task: this.options.task });
  }
  async waitProduct() {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      try {
        const raw = await this.survey();
        if (raw.rows.length === 1 && raw.rows[0].sku === this.options.task.sku &&
            raw.rows[0].wb_id === this.options.task.wb_id) return raw;
      } catch (error) {
        if (!/Catalogue header not ready|Required columns missing/.test(String(error))) throw error;
        await this.event('adapter', 'waiting-for-catalogue', { reason: String(error) });
      }
      await this.frame();
    }
    throw Error('Exact product not observed after search; no retry');
  }
  async perform(request) {
    validateMotor(request, this.options.task);
    requireThat(!this.dispatched.has(request.id), 'Duplicate dispatch rejected');
    this.dispatched.add(request.id);
    const { action, motor } = request;
    await this.event(request.origin === 'teacher' ? 'teacher' : 'kernel', 'dispatch', request);
    const raw = await this.survey();
    requireThat(raw.editor_visible && raw.exact && raw.apply_count === 1, 'Filter context lost');
    if (motor === 'read' && action.kind === 'read') return;
    if (motor === 'local-report' && action.kind === 'write' &&
        action.descriptor.scope === 'Local XWAY report') {
      await this.kernel.call({ op: 'local', dom: raw }); return;
    }
    requireThat(action.descriptor.scope === searchScope(this.options.task), 'Browser write outside search');
    if (motor === 'search-fill' && action.kind === 'write' && action.descriptor.name === 'Product search') {
      requireThat(action.value === this.options.task.sku, 'Wrong task value');
      await this.event('adapter', 'fill-search', { request: request.id, value: action.value });
      this.motorEvents.push('fill-search');
      await this.serial(() => this.tab.playwright.getByPlaceholder(EDITOR, { exact: true }).fill(action.value));
      await this.frame();
    } else if (motor === 'search-apply' && action.kind === 'activate' && action.descriptor.name === 'Apply search') {
      requireThat(raw.search === this.options.task.sku, 'Search value changed');
      await this.event('adapter', 'apply-search', { request: request.id });
      this.motorEvents.push('apply-search');
      await this.serial(() => this.tab.playwright.getByRole('button', { name: 'Применить', exact: true }).click());
      await this.waitProduct();
      // The editor is recreated empty by XWAY; reopen it to verify its actual value.
      await this.openFilter('adapter');
      await this.frame();
    } else throw Error('Motor action denied');
  }
  async confirm() {
    const first = await this.survey(), second = await this.survey();
    return this.kernel.call({ op: 'confirm', first, second });
  }
  async stage(stage) {
    await this.kernel.call({ op: 'start', stage, dom: await this.survey() });
    for (let i = 0; i < 16; i++) {
      const request = await this.kernel.call({ op: 'next', dom: await this.survey() });
      if (request.status) {
        await this.event('kernel', 'stage-result', { stage, ...request });
        requireThat(request.status === 'complete', request.message || request.status);
        return;
      }
      await this.perform(request);
      await this.confirm();
    }
    throw Error('Dispatch limit reached');
  }
  async finish(result) {
    this.recording = false;
    if (this.pump) await this.pump;
    try { await this.frame(); } catch (error) { this.frameErrors.push(String(error)); }
    result.finished_utc = new Date().toISOString();
    result.frames = this.frameCount; result.frame_errors = this.frameErrors;
    result.source_sha256 = this.sources; result.loaded = this.loaded;
    result.browser_writes = this.motorEvents; result.kernel_dispatches = this.dispatched.size;
    result.llm_calls_during_replay = 0;
    result.scope = 'Fixed search->read mission; learned primitive order; open-filter adapter; no ad settings';
    await fs.writeFile(path.join(this.output, 'result.json'), JSON.stringify(result, null, 2));
    await this.kernel.close();
    return { output: this.output, ...result };
  }
  async run() {
    const result = { passed: false, started_utc: new Date().toISOString(), task: this.options.task,
      condition: this.options.mode || 'trained', manual_interventions: 0 };
    await this.initialize(); await this.record();
    try {
      await this.bootstrap();
      await this.event('runner', 'autonomous-start');
      // These two mission stages are declared by the task, not selected by an LLM.
      await this.stage('search');
      await this.stage('read');
      const final = await this.survey(), summary = await this.kernel.call({ op: 'summary' });
      result.summary = summary; result.final = final.rows;
      const current = final.rows[0], report = summary.report;
      result.passed = summary.memory_unchanged && current.sku === report.sku &&
        current.wb_id === report.wb_id && current.budget === report.budget &&
        current.budget === this.baseline[0].budget && current.ai_enabled === this.baseline[0].ai_enabled;
      await this.event('runner', 'autonomous-end', { passed: result.passed });
    } catch (error) {
      result.error = String(error);
      result.summary = await this.kernel.call({ op: 'summary' });
      await this.event('runner', 'stopped', { error: result.error });
    }
    return this.finish(result);
  }
  async teachRead() {
    await this.initialize();
    const result = { started_utc: new Date().toISOString(), teacher: 'Explicit developer-authored live demonstration' };
    await this.openFilter('teacher-setup');
    await this.kernel.call({ op: 'teach-start' });
    for (const [index, source, target] of [[0, 'Product SKU', 'Report SKU'],
      [1, 'Product WB ID', 'Report WB ID'], [2, 'Daily budget', 'Report budget']]) {
      for (const [kind, role, slot] of [['read', source, undefined], ['write', target, `v${index}`]]) {
        const request = await this.kernel.call({ op: 'prepare', kind, role, source: slot, dom: await this.survey() });
        await this.perform(request); await this.confirm();
      }
    }
    result.lesson = await this.kernel.call({ op: 'teach-finish' });
    result.passed = true;
    return this.finish(result);
  }
}
