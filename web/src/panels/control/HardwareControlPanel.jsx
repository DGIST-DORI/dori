import { useState } from 'react';
import { ArrowUp, ArrowDown, RotateCcw, RotateCw, OctagonX, Activity, Cpu } from 'lucide-react';
import { useHardware } from './hardware/useHardware.js';
import { driveReady } from './hardware/client.js';
import './HardwareControlPanel.css';

const ACTIONS = ['대기', '주행', '변형 중', '변형 일시정지', '비상 정지', '오류'];
const MODES = ['수동', '자동'];
const DIRECTIONS = [
  { id: 'forward', label: '전진', icon: ArrowUp, x: 1, z: 0 },
  { id: 'left', label: '좌회전', icon: RotateCcw, x: 0, z: 1 },
  { id: 'right', label: '우회전', icon: RotateCw, x: 0, z: -1 },
  { id: 'backward', label: '후진', icon: ArrowDown, x: -1, z: 0 },
];
const format = (value, scale = 1) => Number.isFinite(value) ? (value * scale).toFixed(1) : '—';

function HoldButton({ direction, disabled, hold, release, power }) {
  const Icon = direction.icon;
  const begin = () => hold({ linear_x: direction.x * power / 100, angular_z: direction.z * power / 100 });
  return <button className={`hw-direction hw-${direction.id}`} disabled={disabled}
    onPointerDown={event => {
      if (event.button !== 0) return;
      event.preventDefault(); event.currentTarget.focus();
      event.currentTarget.setPointerCapture(event.pointerId); begin();
    }}
    onPointerUp={release} onPointerCancel={release} onLostPointerCapture={release} onBlur={release}
    onContextMenu={event => event.preventDefault()}
    onKeyDown={event => {
      if ([' ', 'Enter'].includes(event.key)) { event.preventDefault(); if (!event.repeat) begin(); }
    }}
    onKeyUp={event => { if ([' ', 'Enter'].includes(event.key)) { event.preventDefault(); release(); } }}>
    <Icon size={22} /><span>{direction.label}</span>
  </button>;
}

