/**
 * core/floatingPanels.js — Zustand slice for floating panel workspace
 *
 * State shape:
 *   openPanels: Array<{
 *     id,          // leaf id from PANEL_TREE
 *     label,       // display title
 *     component,   // React component
 *     x, y,        // position (px from workspace top-left)
 *     w, h,        // size (px)
 *     minimized,   // bool — collapsed to title bar only
 *     zIndex,      // stacking order
 *   }>
 *
 * Rules:
 *   - Opening an already-open panel focuses it (brings to front) instead of duplicating
 *   - zIndex is managed as a monotonically increasing counter
 *   - Default spawn position staggers by open count to avoid full overlap
 */

const DEFAULT_W = 480;
const DEFAULT_H = 360;
const STAGGER   = 28;

// Per-panel default sizes [w, h] in px — unlisted panels use DEFAULT_W x DEFAULT_H
const PANEL_SIZES = {
  'campus-map':         [1000, 600],
  'stt':                [420, 300],
  'wakeword':           [340, 180],
  'tts':                [420, 320],
  'state-monitor':      [340, 310],
  'event-log':          [520, 400],
  'face-display':       [400, 420],
  'face-palette':       [280, 300],
  'conversation':       [680, 480],
  'cube-3d':            [520, 480],
  'cube-rotation':      [400, 220],
  'cube-pieces':        [400, 380],
  'menu-parser':        [480, 360],
  'index-builder':      [300, 400],
  'knowledge-docs':     [560, 420],
  'knowledge-building': [480, 400],
  'sys-connection':     [360, 220],
  'sys-topics':         [700, 460],
  'sys-metrics':        [360, 340],
  'vision-test':        [480, 460],
  'llm-inject':         [420, 250],
};

let zCounter = 10;
function nextZ() { return ++zCounter; }

function defaultPosition(count) {
  const base = 60;
  const offset = (count % 8) * STAGGER;
  return { x: base + offset, y: base + offset };
}

function defaultSize(id) {
  const [w, h] = PANEL_SIZES[id] ?? [DEFAULT_W, DEFAULT_H];
  if (id === 'campus-map' && typeof window !== 'undefined') {
    return { w: Math.max(320, Math.min(w, window.innerWidth - 300)),
      h: Math.max(300, Math.min(h, window.innerHeight - 140)) };
  }
  return { w, h };
}

export const floatingPanelsSlice = (set, get) => ({
  openPanels: [],

  // Open a panel by leaf node — focus if already open
  openPanel: (leaf) => {
    const panels = get().openPanels;
    const existing = panels.find(p => p.id === leaf.id);

    if (existing) {
      // Already open — just bring to front and un-minimize
      set({
        openPanels: panels.map(p =>
          p.id === leaf.id
            ? { ...p, minimized: false, zIndex: nextZ() }
            : p
        ),
      });
      return;
    }

    const { x, y } = defaultPosition(panels.length);
    const { w, h } = defaultSize(leaf.id);
    set({
      openPanels: [
        ...panels,
        {
          id:        leaf.id,
          label:     leaf.label,
          component: leaf.component,
          x, y,
          w, h,
          minimized: false,
          zIndex:    nextZ(),
        },
      ],
    });
  },

  // Close a panel by id
  closePanel: (id) => {
    set({ openPanels: get().openPanels.filter(p => p.id !== id) });
  },

  // Toggle minimize
  minimizePanel: (id) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, minimized: !p.minimized, zIndex: nextZ() } : p
      ),
    });
  },

  // Bring panel to front
  focusPanel: (id) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, zIndex: nextZ() } : p
      ),
    });
  },

  // Update position after drag
  movePanelTo: (id, x, y) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, x, y } : p
      ),
    });
  },

  // Update size after resize
  resizePanel: (id, w, h) => {
    set({
      openPanels: get().openPanels.map(p =>
        p.id === id ? { ...p, w, h } : p
      ),
    });
  },
});
