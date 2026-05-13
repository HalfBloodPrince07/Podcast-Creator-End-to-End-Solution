import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, FileText } from 'lucide-react';
import Badge from './ui/Badge';

function countWords(text) {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

export default function ScriptViewer({ script }) {
  if (!script || script.length === 0) return null;

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
        <span
          style={{
            display: 'inline-flex',
            width: 24, height: 24,
            alignItems: 'center', justifyContent: 'center',
            borderRadius: 'var(--radius-xs)',
            background: 'rgba(77, 208, 225, 0.12)',
            color: 'var(--accent-cyan)',
          }}
        >
          <FileText size={13} />
        </span>
        <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 600 }}>Final script</h3>
        <Badge variant="ghost" size="xs">{script.length} segments</Badge>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        {script.map((seg, i) => (
          <ScriptSegmentRow key={`${seg.name}-${i}`} seg={seg} index={i} />
        ))}
      </div>
    </section>
  );
}

function ScriptSegmentRow({ seg, index }) {
  const [open, setOpen] = useState(false);
  const words = seg.actual_words ?? countWords(seg.text);

  return (
    <div
      style={{
        background: 'rgba(0, 0, 0, 0.25)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          padding: 'var(--space-3) var(--space-4)',
          background: 'transparent',
          border: 'none',
          color: 'inherit',
          textAlign: 'left',
          cursor: 'pointer',
          font: 'inherit',
        }}
      >
        <span
          style={{
            display: 'inline-flex',
            width: 22, height: 22,
            alignItems: 'center', justifyContent: 'center',
            borderRadius: 'var(--radius-xs)',
            background: 'rgba(124, 92, 255, 0.12)',
            color: 'var(--brand-300)',
            fontSize: 'var(--text-2xs)',
            fontWeight: 700,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {String(index + 1).padStart(2, '0')}
        </span>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, flex: 1, minWidth: 0 }}>
          {seg.name}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <Badge variant="ghost" size="xs">
            <span className="tabular-nums">{words}w</span>
          </Badge>
          {seg.target_seconds && (
            <Badge variant="ghost" size="xs">
              <span className="tabular-nums">~{Math.round(seg.target_seconds)}s</span>
            </Badge>
          )}
          <motion.span
            animate={{ rotate: open ? 0 : -90 }}
            transition={{ duration: 0.22 }}
            style={{ display: 'inline-flex', color: 'var(--text-tertiary)' }}
          >
            <ChevronDown size={14} />
          </motion.span>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div
              style={{
                padding: 'var(--space-3) var(--space-4) var(--space-4)',
                borderTop: '1px solid var(--border-subtle)',
                whiteSpace: 'pre-wrap',
                color: 'var(--text-secondary)',
                fontSize: 'var(--text-sm)',
                lineHeight: 'var(--leading-relaxed)',
              }}
            >
              {seg.text}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
