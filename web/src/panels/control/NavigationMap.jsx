import { useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch } from '../../core/api.js';
import { defaultView, fitMap, selectionPose, world, zoomAt } from './navigation/geometry.js';
import { drawMap } from './navigation/drawMap.js';

export default function NavigationMap({ state, online, tool, selected, onSelect, selectable }) {
  const canvas = useRef(null), drag = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState(defaultView);
  const [follow, setFollow] = useState(false);
  const [layers, setLayers] = useState({ scan: true, path: true, grid: true });
  const [pointer, setPointer] = useState(null);
  const [image, setImage] = useState(null);
  const [imageError, setImageError] = useState('');
  const [retry, setRetry] = useState(0);
  const mapKey = JSON.stringify(state?.map && { ...state.map, version: undefined });
  const map = useMemo(() => mapKey ? JSON.parse(mapKey) : null, [mapKey]);
  const version = state?.map?.version;

  useEffect(() => {
    const element = canvas.current;
    let fitted = false;
    const resize = () => {
      const rect = element.getBoundingClientRect();
      const next = { w: rect.width, h: rect.height };
      element.width = Math.round(next.w * (window.devicePixelRatio || 1));
      element.height = Math.round(next.h * (window.devicePixelRatio || 1));
      setSize(next);
      if (!fitted && map && next.w && next.h) { setView(fitMap(map, next)); fitted = true; }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    window.addEventListener('resize', resize);
    return () => { observer.disconnect(); window.removeEventListener('resize', resize); };
  }, [map]);

  useEffect(() => {
    if (version === undefined) return;
    let disposed = false, objectUrl, retryTimer;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    async function load() {
      try {
        const response = await apiFetch(`/navigation/api/map.png?v=${encodeURIComponent(version)}`, { signal: controller.signal });
        if (!response.ok) throw new Error(`지도 이미지 수신 실패 (${response.status})`);
        const blob = await response.blob();
        if (disposed) return;
        objectUrl = URL.createObjectURL(blob);
        const loaded = new Image();
        loaded.src = objectUrl;
        await loaded.decode();
        if (!disposed) { setImage({ element: loaded, version }); setImageError(''); }
      } catch (error) {
        if (!disposed) {
          setImageError(error.message);
          retryTimer = setTimeout(() => setRetry(value => value + 1), 1000);
        }
      } finally { clearTimeout(timeout); }
    }
    void load();
    return () => {
      disposed = true; controller.abort(); clearTimeout(timeout); clearTimeout(retryTimer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [version, retry]);

  const robotX = state?.robot?.[0], robotY = state?.robot?.[1];
  const actualView = useMemo(() => follow && robotX !== undefined
    ? { ...view, x: robotX, y: robotY } : view, [follow, robotX, robotY, view]);
  useEffect(() => {
    const element = canvas.current;
    const draw = () => {
      const css = getComputedStyle(element);
      const color = name => css.getPropertyValue(name).trim();
      drawMap(element, { state, view: actualView, size, mapImage: image?.element,
        imageVersion: image?.version, online, selected, tool, layers }, {
        grid: color('--border-default'), path: color('--color-ok'), localPath: color('--color-nav'),
        scan: color('--color-warn'), robotFill: color('--color-info-bg'),
        robotBorder: color('--color-info'), robot: color('--color-info'), text: color('--text-primary'),
      });
    };
    draw();
    const observer = new MutationObserver(draw);
    observer.observe(document.documentElement, { attributes: true });
    return () => observer.disconnect();
  }, [state, actualView, size, image, online, selected, tool, layers]);

  useEffect(() => {
    const element = canvas.current;
    const wheel = event => {
      event.preventDefault();
      const rect = element.getBoundingClientRect();
      setView(zoomAt([event.clientX - rect.left, event.clientY - rect.top], event.deltaY, actualView, size));
      setFollow(false);
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, [actualView, size]);

  const local = event => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };
  const metres = view.scale > 50 ? 1 : view.scale > 10 ? 5 : 10;
  return <div className="nav-map">
    <div className="nav-toolbar">
      <button onClick={() => { setView(map ? fitMap(map, size) : defaultView()); setFollow(false); }}>전체 지도</button>
      <button aria-pressed={follow} onClick={() => {
        setView(actualView); setFollow(!follow);
      }}>로봇 중심</button>
      <button onClick={() => { setView(defaultView()); setFollow(false); onSelect(null); }}>화면 초기화</button>
    </div>
    <div className="nav-viewport">
      <canvas ref={canvas} tabIndex={0} aria-label="지도, 로봇 위치와 라이다 스캔"
        className={tool !== 'pan' && selectable ? 'selecting' : ''}
        onPointerDown={event => {
          if (event.button !== 0) return;
          event.currentTarget.focus();
          const point = local(event);
          drag.current = { start: point, view: actualView, world: world(point, actualView, size), tool };
          event.currentTarget.setPointerCapture(event.pointerId);
          if (tool !== 'pan' && selectable) onSelect([...drag.current.world, 0]);
        }}
        onPointerMove={event => {
          const point = local(event), position = world(point, actualView, size);
          setPointer(position);
          const origin = drag.current;
          if (!origin || origin.tool !== tool) return;
          if (tool === 'pan') {
            setFollow(false);
            setView({ ...origin.view, x: origin.view.x - (point[0] - origin.start[0]) / origin.view.scale,
              y: origin.view.y + (point[1] - origin.start[1]) / origin.view.scale });
          } else if (selectable) onSelect(selectionPose(origin.world, position));
        }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
        onLostPointerCapture={() => { drag.current = null; }} />
      {!state?.map && !state?.robot && !state?.scan?.length && <div className="nav-empty">지도와 센서 데이터를 기다리는 중</div>}
      <div className="nav-map-legend"><span>● 로봇</span><span>· 라이다</span><span>━ 경로</span></div>
      <div className="nav-scale" style={{ width: metres * view.scale }}>{metres} m</div>
    </div>
    {imageError && <p className="nav-error" role="status">{imageError}</p>}
    <div className="nav-map-footer">
      <span>{pointer ? `x ${pointer[0].toFixed(2)} · y ${pointer[1].toFixed(2)}` : '드래그 이동 · 휠 확대/축소'}</span>
      <span>{state?.frame === 'laser' && '위치 추정 대기 · '}좌표계 {state?.frame || 'odom'} · m</span>
    </div>
    <div className="nav-toolbar">{Object.entries({ scan: '라이다', path: '계획 경로', grid: '격자' }).map(([key, label]) =>
      <label key={key}><input type="checkbox" checked={layers[key]} onChange={event => setLayers({ ...layers, [key]: event.target.checked })} />{label}</label>)}
      {selected && <span>선택 위치: {selected[0].toFixed(2)}, {selected[1].toFixed(2)} m</span>}
    </div>
  </div>;
}
