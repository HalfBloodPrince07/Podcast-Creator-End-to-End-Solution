import { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { Play, Film, RotateCcw, Download, AlertCircle, BookOpen, Headphones } from 'lucide-react';

import AudioPlayer from './AudioPlayer';
import ScriptViewer from './ScriptViewer';
import SourcesList from './SourcesList';
import VisualCuesPanel from './VisualCuesPanel';
import Card, { CardHeader, CardTitle } from './ui/Card';
import Button from './ui/Button';
import Badge from './ui/Badge';

export function VideoSection({ results, autoVideo = false, cacheBust = 0, videoMode = 'slideshow' }) {
  const initialUrl = results?.video_url || null;
  const [status, setStatus] = useState(initialUrl ? 'done' : 'idle'); // idle | generating | done | error
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState('');
  const [videoUrl, setVideoUrl] = useState(initialUrl);
  const [errorMsg, setErrorMsg] = useState('');
  // Guard so the auto-fire only happens once per results payload — re-renders
  // (status changes, parent re-renders) must not retrigger generation.
  const autoFiredRef = useRef(false);

  // useCallback so the auto-fire effect can depend on a stable reference.
  const handleGenerate = useCallback(async () => {
    if (!results?.audio_url) return;
    setStatus('generating');
    setProgress(0);
    setProgressMsg('Starting…');
    setVideoUrl(null);
    setErrorMsg('');

    try {
      await fetchEventSource('/api/generate-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio_url: results.audio_url,
          srt_url: results.srt_url || '',
          title: results.metadata?.episode_title || 'Podcast Episode',
          video_mode: videoMode,
        }),
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const data = JSON.parse(ev.data);
            if (data.pct !== undefined) setProgress(data.pct);
            if (data.msg) setProgressMsg(data.msg);
            if (data.done) {
              if (data.video_url) { setVideoUrl(data.video_url); setStatus('done'); }
              else { setErrorMsg(data.error || 'Video generation failed'); setStatus('error'); }
            }
          } catch (_) {}
        },
        onerror(err) {
          setErrorMsg('Connection error during video generation');
          setStatus('error');
          throw err;
        },
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        setErrorMsg(err.message || 'Unknown error');
        setStatus('error');
      }
    }
  }, [results?.audio_url, results?.srt_url, results?.metadata?.episode_title, videoMode]);

  // Reset the auto-fire guard whenever a fresh `results` payload arrives
  // (i.e. the user kicked off a new generation).
  useEffect(() => { autoFiredRef.current = false; }, [results?.audio_url]);

  // Auto-fire video gen exactly once when:
  //   - the user enabled "Auto-generate video" on the form,
  //   - we have a fresh audio result with no existing video,
  //   - and we haven't already fired for this payload.
  useEffect(() => {
    if (!autoVideo) return;
    if (autoFiredRef.current) return;
    if (status !== 'idle') return;
    if (!results?.audio_url || results?.video_url) return;
    autoFiredRef.current = true;
    handleGenerate();
  }, [autoVideo, status, results?.audio_url, results?.video_url, handleGenerate]);

  if (!results?.audio_url) return null;

  return (
    <section style={{ marginTop: 'var(--space-6)' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-3)',
        }}
      >
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
          <Film size={13} />
        </span>
        <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>YouTube video</h3>
        <Badge variant="ghost" size="xs">1080p</Badge>
      </div>

      {status === 'idle' && (
        <div
          style={{
            padding: 'var(--space-5)',
            background: 'rgba(0, 0, 0, 0.25)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-4)',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
            <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
              Render the episode as a 1080p MP4
            </span>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
              Burns subtitles & generates a waveform visualisation. May take several minutes.
            </span>
          </div>
          <Button variant="primary" size="md" iconLeft={<Play size={13} fill="currentColor" />} onClick={handleGenerate}>
            Generate video
          </Button>
        </div>
      )}

      {status === 'generating' && (
        <div
          style={{
            padding: 'var(--space-5)',
            background: 'rgba(0, 0, 0, 0.25)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: 'var(--space-2)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
            }}
          >
            <span>{progressMsg}</span>
            <span className="tabular-nums" style={{ color: 'var(--brand-300)', fontWeight: 600 }}>
              {progress}%
            </span>
          </div>
          <div
            style={{
              height: 4,
              borderRadius: 'var(--radius-pill)',
              background: 'rgba(255, 255, 255, 0.06)',
              overflow: 'hidden',
            }}
          >
            <motion.div
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              style={{
                height: '100%',
                background: 'var(--brand-gradient)',
                backgroundSize: '200% 100%',
                animation: 'bg-pan 4s linear infinite',
                boxShadow: '0 0 12px var(--brand-glow)',
              }}
            />
          </div>
          <p
            style={{
              marginTop: 'var(--space-3)',
              fontSize: 'var(--text-2xs)',
              color: 'var(--text-tertiary)',
            }}
          >
            This may take several minutes depending on episode length…
          </p>
        </div>
      )}

      {status === 'done' && videoUrl && (
        <div>
          <video
            key={cacheBust}
            src={cacheBust > 0 ? `${videoUrl}?v=${cacheBust}` : videoUrl}
            controls
            style={{
              width: '100%',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-default)',
              marginBottom: 'var(--space-3)',
            }}
          />
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <Button
              variant="primary"
              size="md"
              iconLeft={<Download size={13} />}
              onClick={() => window.open(videoUrl, '_blank')}
            >
              Download MP4
            </Button>
            <Button
              variant="secondary"
              size="md"
              iconLeft={<RotateCcw size={13} />}
              onClick={() => { setStatus('idle'); setVideoUrl(null); }}
            >
              Regenerate
            </Button>
          </div>
        </div>
      )}

      {status === 'error' && (
        <div
          style={{
            padding: 'var(--space-4)',
            background: 'var(--danger-bg)',
            border: '1px solid var(--danger-border)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-3)',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <AlertCircle size={16} color="var(--danger)" />
            <span style={{ fontSize: 'var(--text-sm)', color: 'var(--danger)', fontWeight: 500 }}>
              {errorMsg}
            </span>
          </div>
          <Button variant="secondary" size="sm" onClick={() => setStatus('idle')}>
            Try again
          </Button>
        </div>
      )}
    </section>
  );
}

function SectionHeading({ icon, title, accent }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
      <span
        style={{
          display: 'inline-flex',
          width: 24, height: 24,
          alignItems: 'center', justifyContent: 'center',
          borderRadius: 'var(--radius-xs)',
          background: accent === 'cyan' ? 'rgba(77, 208, 225, 0.12)' : 'rgba(124, 92, 255, 0.12)',
          color: accent === 'cyan' ? 'var(--accent-cyan)' : 'var(--brand-300)',
        }}
      >
        {icon}
      </span>
      <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>{title}</h3>
    </div>
  );
}

