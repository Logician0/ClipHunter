# ClipHunter AI setup handoff

Download and extract `cliphunter-source.zip`. Attach the extracted project or this file to a coding assistant with terminal access to **your** computer, then paste the prompt below. A chat assistant without local file and terminal access can explain the steps but cannot install the app for you.

---

Please set up ClipHunter on my own computer from this extracted project folder. Before changing files, read `README.md`, `docs/INSTALL_LOCAL.md`, `SECURITY.md`, `compose.yaml`, and the setup script for my operating system.

1. Ask me which local or external-drive folder should hold all ClipHunter videos, speech models, renders, settings and YouTube access data. Do not choose a folder for me.
2. Check that Docker Desktop or Docker Engine with Compose is installed and running. If missing, give me the official Docker installation link for my operating system and wait while I install it.
3. Run `bash scripts/setup-local.sh` on Mac/Linux or `.\scripts\setup-local.ps1` in Windows PowerShell. Pass my chosen folder when prompted. If the script cannot run, use the manual setup instructions in `docs/INSTALL_LOCAL.md`.
4. Verify `docker compose --env-file .env.docker ps`, check `http://localhost:3000/api/health`, and open `http://localhost:3000` for me. Let me create my own password on the first screen. Do not ask me to paste it into chat. The app stores only its password hash in the chosen data folder's `config` directory.
5. Explain how to start, stop, and update ClipHunter, and where the chosen storage folder is. If setup fails, show the relevant error and fix only the local installation.

Keep the app bound to localhost. Do not upload my media, cookies, `.env.docker`, or storage folder to GitHub, Vercel, Cloudflare, or another remote service. Do not create a public tunnel or change firewall rules. Ask before installing Docker, accepting terms, or spending money if my assistant's rules require it.

---

ClipHunter uses my machine's CPU and storage. The public website only hosts downloads and documentation; it does not process my videos.
