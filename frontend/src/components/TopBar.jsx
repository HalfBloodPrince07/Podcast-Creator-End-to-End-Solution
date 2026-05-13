import { motion } from 'framer-motion';
import { Mic2, Settings, Activity } from 'lucide-react';
import IconButton from './ui/IconButton';
import Tooltip from './ui/Tooltip';

/**
 * TopBar — sticky 60px enterprise app bar.
 * Brand lockup · tab nav (center) · status + settings (right).
 */

const TABS = [
  { id: 'generate', label: 'Generate' },
  { id: 'voices',   label: 'Voice Profiles' },
  { id: 'library',  label: 'Library' },
];

function BrandLockup() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          borderRadius: 'var(--radius-sm)',
          background: 'var(--brand-gradient)',
          color: '#fff',
          boxShadow: '0 4px 12px var(--brand-glow), inset 0 1px 0 rgba(255,255,255,0.15)',
        }}
      >
        <Mic2 size={16} strokeWidth={2.4} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, lineHeight: 1 }}>
        <span
          style={{
            fontSize: 'var(--text-sm)',
            fontWeight: 700,
            letterSpacing: 'var(--tracking-tight)',
            color: 'var(--text-primary)',
          }}
        >
          Podcast Studio
        </span>
        <span
          data-brand-subtitle
          style={{
            fontSize: 'var(--text-2xs)',
            color: 'var(--text-tertiary)',
            fontWeight: 500,
            letterSpacing: 'var(--tracking-wide)',
            textTransform: 'uppercase',
            marginTop: 2,
          }}
        >
          Multi-agent pipeline
        </span>
      </div>
    </div>
  );
}

function TabNav({ active, onChange }) {
  return (
    <nav
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-1)',
        padding: 4,
        background: 'rgba(255, 255, 255, 0.025)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        backdropFilter: 'blur(8px)',
      }}
    >
      {TABS.map((tab) => {
        const isActive = active === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            style={{
              position: 'relative',
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: 'transparent',
              color: isActive ? 'var(--text-primary)' : 'var(--text-tertiary)',
              fontWeight: isActive ? 600 : 500,
              fontSize: 'var(--text-sm)',
              letterSpacing: '0.01em',
              cursor: 'pointer',
              transition: 'color 0.14s var(--ease-snap)',
              zIndex: 1,
            }}
          >
            {isActive && (
              <motion.div
                layoutId="topbar-tab-pill"
                style={{
                  position: 'absolute',
                  inset: 0,
                  borderRadius: 'var(--radius-sm)',
                  background:
                    'linear-gradient(180deg, rgba(124, 92, 255, 0.18), rgba(124, 92, 255, 0.08))',
                  border: '1px solid rgba(124, 92, 255, 0.3)',
                  zIndex: -1,
                }}
                transition={{ type: 'spring', stiffness: 380, damping: 32 }}
              />
            )}
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

function StatusIndicator({ isGenerating }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: '5px 10px 5px 8px',
        borderRadius: 'var(--radius-pill)',
        background: isGenerating ? 'rgba(124, 92, 255, 0.15)' : 'rgba(255, 255, 255, 0.04)',
        border: `1px solid ${isGenerating ? 'rgba(124, 92, 255, 0.35)' : 'var(--border-subtle)'}`,
        color: isGenerating ? 'var(--brand-300)' : 'var(--text-tertiary)',
        fontSize: 'var(--text-2xs)',
        fontWeight: 600,
        letterSpacing: 'var(--tracking-wide)',
        textTransform: 'uppercase',
        transition: 'all 0.22s var(--ease-snap)',
      }}
    >
      <span
        style={{
          display: 'inline-block',
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: isGenerating ? 'var(--brand-400)' : 'var(--text-tertiary)',
          boxShadow: isGenerating ? '0 0 8px var(--brand-400)' : 'none',
          animation: isGenerating ? 'pulse-dot 1.4s ease-in-out infinite' : 'none',
        }}
      />
      {isGenerating ? 'Running' : 'Idle'}
    </div>
  );
}

export default function TopBar({ activeTab, onTabChange, isGenerating, onOpenSettings }) {
  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        height: 'var(--topbar-height)',
        background: 'rgba(10, 10, 15, 0.72)',
        backdropFilter: 'blur(20px) saturate(140%)',
        WebkitBackdropFilter: 'blur(20px) saturate(140%)',
        borderBottom: '1px solid var(--border-subtle)',
      }}
    >
      <div
        style={{
          maxWidth: 'var(--container-max)',
          height: '100%',
          margin: '0 auto',
          padding: '0 var(--space-6)',
          display: 'grid',
          gridTemplateColumns: '1fr auto 1fr',
          alignItems: 'center',
          gap: 'var(--space-4)',
        }}
      >
        <div style={{ justifySelf: 'start' }}>
          <BrandLockup />
        </div>

        <div style={{ justifySelf: 'center' }}>
          <TabNav active={activeTab} onChange={onTabChange} />
        </div>

        <div
          style={{
            justifySelf: 'end',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
          }}
        >
          <StatusIndicator isGenerating={isGenerating} />
          <Tooltip label="Settings">
            <IconButton variant="ghost" onClick={onOpenSettings} title="Settings">
              <Settings size={16} />
            </IconButton>
          </Tooltip>
        </div>
      </div>
    </header>
  );
}
