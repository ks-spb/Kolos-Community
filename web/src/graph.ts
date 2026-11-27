import { pointTitle, visibleName } from './engine.js';
import type { State, Trace, Point } from './engine.js';
export type Positions = Record<string, { x: number; y: number }>;
export type Selection = { kind: 'node'; id: number } | { kind: 'edge'; from: number; to: number } | null;
const SVG_NS = 'http://www.w3.org/2000/svg';
export const escapeHTML = (v: unknown): string => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
export class GraphView {
  positions: Positions = {};
  selected: Selection = null;
  neighborhood = false;
  query = '';
  camera = { x: 0, y: 0, zoom: 1 };
  private state: State | null = null;
  private event: Trace | null = null;
  private world: SVGGElement;
  private pulse: SVGCircleElement;
  private pulseLabel: SVGTextElement;
  private resize: ResizeObserver;
  private drag: { nodeId: number | null; x: number; y: number; moved: boolean } | null = null;
  onSelect: (selection: Selection) => void = () => {};
  onMove: () => void = () => {};
  constructor(readonly svg: SVGSVGElement) {
    svg.innerHTML = `<defs>
      <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#243033"/></pattern>
      <filter id="glow" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#66807d"/></marker>
      <marker id="active-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#baf28a"/></marker>
    </defs><rect width="100%" height="100%" fill="url(#dots)"/><g id="world"></g>`;
    this.world = svg.querySelector('#world')!;
    this.pulse = document.createElementNS(SVG_NS, 'circle');
    this.pulse.setAttribute('r', '5'); this.pulse.setAttribute('class', 'pulse');
    this.pulseLabel = document.createElementNS(SVG_NS, 'text');
    this.pulseLabel.setAttribute('class', 'pulse-caption');
    this.resize = new ResizeObserver(() => this.transform()); this.resize.observe(svg);
    svg.addEventListener('wheel', e => { e.preventDefault(); this.zoom(e.deltaY < 0 ? 1.12 : 0.89); }, { passive: false });
    svg.addEventListener('dblclick', e => { if (!(e.target as Element).closest('[data-node]')) this.fit(); });
    svg.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      const node = (e.target as Element).closest<SVGGElement>('[data-node]');
      const edge = (e.target as Element).closest<SVGGElement>('[data-edge]');
      if (node) { this.selected = { kind: 'node', id: Number(node.dataset.node) }; this.onSelect(this.selected); }
      else if (edge) { const [from, to] = edge.dataset.edge!.split(':').map(Number); this.selected = { kind: 'edge', from, to }; this.onSelect(this.selected); }
      this.drag = { nodeId: node ? Number(node.dataset.node) : null, x: e.clientX, y: e.clientY, moved: false };
      svg.setPointerCapture(e.pointerId);
    });
    svg.addEventListener('pointermove', e => {
      if (!this.drag) return;
      const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) this.drag.moved = true;
      if (this.drag.nodeId !== null) {
        const p = this.positions[this.drag.nodeId]; p.x += dx / this.camera.zoom; p.y += dy / this.camera.zoom;
        if (this.state) this.render(this.state, this.event);
      } else { this.camera.x += dx; this.camera.y += dy; this.transform(); }
      this.drag.x = e.clientX; this.drag.y = e.clientY;
    });
    const end = () => { if (this.drag?.moved) this.onMove(); this.drag = null; };
    svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);
    svg.addEventListener('keydown', e => {
      const el = (e.target as Element).closest<SVGGElement>('[data-node]');
      if (el && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault(); this.selected = { kind: 'node', id: Number(el.dataset.node) }; this.onSelect(this.selected);
      }
    });
  }
  private position(point: Point): { x: number; y: number } {
    if (!this.positions[point.id]) {
      const preset: Record<number, { x: number; y: number }> = {
        3: { x: -415, y: 20 }, 1: { x: 340, y: -205 }, 2: { x: 340, y: 225 },
        4: { x: -195, y: 20 }, 5: { x: 10, y: -75 }, 6: { x: 220, y: 35 },
        7: { x: -145, y: 235 }, 8: { x: -260, y: -205 }, 9: { x: 30, y: -290 }
      };
      const i = point.id - 4, angle = i * 2.399963;
      this.positions[point.id] = preset[point.id] || { x: Math.cos(angle) * Math.sqrt(i + 1) * 150, y: Math.sin(angle) * Math.sqrt(i + 1) * 125 };
    }
    return this.positions[point.id];
  }
  private curve(from: number, to: number, reverse: boolean): { d: string; x: number; y: number } {
    const a = this.positions[from], b = this.positions[to];
    if (from === to) return { d: `M ${a.x - 20} ${a.y - 26} C ${a.x - 110} ${a.y - 150}, ${a.x + 110} ${a.y - 150}, ${a.x + 22} ${a.y - 29}`, x: a.x, y: a.y - 125 };
    const dx = b.x - a.x, dy = b.y - a.y, length = Math.max(1, Math.hypot(dx, dy));
    const nx = dx / length, ny = dy / length;
    const bend = reverse ? 54 : -14;
    const x1 = a.x + nx * 35, y1 = a.y + ny * 35, x2 = b.x - nx * 42, y2 = b.y - ny * 42;
    const cx = (x1 + x2) / 2 - ny * bend, cy = (y1 + y2) / 2 + nx * bend;
    return { d: `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`, x: (x1 + 2 * cx + x2) / 4, y: (y1 + 2 * cy + y2) / 4 - 10 };
  }
  render(state: State, event: Trace | null = null): void {
    this.state = state; this.event = event;
    const nodes = state.nodes.map(p => ({ ...p }));
    if (event) for (const c of event.changes) if (!c.before) nodes.push({ ...c.after, signal: 0 });
    for (const p of nodes) this.position(p);
    const allEdges = [...state.edges]; if (event?.edge) allEdges.push(event.edge);
    const groups = new Map<string, { from: number; to: number; ids: number[] }>();
    for (const e of allEdges) {
      const key = `${e.from}:${e.to}`;
      if (!groups.has(key)) groups.set(key, { from: e.from, to: e.to, ids: [] });
      groups.get(key)!.ids.push(e.id);
    }
    const anchor = this.selected?.kind === 'node' ? this.selected.id : state.runtime.activeId;
    const visible = new Set<number>();
    if (this.neighborhood) {
      visible.add(anchor);
      for (const e of allEdges) if (e.from === anchor || e.to === anchor) { visible.add(e.from); visible.add(e.to); }
      if (event) { visible.add(event.from); visible.add(event.to); }
    } else nodes.forEach(n => visible.add(n.id));
    const activeKey = event?.edge ? `${event.edge.from}:${event.edge.to}` : null;
    const plannedIds = new Set(state.runtime.path.map(p => p.edgeId));
    const edgeHTML = Array.from(groups, ([key, group]) => {
      if (!visible.has(group.from) || !visible.has(group.to)) return '';
      const curve = this.curve(group.from, group.to, groups.has(`${group.to}:${group.from}`));
      const selected = this.selected?.kind === 'edge' && this.selected.from === group.from && this.selected.to === group.to;
      const active = key === activeKey;
      const planned = group.ids.some(id => plannedIds.has(id));
      const ids = group.ids.slice(0, 12);
      const chunks: string[] = []; for (let i = 0; i < ids.length; i += 6) chunks.push(ids.slice(i, i + 6).join(', '));
      if (group.ids.length > 12) chunks.push(`ещё ${group.ids.length - 12} · нажмите`);
      return `<g data-edge="${key}" class="edge-group ${selected ? 'selected' : ''}"><title>${escapeHTML(`Связи ${group.ids.join(', ')}: ${group.from} → ${group.to}`)}</title>
        <path d="${curve.d}" class="edge-hit"/>
        <path id="edge-${key.replace(':', '-')}" d="${curve.d}" class="edge ${active ? 'active-edge' : ''} ${planned ? 'planned' : ''}" marker-end="url(#${active ? 'active-arrow' : 'arrow'})"/>
        <text class="edge-label" x="${curve.x}" y="${curve.y}">${chunks.map((c, i) => `<tspan x="${curve.x}" dy="${i ? 16 : 0}">${escapeHTML(c)}</tspan>`).join('')}</text></g>`;
    }).join('');
    const nodeHTML = nodes.filter(n => visible.has(n.id)).map(point => {
      const p = this.position(point), active = point.id === state.runtime.activeId;
      const selected = this.selected?.kind === 'node' && this.selected.id === point.id;
      const pending = !!event?.changes.some(c => !c.before && c.after.id === point.id);
      const match = !this.query || `${point.id} ${point.name} ${pointTitle(point)}`.toLowerCase().includes(this.query.toLowerCase());
      const label = point.type === 'REAC' ? point.name : pointTitle(point);
      return `<g data-node="${point.id}" tabindex="0" role="button" aria-label="${escapeHTML(`Точка ${point.name}, номер ${point.id}, сигнал ${point.signal}`)}" transform="translate(${p.x},${p.y})" class="node ${active ? 'is-active' : ''} ${selected ? 'is-selected' : ''} ${pending ? 'is-pending' : ''} ${point.name === 'poz' ? 'is-positive' : point.name === 'neg' ? 'is-negative' : ''}" opacity="${match ? 1 : 0.2}">
        <title>${escapeHTML(`${point.name}\nID: ${point.id}\nСигнал: ${point.signal}`)}</title>
        <circle class="node-halo" r="44"/><circle class="node-ring" r="38"/><circle class="node-body" r="30"/>
        <text class="node-name ${point.type === 'REAC' ? 'reaction-name' : point.type === 'ACTION' ? 'action-name' : ''}" y="7">${escapeHTML(label)}</text>
        <text class="node-id" y="57">${point.type === 'REAC' ? escapeHTML(pointTitle(point)) + ' · ' : ''}#${point.id}</text>
        <rect class="signal-pill" x="-31" y="66" width="62" height="23" rx="6"/>
        <text class="node-signal" y="82">S ${point.signal}</text>
        ${active ? '<text class="active-caption" y="-56">ТЕКУЩАЯ</text>' : ''}
      </g>`;
    }).join('');
    this.world.innerHTML = edgeHTML + nodeHTML;
    this.world.append(this.pulse, this.pulseLabel);
    this.pulse.style.display = 'none'; this.pulseLabel.style.display = 'none';
    this.transform();
  }
  animate(event: Trace, progress: number): void {
    if (!event.edge) return;
    const path = this.world.querySelector<SVGPathElement>(`#edge-${event.edge.from}-${event.edge.to}`);
    if (!path) return;
    const p = path.getPointAtLength(path.getTotalLength() * Math.max(0, Math.min(1, progress)));
    this.pulse.style.display = ''; this.pulse.setAttribute('cx', String(p.x)); this.pulse.setAttribute('cy', String(p.y));
    this.pulseLabel.style.display = ''; this.pulseLabel.textContent = `№${event.usedEdgeId ?? event.edge.id}`;
    this.pulseLabel.setAttribute('x', String(p.x)); this.pulseLabel.setAttribute('y', String(p.y - 17));
  }
  private transform(): void {
    this.world.setAttribute('transform', `translate(${this.svg.clientWidth / 2 + this.camera.x},${this.svg.clientHeight / 2 + this.camera.y}) scale(${this.camera.zoom})`);
  }
  fit(): void {
    if (!this.state) return;
    const shown = Array.from(this.world.querySelectorAll<SVGGElement>('[data-node]')).map(n => this.positions[Number(n.dataset.node)]);
    if (!shown.length) return;
    const minX = Math.min(...shown.map(p => p.x)) - 80, maxX = Math.max(...shown.map(p => p.x)) + 80;
    const minY = Math.min(...shown.map(p => p.y)) - 145, maxY = Math.max(...shown.map(p => p.y)) + 110;
    this.camera.zoom = Math.min(1.25, (this.svg.clientWidth - 60) / (maxX - minX), (this.svg.clientHeight - 40) / (maxY - minY));
    this.camera.x = -(minX + maxX) / 2 * this.camera.zoom;
    this.camera.y = -(minY + maxY) / 2 * this.camera.zoom; this.transform();
  }
  zoom(multiplier: number): void { this.camera.zoom = Math.max(0.08, Math.min(3.5, this.camera.zoom * multiplier)); this.transform(); }
  focus(id: number): void {
    const p = this.positions[id]; if (!p) return;
    this.camera.x = -p.x * this.camera.zoom; this.camera.y = -p.y * this.camera.zoom; this.transform();
  }
}
