# Audio Assets

Place royalty-free audio files here to enable automatic audio mixing.

The `AudioMixerAgent` maps `[CUE: ...]` markers in the script to these files:

| CUE Marker | Expected File | Usage |
|---|---|---|
| `[CUE: INTRO_MUSIC]` | `intro_music.mp3` | Played at episode start |
| `[CUE: OUTRO_MUSIC]` | `outro_music.mp3` | Played at episode end |
| `[CUE: CHAPTER_TRANSITION]` | `transition.mp3` | Between chapters |
| `[CUE: SFX_WHOOSH]` | `whoosh.mp3` | Hook section transition |
| `[CUE: CTA_JINGLE]` | `cta_jingle.mp3` | Call-to-action break |

Assets are overlaid at -10 dB so they mix under the speech. Keep files short (2-5 seconds for effects, up to 15 seconds for music beds).

Missing files are silently skipped — the pipeline works fine without any assets.
