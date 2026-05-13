import { useId } from 'react';

/**
 * Slider — labeled range input with current value chip and optional tick presets.
 *
 * Props:
 *  - value, onChange, min, max, step
 *  - label, hint, unit, formatValue (fn)
 *  - presets: number[]  → renders quick-pick chips below the track
 */

export default function Slider({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  label,
  hint,
  unit = '',
  formatValue,
  presets,
  style,
  id,
  ...rest
}) {
  const autoId = useId();
  const inputId = id || autoId;
  const display = formatValue ? formatValue(value) : `${value}${unit}`;
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', ...style }}>
      {label && (
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-2)',
          }}
        >
          <label
            htmlFor={inputId}
            style={{
              fontSize: 'var(--text-xs)',
              fontWeight: 500,
              color: 'var(--text-secondary)',
              letterSpacing: '0.01em',
            }}
          >
            {label}
          </label>
          <span
            style={{
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              fontVariantNumeric: 'tabular-nums',
              color: 'var(--brand-300)',
              padding: '2px 8px',
              borderRadius: 'var(--radius-pill)',
              background: 'rgba(124, 92, 255, 0.12)',
              border: '1px solid rgba(124, 92, 255, 0.25)',
            }}
          >
            {display}
          </span>
        </div>
      )}

      <div style={{ position: 'relative', padding: '4px 0' }}>
        {/* Filled track overlay */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            left: 0,
            top: '50%',
            transform: 'translateY(-50%)',
            height: 6,
            width: `${pct}%`,
            background: 'var(--brand-gradient)',
            borderRadius: 'var(--radius-pill)',
            pointerEvents: 'none',
            boxShadow: '0 0 12px var(--brand-glow)',
            transition: 'width 0.14s var(--ease-snap)',
          }}
        />
        <input
          id={inputId}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{ position: 'relative', zIndex: 1, background: 'var(--surface-2)' }}
          {...rest}
        />
      </div>

      {presets && presets.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-1)', marginTop: 'var(--space-3)' }}>
          {presets.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onChange(p)}
              style={{
                padding: '4px 10px',
                fontSize: 'var(--text-2xs)',
                fontWeight: 600,
                fontVariantNumeric: 'tabular-nums',
                borderRadius: 'var(--radius-pill)',
                border: `1px solid ${value === p ? 'rgba(124,92,255,0.45)' : 'var(--border-subtle)'}`,
                background: value === p ? 'rgba(124, 92, 255, 0.18)' : 'transparent',
                color: value === p ? 'var(--brand-300)' : 'var(--text-tertiary)',
                cursor: 'pointer',
                transition: 'all 0.14s var(--ease-snap)',
              }}
            >
              {p}{unit}
            </button>
          ))}
        </div>
      )}

      {hint && (
        <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-2xs)', color: 'var(--text-tertiary)' }}>
          {hint}
        </div>
      )}
    </div>
  );
}
