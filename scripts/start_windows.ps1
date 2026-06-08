param([switch]$Build)

$ProjectDir = Split-Path -Parent $PSScriptRoot
$ContainerName = "finally"
$ImageName = "finally:latest"

Set-Location $ProjectDir

# Check for .env file
if (-not (Test-Path ".env")) {
    Write-Host "No .env file found. Creating from .env.example..."
    Copy-Item ".env.example" ".env"
    Write-Host "Edit .env to set your OPENROUTER_API_KEY before using AI chat."
}

# Check if already running
$running = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($running) {
    Write-Host "FinAlly is already running at http://localhost:8000"
    exit 0
}

# Build if needed
$imageExists = docker image inspect $ImageName 2>$null
if ($Build -or -not $imageExists) {
    Write-Host "Building FinAlly..."
    docker build -t $ImageName .
}

# Remove stopped container if exists
docker rm -f $ContainerName 2>$null

# Run
Write-Host "Starting FinAlly..."
docker run -d `
    --name $ContainerName `
    -v finally-data:/app/db `
    -p 8000:8000 `
    --env-file .env `
    $ImageName

Write-Host ""
Write-Host "FinAlly is running!"
Write-Host "   -> http://localhost:8000"
Write-Host ""
Write-Host "   To stop: .\scripts\stop_windows.ps1"

Start-Sleep -Seconds 1
Start-Process "http://localhost:8000"
