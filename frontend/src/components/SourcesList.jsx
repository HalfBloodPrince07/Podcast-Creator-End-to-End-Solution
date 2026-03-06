export default function SourcesList({ sources }) {
  if (sources.length === 0) return null;

  return (
    <div>
      <h3 style={{ color: 'var(--accent)' }}>Sources</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {sources.map((s, i) => (
          <div
            key={i}
            style={{
              background: 'var(--bg-surface)',
              padding: '0.75rem',
              borderRadius: '8px',
              border: '1px solid var(--border)',
              fontSize: '0.9rem',
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--primary-light)' }}>
              [SRC-{s.index}] {s.title}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
              {s.publisher} &bull; {s.date}
            </div>
            <div style={{ color: '#D1D5DB' }}>{s.snippet.slice(0, 180)}...</div>
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer"
              style={{ color: 'var(--accent)', fontSize: '0.8rem', marginTop: '0.5rem', display: 'inline-block' }}
            >
              {s.url.slice(0, 80)}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}
