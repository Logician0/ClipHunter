$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install and start Docker Desktop first.' }
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is required.' }
if (Test-Path .env.docker) {
  docker compose --env-file .env.docker up -d
  if ($LASTEXITCODE -ne 0) { throw 'Could not start the existing ClipHunter installation.' }
  docker compose --env-file .env.docker exec -T api python3 -c 'from faster_whisper import WhisperModel; WhisperModel("large-v3",device="cpu",compute_type="int8",download_root="/data/models")'
  if ($LASTEXITCODE -ne 0) { throw 'Speech model setup failed. Check your connection and rerun the setup script.' }
  Write-Host 'ClipHunter is ready at http://localhost:3000'
  exit 0
}
$chosen = Read-Host 'Folder for ClipHunter videos and models (for example D:\ClipHunter)'
if ([string]::IsNullOrWhiteSpace($chosen)) { throw 'Choose a folder.' }
if ($chosen.Contains("'")) { throw 'Choose a folder path without apostrophes.' }
New-Item -ItemType Directory -Force -Path $chosen | Out-Null
$library = (Resolve-Path $chosen).Path.Replace('\', '/')
@('config','home','models','chunks','logs','live') | ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $chosen $_) | Out-Null }
$lines = @(
  "CLIPHUNTER_DATA_PATH='$library'"
  'HOST_UID=1000'
  'HOST_GID=1000'
)
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) '.env.docker'), $lines, $utf8)
docker compose --env-file .env.docker up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker setup failed. Read the error above and retry.' }
Write-Host 'Downloading the speech model once into your chosen folder. This may take several minutes.'
docker compose --env-file .env.docker exec -T api python3 -c 'from faster_whisper import WhisperModel; WhisperModel("large-v3",device="cpu",compute_type="int8",download_root="/data/models")'
if ($LASTEXITCODE -ne 0) { throw 'Speech model setup failed. Check your connection and rerun the setup script.' }
Write-Host 'ClipHunter is starting at http://localhost:3000'
Write-Host 'Open ClipHunter and create your own password on the first screen.'
Write-Host "Your videos, models, and settings are under: $library"
