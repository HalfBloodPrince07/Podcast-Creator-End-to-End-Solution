import { forwardRef } from 'react';
import { motion } from 'framer-motion';

/**
 * IconButton — square icon-only control with optional tooltip-style title.
 */

const variants = {
  default: {
    background: 'rgba(255, 255, 255, 0.04)',
    color: 'var(--text-secondary)',
    border: '1px solid var(--border-default)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-tertiary)',
    border: '1px solid transparent',
  },
  primary: {
    background: 'var(--brand-gradient)',
    color: '#fff',
    border: '1px solid transparent',
    boxShadow: '0 4px 16px rgba(124, 92, 255, 0.3)',
  },
  danger: {
    background: 'var(--danger-bg)',
    color: 'var(--danger)',
    border: '1px solid var(--danger-border)',
  },
};

const sizes = {
  sm: { size: 28, radius: 'var(--radius-xs)' },
  md: { size: 34, radius: 'var(--radius-sm)' },
  lg: { size: 40, radius: 'var(--radius-sm)' },
};

const IconButton = forwardRef(function IconButton(
  { variant = 'default', size = 'md', title, disabled = false, style, onClick, children, ...rest },
  ref,
) {
  const v = variants[variant];
  const s = sizes[size];

  return (
    <motion.button
      ref={ref}
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      whileHover={disabled ? {} : { y: -1, borderColor: 'var(--border-strong)' }}
      whileTap={disabled ? {} : { scale: 0.92 }}
      transition={{ duration: 0.14 }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: s.size,
        height: s.size,
        borderRadius: s.radius,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transition: 'background 0.14s, color 0.14s',
        ...v,
        ...style,
      }}
      {...rest}
    >
      {children}
    </motion.button>
  );
});

export default IconButton;
