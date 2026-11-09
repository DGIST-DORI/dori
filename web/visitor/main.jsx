import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Microphone, StreamingMicrophone, encodeWav, toBase64 } from './audio';
import { confirmPairingScan, pairingError } from './pairing';
import doriLogo from '../src/assets/logo/logo-full.svg';
import './style.css';

const labels = { READY: '무엇이 궁금하세요?', TRANSCRIBING: '말씀을 글로 바꾸고 있어요', THINKING: '답변을 생각하고 있어요', SPEAKING: 'DORI가 답하고 있어요' };
const labels = { READY: '무엇이 궁금하세요?', TRANSCRIBING: '말씀을 글로 바꾸고 있어요', THINKING: '답변을 생각하고 있어요', SPEAKING: 'DORI가 답하고 있어요', NAVIGATING: '목적지로 안내하고 있어요', ARRIVED: '목적지에 도착했어요' };
const MAX_TEXT_LENGTH = 1000;
const initialNonce = location.hash.slice(1);
if (initialNonce) history.replaceState(null, '', location.pathname);
// A QR scanner may reuse this tab with a different fragment without loading
// the document again. Re-bootstrap so the new QR replaces the expired proof.
window.addEventListener('hashchange', () => {
  if (location.hash.length > 1) location.reload();
});