export default function HardwareControlPanel() {
  const { state, online, holding, busy, error, notice, command, hold, release, clientId } = useHardware();
  const [power, setPower] = useState(10);
  const live = !!state?.live_enabled;
  const simulated = state?.executor === 'dry-run';
  const writable = online && state?.can_control && (live || simulated) && !busy && !holding;
  const driveAllowed = online && driveReady(state, clientId) && !busy;
  const stopped = state?.stop_latched || [3, 4, 5].includes(state?.action_state);
  const transformAllowed = writable && driveReady(state, clientId) && (!live || (
    state.transform_available && state.joints?.slice(0, 4).length === 4 && state.joints.slice(0, 4).every(j => j.fresh)
  ));
  const reason = !online ? '하드웨어 상태를 기다리고 있습니다.' : !state.can_control ? '조회 전용 계정입니다.'
    : simulated ? '모의 제어: 명령을 검증하며 실제 로봇은 움직이지 않습니다.'
    : !live ? '실제 제어 설정이 일치하지 않습니다. 서버와 브리지의 제어 설정을 확인하세요.'
    : !state.supervisor_available ? '로봇 제어기가 연결되지 않았습니다.'
    : state.manual_input_conflict ? '다른 수동 입력 장치가 연결되어 있습니다.'
    : state.move_owner && state.move_owner !== clientId ? '다른 대시보드가 주행을 제어하고 있습니다.'
    : stopped ? '정지 상태입니다. 주변을 확인한 뒤 정지를 해제하세요.'
    : state.mode !== 0 ? '수동 모드로 전환하면 직접 조작할 수 있습니다.'
    : state.action_state === 2 ? '자세 변형을 실행하고 있습니다.' : '버튼을 누르는 동안 움직이고, 놓으면 정지합니다.';
  const recent = Object.entries(state?.feedback || {}).sort((a, b) => a[1].age - b[1].age);
  const sensor = (key, scale = 1) => {
    const entry = state?.values?.[key];
    return online && entry?.age < 0.5 ? format(entry.value, scale) : '—';
  };
  return <section className="hardware-panel" tabIndex={-1} aria-label="로봇 하드웨어 제어"
    onKeyDown={event => {
      if (event.key === 'Escape' && !event.repeat && state?.can_control) {
        event.preventDefault(); event.stopPropagation(); void command('stop');
      }
    }}>
    <header className="hw-header">
      <div><Cpu size={18} /><strong>로봇 하드웨어</strong>
        <span className={`hw-badge ${live ? 'hw-live' : ''}`}>{state ? live ? '실제 제어' : simulated ? '모의 제어' : '제어 비활성' : '연결 대기'}</span></div>
      <button className="hw-stop" disabled={!state?.can_control} onClick={() => void command('stop')}>
        <OctagonX size={18} /> 비상 정지 <kbd>Esc</kbd>
      </button>
    </header>
    <div className="hw-summary">
      <span><i className={online && state?.supervisor_available ? 'hw-led hw-ok' : 'hw-led'} />
        {online ? state?.supervisor_available ? '제어기 연결됨' : '제어기 대기' : '연결 끊김 / 대기'}</span>
      <span>모드 <strong>{online ? MODES[state?.mode] ?? '—' : '—'}</strong></span>
      <span>상태 <strong>{online ? ACTIONS[state?.action_state] ?? '—' : '—'}</strong></span>
      <span>{state?.can_control ? '조작 권한 있음' : '조회 전용'}</span>
    </div>
    <div className="hw-live-control">
      <div><strong>대시보드 실제 제어</strong>
        <p>{live ? '이 로봇의 모든 대시보드에 적용 중입니다. 끄면 정지 후 모의 제어로 전환합니다.'
          : '켜면 로봇을 정지 상태로 연결합니다. 이후 정지를 해제하면 조작할 수 있습니다.'}</p>
        {!live && state?.manual_input_conflict && <p className="hw-error">조이스틱 또는 키보드 입력을 종료한 뒤 실제 제어를 켜세요.</p>}
      </div>
      <button className="hw-live-toggle" aria-pressed={live}
        disabled={!state?.can_control || (!live && (!online || busy || holding || !state.supervisor_available || state.manual_input_conflict))}
        onClick={() => void command('set_live_control', { enabled: !live })}>
        {live ? '실제 제어 끄기' : '실제 제어 켜기'}
      </button>
    </div>
    <p className="hw-guidance">{reason}</p>
    {error && <p className="hw-error" role="alert">{error}</p>}
    <div className="hw-layout">
      <section className="hw-card">
        <h3>수동 주행 <span>{holding ? '입력 중' : 'HOLD TO DRIVE'}</span></h3>
        <div className="hw-mode-row">
          {['manual', 'auto'].map((mode, index) => <button key={mode} aria-pressed={state?.mode === index}
            disabled={!writable || (live && !state.supervisor_available)}
            onClick={() => void command('set_mode', { mode })}>{MODES[index]} 모드</button>)}
        </div>
        <div className="hw-pad" role="group" aria-label="누르고 있는 동안 주행">
          {DIRECTIONS.map(direction => <HoldButton key={direction.id} direction={direction} disabled={!driveAllowed}
            hold={hold} release={release} power={power} />)}
          <span className="hw-pad-center"><Activity size={22} /><small>{power}%</small></span>
        </div>
        <label className="hw-power">입력 강도 <strong>{power}%</strong>
          <input type="range" min="5" max="80" step="5" value={power} disabled={holding}
            onChange={event => setPower(Number(event.target.value))} /></label>
        <p>최대 주행 입력 대비 비율입니다. 터치 또는 버튼에 포커스를 두고 Space / Enter를 누르세요.</p>
      </section>
      <section className="hw-card hw-posture">
        <h3>자세 변형 <span>A ↔ B</span></h3>
        <p>바퀴와 몸체 서보를 정해진 순서로 움직여 자세를 변경합니다. 모터 1–4의 최신 피드백이 필요합니다.</p>
        <div className="hw-pose-buttons">
          {['A', 'B'].map(pose => <button disabled={!transformAllowed} key={pose}
            onClick={() => void command('transform', { pose })}><strong>{pose}</strong><span>{pose} 자세로 변형</span></button>)}
        </div>
        <div className="hw-resume">
          <button disabled={!writable || (live && (!stopped || !state.supervisor_available || state.manual_input_conflict))}
            onClick={() => void command('resume')}>정지 해제 / 변형 재개</button>
          <p>수동 모드로 복귀합니다. 중단된 변형이 있으면 이어서 움직입니다.</p>
        </div>
        <dl className="hw-sensors">
          <div><dt>몸체 기울기</dt><dd>{sensor('body/pitch', 180 / Math.PI)} <small>°</small></dd></div>
          <div><dt>기울기 속도</dt><dd>{sensor('body/pitch_rate', 180 / Math.PI)} <small>°/s</small></dd></div>
          <div><dt>안정화 토크</dt><dd>{sensor('body/stabilization_torque')} <small>N·m</small></dd></div>
        </dl>
      </section>
    </div>
    <section className="hw-card">
      <h3>모터 피드백 <span>LIVE TELEMETRY</span></h3>
      <div className="hw-table-wrap"><table className="hw-table">
        <thead><tr><th>모터</th><th>수신</th><th>위치 · °</th><th>속도 · rad/s</th><th>부하 · N·m</th></tr></thead>
        <tbody>{(state?.joints || []).map(joint => {
          const fresh = online && joint.fresh;
          return <tr key={joint.name}><th title={joint.topic}>{joint.label}</th>
            <td className={fresh ? 'hw-ok' : 'hw-muted'}>{fresh ? '정상' : joint.age == null ? '미수신' : '지연'}</td>
            <td>{fresh ? format(joint.position, 180 / Math.PI) : '—'}</td>
            <td>{fresh ? format(joint.velocity) : '—'}</td><td>{fresh ? format(joint.effort) : '—'}</td></tr>;
        })}</tbody>
      </table></div>
      {!state?.joints?.length && <p>아직 수신된 모터 상태가 없습니다.</p>}
      <p>미수신·지연 값은 —로 표시합니다. 하드웨어가 제공하지 않는 부하 값은 표시하지 않습니다.</p>
    </section>
    {recent.length > 0 && <section className="hw-feedback" aria-label="제어기 응답">
      {recent.map(([key, feedback]) => <div key={key} className={feedback.accepted ? '' : 'hw-error'}>
        <strong>{key.startsWith('transform') ? '변형' : key.startsWith('drive') ? '주행' : '최근 오류'}</strong>
        <span>{feedback.message}</span><small>{Math.floor(feedback.age)}초 전</small>
      </div>)}
    </section>}
    <footer className="hw-footer" role="status">{notice || '모드와 연결 상태를 확인한 뒤 조작하세요.'}</footer>
  </section>;
}
