import { useState, useRef, cloneElement } from 'react';
import { AnimatePresence, motion } from 'framer-motion';

/**
 * Tooltip — lightweight, framer-driven (no Radix dependency).
 * Wraps a single child and shows a floating label on hover / focus.
 *
 * Usage:
 *   <Tooltip label="Download MP3"><IconButton><Download/></IconButton></Tooltip>
 */

const SHOW_DELAY = 220;

export default function Tooltip({ label, side = 'top', children }) {
  const [open, setOpen] = useState(false);
  const timerRef = useRef(null);

  const show = () => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setOpen(true), SHOW_DELAY);
  };
  const hide = () => {
    clearTimeout(timerRef.current);
    setOpen(false);
  };

  const positionStyles = {
    top:    { bottom: 'calc(100% + 8px)', left: '50%', transform: 'translateX(-50%)' },
    bottom: { top: 'calc(100% + 8px)',    left: '50%', transform: 'translateX(-50%)' },
    left:   { right: 'calc(100% + 8px)',  top: '50%',  transform: 'translateY(-50%)' },
    right:  { left: 'calc(100% + 8px)',   top: '50%',  transform: 'translateY(-50%)' },
  };

  const enterY = side === 'top' ? 4 : side === 'bottom' ? -4 : 0;
  const enterX = side === 'left' ? 4 : side === 'right' ? -4 : 0;

  // Inject handlers onto the child without a wrapping element where possible.
  const child = cloneElement(children, {
    onMouseEnter: (e) => { show(); children.props.onMouseEnter?.(e); },
    onMouseLeave: (e) => { hide(); children.props.onMouseLeave?.(e); },
    onFocus:      (e) => { show(); children.props.onFocus?.(e); },
    onBlur:       (e) => { hide(); children.props.onBlur?.(e); },
  });

  return (
    <span style={{ position: 'relative', display: 'inline-flex' }}>
      {child}
      <AnimatePresence>
        {open && label && (
          <motion.span
            role="tooltip"
            initial={{ opacity: 0, y: enterY, x: enterX, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, x: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.96 }}
            transition={{ duration: 0.14, ease: [0.2, 0.8, 0.2, 1] }}
            style={{
              position: 'absolute',
              zIndex: 1000,
              pointerEvents: 'none',
              padding: '5px 9px',
              fontSize: 'var(--text-2xs)',
              fontWeight: 500,
              color: 'var(--text-primary)',
              background: 'var(--surface-3)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-xs)',
              boxShadow: 'var(--shadow-md)',
              whiteSpace: 'nowrap',
              letterSpacing: '0.01em',
              ...positionStyles[side],
            }}
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
