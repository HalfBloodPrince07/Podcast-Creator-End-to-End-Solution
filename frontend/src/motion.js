/**
 * Motion presets — single source of truth for framer-motion transitions.
 * Mirrors the CSS --ease-* and --dur-* tokens in index.css.
 */

// ── Springs ────────────────────────────────────────────────────────────────
export const spring = {
  snap:   { type: 'spring', stiffness: 380, damping: 30, mass: 0.7 },
  smooth: { type: 'spring', stiffness: 220, damping: 28 },
  gentle: { type: 'spring', stiffness: 140, damping: 22 },
  bouncy: { type: 'spring', stiffness: 280, damping: 16 },
  layout: { type: 'spring', stiffness: 320, damping: 32, mass: 0.8 },
};

// ── Easings (matching CSS cubic-beziers) ──────────────────────────────────
export const ease = {
  snap:   [0.2, 0.8, 0.2, 1],
  glide:  [0.16, 1, 0.3, 1],
  spring: [0.34, 1.56, 0.64, 1],
  out:    [0.25, 0.46, 0.45, 0.94],
};

// ── Durations (ms → seconds for framer) ───────────────────────────────────
export const duration = {
  instant: 0.08,
  fast:    0.14,
  base:    0.22,
  slow:    0.42,
  slower:  0.7,
};

// ── Common transitions ────────────────────────────────────────────────────
export const transition = {
  fast:  { duration: duration.fast, ease: ease.snap },
  base:  { duration: duration.base, ease: ease.glide },
  slow:  { duration: duration.slow, ease: ease.glide },
};

// ── Variants for repeated patterns ────────────────────────────────────────
export const fadeIn = {
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: transition.base },
};

export const fadeUp = {
  hidden:  { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: spring.smooth },
};

export const fadeUpSm = {
  hidden:  { opacity: 0, y: 6 },
  visible: { opacity: 1, y: 0, transition: transition.base },
};

export const scaleIn = {
  hidden:  { opacity: 0, scale: 0.96 },
  visible: { opacity: 1, scale: 1, transition: spring.smooth },
  exit:    { opacity: 0, scale: 0.96, transition: transition.fast },
};

// ── Stagger orchestration ─────────────────────────────────────────────────
export const stagger = (childDelay = 0.06, parentDelay = 0) => ({
  hidden:  { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: childDelay, delayChildren: parentDelay },
  },
});

// ── Reduced motion check ──────────────────────────────────────────────────
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
