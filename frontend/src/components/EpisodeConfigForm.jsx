import { useState } from 'react';
import { motion } from 'framer-motion';

const TONE_OPTIONS = ['conversational', 'analytical', 'storytelling', 'humorous', 'authoritative', 'casual'];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08 }
  }
};

const itemVariants = {
  hidden: { opacity: 0, y: 15 },
  visible: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 300, damping: 24 } }
};

export default function EpisodeConfigForm({ isGenerating, onGenerate, onStop }) {
  const [topic, setTopic] = useState('');
  const [minutes, setMinutes] = useState(5);
  const [tone, setTone] = useState('conversational');
  const [audience, setAudience] = useState('general listeners');
  const [wpm, setWpm] = useState(150);
  const [timeline, setTimeline] = useState('');
  const [constraints, setConstraints] = useState('');
  const [dryRun, setDryRun] = useState(false);
  const [ttsBackend, setTtsBackend] = useState('kokoro');
  const [voiceGender, setVoiceGender] = useState('female');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!topic.trim()) {
      alert('Please enter a topic.');
      return;
    }
    onGenerate({ topic, minutes, tone, audience, wpm, timeline, constraints, dry_run: dryRun, multi_voice: false, tts_backend: ttsBackend, voice_gender: voiceGender });
  };

  return (
    <motion.div className="glass-panel" style={{ marginBottom: '2rem' }}>
      <motion.h2 variants={itemVariants} style={{ fontSize: '1.4rem', marginBottom: '1.5rem', fontWeight: 600 }}>
        Episode Configuration
      </motion.h2>

      <motion.form onSubmit={handleSubmit} variants={containerVariants} initial="hidden" animate="visible">
        <motion.div className="form-group" variants={itemVariants}>
          <label>Podcast Topic <span style={{ color: 'var(--primary-light)' }}>*</span></label>
          <textarea
            required
            placeholder="e.g. The rise of AI in healthcare"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
        </motion.div>

        <motion.div className="grid-2" style={{ marginBottom: '1rem' }} variants={itemVariants}>
          <div className="form-group">
            <label>Duration: <span style={{ color: 'var(--text-muted)' }}>{minutes} mins</span></label>
            <input type="range" min="1" max="60" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
          </div>
          <div className="form-group">
            <label>Speaking Rate: <span style={{ color: 'var(--text-muted)' }}>{wpm} wpm</span></label>
            <input type="range" min="140" max="170" step="5" value={wpm} onChange={(e) => setWpm(Number(e.target.value))} />
          </div>
        </motion.div>

        <motion.div className="grid-2" variants={itemVariants}>
          <div className="form-group">
            <label>Tone</label>
            <select value={tone} onChange={(e) => setTone(e.target.value)}>
              {TONE_OPTIONS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Target Audience</label>
            <input type="text" value={audience} onChange={(e) => setAudience(e.target.value)} />
          </div>
        </motion.div>

        <motion.div className="form-group" variants={itemVariants}>
          <label>Timeline / Focus (optional)</label>
          <input type="text" placeholder="0:Intro,3:AI Origins,7:Ethics" value={timeline} onChange={(e) => setTimeline(e.target.value)} />
        </motion.div>

        <motion.div className="form-group" variants={itemVariants}>
          <label>Constraints (optional)</label>
          <input type="text" placeholder="avoid jargon; must mention FDA approval" value={constraints} onChange={(e) => setConstraints(e.target.value)} />
        </motion.div>

        <motion.div className="grid-2" variants={itemVariants}>
          <div className="form-group">
            <label>TTS Engine</label>
            <select value={ttsBackend} onChange={(e) => setTtsBackend(e.target.value)}>
              <option value="kokoro">Kokoro (Fast, Local CPU)</option>
              <option value="qwen">Qwen3-TTS (Voice Design, GPU)</option>
              <option value="bark">Bark (Expressive, GPU)</option>
            </select>
          </div>
          <div className="form-group">
            <label>Voice Gender</label>
            <select value={voiceGender} onChange={(e) => setVoiceGender(e.target.value)}>
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
          </div>
        </motion.div>

        <motion.div variants={itemVariants}>
          <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '1rem' }}>
            <input
              type="checkbox"
              id="dryRun"
              style={{ width: 'auto', accentColor: 'var(--primary)' }}
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            <label htmlFor="dryRun" style={{ marginBottom: 0, fontWeight: '500', display: 'flex', alignItems: 'center' }}>
              Dry Run <span style={{ color: 'var(--text-muted)', fontSize: '0.85em', marginLeft: '6px' }}>(mock generation)</span>
            </label>
          </div>
        </motion.div>

        <motion.div style={{ marginTop: '2.5rem', display: 'flex', gap: '1rem' }} variants={itemVariants}>
          {!isGenerating ? (
            <motion.button
              type="submit"
              className="btn btn-primary"
              style={{ flex: 1 }}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              Initialize Generation
            </motion.button>
          ) : (
            <motion.button
              type="button"
              onClick={onStop}
              className="btn"
              style={{ flex: 1, background: 'rgba(239, 68, 68, 0.2)', color: '#FCA5A5', border: '1px solid rgba(239,68,68,0.3)' }}
              whileHover={{ scale: 1.02, backgroundColor: 'rgba(239, 68, 68, 0.3)' }}
              whileTap={{ scale: 0.98 }}
            >
              Abort Process
            </motion.button>
          )}
        </motion.div>
      </motion.form>
    </motion.div>
  );
}
