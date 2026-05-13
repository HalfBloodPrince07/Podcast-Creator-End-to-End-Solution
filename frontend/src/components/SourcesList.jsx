import { ExternalLink, Link2 } from 'lucide-react';
import Badge from './ui/Badge';

function hostnameOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

function faviconUrl(url) {
  const h = hostnameOf(url);
  if (!h) return null;
  return `https://www.google.com/s2/favicons?sz=64&domain=${h}`;
}

export default function SourcesList({ sources }) {
  if (!sources || sources.length === 0) return null;

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
        <span
          style={{
            display: 'inline-flex',
            width: 24, height: 24,
            alignItems: 'center', justifyContent: 'center',
            borderRadius: 'var(--radius-xs)',
            background: 'rgba(77, 208, 225, 0.12)',
            color: 'var(--accent-cyan)',
          }}
        >
          <Link2 size={13} />
        </span>
        <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>Sources</h3>
        <Badge variant="ghost" size="xs">{sources.length}</Badge>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 'var(--space-3)',
        }}
      >
        {sources.map((s, i) => {
          const fav = faviconUrl(s.url);
          const host = hostnameOf(s.url);
          return (
            <a
              key={`${s.index}-${i}`}
              href={s.url}
              target="_blank"
              rel="noreferrer"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-2)',
                padding: 'var(--space-4)',
                background: 'rgba(0, 0, 0, 0.25)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                color: 'inherit',
                transition: 'all 0.18s var(--ease-snap)',
                minWidth: 0,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-strong)';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-subtle)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', minWidth: 0 }}>
                {fav && (
                  <img
                    src={fav}
                    alt=""
                    width={16}
                    height={16}
                    style={{
                      borderRadius: 4,
                      flexShrink: 0,
                      background: 'rgba(255, 255, 255, 0.06)',
                    }}
                  />
                )}
                <span
                  style={{
                    fontSize: 'var(--text-2xs)',
                    fontWeight: 600,
                    color: 'var(--text-tertiary)',
                    letterSpacing: 'var(--tracking-wide)',
                    textTransform: 'uppercase',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {host || `Source ${s.index}`}
                </span>
                <Badge variant="ghost" size="xs" style={{ marginLeft: 'auto' }}>
                  #{s.index}
                </Badge>
              </div>

              <div
                style={{
                  fontSize: 'var(--text-sm)',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  letterSpacing: 'var(--tracking-tight)',
                  lineHeight: 'var(--leading-snug)',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {s.title}
              </div>

              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
                {s.publisher}{s.publisher && s.date ? ' · ' : ''}{s.date}
              </div>

              {s.snippet && (
                <p
                  style={{
                    margin: 0,
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-secondary)',
                    lineHeight: 'var(--leading-relaxed)',
                    display: '-webkit-box',
                    WebkitLineClamp: 3,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}
                >
                  {s.snippet}
                </p>
              )}

              <div
                style={{
                  marginTop: 'auto',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  fontSize: 'var(--text-2xs)',
                  color: 'var(--accent-cyan)',
                  fontWeight: 500,
                }}
              >
                Open source <ExternalLink size={10} />
              </div>
            </a>
          );
        })}
      </div>
    </section>
  );
}
