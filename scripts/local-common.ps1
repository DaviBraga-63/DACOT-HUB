$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..").Path
$dev = Join-Path $root '.local-dev'

function Get-LocalProfile($name) {
    if ($name -eq 'smoke') {
        return @{ State = (Join-Path $dev 'smoke'); Mongo = 27119; Hub = 18000; Gateway = 13014; Admin = 13015; Https = 18444 }
    }
    return @{ State = $dev; Mongo = 27118; Hub = 8000; Gateway = 3014; Admin = 3015; Https = 8444 }
}

function Read-LocalEnv($file) {
    $result = @{}
    foreach ($line in Get-Content -LiteralPath $file) {
        if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') { $result[$Matches[1]] = $Matches[2] }
    }
    return $result
}

function New-LocalSecret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [Convert]::ToBase64String($bytes)
}

function Get-OwnedProcess($item) {
    $process = Get-Process -Id ([int]$item.id) -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq ([datetime]$item.started).ToUniversalTime().Ticks) {
        return $process
    }
}

function Open-LocalLock($directory) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [IO.File]::Open((Join-Path $directory 'lifecycle.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
}
