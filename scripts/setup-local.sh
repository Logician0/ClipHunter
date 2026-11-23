#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Install and start Docker Desktop (or Docker Engine) first.' >&2; exit 1; }
docker compose version >/dev/null || { echo 'Docker Compose is required.' >&2; exit 1; }
if [[ -f .env.docker ]]; then
  echo 'An existing .env.docker was found. To keep the same library, run: docker compose --env-file .env.docker up --build -d'
  exit 0
fi
read -r -p 'Folder for ClipHunter videos and models (for example /Volumes/Samsung 512/ClipHunter): ' chosen
[[ -n "$chosen" ]] || { echo 'Choose a folder.' >&2; exit 1; }
[[ "$chosen" != *"'"* && "$chosen" != *$'\n'* ]] || { echo 'Choose a folder path without apostrophes or newlines.' >&2; exit 1; }
mkdir -p "$chosen"
library=$(cd "$chosen" && pwd -P)
mkdir -p "$library/config" "$library/home" "$library/models" "$library/chunks" "$library/logs" "$library/live"
umask 077
{
  printf "CLIPHUNTER_DATA_PATH='%s'\n" "$library"
  printf 'HOST_UID=%s\nHOST_GID=%s\n' "$(id -u)" "$(id -g)"
} > .env.docker
docker compose --env-file .env.docker up --build -d
echo 'ClipHunter is starting at http://localhost:3000'
echo 'Open ClipHunter and create your own password on the first screen.'
echo "Your videos, models, and settings are under: $library"
