import { useState } from 'react';
import { useStore } from '../core/store';
import { useI18n, detectBrowserLang, LANG_LABELS } from '../core/i18n';
import { AUDIO_OUTPUT_MODES, EXECUTION_PROFILES } from '../core/topicProfiles';
import CloseIcon from '../assets/icons/icon-close.svg?react';
import './SettingsTab.css';

function Section({ title, children }) {
  return (
    <div className="sp-section">
      <div className="sp-section-title">{title}</div>
      <div className="sp-section-body">{children}</div>
    </div>
  );
}

function Row({ label, hint, children }) {
  return (
    <div className="sp-row">
      <div className="sp-row-label">
        <span className="sp-label">{label}</span>
        {hint && <span className="sp-hint">{hint}</span>}
      </div>
      <div className="sp-row-control">{children}</div>
    </div>
  );
}

function Seg({ options, value, onChange }) {
  return (
    <div className="sp-seg">
      {options.map(opt => (
        <button
          key={opt.value}
          className={`sp-seg-btn ${value === opt.value ? 'active' : ''}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function SettingsTab({ themeMode, onThemeModeChange, onClose }) {
  const { t, langPref } = useI18n();
  const setLangPref = useStore(s => s.setLangPref);
  const wsUrl       = useStore(s => s.wsUrl);
  const setWsUrl    = useStore(s => s.setWsUrl);
  const connected   = useStore(s => s.connected);

  const executionProfile = useStore(s => s.executionProfile);
  const setExecutionProfile = useStore(s => s.setExecutionProfile);
  const useClientMic = useStore(s => s.useClientMic);
  const setUseClientMic = useStore(s => s.setUseClientMic);
  const useClientCam = useStore(s => s.useClientCam);
  const setUseClientCam = useStore(s => s.setUseClientCam);
  const audioOutputMode = useStore(s => s.audioOutputMode);
  const setAudioOutputMode = useStore(s => s.setAudioOutputMode);
  const browserTtsWarning = useStore(s => s.browserTtsWarning);
  const rosAudioDebug = useStore(s => s.rosAudioDebug);

  const [wsInput, setWsInput] = useState(wsUrl);
  const detectedLang = detectBrowserLang();


  function handleWsSave() {
    setWsUrl(wsInput.trim());
  }

  const themeOptions = [
    { value: 'light', label: t('settings.theme.light') },
    { value: 'dark',  label: t('settings.theme.dark') },
    { value: 'auto',  label: t('settings.theme.auto') },
  ];

  const langOptions = [
    { value: 'ko',   label: t('settings.lang.ko') },
    { value: 'en',   label: t('settings.lang.en') },
    { value: 'auto', label: t('settings.lang.auto') },
  ];

  return (
    <div className="sp-root">
      <header className="sp-header">
        <h2 className="sp-title">{t('settings.title')}</h2>
        <button className="sp-close-btn" onClick={onClose} aria-label={t('sidebar.close')}>
          <CloseIcon />
        </button>
      </header>

      <Section title={t('settings.section.appearance')}>
        <Row label={t('settings.theme.label')}>
          <Seg options={themeOptions} value={themeMode} onChange={onThemeModeChange} />
        </Row>
      </Section>

      <Section title={t('settings.section.language')}>
        <Row
          label={t('settings.lang.label')}
          hint={langPref === 'auto'
            ? `${t('settings.lang.detected')}: ${LANG_LABELS[detectedLang]}`
            : undefined}
        >
          <Seg options={langOptions} value={langPref} onChange={setLangPref} />
        </Row>
      </Section>

      <Section title={t('settings.section.connection')}>

        <Row label="Execution Profile" hint="Robot=실기체, Sim=ROS 그래프를 실제로 타는 테스트 모드">
          <Seg
            options={[
              { value: EXECUTION_PROFILES.ROBOT, label: 'Robot' },
              { value: EXECUTION_PROFILES.SIM, label: 'Sim' },
            ]}
            value={executionProfile}
            onChange={setExecutionProfile}
          />
        </Row>
        <Row label="Client Microphone">
          <input type="checkbox" checked={useClientMic} onChange={e => setUseClientMic(e.target.checked)} />
        </Row>
        <Row label="Client Camera">
          <input type="checkbox" checked={useClientCam} onChange={e => setUseClientCam(e.target.checked)} />
        </Row>
        <Row label="Speaker Output" hint="모바일 브라우저는 HTTPS/사용자 제스처가 필요할 수 있습니다.">
          <Seg
            options={[
              { value: AUDIO_OUTPUT_MODES.BROWSER_TTS, label: 'browser_tts' },
              { value: AUDIO_OUTPUT_MODES.ROS_AUDIO, label: 'ros_audio' },
            ]}
            value={audioOutputMode}
            onChange={setAudioOutputMode}
          />
        </Row>


        {audioOutputMode === AUDIO_OUTPUT_MODES.BROWSER_TTS && browserTtsWarning && (
          <Row label="Browser TTS Notice">
            <div style={{ color: 'var(--color-error)', fontSize: 12 }}>{browserTtsWarning}</div>
          </Row>
        )}

        {audioOutputMode === AUDIO_OUTPUT_MODES.ROS_AUDIO && (
          <Row label="ROS Audio Debug" hint="수신 패킷/큐 길이/underrun 모니터링">
            <div style={{ fontSize: 12, fontFamily: 'monospace' }}>
              packets={rosAudioDebug?.packets ?? 0} | queue={rosAudioDebug?.queueLength ?? 0} | underrun={rosAudioDebug?.underruns ?? 0}
            </div>
          </Row>
        )}

        <Row label={t('settings.ws.label')} hint={t('settings.ws.hint')}>
          <div className="sp-ws-row">
            <input
              className="sp-ws-input"
              value={wsInput}
              onChange={e => setWsInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleWsSave()}
              disabled={connected}
              spellCheck={false}
              placeholder="ws://localhost:9090"
            />
            <button
              className="sp-ws-save"
              onClick={handleWsSave}
              disabled={connected || wsInput.trim() === wsUrl}
            >
              Save
            </button>
          </div>
        </Row>
      </Section>
    </div>
  );
}
