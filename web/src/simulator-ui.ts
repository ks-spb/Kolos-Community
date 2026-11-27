import type { Action, Command, Trace } from './engine.js';
import { actionTitle } from './engine.js';
import {
  addVirtualObject, cloneVirtualScreen, commandForKey, commandsForObjectClick,
  defaultVirtualScreen, findVirtualObject, hideSelectedVirtualObject, moveVirtualObject,
  objectAtCursor, resetVirtualRuntime, selectVirtualObject, showAllVirtualObjects,
  shuffleVirtualObjects, validateVirtualScreen
} from './simulator.js';
import type { VirtualObject, VirtualScreenSnapshot } from './simulator.js';

type TrainingMode = 'idle' | 'recording' | 'stopped';
interface VirtualLabOptions {
  onSave(commands: Command[]): boolean;
  onChange(): void;
  toast(message: string, error?: boolean): void;
  canTrain(): boolean;
}

const q = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

export class VirtualLab {
  screen: VirtualScreenSnapshot = defaultVirtualScreen();
  mode: TrainingMode = 'idle';
  buffer: Command[] = [];
  private options: VirtualLabOptions;
  private history = false;
  private memoryPlaying = false;
  private animationStart: { step: number; x: number; y: number } | null = null;
  private dragged = false;

  constructor(options: VirtualLabOptions) {
    this.options = options;
    this.bind();
    this.render();
  }

  snapshot(): VirtualScreenSnapshot { return cloneVirtualScreen(this.screen); }
  isTraining(): boolean { return this.mode !== 'idle'; }

  restore(raw: unknown): void {
    this.screen = validateVirtualScreen(raw);
    this.mode = 'idle';
    this.buffer = [];
    this.animationStart = null;
    this.render();
  }

  setMemoryState(history: boolean, memoryPlaying: boolean): void {
    this.history = history;
    this.memoryPlaying = memoryPlaying;
    this.updateControls();
  }

  private notice(message: string, kind: 'normal' | 'ok' | 'error' = 'normal'): void {
    const el = q('screen-alert');
    el.textContent = message;
    el.classList.toggle('ok', kind === 'ok');
    el.classList.toggle('error', kind === 'error');
  }

