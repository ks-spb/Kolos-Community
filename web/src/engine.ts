/** Text-only Kolos v4. Original: feature/context-graph @ 35aed01e.
 * See ALGORITHM.md for preserved rules and deliberate safety fixes. No DOM/I/O. */
export const ALGORITHM = 'kolos-v4-text/1';
export const MAX_EVENTS = 5000;
export type Action =
  | { kind: 'move'; x: number; y: number }
  | { kind: 'check'; object: string }
  | { kind: 'click'; object: string }
  | { kind: 'key'; value: string };
export interface Point { id: number; name: string; type: 'in' | 'REAC' | 'ACTION'; signal: number }
export interface Link { id: number; from: number; to: number }
export interface PathItem { nodeId: number; edgeId: number }
export interface Runtime {
  activeId: number; nextNodeId: number; nextEdgeId: number; online: number[];
  path: PathItem[]; blocked: number[]; memory: string; answer: string;
  status: string; terminal: boolean;
}
export interface State { nodes: Point[]; edges: Link[]; runtime: Runtime }
export type Command =
  | { kind: 'input'; value: string }
  | { kind: 'action'; action: Action }
  | { kind: 'continue' | 'positive' | 'negative' | 'reset' };
export interface NodeChange { before: Point | null; after: Point }
export interface Trace {
  step: number; command: Command; kind: string; from: number; to: number;
  usedEdgeId: number | null; edge: Link | null; action: Action | null; changes: NodeChange[];
  before: Runtime; after: Runtime; explanation: string;
  rejected: { edgeId: number; reason: string }[];
}
export const clone = <T>(value: T): T => structuredClone(value);
export function initialState(): State {
  return { nodes: [
    { id: 1, name: 'poz', type: 'REAC', signal: 0 },
    { id: 2, name: 'neg', type: 'REAC', signal: 0 },
    { id: 3, name: 'ney', type: 'REAC', signal: 1 }
  ], edges: [], runtime: { activeId: 3, nextNodeId: 4, nextEdgeId: 4,
    online: [], path: [], blocked: [], memory: '', answer: '',
    status: 'Готов к вводу', terminal: false } };
}
export function visibleName(name: string): string {
  return name === ' ' ? '␣' : name === '\n' ? '↵' : name === '\t' ? '⇥' : name;
}
export function actionToken(action: Action): string {
  if (action.kind === 'move') return `@move:${Math.round(action.x)}:${Math.round(action.y)}`;
  if (action.kind === 'check') return `@check:${encodeURIComponent(action.object)}`;
  if (action.kind === 'click') return `@click:${encodeURIComponent(action.object)}`;
  return `@key:${encodeURIComponent(action.value)}`;
}
export function parseActionToken(name: string): Action | null {
  if (name.startsWith('@move:')) {
    const parts = name.split(':');
    const x = Number(parts[1]), y = Number(parts[2]);
    return Number.isFinite(x) && Number.isFinite(y) ? { kind: 'move', x, y } : null;
  }
  for (const kind of ['check', 'click', 'key'] as const) {
    const prefix = `@${kind}:`;
    if (name.startsWith(prefix)) {
      try {
        const value = decodeURIComponent(name.slice(prefix.length));
        return kind === 'key' ? { kind, value } : { kind, object: value };
      } catch { return null; }
    }
  }
  return null;
}
export function actionTitle(action: Action): string {
  if (action.kind === 'move') return `POS ${Math.round(action.x)}×${Math.round(action.y)}`;
  if (action.kind === 'check') return `${action.object}?`;
  if (action.kind === 'click') return `click ${action.object}`;
  return `⌨ ${visibleName(action.value)}`;
}
export function pointTitle(point: Point): string {
  if (point.type === 'REAC') return ({ poz: 'Успех', neg: 'Ошибка', ney: 'Старт' }[point.name] || point.name);
  if (point.type === 'ACTION') {
    const action = parseActionToken(point.name);
    return action ? actionTitle(action) : point.name;
  }
  return visibleName(point.name);
}
function maxPoint(state: State): Point {
  // Stable tie-break: lowest ID. SQLite's unordered fetchone was ambiguous.
  return state.nodes.reduce((a, b) => b.signal > a.signal || (b.signal === a.signal && b.id < a.id) ? b : a);
}
function refreshOnline(state: State, nodeId: number): void {
  const available = state.edges.filter(e => e.from === nodeId).map(e => e.id).sort((a, b) => a - b);
  const continued: number[] = [];
  for (const prior of state.runtime.online) {
    const index = available.indexOf(prior + 1);
    if (index >= 0) continued.push(...available.splice(index, 1));
  }
  state.runtime.online = [...continued, ...available];
}
function changeSignal(state: State, event: Trace, point: Point, signal: number): void {
  const existing = event.changes.find(c => c.after.id === point.id);
  if (existing) { point.signal = signal; existing.after = clone(point); return; }
  const before = clone(point); point.signal = signal;
  event.changes.push({ before, after: clone(point) });
}
function recordLink(state: State, event: Trace, from: number, to: number): void {
  const edge = { id: state.runtime.nextEdgeId++, from, to };
  state.edges.push(edge); event.edge = clone(edge);
}
function activate(state: State, event: Trace, name: string, type: Point['type'] = 'in'): Point {
  const previous = maxPoint(state);
  const signal = previous.signal + 1;
  let point = state.nodes.find(n => n.name === name && n.type === type);
  if (!point) {
    if (state.nodes.length >= 1000) throw new Error('Лимит эксперимента: 1000 точек. Сохраните его и начните новый.');
    point = { id: state.runtime.nextNodeId++, name, type, signal };
    state.nodes.push(point); event.changes.push({ before: null, after: clone(point) });
  } else changeSignal(state, event, point, signal);
  event.from = previous.id; event.to = point.id;
  recordLink(state, event, previous.id, point.id);
  state.runtime.activeId = point.id;
  refreshOnline(state, point.id);
  return point;
}
function clearAttempt(state: State): void {
  Object.assign(state.runtime, { online: [], path: [], blocked: [], memory: '', answer: '', terminal: false });
}
function findPath(state: State, event: Trace): PathItem[] {
  const byId = new Map(state.edges.map(e => [e.id, e]));
  const nodes = new Map(state.nodes.map(n => [n.id, n]));
  // Candidate ordering is the online_svyaz ordering, not shortest-path ranking.
  for (const candidate of state.runtime.online) {
    const path: PathItem[] = [];
    let current = state.runtime.activeId;
    let reason = 'У цепочки нет подтверждённого завершения';
    for (let offset = 0; offset < 256; offset++) {
      const edge = byId.get(candidate + offset);
      if (!edge || edge.from !== current) break;
      const target = nodes.get(edge.to)!;
      if (state.runtime.blocked.includes(target.id)) { reason = 'Точка отклонена в этой попытке'; break; }
      if (target.name === 'neg') { reason = 'Цепочка ведёт к отрицательной реакции'; break; }
      path.push({ nodeId: target.id, edgeId: edge.id });
      if (target.name === 'poz' || target.name === 'ney') return path;
      current = edge.to;
      if (offset === 255) reason = 'Достигнут предел: 256 переходов';
    }
    event.rejected.push({ edgeId: candidate, reason });
  }
  return [];
}
export function applyTrace(state: State, event: Trace): void {
  for (const change of event.changes) {
    const index = state.nodes.findIndex(n => n.id === change.after.id);
    if (index < 0) state.nodes.push(clone(change.after));
    else state.nodes[index] = clone(change.after);
  }
  if (event.edge) state.edges.push(clone(event.edge));
  state.runtime = clone(event.after);
}
export class Engine {
  state: State;
  events: Trace[] = [];
  constructor() { this.state = initialState(); }
  /** Preview is pure relative to live state: an animation cannot run ahead of memory. */
  preview(command: Command): Trace {
    if (this.events.length >= MAX_EVENTS) throw new Error('Лимит 5000 шагов. Экспортируйте эксперимент и начните новый.');
    const state = clone(this.state);
    const event: Trace = { step: this.events.length + 1, command: clone(command), kind: command.kind,
      from: state.runtime.activeId, to: state.runtime.activeId, usedEdgeId: null,
      edge: null, action: null, changes: [], before: clone(state.runtime), after: clone(state.runtime), explanation: '', rejected: [] };
    if (command.kind === 'input') {
      if (typeof command.value !== 'string' || Array.from(command.value).length !== 1) throw new Error('Один шаг ввода должен содержать один символ Unicode.');
      if (state.runtime.terminal) { clearAttempt(state); }
      state.runtime.path = [];
      const point = activate(state, event, command.value);
      state.runtime.memory += command.value;
      state.runtime.status = 'Символ записан';
      const change = event.changes.find(c => c.after.id === point.id)!;
      event.explanation = `${change.before ? 'Найдена существующая' : 'Создана новая'} точка «${visibleName(point.name)}» №${point.id}. ` +
        `Сигнал ${change.before?.signal ?? 0} → ${point.signal}. Записана связь №${event.edge!.id}: ${event.from} → ${event.to}.`;
    } else if (command.kind === 'action') {
      if (state.runtime.terminal) clearAttempt(state);
      state.runtime.path = [];
      const token = actionToken(command.action);
      const point = activate(state, event, token, 'ACTION');
      event.action = clone(command.action);
      state.runtime.status = 'Действие демонстрации записано';
      const change = event.changes.find(c => c.after.id === point.id)!;
      event.explanation = `${change.before ? 'Найдена существующая' : 'Создана новая'} точка действия «${actionTitle(command.action)}» №${point.id}. ` +
        `Сигнал ${change.before?.signal ?? 0} → ${point.signal}. Записана связь №${event.edge!.id}: ${event.from} → ${event.to}.`;
    } else if (command.kind === 'reset') {
      activate(state, event, 'ney', 'REAC'); clearAttempt(state);
      state.runtime.status = 'Новая попытка';
      event.explanation = 'Состояние переведено на нейтральную точку. Граф сохранён; кандидаты, ответ и краткосрочная память очищены.';
    } else if (command.kind === 'positive') {
      activate(state, event, 'poz', 'REAC');
      Object.assign(state.runtime, { path: [], online: [], memory: '', terminal: true, status: 'Успех записан' });
      event.explanation = `Записана положительная реакция по связи №${event.edge!.id}. Эта цепочка доступна для продолжения.`;
    } else if (command.kind === 'negative') {
      const point = maxPoint(state);
      if (point.type === 'REAC') {
        event.explanation = 'Нет действия для отклонения. Сначала введите текст или выполните продолжение.';
        state.runtime.status = 'Нет действия для оценки';
      } else {
        recordLink(state, event, point.id, 2); event.to = 2;
        state.runtime.blocked = [...new Set([...state.runtime.blocked, point.id])];
        changeSignal(state, event, point, 0);
        state.runtime.activeId = maxPoint(state).id;
        state.runtime.path = []; state.runtime.terminal = false;
        refreshOnline(state, state.runtime.activeId);
        state.runtime.status = 'Действие отклонено';
        event.explanation = `Связь №${event.edge!.id} отмечает ошибку. Сигнал точки №${point.id} обнулён. ` +
          `Состояние возвращено к максимуму: точка №${state.runtime.activeId}. Откат — не переход по выдуманной связи.`;
      }
    } else {
      if (!state.runtime.memory || state.runtime.terminal) {
        state.runtime.status = 'Сначала введите начало цепочки';
        event.explanation = 'Продолжать нечего. Начните новую попытку и введите знакомый префикс.';
      } else {
        if (!state.runtime.path.length) state.runtime.path = findPath(state, event);
        const next = state.runtime.path.shift();
        if (!next) {
          state.runtime.status = 'Продолжение не найдено'; state.runtime.terminal = true;
          event.explanation = 'Нет непрерывной цепочки ID + 1 до положительной или нейтральной реакции. Ничего не добавлено к графу.';
        } else {
          const target = state.nodes.find(n => n.id === next.nodeId)!;
          event.usedEdgeId = next.edgeId;
          event.action = target.type === 'ACTION' ? parseActionToken(target.name) : null;
          activate(state, event, target.name, target.type);
          const reaction = target.type === 'REAC';
          if (reaction) {
            Object.assign(state.runtime, { path: [], online: [], memory: '', terminal: true,
              status: target.name === 'poz' ? 'Цепочка завершена успешно' : 'Достигнута нейтральная реакция' });
            event.kind = 'complete';
          } else if (target.type === 'ACTION') {
            state.runtime.status = event.action ? `Действие по памяти: ${actionTitle(event.action)}` : 'Действие по памяти';
          } else {
            state.runtime.answer += target.name;
            state.runtime.status = 'Продолжение по памяти';
          }
          event.explanation = `Продолжение выбрано по старой связи №${next.edgeId}. ` +
            `Текущий переход записан новой связью №${event.edge!.id}. ` +
            (reaction ? 'Достигнута реакция; выполнение остановлено.' :
              event.action ? `Подготовлено действие «${actionTitle(event.action)}».` :
              `Ответ дополнен символом «${visibleName(target.name)}».`);
        }
      }
    }
    event.after = clone(state.runtime);
    return event;
  }
  commit(event: Trace): void {
    if (event.step !== this.events.length + 1 || JSON.stringify(event.before) !== JSON.stringify(this.state.runtime))
      throw new Error('Состояние изменилось: предварительный шаг устарел.');
    applyTrace(this.state, event); this.events.push(clone(event));
  }
  execute(command: Command): Trace { const e = this.preview(command); this.commit(e); return e; }
  at(step: number): State {
    const state = initialState();
    for (const event of this.events.slice(0, Math.max(0, step))) applyTrace(state, event);
    return state;
  }
}
export interface Experiment {
  schema: 'kolos-graph-lab/1'; algorithm: string;
  commands: Command[];
  view: { seconds: number; positions: Record<string, { x: number; y: number }>; input: string; simulator?: unknown };
  pending: Command[];
}
export function exportExperiment(engine: Engine, view: Experiment['view'], pending: Command[] = []): Experiment {
  return { schema: 'kolos-graph-lab/1', algorithm: ALGORITHM,
    commands: engine.events.map(e => clone(e.command)), view: clone(view), pending: clone(pending) };
}
function validateAction(value: unknown): Action {
  if (!value || typeof value !== 'object') throw new Error('Некорректное действие в файле.');
  const v = value as Record<string, unknown>;
  if (v.kind === 'move') {
    const x = Number(v.x), y = Number(v.y);
    if (Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1000 && y >= 0 && y <= 600)
      return { kind: 'move', x: Math.round(x), y: Math.round(y) };
  }
  if ((v.kind === 'check' || v.kind === 'click') && typeof v.object === 'string' && v.object.length > 0 && v.object.length <= 40)
    return { kind: v.kind, object: v.object };
  if (v.kind === 'key' && typeof v.value === 'string' && Array.from(v.value).length === 1)
    return { kind: 'key', value: v.value };
  throw new Error('Неизвестное или некорректное действие.');
}
function validateCommand(value: unknown): Command {
  if (!value || typeof value !== 'object') throw new Error('Некорректная команда в файле.');
  const v = value as Record<string, unknown>;
  if (v.kind === 'input' && typeof v.value === 'string' && Array.from(v.value).length === 1)
    return { kind: 'input', value: v.value };
  if (v.kind === 'action') return { kind: 'action', action: validateAction(v.action) };
  if (v.kind === 'continue' || v.kind === 'positive' || v.kind === 'negative' || v.kind === 'reset') return { kind: v.kind };
  throw new Error('Неизвестная команда или некорректный символ.');
}
/** Recompute every event rather than trusting imported graph IDs, HTML or deltas. */
export function importExperiment(raw: unknown): { engine: Engine; view: Experiment['view']; pending: Command[] } {
  const data = raw as Partial<Experiment> | null;
  if (!data || data.schema !== 'kolos-graph-lab/1' || data.algorithm !== ALGORITHM)
    throw new Error('Формат не поддерживается. Нужен JSON-эксперимент Kolos Graph Lab v1, не SQLite.');
  if (!Array.isArray(data.commands) || data.commands.length > MAX_EVENTS || !Array.isArray(data.pending) || data.pending.length > 2000)
    throw new Error('Некорректный или слишком большой журнал.');
  const engine = new Engine();
  for (const item of data.commands) engine.execute(validateCommand(item));
  const seconds = Number(data.view?.seconds);
  if (!Number.isFinite(seconds) || seconds < 0.25 || seconds > 5) throw new Error('Скорость должна быть от 0,25 до 5 секунд.');
  const positions: Experiment['view']['positions'] = {};
  const rawPositions = data.view?.positions;
  if (!rawPositions || typeof rawPositions !== 'object' || Object.keys(rawPositions).length > 1000) throw new Error('Некорректные координаты графа.');
  for (const [id, p] of Object.entries(rawPositions)) {
    if (!/^\d+$/.test(id) || !p || !Number.isFinite(p.x) || !Number.isFinite(p.y) || Math.abs(p.x) > 100000 || Math.abs(p.y) > 100000)
      throw new Error('Некорректные координаты точки.');
    positions[id] = { x: p.x, y: p.y };
  }
  const input = data.view?.input;
  if (typeof input !== 'string' || Array.from(input).length > 2000) throw new Error('Слишком длинный ввод.');
  return { engine, view: { seconds, positions, input, simulator: data.view?.simulator }, pending: data.pending.map(validateCommand) };
}
