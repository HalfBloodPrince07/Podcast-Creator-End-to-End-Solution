import ReactMarkdown from 'react-markdown';
import { motion, AnimatePresence } from 'framer-motion';
import AudioPlayer from './AudioPlayer';
import ScriptViewer from './ScriptViewer';
import SourcesList from './SourcesList';

export default function ResultsPanel({ results, script, sources }) {
  const hasContent = results || script.length > 0 || sources.length > 0;
  if (!hasContent) return null;

  return (
    <motion.div
      className="glass-panel"
      style={{ padding: 0, overflow: 'hidden' }}
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
    >
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)' }}>
        <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 600 }}>Results</h2>
      </div>

      <div style={{ padding: '1.5rem' }}>
        <AnimatePresence>
          {results && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
            >
              <AudioPlayer results={results} />
            </motion.div>
          )}

          {results?.show_notes && (
            <motion.div
              style={{ marginBottom: '2rem' }}
              className="markdown-content"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
            >
              <h3 style={{ color: 'var(--accent)' }}>Show Notes</h3>
              <div style={{ background: 'rgba(0,0,0,0.3)', padding: '1.5rem', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)', boxShadow: 'inset 0 2px 10px rgba(0,0,0,0.2)' }}>
                <ReactMarkdown>{results.show_notes}</ReactMarkdown>
              </div>
            </motion.div>
          )}

          {script && script.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <ScriptViewer script={script} />
            </motion.div>
          )}

          {sources && sources.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
            >
              <SourcesList sources={sources} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
