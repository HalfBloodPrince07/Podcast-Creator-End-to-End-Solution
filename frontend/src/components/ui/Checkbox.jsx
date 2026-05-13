import { useId } from 'react';
import { motion } from 'framer-motion';
import { Check } from 'lucide-react';

/**
 * Checkbox — custom-styled with brand color and motion check.
 */

export default function Checkbox({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  id,
  style,
}) {
  const autoId = useId();
  const inputId = id || autoId;

  return (
    <label
      htmlFor={inputId}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-3)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        userSelect: 'none',
        ...style,
      }}
    >
      <span
        style={{
          position: 'relative',
          flexShrink: 0,
          width: 18,
          height: 18,
          marginTop: 1,
          borderRadius: 'var(--radius-xs)',
          border: `1.5px solid ${checked ? 'var(--brand-500)' : 'var(--border-strong)'}`,
          background: checked ? 'var(--brand-500)' : 'transparent',
          boxShadow: checked ? '0 0 0 3px var(--brand-glow)' : 'none',
          transition: 'all 0.14s var(--ease-snap)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <input
          id={inputId}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            opacity: 0,
            cursor: disabled ? 'not-allowed' : 'pointer',
            margin: 0,
          }}
        />
        {checked && (
          <motion.span
            initial={{ scale: 0, rotate: -20 }}
            animate={{ scale: 1, rotate: 0 }}
            transition={{ duration: 0.18, ease: [0.34, 1.56, 0.64, 1] }}
            style={{ display: 'inline-flex', color: '#fff' }}
          >
            <Check size={12} strokeWidth={3} />
          </motion.span>
        )}
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', gap: 2, lineHeight: 'var(--leading-snug)' }}>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 500, color: 'var(--text-primary)' }}>
          {label}
        </span>
        {description && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
            {description}
          </span>
        )}
      </span>
    </label>
  );
}
