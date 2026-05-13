import { motion } from 'framer-motion';

/**
 * EmptyState — icon + headline + caption + optional CTA.
 */
export default function EmptyState({
  icon,
  title,
  description,
  action,
  style,
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: 'var(--space-10) var(--space-6)',
        gap: 'var(--space-3)',
        ...style,
      }}
    >
      {icon && (
        <div
          style={{
            display: 'inline-flex',
            width: 56,
            height: 56,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(124, 92, 255, 0.08)',
            border: '1px solid rgba(124, 92, 255, 0.18)',
            color: 'var(--brand-300)',
            marginBottom: 'var(--space-2)',
          }}
        >
          {icon}
        </div>
      )}
      {title && (
        <h3
          style={{
            margin: 0,
            fontSize: 'var(--text-md)',
            fontWeight: 600,
            color: 'var(--text-primary)',
          }}
        >
          {title}
        </h3>
      )}
      {description && (
        <p
          style={{
            margin: 0,
            fontSize: 'var(--text-sm)',
            color: 'var(--text-tertiary)',
            maxWidth: '38ch',
            lineHeight: 'var(--leading-relaxed)',
          }}
        >
          {description}
        </p>
      )}
      {action && <div style={{ marginTop: 'var(--space-3)' }}>{action}</div>}
    </motion.div>
  );
}
