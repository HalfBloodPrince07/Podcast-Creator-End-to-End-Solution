import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion, AnimatePresence } from 'framer-motion';

export default function EpisodeLibrary() {
  const [episodes, setEpisodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    fetchEpisodes();
  }, []);

  const fetchEpisodes = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/episodes');
      const data = await res.json();
      setEpisodes(data.episodes || []);
    } catch {
      setEpisodes([]);
    }
    setLoading(false);
  };

  const openDetail = async (runId) => {
    setSelected(runId);
    setDetail(null);
    try {
      const res = await fetch(`/api/episodes/${encodeURIComponent(runId)}`);
      if (res.ok) setDetail(await res.json());
    } catch { /* ignore */ }
  };

  if (loading) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <motion.div animate={{ opacity: [0.5, 1, 0.5] }} transition={{ repeat: Infinity, duration: 1.5 }}>
          <span style={{ color: 'var(--text-muted)' }}>Loading episodes...</span>
        </motion.div>
      </div>
    );
  }

  if (episodes.length === 0) {
    return (
      <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
        <p style={{ color: 'var(--text-muted)', margin: 0 }}>No episodes yet. Generate your first podcast above!</p>
      </div>
    );
  }

  // Detail view
  if (selected && detail) {
    return (
      <motion.div
        className="glass-panel"
        style={{ padding: 0 }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: '1.5rem' }}>{detail.episode_title || 'Episode'}</h2>
          <button className="btn btn-secondary" style={{ fontSize: '0.85rem', padding: '0.4rem 1rem' }} onClick={() => { setSelected(null); setDetail(null); }}>
            &larr; Back to Library
          </button>
        </div>
        <div style={{ padding: '1.5rem' }}>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            <span className="status-badge" style={{ background: 'rgba(255,255,255,0.05)', border: 'none' }}>Topic: {detail.podcast_topic}</span>
            <span className="status-badge" style={{ background: 'rgba(255,255,255,0.05)', border: 'none' }}>Tone: {detail.tone}</span>
            <span className="status-badge" style={{ background: 'rgba(255,255,255,0.05)', border: 'none' }}>Dur: {detail.duration_hms || `${Math.round((detail.duration_seconds || 0) / 60)}m`}</span>
            {detail.dry_run && <span style={{ color: 'var(--accent-warm)' }}>Dry Run</span>}
          </div>

          {detail.files?.audio_url && (
            <motion.div style={{ marginBottom: '2rem' }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
              <h3 style={{ color: 'var(--accent)', marginBottom: '1rem' }}>Audio</h3>
              <audio src={detail.files.audio_url} controls style={{ width: '100%' }} />
              <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                {Object.entries(detail.files).map(([key, url]) => (
                  <a key={key} href={url} target="_blank" rel="noreferrer" download className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>
                    {key.replace('_url', '').toUpperCase()}
                  </a>
                ))}
              </div>
            </motion.div>
          )}

          {detail.show_notes && (
            <motion.div
              className="markdown-content"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}
              style={{ background: 'rgba(0,0,0,0.3)', padding: '1.5rem', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)', boxShadow: 'inset 0 2px 10px rgba(0,0,0,0.2)' }}
            >
              <ReactMarkdown>{detail.show_notes}</ReactMarkdown>
            </motion.div>
          )}
        </div>
      </motion.div>
    );
  }

  // List view
  return (
    <div className="glass-panel" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.02)' }}>
        <h2 style={{ margin: 0, fontSize: '1.4rem' }}>Episode Library</h2>
        <button className="btn btn-secondary" style={{ fontSize: '0.85rem', padding: '0.4rem 1rem' }} onClick={fetchEpisodes}>
          Refresh
        </button>
      </div>
      <motion.div
        style={{ display: 'flex', flexDirection: 'column' }}
        variants={{
          hidden: { opacity: 0 },
          show: { opacity: 1, transition: { staggerChildren: 0.05 } }
        }}
        initial="hidden"
        animate="show"
      >
        {episodes.map((ep) => (
          <motion.div
            key={ep.run_id}
            variants={{
              hidden: { opacity: 0, x: -20 },
              show: { opacity: 1, x: 0 }
            }}
            onClick={() => openDetail(ep.run_id)}
            style={{
              padding: '1.25rem 1.5rem',
              borderBottom: '1px solid rgba(255,255,255,0.05)',
              cursor: 'pointer',
              transition: 'background 0.2s',
            }}
            whileHover={{ backgroundColor: 'rgba(124, 58, 237, 0.1)', paddingLeft: '2rem' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontWeight: 600, color: 'var(--primary-light)', fontSize: '1.1rem' }}>{ep.title}</div>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                  {ep.tone} &bull; {ep.duration_hms || `${Math.round((ep.duration_seconds || 0) / 60)}m`} &bull; {ep.actual_words} words
                  {ep.dry_run && <span style={{ color: 'var(--accent-warm)', marginLeft: '0.5rem', fontWeight: 'bold' }}>DRY RUN</span>}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                {ep.has_audio && <span style={{ color: 'var(--success)', fontSize: '0.8rem', background: 'rgba(16, 185, 129, 0.1)', padding: '2px 8px', borderRadius: '10px' }}>AUDIO</span>}
                <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{ep.generated_at?.slice(0, 10)}</span>
              </div>
            </div>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}
