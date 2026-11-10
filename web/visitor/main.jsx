import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUp, Mic, Square, Check, MapPin, ChevronDown, BookOpen, Volume2 } from 'lucide-react';
import { Microphone, StreamingMicrophone, encodeWav, toBase64 } from './audio';
import { confirmPairingScan, pairingError } from './pairing';
import doriLogo from '../src/assets/logo/logo-full.svg';
import './style.css';

const labels = { TRANSCRIBING: '말씀을 글로 바꾸고 있어요', THINKING: '답변을 생각하고 있어요', SPEAKING: '답변을 읽고 있어요', CANCELING: '대화를 중지하고 있어요' };
const MAX_TEXT_LENGTH = 1000;
const initialNonce = location.hash.slice(1);
if (initialNonce) history.replaceState(null, '', location.pathname);
// A QR scanner may reuse this tab with a different fragment without loading
// the document again. Re-bootstrap so the new QR replaces the expired proof.
window.addEventListener('hashchange', () => {
  if (location.hash.length > 1) location.reload();
});

function ReplyStatus({ state }) {
  return <div className="reply-status" role="status" aria-atomic="true">
    {state === 'SPEAKING' ? <Volume2 size={15} aria-hidden="true" /> : <span className="status-dots" aria-hidden="true"><i /><i /><i /></span>}
    <span>{labels[state]}</span>
  </div>;
}