  private bind(): void {
    q('simulator-toggle').addEventListener('click', () => {
      const collapsed = q('simulator').classList.toggle('collapsed');
      q('simulator-toggle').textContent = collapsed ? '+' : '−';
      q('simulator-toggle').setAttribute('aria-expanded', String(!collapsed));
    });
    q('add-object').addEventListener('click', () => {
      try {
        const input = q<HTMLInputElement>('object-name');
        addVirtualObject(this.screen, input.value);
        input.value = '';
        this.notice('Объект добавлен. Его можно перетащить в нужное место.', 'ok');
        this.changed();
      } catch (error) { this.options.toast((error as Error).message, true); }
    });
    q('shuffle-screen').addEventListener('click', () => {
      shuffleVirtualObjects(this.screen);
      this.notice('Объекты переставлены. Память Kolos не менялась.', 'ok');
      this.changed();
    });
    q('hide-object').addEventListener('click', () => {
      const hidden = hideSelectedVirtualObject(this.screen);
      if (!hidden) { this.options.toast('Сначала выберите объект на виртуальном экране.'); return; }
      this.notice(`${hidden.name} скрыт. Теперь можно проверить безопасную остановку.`, 'ok');
      this.changed();
    });
    q('show-objects').addEventListener('click', () => {
      showAllVirtualObjects(this.screen);
      this.notice('Все объекты снова видимы.', 'ok');
      this.changed();
    });
    q('reset-screen').addEventListener('click', () => {
      resetVirtualRuntime(this.screen);
      q<HTMLInputElement>('virtual-keyboard').value = '';
      this.notice('Курсор, открытое приложение и виртуальный ввод сброшены. Позиции объектов сохранены.');
      this.changed();
    });
    q('train-start').addEventListener('click', () => this.startTraining());
    q('train-stop').addEventListener('click', () => this.stopTraining());
    q('train-save').addEventListener('click', () => this.saveTraining());
    q('train-clear').addEventListener('click', () => {
      this.buffer = []; this.mode = 'idle'; document.body.classList.remove('training-active');
      this.notice('Запись демонстрации очищена. Память Kolos не менялась.');
      this.render();
    });
    q<HTMLInputElement>('virtual-keyboard').addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); this.stopTraining(); return; }
      if (this.mode !== 'recording' || event.ctrlKey || event.metaKey || event.altKey) return;
      if (Array.from(event.key).length !== 1) return;
      event.preventDefault();
      const command = commandForKey(event.key);
      this.buffer.push(command);
      this.screen.display = (this.screen.display + event.key).slice(-200);
      (event.currentTarget as HTMLInputElement).value = '';
      this.notice(`Записана клавиша «${event.key}».`, 'ok');
      this.changed();
    });
    q('virtual-screen').addEventListener('pointerdown', event => {
      const target = event.target as HTMLElement;
      if (target.closest('.screen-object')) return;
      if (this.mode === 'recording') return;
      this.screen.cursor = this.toVirtual(event.clientX, event.clientY);
      this.notice(`Курсор перемещён: ${Math.round(this.screen.cursor.x)} × ${Math.round(this.screen.cursor.y)}.`);
      this.changed();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && this.mode === 'recording') {
        event.preventDefault(); this.stopTraining();
      }
    }, true);
  }

  private startTraining(): void {
    if (!this.options.canTrain()) {
      this.options.toast('Сначала завершите ввод запроса и остановите другие переходы.');
      return;
    }
    this.buffer = [];
    this.mode = 'recording';
    document.body.classList.add('training-active');
    this.notice('Запись включена. Кликните нужный объект, затем вводите клавиши. Escape завершает запись.', 'ok');
    this.render();
  }

  private stopTraining(): void {
    if (this.mode !== 'recording') return;
    this.mode = 'stopped';
    document.body.classList.remove('training-active');
    this.notice(`Запись остановлена: ${this.buffer.length} действий. Нажмите «Сохранить демонстрацию».`, 'ok');
    this.render();
  }

  private saveTraining(): void {
    if (this.mode !== 'stopped' || !this.buffer.length) return;
    const commands = structuredClone(this.buffer);
    if (!this.options.onSave(commands)) return;
    this.buffer = [];
    this.mode = 'idle';
    document.body.classList.remove('training-active');
    this.notice('Демонстрация передана в Kolos. После записи отметьте результат «Правильно».', 'ok');
    this.render();
  }

  private changed(): void {
    this.render();
    this.options.onChange();
  }

  private toVirtual(clientX: number, clientY: number): { x: number; y: number } {
    const rect = q('virtual-screen').getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1000, (clientX - rect.left) / Math.max(1, rect.width) * 1000)),
      y: Math.max(0, Math.min(600, (clientY - rect.top) / Math.max(1, rect.height) * 600)),
    };
  }

  private objectClick(object: VirtualObject): void {
    this.screen.selectedId = object.id;
    this.screen.cursor = { x: object.x, y: object.y };
    if (this.mode === 'recording') {
      this.buffer.push(...commandsForObjectClick(object));
      if (this.screen.activeApp !== object.name) this.screen.display = '';
      this.screen.activeApp = object.name;
      this.notice(`Объект ${object.name} (${object.id}) определён. Записано: POS → CHECK → CLICK.`, 'ok');
      this.changed();
      q<HTMLInputElement>('virtual-keyboard').focus();
    } else {
      this.notice(`Выбран объект ${object.name}. В режиме обучения клик станет частью демонстрации.`);
      this.changed();
    }
  }

  private installObjectInteraction(button: HTMLButtonElement, object: VirtualObject): void {
    let startX = 0, startY = 0;
    const move = (event: PointerEvent) => {
      if (!button.hasPointerCapture(event.pointerId)) return;
      const p = this.toVirtual(event.clientX, event.clientY);
      if (Math.abs(event.clientX - startX) + Math.abs(event.clientY - startY) > 5) this.dragged = true;
      if (this.mode !== 'recording') {
        moveVirtualObject(this.screen, object.id, p.x, p.y);
        this.screen.cursor = { x: p.x, y: p.y };
        button.style.left = `${this.screen.objects.find(item => item.id === object.id)!.x / 10}%`;
        button.style.top = `${this.screen.objects.find(item => item.id === object.id)!.y / 6}%`;
        this.render(false);
      }
    };
    button.addEventListener('pointerdown', event => {
      startX = event.clientX; startY = event.clientY; this.dragged = false;
      if (this.mode !== 'recording') button.setPointerCapture(event.pointerId);
    });
    button.addEventListener('pointermove', move);
    button.addEventListener('pointerup', event => {
      if (button.hasPointerCapture(event.pointerId)) button.releasePointerCapture(event.pointerId);
      if (this.dragged) { this.dragged = false; this.render(); this.options.onChange(); return; }
      this.objectClick(object);
    });
  }

  render(rebuildObjects = true): void {
    const screenEl = q('virtual-screen');
    if (rebuildObjects) {
      screenEl.querySelectorAll('.screen-object').forEach(element => element.remove());
      for (const object of this.screen.objects.filter(item => item.visible)) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'screen-object' + (this.screen.selectedId === object.id ? ' selected' : '');
        button.dataset.objectId = object.id;
        button.dataset.name = object.name;
        button.textContent = object.name;
        button.style.left = `${object.x / 10}%`;
        button.style.top = `${object.y / 6}%`;
        button.title = `${object.name}: ${Math.round(object.x)} × ${Math.round(object.y)}`;
        this.installObjectInteraction(button, object);
        screenEl.appendChild(button);
      }
    }
    const cursor = q('virtual-cursor');
    cursor.style.left = `${this.screen.cursor.x / 10}%`;
    cursor.style.top = `${this.screen.cursor.y / 6}%`;
    const under = objectAtCursor(this.screen);
    q('screen-under').textContent = under ? `${under.name} · ${under.id}` : '—';
    q('cursor-coords').textContent = `${Math.round(this.screen.cursor.x)} × ${Math.round(this.screen.cursor.y)}`;
    q('screen-opened').textContent = this.screen.activeApp ? `Открыто: ${this.screen.activeApp}` : 'Рабочий стол';
    q('screen-display').textContent = this.screen.display ? `Ввод: ${this.screen.display}` : '';
    q('training-mode').textContent = this.mode === 'recording' ? '● Идёт запись' : this.mode === 'stopped' ? 'Запись остановлена' : 'Готов к обучению';
    q('training-list').innerHTML = this.buffer.length
      ? this.buffer.map(command => command.kind === 'action' ? `<span class="action-chip">${this.escape(actionTitle(command.action))}</span>` : '').join('')
      : '<span class="muted">Демонстрация пока пуста.</span>';
    this.updateControls();
  }

  private updateControls(): void {
    const recording = this.mode === 'recording';
    const stopped = this.mode === 'stopped';
    q<HTMLButtonElement>('train-start').disabled = recording || stopped || this.history || this.memoryPlaying;
    q<HTMLButtonElement>('train-stop').disabled = !recording;
    q<HTMLButtonElement>('train-save').disabled = !stopped || !this.buffer.length || this.history || this.memoryPlaying;
    q<HTMLButtonElement>('train-clear').disabled = this.mode === 'idle' || this.memoryPlaying;
    q<HTMLInputElement>('virtual-keyboard').disabled = !recording || !this.screen.activeApp;
    for (const id of ['add-object', 'shuffle-screen', 'hide-object', 'show-objects', 'reset-screen'])
      q<HTMLButtonElement>(id).disabled = this.history || this.memoryPlaying;
    q<HTMLInputElement>('object-name').disabled = this.history || this.memoryPlaying;
  }

  guard(event: Trace): boolean {
    if (event.command.kind !== 'continue' || !event.action) return true;
    const action = event.action;
    if (action.kind === 'move') {
      this.animationStart = { step: event.step, x: this.screen.cursor.x, y: this.screen.cursor.y };
      this.notice(`Память ведёт курсор к старой позиции ${Math.round(action.x)} × ${Math.round(action.y)}.`);
      return true;
    }
    if (action.kind === 'key') {
      if (!this.screen.activeApp) {
        this.notice(`KEY «${action.value}» заблокирован: нет открытого объекта.`, 'error');
        return false;
      }
      return true;
    }
    const expected = action.object;
    const under = objectAtCursor(this.screen);
    if (under?.name === expected) {
      this.notice(`Проверка пройдена: под курсором ${expected}.`, 'ok');
      return true;
    }
    const found = findVirtualObject(this.screen, expected);
    if (!found) {
      this.notice(`Ожидался ${expected}, но объект не найден на экране. ${action.kind === 'click' ? 'КЛИК ЗАПРЕЩЁН.' : 'Выполнение остановлено.'}`, 'error');
      return false;
    }
    const actual = under?.name || 'пусто';
    this.screen.cursor = { x: found.x, y: found.y };
    this.notice(`На старой позиции: ${actual}. ${expected} найден в ${Math.round(found.x)} × ${Math.round(found.y)}; курсор перенесён.`, 'ok');
    this.render();
    this.options.onChange();
    return true;
  }

  animate(event: Trace, progress: number): void {
    if (event.command.kind !== 'continue' || event.action?.kind !== 'move') return;
    const start = this.animationStart?.step === event.step ? this.animationStart : { step: event.step, x: this.screen.cursor.x, y: this.screen.cursor.y };
    this.animationStart = start;
    this.screen.cursor = {
      x: start.x + (event.action.x - start.x) * progress,
      y: start.y + (event.action.y - start.y) * progress,
    };
    this.render(false);
  }

  commit(event: Trace): void {
    if (event.command.kind !== 'continue' || !event.action) return;
    const action: Action = event.action;
    if (action.kind === 'move') {
      this.screen.cursor = { x: action.x, y: action.y };
      this.animationStart = null;
    } else if (action.kind === 'click') {
      if (this.screen.activeApp !== action.object) this.screen.display = '';
      this.screen.activeApp = action.object;
      this.notice(`CLICK ${action.object} выполнен после проверки объекта.`, 'ok');
    } else if (action.kind === 'key') {
      this.screen.display = (this.screen.display + action.value).slice(-200);
      this.notice(`KEY «${action.value}» выполнен в ${this.screen.activeApp}.`, 'ok');
    }
    this.render();
    this.options.onChange();
  }

  private escape(value: string): string {
    return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));
  }
}
