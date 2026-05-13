import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Mic, Trash2, Upload, Plus, X, Play, Square,
  Loader2, Check, AudioWaveform, RefreshCw, Volume2,
  AlertCircle, Sparkles, Headphones,
} from 'lucide-react';

import useVoiceProfiles from '../hooks/useVoiceProfiles';
import Card, { CardHeader, CardTitle } from './ui/Card';
import Button from './ui/Button';
import IconButton from './ui/IconButton';
import Badge from './ui/Badge';
import Tooltip from './ui/Tooltip';
import EmptyState from './ui/EmptyState';
import { Input, Textarea } from './ui/Input';

const cardVariants = {
  hidden:  { opacity: 0, y: 20, scale: 0.97 },
  visible: { opacity: 1, y: 0, scale: 1, transition: { type: 'spring', stiffness: 280, damping: 26 } },
  exit:    { opacity: 0, scale: 0.95, transition: { duration: 0.18 } },
};

function formatDuration(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}
function formatDate(ts) {
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}
function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ════════════════════════════════════════════════════════════════════════════
// Drop zone (reused by create form and add-clips section)
// ════════════════════════════════════════════════════════════════════════════
function FileDropZone({ onFiles, accent = 'brand', compact = false }) {
  const [drag, setDrag] = useState(false);
  const ref = useRef(null);

  const colors = {
    brand:   { line: 'var(--brand-400)', bg: 'rgba(124, 92, 255, 0.07)', icon: 'var(--brand-300)' },
    success: { line: 'var(--success)',   bg: 'rgba(52, 211, 153, 0.07)', icon: 'var(--success)'   },
  }[accent];

  return (
    <div
      onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onClick={() => ref.current?.click()}
      style={{
        border: `2px dashed ${drag ? colors.line : 'var(--border-default)'}`,
        borderRadius: 'var(--radius-md)',
        padding: compact ? 'var(--space-4)' : 'var(--space-6) var(--space-5)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 'var(--space-2)',
        cursor: 'pointer',
        background: drag ? colors.bg : 'rgba(255, 255, 255, 0.02)',
        transition: 'all 0.22s var(--ease-snap)',
        textAlign: 'center',
      }}
    >
      <Upload size={compact ? 18 : 22} color={drag ? colors.icon : 'var(--text-tertiary)'} />
      <p style={{ margin: 0, fontSize: compact ? 'var(--text-xs)' : 'var(--text-sm)', color: 'var(--text-secondary)' }}>
        Drop audio clips here or{' '}
        <span style={{ color: colors.icon, fontWeight: 600 }}>browse</span>
      </p>
      {!compact && (
        <p style={{ margin: 0, fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
          WAV · MP3 · FLAC · M4A · multi-clip supported
        </p>
      )}
      <input
        ref={ref}
        type="file"
        accept="audio/*,.wav,.mp3,.ogg,.flac,.m4a,.aac"
        multiple
        style={{ display: 'none' }}
        onChange={(e) => onFiles(e.target.files)}
      />
    </div>
  );
}

function FileListItem({ file, onRemove, accent = 'brand' }) {
  const color = accent === 'success' ? 'var(--success)' : 'var(--brand-300)';
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 8 }}
      transition={{ duration: 0.18 }}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: 'var(--space-2) var(--space-3)',
        background: 'rgba(255, 255, 255, 0.04)',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      <AudioWaveform size={14} color={color} style={{ flexShrink: 0 }} />
      <span
        style={{
          flex: 1,
          fontSize: 'var(--text-xs)',
          color: 'var(--text-primary)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {file.name}
      </span>
      <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', flexShrink: 0 }}>
        {formatFileSize(file.size)}
      </span>
      <IconButton size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); onRemove(); }} title="Remove">
        <X size={12} />
      </IconButton>
    </motion.div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Create form
