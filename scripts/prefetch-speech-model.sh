#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env.docker ]] && command -v docker >/dev/null 2>&1; then
  docker compose --env-file .env.docker exec -T api python3 -c 'from faster_whisper.utils import download_model; download_model("large-v3",cache_dir="/data/models")'
elif [[ -x .venv/bin/python ]]; then
  .venv/bin/python -c 'from faster_whisper.utils import download_model; download_model("large-v3",cache_dir="data/models")'
else
  echo 'Install ClipHunter first, then run this script.' >&2
  exit 1
fi
echo 'Whisper large-v3 is cached in your chosen data folder.'
