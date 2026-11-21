# ClipHunter

ClipHunter finds chat-reaction highlights in long YouTube, Twitch, and Kick streams, then lets you edit and render vertical clips on your own computer. The editor includes a zoomable trim timeline, live gameplay and facecam framing, Hindi/English speech recognition, editable caption timing and words, caption styles, and a no-caption option.

**Your media stays on your computer.** The public website is a download and installation guide. ClipHunter itself runs at `http://localhost:3000` with a private workspace password. The Docker setup asks which folder should hold videos, models, clips, settings and optional YouTube cookies.

## Quick start

1. Install and start [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/) or [Windows](https://docs.docker.com/desktop/setup/install/windows-install/), or [Docker Engine with Compose](https://docs.docker.com/engine/install/) on Linux.
2. Download and extract this repository or its source ZIP.
3. Open Terminal or PowerShell in the extracted folder and run:

   **Mac/Linux:** `bash scripts/setup-local.sh`

   **Windows PowerShell:** `.\scripts\setup-local.ps1`

4. Choose your storage folder when prompted, then open `http://localhost:3000`. The generated private `.env.docker` file contains your workspace password.

For a full walkthrough and manual fallback, read [INSTALL_LOCAL.md](docs/INSTALL_LOCAL.md). If you use a coding assistant with access to your computer, give it [INSTALL_WITH_AI.md](docs/INSTALL_WITH_AI.md) as its setup instructions.

## Using ClipHunter

Paste a supported stream link. The worker scans one hour at a time and saves each hour locally. If stream chat is available and has unusual W, laughing, fire, or other excited reaction bursts, review those suggested moments. If chat cannot be retrieved or has no clear reaction, the app suggests no automatic highlights; it does not invent highlights from ordinary speech. Edit the selected range and vertical layout, recognize speech, correct captions or turn them off, then render and download the final MP4. Read the [editor guide](docs/CLIP_EDITOR_GUIDE.md) for detailed controls.

ClipHunter uses your CPU and storage. Longer streams, larger speech models and high-quality renders take time. Browser access to a YouTube video does not always grant downloader access; see the [YouTube access guide](docs/YOUTUBE_ACCESS_GUIDE.md). Only process streams you have permission to use.

## Start and stop later

From this folder:

```sh
docker compose --env-file .env.docker up -d
docker compose --env-file .env.docker down
```

Stopping does not delete your chosen storage folder. Do not publish port 3000 or share `.env.docker` or your media folder. The public site does not provide cloud rendering, user accounts, or YouTube upload/scheduling. Read [SECURITY.md](SECURITY.md) before changing network access.

## License

MIT. See [LICENSE](LICENSE).
