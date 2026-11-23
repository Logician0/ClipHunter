# Repository research for the ClipHunter rebuild

The [referenced X post](https://x.com/e1genqq/status/2124260825934516271) lists 18 public repositories and describes what each could contribute. It does not link a single finished app or implementation. These are independent projects with different licenses and maturity. ClipHunter uses the ideas and documented interfaces that fit its local worker architecture; it does not bundle upstream source code from this list.

| Repository | Role in the post | ClipHunter decision |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Fetch stream media and chat | Already used for metadata, chat replay, and sparse clip window downloads. Keep it as the media entry point. |
| [OpenCut](https://github.com/OpenCut-app/OpenCut) | Web editor | Current main branch says it is being rewritten. Study its interaction patterns; do not replace ClipHunter's working editor with its incomplete rewrite. |
| [OpenCV](https://github.com/opencv/opencv) | Video analysis | Already used in the worker for frame and layout analysis. |
| [OBS Studio](https://github.com/obsproject/obs-studio) | Recording and source composition | OBS style source selection informs the layout editor. ClipHunter does not embed OBS. |
| [Clipper](https://github.com/guleriaakshit/clipper) | Chat based clip discovery | Studied its local baseline, participation, and reaction evidence. ClipHunter now scores chat surges against nearby activity, shows a heatmap, and retains its own sparse download pipeline. |
| [Hypeline](https://github.com/Angel-Casas/Hypeline) | Chat heatmap | Studied its browser based moment discovery. ClipHunter now displays a chat activity timeline with selectable moments. |
| [AutoCut](https://github.com/mli/autocut) | Cut video using subtitles | Useful for a future optional transcript driven mode. Do not use speech alone as proof of a gaming highlight. |
| [TransNetV2](https://github.com/soCzech/TransNetV2) | Shot boundaries | Candidate for a later cut refinement stage after a clip window has been downloaded. No need to analyze an entire stream with it. |
| [Ultralytics](https://github.com/ultralytics/ultralytics) | Object detection | Direct incorporation requires a license review because the repository is AGPL licensed. Current facecam detection stays with OpenCV. |
| [ByteTrack](https://github.com/FoundationVision/ByteTrack) | Object tracking | Potential optional subject tracking after a detector is chosen. It is not a standalone facecam detector. |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Local speech recognition | Possible lightweight transcription option. ClipHunter currently uses its existing transcription pipeline and lets users generate captions on demand. |
| [Captacity](https://github.com/unconv/captacity) | Automatic captions | Reference for caption timing and styling; do not replace ClipHunter's editable caption data with a hardcoded export. |
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | Translation and dubbing | Candidate for optional multilingual output, with a separate model and compute budget. |
| [RNNoise](https://github.com/xiph/rnnoise) | Speech denoising | Candidate optional preprocessing for noisy clips. It should not be applied blindly to game audio. |
| [Pedalboard](https://github.com/spotify/pedalboard) | Audio effects | GPL licensed; do not package its library into the public MIT release without a license review. |
| [Revideo](https://github.com/midrender/revideo) | Programmatic video rendering | Potential shared preview and export engine if a future editor rewrite justifies migration. Its documented telemetry should be disabled for a private local project. |
| [VidGear](https://github.com/abhiTronix/vidgear) | Video I/O and streaming | Evaluate only where FFmpeg and yt-dlp do not already cover the need. |
| [HandBrake](https://github.com/HandBrake/HandBrake) | Final encoding | FFmpeg already provides ClipHunter's export profiles. HandBrake can remain an external tool for users who want separate compression. |

## Implemented in this pass

- Chat discovery evaluates a local baseline, reaction density, and viewer participation. It rejects steady activity and obvious repeated posting from one account.
- Suggested clip windows follow the duration of the audience surge, with a lead before chat reacts and a short tail after it. No random first segment is substituted when no reliable signal exists.
- A privacy preserving 15 second activity map uses stored aggregate counts; it does not retain chat text or viewer IDs. Each bar can set a manual clip moment.
- Recorded stream scans still index chat before downloading video. They download only suggested or manually chosen clip windows. If chat has no reliable peaks, the existing audio only fallback remains.

## Remaining work before claiming parity with a full web editor

The current editor is not a replacement for Premiere Pro, CapCut, or OpenCut. A multitrack composition model, GPU preview, object tracking, audio effects, and robust public multiuser hosting require separate implementation and verification. The current local worker and private data folder cannot be deployed as a static Vercel page. The public site must continue to direct users to their own local installation until a secure always on backend exists.
