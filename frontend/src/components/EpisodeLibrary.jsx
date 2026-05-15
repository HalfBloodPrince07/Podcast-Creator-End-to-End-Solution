import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import {
  Search, RefreshCw, Trash2, ArrowLeft, Library,
  Headphones, Clock, Type, RotateCcw, BookOpen, AlertCircle,
} from 'lucide-react';

import Card, { CardHeader, CardTitle } from './ui/Card';
import Button from './ui/Button';
import IconButton from './ui/IconButton';
import Tooltip from './ui/Tooltip';
import Badge from './ui/Badge';
import EmptyState from './ui/EmptyState';
import Skeleton from './ui/Skeleton';
import { Input } from './ui/Input';
import AudioPlayer from './AudioPlayer';
import ScriptViewer from './ScriptViewer';
import { VideoSection } from './ResultsPanel';
import VisualCuesPanel from './VisualCuesPanel';

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

function formatDuration(ep) {
  if (ep.duration_hms) return ep.duration_hms;
  const s = ep.duration_seconds || 0;
  return `${Math.round(s / 60)}m`;
}

export default function EpisodeLibrary() {
  const [episodes, setEpisodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [regenState, setRegenState] = useState({ name: null, pct: 0, msg: '' });
  // Bumped after a per-cue re-roll auto-recomposites episode.mp4, so the
  // <video> tag refetches the updated file instead of using the cached one.
  const [libraryVideoCacheBust, setLibraryVideoCacheBust] = useState(0);
  const [query, setQuery] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(null); // runId

  useEffect(() => { fetchEpisodes(); }, []);

  async function fetchEpisodes() {
    setLoading(true);
    try {
      const res = await fetch('/api/episodes');
      const data = await res.json();
      setEpisodes(data.episodes || []);
    } catch {
      setEpisodes([]);
    }
    setLoading(false);
  }

  async function openDetail(runId) {
    setSelected(runId);
    setDetail(null);
    try {
      const res = await fetch(`/api/episodes/${encodeURIComponent(runId)}`);
      if (res.ok) setDetail(await res.json());
    } catch { /* ignore */ }
  }

  async function regenerateSegment(runId, segmentName) {
    setRegenState({ name: segmentName, pct: 0, msg: 'Starting…' });
    try {
      await fetchEventSource('/api/regenerate-segment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId, segment_name: segmentName }),
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const data = JSON.parse(ev.data);
            if (data.pct !== undefined) setRegenState({ name: segmentName, pct: data.pct, msg: data.msg || '' });
            if (data.done) {
              setRegenState({ name: null, pct: 0, msg: '' });
              openDetail(runId);
            }
          } catch { /* ignore */ }
        },
        onerror() {
          setRegenState({ name: null, pct: 0, msg: '' });
          throw new Error('SSE error');
        },
      });
    } catch {
      setRegenState({ name: null, pct: 0, msg: '' });
    }
  }

  async function deleteEpisode(runId) {
    setDeletingId(runId);
    setConfirmDelete(null);
    try {
      const res = await fetch(`/api/episodes/${encodeURIComponent(runId)}`, { method: 'DELETE' });
      if (res.ok) {
        setEpisodes((prev) => prev.filter((ep) => ep.run_id !== runId));
        if (selected === runId) { setSelected(null); setDetail(null); }
      }
    } finally {
      setDeletingId(null);
    }
  }

  // ── List loading ────────────────────────────────────────────────
  if (loading) {
    return (
      <Card padding="md">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 'var(--space-4)',
                alignItems: 'center',
                padding: 'var(--space-3)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
              }}
            >
              <Skeleton width={96} height={54} radius="var(--radius-xs)" />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                <Skeleton width="60%" height={14} />
                <Skeleton width="40%" height={10} />
              </div>
            </div>
          ))}
        </div>
      </Card>
    );
  }

  // ── Empty ───────────────────────────────────────────────────────
  if (episodes.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Library size={22} />}
          title="No episodes yet"
          description="Generate your first podcast on the Generate tab. Episodes you create will appear here."
        />
      </Card>
    );
  }

  // ── Detail view ─────────────────────────────────────────────────
  if (selected && detail) {
    const fileMap = detail.files || {};
    return (
      <Card padding="none">
        <CardHeader>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', minWidth: 0 }}>
            <IconButton
              variant="ghost"
              onClick={() => { setSelected(null); setDetail(null); }}
              title="Back to library"
            >
              <ArrowLeft size={16} />
            </IconButton>
            <CardTitle eyebrow="Episode">{detail.episode_title || 'Episode'}</CardTitle>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <Button
              variant="destructive"
              size="sm"
              iconLeft={<Trash2 size={13} />}
              onClick={() => deleteEpisode(selected)}
              loading={deletingId === selected}
            >
              Delete
            </Button>
          </div>
        </CardHeader>

        <div style={{ padding: 'var(--space-6)' }}>
          {detail.thumbnail_path && (
            <img
              src={`/outputs/${detail.run_id || ''}/thumbnail.png`}
              alt=""
              onError={(e) => { e.target.style.display = 'none'; }}
              style={{
                width: '100%',
                maxWidth: 720,
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-default)',
                marginBottom: 'var(--space-5)',
              }}
            />
          )}

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginBottom: 'var(--space-5)' }}>
            <Badge variant="ghost" size="sm">Topic: {detail.podcast_topic}</Badge>
            <Badge variant="ghost" size="sm">Tone: {detail.tone}</Badge>
            <Badge variant="ghost" size="sm" icon={<Clock size={11} />}>{formatDuration(detail)}</Badge>
            {detail.dry_run && <Badge variant="warning" size="sm">Dry run</Badge>}
          </div>

          {fileMap.audio_url && (
            <div style={{ marginBottom: 'var(--space-7)' }}>
              <AudioPlayer
                results={{
                  audio_url: fileMap.audio_url,
                  srt_url: fileMap.srt_url,
                  txt_url: fileMap.txt_url,
                  notes_url: fileMap.notes_url,
                }}
              />
              <VideoSection
                results={{
                  audio_url: fileMap.audio_url,
                  srt_url: fileMap.srt_url || '',
                  video_url: fileMap.video_url || null,
                  metadata: { episode_title: detail.episode_title },
                }}
                cacheBust={libraryVideoCacheBust}
              />
              <VisualCuesPanel
                runId={selected}
                onVideoUpdated={() => setLibraryVideoCacheBust((v) => v + 1)}
              />
            </div>
          )}

          {detail.segments?.length > 0 && (
            <div style={{ marginBottom: 'var(--space-7)' }}>
              <ScriptViewer script={detail.segments} />

              {/* Regenerate controls — separate from viewer for clarity */}
              <div style={{ marginTop: 'var(--space-4)' }}>
                {detail.segments.map((seg) => {
                  const isRegen = regenState.name === seg.name;
                  return (
                    <div
                      key={seg.name}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-3)',
                        padding: 'var(--space-2) var(--space-3)',
                        fontSize: 'var(--text-xs)',
                        color: 'var(--text-tertiary)',
                      }}
                    >
                      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {seg.name}
                      </span>
                      <Button
                        variant="secondary"
                        size="sm"
                        iconLeft={<RotateCcw size={11} />}
                        onClick={() => regenerateSegment(selected, seg.name)}
                        disabled={regenState.name !== null}
                      >
                        {isRegen ? `${regenState.pct}%` : 'Regenerate'}
                      </Button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {detail.show_notes && (
            <div>
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
                  <BookOpen size={13} />
                </span>
                <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>Show notes</h3>
              </div>
              <div
                className="markdown-content"
                style={{
                  background: 'rgba(0, 0, 0, 0.25)',
                  padding: 'var(--space-5) var(--space-6)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                  boxShadow: 'inset 0 1px 8px rgba(0, 0, 0, 0.2)',
                }}
              >
                <ReactMarkdown>{detail.show_notes}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </Card>
    );
  }

  // ── List view ──────────────────────────────────────────────────
  const filtered = query
    ? episodes.filter((ep) =>
        (ep.title || '').toLowerCase().includes(query.toLowerCase()) ||
        (ep.podcast_topic || '').toLowerCase().includes(query.toLowerCase()),
      )
    : episodes;

  return (
    <Card padding="none">
      <CardHeader>
        <CardTitle eyebrow="Library">Episodes</CardTitle>
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <Badge variant="ghost" size="sm">{episodes.length}</Badge>
          <Tooltip label="Refresh">
            <IconButton variant="ghost" onClick={fetchEpisodes} title="Refresh">
              <RefreshCw size={14} />
            </IconButton>
          </Tooltip>
        </div>
      </CardHeader>

      <div
        style={{
          padding: 'var(--space-4) var(--space-6)',
          borderBottom: '1px solid var(--border-subtle)',
          background: 'rgba(0, 0, 0, 0.15)',
        }}
      >
        <Input
          placeholder="Search by title or topic…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          iconLeft={<Search size={13} />}
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<Search size={20} />}
          title="No matches"
          description="Try a different search term."
        />
      ) : (
        <motion.div
          style={{ display: 'flex', flexDirection: 'column' }}
          variants={{ hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.04 } } }}
          initial="hidden"
          animate="show"
        >
          {filtered.map((ep) => (
            <motion.div
              key={ep.run_id}
              variants={{ hidden: { opacity: 0, y: 6 }, show: { opacity: 1, y: 0 } }}
              onClick={() => openDetail(ep.run_id)}
              whileHover={{ backgroundColor: 'rgba(124, 92, 255, 0.05)' }}
              style={{
                padding: 'var(--space-4) var(--space-6)',
                borderBottom: '1px solid var(--border-subtle)',
                cursor: 'pointer',
                display: 'flex',
                gap: 'var(--space-4)',
                alignItems: 'center',
                transition: 'background 0.18s var(--ease-snap)',
              }}
            >
              <div
                style={{
                  width: 96, height: 54,
                  flexShrink: 0,
                  borderRadius: 'var(--radius-xs)',
                  overflow: 'hidden',
                  background: 'linear-gradient(135deg, rgba(124, 92, 255, 0.25), rgba(91, 127, 255, 0.15))',
                  border: '1px solid var(--border-subtle)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                {ep.thumbnail_url ? (
                  <img src={ep.thumbnail_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                ) : (
                  <Headphones size={18} color="rgba(180, 165, 255, 0.6)" />
                )}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: 'var(--text-sm)',
                    color: 'var(--text-primary)',
                    letterSpacing: 'var(--tracking-tight)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {ep.title || ep.podcast_topic || 'Untitled episode'}
                </div>
                <div
                  style={{
                    display: 'flex',
                    gap: 'var(--space-3)',
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-tertiary)',
                    marginTop: 4,
                    flexWrap: 'wrap',
                  }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <Type size={10} /> {ep.tone}
                  </span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <Clock size={10} /> {formatDuration(ep)}
                  </span>
                  <span>{ep.actual_words ?? 0} words</span>
                  {ep.dry_run && <Badge variant="warning" size="xs">Dry run</Badge>}
                </div>
              </div>

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--space-2)',
                  flexShrink: 0,
                }}
              >
                {ep.has_audio && <Badge variant="success" size="xs" icon={<Headphones size={9} />}>Audio</Badge>}
                <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', minWidth: 80, textAlign: 'right' }}>
                  {formatDate(ep.generated_at)}
                </span>
                {confirmDelete === ep.run_id ? (
                  <span style={{ display: 'inline-flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => deleteEpisode(ep.run_id)}
                      loading={deletingId === ep.run_id}
                    >
                      Confirm
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmDelete(null)}
                    >
                      Cancel
                    </Button>
                  </span>
                ) : (
                  <Tooltip label="Delete">
                    <IconButton
                      variant="ghost"
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); setConfirmDelete(ep.run_id); }}
                      title="Delete episode"
                      disabled={deletingId === ep.run_id}
                    >
                      <Trash2 size={13} />
                    </IconButton>
                  </Tooltip>
                )}
              </div>
            </motion.div>
          ))}
        </motion.div>
      )}

      <AnimatePresence>
        {regenState.name && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            style={{
              position: 'fixed',
              bottom: 'var(--space-6)',
              right: 'var(--space-6)',
              padding: 'var(--space-3) var(--space-4)',
              background: 'var(--surface-3)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-lg)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              zIndex: 50,
            }}
          >
            <RefreshCw size={12} color="var(--brand-300)" style={{ animation: 'spin 1s linear infinite' }} />
            Regenerating <strong style={{ color: 'var(--brand-300)' }}>{regenState.name}</strong> — {regenState.pct}%
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
