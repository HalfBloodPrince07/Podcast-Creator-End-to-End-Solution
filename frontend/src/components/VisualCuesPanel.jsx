import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { Image as ImageIcon, RotateCcw, Edit3, AlertCircle, Check, X } from 'lucide-react';

import Button from './ui/Button';
import Badge from './ui/Badge';
import { Textarea } from './ui/Input';

function formatTimestamp(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function VisualCuesPanel({ runId }) {
  const [cues, setCues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/episodes/${encodeURIComponent(runId)}/visuals`);
      if (!r.ok) {
        const detail = await r.text();
        throw new Error(detail || `HTTP ${r.status}`);
      }
      const data = await r.json();
      setCues(Array.isArray(data.cues) ? data.cues : []);
    } catch (err) {
      setError(err.message || 'Could not load visual cues');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  if (!runId) return null;

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-4)', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
        Loading visual cues…
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          padding: 'var(--space-3) var(--space-4)',
          background: 'var(--danger-bg)',
          border: '1px solid var(--danger-border)',
          borderRadius: 'var(--radius-md)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          color: 'var(--danger)',
          fontSize: 'var(--text-sm)',
        }}
      >
        <AlertCircle size={14} />
        <span>{error}</span>
      </div>
    );
  }

  if (cues.length === 0) {
    return (
      <div style={{ padding: 'var(--space-4)', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
        No <code>[VISUAL:]</code> cues found for this episode. Generate the video first to create them.
      </div>
    );
  }

  return (
    <section style={{ marginTop: 'var(--space-6)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
        <span
          style={{
            display: 'inline-flex',
            width: 24, height: 24,
            alignItems: 'center', justifyContent: 'center',
            borderRadius: 'var(--radius-xs)',
            background: 'rgba(124, 92, 255, 0.12)',
            color: 'var(--brand-300)',
          }}
        >
          <ImageIcon size={13} />
        </span>
        <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>Visual cues</h3>
        <Badge variant="ghost" size="xs">{cues.length}</Badge>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 'var(--space-3)',
        }}
      >
        {cues.map((cue) => (
          <CueCard key={cue.cue_index} cue={cue} runId={runId} onUpdated={load} />
        ))}
      </div>
    </section>
  );
}

function CueCard({ cue, runId, onUpdated }) {
  const [editing, setEditing] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState(cue.prompt || '');
  const [useCog, setUseCog] = useState(true);
  const [status, setStatus] = useState('idle'); // idle | regen | error
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [thumb, setThumb] = useState(cue.thumbnail_url);

  // Cache-bust the thumbnail when it gets re-rendered
  const thumbSrc = thumb ? `${thumb}?v=${Date.now()}` : null;

  const handleRegen = async (overrides = {}) => {
    setStatus('regen');
    setProgress(0);
    setProgressMsg('Starting…');
    setErrorMsg('');

    const body = {
      run_id: runId,
      cue_index: cue.cue_index,
      prompt: overrides.prompt ?? (editing ? draftPrompt : null),
      seed: null, // server picks a random seed
      use_cogvideox: useCog,
    };

    try {
      await fetchEventSource('/api/visuals/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const data = JSON.parse(ev.data);
            if (data.pct !== undefined) setProgress(data.pct);
            if (data.msg) setProgressMsg(data.msg);
            if (data.done) {
              if (data.error) {
                setErrorMsg(data.error);
                setStatus('error');
              } else {
                if (data.thumbnail_url) setThumb(data.thumbnail_url);
                setStatus('idle');
                setEditing(false);
                onUpdated?.();
              }
            }
          } catch (_) {}
        },
        onerror(err) {
          setErrorMsg('Connection error');
          setStatus('error');
          throw err;
        },
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        setErrorMsg(err.message || 'Regenerate failed');
        setStatus('error');
      }
    }
  };

  return (
    <div
      style={{
        background: 'rgba(0, 0, 0, 0.25)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          aspectRatio: '16 / 9',
          background: 'rgba(0,0,0,0.5)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {thumbSrc ? (
          <img
            src={thumbSrc}
            alt={`Cue ${cue.cue_index + 1}`}
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
        ) : (
          <div
            style={{
              width: '100%', height: '100%',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)',
            }}
          >
            No thumbnail yet
          </div>
        )}
        {status === 'regen' && (
          <div
            style={{
              position: 'absolute', inset: 0,
              background: 'rgba(0,0,0,0.6)',
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              gap: 'var(--space-2)',
              color: 'var(--brand-300)',
              fontSize: 'var(--text-xs)',
            }}
          >
            <span className="tabular-nums" style={{ fontWeight: 600 }}>{progress}%</span>
            <span style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '0 var(--space-3)' }}>
              {progressMsg}
            </span>
          </div>
        )}
      </div>

      <div style={{ padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <Badge variant="ghost" size="xs" className="tabular-nums">#{cue.cue_index + 1}</Badge>
          <Badge variant="ghost" size="xs" className="tabular-nums">
            {formatTimestamp(cue.start_ms)} – {formatTimestamp(cue.end_ms)}
          </Badge>
          {cue.clip_url && <Badge variant="success" size="xs">t2v</Badge>}
        </div>

        {editing ? (
          <Textarea
            value={draftPrompt}
            onChange={(e) => setDraftPrompt(e.target.value)}
            placeholder="Visual prompt…"
            rows={3}
            style={{ fontSize: 'var(--text-xs)', minHeight: 64 }}
          />
        ) : (
          <p
            style={{
              margin: 0,
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
              lineHeight: 'var(--leading-snug)',
              display: '-webkit-box',
              WebkitLineClamp: 3,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
            title={cue.prompt}
          >
            {cue.prompt || <em style={{ color: 'var(--text-tertiary)' }}>No prompt</em>}
          </p>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
          <input
            type="checkbox"
            checked={useCog}
            onChange={(e) => setUseCog(e.target.checked)}
            disabled={status === 'regen'}
          />
          Use CogVideoX (slower, ~10-15 min)
        </label>

        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {editing ? (
            <>
              <Button
                variant="primary"
                size="sm"
                iconLeft={<Check size={11} />}
                onClick={() => handleRegen({ prompt: draftPrompt })}
                disabled={status === 'regen'}
              >
                Save & re-roll
              </Button>
              <Button
                variant="secondary"
                size="sm"
                iconLeft={<X size={11} />}
                onClick={() => { setEditing(false); setDraftPrompt(cue.prompt || ''); }}
                disabled={status === 'regen'}
              >
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="primary"
                size="sm"
                iconLeft={<RotateCcw size={11} />}
                onClick={() => handleRegen()}
                disabled={status === 'regen'}
              >
                Re-roll
              </Button>
              <Button
                variant="secondary"
                size="sm"
                iconLeft={<Edit3 size={11} />}
                onClick={() => setEditing(true)}
                disabled={status === 'regen'}
              >
                Edit prompt
              </Button>
            </>
          )}
        </div>

        {status === 'error' && errorMsg && (
          <div
            style={{
              padding: 'var(--space-2) var(--space-3)',
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--danger)',
              fontSize: 'var(--text-2xs)',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
            }}
          >
            <AlertCircle size={11} /> {errorMsg}
          </div>
        )}
      </div>
    </div>
  );
}