export default function App() {
  const [phase, setPhase] = useState('loading'), [status, setStatus] = useState('READY');
  const [consent, setConsent] = useState(false), [error, setError] = useState('');
  const [messages, setMessages] = useState([]), [recording, setRecording] = useState(false);
  const [introDismissed, setIntroDismissed] = useState(false), [replyReceived, setReplyReceived] = useState(false);
  const [destinations, setDestinations] = useState([]);
  const [navigation, setNavigation] = useState({ status: 'IDLE' });
  const [draft, setDraft] = useState('');
  const [destinationsOpen, setDestinationsOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const pendingText = useRef(null), composing = useRef(false);
  const responseCanceled = useRef(false);
  const messageList = useRef(null), controls = useRef(null), followReplies = useRef(true);
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
  function finish(reason) {
    if (!capture.current) return;
    if (reason === 'limit') setNotice('2분 동안의 말씀을 전송했어요. 답변 후 이어서 말씀해 주세요.');
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
    followReplies.current = true;
    unlock(); setError(''); setNotice(''); setDestinationsOpen(false); setReplyReceived(false); capture.current = true; setRecording(true);
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
    send({ type: 'ptt_start' });
    try { if (!await microphone.current.start(finish)) setRecording(false); }
    catch { capture.current = false; setRecording(false); setError('마이크를 사용할 수 없습니다. 브라우저의 마이크 권한을 확인한 뒤 다시 시도해 주세요.'); }
  }
  function sendText(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || draft.length > MAX_TEXT_LENGTH || composing.current || pendingText.current !== null
      || capture.current || phase !== 'active' || status !== 'READY') return;
    unlock(); setError(''); setNotice(''); setDestinationsOpen(false);
    if (send({ type: 'text', text })) {
      followReplies.current = true;
      pendingText.current = draft;
      setReplyReceived(false);
      setStatus('THINKING');
    } else setError('연결이 끊겼습니다. 다시 연결한 뒤 보내 주세요.');
  }
  function navigate(destination) {
    if (pendingText.current !== null || capture.current || phase !== 'active' || status !== 'READY') return;
    unlock(); setError(''); setNotice(''); setDestinationsOpen(false);
    if (send({ type: 'navigate', destination_id: destination.id })) {
      followReplies.current = true;
      pendingText.current = ''; // Keep any drafted question when the selection is echoed.
      setReplyReceived(false);
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
    setIntroDismissed(false); setReplyReceived(false);
    setDraft(''); setMessages([]); setDestinations([]); setNavigation({ status: 'IDLE' }); setPhase('ended');
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
      if (ws.current !== socket || closed.current) return;
      const message = JSON.parse(data);
      if (Array.isArray(message.destinations)) setDestinations(message.destinations);
      if (message.stt_provider) provider.current = message.stt_provider;
      if (message.navigation) setNavigation(message.navigation);
      if (message.type === 'navigation_state') setNavigation(message);
      if (responseCanceled.current) {
        if (message.type === 'robot_state' && message.status === 'READY') responseCanceled.current = false;
        else if (['stt_ready', 'stt_closed', 'stt_text', 'user_text', 'llm_text', 'tts_audio', 'robot_state', 'error'].includes(message.type)) return;
      }
      if (message.type === 'stt_ready' && message.id === streamTurn.current?.id) {
        streamTurn.current.ready = true; flushStream();
      }
      if (message.type === 'stt_closed' && message.id === streamTurn.current?.id) {
        if (message.reason === 'limit') setNotice('2분 동안의 말씀을 전송했어요. 답변 후 이어서 말씀해 주세요.');
        streamTurn.current = null; capture.current = false;
        microphone.current.cancel(); setRecording(false); setStatus('TRANSCRIBING');
      }
      if (message.type === 'robot_state') {
        setStatus(message.status);
        if (message.status === 'READY') setReplyReceived(false);
      }
      if (['stt_text', 'user_text', 'llm_text'].includes(message.type)) {
        setIntroDismissed(true);
        setReplyReceived(message.type === 'llm_text');
        setMessages(old => [...old, {
          who: message.type === 'llm_text' ? 'DORI' : '나', text: message.data,
          sources: message.type === 'llm_text' && Array.isArray(message.sources) ? message.sources : [],
        }].slice(-40));
      }
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
      responseCanceled.current = false;
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
  function stopResponse() {
    pendingText.current = null; stopMedia(); setNotice('');
    if (send({ type: 'command', action: 'CANCEL_RESPONSE' })) { responseCanceled.current = true; setStatus('CANCELING'); }
    else setError('연결이 끊겼습니다. 다시 연결한 뒤 시도해 주세요.');
  }
  function stopNavigation() {
    if (send({ type: 'command', action: 'CANCEL_NAVIGATION' })) setNavigation(current => ({ ...current, status: 'STOPPING' }));
    else setError('연결이 끊겼습니다. 다시 연결한 뒤 시도해 주세요.');
  }
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
  const hasDraft = Boolean(draft.trim());
  const ready = phase === 'active' && status === 'READY';
  const responding = !recording && ['TRANSCRIBING', 'THINKING', 'SPEAKING', 'CANCELING'].includes(status);
  const navigating = ['STARTING', 'NAVIGATING', 'STOPPING'].includes(navigation.status);
  const actionLabel = recording ? '말하기 마치기' : responding ? '대화 중지' : hasDraft ? '전송' : '눌러서 말하기';
  const showReplyStatus = phase === 'active' && !recording && Boolean(labels[status]);
  const showPendingReply = showReplyStatus && !replyReceived;
  useEffect(() => {
    const trackScroll = () => {
      if (messageList.current && controls.current) {
        followReplies.current = messageList.current.getBoundingClientRect().bottom <= controls.current.getBoundingClientRect().top + 80;
      }
    };
    window.addEventListener('scroll', trackScroll, { passive: true });
    return () => window.removeEventListener('scroll', trackScroll);
  }, []);
  useLayoutEffect(() => {
    if (!followReplies.current || !messageList.current || !controls.current) return;
    // Keep new replies above the sticky composer, unless the visitor scrolled
    // back to read earlier messages. Sending a new question resumes following.
    const overlap = messageList.current.getBoundingClientRect().bottom - controls.current.getBoundingClientRect().top;
    if (overlap > 0) window.scrollBy(0, overlap);
  }, [messages, status, recording, navigation.status, phase]);
  return <main>
    <header><a href="/" aria-label="DORI 홈"><img src={doriLogo} alt="DORI" className="brand-logo" /></a><span>DGIST CAMPUS COMPANION</span></header>
    <audio ref={audio} onEnded={() => playback('ended')} onError={() => { if (audioId.current) playback('failed'); }} />
    {['loading', 'pair', 'pairing'].includes(phase) && <section className="welcome"><div className="orb">안녕!</div><p className="eyebrow">처음 만나는 캠퍼스, 함께 알아가요</p><h1>반가워요.<br/>저는 DORI예요.</h1><p>캠퍼스에 대해 궁금한 이야기를<br/>스마트폰으로 편하게 물어보세요.</p>
      <div className="consent"><p>마이크는 말하기 버튼을 눌렀을 때만 사용합니다. 음성 인식에는 Microsoft Azure Speech가 사용될 수 있으며, 음성이 해당 서비스로 전송됩니다. 음성과 입력한 텍스트는 답변 생성에 사용하며 DORI 서버에 녹음을 저장하지 않습니다. 답변 생성·음성 합성에도 외부 서비스가 사용될 수 있습니다. 대화 기록은 연결 종료 시 초기화합니다.</p><label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />음성·텍스트 처리 안내를 확인하고 동의합니다.</label></div>
      <button className="primary" disabled={scanState !== 'ready' || !consent || phase !== 'pair'} onClick={pair}>{phase === 'pairing' ? '연결 중…' : 'DORI와 연결하기'}</button>{scanState === 'checking' && <p className="hint" role="status">QR을 확인하고 있어요…</p>}
      {scanState === 'ready' && <p className="hint">QR 확인 완료 · 연결 가능 시간 {Math.floor(claimSeconds / 60)}:{String(claimSeconds % 60).padStart(2, '0')}</p>}
      {scanState === 'expired' && <p className="hint">QR 화면의 새 코드를 스캔해 주세요. 이 페이지를 새로고침해도 시간이 연장되지는 않습니다.</p>}
      {scanState === 'error' && <button onClick={retryScan}>QR 확인 다시 시도</button>}</section>}
    {['active', 'reconnecting'].includes(phase) && <><section className="conversation">
      <div className="badge" role="status"><i />{phase === 'reconnecting' ? '다시 연결하는 중' : 'DORI와 연결됨'}</div>
      <div className={`conversation-intro ${introDismissed ? 'is-dismissed' : ''}`} aria-hidden={introDismissed}>
        <div><h1>무엇이 궁금하세요?</h1><p className="hint">궁금한 내용을 적거나 마이크를 눌러 이야기해 주세요.</p></div>
      </div>
      <div className="messages" ref={messageList}>
        <div className="message-history" role="log" aria-label="DORI와 대화" aria-relevant="additions">
        {messages.map((message, i) => <div key={i} className={`message ${message.who === '나' ? 'mine' : ''}`}><article><small>{message.who}</small><p>{message.text}</p>
          {i === messages.length - 1 && message.who === 'DORI' && replyReceived && showReplyStatus && status !== 'THINKING' && <ReplyStatus state={status} />}
        </article>
        {message.sources.length > 0 && <details className="message-sources"><summary><BookOpen size={14} aria-hidden="true" />참고자료 {message.sources.length}개</summary><ul>{message.sources.map((source, index) => <li key={index}>
          {/^https?:\/\//i.test(source.url || '') ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a> : <span>{source.title}</span>}
          <small>{[source.edition && `${source.edition}년판`, source.page_label ? `${source.page_label}쪽` : source.page_number && `PDF ${source.page_number}쪽`].filter(Boolean).join(' · ')}</small>
        </li>)}</ul></details>}
        </div>)}
        </div>
        {showPendingReply && <div className="message pending-reply"><article><small>DORI</small><ReplyStatus state={status} /></article></div>}
        {!messages.length && !showPendingReply && !recording && <p className="empty">“DGIST는 어떤 곳인가요?”<br/>궁금한 이야기로 시작해 보세요.</p>}
      </div>
    </section><div className="controls" ref={controls}>{audioUrl && needsPlay && <button onClick={() => { audio.current.play().then(() => setNeedsPlay(false)).catch(() => setError('재생 버튼을 다시 눌러 주세요.')); }}>답변 음성 재생 ▶</button>}
      {navigation.status !== 'IDLE' && <div className="navigation-status">
        <div role="status"><MapPin size={18} aria-hidden="true" /><span><strong>{navigation.status === 'ARRIVED' ? `${navigation.name || '목적지'}에 도착했어요` : navigation.status === 'FAILED' ? '길안내를 완료하지 못했어요' : navigation.status === 'STOPPING' ? '길안내를 중지하고 있어요' : `${navigation.name || '목적지'}${navigation.status === 'STARTING' ? ' 안내를 시작하고 있어요' : '(으)로 안내 중'}`}</strong><small>{navigating ? '이동 중에도 편하게 질문하세요' : navigation.status === 'FAILED' ? '목적지를 다시 선택해 주세요' : '계속 이야기할 수 있어요'}</small></span></div>
        {navigating && <button type="button" onClick={stopNavigation} disabled={phase !== 'active' || navigation.status === 'STOPPING'}>길안내 중지</button>}
      </div>}
      {destinations.length > 0 && <div className="destinations">
        <button type="button" className="destinations-toggle" aria-expanded={destinationsOpen} aria-controls="destination-options" disabled={!ready || recording || navigating} onClick={() => setDestinationsOpen(open => !open)}><MapPin size={16} aria-hidden="true" />목적지 선택<ChevronDown size={16} aria-hidden="true" /></button>
        {destinationsOpen && <div id="destination-options" className="destination-chips" aria-label="안내 가능한 목적지">
          {destinations.map(dest => <button key={dest.id} type="button" className="destination-chip"
            disabled={recording || phase !== 'active' || status !== 'READY' || navigating}
            onClick={() => navigate(dest)}>{dest.name} ↗</button>)}
        </div>}
      </div>}
      <form className="text-composer" onSubmit={sendText}>
        <label className="sr-only" htmlFor="visitor-text">텍스트로 이야기하기</label>
        <div className={`text-composer-row ${recording ? 'is-recording' : ''}`}>
          <textarea id="visitor-text" rows={1} maxLength={MAX_TEXT_LENGTH} value={draft}
            placeholder={recording ? '듣고 있어요…' : 'DORI에게 물어보세요'}
            disabled={phase !== 'active' || recording} aria-describedby="composer-hint"
            onChange={event => setDraft(event.target.value)} onKeyDown={textKeyDown}
            onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} />
          <button type={hasDraft && !recording && !responding ? 'submit' : 'button'} className={`composer-action ${recording ? 'recording' : responding ? 'stopping' : ''}`}
            disabled={phase !== 'active' || status === 'CANCELING'} aria-label={actionLabel}
            onClick={responding ? stopResponse : recording || !hasDraft ? () => record() : undefined}>
            {recording ? <Check size={22} aria-hidden="true" /> : responding ? <Square size={20} fill="currentColor" aria-hidden="true" /> : hasDraft ? <ArrowUp size={22} aria-hidden="true" /> : <Mic size={22} aria-hidden="true" />}<span>{recording ? '완료' : responding ? '중지' : hasDraft ? '전송' : '말하기'}</span>
          </button>
        </div>
        <div className="composer-meta"><small id="composer-hint" role={recording ? 'status' : undefined}>{recording ? '말씀을 듣고 있어요 · 말이 끝나면 전송 · 최대 2분' : responding ? '중지를 누르면 현재 대화만 멈춰요' : hasDraft ? 'Enter로 전송 · Shift+Enter로 줄바꿈' : '글이나 음성으로 편하게 질문하세요'}</small>{draft.length > 0 && <small>{draft.length.toLocaleString()} / 1,000자</small>}</div>
      </form>
      {notice && <p className="hint" role="status">{notice}</p>}
      <div className="secondary">{recording && <button onClick={stopResponse} disabled={phase !== 'active'}>녹음 취소</button>}<button onClick={end}>연결 종료</button></div></div></>}
    {phase === 'ended' && <section className="welcome"><div className="orb">또 봐요</div><h1>대화를 마쳤어요.</h1><p>다시 이야기하려면<br/>로봇 화면의 새 QR을 스캔해 주세요.</p></section>}
    {error && <p className="error" role="alert">{error}</p>}
    <footer>함께 걷는 캠퍼스, DORI</footer>
  </main>;
}
createRoot(document.getElementById('root')).render(<App />);
