import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'podcast-pipeline-settings';

const DEFAULTS = {
  llmUrl: 'http://localhost:1234/v1',
  llmKey: 'lm-studio',
  llmModel: 'local-model',
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore corrupt data */ }
  return DEFAULTS;
}

export default function useSettings() {
  const [llmUrl, setLlmUrl] = useState(() => loadSettings().llmUrl);
  const [llmKey, setLlmKey] = useState(() => loadSettings().llmKey);
  const [llmModel, setLlmModel] = useState(() => loadSettings().llmModel);
  const [availableModels, setAvailableModels] = useState(['local-model']);

  // Persist whenever settings change
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ llmUrl, llmKey, llmModel }));
  }, [llmUrl, llmKey, llmModel]);

  const refreshModels = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/settings/models?llm_url=${encodeURIComponent(llmUrl)}&llm_key=${encodeURIComponent(llmKey)}`
      );
      const data = await res.json();
      if (data.models?.length > 0) {
        setAvailableModels(data.models);
        if (!data.models.includes(llmModel)) {
          setLlmModel(data.models[0]);
        }
      }
      if (data.error) {
        console.warn('Could not fetch models:', data.error);
        alert(`Warning: Could not fetch models (${data.error}). Make sure LM Studio is running.`);
      }
    } catch (e) {
      console.error('Error fetching models', e);
      alert('Error fetching models from backend.');
    }
  }, [llmUrl, llmKey, llmModel]);

  return {
    llmUrl, setLlmUrl,
    llmKey, setLlmKey,
    llmModel, setLlmModel,
    availableModels,
    refreshModels,
  };
}
