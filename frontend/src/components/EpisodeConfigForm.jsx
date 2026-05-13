import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Square, Mic, Settings2, Sliders,
  Clock, Users, Wand2, FileText, Tag,
} from 'lucide-react';

import useVoiceProfiles from '../hooks/useVoiceProfiles';
import Card, { CardHeader, CardTitle } from './ui/Card';
import Section from './ui/Section';
import Button from './ui/Button';
import Badge from './ui/Badge';
import Slider from './ui/Slider';
import Checkbox from './ui/Checkbox';
import { Input, Textarea, Select } from './ui/Input';

const TONE_OPTIONS = ['conversational', 'analytical', 'storytelling', 'humorous', 'authoritative', 'casual'];
const TTS_OPTIONS = [
  { value: 'kokoro',      label: 'Kokoro',      hint: 'Fast, local CPU' },
  { value: 'qwen',        label: 'Qwen3-TTS',   hint: 'Voice design, GPU' },
  { value: 'bark',        label: 'Bark',        hint: 'Expressive, GPU' },
  { value: 'chatterbox',  label: 'Chatterbox',  hint: 'Voice clone, GPU' },
];

export default function EpisodeConfigForm({ isGenerating, onGenerate, onStop }) {
  const [topic, setTopic] = useState('');
  const [minutes, setMinutes] = useState(5);
  const [tone, setTone] = useState('conversational');
  const [audience, setAudience] = useState('general listeners');
  const [wpm, setWpm] = useState(150);
  const [timeline, setTimeline] = useState('');
  const [constraints, setConstraints] = useState('');
  const [dryRun, setDryRun] = useState(false);
  const [pauseForReview, setPauseForReview] = useState(false);
  const [autoVideo, setAutoVideo] = useState(false);
  const [ttsBackend, setTtsBackend] = useState('kokoro');
  const [voiceGender, setVoiceGender] = useState('female');
  const [voiceId, setVoiceId] = useState('');

  const { profiles, loading: profilesLoading } = useVoiceProfiles();
  const isChatterbox = ttsBackend === 'chatterbox';

  // Quick cost-estimate
  const estimate = useMemo(() => {
    const words = minutes * wpm;
    const tokensK = Math.max(1, Math.round((words * 1.5) / 1000));
    return { words, tokensK };
  }, [minutes, wpm]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!topic.trim()) return;
    onGenerate({
      topic, minutes, tone, audience, wpm,
      timeline, constraints,
      dry_run: dryRun,
      pause_for_review: pauseForReview,
      auto_video: autoVideo,
      multi_voice: false,
      tts_backend: ttsBackend,
      voice_gender: voiceGender,
      voice_id: voiceId || '',
    });
  };

  return (
    <Card padding="none">
      <CardHeader>
        <CardTitle eyebrow="Episode">New podcast</CardTitle>
        <Badge variant={isGenerating ? 'brand' : 'ghost'} size="sm" dot pulse={isGenerating}>
          {isGenerating ? 'Running' : 'Ready'}
        </Badge>
      </CardHeader>

      <form onSubmit={handleSubmit}>
        {/* ── 1. Topic & Format ───────────────────────────────────────── */}
        <Section
          eyebrow="01"
          title="Topic & Format"
          icon={<FileText size={14} />}
          defaultOpen
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
            <Textarea
              label="What's the episode about?"
              placeholder="The rise of AI agents in software engineering — what changed in 2024, where it's going next."
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              rows={3}
              required
            />

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-5)' }}>
              <Slider
                label="Duration"
                value={minutes}
                onChange={setMinutes}
                min={1}
                max={60}
                step={1}
                unit=" min"
                presets={[3, 5, 10, 20, 30]}
              />
              <Slider
                label="Speaking pace"
                value={wpm}
                onChange={setWpm}
                min={130}
                max={180}
                step={5}
                unit=" wpm"
                presets={[140, 150, 160]}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
              <Select
                label="Tone"
                value={tone}
                onChange={(e) => setTone(e.target.value)}
              >
                {TONE_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </Select>
              <Input
                label="Target audience"
                value={audience}
                onChange={(e) => setAudience(e.target.value)}
                placeholder="general listeners"
                iconLeft={<Users size={14} />}
              />
            </div>
          </div>
        </Section>

        {/* ── 2. Voice & Synthesis ────────────────────────────────────── */}
        <Section
          eyebrow="02"
          title="Voice & Synthesis"
          icon={<Mic size={14} />}
          defaultOpen
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
              <Select
                label="TTS Engine"
                hint={TTS_OPTIONS.find((o) => o.value === ttsBackend)?.hint}
                value={ttsBackend}
                onChange={(e) => { setTtsBackend(e.target.value); setVoiceId(''); }}
              >
                {TTS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label} — {o.hint}</option>
                ))}
              </Select>
              <Select
                label="Voice gender"
                value={voiceGender}
                onChange={(e) => setVoiceGender(e.target.value)}
              >
                <option value="female">Female</option>
                <option value="male">Male</option>
              </Select>
            </div>

            <AnimatePresence>
              {isChatterbox && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
                  style={{ overflow: 'hidden' }}
                >
                  <div
                    style={{
                      padding: 'var(--space-4)',
                      background: 'rgba(124, 92, 255, 0.06)',
                      border: '1px solid rgba(124, 92, 255, 0.18)',
                      borderRadius: 'var(--radius-md)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-2)',
                        marginBottom: 'var(--space-3)',
                      }}
                    >
                      <Wand2 size={13} color="var(--brand-300)" />
                      <span
                        style={{
                          fontSize: 'var(--text-xs)',
                          fontWeight: 600,
                          color: 'var(--brand-300)',
                          letterSpacing: 'var(--tracking-wide)',
                          textTransform: 'uppercase',
                        }}
                      >
                        Voice Profile
                      </span>
                      <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', marginLeft: 'auto' }}>
                        Create in the Voice Profiles tab
                      </span>
                    </div>

                    {profilesLoading ? (
                      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-tertiary)', margin: 0 }}>
                        Loading profiles…
                      </p>
                    ) : profiles.length === 0 ? (
                      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-tertiary)', margin: 0 }}>
                        No profiles found. Create one and return here.
                      </p>
                    ) : (
                      <Select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                        <option value="">— Use Chatterbox built-in voice —</option>
                        {profiles.map((p) => (
                          <option key={p.voice_id} value={p.voice_id}>
                            {p.name} ({(p.sample_duration_ms / 1000).toFixed(1)}s)
                          </option>
                        ))}
                      </Select>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </Section>

        {/* ── 3. Advanced ─────────────────────────────────────────────── */}
        <Section
          eyebrow="03"
          title="Advanced"
          icon={<Sliders size={14} />}
          defaultOpen={false}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
            <Input
              label="Timeline / focus"
              hint="Optional comma-separated chapter cues — '0:Intro,3:AI Origins,7:Ethics'"
              value={timeline}
              onChange={(e) => setTimeline(e.target.value)}
              placeholder="0:Intro,3:AI Origins,7:Ethics"
              optional
              iconLeft={<Clock size={14} />}
            />
            <Input
              label="Constraints"
              hint="Soft guidance for the writer — 'avoid jargon; must mention FDA approval'"
              value={constraints}
              onChange={(e) => setConstraints(e.target.value)}
              placeholder="avoid jargon; must mention FDA approval"
              optional
              iconLeft={<Tag size={14} />}
            />

            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <Checkbox
                checked={dryRun}
                onChange={setDryRun}
                label="Dry run"
                description="Skip the LLM and produce mock content (fast, free)"
              />
              <Checkbox
                checked={pauseForReview}
                onChange={setPauseForReview}
                label="Review script before TTS"
                description="Pause after writing so you can edit segments before GPU minutes are spent"
              />
              <Checkbox
                checked={autoVideo}
                onChange={setAutoVideo}
                label="Auto-generate video"
                description="Render the 1080p video (AI visual bed + waveform + subtitles) right after audio finishes — no extra click."
              />
            </div>
          </div>
        </Section>

        {/* ── Footer / Action bar ─────────────────────────────────────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-4)',
            padding: 'var(--space-5) var(--space-6)',
            borderTop: '1px solid var(--border-subtle)',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <Badge variant="ghost" size="sm" icon={<Clock size={11} />}>
              ≈ {minutes}m audio
            </Badge>
            <Badge variant="ghost" size="sm" icon={<Sparkles size={11} />}>
              ~{estimate.tokensK}k tokens
            </Badge>
            <Badge variant="ghost" size="sm" icon={<Settings2 size={11} />}>
              {ttsBackend}
            </Badge>
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            {!isGenerating ? (
              <Button
                type="submit"
                variant="primary"
                size="lg"
                iconLeft={<Sparkles size={16} />}
                disabled={!topic.trim()}
              >
                Generate episode
              </Button>
            ) : (
              <Button
                type="button"
                variant="destructive"
                size="lg"
                iconLeft={<Square size={14} fill="currentColor" />}
                onClick={onStop}
              >
                Abort
              </Button>
            )}
          </div>
        </div>
      </form>
    </Card>
  );
}
