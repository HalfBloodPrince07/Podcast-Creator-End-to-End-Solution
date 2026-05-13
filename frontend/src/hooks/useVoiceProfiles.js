import { useState, useCallback, useEffect } from 'react';

export default function useVoiceProfiles() {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/voice-clones');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setProfiles(data.voice_clones || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const createProfile = useCallback(async (name, files) => {
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('name', name);
      files.forEach((f) => formData.append('files', f));
      const res = await fetch('/api/voice-clone/chatterbox', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to create voice clone');
      await fetchProfiles();
      return data;
    } catch (e) {
      setError(e.message);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [fetchProfiles]);

  const deleteProfile = useCallback(async (voiceId) => {
    setError(null);
    try {
      const res = await fetch(`/api/voice-clone/${voiceId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete');
      setProfiles((prev) => prev.filter((p) => p.voice_id !== voiceId));
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const addClips = useCallback(async (voiceId, files) => {
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      files.forEach((f) => formData.append('files', f));
      const res = await fetch(`/api/voice-clone/${voiceId}/add-clips`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to add clips');
      await fetchProfiles();
      return data;
    } catch (e) {
      setError(e.message);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [fetchProfiles]);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  return { profiles, loading, error, fetchProfiles, createProfile, deleteProfile, addClips };
}