export default function App() {
  const [phase, setPhase] = useState('loading'), [status, setStatus] = useState('READY');
  const [consent, setConsent] = useState(false), [error, setError] = useState('');
  const [messages, setMessages] = useState([]), [recording, setRecording] = useState(false);
  const [destinations, setDestinations] = useState([]);
  const [draft, setDraft] = useState('');
  const pendingText = useRef(null), composing = useRef(false);
  const [scanState, setScanState] = useState('checking'), [claimDeadline, setClaimDeadline] = useState(0);
  const [claimSeconds, setClaimSeconds] = useState(0);
  const [audioUrl, setAudioUrl] = useState(''), [needsPlay, setNeedsPlay] = useState(false);
  const ws = useRef(null), audio = useRef(null), microphone = useRef(new Microphone());
  const provider = useRef('whisper'), streamTurn = useRef(null);
  const retry = useRef(null), heartbeat = useRef(null), wake = useRef(null), audioId = useRef(null);
  const closed = useRef(false), capture = useRef(false), reconnectStarted = useRef(0);
  const send = data => { if (ws.current?.readyState === WebSocket.OPEN) { ws.current.send(JSON.stringify(data)); return true; } return false; };
  const stopMedia = () => {
    streamTurn.current = null;
    capture.current = false; microphone.current.cancel(); setRecording(false);
    audio.current?.pause(); audio.current?.removeAttribute('src'); audio.current?.load();
    audioId.current = null; setAudioUrl(''); setNeedsPlay(false);
  };
  function abortStream(message) {
    const turn = streamTurn.current;
    if (turn) send({ type: 'stt_cancel', id: turn.id });
    streamTurn.current = null; capture.current = false;
    microphone.current.cancel(); setRecording(false); setStatus('READY');
    if (message) setError(message);
  }
  function flushStream() {
    const turn = streamTurn.current;
    if (!turn?.ready) return;
    if (ws.current?.readyState !== WebSocket.OPEN || ws.current.bufferedAmount > 128 * 1024) {
      abortStream('음성 전송이 지연되고 있습니다. 연결을 확인하고 다시 말씀해 주세요.'); return;
    }
    for (const pcm of turn.pending.splice(0)) {
      if (!send({ type: 'stt_chunk', id: turn.id, seq: turn.seq++, audio_b64: toBase64(pcm) })) {
        abortStream('연결이 끊겼습니다. 다시 연결한 뒤 말씀해 주세요.'); return;
      }
    }
    if (turn.ended && !turn.endSent) {
      turn.endSent = true; send({ type: 'stt_end', id: turn.id, seq: turn.seq });
    }
  }
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
    if (streamTurn.current) {
      if (!streamTurn.current.started) { abortStream(); return; }
      microphone.current.finish();
      capture.current = false; setRecording(false); setStatus('TRANSCRIBING');
      if (streamTurn.current) { streamTurn.current.ended = true; flushStream(); }
      return;
    }
    capture.current = false; setRecording(false);
    try {
      const audio_b64 = microphone.current.finish();
      if (send({ type: 'ptt_audio', audio_b64, format: 'wav_pcm16', sample_rate: 16000, channels: 1 })) setStatus('TRANSCRIBING');
      else setError('연결이 끊겼습니다. 다시 연결한 뒤 말씀해 주세요.');
    } catch (err) { setError(err.message); }
  }
  async function record() {
    if (capture.current) { finish(); return; }
    if (pendingText.current !== null || phase !== 'active' || status !== 'READY') return;
    unlock(); setError(''); capture.current = true; setRecording(true);
    if (provider.current === 'azure') {
      const turn = { id: crypto.randomUUID(), seq: 0, pending: [], ready: false, ended: false };
      streamTurn.current = turn;
      microphone.current = new StreamingMicrophone();
      try {
        const started = await microphone.current.start(pcm => {
          if (streamTurn.current !== turn) return;
          turn.pending.push(pcm);
          if (turn.pending.length > 20) abortStream('음성 연결이 지연되고 있습니다. 잠시 후 다시 말씀해 주세요.');
          else flushStream();
        }, finish);
        if (!started || streamTurn.current !== turn) return;
        turn.started = true;
        if (!send({ type: 'stt_start', id: turn.id, format: 'pcm16', sample_rate: 16000, channels: 1 }))
          abortStream('연결이 끊겼습니다. 다시 연결한 뒤 말씀해 주세요.');
      } catch {
        if (streamTurn.current === turn) abortStream('마이크를 사용할 수 없습니다. 브라우저의 마이크 권한을 확인해 주세요.');
      }
      return;
    }
    microphone.current = new Microphone();
    try { if (!await microphone.current.start(finish)) setRecording(false); }
    catch { capture.current = false; setRecording(false); setError('마이크를 사용할 수 없습니다. 브라우저의 마이크 권한을 확인한 뒤 다시 시도해 주세요.'); }
  }
  function sendText(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || draft.length > MAX_TEXT_LENGTH || composing.current || pendingText.current !== null
      || capture.current || phase !== 'active' || status !== 'READY') return;
    unlock(); setError('');
    if (send({ type: 'text', text })) {
      pendingText.current = draft;
      setStatus('THINKING');
    } else setError('연결이 끊겼습니다. 다시 연결한 뒤 보내 주세요.');
  }
  function textKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing
      || event.keyCode === 229 || composing.current) return;
    event.preventDefault();
    event.currentTarget.form.requestSubmit();
  }
  function showEnded() {
    closed.current = true; pendingText.current = null;
    setDraft(''); setMessages([]); setPhase('ended');
  }
  function connect() {
    if (closed.current) return;
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/user`);
    ws.current = socket;
    socket.onopen = () => {
      reconnectStarted.current = 0; setPhase('active'); setError(''); acquireWake();
      clearInterval(heartbeat.current); heartbeat.current = setInterval(() => send({ type: 'heartbeat' }), 5000);
      fetch('/api/destinations').then(r => r.json()).then(d => { if (d.destinations) setDestinations(d.destinations); }).catch(() => {});
    };
    socket.onmessage = ({ data }) => {
      if (ws.current !== socket || closed.current) return;
      const message = JSON.parse(data);
      if (message.destinations) setDestinations(message.destinations);
      if (message.type === 'destinations') setDestinations(message.destinations);
      if (message.stt_provider) provider.current = message.stt_provider;
      if (message.type === 'stt_ready' && message.id === streamTurn.current?.id) {
        streamTurn.current.ready = true; flushStream();
      }
      if (message.type === 'stt_closed' && message.id === streamTurn.current?.id) {
        streamTurn.current = null; capture.current = false;
        microphone.current.cancel(); setRecording(false); setStatus('TRANSCRIBING');
      }
      if (message.type === 'robot_state') setStatus(message.status);
      if (['stt_text', 'user_text', 'llm_text'].includes(message.type)) setMessages(old => [...old, { who: message.type === 'llm_text' ? 'DORI' : '나', text: message.data }].slice(-40));
      if (message.type === 'user_text') {
        const accepted = pendingText.current;
        setDraft(current => current === accepted ? '' : current);
        pendingText.current = null;
      }
      if (message.type === 'tts_audio') {
        audioId.current = message.id; setAudioUrl(message.url); audio.current.src = message.url;
        audio.current.play().catch(() => setNeedsPlay(true));
      }
      if (message.type === 'error') { if (streamTurn.current) abortStream(); pendingText.current = null; setError(message.message); setStatus('READY'); }
    };
    socket.onclose = async event => {
      if (ws.current !== socket || closed.current) return;
      pendingText.current = null;
      clearInterval(heartbeat.current); stopMedia(); await wake.current?.release(); wake.current = null;
      if ([1000, 1008, 4000].includes(event.code)) { showEnded(); return; }
      setPhase('reconnecting');
      reconnectStarted.current ||= Date.now();
      if (Date.now() - reconnectStarted.current > 90000) { showEnded(); return; }
      try { const response = await fetch('/api/session', { cache: 'no-store' }); if (response.status === 401) { showEnded(); return; } } catch { /* retry */ }
      if (!closed.current) retry.current = setTimeout(connect, 2000);
    };
  }
  function acceptScan(claim) {
    const seconds = Math.max(0, Math.floor(claim.expires_in));
    setClaimSeconds(seconds); setClaimDeadline(Date.now() + seconds * 1000);
    setScanState(seconds > 0 ? 'ready' : 'expired');
  }
  function rejectScan(err) {
    setScanState(err.status === 410 ? 'expired' : 'error');
    setError(err.message);
  }
  async function retryScan() {
    setError(''); setScanState('checking');
    try { acceptScan(await confirmPairingScan(initialNonce)); }
    catch (err) { rejectScan(err); }
  }
  useEffect(() => {
    if (!claimDeadline) return;
    const timer = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((claimDeadline - Date.now()) / 1000));
      setClaimSeconds(remaining);
      if (!remaining) setScanState('expired');
    }, 1000);
    return () => clearInterval(timer);
  }, [claimDeadline]);
  async function pair() {
    unlock(); setError(''); setPhase('pairing');
    try {
      const response = await fetch('/api/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ consent }) });
      if (!response.ok) {
        if (response.status === 410) { setScanState('expired'); setClaimDeadline(0); }
        throw new Error(pairingError(response.status));
      }
      setClaimDeadline(0);
      closed.current = false; connect();
    } catch (err) { setError(err.message); setPhase('pair'); }
  }
  function stop() { pendingText.current = null; stopMedia(); send({ type: 'command', action: 'STOP' }); setStatus('READY'); }
  async function end() {
    closed.current = true; clearTimeout(retry.current); clearInterval(heartbeat.current);
    stopMedia(); send({ type: 'end' }); ws.current?.close(); wake.current?.release();
    showEnded();
    try { await fetch('/api/session', { method: 'DELETE' }); } catch { /* server grace deadline still applies */ }
  }
  useEffect(() => {
    let disposed = false;
    const mic = microphone.current;
    // Validate the scan immediately, before the visitor reads the consent text.
    // This does not create a session, open the microphone, or trigger the robot.
    const scan = confirmPairingScan(initialNonce).then(value => ({ value }), error => ({ error }));
    fetch('/api/session', { cache: 'no-store' }).then(async response => {
      if (disposed) return;
      if (response.ok) { connect(); return; }
      const result = await scan;
      if (disposed) return;
      setPhase('pair');
      if (result.error) rejectScan(result.error); else acceptScan(result.value);
    }).catch(async () => {
      const result = await scan;
      if (disposed) return;
      setPhase('pair');
      if (result.error) rejectScan(result.error); else acceptScan(result.value);
    });
    const visibility = () => {
      if (document.hidden) { if (streamTurn.current) abortStream(); capture.current = false; microphone.current.cancel(); setRecording(false); if (audioId.current) { audio.current?.pause(); playback('canceled'); } wake.current?.release(); }
      else if (ws.current?.readyState === WebSocket.OPEN) acquireWake();
    };
    document.addEventListener('visibilitychange', visibility);
    return () => { disposed = true; closed.current = true; clearTimeout(retry.current); clearInterval(heartbeat.current); ws.current?.close(); mic.cancel(); microphone.current.cancel(); wake.current?.release(); document.removeEventListener('visibilitychange', visibility); };
    // Connection lifecycle is owned by refs; renders must not reopen the socket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <main>
    <header><a href="/" aria-label="DORI 홈"><img src={doriLogo} alt="DORI" className="brand-logo" /></a><span>DGIST CAMPUS COMPANION</span></header>
    <audio ref={audio} onEnded={() => playback('ended')} onError={() => { if (audioId.current) playback('failed'); }} />
    {['loading', 'pair', 'pairing'].includes(phase) && <section className="welcome"><div className="orb">안녕!</div><p className="eyebrow">처음 만나는 캠퍼스, 함께 알아가요</p><h1>반가워요.<br/>저는 DORI예요.</h1><p>캠퍼스에 대해 궁금한 이야기를<br/>스마트폰으로 편하게 물어보세요.</p>
      <div className="consent"><p>마이크는 말하기 버튼을 눌렀을 때만 사용합니다. 음성 인식에는 Microsoft Azure Speech가 사용될 수 있으며, 음성이 해당 서비스로 전송됩니다. 음성과 입력한 텍스트는 답변 생성에 사용하며 DORI 서버에 녹음을 저장하지 않습니다. 답변 생성·음성 합성에도 외부 서비스가 사용될 수 있습니다. 대화 기록은 연결 종료 시 초기화합니다.</p><label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />음성·텍스트 처리 안내를 확인하고 동의합니다.</label></div>
      <button className="primary" disabled={scanState !== 'ready' || !consent || phase !== 'pair'} onClick={pair}>{phase === 'pairing' ? '연결 중…' : 'DORI와 연결하기'}</button>{scanState === 'checking' && <p className="hint" role="status">QR을 확인하고 있어요…</p>}
      {scanState === 'ready' && <p className="hint">QR 확인 완료 · 연결 가능 시간 {Math.floor(claimSeconds / 60)}:{String(claimSeconds % 60).padStart(2, '0')}</p>}
      {scanState === 'expired' && <p className="hint">QR 화면의 새 코드를 스캔해 주세요. 이 페이지를 새로고침해도 시간이 연장되지는 않습니다.</p>}
      {scanState === 'error' && <button onClick={retryScan}>QR 확인 다시 시도</button>}</section>}
    {['active', 'reconnecting'].includes(phase) && <><section className="conversation"><div className="badge"><i />{phase === 'reconnecting' ? '다시 연결하는 중' : 'DORI와 연결됨'}</div><h1>{phase === 'reconnecting' ? '잠시만 기다려 주세요' : recording ? '말씀을 듣고 있어요' : labels[status]}</h1><p className="hint">말을 마치면 자동으로 전송해요 · 최대 10초</p><div className="messages" aria-live="polite">{messages.length ? messages.map((message, i) => <article key={i} className={message.who === '나' ? 'mine' : ''}><small>{message.who}</small><p>{message.text}</p></article>) : <p className="empty">“DGIST는 어떤 곳인가요?”<br/>궁금한 이야기로 시작해 보세요.</p>}</div></section><div className="controls">{audioUrl && needsPlay && <button onClick={() => { audio.current.play().then(() => setNeedsPlay(false)).catch(() => setError('재생 버튼을 다시 눌러 주세요.')); }}>답변 음성 재생 ▶</button>}
      {destinations.length > 0 && <div className="destinations" aria-label="안내 가능한 목적지">
        <span className="destinations-title">안내 가능한 목적지</span>
        <div className="destination-chips">
          {destinations.map(dest => <button key={dest.id || dest.name} type="button" className="destination-chip"
            disabled={recording || phase !== 'active' || (status !== 'READY' && status !== 'NAVIGATING')}
            onClick={() => {
              const text = `${dest.name} 안내해줘`;
              unlock(); setError('');
              if (send({ type: 'text', text })) {
                pendingText.current = text;
                setStatus('THINKING');
              }
            }}>{dest.name} ↗</button>)}
        </div>
      </div>}
      <form className="text-composer" onSubmit={sendText}>
        <label htmlFor="visitor-text">텍스트로 이야기하기</label>
        <div className="text-composer-row">
          <textarea id="visitor-text" rows={2} maxLength={MAX_TEXT_LENGTH} value={draft}
            placeholder="DORI에게 하고 싶은 말을 적어 주세요"
            disabled={phase !== 'active' || recording} aria-describedby="text-length"
            onChange={event => setDraft(event.target.value)} onKeyDown={textKeyDown}
            onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} />
          <button type="submit" disabled={!draft.trim() || recording || phase !== 'active' || status !== 'READY'}>전송</button>
        </div>
        <small id="text-length">{draft.length.toLocaleString()} / 1,000자</small>
      </form>
      <button className={`primary ${recording ? 'recording' : ''}`} disabled={phase !== 'active' || (status !== 'READY' && !recording)} aria-pressed={recording} onClick={record}>{recording ? '말하기 마치기 ■' : '눌러서 말하기 🎙'}</button><div className="secondary"><button onClick={stop} disabled={phase !== 'active'}>현재 작업 취소</button><button onClick={end}>연결 종료</button></div></div></>}
    {phase === 'ended' && <section className="welcome"><div className="orb">또 봐요</div><h1>대화를 마쳤어요.</h1><p>다시 이야기하려면<br/>로봇 화면의 새 QR을 스캔해 주세요.</p></section>}
    {error && <p className="error" role="alert">{error}</p>}
    <footer>함께 걷는 캠퍼스, DORI</footer>
  </main>;
}
createRoot(document.getElementById('root')).render(<App />);
