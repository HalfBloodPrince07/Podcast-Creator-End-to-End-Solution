import { forwardRef, useId, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, AlertCircle } from 'lucide-react';

/**
 * Input primitives — Input, Textarea, Select.
 * All support `label`, `hint`, `error`, `iconLeft`, `iconRight`.
 */

const fieldBase = {
  width: '100%',
  fontFamily: 'inherit',
  fontSize: 'var(--text-sm)',
  lineHeight: 'var(--leading-normal)',
  color: 'var(--text-primary)',
  background: 'rgba(10, 10, 15, 0.55)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-sm)',
  padding: '10px 14px',
  transition:
    'border-color 0.14s var(--ease-snap), background 0.14s var(--ease-snap), box-shadow 0.14s var(--ease-snap)',
  outline: 'none',
};

function FieldLabel({ htmlFor, children, optional }) {
  if (!children) return null;
  return (
    <label
      htmlFor={htmlFor}
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        marginBottom: 'var(--space-2)',
        fontSize: 'var(--text-xs)',
        fontWeight: 500,
        color: 'var(--text-secondary)',
        letterSpacing: '0.01em',
      }}
    >
      <span>{children}</span>
      {optional && (
        <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)', fontWeight: 400 }}>
          Optional
        </span>
      )}
    </label>
  );
}

function FieldFooter({ hint, error }) {
  return (
    <AnimatePresence mode="wait">
      {error ? (
        <motion.div
          key="error"
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.14 }}
          style={{
            marginTop: 'var(--space-2)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-1)',
            fontSize: 'var(--text-xs)',
            color: 'var(--danger)',
          }}
        >
          <AlertCircle size={12} />
          {error}
        </motion.div>
      ) : hint ? (
        <motion.div
          key="hint"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          style={{
            marginTop: 'var(--space-2)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-tertiary)',
          }}
        >
          {hint}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

export const Input = forwardRef(function Input(
  { label, hint, error, optional, iconLeft, iconRight, style, id, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id || autoId;
  const [focused, setFocused] = useState(false);
  const hasIcon = !!iconLeft || !!iconRight;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <FieldLabel htmlFor={inputId} optional={optional}>{label}</FieldLabel>
      <div style={{ position: 'relative' }}>
        {iconLeft && (
          <span
            style={{
              position: 'absolute',
              left: 12,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-tertiary)',
              pointerEvents: 'none',
              display: 'inline-flex',
            }}
          >
            {iconLeft}
          </span>
        )}
        <input
          ref={ref}
          id={inputId}
          onFocus={(e) => { setFocused(true); rest.onFocus?.(e); }}
          onBlur={(e) => { setFocused(false); rest.onBlur?.(e); }}
          style={{
            ...fieldBase,
            paddingLeft: iconLeft ? 38 : 14,
            paddingRight: iconRight ? 38 : 14,
            borderColor: error
              ? 'var(--danger-border)'
              : focused
              ? 'var(--brand-400)'
              : 'var(--border-default)',
            boxShadow: focused
              ? error
                ? '0 0 0 3px rgba(248, 113, 113, 0.18)'
                : '0 0 0 3px var(--brand-glow)'
              : 'none',
            background: focused ? 'rgba(20, 20, 30, 0.85)' : fieldBase.background,
            ...style,
          }}
          {...rest}
        />
        {iconRight && (
          <span
            style={{
              position: 'absolute',
              right: 12,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-tertiary)',
              pointerEvents: 'none',
              display: 'inline-flex',
            }}
          >
            {iconRight}
          </span>
        )}
      </div>
      <FieldFooter hint={hint} error={error} />
    </div>
  );
});

export const Textarea = forwardRef(function Textarea(
  { label, hint, error, optional, rows = 4, style, id, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id || autoId;
  const [focused, setFocused] = useState(false);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <FieldLabel htmlFor={inputId} optional={optional}>{label}</FieldLabel>
      <textarea
        ref={ref}
        id={inputId}
        rows={rows}
        onFocus={(e) => { setFocused(true); rest.onFocus?.(e); }}
        onBlur={(e) => { setFocused(false); rest.onBlur?.(e); }}
        style={{
          ...fieldBase,
          minHeight: 88,
          resize: 'vertical',
          lineHeight: 'var(--leading-relaxed)',
          borderColor: error
            ? 'var(--danger-border)'
            : focused
            ? 'var(--brand-400)'
            : 'var(--border-default)',
          boxShadow: focused
            ? error
              ? '0 0 0 3px rgba(248, 113, 113, 0.18)'
              : '0 0 0 3px var(--brand-glow)'
            : 'none',
          background: focused ? 'rgba(20, 20, 30, 0.85)' : fieldBase.background,
          ...style,
        }}
        {...rest}
      />
      <FieldFooter hint={hint} error={error} />
    </div>
  );
});

export const Select = forwardRef(function Select(
  { label, hint, error, optional, children, style, id, ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id || autoId;
  const [focused, setFocused] = useState(false);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <FieldLabel htmlFor={inputId} optional={optional}>{label}</FieldLabel>
      <div style={{ position: 'relative' }}>
        <select
          ref={ref}
          id={inputId}
          onFocus={(e) => { setFocused(true); rest.onFocus?.(e); }}
          onBlur={(e) => { setFocused(false); rest.onBlur?.(e); }}
          style={{
            ...fieldBase,
            paddingRight: 38,
            appearance: 'none',
            WebkitAppearance: 'none',
            MozAppearance: 'none',
            cursor: 'pointer',
            borderColor: error
              ? 'var(--danger-border)'
              : focused
              ? 'var(--brand-400)'
              : 'var(--border-default)',
            boxShadow: focused
              ? error
                ? '0 0 0 3px rgba(248, 113, 113, 0.18)'
                : '0 0 0 3px var(--brand-glow)'
              : 'none',
            background: focused ? 'rgba(20, 20, 30, 0.85)' : fieldBase.background,
            ...style,
          }}
          {...rest}
        >
          {children}
        </select>
        <ChevronDown
          size={14}
          style={{
            position: 'absolute',
            right: 12,
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--text-tertiary)',
            pointerEvents: 'none',
          }}
        />
      </div>
      <FieldFooter hint={hint} error={error} />
    </div>
  );
});

export default Input;
