$ContainerName = "finally"

$running = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($running) {
    Write-Host "Stopping FinAlly..."
    docker stop $ContainerName
    docker rm $ContainerName
    Write-Host "Container stopped. Data volume preserved."
} else {
    Write-Host "FinAlly is not running."
}
