param(
    [ValidateSet("python", "docker")]
    [string]$Mode = "python",
    [string]$Python = "python",
    [int]$Port = 8080,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Wait-ForUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            return Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    throw "Timed out waiting for $Url"
}

Push-Location $repoRoot
try {
    if ($Mode -eq "python") {
        Write-Output "Starting local preview with Python on http://127.0.0.1:$Port/"
        Write-Output "Press Ctrl+C in this window to stop the server."

        if ($OpenBrowser) {
            Start-Process "http://127.0.0.1:$Port/" | Out-Null
        }

        & $Python server.py --host 127.0.0.1 --port $Port
        exit $LASTEXITCODE
    }

    Write-Output "Starting local preview with Docker on http://127.0.0.1:8080/"
    docker compose up -d --build | Out-Null
    $null = Wait-ForUrl -Url "http://127.0.0.1:8080/"

    if ($OpenBrowser) {
        Start-Process "http://127.0.0.1:8080/" | Out-Null
    }

    Write-Output "Container is running."
    Write-Output "App URL: http://127.0.0.1:8080/"
    Write-Output "Use 'docker compose down' to stop it."
} finally {
    Pop-Location
}
