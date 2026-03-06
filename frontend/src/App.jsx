import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import useSettings from './hooks/useSettings';
import useGeneration from './hooks/useGeneration';
import EpisodeConfigForm from './components/EpisodeConfigForm';
import SettingsPanel from './components/SettingsPanel';
import ProgressPanel from './components/ProgressPanel';
import ResultsPanel from './components/ResultsPanel';
import EpisodeLibrary from './components/EpisodeLibrary';
import BackgroundScene from './components/BackgroundScene';
import './index.css';

// Animation variants for panel entrances
const panelVariants = {
  hidden: { opacity: 0, y: 30, scale: 0.95 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring', stiffness: 300, damping: 30, mass: 0.8 }
  },
  exit: {
    opacity: 0,
    y: -20,
    scale: 0.95,
    transition: { duration: 0.2 }
  }
};

const staggerContainer = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.15
    }
  }
};

function App() {
  const settings = useSettings();
  const gen = useGeneration();

  const handleGenerate = (formData) => {
    gen.generate({
      ...formData,
      llm_url: settings.llmUrl,
      llm_key: settings.llmKey,
      llm_model: settings.llmModel,
    });
  };

  return (
    <>
      <BackgroundScene isGenerating={gen.isGenerating} />

      <div id="root">
        <motion.div
          className="app-header"
          initial={{ opacity: 0, y: -50 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        >
          <h1>Podcast Production Pipeline</h1>
          <p>Multi-agent AI system &middot; Research &rarr; Script &rarr; Fact-check &rarr; Audio</p>
        </motion.div>

        <motion.div
          className="grid-layout"
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
        >
          {/* Left Column */}
          <motion.div className="left-panel" variants={panelVariants}>
            <EpisodeConfigForm
              isGenerating={gen.isGenerating}
              onGenerate={handleGenerate}
              onStop={gen.stop}
            />

            <div style={{ marginTop: '2rem' }}>
              <SettingsPanel {...settings} />
            </div>
          </motion.div>

          {/* Right Column */}
          <motion.div
            className="right-panel"
            style={{ display: 'flex', flexDirection: 'column', gap: '2.5rem' }}
            variants={panelVariants}
          >
            <AnimatePresence mode="popLayout">
              <motion.div
                key="progress-panel"
                layout
                initial={{ opacity: 0, x: 50 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ type: 'spring', stiffness: 200, damping: 25 }}
              >
                <ProgressPanel
                  isGenerating={gen.isGenerating}
                  currentStage={gen.currentStage}
                  progress={gen.progress}
                  logs={gen.logs}
                  lastError={gen.lastError}
                  onRetry={gen.retry}
                />
              </motion.div>

              {(gen.results || gen.script || gen.sources.length > 0) && (
                <motion.div
                  key="results-panel"
                  layout
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ type: 'spring', stiffness: 200, damping: 25 }}
                >
                  <ResultsPanel
                    results={gen.results}
                    script={gen.script}
                    sources={gen.sources}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>

        <motion.div
          style={{ marginTop: '3.5rem' }}
          initial={{ opacity: 0, y: 40 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          <EpisodeLibrary />
        </motion.div>
      </div>
    </>
  );
}

export default App;
