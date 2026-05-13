/**
 * Badge — semantic status pill.
 * Variants: neutral | brand | success | warning | danger | info | ghost
 * Sizes:    xs | sm | md
 */

const variants = {
  neutral: {
    background: 'rgba(255, 255, 255, 0.06)',
    color: 'var(--text-secondary)',
    border: '1px solid var(--border-default)',
  },
  brand: {
    background: 'rgba(124, 92, 255, 0.15)',
    color: 'var(--brand-300)',
    border: '1px solid rgba(124, 92, 255, 0.3)',
  },
  success: {
    background: 'var(--success-bg)',
    color: 'var(--success)',
    border: '1px solid var(--success-border)',
  },
  warning: {
    background: 'var(--warning-bg)',
    color: 'var(--warning)',
    border: '1px solid var(--warning-border)',
  },
  danger: {
    background: 'var(--danger-bg)',
    color: 'var(--danger)',
    border: '1px solid var(--danger-border)',
  },
  info: {
    background: 'var(--info-bg)',
    color: 'var(--info)',
    border: '1px solid var(--info-border)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-tertiary)',
    border: '1px solid var(--border-subtle)',
  },
};

const sizes = {
  xs: { padding: '2px 8px',  fontSize: 'var(--text-2xs)', height: 20, gap: 4 },
  sm: { padding: '3px 10px', fontSize: 'var(--text-xs)',  height: 22, gap: 5 },
  md: { padding: '5px 12px', fontSize: 'var(--text-xs)',  height: 26, gap: 6 },
};

export default function Badge({
  variant = 'neutral',
  size = 'sm',
  icon,
  dot = false,
  pulse = false,
  children,
  style,
  ...rest
}) {
  const v = variants[variant];
  const s = sizes[size];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: s.gap,
        padding: s.padding,
        height: s.height,
        fontSize: s.fontSize,
        fontWeight: 600,
        letterSpacing: 'var(--tracking-wide)',
        borderRadius: 'var(--radius-pill)',
        whiteSpace: 'nowrap',
        ...v,
        ...style,
      }}
      {...rest}
    >
      {dot && (
        <span
          style={{
            display: 'inline-block',
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: 'currentColor',
            animation: pulse ? 'pulse-dot 1.6s ease-in-out infinite' : 'none',
          }}
        />
      )}
      {icon && <span style={{ display: 'inline-flex' }}>{icon}</span>}
      {children}
    </span>
  );
}
