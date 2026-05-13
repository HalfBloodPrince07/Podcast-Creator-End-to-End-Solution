import { useState, useEffect, useRef, useMemo } from 'react';
import { motion } from 'framer-motion';
import { Play, X, Timer, FileText } from 'lucide-react';

import Card, { CardHeader, CardTitle } from './ui/Card';
import Button from './ui/Button';
import Badge from './ui/Badge';
import { Textarea } from './ui/Input';

const TIMEOUT_SECONDS = 120; // auto-resume after 2 minutes of inactivity

function countWords(text) {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * ScriptEditor — pause-for-review surface between audio_design and TTS.
 * Editable segments + auto-resume countdown after 2 min of inactivity.
 */
export default function ScriptEditor({ pausedState, onResume, onCancel }) {
  const [segments, setSegments] = useState([]);
  const [secondsLeft, setSecondsLeft] = useState(TIMEOUT_SECONDS);

  const segmentsRef = useRef([]);
  const resumedRef = useRef(false);
  const intervalRef = useRef(null);

  useEffect(() => {
    const initial = (pausedState?.segments || []).map((s) => ({ ...s }));
    setSegments(initial);
    segmentsRef.current = initial;
    setSecondsLeft(TIMEOUT_SECONDS);
    resumedRef.current = false;
  }, [pausedState]);

  useEffect(() => {
    segmentsRef.current = segments;
  }, [segments]);

  useEffect(() => {
    if (!pausedState) return;
    intervalRef.current = setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          clearInterval(intervalRef.current);
          if (!resumedRef.current) {
            resumedRef.current = true;
            const edited = segmentsRef.current.map((s) => ({ name: s.name, text: s.text }));
            onResume(edited);
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(intervalRef.current);
  }, [pausedState, onResume]);

  if (!pausedState) return null;

  const updateText = (idx, newText) => {
    setSegments((prev) => prev.map((s, i) => (i === idx ? { ...s, text: newText } : s)));
  };

  const handleResume = () => {
    if (resumedRef.current) return;
    resumedRef.current = true;
    clearInterval(intervalRef.current);
    const edited = segments.map((s) => ({ name: s.name, text: s.text }));
    onResume(edited);
  };

  const handleCancel = () => {
    clearInterval(intervalRef.current);
    onCancel?.();
  };

  // Footer totals
  const totals = useMemo(() => {
    const totalWords = segments.reduce((acc, s) => acc + countWords(s.text || ''), 0);
    const targetSeconds = segments.reduce(
      (acc, s) => acc + (Number(s.target_seconds) || 0),
      0,
    );
    return {
      totalWords,
      targetMin: Math.round(targetSeconds / 60),
    };
  }, [segments]);

  // Countdown styling
  const urgency = secondsLeft <= 30 ? 'danger' : secondsLeft <= 60 ? 'warning' : 'success';
  const mm = String(Math.floor(secondsLeft / 60)).padStart(2, '0');
  const ss = String(secondsLeft % 60).padStart(2, '0');

  return (
    <Card padding="none" variant="glow">
      <CardHeader>
        <CardTitle eyebrow="Review">Edit your script</CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <Badge variant={urgency} size="sm" icon={<Timer size={11} />}>
            <span className="tabular-nums">{mm}:{ss}</span>
          </Badge>
        </div>
      </CardHeader>

      {/* Drain bar */}
      <div
        style={{
          position: 'relative',
          height: 3,
          background: 'rgba(255, 255, 255, 0.05)',
          overflow: 'hidden',
        }}
      >
        <motion.div
          animate={{ scaleX: secondsLeft / TIMEOUT_SECONDS }}
          transition={{ duration: 0.95, ease: 'linear' }}
          style={{
            position: 'absolute',
            inset: 0,
            transformOrigin: 'left',
            background:
              urgency === 'danger'
                ? 'linear-gradient(90deg, #F87171, #FCA5A5)'
                : urgency === 'warning'
                ? 'linear-gradient(90deg, #FFB547, #FCD34D)'
                : 'var(--brand-gradient)',
            boxShadow: '0 0 12px var(--brand-glow)',
          }}
        />
      </div>

      {/* Sub-header */}
      <div
        style={{
          padding: 'var(--space-3) var(--space-6)',
          borderBottom: '1px solid var(--border-subtle)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-tertiary)',
          lineHeight: 'var(--leading-relaxed)',
        }}
      >
        Edit any segment below. The pipeline auto-resumes when the timer hits zero — your edits are preserved.
      </div>

      {/* Narrative arc */}
      {pausedState.narrative_arc && (
        <div
          style={{
            padding: 'var(--space-4) var(--space-6)',
            borderBottom: '1px solid var(--border-subtle)',
            background: 'rgba(0, 0, 0, 0.15)',
          }}
        >
          <div
            style={{
              fontSize: 'var(--text-2xs)',
              fontWeight: 600,
              color: 'var(--brand-300)',
              letterSpacing: 'var(--tracking-wide)',
              textTransform: 'uppercase',
              marginBottom: 'var(--space-2)',
            }}
          >
            Narrative arc
          </div>
          <pre
            style={{
              margin: 0,
              fontFamily: 'inherit',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
              lineHeight: 'var(--leading-relaxed)',
              whiteSpace: 'pre-wrap',
            }}
          >
            {pausedState.narrative_arc}
          </pre>
        </div>
      )}

      {/* Segments */}
      <div
        style={{
          padding: 'var(--space-6)',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        {segments.map((seg, i) => {
          const wordCount = countWords(seg.text || '');
          const target = Number(seg.target_words) || 0;
          const delta = target ? ((wordCount - target) / target) * 100 : 0;
          const deltaSign = delta > 0 ? '+' : '';
          const deltaBadge =
            target === 0
              ? 'ghost'
              : Math.abs(delta) <= 10
              ? 'success'
              : Math.abs(delta) <= 25
              ? 'warning'
              : 'danger';

          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03, duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              style={{
                background: 'rgba(0, 0, 0, 0.25)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 'var(--space-3)',
                  padding: '10px var(--space-4)',
                  background: 'rgba(124, 92, 255, 0.05)',
                  borderBottom: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', minWidth: 0 }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      width: 24, height: 24,
                      alignItems: 'center', justifyContent: 'center',
                      borderRadius: 'var(--radius-xs)',
                      background: 'rgba(124, 92, 255, 0.12)',
                      color: 'var(--brand-300)',
                      border: '1px solid rgba(124, 92, 255, 0.25)',
                      fontSize: 'var(--text-2xs)',
                      fontWeight: 700,
                      fontVariantNumeric: 'tabular-nums',
                      letterSpacing: 'var(--tracking-wide)',
                    }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span
                    style={{
                      fontSize: 'var(--text-sm)',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      letterSpacing: 'var(--tracking-tight)',
                    }}
                  >
                    {seg.name}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                  <Badge variant={deltaBadge} size="xs">
                    <span className="tabular-nums">
                      {wordCount}
                      {target > 0 && ` / ~${target}`}
                      {target > 0 && ` · ${deltaSign}${delta.toFixed(0)}%`}
                    </span>
                  </Badge>
                  {seg.target_seconds && (
                    <Badge variant="ghost" size="xs">
                      <span className="tabular-nums">~{Math.round(seg.target_seconds)}s</span>
                    </Badge>
                  )}
                </div>
              </div>
              <Textarea
                value={seg.text || ''}
                onChange={(e) => updateText(i, e.target.value)}
                rows={Math.max(4, Math.min(20, (seg.text || '').split('\n').length + 2))}
                style={{
                  background: 'transparent',
                  border: 'none',
                  borderRadius: 0,
                  padding: 'var(--space-4)',
                  fontSize: 'var(--text-sm)',
                  lineHeight: 'var(--leading-relaxed)',
                  color: 'var(--text-primary)',
                  boxShadow: 'none',
                }}
              />
            </motion.div>
          );
        })}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: 'var(--space-4) var(--space-6)',
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 'var(--space-3)',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <Badge variant="ghost" size="sm" icon={<FileText size={11} />}>
            <span className="tabular-nums">{totals.totalWords} words</span>
          </Badge>
          {totals.targetMin > 0 && (
            <Badge variant="ghost" size="sm" icon={<Timer size={11} />}>
              <span className="tabular-nums">~{totals.targetMin} min</span>
            </Badge>
          )}
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          {onCancel && (
            <Button variant="secondary" size="md" iconLeft={<X size={14} />} onClick={handleCancel}>
              Cancel
            </Button>
          )}
          <Button variant="primary" size="md" iconLeft={<Play size={14} />} onClick={handleResume}>
            Resume now
          </Button>
        </div>
      </div>
    </Card>
  );
}
