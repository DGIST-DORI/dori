import { apiFetch } from '../../core/api';
import { useState, useEffect, useCallback } from 'react';
import './BuildingEditorPanel.css';

const API = '/api/knowledge';

function StatusBadge({ status }) {
  const map = {
    idle: ['badge', '—'],
    running: ['badge badge-running', 'RUNNING'],
    ok: ['badge badge-ok', 'OK'],
    error: ['badge badge-error', 'ERROR'],
  };
  const [cls, label] = map[status] ?? map.idle;
  return <span className={cls}>{label}</span>;
}

const EMPTY_BUILDING = {
  bldg_no: '', name_ko: '', name_en: '',
  description_ko: '', description_en: '',
  coordinates: [0.0, 0.0], floor: 1,
  keywords: [], hours: '', facilities: [], url: '',
};

function BuildingEditorPanel() {
  const [buildings, setBuildings] = useState({});
  const [selected, setSelected] = useState(null);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState('idle');
  const [filter, setFilter] = useState('');

  const fetchBuildings = useCallback(async () => {
    try {
      const res = await apiFetch(`${API}/buildings`);
      if (res.ok) setBuildings(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchBuildings(); }, [fetchBuildings]);

  function selectBuilding(key) {
    setSelected(key);
    setDraft({ ...EMPTY_BUILDING, ...buildings[key] });
    setSaveStatus('idle');
  }

  function updateDraft(field, value) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    if (!selected || !draft) return;
    setSaving(true);
    setSaveStatus('running');
    try {
      const res = await apiFetch(`${API}/buildings/${encodeURIComponent(selected)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      await fetchBuildings();
      setSaveStatus('ok');
    } catch {
      setSaveStatus('error');
    }
    setSaving(false);
  }

  const keys = Object.keys(buildings).filter((k) =>
    k.toLowerCase().includes(filter.toLowerCase())
    || (buildings[k].name_ko ?? '').includes(filter)
    || (buildings[k].name_en ?? '').toLowerCase().includes(filter.toLowerCase()),
  );

  const isEmpty = (b) => !b.name_ko && !b.name_en;

  return (
    <div className="layout-panel-body km-building-editor-panel km-panel-wide">
      <div className="km-building-layout">
        <div className="km-building-list">
          <input
            className="input-search"
            placeholder="Search…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="km-building-keys">
            {keys.map((k) => (
              <button
                key={k}
                className={`km-building-key ${selected === k ? 'active' : ''} ${isEmpty(buildings[k]) ? 'empty' : ''}`}
                onClick={() => selectBuilding(k)}
              >
                <span className="km-key-id">{k}</span>
                {isEmpty(buildings[k])
                  ? <span className="km-key-empty">unfilled</span>
                  : <span className="km-key-name">{buildings[k].name_ko}</span>}
              </button>
            ))}
          </div>
        </div>

        <div className="km-building-editor">
          {!draft
            ? <div className="km-empty km-empty-center">Select a building to edit</div>
            : (
              <>
                <div className="km-field-grid">
                  {[
                    ['Name (KO)', 'name_ko', 'text'],
                    ['Name (EN)', 'name_en', 'text'],
                    ['Hours', 'hours', 'text'],
                    ['URL', 'url', 'text'],
                    ['Floor', 'floor', 'number'],
                  ].map(([label, field, type]) => (
                    <label key={field} className="field">
                      <span className="field-label">{label}</span>
                      <input
                        type={type}
                        className="input-km"
                        value={draft[field] ?? ''}
                        onChange={(e) => updateDraft(
                          field,
                          type === 'number' ? Number(e.target.value) : e.target.value,
                        )}
                      />
                    </label>
                  ))}
                  <label className="field km-field-full">
                    <span className="field-label">Description (KO)</span>
                    <textarea
                      className="input-km textarea"
                      value={draft.description_ko ?? ''}
                      onChange={(e) => updateDraft('description_ko', e.target.value)}
                    />
                  </label>
                  <label className="field km-field-full">
                    <span className="field-label">Description (EN)</span>
                    <textarea
                      className="input-km textarea"
                      value={draft.description_en ?? ''}
                      onChange={(e) => updateDraft('description_en', e.target.value)}
                    />
                  </label>
                  <label className="field km-field-full">
                    <span className="field-label">Keywords (comma-separated)</span>
                    <input
                      type="text"
                      className="input-km"
                      value={(draft.keywords ?? []).join(', ')}
                      onChange={(e) => updateDraft(
                        'keywords',
                        e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                      )}
                    />
                  </label>
                  <label className="field km-field-full">
                    <span className="field-label">Facilities (comma-separated)</span>
                    <input
                      type="text"
                      className="input-km"
                      value={(draft.facilities ?? []).join(', ')}
                      onChange={(e) => updateDraft(
                        'facilities',
                        e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                      )}
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">Coord lat</span>
                    <input
                      type="number"
                      step="0.0001"
                      className="input-km"
                      value={draft.coordinates?.[0] ?? 0}
                      onChange={(e) => updateDraft(
                        'coordinates',
                        [parseFloat(e.target.value), draft.coordinates?.[1] ?? 0],
                      )}
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">Coord lng</span>
                    <input
                      type="number"
                      step="0.0001"
                      className="input-km"
                      value={draft.coordinates?.[1] ?? 0}
                      onChange={(e) => updateDraft(
                        'coordinates',
                        [draft.coordinates?.[0] ?? 0, parseFloat(e.target.value)],
                      )}
                    />
                  </label>
                </div>

                <div className="row row-wrap">
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={saving}
                    onClick={handleSave}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    className="btn btn-sm"
                    onClick={() => { setDraft({ ...EMPTY_BUILDING, ...buildings[selected] }); setSaveStatus('idle'); }}
                  >
                    Reset
                  </button>
                  <StatusBadge status={saveStatus} />
                </div>
              </>
            )}
        </div>
      </div>
    </div>
  );
}

export default BuildingEditorPanel;
export { BuildingEditorPanel };
