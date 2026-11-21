$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install and start Docker Desktop first.' }
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is required.' }
if (Test-Path .env.docker) {
  Write-Host 'An existing .env.docker was found. To keep the same library, run: docker compose --env-file .env.docker up --build -d'
  exit 0
}
$chosen = Read-Host 'Folder for ClipHunter videos and models (for example D:\ClipHunter)'
if ([string]::IsNullOrWhiteSpace($chosen)) { throw 'Choose a folder.' }
if ($chosen.Contains("'")) { throw 'Choose a folder path without apostrophes.' }
New-Item -ItemType Directory -Force -Path $chosen | Out-Null
$library = (Resolve-Path $chosen).Path.Replace('\', '/')
@('config','home','models','chunks','logs','live') | ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $chosen $_) | Out-Null }
$bytes = New-Object byte[] 18
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$secret = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
$lines = @(
  "CLIPHUNTER_DATA_PATH='$library'"
  'HOST_UID=1000'
  'HOST_GID=1000'
  "APP_PASSWORD=$secret"
)
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) '.env.docker'), $lines, $utf8)
docker compose --env-file .env.docker up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker setup failed. Read the error above and retry.' }
Write-Host 'ClipHunter is starting at http://localhost:3000'
Write-Host 'Your workspace password is in the private .env.docker file. Keep it private.'
Write-Host "Your videos, models, and settings are under: $library"
