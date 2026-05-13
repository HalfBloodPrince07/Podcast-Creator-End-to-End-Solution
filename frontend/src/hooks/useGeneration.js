import { useState, useRef, useCallback } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';

export default function useGeneration() {
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [currentStage, setCurrentStage] = useState('Idle');
  const [results, setResults] = useState(null);
  const [sources, setSources] = useState([]);
  const [script, setScript] = useState([]);
  const [lastError, setLastError] = useState(null);
  // Pause-for-review state
  const [pausedForReview, setPausedForReview] = useState(null); // null | { run_id, segments }
  const [notices, setNotices] = useState([]);

  const controllerRef = useRef(null);
  const lastPayloadRef = useRef(null);
  // Guard flag: prevent fetchEventSource re-POST on reconnect
  const isRunningRef = useRef(false);

  const generate = useCallback(async (payload) => {
    // Hard guard: if already running, ignore the call entirely
    if (isRunningRef.current) return;
    isRunningRef.current = true;

    setIsGenerating(true);
    setProgress(0);
    setLogs([]);
    setCurrentStage('Starting...');
    setResults(null);
    setSources([]);
    setScript([]);
    setLastError(null);
    setPausedForReview(null);
    setNotices([]);

    lastPayloadRef.current = payload;
    controllerRef.current = new AbortController();

    try {
      await fetchEventSource('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controllerRef.current.signal,
        // CRITICAL: prevent the library from re-POSTing when the tab loses focus
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const data = JSON.parse(ev.data);
            if (data.error) {
              setLogs(prev => [...prev, `[ERROR] ${data.error}`]);
              setLastError(data.error);
              setIsGenerating(false);
              isRunningRef.current = false;
              return;
            }
            if (data.notice) {
              setNotices(prev => [...prev, { message: data.notice, severity: data.severity || 'info', node: data.node }]);
              setLogs(prev => [...prev, `[${data.severity || 'info'}] ${data.notice}`]);
              return;
            }
            if (data.stage) setCurrentStage(data.stage);
            if (data.pct !== undefined) setProgress(data.pct);
            if (data.msg) setLogs(prev => [...prev, `[${data.stage}] ${data.msg}`]);
            if (data.sources) setSources(data.sources);
            if (data.script && data.script.length > 0) setScript(data.script);

            // Pause-for-review: pipeline halted after audio_design; show editor
            if (data.paused) {
              setPausedForReview({
                run_id: data.run_id,
                segments: data.script_segments || data.script || [],
                narrative_arc: data.narrative_arc || '',
              });
              setIsGenerating(false);
              isRunningRef.current = false;
              return;
            }

            if (data.done) {
              setIsGenerating(false);
              isRunningRef.current = false;
              if (data.results) setResults(data.results);
            }
          } catch (e) {
            console.error('Parse error:', e);
          }
        },
        onerror(err) {
          console.error('SSE Error:', err);
          setLogs(prev => [...prev, '[SSE Error] Connection closed or failed.']);
          setLastError('Connection closed or failed.');
          setIsGenerating(false);
          isRunningRef.current = false;
          throw err; // re-throw tells fetchEventSource NOT to retry
        },
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        setIsGenerating(false);
        isRunningRef.current = false;
        setLogs(prev => [...prev, `[Network Error] ${err.message}`]);
        setLastError(err.message);
      }
    } finally {
      isRunningRef.current = false;
    }
  }, []);

  const stop = useCallback(() => {
    if (controllerRef.current) {
      controllerRef.current.abort();
      setIsGenerating(false);
      isRunningRef.current = false;
      setLogs(prev => [...prev, '[SYSTEM] Generation aborted by user.']);
    }
  }, []);

  const retry = useCallback(() => {
    if (lastPayloadRef.current) {
      generate(lastPayloadRef.current);
    }
  }, [generate]);

  const resume = useCallback(async (editedSegments) => {
    if (!pausedForReview) return;
    if (isRunningRef.current) return;
    isRunningRef.current = true;
    setIsGenerating(true);
    setCurrentStage('Resuming...');
    setLastError(null);
    controllerRef.current = new AbortController();

    try {
      await fetchEventSource('/api/resume-generation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: pausedForReview.run_id, segments: editedSegments }),
        signal: controllerRef.current.signal,
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const data = JSON.parse(ev.data);
            if (data.error) {
              setLastError(data.error);
              setIsGenerating(false);
              isRunningRef.current = false;
              return;
            }
            if (data.stage) setCurrentStage(data.stage);
            if (data.pct !== undefined) setProgress(data.pct);
            if (data.msg) setLogs(prev => [...prev, `[${data.stage}] ${data.msg}`]);
            if (data.done) {
              setIsGenerating(false);
              isRunningRef.current = false;
              setPausedForReview(null);
              if (data.audio_url) {
                setResults({
                  audio_url: data.audio_url,
                  srt_url: data.srt_url,
                  notes_url: data.notes_url,
                  metadata: { episode_title: pausedForReview.run_id },
                });
              }
            }
          } catch { /* ignore */ }
        },
        onerror(err) {
          setLastError('Resume connection error');
          setIsGenerating(false);
          isRunningRef.current = false;
          throw err;
        },
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        setLastError(err.message);
        setIsGenerating(false);
        isRunningRef.current = false;
      }
    } finally {
      isRunningRef.current = false;
    }
  }, [pausedForReview]);

  return {
    isGenerating, progress, logs, currentStage,
    results, sources, script, lastError,
    pausedForReview, notices,
    generate, stop, retry, resume,
  };
}
