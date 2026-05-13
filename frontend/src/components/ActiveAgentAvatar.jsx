import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, PenTool, ShieldCheck, Music, Mic, Layers,
  Sparkles, Moon, CheckCircle, Activity,
} from 'lucide-react';

/**
 * ActiveAgentAvatar — animated agent indicator.
 *
 * Variants:
 *  - "led" (legacy): 100×90 LED-screen surface with scanlines (kept for legacy use).
 *  - "chip" (new):   compact 28×28 inline chip suitable for embedding in
 *                    cards / stage rows.
 */

function configFor(currentStage) {
  if (currentStage?.match(/refin(e|ing) topic/i))
    return { id: 'topic_refine', label: 'REFINER',   icon: Sparkles,    color: '#B4A5FF' };
  if (currentStage?.match(/research/i))
    return { id: 'search',       label: 'SEARCHER',  icon: Search,      color: '#4DD0E1' };
  if (currentStage?.match(/draft(ing)? script|writing/i))
    return { id: 'write',        label: 'WRITER',    icon: PenTool,     color: '#34D399' };
  if (currentStage?.match(/fact[\s-]?check/i))
    return { id: 'fact_check',   label: 'CHECKER',   icon: ShieldCheck, color: '#FFB547' };
  if (currentStage?.match(/audio design/i))
    return { id: 'audio_design', label: 'AUDIO',     icon: Music,       color: '#F472B6' };
  if (currentStage?.match(/generating audio|tts/i))
    return { id: 'tts',          label: 'TTS',       icon: Mic,         color: '#9B85FF' };
  if (currentStage?.match(/assembl(ing|y)/i))
    return { id: 'assemble',     label: 'ASSEMBLY',  icon: Layers,      color: '#FFB547' };
  if (currentStage?.match(/start/i))
    return { id: 'starting',     label: 'BOOTING',   icon: Activity,    color: '#6F6F85' };
  if (currentStage?.match(/complete/i))
    return { id: 'complete',     label: 'DONE',      icon: CheckCircle, color: '#34D399' };
  return     { id: 'idle',         label: 'IDLE',      icon: Moon,        color: '#6F6F85' };
}

export default function ActiveAgentAvatar({ currentStage, variant = 'led', size }) {
  const cfg = configFor(currentStage);
  const Icon = cfg.icon;

  // ── Chip variant ────────────────────────────────────────────────
  if (variant === 'chip') {
    const d = size || 28;
    return (
      <AnimatePresence mode="popLayout">
        <motion.div
          key={cfg.id}
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.85 }}
          transition={{ type: 'spring', stiffness: 320, damping: 26 }}
          title={cfg.label}
          style={{
            display: 'inline-flex',
            width: d, height: d,
            alignItems: 'center', justifyContent: 'center',
            borderRadius: '50%',
            background: `${cfg.color}1f`,
            border: `1px solid ${cfg.color}66`,
            boxShadow: `0 0 0 3px ${cfg.color}1a`,
            color: cfg.color,
          }}
        >
          <Icon size={Math.round(d * 0.5)} strokeWidth={2.4} />
        </motion.div>
      </AnimatePresence>
    );
  }

  // ── LED variant (legacy) ───────────────────────────────────────
  return (
    <div
      style={{
        width: 100, height: 90,
        backgroundColor: '#0F172A',
        borderRadius: 'var(--radius-md)',
        border: '4px solid #1E293B',
        boxShadow: 'inset 0 0 15px rgba(0,0,0,0.8), 0 0 10px rgba(0,0,0,0.3)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 8,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06))',
          backgroundSize: '100% 4px, 6px 100%',
          pointerEvents: 'none',
          zIndex: 10,
          opacity: 0.55,
        }}
      />
      <AnimatePresence mode="popLayout">
        <motion.div
          key={cfg.id}
          initial={{ opacity: 0, y: 12, scale: 0.85 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -12, scale: 0.85 }}
          transition={{ type: 'spring', stiffness: 300, damping: 25 }}
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, zIndex: 5 }}
        >
          <div
            style={{
              color: cfg.color,
              filter: `drop-shadow(0 0 8px ${cfg.color})`,
            }}
          >
            <Icon size={26} strokeWidth={2.4} />
          </div>
          <span
            style={{
              color: cfg.color,
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 700,
              textShadow: `0 0 5px ${cfg.color}`,
              letterSpacing: '0.08em',
            }}
          >
            {cfg.label}
          </span>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