// ════════════════════════════════════════════════════════════════════════════
function CreateProfileForm({ onCreated, onCancel }) {
  const { createProfile, loading, error } = useVoiceProfiles();
  const [name, setName] = useState('');
  const [files, setFiles] = useState([]);
  const [success, setSuccess] = useState(null);

  const addFiles = useCallback((list) => {
    const audio = Array.from(list).filter(
      (f) => f.type.startsWith('audio/') || f.name.match(/\.(wav|mp3|ogg|flac|m4a|aac)$/i),
    );
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => f.name + f.size));
      return [...prev, ...audio.filter((f) => !seen.has(f.name + f.size))];
    });
  }, []);

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || files.length === 0) return;
    try {
      const result = await createProfile(name.trim(), files);
      setSuccess(result);
      onCreated?.(result);
    } catch { /* surfaced via hook */ }
  };

  if (success) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        style={{
          padding: 'var(--space-8) var(--space-6)',
          background: 'var(--success-bg)',
          border: '1px solid var(--success-border)',
          borderRadius: 'var(--radius-md)',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            width: 48, height: 48,
            alignItems: 'center', justifyContent: 'center',
            borderRadius: '50%',
            background: 'rgba(52, 211, 153, 0.18)',
            color: 'var(--success)',
            marginBottom: 'var(--space-3)',
          }}
        >
          <Check size={22} strokeWidth={3} />
        </div>
        <div style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--success)' }}>
          Voice profile created
        </div>
        <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--text-primary)' }}>{success.name}</strong>
          {' · '}{formatDuration(success.duration_ms)} from {success.clips_merged} clip{success.clips_merged !== 1 ? 's' : ''}
        </div>
        <div
          style={{
            marginTop: 'var(--space-3)',
            fontSize: 'var(--text-2xs)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-tertiary)',
            letterSpacing: 'var(--tracking-wide)',
          }}
        >
          ID · {success.voice_id}
        </div>
        <div style={{ marginTop: 'var(--space-5)' }}>
          <Button variant="primary" size="md" onClick={onCancel}>Done</Button>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.form
      onSubmit={handleSubmit}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}
    >
      <Input
        label="Profile name"
        placeholder="e.g. My podcast voice"
        value={name}
        onChange={(e) => setName(e.target.value)}
        iconLeft={<Sparkles size={13} />}
        required
      />

      <div>
        <label
          style={{
            display: 'block',
            marginBottom: 'var(--space-2)',
            fontSize: 'var(--text-xs)',
            fontWeight: 500,
            color: 'var(--text-secondary)',
          }}
        >
          Voice clips
        </label>
        <FileDropZone onFiles={addFiles} accent="brand" />

        <AnimatePresence>
          {files.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              style={{
                marginTop: 'var(--space-3)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-2)',
                overflow: 'hidden',
              }}
            >
              <AnimatePresence>
                {files.map((f, i) => (
                  <FileListItem
                    key={f.name + f.size}
                    file={f}
                    onRemove={() => removeFile(i)}
                  />
                ))}
              </AnimatePresence>
              <p style={{ margin: 0, fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
                {files.length} clip{files.length > 1 ? 's' : ''} selected — Chatterbox works best with 10–20s total
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              padding: 'var(--space-3)',
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--danger)',
              fontSize: 'var(--text-xs)',
            }}
          >
            <AlertCircle size={14} />
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <Button
          type="submit"
          variant="primary"
          size="md"
          fullWidth
          disabled={!name.trim() || files.length === 0}
          loading={loading}
          iconLeft={<Sparkles size={14} />}
        >
          Create profile
        </Button>
        <Button type="button" variant="secondary" size="md" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </motion.form>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Profile card
