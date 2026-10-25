import { useState } from 'react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import { useI18n } from '../../core/i18n';

function pub(topic, msgType, data) {
  try {
    publishROS(topic, msgType, data);
    return true;
  } catch (e) {
    console.error('[pub] failed:', topic, e);
    return false;
  }
}

function SectionLabel({ children }) {
  return <div className="panel-section-label">{children}</div>;
}

function LLMInjectPanel() {
  const { t } = useI18n();
  const connected = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const addLog = useStore(s => s.addLog);
  const lastLlmResp = useStore(s => s.lastLlmResponse);
  const canPublish = connected || isDemoMode;

  const [llmQuery, setLlmQuery] = useState('');
  const [locCtx, setLocCtx] = useState('');

  function handleLLM() {
    if (!llmQuery.trim()) return;

    const payload = {
      text: llmQuery.trim(),
      user_text: llmQuery.trim(),
      location_context: locCtx.trim(),
      confidence: 1.0,
      timestamp: Date.now() / 1000,
      source: 'dashboard_inject',
    };

    pub('/dori/stt/result', 'std_msgs/msg/String', { data: JSON.stringify(payload) });
    addLog(LOG_TAGS.LLM, `[inject] "${llmQuery.trim()}"`);
    setLlmQuery('');
  }

  return (
    <div className="panel-body">
      <SectionLabel>LLM Query Injection → /dori/stt/result</SectionLabel>
      <textarea
        className="input-text"
        rows={2}
        placeholder={t('panel.llm.query.placeholder')}
        value={llmQuery}
        onChange={e => setLlmQuery(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleLLM(); } }}
      />
      <div className="field field-full">
        <label className="field-label">Location context (optional)</label>
        <input
          className="input input-full"
          type="text"
          placeholder={t('panel.llm.location.placeholder')}
          value={locCtx}
          onChange={e => setLocCtx(e.target.value)}
        />
      </div>
      <button className="btn btn-sm btn-primary" disabled={!canPublish || !llmQuery.trim()} onClick={handleLLM}>
        Send to LLM
      </button>
      {lastLlmResp && (
        <div className="result-row result-row-col">
          <span className="result-label">LLM response</span>
          <span className="result-value">{typeof lastLlmResp === 'string' ? lastLlmResp : JSON.stringify(lastLlmResp)}</span>
        </div>
      )}
    </div>
  );
}

export default LLMInjectPanel;
export { LLMInjectPanel };
