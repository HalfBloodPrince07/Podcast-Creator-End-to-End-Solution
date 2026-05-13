import { forwardRef } from 'react';
import { motion } from 'framer-motion';

/**
 * Card — primary bento tile primitive.
 * Variants: default | raised | glow
 * Padding: sm | md | lg | none
 */

const paddings = {
  none: 0,
  sm:   'var(--space-4)',
  md:   'var(--space-6)',
  lg:   'var(--space-8)',
};

const variantStyle = {
  default: {
    background: 'linear-gradient(180deg, rgba(22, 22, 31, 0.7), rgba(17, 17, 24, 0.6))',
    border: '1px solid var(--border-default)',
    boxShadow: 'var(--shadow-md), var(--shadow-inset)',
  },
  raised: {
    background: 'linear-gradient(180deg, rgba(29, 29, 39, 0.85), rgba(22, 22, 31, 0.75))',
    border: '1px solid var(--border-strong)',
    boxShadow: 'var(--shadow-lg), var(--shadow-inset)',
  },
  glow: {
    background: 'linear-gradient(180deg, rgba(29, 29, 39, 0.85), rgba(22, 22, 31, 0.75))',
    border: '1px solid rgba(124, 92, 255, 0.35)',
    boxShadow: 'var(--shadow-glow), var(--shadow-inset)',
  },
};

const Card = forwardRef(function Card(
  {
    variant = 'default',
    padding = 'md',
    interactive = false,
    onClick,
    children,
    style,
    className = '',
    ...rest
  },
  ref,
) {
  const isInteractive = !!onClick || interactive;
  return (
    <motion.div
      ref={ref}
      onClick={onClick}
      whileHover={
        isInteractive
          ? { y: -2, borderColor: 'var(--border-strong)', boxShadow: 'var(--shadow-lg), var(--shadow-inset)' }
          : undefined
      }
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className={className}
      style={{
        position: 'relative',
        borderRadius: 'var(--radius-lg)',
        padding: paddings[padding],
        backdropFilter: 'blur(28px) saturate(140%)',
        WebkitBackdropFilter: 'blur(28px) saturate(140%)',
        cursor: isInteractive ? 'pointer' : 'default',
        ...variantStyle[variant],
        ...style,
      }}
      {...rest}
    >
      {children}
    </motion.div>
  );
});

export function CardHeader({ children, style, separator = true, ...rest }) {
  return (
    <div
      style={{
        padding: 'var(--space-5) var(--space-6)',
        borderBottom: separator ? '1px solid var(--border-subtle)' : 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--space-3)',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, eyebrow, style }) {
  return (
    <div style={style}>
      {eyebrow && (
        <div
          style={{
            fontSize: 'var(--text-2xs)',
            fontWeight: 600,
            letterSpacing: 'var(--tracking-wide)',
            color: 'var(--text-tertiary)',
            textTransform: 'uppercase',
            marginBottom: 'var(--space-1)',
          }}
        >
          {eyebrow}
        </div>
      )}
      <h2
        style={{
          margin: 0,
          fontSize: 'var(--text-lg)',
          fontWeight: 600,
          letterSpacing: 'var(--tracking-tight)',
        }}
      >
        {children}
      </h2>
    </div>
  );
}

export function CardBody({ children, style, ...rest }) {
  return (
    <div style={{ padding: 'var(--space-6)', ...style }} {...rest}>
      {children}
    </div>
  );
}

export function CardFooter({ children, style, ...rest }) {
  return (
    <div
      style={{
        padding: 'var(--space-4) var(--space-6)',
        borderTop: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export default Card;
