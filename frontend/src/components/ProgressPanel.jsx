import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2 } from 'lucide-react';

import ActiveAgentAvatar from './ActiveAgentAvatar';

export default function ProgressPanel({ isGenerating, currentStage, progress, logs, lastError, onRetry }) {
  const logEndRef = useRef(null);
  const containerRef = useRef(null);

  // Auto scroll logic
  useEffect(() => {
    if (logEndRef.current && containerRef.current) {
      const container = containerRef.current;
      // Scroll if we're near the bottom to avoid interrupting user scrolling up
      const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
      if (isNearBottom || logs.length < 5) {
        logEndRef.current.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }, [logs]);

  return (
    <motion.div className="glass-panel" layout>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <h2 style={{ fontSize: '1.4rem', margin: 0, fontWeight: 600 }}>Pipeline Progress</h2>
            {isGenerating && (
              <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 2, ease: "linear" }}>
                <Loader2 size={20} color="var(--primary-light)" />
              </motion.div>
            )}
          </div>

          <motion.span
            className="status-badge"
            style={{ alignSelf: 'flex-start' }}
            animate={{
              backgroundColor: isGenerating ? 'rgba(124, 58, 237, 0.25)' : 'rgba(255, 255, 255, 0.05)',
              borderColor: isGenerating ? 'rgba(124, 58, 237, 0.5)' : 'rgba(255, 255, 255, 0.1)',
              color: isGenerating ? '#fff' : 'var(--text-muted)'
            }}
            transition={{ duration: 0.3 }}
          >
            {currentStage || "Idle"} <span style={{ opacity: 0.7, marginLeft: '6px' }}>{progress}%</span>
          </motion.span>
        </div>

        {/* LED Screen Avatar container */}
        <div style={{ paddingLeft: '1rem' }}>
          <ActiveAgentAvatar currentStage={currentStage} />
        </div>
      </div>

      <div className="progress-bar-container">
        <motion.div
          className="progress-bar"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ type: "spring", stiffness: 60, damping: 15 }}
        />
      </div>

      <div className="log-container" ref={containerRef}>
        {logs.length === 0 ? (
          <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Awaiting pipeline activation...</span>
        ) : (
          <AnimatePresence initial={false}>
            {logs.map((log, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -10, filter: 'blur(5px)' }}
                animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
                transition={{ duration: 0.3 }}
                style={{
                  marginBottom: '0.4rem',
                  padding: '0.2rem 0',
                  borderBottom: '1px solid rgba(255,255,255,0.02)'
                }}
              >
                {log}
              </motion.div>
            ))}
          </AnimatePresence>
        )}
        <div ref={logEndRef} style={{ height: '1px' }} />
      </div>

      <AnimatePresence>
        {lastError && !isGenerating && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            style={{ marginTop: '1.25rem', padding: '1rem', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
          >
            <span style={{ color: '#FCA5A5', fontSize: '0.9rem', fontWeight: 500 }}>System Error: Generation halted</span>
            <button className="btn btn-secondary" style={{ fontSize: '0.85rem', padding: '0.4rem 1.2rem', borderColor: '#FCA5A5', color: '#FCA5A5' }} onClick={onRetry}>
              Retry Payload
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
