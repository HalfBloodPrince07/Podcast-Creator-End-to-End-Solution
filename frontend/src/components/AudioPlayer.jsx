import { useState, useRef, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Play, Pause, Volume2, VolumeX, Download,
  FileAudio, FileType2, FileText, BookOpen,
} from 'lucide-react';
import IconButton from './ui/IconButton';
import Tooltip from './ui/Tooltip';

/**
 * AudioPlayer — custom premium audio surface.
 * Hidden HTML5 audio element drives the UI.
 */

function formatTime(s) {
  if (!Number.isFinite(s)) return '0:00';
  const total = Math.max(0, Math.floor(s));
  const m = Math.floor(total / 60);
  const r = total % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

const DOWNLOAD_TRAY = [
  { key: 'audio_url', label: 'MP3',   icon: FileAudio },
  { key: 'srt_url',   label: 'SRT',   icon: FileType2 },
  { key: 'txt_url',   label: 'TXT',   icon: FileText },
  { key: 'notes_url', label: 'Notes', icon: BookOpen },
];

export default function AudioPlayer({ results }) {
  const audioRef = useRef(null);
  const trackRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [seeking, setSeeking] = useState(false);

  // Wire native audio events
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => { if (!seeking) setCurrent(el.currentTime); };
    const onMeta = () => setDuration(el.duration || 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => setPlaying(false);
    el.addEventListener('timeupdate', onTime);
    el.addEventListener('loadedmetadata', onMeta);
    el.addEventListener('play', onPlay);
    el.addEventListener('pause', onPause);
    el.addEventListener('ended', onEnded);
    return () => {
      el.removeEventListener('timeupdate', onTime);
      el.removeEventListener('loadedmetadata', onMeta);
      el.removeEventListener('play', onPlay);
      el.removeEventListener('pause', onPause);
      el.removeEventListener('ended', onEnded);
    };
  }, [seeking]);

  // Apply volume / mute
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = muted ? 0 : volume;
    }
  }, [volume, muted]);

  const togglePlay = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) el.play(); else el.pause();
  }, []);

  // Scrubber interactions
  const seekToClientX = useCallback((clientX) => {
    const el = audioRef.current;
    const track = trackRef.current;
    if (!el || !track || !duration) return;
    const rect = track.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    el.currentTime = pct * duration;
    setCurrent(pct * duration);
  }, [duration]);

  const onTrackPointerDown = (e) => {
    setSeeking(true);
    seekToClientX(e.clientX);
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onTrackPointerMove = (e) => {
    if (!seeking) return;
    seekToClientX(e.clientX);
  };
  const onTrackPointerUp = (e) => {
    setSeeking(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  if (!results?.audio_url) return null;

  const pct = duration ? (current / duration) * 100 : 0;

  return (
    <div
      style={{
        background:
          'linear-gradient(180deg, rgba(29, 29, 39, 0.85), rgba(22, 22, 31, 0.7))',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-5)',
        boxShadow: 'var(--shadow-md), var(--shadow-inset)',
      }}
    >
      <audio ref={audioRef} src={results.audio_url} preload="metadata" style={{ display: 'none' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
        {/* Play / pause */}
        <motion.button
          type="button"
          onClick={togglePlay}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.94 }}
          transition={{ duration: 0.14 }}
          aria-label={playing ? 'Pause' : 'Play'}
          style={{
            flexShrink: 0,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 44,
            height: 44,
            borderRadius: '50%',
            background: 'var(--brand-gradient)',
            color: '#fff',
            border: 'none',
            cursor: 'pointer',
            boxShadow: '0 6px 18px var(--brand-glow), inset 0 1px 0 rgba(255,255,255,0.15)',
          }}
        >
          {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" style={{ marginLeft: 2 }} />}
        </motion.button>

        {/* Scrubber + time */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            ref={trackRef}
            onPointerDown={onTrackPointerDown}
            onPointerMove={onTrackPointerMove}
            onPointerUp={onTrackPointerUp}
            style={{
              position: 'relative',
              height: 6,
              background: 'rgba(255, 255, 255, 0.07)',
              borderRadius: 'var(--radius-pill)',
              cursor: 'pointer',
              touchAction: 'none',
            }}
          >
            <div
              style={{
                position: 'absolute',
                left: 0, top: 0, bottom: 0,
                width: `${pct}%`,
                background: 'var(--brand-gradient)',
                borderRadius: 'var(--radius-pill)',
                boxShadow: '0 0 10px var(--brand-glow)',
              }}
            />
            <div
              style={{
                position: 'absolute',
                left: `${pct}%`,
                top: '50%',
                transform: 'translate(-50%, -50%)',
                width: 12,
                height: 12,
                borderRadius: '50%',
                background: '#fff',
                border: '2px solid var(--brand-500)',
                boxShadow: '0 0 0 4px var(--brand-glow)',
                pointerEvents: 'none',
                opacity: duration ? 1 : 0,
                transition: 'opacity 0.2s',
              }}
            />
          </div>
          <div
            style={{
              marginTop: 'var(--space-2)',
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 'var(--text-2xs)',
              fontVariantNumeric: 'tabular-nums',
              color: 'var(--text-tertiary)',
              fontWeight: 600,
              letterSpacing: 'var(--tracking-wide)',
            }}
          >
            <span>{formatTime(current)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        {/* Volume */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', flexShrink: 0 }}>
          <Tooltip label={muted ? 'Unmute' : 'Mute'}>
            <IconButton variant="ghost" onClick={() => setMuted((m) => !m)} title={muted ? 'Unmute' : 'Mute'}>
              {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </IconButton>
          </Tooltip>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            onChange={(e) => {
              const v = Number(e.target.value);
              setVolume(v);
              if (v > 0 && muted) setMuted(false);
            }}
            aria-label="Volume"
            style={{ width: 80, height: 4 }}
          />
        </div>
      </div>

      {/* Download tray */}
      <div
        style={{
          marginTop: 'var(--space-4)',
          paddingTop: 'var(--space-3)',
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{
            fontSize: 'var(--text-2xs)',
            fontWeight: 600,
            color: 'var(--text-tertiary)',
            letterSpacing: 'var(--tracking-wide)',
            textTransform: 'uppercase',
            marginRight: 'var(--space-2)',
          }}
        >
          Download
        </span>
        {DOWNLOAD_TRAY.filter((d) => results[d.key]).map((d) => {
          const Icon = d.icon;
          return (
            <Tooltip key={d.key} label={`Download ${d.label}`}>
              <a
                href={results[d.key]}
                download
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 10px',
                  fontSize: 'var(--text-2xs)',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  background: 'rgba(255, 255, 255, 0.04)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)',
                  letterSpacing: 'var(--tracking-wide)',
                  transition: 'all 0.14s var(--ease-snap)',
                }}
              >
                <Icon size={11} />
                {d.label}
              </a>
            </Tooltip>
          );
        })}
        <div style={{ flex: 1 }} />
        <Tooltip label="Save to disk">
          <a
            href={results.audio_url}
            download
            target="_blank"
            rel="noreferrer"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--brand-300)',
              background: 'rgba(124, 92, 255, 0.12)',
              border: '1px solid rgba(124, 92, 255, 0.25)',
              borderRadius: 'var(--radius-sm)',
              letterSpacing: '0.01em',
            }}
          >
            <Download size={12} />
            Save MP3
          </a>
        </Tooltip>
      </div>
    </div>
  );
}