export default function ResultsPanel({ results, script, sources, autoVideo = false, videoMode = 'slideshow' }) {
  const hasContent = results || script.length > 0 || sources.length > 0;
  // Bumped whenever a per-cue re-roll auto-recomposites episode.mp4. The
  // VideoSection appends this to the video src so the browser refetches
  // the updated file instead of serving its cached copy.
  const [videoCacheBust, setVideoCacheBust] = useState(0);
  if (!hasContent) return null;

  return (
    <Card padding="none">
      <CardHeader>
        <CardTitle eyebrow="Output">Results</CardTitle>
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {results?.audio_url && <Badge variant="success" size="sm" icon={<Headphones size={11} />}>Audio ready</Badge>}
          {results?.show_notes && <Badge variant="info" size="sm" icon={<BookOpen size={11} />}>Show notes</Badge>}
          {sources?.length > 0 && <Badge variant="ghost" size="sm">{sources.length} sources</Badge>}
        </div>
      </CardHeader>

      <div style={{ padding: 'var(--space-6)' }}>
        <AnimatePresence>
          {results && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08 }}
            >
              <AudioPlayer results={results} />
            </motion.div>
          )}

          {results?.audio_url && <VideoSection results={results} autoVideo={autoVideo} cacheBust={videoCacheBust} videoMode={videoMode} />}
          {results?.metadata?.run_id && (
            <VisualCuesPanel
              runId={results.metadata.run_id}
              onVideoUpdated={() => setVideoCacheBust((v) => v + 1)}
            />
          )}

          {results?.show_notes && (
            <motion.div
              style={{ marginTop: 'var(--space-7)' }}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.18 }}
            >
              <SectionHeading icon={<BookOpen size={13} />} title="Show notes" />
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
                <ReactMarkdown>{results.show_notes}</ReactMarkdown>
              </div>
            </motion.div>
          )}

          {script && script.length > 0 && (
            <motion.div
              style={{ marginTop: 'var(--space-7)' }}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.26 }}
            >
              <ScriptViewer script={script} />
            </motion.div>
          )}

          {sources && sources.length > 0 && (
            <motion.div
              style={{ marginTop: 'var(--space-7)' }}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.34 }}
            >
              <SourcesList sources={sources} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Card>
  );
}
