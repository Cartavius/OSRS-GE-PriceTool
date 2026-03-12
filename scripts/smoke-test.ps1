param(
    [string]$Python = "python",
    [int]$Port = 8091,
    [int]$StartupTimeoutSeconds = 15,
    [switch]$IncludeUpstream
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$stdoutPath = Join-Path $repoRoot "smoke-test.stdout.log"
$stderrPath = Join-Path $repoRoot "smoke-test.stderr.log"

if (Test-Path $stdoutPath) {
    Remove-Item $stdoutPath -Force
}

if (Test-Path $stderrPath) {
    Remove-Item $stderrPath -Force
}

$server = $null

try {
    $server = Start-Process `
        -FilePath $Python `
        -ArgumentList "server.py", "--host", "127.0.0.1", "--port", $Port `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    $rootResponse = $null
    $historyResponse = $null
    $baseUrl = "http://127.0.0.1:$Port"
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        try {
            $rootResponse = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 5
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $rootResponse) {
        throw "Server did not become ready within $StartupTimeoutSeconds seconds."
    }

    $historyResponse = Invoke-WebRequest -Uri "$baseUrl/history/stats" -UseBasicParsing -TimeoutSec 10
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

    Write-Output "Smoke test passed."
    Write-Output "PID: $($server.Id)"
    Write-Output "Root: $($rootResponse.StatusCode)"
    Write-Output "History stats: $($historyResponse.StatusCode)"
    Write-Output "History DB path: $($historyJson.db_path)"

    if ($IncludeUpstream) {
        $mappingResponse = Invoke-WebRequest -Uri "$baseUrl/api/v1/osrs/mapping" -UseBasicParsing -TimeoutSec 20

        if ($mappingResponse.StatusCode -ne 200) {
            throw "Expected GET /api/v1/osrs/mapping to return 200, got $($mappingResponse.StatusCode)."
        }

        $mappingJson = $mappingResponse.Content | ConvertFrom-Json
        $mappingCount = @($mappingJson).Count

        if ($mappingCount -le 0) {
            throw "Expected mapping endpoint to return at least one item."
        }

        Write-Output "Mapping items: $mappingCount"
    } else {
        Write-Output "Upstream API check: skipped"
    }
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
