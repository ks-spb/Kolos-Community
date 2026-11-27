import type { Command } from './engine.js';

export interface VirtualObject {
  id: string;
  name: string;
  x: number;
  y: number;
  visible: boolean;
}
export interface VirtualCursor { x: number; y: number }
export interface VirtualScreenSnapshot {
  objects: VirtualObject[];
  cursor: VirtualCursor;
  selectedId: string | null;
  activeApp: string;
  display: string;
  shuffleStep: number;
}

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value));

export function defaultVirtualScreen(): VirtualScreenSnapshot {
  return {
    objects: [
      { id: 'obj-1', name: 'DOC', x: 180, y: 150, visible: true },
      { id: 'obj-2', name: 'CALC', x: 500, y: 150, visible: true },
      { id: 'obj-3', name: 'SET', x: 820, y: 150, visible: true },
      { id: 'obj-4', name: 'MAIL', x: 340, y: 390, visible: true },
    ],
    cursor: { x: 500, y: 300 },
    selectedId: null,
    activeApp: '',
    display: '',
    shuffleStep: 0,
  };
}

export function cloneVirtualScreen(value: VirtualScreenSnapshot): VirtualScreenSnapshot {
  return structuredClone(value);
}

export function normalizeObjectName(name: string): string {
  return name.trim().replace(/\s+/g, ' ').slice(0, 40);
}

export function objectAtCursor(screen: VirtualScreenSnapshot): VirtualObject | null {
  const visible = screen.objects.filter(object => object.visible);
  let winner: VirtualObject | null = null;
  let best = Infinity;
  for (const object of visible) {
    const dx = Math.abs(object.x - screen.cursor.x);
    const dy = Math.abs(object.y - screen.cursor.y);
    if (dx <= 82 && dy <= 48) {
      const score = dx * dx + dy * dy;
      if (score < best) { winner = object; best = score; }
    }
  }
  return winner;
}

export function findVirtualObject(screen: VirtualScreenSnapshot, name: string): VirtualObject | null {
  const normalized = normalizeObjectName(name).toLocaleLowerCase();
  return screen.objects.find(object => object.visible && object.name.toLocaleLowerCase() === normalized) || null;
}

export function selectVirtualObject(screen: VirtualScreenSnapshot, id: string | null): void {
  screen.selectedId = id && screen.objects.some(object => object.id === id) ? id : null;
}

export function moveVirtualObject(screen: VirtualScreenSnapshot, id: string, x: number, y: number): void {
  const object = screen.objects.find(item => item.id === id);
  if (!object) return;
  object.x = Math.round(clamp(x, 85, 915));
  object.y = Math.round(clamp(y, 55, 545));
  screen.selectedId = id;
}

export function addVirtualObject(screen: VirtualScreenSnapshot, name: string): VirtualObject {
  const normalized = normalizeObjectName(name);
  if (!normalized) throw new Error('Введите имя объекта.');
  if (screen.objects.some(object => object.name.toLocaleLowerCase() === normalized.toLocaleLowerCase()))
    throw new Error('Объект с таким именем уже есть.');
  if (screen.objects.length >= 24) throw new Error('На виртуальном экране допускается не более 24 объектов.');
  const next = Math.max(0, ...screen.objects.map(object => Number(object.id.replace(/\D/g, '')) || 0)) + 1;
  const index = screen.objects.length;
  const object: VirtualObject = {
    id: `obj-${next}`,
    name: normalized,
    x: 180 + (index % 3) * 320,
    y: 150 + (Math.floor(index / 3) % 3) * 180,
    visible: true,
  };
  screen.objects.push(object);
  screen.selectedId = object.id;
  return object;
}

export function hideSelectedVirtualObject(screen: VirtualScreenSnapshot): VirtualObject | null {
  const object = screen.objects.find(item => item.id === screen.selectedId) || null;
  if (!object) return null;
  object.visible = false;
  screen.selectedId = null;
  return object;
}

export function showAllVirtualObjects(screen: VirtualScreenSnapshot): void {
  for (const object of screen.objects) object.visible = true;
}

export function shuffleVirtualObjects(screen: VirtualScreenSnapshot): void {
  const slots = [
    { x: 180, y: 150 }, { x: 500, y: 150 }, { x: 820, y: 150 },
    { x: 180, y: 390 }, { x: 500, y: 390 }, { x: 820, y: 390 },
    { x: 340, y: 270 }, { x: 660, y: 270 },
  ];
  screen.shuffleStep = (screen.shuffleStep + 1) % slots.length;
  const visible = screen.objects.filter(object => object.visible);
  visible.forEach((object, index) => {
    const slot = slots[(index + screen.shuffleStep) % slots.length];
    object.x = slot.x; object.y = slot.y;
  });
}

export function resetVirtualRuntime(screen: VirtualScreenSnapshot): void {
  screen.cursor = { x: 500, y: 300 };
  screen.activeApp = '';
  screen.display = '';
  screen.selectedId = null;
}

export function commandsForObjectClick(object: VirtualObject): Command[] {
  return [
    { kind: 'action', action: { kind: 'move', x: object.x, y: object.y } },
    { kind: 'action', action: { kind: 'check', object: object.name } },
    { kind: 'action', action: { kind: 'click', object: object.name } },
  ];
}

export function commandForKey(value: string): Command {
  if (Array.from(value).length !== 1) throw new Error('Записывается по одной клавише.');
  return { kind: 'action', action: { kind: 'key', value } };
}

export function validateVirtualScreen(raw: unknown): VirtualScreenSnapshot {
  if (!raw || typeof raw !== 'object') return defaultVirtualScreen();
  const value = raw as Record<string, unknown>;
  if (!Array.isArray(value.objects) || value.objects.length > 24) throw new Error('Некорректный виртуальный экран.');
  const ids = new Set<string>(), names = new Set<string>();
  const objects = value.objects.map((item, index) => {
    if (!item || typeof item !== 'object') throw new Error('Некорректный объект виртуального экрана.');
    const object = item as Record<string, unknown>;
    const id = typeof object.id === 'string' ? object.id : `obj-${index + 1}`;
    const name = typeof object.name === 'string' ? normalizeObjectName(object.name) : '';
    const x = Number(object.x), y = Number(object.y);
    if (!id || ids.has(id) || !name || names.has(name.toLocaleLowerCase()) ||
        !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1000 || y < 0 || y > 600 ||
        typeof object.visible !== 'boolean') throw new Error('Некорректные данные объекта виртуального экрана.');
    ids.add(id); names.add(name.toLocaleLowerCase());
    return { id, name, x: Math.round(x), y: Math.round(y), visible: object.visible };
  });
  const cursorRaw = value.cursor as Record<string, unknown> | null;
  const cursor = {
    x: clamp(Number(cursorRaw?.x) || 500, 0, 1000),
    y: clamp(Number(cursorRaw?.y) || 300, 0, 600),
  };
  const selectedId = typeof value.selectedId === 'string' && ids.has(value.selectedId) ? value.selectedId : null;
  const activeApp = typeof value.activeApp === 'string' ? value.activeApp.slice(0, 40) : '';
  const display = typeof value.display === 'string' ? value.display.slice(0, 200) : '';
  const shuffleStep = Number.isInteger(value.shuffleStep) ? clamp(Number(value.shuffleStep), 0, 10000) : 0;
  return { objects, cursor, selectedId, activeApp, display, shuffleStep };
}
