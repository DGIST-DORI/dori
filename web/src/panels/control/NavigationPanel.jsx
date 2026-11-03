import { useRef, useState } from 'react';
import NavigationMap from './NavigationMap.jsx';
import NavigationStatus from './NavigationStatus.jsx';
import { useNavigation } from './navigation/useNavigation.js';
import { poseFromFields, sceneKey } from './navigation/geometry.js';
import './NavigationPanel.css';

function NavigationWorkspace({ navigation }) {
  const { state, online, canControl, clientId, command, error } = navigation;
  const [tool, setTool] = useState('pan');
  const [fields, setFields] = useState(['', '', '0']);
  const [destinationName, setDestinationName] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [notice, setNotice] = useState('지도에서 위치를 선택하고 드래그해 방향을 지정하세요.');
  const [commandError, setCommandError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const selected = poseFromFields(fields);
  const nav = online && state?.mode === 'navigation';
  const writable = nav && canControl;
  const otherOwner = !!state?.control_owner && state.control_owner !== clientId;
  const own = state?.control_owner === clientId;
  const ready = !state?.readiness?.length;
  const poseAllowed = writable && !otherOwner && !busy && (tool === 'initial_pose'
    ? !state?.values?.active : tool === 'goal' && own && state?.values?.enabled && ready);

  async function perform(action, extra) {
    if (pending.current && action !== 'stop') return null;
    if (action !== 'stop') { pending.current = true; setBusy(true); }
    setCommandError('');
    try {
      const result = await command(action, extra);
      if (result.message) setNotice(result.message);
      return result;
    } catch (err) { setCommandError(err.message); return null; }
    finally { if (action !== 'stop') { pending.current = false; setBusy(false); } }
  }
  function select(pose) {
    setFields(pose ? pose.map((value, i) => (value * (i === 2 ? 180 / Math.PI : 1)).toFixed(i === 2 ? 1 : 2)) : ['', '', '0']);
  }
  function chooseTool(value) { setTool(value); select(null); setEditingId(null); setDestinationName(''); }
  function posePayload() { return { x: selected[0], y: selected[1], yaw: selected[2] }; }
  return <section className="navigation-panel" tabIndex={-1} aria-label="내비게이션 지도 및 주행 제어"
    onKeyDown={event => {
      if (event.key === 'Escape' && !event.repeat && canControl) {
        event.preventDefault(); event.stopPropagation(); void perform('stop');
      }
    }}>
    <div className="nav-topbar">
      <span className={online ? 'nav-ok' : 'nav-warning'}>{online ? '● 연결됨' : '○ 연결 대기 / 지연'}</span>
      <span>{({ navigation: '자율주행', monitor: '상태 보기', mapping: '매핑' })[state?.mode] || '상태 대기'}</span>
      <span>{canControl ? otherOwner ? '다른 브라우저가 제어 중' : own ? '이 패널이 제어 중' : '제어 가능' : '조회 전용'}</span>
      <button className="nav-stop" disabled={!canControl || !state} onClick={() => void perform('stop')}>AUTO 정지</button>
    </div>
    {error && <p className="nav-error" role="alert">{error}</p>}
    <div className="nav-layout">
      <div className="nav-workspace">
        <div className="nav-toolbar" role="group" aria-label="지도 조작">
          {Object.entries({ pan: '이동', initial_pose: '초기 위치', goal: '목표 지정' }).map(([key, label]) =>
            <button key={key} aria-pressed={tool === key} disabled={key !== 'pan' && (!writable || otherOwner)}
              onClick={() => chooseTool(key)}>{label}</button>)}
        </div>
        <NavigationMap state={state} online={online} tool={tool} selected={selected} onSelect={select} selectable={writable && !otherOwner} />
      </div>
      <aside className="nav-controls">
        <section className="nav-card">
          <h3>주행 <span>{state?.values?.enabled ? '활성' : '비활성'}</span></h3>
          <button className="nav-primary nav-wide" disabled={!writable || !ready || otherOwner || busy || !!state?.values?.enabled}
            onClick={() => void perform('enable')}>{state?.values?.enabled ? '주행 활성화됨' : '주행 활성화'}</button>
          <p>{state?.mode === 'navigation' ? (state.readiness || []).join(' · ') : '목표 지정은 주행 세션에서 사용할 수 있습니다.'}</p>
        </section>
        <section className="nav-card">
          <h3>{tool === 'initial_pose' ? '초기 위치' : '목표 위치'}</h3>
          <p>초기 위치는 선택 지점 주변에서 자동 정합합니다. 목표 방향은 참고값이며 30cm 안에 도착하면 정지합니다.</p>
          <form onSubmit={event => { event.preventDefault(); if (poseAllowed && selected) void perform(tool, posePayload()); }}>
            <div className="nav-fields">{['X · m', 'Y · m', '방향 · °'].map((label, index) =>
              <label key={label}>{label}<input type="number" step="any" required value={fields[index]}
                disabled={!writable || otherOwner || tool === 'pan'}
                onChange={event => setFields(fields.map((value, i) => i === index ? event.target.value : value))} /></label>)}</div>
            <button className="nav-wide" disabled={!poseAllowed || !selected} type="submit">
              {tool === 'initial_pose' ? '초기 위치 적용' : tool === 'goal' ? '이 목표로 이동' : '위치를 선택하세요'}</button>
          </form>
        </section>
        <section className="nav-card">
          <h3>이름 있는 목표 <button disabled={!writable || otherOwner} onClick={() => chooseTool('goal')}>새 위치</button></h3>
          <form onSubmit={async event => {
            event.preventDefault();
            if (!writable || !selected || tool !== 'goal') return;
            const result = await perform('save_destination', { ...posePayload(), name: destinationName, ...(editingId ? { id: editingId } : {}) });
            if (result?.destination) setEditingId(result.destination.id);
          }}>
            <label>목표 이름<input value={destinationName} maxLength={48} required disabled={!writable || tool !== 'goal'}
              onChange={event => setDestinationName(event.target.value)} /></label>
            <button className="nav-wide" type="submit" disabled={!writable || busy || !selected || tool !== 'goal' || !destinationName.trim()}>
              {editingId ? '목표 수정 저장' : '선택 위치 저장'}</button>
          </form>
          <div className="nav-destinations">{(state?.destinations || []).map(goal => <div key={goal.id}>
            <button disabled={!writable || otherOwner} onClick={() => {
              setTool('goal'); select([goal.x, goal.y, goal.yaw]); setEditingId(goal.id); setDestinationName(goal.name);
            }}>{goal.name}</button>
            <button aria-label={`${goal.name} 삭제`} disabled={!writable || busy} onClick={async () => {
              const result = await perform('delete_destination', { id: goal.id });
              if (result && editingId === goal.id) { setEditingId(null); setDestinationName(''); }
            }}>삭제</button>
          </div>)}</div>
          {!state?.destinations?.length && <p>저장된 목표가 없습니다.</p>}
        </section>
        <NavigationStatus state={state} />
      </aside>
    </div>
    <footer className="nav-footer"><span role="status" className={commandError ? 'nav-error' : ''}>{commandError || notice}</span>
      <span>ESC · 이 패널의 목표 취소 및 AUTO 정지</span></footer>
  </section>;
}

export default function NavigationPanel() {
  const navigation = useNavigation();
  return <NavigationWorkspace key={sceneKey(navigation.state)} navigation={navigation} />;
}
