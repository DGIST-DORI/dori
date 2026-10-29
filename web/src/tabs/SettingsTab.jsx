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
        <Row
          label={t('settings.audioOutput.label')}
          hint={t('settings.audioOutput.hint')}
        >
          <Seg
            options={[
              { value: AUDIO_OUTPUT_MODES.BROWSER_TTS, label: t('settings.audioOutput.mode.browserTts') },
              { value: AUDIO_OUTPUT_MODES.ROS_AUDIO, label: t('settings.audioOutput.mode.rosAudio') },
            ]}
            value={audioOutputMode}
            onChange={setAudioOutputMode}
          />
        </Row>


        {audioOutputMode === AUDIO_OUTPUT_MODES.BROWSER_TTS && (
          <Row
            label={t('settings.audioOutput.mode.browserTts')}
            hint={t('settings.audioOutput.modeHint.browserTts')}
          >
            {browserTtsWarning ? (
              <div style={{ color: 'var(--color-error)', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
                <span
                  style={{
                    padding: '2px 6px',
                    borderRadius: 999,
                    background: 'color-mix(in srgb, var(--color-error) 15%, transparent)',
                    border: '1px solid color-mix(in srgb, var(--color-error) 35%, transparent)',
                    fontWeight: 700,
                    letterSpacing: 0.2,
                  }}
                >
                  {t('settings.audioOutput.conflict.badge')}
                </span>
                <span>{t('settings.audioOutput.conflict.text')}</span>
              </div>
            ) : (
              <div style={{ fontSize: 12 }}>{t('settings.audioOutput.modeHelp.browserTts')}</div>
            )}
            {browserTtsWarning && (
              <div style={{ color: 'var(--color-error)', fontSize: 12, marginTop: 4 }}>{browserTtsWarning}</div>
            )}
          </Row>
        )}

        {audioOutputMode === AUDIO_OUTPUT_MODES.ROS_AUDIO && (
          <Row
            label={t('settings.audioOutput.mode.rosAudio')}
            hint={t('settings.audioOutput.modeHint.rosAudio')}
          >
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
