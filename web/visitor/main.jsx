import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Microphone, encodeWav, toBase64 } from './audio';
import './style.css';

const labels = { READY: '무엇이 궁금하세요?', TRANSCRIBING: '말씀을 듣고 있어요', THINKING: '답변을 생각하고 있어요', SPEAKING: 'DORI가 답하고 있어요' };
const initialNonce = location.hash.slice(1);
if (initialNonce) history.replaceState(null, '', location.pathname);

export default function App() {
  const [phase, setPhase] = useState('loading'), [status, setStatus] = useState('READY');
  const [consent, setConsent] = useState(false), [error, setError] = useState('');
  const [messages, setMessages] = useState([]), [recording, setRecording] = useState(false);
  const [audioUrl, setAudioUrl] = useState(''), [needsPlay, setNeedsPlay] = useState(false);
  const ws = useRef(null), audio = useRef(null), microphone = useRef(new Microphone());
  const retry = useRef(null), heartbeat = useRef(null), wake = useRef(null), audioId = useRef(null);
  const closed = useRef(false), capture = useRef(false), reconnectStarted = useRef(0);
  const send = data => { if (ws.current?.readyState === WebSocket.OPEN) { ws.current.send(JSON.stringify(data)); return true; } return false; };
  const stopMedia = () => {
    capture.current = false; microphone.current.cancel(); setRecording(false);
    audio.current?.pause(); audio.current?.removeAttribute('src'); audio.current?.load();
    audioId.current = null; setAudioUrl(''); setNeedsPlay(false);
  };
  const playback = result => {
    if (audioId.current) send({ type: 'playback', id: audioId.current, status: result });
    if (result !== 'ended') setError('음성을 재생하지 못했습니다. 답변은 화면에서 확인해 주세요.');
    audioId.current = null; setNeedsPlay(false);
  };
  const unlock = () => {
    // Reuse the same audio element after a gesture, including on iOS.
    if (!audioId.current && audio.current) {
      audio.current.src = 'data:audio/wav;base64,' + toBase64(encodeWav(new Float32Array(1600), 16000));
      audio.current.play().catch(() => {});
    }
  };
  async function acquireWake() {
    if (document.visibilityState === 'visible' && !closed.current && !wake.current) {
      try { wake.current = await navigator.wakeLock?.request('screen'); wake.current?.addEventListener('release', () => { wake.current = null; }); } catch { /* optional */ }
    }
  }
  function finish() {
    if (!capture.current) return;
    capture.current = false; setRecording(false);
    try {
      const audio_b64 = microphone.current.finish();
      if (send({ type: 'ptt_audio', audio_b64, format: 'wav_pcm16', sample_rate: 16000, channels: 1 })) setStatus('TRANSCRIBING');
      else setError('연결이 끊겼습니다. 다시 연결한 뒤 말씀해 주세요.');
    } catch (err) { setError(err.message); }
  }
  async function record() {
    if (capture.current) { finish(); return; }
    unlock(); setError(''); capture.current = true; setRecording(true);
    try { if (!await microphone.current.start(finish)) setRecording(false); }
    catch { capture.current = false; setRecording(false); setError('마이크를 사용할 수 없습니다. 브라우저의 마이크 권한을 확인한 뒤 다시 시도해 주세요.'); }
  }
  function connect() {
    if (closed.current) return;
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/user`);
    ws.current = socket;
    socket.onopen = () => {
      reconnectStarted.current = 0; setPhase('active'); setError(''); acquireWake();
      clearInterval(heartbeat.current); heartbeat.current = setInterval(() => send({ type: 'heartbeat' }), 5000);
    };
    socket.onmessage = ({ data }) => {
      const message = JSON.parse(data);
      if (message.type === 'robot_state') setStatus(message.status);
      if (message.type === 'stt_text' || message.type === 'llm_text') setMessages(old => [...old, { who: message.type === 'stt_text' ? '나' : 'DORI', text: message.data }].slice(-40));
      if (message.type === 'tts_audio') {
        audioId.current = message.id; setAudioUrl(message.url); audio.current.src = message.url;
        audio.current.play().catch(() => setNeedsPlay(true));
      }
      if (message.type === 'error') { setError(message.message); setStatus('READY'); }
    };
    socket.onclose = async event => {
      if (ws.current !== socket || closed.current) return;
      clearInterval(heartbeat.current); stopMedia(); await wake.current?.release(); wake.current = null;
      if ([1000, 1008, 4000].includes(event.code)) { closed.current = true; setPhase('ended'); return; }
      setPhase('reconnecting');
      reconnectStarted.current ||= Date.now();
      if (Date.now() - reconnectStarted.current > 90000) { closed.current = true; setPhase('ended'); return; }
      try { const response = await fetch('/api/session', { cache: 'no-store' }); if (response.status === 401) { closed.current = true; setPhase('ended'); return; } } catch { /* retry */ }
      if (!closed.current) retry.current = setTimeout(connect, 2000);
    };
  }
  async function pair() {
    unlock(); setError(''); setPhase('pairing');
    try {
      const response = await fetch('/api/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nonce: initialNonce, consent }) });
      if (!response.ok) throw new Error(({ 409: '다른 방문자가 사용 중이거나 정리 중입니다.', 410: 'QR이 만료되었습니다. 로봇 화면의 새 QR을 스캔해 주세요.', 429: '연결 시도가 많습니다. 1분 후 다시 시도해 주세요.' })[response.status] || '연결할 수 없습니다. 잠시 후 다시 시도해 주세요.');
      closed.current = false; connect();
    } catch (err) { setError(err.message); setPhase('pair'); }
  }
  function stop() { stopMedia(); send({ type: 'command', action: 'STOP' }); setStatus('READY'); }
  async function end() {
    closed.current = true; clearTimeout(retry.current); clearInterval(heartbeat.current);
    stopMedia(); send({ type: 'end' }); ws.current?.close(); wake.current?.release();
    setMessages([]); setPhase('ended');
    try { await fetch('/api/session', { method: 'DELETE' }); } catch { /* server grace deadline still applies */ }
  }
  useEffect(() => {
    let disposed = false;
    const mic = microphone.current;
    fetch('/api/session', { cache: 'no-store' }).then(response => {
      if (!disposed) { if (response.ok) connect(); else setPhase('pair'); }
    }).catch(() => { if (!disposed) { setPhase('pair'); setError('네트워크 연결을 확인해 주세요.'); } });
    const visibility = () => {
      if (document.hidden) { capture.current = false; microphone.current.cancel(); setRecording(false); if (audioId.current) { audio.current?.pause(); playback('canceled'); } wake.current?.release(); }
      else if (ws.current?.readyState === WebSocket.OPEN) acquireWake();
    };
    document.addEventListener('visibilitychange', visibility);
    return () => { disposed = true; closed.current = true; clearTimeout(retry.current); clearInterval(heartbeat.current); ws.current?.close(); mic.cancel(); wake.current?.release(); document.removeEventListener('visibilitychange', visibility); };
    // Connection lifecycle is owned by refs; renders must not reopen the socket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <main>
    <header><a href="/" aria-label="DORI 홈">dori<span>●</span></a><span>DGIST CAMPUS COMPANION</span></header>
    <audio ref={audio} onEnded={() => playback('ended')} onError={() => { if (audioId.current) playback('failed'); }} />
    {['loading', 'pair', 'pairing'].includes(phase) && <section className="welcome"><div className="orb">안녕!</div><p className="eyebrow">처음 만나는 캠퍼스, 함께 알아가요</p><h1>반가워요.<br/>저는 DORI예요.</h1><p>캠퍼스에 대해 궁금한 이야기를<br/>스마트폰으로 편하게 물어보세요.</p>
      <div className="consent"><p>마이크는 말하기 버튼을 눌렀을 때만 사용합니다. 음성은 인식과 답변 생성에 사용하며 서버에 녹음을 저장하지 않습니다. 답변 생성·음성 합성에는 외부 서비스가 사용될 수 있습니다. 대화 기록은 연결 종료 시 초기화합니다.</p><label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />음성 처리 안내를 확인하고 동의합니다.</label></div>
      <button className="primary" disabled={!initialNonce || !consent || phase !== 'pair'} onClick={pair}>{phase === 'pairing' ? '연결 중…' : 'DORI와 연결하기'}</button>{!initialNonce && <p className="hint">로봇 화면의 QR을 스캔해 주세요.</p>}</section>}
    {['active', 'reconnecting'].includes(phase) && <><section className="conversation"><div className="badge"><i />{phase === 'reconnecting' ? '다시 연결하는 중' : 'DORI와 연결됨'}</div><h1>{phase === 'reconnecting' ? '잠시만 기다려 주세요' : labels[status]}</h1><p className="hint">한 번에 최대 10초 · 답변은 스마트폰에서 들려요</p><div className="messages" aria-live="polite">{messages.length ? messages.map((message, i) => <article key={i} className={message.who === '나' ? 'mine' : ''}><small>{message.who}</small><p>{message.text}</p></article>) : <p className="empty">“DGIST는 어떤 곳인가요?”<br/>궁금한 이야기로 시작해 보세요.</p>}</div></section><div className="controls">{audioUrl && needsPlay && <button onClick={() => { audio.current.play().then(() => setNeedsPlay(false)).catch(() => setError('재생 버튼을 다시 눌러 주세요.')); }}>답변 음성 재생 ▶</button>}<button className={`primary ${recording ? 'recording' : ''}`} disabled={phase !== 'active' || (status !== 'READY' && !recording)} aria-pressed={recording} onClick={record}>{recording ? '말하기 마치기 ■' : '눌러서 말하기 🎙'}</button><div className="secondary"><button onClick={stop} disabled={phase !== 'active'}>현재 작업 취소</button><button onClick={end}>연결 종료</button></div></div></>}
    {phase === 'ended' && <section className="welcome"><div className="orb">또 봐요</div><h1>대화를 마쳤어요.</h1><p>다시 이야기하려면<br/>로봇 화면의 새 QR을 스캔해 주세요.</p></section>}
    {error && <p className="error" role="alert">{error}</p>}
    <footer>함께 걷는 캠퍼스, DORI</footer>
  </main>;
}
createRoot(document.getElementById('root')).render(<App />);
