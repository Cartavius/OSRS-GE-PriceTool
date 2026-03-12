param(
    [int]$StartupTimeoutSeconds = 30,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Wait-ForUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
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
    docker compose up -d --build | Out-Null

    $rootResponse = Wait-ForUrl -Url "http://127.0.0.1:8080/" -TimeoutSeconds $StartupTimeoutSeconds
    $historyResponse = Wait-ForUrl -Url "http://127.0.0.1:8080/history/stats" -TimeoutSeconds $StartupTimeoutSeconds

    if ($rootResponse.StatusCode -ne 200) {
        throw "Expected GET / to return 200, got $($rootResponse.StatusCode)."
    }

    if ($historyResponse.StatusCode -ne 200) {
        throw "Expected GET /history/stats to return 200, got $($historyResponse.StatusCode)."
    }

    $historyJson = $historyResponse.Content | ConvertFrom-Json
    if (-not $historyJson.db_path) {
        throw "Expected /history/stats to return a db_path value."
    }

    Write-Output "Docker smoke test passed."
    Write-Output "Root: $($rootResponse.StatusCode)"
    Write-Output "History stats: $($historyResponse.StatusCode)"
    Write-Output "History DB path: $($historyJson.db_path)"
    Write-Output "App URL: http://127.0.0.1:8080/"

    if (-not $KeepRunning) {
        docker compose down | Out-Null
        Write-Output "Container stopped."
    } else {
        Write-Output "Container left running."
    }
} catch {
    try {
        docker compose logs --tail 100
    } catch {
    }
    throw
} finally {
    Pop-Location
}
