# Install ClipHunter on your computer

ClipHunter's public website is a download and setup guide. The actual editor opens at **http://localhost:3000** on your computer. Video downloads, speech models, cookies, clips and the library stay in the folder you choose. Keep that folder private and keep enough free space for the streams you process (at least 10 GB before a new scan).

## 1. Install Docker

Install and start [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/) or [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/). On Linux, install [Docker Engine and the Compose plugin](https://docs.docker.com/engine/install/). Windows users should use Docker's Linux containers with WSL 2. Docker may ask you to share access to an external drive; allow only the folder you choose for ClipHunter.

## 2. Download and unpack

Download **cliphunter-source.zip** from the ClipHunter website and extract it. Open Terminal or PowerShell inside the extracted `ClipHunter` folder. This bundle contains source code and setup files; it does not include anyone's videos, login cookies or password.

## 3. Choose storage and start

**Mac or Linux**

```sh
bash scripts/setup-local.sh
```

**Windows PowerShell**

```powershell
.\scripts\setup-local.ps1
```

When prompted, enter the folder for videos and models, for example `/Volumes/Samsung 512/ClipHunter` or `D:\ClipHunter`. The setup writes a private `.env.docker` file, builds the two local services and starts ClipHunter. The first build and speech model download can take several minutes. The password is the `APP_PASSWORD` value in `.env.docker`; do not share this file.

If PowerShell blocks the script, use the manual commands below rather than changing system-wide script security settings.

## 4. Open the editor

Open **http://localhost:3000** and enter the workspace password from `.env.docker`. The public website's **Open local studio** button goes to the same address after installation. Paste a supported stream link to start scanning.

## Later

From the extracted folder:

```sh
docker compose --env-file .env.docker up -d
docker compose --env-file .env.docker down
docker compose --env-file .env.docker logs --tail=100
```

These commands start, stop, and inspect ClipHunter. `down` stops the services but leaves your chosen folder intact. To update after downloading a newer source bundle, keep your `.env.docker`, then run `docker compose --env-file .env.docker up --build -d`.

## Manual setup if scripts are blocked

1. Create a folder for ClipHunter data. Inside it, create `config`, `home`, `models`, `chunks`, `logs`, and `live` folders.
2. In the extracted project folder, create `.env.docker` with four lines. Replace the examples with your absolute folder path, your user/group ID on Mac/Linux (`id -u` and `id -g`; use `1000` for both on Windows), and a unique random password:

```text
CLIPHUNTER_DATA_PATH='/absolute/path/to/ClipHunter'
HOST_UID=1000
HOST_GID=1000
APP_PASSWORD=replace-with-a-long-random-private-password
```

3. Run `docker compose --env-file .env.docker up --build -d`, then open **http://localhost:3000**. On Windows, use forward slashes in the drive path, such as `D:/ClipHunter`.

The API is available only inside Docker's private network; the web app listens only on your computer's loopback address. Do not publish port 3000, share `.env.docker`, or import browser cookies from sites other than YouTube.
