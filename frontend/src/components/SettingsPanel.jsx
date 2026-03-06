export default function SettingsPanel({ llmUrl, setLlmUrl, llmKey, setLlmKey, llmModel, setLlmModel, availableModels, refreshModels }) {
  return (
    <div className="glass-panel">
      <h3 style={{ marginTop: 0, fontSize: '1.1rem' }}>Quick Settings</h3>
      <div className="form-group">
        <label>LLM Base URL</label>
        <input type="text" value={llmUrl} onChange={(e) => setLlmUrl(e.target.value)} />
      </div>
      <div className="grid-2">
        <div className="form-group">
          <label>API Key</label>
          <input type="password" value={llmKey} onChange={(e) => setLlmKey(e.target.value)} />
        </div>
        <div className="form-group">
          <label>Model</label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <select style={{ flex: 1 }} value={llmModel} onChange={(e) => setLlmModel(e.target.value)}>
              {availableModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <button type="button" className="btn btn-secondary" style={{ padding: '0 0.5rem' }} onClick={refreshModels} title="Refresh Models">
              Refresh
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
