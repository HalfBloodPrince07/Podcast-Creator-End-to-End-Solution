import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';

/**
 * Section — collapsible labeled segment used inside a Card.
 * Eyebrow label + title + optional right-side meta + content.
 */

export default function Section({
  title,
  eyebrow,
  icon,
  meta,
  defaultOpen = true,
  collapsible = true,
  children,
  style,
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      style={{
        borderBottom: '1px solid var(--border-subtle)',
        ...style,
      }}
    >
      <button
        type="button"
        onClick={collapsible ? () => setOpen((o) => !o) : undefined}
        aria-expanded={open}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--space-3)',
          padding: 'var(--space-5) var(--space-6)',
          background: 'transparent',
          border: 'none',
          color: 'inherit',
          cursor: collapsible ? 'pointer' : 'default',
          textAlign: 'left',
          font: 'inherit',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flex: 1, minWidth: 0 }}>
          {icon && (
            <span
              style={{
                display: 'inline-flex',
                width: 28,
                height: 28,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(124, 92, 255, 0.12)',
                color: 'var(--brand-300)',
                border: '1px solid rgba(124, 92, 255, 0.2)',
              }}
            >
              {icon}
            </span>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
            {eyebrow && (
              <span
                style={{
                  fontSize: 'var(--text-2xs)',
                  fontWeight: 600,
                  letterSpacing: 'var(--tracking-wide)',
                  color: 'var(--text-tertiary)',
                  textTransform: 'uppercase',
                }}
              >
                {eyebrow}
              </span>
            )}
            <span
              style={{
                fontSize: 'var(--text-md)',
                fontWeight: 600,
                color: 'var(--text-primary)',
                letterSpacing: 'var(--tracking-tight)',
              }}
            >
              {title}
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          {meta && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
              {meta}
            </span>
          )}
          {collapsible && (
            <motion.span
              animate={{ rotate: open ? 0 : -90 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              style={{ color: 'var(--text-tertiary)', display: 'inline-flex' }}
            >
              <ChevronDown size={16} />
            </motion.span>
          )}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '0 var(--space-6) var(--space-6)' }}>
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
