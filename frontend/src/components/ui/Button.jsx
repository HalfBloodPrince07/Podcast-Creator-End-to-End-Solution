import { forwardRef } from 'react';
import { motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';

/**
 * Button — enterprise primitive
 * Variants: primary | secondary | ghost | destructive
 * Sizes:    sm | md | lg
 */

const variants = {
  primary: {
    background: 'var(--brand-gradient)',
    color: '#fff',
    border: '1px solid transparent',
    boxShadow:
      '0 4px 16px rgba(124, 92, 255, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.15)',
  },
  secondary: {
    background: 'rgba(255, 255, 255, 0.04)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-default)',
    boxShadow: 'none',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-secondary)',
    border: '1px solid transparent',
    boxShadow: 'none',
  },
  destructive: {
    background: 'var(--danger-bg)',
    color: 'var(--danger)',
    border: '1px solid var(--danger-border)',
    boxShadow: 'none',
  },
};

const sizes = {
  sm: { padding: '6px 12px',  fontSize: 'var(--text-xs)',  borderRadius: 'var(--radius-sm)', height: 28, gap: 'var(--space-1)' },
  md: { padding: '10px 16px', fontSize: 'var(--text-sm)',  borderRadius: 'var(--radius-md)', height: 36, gap: 'var(--space-2)' },
  lg: { padding: '12px 22px', fontSize: 'var(--text-base)', borderRadius: 'var(--radius-md)', height: 44, gap: 'var(--space-2)' },
};

const hoverShadow = {
  primary:
    '0 8px 24px rgba(124, 92, 255, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.2)',
  secondary: 'none',
  ghost: 'none',
  destructive: '0 4px 16px rgba(248, 113, 113, 0.25)',
};

const Button = forwardRef(function Button(
  {
    variant = 'primary',
    size = 'md',
    iconLeft,
    iconRight,
    loading = false,
    disabled = false,
    fullWidth = false,
    children,
    style,
    onClick,
    type = 'button',
    ...rest
  },
  ref,
) {
  const v = variants[variant];
  const s = sizes[size];
  const isDisabled = disabled || loading;

  return (
    <motion.button
      ref={ref}
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      whileHover={isDisabled ? {} : { y: -1, boxShadow: hoverShadow[variant] }}
      whileTap={isDisabled ? {} : { scale: 0.97 }}
      transition={{ duration: 0.14, ease: [0.2, 0.8, 0.2, 1] }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: s.gap,
        padding: s.padding,
        height: s.height,
        minWidth: s.height,
        fontFamily: 'inherit',
        fontWeight: 600,
        fontSize: s.fontSize,
        letterSpacing: '0.01em',
        borderRadius: s.borderRadius,
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        userSelect: 'none',
        whiteSpace: 'nowrap',
        position: 'relative',
        width: fullWidth ? '100%' : undefined,
        opacity: isDisabled ? 0.55 : 1,
        ...v,
        ...style,
      }}
      {...rest}
    >
      {loading ? (
        <Loader2 size={size === 'sm' ? 14 : 16} className="spinner" style={{ animation: 'spin 0.9s linear infinite' }} />
      ) : (
        iconLeft && <span style={{ display: 'inline-flex' }}>{iconLeft}</span>
      )}
      {children && <span>{children}</span>}
      {!loading && iconRight && <span style={{ display: 'inline-flex' }}>{iconRight}</span>}
    </motion.button>
  );
});

export default Button;
