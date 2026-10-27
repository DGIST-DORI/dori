/**
 * hooks/useDraggable.js — Drag handler for floating panels
 *
 * Usage:
 *   const { onDragStart } = useDraggable({ x, y, onMove, onFocus });
 *   <div onMouseDown={onDragStart} onTouchStart={onDragStart} />
 *
 * - Works with both mouse and touch events
 * - Clamps position so panel never fully leaves viewport
 * - Calls onFocus() on drag start to bring panel to front
 */

import { useCallback, useRef } from 'react';

const MIN_VISIBLE = 40; // px — minimum title bar that must remain on-screen

export function useDraggable({ x, y, onMove, onFocus }) {
  const origin = useRef(null); // { mouseX, mouseY, panelX, panelY }

  const clamp = useCallback((nx, ny, el) => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const w  = el?.offsetWidth  ?? 200;

    const cx = Math.min(Math.max(nx, -(w - MIN_VISIBLE)), vw - MIN_VISIBLE);
    const cy = Math.min(Math.max(ny, 0), vh - MIN_VISIBLE);
    return { cx, cy };
  }, []);

  const onDragStart = useCallback((e) => {
    // Ignore right-click
    if (e.button !== undefined && e.button !== 0) return;

    onFocus?.();

    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;

    origin.current = { mouseX: clientX, mouseY: clientY, panelX: x, panelY: y };

    const el = e.currentTarget.closest('.fp-window');

    function onMove_(ev) {
      if (!origin.current) return;
      const cx_ = ev.touches ? ev.touches[0].clientX : ev.clientX;
      const cy_ = ev.touches ? ev.touches[0].clientY : ev.clientY;
      const dx = cx_ - origin.current.mouseX;
      const dy = cy_ - origin.current.mouseY;
      const nx = origin.current.panelX + dx;
      const ny = origin.current.panelY + dy;
      const { cx, cy } = clamp(nx, ny, el);
      onMove(cx, cy);
    }

    function onUp() {
      origin.current = null;
      window.removeEventListener('mousemove', onMove_);
      window.removeEventListener('mouseup',   onUp);
      window.removeEventListener('touchmove', onMove_);
      window.removeEventListener('touchend',  onUp);
    }

    window.addEventListener('mousemove', onMove_);
    window.addEventListener('mouseup',   onUp);
    window.addEventListener('touchmove', onMove_, { passive: false });
    window.addEventListener('touchend',  onUp);

    e.preventDefault();
  }, [x, y, clamp, onMove, onFocus]);

  return { onDragStart };
}
