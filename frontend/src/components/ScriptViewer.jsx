export default function ScriptViewer({ script }) {
  if (script.length === 0) return null;

  return (
    <div style={{ marginBottom: '2rem' }}>
      <h3 style={{ color: 'var(--accent)' }}>Script Segments</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {script.map((seg, i) => (
          <details
            key={i}
            style={{
              background: 'var(--bg-surface)',
              padding: '0.75rem',
              borderRadius: '8px',
              border: '1px solid var(--border)',
            }}
          >
            <summary style={{ cursor: 'pointer', fontWeight: 500, color: 'var(--primary-light)' }}>
              {seg.name}{' '}
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginLeft: '0.5rem' }}>
                (~{seg.actual_words} words / ~{seg.target_seconds}s)
              </span>
            </summary>
            <div style={{ marginTop: '1rem', whiteSpace: 'pre-wrap', color: '#E2E8F0', lineHeight: 1.6 }}>
              {seg.text}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
