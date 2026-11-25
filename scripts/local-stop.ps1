param(
    [string]$Python = "$PSScriptRoot\..\..\.team-validate-venv\Scripts\python.exe",
    [ValidateSet('local', 'smoke')][string]$Profile = 'local'
)
. "$PSScriptRoot\local-common.ps1"
$ports = Get-LocalProfile $Profile
$state = $ports.State
$file = Join-Path $state 'processes.json'
$lock = Open-LocalLock $state
try {
    if (!(Test-Path -LiteralPath $file)) { Write-Output 'No local services registered.'; return }
    $items = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
    $items = @($items)
    [array]::Reverse($items)
    foreach ($item in $items) {
        $process = Get-OwnedProcess $item
        if (!$process) { continue }
        # Open the Windows handle before shutdown so ExitCode stays readable.
        $null = $process.Handle
        switch ($item.name) {
            { $_ -in 'backend', 'https' } {
                New-Item -ItemType File -Force -Path "$state\$($item.name).stop" | Out-Null
            }
            'gateway' {
                $keys = Read-LocalEnv "$state\gateway-v2.env"
                Invoke-RestMethod "http://127.0.0.1:$($ports.Admin)/internal/local-shutdown" -Method Post -TimeoutSec 5 -Headers @{
                    Authorization = "Bearer $($keys.WHATSAPP_ADMIN_SECRET)"
                } | Out-Null
            }
            'mongo' {
                $Python = (Resolve-Path -LiteralPath $Python).Path
                & $Python "$PSScriptRoot\local-mongo-stop.py" $ports.Mongo
                if ($LASTEXITCODE -ne 0) { throw 'MongoDB rejected the local shutdown.' }
            }
            default { throw 'Unknown service in local registry.' }
        }
        if (!$process.WaitForExit(18000)) {
            throw "Graceful shutdown did not finish for $($item.name). Registry retained."
        }
        if ($item.name -eq 'gateway' -and $process.ExitCode -ne 0) {
            throw 'Gateway shutdown failed. Registry retained.'
        }
    }
    Remove-Item -LiteralPath $file
    Write-Output 'Local services stopped. MongoDB and WhatsApp storage preserved.'
} finally {
    $lock.Dispose()
}
