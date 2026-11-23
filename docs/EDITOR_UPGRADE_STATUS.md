# Editor upgrade status

The user-provided editor upgrade spec describes a staged CapCut-scale editor. This release implements its vertical-workspace foundation without changing the existing local media pipeline.

## Working in this release

- Vertical focus places the 9:16 composition in a tall, resizable right column. Classic and Compact layouts are available; the last layout and preview width are saved in the browser.
- The source monitor, Frame/Captions inspector, and audio/caption timeline are separate surfaces. The timeline stays below the tools and stops before the right preview.
- The preview has a safe-zone overlay and full-screen control. Gameplay plus facecam remains the default composition.
- The timeline supports live IN/OUT trimming, click-to-seek, zoom, audio waveform, chat-reaction marker, user markers, and optional marker snapping.
- Undo/redo covers trim, crop/layout, caption text and caption style changes; autosave and 480p preview rendering still run in the background.
- Caption generation is opt-in, uses local Whisper large-v3 by default, and offers offline translation into supported caption languages. Source media and models stay in the selected local storage location.
- A timed text track lets you add up to 12 title cards or callouts, adjust their IN/OUT times, colors, size, and position, and drag them on the vertical preview. They are saved with undo/redo and autosave, then rendered into both the 480p preview and the final MP4.

## Still to build from the spec

- The full project JSON with independently movable video, overlay, audio and music clips; split, ripple delete, duplicate, speed and keyframes. The new text track has timed items but is not a general multitrack engine.
- A shared frame renderer for exact animated-caption parity between preview and export, plus the 20 animated templates.
- Proxy/cache worker, advanced effects, masks, stickers, music and transition tools.
- Multi-ratio project export, batch styles, version history and background render queue.

The current MP4 export uses the existing FFmpeg composition and supports a single 20–180 second source selection. The new UI does not present unfinished timeline or effect tools as working controls.
