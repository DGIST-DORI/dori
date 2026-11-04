import { qualities, reasons } from './navigation/status.js';

const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : '—';
const parse = value => { try { return JSON.parse(value || '{}') || {}; } catch { return {}; } };
const velocity = (value, normalized = false) => value
  ? `${number(value[0])}${normalized ? '' : ' m/s'} / ${number(value[1])}${normalized ? '' : ' rad/s'}` : '—';

export default function NavigationStatus({ state }) {
  const v = state?.values || {}, joints = state?.joints || {}, wheelControl = state?.wheel_control || {};
  const quality = parse(v.odometry), motion = parse(v.motion), hri = parse(v.hri_state), retry = parse(v.retry);
  const pair = field => ['left_wheel_joint', 'right_wheel_joint'].map(name => number(wheelControl[name]?.[field])).join(' / ');
  const wheels = ['left_wheel_joint', 'right_wheel_joint'].map(name =>
    state?.hardware?.fresh && joints[name]?.age < .5 ? number(joints[name].velocity) : '—').join(' / ');
  const phase = value => ({ stop: '정지', start: '출발', track: '추종', brake: '감속' })[value] || '—';
  const rows = [
    ['모터 통신', state?.hardware?.fresh ? '수신 정상' : '피드백 없음 / 드라이버 확인'],
    ['조이스틱 명령', velocity(state?.velocities?.manual_velocity, true)],
    ['바퀴 L / R · rad/s', wheels], ['바퀴 목표 L / R · rad/s', pair('target_velocity')],
    ['구동 보상 L / R · Nm', pair('compensation_torque')],
    ['Nav2 명령', velocity(state?.velocities?.nav_velocity)],
    ['구동 출력 · 정규화', velocity(state?.velocities?.drive_velocity, true)],
    ['실행 상태', `${motion.recovering ? '후진 복구 · ' : ''}${phase(motion.linear?.phase)} / ${phase(motion.angular?.phase)}`],
    ['응답 보정', `직진 ${number(motion.linear?.response_gain)} · 회전 ${number(motion.angular?.response_gain)} (${number((motion.linear?.learned_samples ?? 0) + (motion.angular?.learned_samples ?? 0), 0)} 표본)`],
    ['HRI 상태', hri.state || '미연결'], ['짐벌 목표 각도', `${number(v.gimbal_target, 1)}°`],
    ['짐벌 실제 각도', `${joints.motor_5_joint?.age < .5 ? number(joints.motor_5_joint.position * 180 / Math.PI, 1) : '—'}°`],
  ];
  return <>
    <section className="nav-card">
      <h3>로봇 상태 <span>{['대기', '주행', '변형', '일시정지', '비상정지', '오류'][v.action] || '미수신'}</span></h3>
      <div className="nav-pose">{['X · m', 'Y · m', '방향 · °'].map((label, index) => <div key={label}>
        <span>{label}</span><strong>{number(state?.robot?.[index] * (index === 2 ? 180 / Math.PI : 1), index === 2 ? 1 : 2)}</strong>
      </div>)}</div>
      <p>{v.control === 1 ? 'AUTO' : v.control === 0 ? 'MANUAL' : '제어 미연결'} · 몸체 pitch {number(v.pitch_deg, 1)}°</p>
      <p>{reasons[v.drive] || v.drive || '주행 브리지 미수신'}</p>
      <p>목표: {v.enabled && retry.state === 'waiting'
        ? `경로 재시도 ${retry.attempt}/${retry.max_attempts} · ${Math.ceil(retry.remaining_seconds || 0)}초 후`
        : v.goal_status || '—'}</p>
    </section>
    <details className="nav-card" open>
      <summary>센서와 위치 추정</summary>
      <dl>{[['scan', 'LiDAR', .8], ['odom', 'Odometry', .5], ['imu', 'IMU', .5]].map(([key, label, limit]) => {
        const sensor = state?.sensors?.[key], age = sensor?.age;
        const fresh = Number.isFinite(age) && age >= -.05 && age < limit;
        return <div key={key}><dt>{label}</dt><dd className={fresh ? 'nav-ok' : 'nav-warning'}>
          {Number.isFinite(age) ? `${number(sensor.hz, 1)} Hz / ${number(Math.max(0, age * 1000), 0)} ms` : '미수신'}</dd></div>;
      })}</dl>
      <p>LiDAR 정합: {qualities[quality.state] || quality.state || '미수신'}</p>
      <p>{quality.rmse_m !== undefined
        ? `잔차 ${number(quality.rmse_m * 1000, 1)} mm · 겹침 ${number(quality.overlap * 100, 0)}% · ${number(quality.processing_ms, 0)} ms`
        : state?.scan_error || '—'}</p>
      <p>{state?.localization?.state === 'ready' ? '마지막 수동 정합 · ' : ''}{state?.localization?.message}</p>
      <p>{state?.auto_alignment?.enabled ? state.auto_alignment.message : '자동 지도 정합 꺼짐'}
        {state?.auto_alignment?.last_check && ` · 최근 점검 일치율 ${number(state.auto_alignment.last_check.matched_fraction * 100, 0)}%`}</p>
    </details>
    <details className="nav-card"><summary>구동 상세 · 라이다 짐벌</summary>
      <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </details>
  </>;
}