// ════════════════════════════════════════════════════════════════════════════
function ProfileCard({ profile, onDelete, onAddClips, previewText }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [refPlaying, setRefPlaying] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [showAddClips, setShowAddClips] = useState(false);
  const [addFiles, setAddFiles] = useState([]);
  const [addingClips, setAddingClips] = useState(false);
  const [addSuccess, setAddSuccess] = useState(null);
  const [addError, setAddError] = useState(null);
  const refAudioRef = useRef(null);
  const previewAudioRef = useRef(null);

  const addAudio = (list) => {
    const audio = Array.from(list).filter(
      (f) => f.type.startsWith('audio/') || f.name.match(/\.(wav|mp3|ogg|flac|m4a|aac)$/i),
    );
    setAddFiles((prev) => {
      const seen = new Set(prev.map((f) => f.name + f.size));
      return [...prev, ...audio.filter((f) => !seen.has(f.name + f.size))];
    });
  };
  const removeAddFile = (idx) => setAddFiles((prev) => prev.filter((_, i) => i !== idx));

  const submitAddClips = async () => {
    if (addFiles.length === 0) return;
    setAddingClips(true);
    setAddError(null);
    setAddSuccess(null);
    try {
      const result = await onAddClips(profile.voice_id, addFiles);
      setAddSuccess(result);
      setAddFiles([]);
      setTimeout(() => { setAddSuccess(null); setShowAddClips(false); }, 3000);
    } catch (e) {
      setAddError(e.message);
    } finally {
      setAddingClips(false);
    }
  };

  const toggleReference = () => {
    if (!refAudioRef.current) {
      const audio = new Audio(`/api/voice-clone/${profile.voice_id}/reference`);
      refAudioRef.current = audio;
      audio.onended = () => setRefPlaying(false);
      audio.onerror = () => setRefPlaying(false);
    }
    if (refPlaying) {
      refAudioRef.current.pause();
      refAudioRef.current.currentTime = 0;
      setRefPlaying(false);
    } else {
      if (previewAudioRef.current) { previewAudioRef.current.pause(); setPreviewPlaying(false); }
      refAudioRef.current.play();
      setRefPlaying(true);
    }
  };

  const generatePreview = async () => {
    setPreviewError(null);
    setPreviewLoading(true);
    if (refAudioRef.current) { refAudioRef.current.pause(); setRefPlaying(false); }
    if (previewAudioRef.current) { previewAudioRef.current.pause(); setPreviewPlaying(false); }
    try {
      const res = await fetch(`/api/voice-clone/${profile.voice_id}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: previewText }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      previewAudioRef.current = audio;
      audio.onended = () => setPreviewPlaying(false);
      audio.onerror = () => { setPreviewPlaying(false); setPreviewError('Playback error'); };
      audio.play();
      setPreviewPlaying(true);
    } catch (e) {
      setPreviewError(e.message);
    } finally {
      setPreviewLoading(false);
    }
  };

  const stopPreview = () => {
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.currentTime = 0;
      setPreviewPlaying(false);
    }
  };

  return (
    <motion.div
      variants={cardVariants}
      layout
      style={{
        position: 'relative',
        background: 'linear-gradient(180deg, rgba(29, 29, 39, 0.8), rgba(22, 22, 31, 0.7))',
        backdropFilter: 'blur(20px) saturate(140%)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-5)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-4)',
        boxShadow: 'var(--shadow-md), var(--shadow-inset)',
        overflow: 'hidden',
      }}
    >
      {/* Accent line */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: '0 0 auto 0',
          height: 2,
          background: 'var(--brand-gradient)',
          opacity: 0.7,
        }}
      />

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        <div
          style={{
            display: 'inline-flex',
            width: 40, height: 40,
            alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
            borderRadius: 'var(--radius-sm)',
            background: 'rgba(124, 92, 255, 0.12)',
            border: '1px solid rgba(124, 92, 255, 0.25)',
            color: 'var(--brand-300)',
          }}
        >
          <Mic size={18} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 'var(--text-md)',
              fontWeight: 600,
              color: 'var(--text-primary)',
              letterSpacing: 'var(--tracking-tight)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {profile.name}
          </div>
          <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', marginTop: 2 }}>
            {formatDate(profile.created_at)}
          </div>
        </div>
      </div>

      {/* Stat badges */}
      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <Badge variant="info" size="xs" icon={<Headphones size={9} />}>
          <span className="tabular-nums">{formatDuration(profile.sample_duration_ms)}</span>
        </Badge>
        <Badge variant="ghost" size="xs">{profile.clone_type}</Badge>
        {profile.quality_check_passed && (
          <Badge variant="success" size="xs" icon={<Check size={9} />}>Ready</Badge>
        )}
      </div>

      {/* Voice ID */}
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--text-2xs)',
          color: 'var(--text-tertiary)',
          letterSpacing: 'var(--tracking-wide)',
          opacity: 0.85,
        }}
      >
        ID · {profile.voice_id}
      </div>

      {/* Playback actions */}
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          fullWidth
          onClick={toggleReference}
          iconLeft={refPlaying ? <Square size={11} fill="currentColor" /> : <Play size={11} fill="currentColor" />}
        >
          {refPlaying ? 'Stop' : 'Reference'}
        </Button>
        <Button
          type="button"
          variant="primary"
          size="sm"
          fullWidth
          loading={previewLoading}
          onClick={previewPlaying ? stopPreview : generatePreview}
          iconLeft={previewPlaying ? <Square size={11} fill="currentColor" /> : <Volume2 size={11} />}
        >
          {previewPlaying ? 'Stop' : previewLoading ? 'Generating' : 'Preview'}
        </Button>
      </div>

      <AnimatePresence>
        {previewError && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            style={{
              fontSize: 'var(--text-2xs)',
              color: 'var(--danger)',
              padding: 'var(--space-2)',
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)',
              borderRadius: 'var(--radius-xs)',
            }}
          >
            {previewError}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Add clips */}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        fullWidth
        onClick={() => { setShowAddClips(!showAddClips); setAddError(null); setAddSuccess(null); setAddFiles([]); }}
        iconLeft={showAddClips ? <X size={12} /> : <Plus size={12} />}
      >
        {showAddClips ? 'Cancel add' : 'Add clips'}
      </Button>

      <AnimatePresence>
        {showAddClips && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}
          >
            <FileDropZone onFiles={addAudio} accent="success" compact />
            {addFiles.length > 0 && (
              <>
                {addFiles.map((f, i) => (
                  <FileListItem
                    key={f.name + f.size}
                    file={f}
                    accent="success"
                    onRemove={() => removeAddFile(i)}
                  />
                ))}
                <Button
                  type="button"
                  size="sm"
                  fullWidth
                  variant="primary"
                  loading={addingClips}
                  onClick={submitAddClips}
                >
                  Merge {addFiles.length} clip{addFiles.length > 1 ? 's' : ''}
                </Button>
              </>
            )}
            {addSuccess && (
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--success)' }}>
                ✓ {addSuccess.clips_added} clip{addSuccess.clips_added > 1 ? 's' : ''} merged — now {formatDuration(addSuccess.duration_ms)}
              </div>
            )}
            {addError && (
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--danger)' }}>{addError}</div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Delete (footer) */}
      <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'flex-end' }}>
        <AnimatePresence mode="wait">
          {!confirmDelete ? (
            <motion.div
              key="delete-btn"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <Button
                type="button"
                size="sm"
                variant="destructive"
                iconLeft={<Trash2 size={11} />}
                onClick={() => setConfirmDelete(true)}
              >
                Delete
              </Button>
            </motion.div>
          ) : (
            <motion.div
              key="confirm-row"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}
            >
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>Delete?</span>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => { onDelete(profile.voice_id); setConfirmDelete(false); }}
              >
                Yes
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                No
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// Main
// ════════════════════════════════════════════════════════════════════════════
const DEFAULT_PREVIEW_TEXT =
  `It feels counterintuitive that a 20-billion parameter model runs smoother than an 18-billion parameter one, especially when balancing it all on an RTX 5060 Ti with 16GB of VRAM. But GPT OSS 20B has two massive architectural advantages over standard dense models that make it punch well above its weight class.`;

export default function VoiceProfiles() {
  const { profiles, loading, error, deleteProfile, fetchProfiles, addClips } = useVoiceProfiles();
  const [showCreate, setShowCreate] = useState(false);
  const [previewText, setPreviewText] = useState(DEFAULT_PREVIEW_TEXT);

  const handleCreated = () => {
    setShowCreate(false);
    fetchProfiles();
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
      style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}
    >
      {/* Header card */}
      <Card padding="md">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-4)',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <span
              style={{
                display: 'inline-flex',
                width: 36, height: 36,
                alignItems: 'center', justifyContent: 'center',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(124, 92, 255, 0.12)',
                color: 'var(--brand-300)',
                border: '1px solid rgba(124, 92, 255, 0.25)',
              }}
            >
              <Mic size={16} />
            </span>
            <div>
              <div
                style={{
                  fontSize: 'var(--text-lg)',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  letterSpacing: 'var(--tracking-tight)',
                }}
              >
                Voice profiles
              </div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)', marginTop: 2 }}>
                Clone voices for Chatterbox TTS · Best with 10–20s of clean audio
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
            <Tooltip label="Refresh">
              <IconButton variant="ghost" onClick={fetchProfiles} title="Refresh">
                <RefreshCw size={14} />
              </IconButton>
            </Tooltip>
            {!showCreate && (
              <Button
                variant="primary"
                size="md"
                iconLeft={<Plus size={14} />}
                onClick={() => setShowCreate(true)}
              >
                New profile
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* Create */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            style={{ overflow: 'hidden' }}
          >
            <Card padding="none" variant="glow">
              <CardHeader>
                <CardTitle eyebrow="Add">Create profile</CardTitle>
              </CardHeader>
              <div style={{ padding: 'var(--space-6)' }}>
                <CreateProfileForm onCreated={handleCreated} onCancel={() => setShowCreate(false)} />
              </div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
              padding: 'var(--space-3) var(--space-4)',
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--danger)',
              fontSize: 'var(--text-sm)',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
            }}
          >
            <AlertCircle size={14} /> {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Loading */}
      {loading && profiles.length === 0 && (
        <Card padding="md">
          <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', verticalAlign: 'middle', marginRight: 8 }} />
            Loading profiles…
          </div>
        </Card>
      )}

      {/* Empty */}
      {!loading && profiles.length === 0 && !showCreate && (
        <Card padding="md">
          <EmptyState
            icon={<Mic size={22} />}
            title="No voice profiles yet"
            description="Upload a short recording of your voice to create a clone for Chatterbox TTS."
            action={
              <Button variant="primary" size="md" iconLeft={<Plus size={14} />} onClick={() => setShowCreate(true)}>
                Create your first profile
              </Button>
            }
          />
        </Card>
      )}

      {/* Preview text */}
      {profiles.length > 0 && (
        <Card padding="md">
          <Textarea
            label="Preview text"
            hint="This is the text spoken when you press Preview on any profile below."
            value={previewText}
            onChange={(e) => setPreviewText(e.target.value)}
            rows={3}
          />
        </Card>
      )}

      {/* Profile grid */}
      <AnimatePresence>
        {profiles.length > 0 && (
          <motion.div
            layout
            initial="visible"
            animate="visible"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 'var(--space-4)',
            }}
          >
            <AnimatePresence>
              {profiles.map((p) => (
                <ProfileCard
                  key={p.voice_id}
                  profile={p}
                  onDelete={deleteProfile}
                  onAddClips={addClips}
                  previewText={previewText}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Usage hint */}
      {profiles.length > 0 && (
        <div
          style={{
            padding: 'var(--space-4) var(--space-5)',
            background: 'rgba(124, 92, 255, 0.06)',
            border: '1px solid rgba(124, 92, 255, 0.2)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 'var(--space-3)',
          }}
        >
          <Sparkles size={14} color="var(--brand-300)" style={{ flexShrink: 0, marginTop: 2 }} />
          <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 'var(--leading-relaxed)' }}>
            <strong style={{ color: 'var(--brand-300)' }}>How to use:</strong>{' '}
            Switch to the <strong style={{ color: 'var(--text-primary)' }}>Generate</strong> tab, choose{' '}
            <strong style={{ color: 'var(--text-primary)' }}>Chatterbox</strong> as the TTS engine, then pick your voice profile.
          </p>
        </div>
      )}
    </motion.div>
  );
}
