export default function AudioPlayer({ results }) {
  if (!results?.audio_url) return null;

  return (
    <div style={{ marginBottom: '2rem' }}>
      <h3 style={{ color: 'var(--accent)' }}>Generated Audio</h3>
      <audio src={results.audio_url} controls autoPlay />
      <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <a href={results.audio_url} target="_blank" rel="noreferrer" download className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>MP3</a>
        <a href={results.srt_url} target="_blank" rel="noreferrer" download className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>SRT</a>
        <a href={results.txt_url} target="_blank" rel="noreferrer" download className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>TXT</a>
        <a href={results.notes_url} target="_blank" rel="noreferrer" download className="btn btn-secondary" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>Notes</a>
      </div>
    </div>
  );
}
