import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import useSettings from './hooks/useSettings';
import useGeneration from './hooks/useGeneration';
import EpisodeConfigForm from './components/EpisodeConfigForm';
import ProgressPanel from './components/ProgressPanel';
import ResultsPanel from './components/ResultsPanel';
import EpisodeLibrary from './components/EpisodeLibrary';
import VoiceProfiles from './components/VoiceProfiles';
import BackgroundScene from './components/BackgroundScene';
import ScriptEditor from './components/ScriptEditor';
import TopBar from './components/TopBar';
import SettingsDrawer from './components/SettingsDrawer';
import './index.css';

const tabVariants = {
  hidden:  { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.26, ease: [0.16, 1, 0.3, 1] } },
  exit:    { opacity: 0, y: -8, transition: { duration: 0.16 } },
};

const panelStagger = {
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const panelEnter = {
  hidden:  { opacity: 0, y: 14, scale: 0.985 },
  visible: { opacity: 1, y: 0,  scale: 1, transition: { type: 'spring', stiffness: 280, damping: 32 } },
};

function App() {
  const settings = useSettings();
  const gen = useGeneration();
  const [activeTab, setActiveTab] = useState('generate');
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Sticky across this page lifetime — controls whether the video step
  // auto-fires after audio finishes. Reset on each new generation start.
  const [autoVideo, setAutoVideo] = useState(false);

  const handleGenerate = (formData) => {
    setAutoVideo(!!formData.auto_video);
    gen.generate({
      ...formData,
      llm_url: settings.llmUrl,
      llm_key: settings.llmKey,
      llm_model: settings.llmModel,
    });
  };

  // Only render the 3D scene on the Generate tab to avoid useless GPU work elsewhere.
  const sceneActive = activeTab === 'generate';

  return (
    <>
      <BackgroundScene isGenerating={gen.isGenerating} active={sceneActive} />

      <div id="root">
        <TopBar
          activeTab={activeTab}
          onTabChange={setActiveTab}
          isGenerating={gen.isGenerating}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <main className="app-shell">
          <AnimatePresence mode="wait">
            {activeTab === 'generate' && (
              <motion.div
                key="generate"
                variants={tabVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
              >
                <motion.div
                  className="bento-grid"
                  variants={panelStagger}
                  initial="hidden"
                  animate="visible"
                >
                  {/* Left column — Configuration */}
                  <motion.div variants={panelEnter} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
                    <EpisodeConfigForm
                      isGenerating={gen.isGenerating}
                      onGenerate={handleGenerate}
                      onStop={gen.stop}
                    />
                  </motion.div>

                  {/* Right column — Progress + Script editor + Results */}
                  <motion.div
                    variants={panelEnter}
                    style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}
                  >
                    <AnimatePresence mode="popLayout">
                      <motion.div key="progress-panel" layout>
                        <ProgressPanel
                          isGenerating={gen.isGenerating}
                          currentStage={gen.currentStage}
                          progress={gen.progress}
                          logs={gen.logs}
                          lastError={gen.lastError}
                          onRetry={gen.retry}
                        />
                      </motion.div>

                      {gen.pausedForReview && (
                        <motion.div
                          key="script-editor"
                          layout
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ type: 'spring', stiffness: 220, damping: 28 }}
                        >
                          <ScriptEditor
                            pausedState={gen.pausedForReview}
                            onResume={gen.resume}
                            onCancel={gen.stop}
                          />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                </motion.div>

                {/* Results — full-width row beneath bento */}
                <AnimatePresence>
                  {(gen.results || gen.script?.length > 0 || gen.sources?.length > 0) && (
                    <motion.div
                      key="results-row"
                      layout
                      initial={{ opacity: 0, y: 16 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ type: 'spring', stiffness: 220, damping: 30 }}
                      style={{ marginTop: 'var(--space-6)' }}
                    >
                      <ResultsPanel
                        results={gen.results}
                        script={gen.script}
                        sources={gen.sources}
                        autoVideo={autoVideo}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )}

            {activeTab === 'voices' && (
              <motion.div key="voices" variants={tabVariants} initial="hidden" animate="visible" exit="exit">
                <VoiceProfiles />
              </motion.div>
            )}

            {activeTab === 'library' && (
              <motion.div key="library" variants={tabVariants} initial="hidden" animate="visible" exit="exit">
                <EpisodeLibrary />
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        <SettingsDrawer
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          {...settings}
        />
      </div>
    </>
  );
}

export default App;
