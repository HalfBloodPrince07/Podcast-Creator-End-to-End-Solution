import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, ChevronDown, Circle, X, Loader2 } from 'lucide-react';

/**
 * StageTimeline — Vercel-style pipeline tracker.
 *
 * Pure rendering primitive. Parent passes pre-grouped stages.
 *
 * Props:
 *   stages: [{
 *     id: string,
 *     label: string,
 *     icon?: ReactNode,                       // small icon left of label
 *     status: 'pending' | 'active' | 'done' | 'error',
 *     elapsedMs?: number,                     // optional, rendered as "Xm Ys"
 *     logs?: string[],                        // collapsible sub-log lines
 *   }]
 */

function fmtElapsed(ms) {
  if (ms == null) return null;
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m === 0) return `${r}s`;
  return `${m}m ${String(r).padStart(2, '0')}s`;
}

const statusColors = {
  pending: 'var(--text-tertiary)',
  active:  'var(--brand-300)',
  done:    'var(--success)',
  error:   'var(--danger)',
};

function StatusIcon({ status }) {
  if (status === 'done') {
    return (
      <span
        style={{
          display: 'inline-flex',
          width: 22, height: 22,
          alignItems: 'center', justifyContent: 'center',
          borderRadius: '50%',
          background: 'var(--success-bg)',
          color: 'var(--success)',
          border: '1px solid var(--success-border)',
        }}
      >
        <Check size={12} strokeWidth={3} />
      </span>
    );
  }
  if (status === 'error') {
    return (
      <span
        style={{
          display: 'inline-flex',
          width: 22, height: 22,
          alignItems: 'center', justifyContent: 'center',
          borderRadius: '50%',
          background: 'var(--danger-bg)',
          color: 'var(--danger)',
          border: '1px solid var(--danger-border)',
        }}
      >
        <X size={12} strokeWidth={3} />
      </span>
    );
  }
  if (status === 'active') {
    return (
      <span
        style={{
          display: 'inline-flex',
          width: 22, height: 22,
          alignItems: 'center', justifyContent: 'center',
          borderRadius: '50%',
          background: 'rgba(124, 92, 255, 0.18)',
          color: 'var(--brand-300)',
          border: '1px solid rgba(124, 92, 255, 0.5)',
          boxShadow: '0 0 0 4px rgba(124, 92, 255, 0.12)',
        }}
      >
        <motion.span
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 1.4, ease: 'linear' }}
          style={{ display: 'inline-flex' }}
        >
          <Loader2 size={12} strokeWidth={2.5} />
        </motion.span>
      </span>
    );
  }
  return (
    <span
      style={{
        display: 'inline-flex',
        width: 22, height: 22,
        alignItems: 'center', justifyContent: 'center',
        borderRadius: '50%',
        background: 'transparent',
        color: 'var(--text-tertiary)',
        border: '1px solid var(--border-default)',
      }}
    >
      <Circle size={6} strokeWidth={0} fill="currentColor" />
    </span>
  );
}

function StageRow({ stage, isLast }) {
  const [open, setOpen] = useState(stage.status === 'active');
  const canExpand = !!stage.logs?.length;
  const elapsedLabel = fmtElapsed(stage.elapsedMs);
  const c = statusColors[stage.status];

  return (
    <div style={{ position: 'relative', paddingLeft: 0 }}>
      {/* Vertical connector */}
      {!isLast && (
        <span
          aria-hidden
          style={{
            position: 'absolute',
            left: 10,
            top: 30,
            bottom: -8,
            width: 1,
            background:
              stage.status === 'done'
                ? 'linear-gradient(180deg, var(--success-border), var(--border-subtle) 80%)'
                : 'var(--border-subtle)',
          }}
        />
      )}

      <button
        type="button"
        onClick={canExpand ? () => setOpen((o) => !o) : undefined}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          width: '100%',
          padding: 'var(--space-2) 0',
          background: 'transparent',
          border: 'none',
          color: 'inherit',
          textAlign: 'left',
          cursor: canExpand ? 'pointer' : 'default',
          font: 'inherit',
        }}
      >
        <StatusIcon status={stage.status} />

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flex: 1, minWidth: 0 }}>
          {stage.icon && (
            <span style={{ display: 'inline-flex', color: c, opacity: 0.85 }}>{stage.icon}</span>
          )}
          <span
            style={{
              fontSize: 'var(--text-sm)',
              fontWeight: stage.status === 'pending' ? 400 : 600,
              color: stage.status === 'pending' ? 'var(--text-tertiary)' : 'var(--text-primary)',
              letterSpacing: 'var(--tracking-tight)',
            }}
          >
            {stage.label}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          {elapsedLabel && (
            <span
              style={{
                fontSize: 'var(--text-2xs)',
                fontVariantNumeric: 'tabular-nums',
                color: stage.status === 'active' ? 'var(--brand-300)' : 'var(--text-tertiary)',
                fontWeight: 600,
                letterSpacing: 'var(--tracking-wide)',
              }}
            >
              {elapsedLabel}
            </span>
          )}
          {canExpand && (
            <motion.span
              animate={{ rotate: open ? 0 : -90 }}
              transition={{ duration: 0.22 }}
              style={{ display: 'inline-flex', color: 'var(--text-tertiary)' }}
            >
              <ChevronDown size={14} />
            </motion.span>
          )}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && canExpand && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div
              style={{
                marginLeft: 34,
                marginTop: 'var(--space-1)',
                marginBottom: 'var(--space-3)',
                padding: 'var(--space-3) var(--space-4)',
                borderLeft: '2px solid var(--border-subtle)',
                background: 'rgba(0, 0, 0, 0.25)',
                borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-xs)',
                lineHeight: 'var(--leading-relaxed)',
                color: 'var(--text-secondary)',
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              {stage.logs.map((line, i) => (
                <div key={i} style={{ opacity: 0.85, paddingBottom: 2 }}>
                  {line}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function StageTimeline({ stages, style }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', ...style }}>
      {stages.map((stage, i) => (
        <StageRow key={stage.id} stage={stage} isLast={i === stages.length - 1} />
      ))}
    </div>
  );
}

export { StageRow };
