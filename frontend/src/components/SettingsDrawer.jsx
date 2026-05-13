import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Settings, RefreshCw } from 'lucide-react';
import { Input, Select } from './ui/Input';
import IconButton from './ui/IconButton';
import Button from './ui/Button';

/**
 * SettingsDrawer — slide-in panel from the right for LLM connection settings.
 * Wraps the original SettingsPanel fields but in a focused premium surface.
 */

const BACKDROP_BG = 'rgba(5, 5, 8, 0.6)';

export default function SettingsDrawer({
  open,
  onClose,
  llmUrl, setLlmUrl,
  llmKey, setLlmKey,
  llmModel, setLlmModel,
  availableModels = [],
  refreshModels,
}) {
  // Lock body scroll & close on Escape
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            style={{
              position: 'fixed',
              inset: 0,
              background: BACKDROP_BG,
              backdropFilter: 'blur(4px)',
              WebkitBackdropFilter: 'blur(4px)',
              zIndex: 200,
            }}
          />
          <motion.aside
            key="drawer"
            role="dialog"
            aria-label="Settings"
            initial={{ x: '100%', opacity: 0.5 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0 }}
            transition={{ type: 'spring', stiffness: 320, damping: 36 }}
            style={{
              position: 'fixed',
              top: 0,
              right: 0,
              bottom: 0,
              width: 'min(440px, 100vw)',
              zIndex: 201,
              background: 'linear-gradient(180deg, var(--surface-2) 0%, var(--surface-1) 100%)',
              borderLeft: '1px solid var(--border-default)',
              boxShadow: 'var(--shadow-xl)',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {/* Header */}
            <div
              style={{
                padding: 'var(--space-5) var(--space-6)',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    width: 32, height: 32,
                    alignItems: 'center', justifyContent: 'center',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(124, 92, 255, 0.12)',
                    color: 'var(--brand-300)',
                    border: '1px solid rgba(124, 92, 255, 0.2)',
                  }}
                >
                  <Settings size={15} />
                </span>
                <div>
                  <div
                    style={{
                      fontSize: 'var(--text-md)',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      letterSpacing: 'var(--tracking-tight)',
                    }}
                  >
                    Settings
                  </div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
                    LLM connection & model
                  </div>
                </div>
              </div>
              <IconButton onClick={onClose} variant="ghost" title="Close">
                <X size={16} />
              </IconButton>
            </div>

            {/* Body */}
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: 'var(--space-6)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-5)',
              }}
            >
              <Input
                label="LLM Base URL"
                hint="OpenAI-compatible endpoint (Ollama, LM Studio, etc.)"
                value={llmUrl}
                onChange={(e) => setLlmUrl(e.target.value)}
                placeholder="http://localhost:11434/v1"
              />

              <Input
                label="API Key"
                hint="Leave blank for local servers"
                type="password"
                value={llmKey}
                onChange={(e) => setLlmKey(e.target.value)}
                placeholder="sk-..."
                optional
              />

              <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <Select
                    label="Model"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                  >
                    {availableModels.length === 0 && <option value="">— no models —</option>}
                    {availableModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </Select>
                </div>
                <Button
                  variant="secondary"
                  size="md"
                  iconLeft={<RefreshCw size={14} />}
                  onClick={refreshModels}
                  style={{ marginBottom: 0 }}
                >
                  Refresh
                </Button>
              </div>
            </div>

            {/* Footer */}
            <div
              style={{
                padding: 'var(--space-4) var(--space-6)',
                borderTop: '1px solid var(--border-subtle)',
                display: 'flex',
                justifyContent: 'flex-end',
              }}
            >
              <Button variant="primary" size="md" onClick={onClose}>
                Done
              </Button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
