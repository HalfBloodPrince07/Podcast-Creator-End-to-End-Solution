import { useMemo, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Search, PenTool, ShieldCheck, Music, Mic, Layers,
  AlertTriangle, RefreshCw, Activity,
} from 'lucide-react';

import Card, { CardHeader, CardTitle } from './ui/Card';
import StageTimeline from './ui/StageTimeline';
import Button from './ui/Button';
import Badge from './ui/Badge';

/**
 * ProgressPanel — Vercel-style pipeline tracker.
 *
 * Parses the flat `logs` array (lines look like `[Stage Name] message`)
 * into per-stage buckets, derives status from `currentStage`,
 * and renders the result through the StageTimeline primitive.
 */

const PIPELINE_STAGES = [
  { id: 'topic_refine', label: 'Topic refinement', match: /refin(e|ing) topic/i, icon: <Sparkles size={12} /> },
  { id: 'search',       label: 'Research',         match: /research/i,            icon: <Search size={12} /> },
  { id: 'write',        label: 'Script writing',   match: /draft(ing)? script|writing/i, icon: <PenTool size={12} /> },
  { id: 'fact_check',   label: 'Fact-check',       match: /fact[\s-]?check/i,     icon: <ShieldCheck size={12} /> },
  { id: 'audio_design', label: 'Audio design',     match: /audio design/i,        icon: <Music size={12} /> },
  { id: 'tts',          label: 'Speech synthesis', match: /generating audio|tts/i, icon: <Mic size={12} /> },
  { id: 'assemble',     label: 'Assembly',         match: /assembl(ing|y)/i,      icon: <Layers size={12} /> },
];

function buildStageRows({ logs, currentStage, isGenerating, lastError, progress }) {
  const currentIdx = PIPELINE_STAGES.findIndex((s) => s.match.test(currentStage || ''));
  const hasResults = progress >= 100;

  // Group logs by bracket prefix
  const buckets = PIPELINE_STAGES.map(() => []);
  for (const line of logs) {
    const m = line.match(/^\[(.+?)\]\s*(.*)$/);
    if (!m) continue;
    const tag = m[1];
    const idx = PIPELINE_STAGES.findIndex((s) => s.match.test(tag));
    if (idx >= 0) {
      buckets[idx].push(m[2] || line);
    }
  }

  return PIPELINE_STAGES.map((stage, i) => {
    let status = 'pending';
    if (hasResults) {
      status = 'done';
    } else if (currentIdx >= 0) {
      if (i < currentIdx)        status = 'done';
      else if (i === currentIdx) status = lastError ? 'error' : (isGenerating ? 'active' : 'done');
      else                        status = 'pending';
    } else if (buckets[i].length > 0) {
      status = 'done';
    }
    return {
      ...stage,
      status,
      logs: buckets[i],
    };
  });
}

// Live ticker showing elapsed seconds since `since`
function useElapsed(active, since) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  if (!since) return '';
  const s = Math.max(0, Math.floor((now - since) / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${String(r).padStart(2, '0')}s` : `${r}s`;
}

export default function ProgressPanel({
  isGenerating,
  currentStage,
  progress,
  logs,
  lastError,
  onRetry,
}) {
  // Track when generation started for elapsed counter
  const startedAtRef = useRef(null);
  useEffect(() => {
    if (isGenerating && !startedAtRef.current) {
      startedAtRef.current = Date.now();
    }
    if (!isGenerating && progress >= 100) {
      // Keep startedAt so user can see total elapsed in idle state
    }
    if (!isGenerating && progress === 0) {
      startedAtRef.current = null;
    }
  }, [isGenerating, progress]);

  const elapsed = useElapsed(isGenerating, startedAtRef.current);
  const stages = useMemo(
    () => buildStageRows({ logs, currentStage, isGenerating, lastError, progress }),
    [logs, currentStage, isGenerating, lastError, progress],
  );

  const stageLabel = currentStage || (isGenerating ? 'Initialising' : 'Idle');

  return (
    <Card padding="none">
      <CardHeader>
        <CardTitle eyebrow="Pipeline">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            {stageLabel}
            {isGenerating && (
              <motion.span
                animate={{ rotate: 360 }}
                transition={{ repeat: Infinity, duration: 1.4, ease: 'linear' }}
                style={{ display: 'inline-flex', color: 'var(--brand-300)' }}
              >
                <Activity size={14} />
              </motion.span>
            )}
          </span>
        </CardTitle>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          {elapsed && (
            <Badge variant="ghost" size="sm">
              <span className="tabular-nums">{elapsed}</span>
            </Badge>
          )}
          <Badge variant={isGenerating ? 'brand' : 'ghost'} size="sm" dot pulse={isGenerating}>
            {progress}%
          </Badge>
        </div>
      </CardHeader>

      {/* Progress hairline */}
      <div
        style={{
          position: 'relative',
          height: 3,
          background: 'rgba(255, 255, 255, 0.05)',
          overflow: 'hidden',
        }}
      >
        <motion.div
          animate={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
          transition={{ type: 'spring', stiffness: 80, damping: 20 }}
          style={{
            height: '100%',
            background: 'var(--brand-gradient)',
            backgroundSize: '200% 100%',
            animation: isGenerating ? 'bg-pan 4s linear infinite' : 'none',
            boxShadow: '0 0 12px var(--brand-glow)',
          }}
        />
      </div>

      {/* Stage timeline body */}
      <div style={{ padding: 'var(--space-5) var(--space-6)' }}>
        <StageTimeline stages={stages} />
      </div>

      {/* Error banner */}
      <AnimatePresence>
        {lastError && !isGenerating && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div
              style={{
                margin: 'var(--space-3) var(--space-6) var(--space-6)',
                padding: 'var(--space-4)',
                background: 'var(--danger-bg)',
                border: '1px solid var(--danger-border)',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                gap: 'var(--space-4)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)', minWidth: 0 }}>
                <span
                  style={{
                    flexShrink: 0,
                    display: 'inline-flex',
                    width: 28, height: 28,
                    alignItems: 'center', justifyContent: 'center',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(248, 113, 113, 0.18)',
                    color: 'var(--danger)',
                    border: '1px solid var(--danger-border)',
                  }}
                >
                  <AlertTriangle size={14} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 'var(--text-sm)',
                      fontWeight: 600,
                      color: 'var(--danger)',
                      letterSpacing: 'var(--tracking-tight)',
                    }}
                  >
                    Generation halted
                  </div>
                  <div
                    style={{
                      marginTop: 2,
                      fontSize: 'var(--text-xs)',
                      color: 'var(--text-secondary)',
                      lineHeight: 'var(--leading-snug)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {lastError}
                  </div>
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                iconLeft={<RefreshCw size={12} />}
                onClick={onRetry}
                style={{ flexShrink: 0 }}
              >
                Retry
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
