param(
    [string]$Python = "$PSScriptRoot\..\..\.team-validate-venv\Scripts\python.exe",
    [string]$Mongod = "$PSScriptRoot\..\..\.whatsapp-mongo-test\mongod.exe",
    [string]$Node = "$PSScriptRoot\..\..\.node22-verified\node-v22.13.0-win-x64\node.exe",
    [ValidateSet('local', 'smoke')][string]$Profile = 'local',
    [switch]$ShowQr
)
. "$PSScriptRoot\local-common.ps1"
$ports = Get-LocalProfile $Profile
$state = $ports.State
$lock = Open-LocalLock $state
$pidFile = Join-Path $state 'processes.json'
$records = @()
$failure = $null

function Start-LocalProcess($name, $exe, $arguments, $directory) {
    $options = @{
        FilePath = $exe; ArgumentList = $arguments; WorkingDirectory = $directory
        WindowStyle = 'Hidden'; PassThru = $true
        RedirectStandardOutput = "$state\logs\$name.out.log"
        RedirectStandardError = "$state\logs\$name.err.log"
    }
    $process = Start-Process @options
    $script:records += @{ name = $name; id = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o') }
    ConvertTo-Json -InputObject $script:records | Set-Content -LiteralPath $pidFile
    return $process
}

function Wait-LocalService($process, $name, $probe) {
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        if ($process.HasExited) { break }
        try { if (& $probe) { return } } catch {}
        Start-Sleep -Milliseconds 350
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$name did not become ready. See .local-dev logs for this profile."
}

try {
    if (Test-Path -LiteralPath $pidFile) { throw 'Existing service registry. Stop this profile first with local-stop.ps1.' }
    foreach ($port in $ports.Mongo, $ports.Hub, $ports.Gateway, $ports.Admin, $ports.Https) {
        $probe = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback), $port
        try { $probe.Start() } catch { throw "Local port $port is occupied. No existing process was stopped." }
        finally { $probe.Stop() }
    }
    $Python = (Resolve-Path -LiteralPath $Python).Path
    $Mongod = (Resolve-Path -LiteralPath $Mongod).Path
    $Node = (Resolve-Path -LiteralPath $Node).Path
    $nodeVersion = & $Node -p "process.versions.node"
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^22\.' -or [version]$nodeVersion -lt [version]'22.13.0') {
        throw 'The gateway requires Node 22 version 22.13.0 or later.'
    }
    if (!(Test-Path "$root\frontend\build\index.html")) {
        throw 'Build React first in frontend with corepack yarn install --frozen-lockfile and corepack yarn build.'
    }
    if (!(Test-Path "$root\whatsapp-service\node_modules\@whiskeysockets\baileys")) {
        throw 'Install the gateway dependencies with npm ci under Node 22.'
    }
    foreach ($name in 'server-dev.crt','server-dev.key') {
        if (!(Test-Path -LiteralPath "$dev\tls\$name")) { throw "Missing .local-dev/tls/$name." }
    }
    New-Item -ItemType Directory -Force -Path "$state\mongo", "$state\logs", "$state\gateway" | Out-Null
    $envFile = Join-Path $state 'local.env'
    if (!(Test-Path -LiteralPath $envFile)) {
        Get-Content "$PSScriptRoot\local.env.example" | ForEach-Object {
            if ($_ -match '^([A-Z_]+)=CHANGE_ME$') { "$($Matches[1])=$(New-LocalSecret)" } else { $_ }
        } | Set-Content -LiteralPath $envFile
    }
    $keysFile = Join-Path $state 'gateway-v2.env'
    if (!(Test-Path -LiteralPath $keysFile)) {
        $newKeys = foreach ($name in 'WHATSAPP_SERVICE_SECRET','WHATSAPP_ADMIN_SECRET','WHATSAPP_STORAGE_KEY') {
            "$name=$(New-LocalSecret)"
        }
        $newKeys | Set-Content -LiteralPath $keysFile
    }
    # Keep deployment credentials and integrations out of local child processes.
    Get-ChildItem Env: | Where-Object Name -Match '^(MONGO|DB_NAME$|ADMIN_|STAFF_|JWT|HANDOFF_|MODULE_|ORDERS_|INVENTORY_|WHATSAPP_|FRONTEND_|RESEND_|EMAIL_FROM_|RECOVERY_|DACOT_|UVICORN_)' |
        ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name, $null, 'Process') }
    $local = Read-LocalEnv $envFile
    $gatewayKeys = Read-LocalEnv $keysFile
    foreach ($name in 'ADMIN_EMAIL','ADMIN_PASSWORD','JWT_SECRET','HANDOFF_JWT_SECRET') {
        if (!$local[$name] -or $local[$name] -eq 'CHANGE_ME') { throw "Configure $name in the local environment file." }
        [Environment]::SetEnvironmentVariable($name, $local[$name], 'Process')
    }
    foreach ($name in 'WHATSAPP_SERVICE_SECRET','WHATSAPP_ADMIN_SECRET','WHATSAPP_STORAGE_KEY') {
        if ($gatewayKeys[$name].Length -lt 32) { throw "Invalid local gateway key $name." }
        [Environment]::SetEnvironmentVariable($name, $gatewayKeys[$name], 'Process')
    }
    $env:APP_ENV = 'development'
    $env:PYTHON_DOTENV_DISABLED = '1'
    $env:MONGO_URL = "mongodb://127.0.0.1:$($ports.Mongo)/?directConnection=true"
    $env:DB_NAME = 'dacot_local'
    $env:FRONTEND_URL = 'http://localhost:3000'
    $env:WHATSAPP_LOCAL_INVITE_ORIGIN = "https://localhost:$($ports.Https)"
    $env:WHATSAPP_FRONTEND_ORIGIN = $env:WHATSAPP_LOCAL_INVITE_ORIGIN
    $env:WHATSAPP_SERVICE_URL = "http://127.0.0.1:$($ports.Gateway)"
    $env:WHATSAPP_SERVICE_TRANSPORT = 'local-loopback-http'
    $env:LOCAL_HUB_PORT = [string]$ports.Hub
    $env:LOCAL_HTTPS_PORT = [string]$ports.Https
    $env:LOCAL_STATE_DIR = $state
    $env:LOCAL_TLS_DIR = "$dev\tls"
    $env:WHATSAPP_DB_PATH = "$state\gateway\managed.sqlite"
    $env:WHATSAPP_TRANSPORT = 'proxy-http'
    $env:WHATSAPP_ENABLED = if ($Profile -eq 'smoke') { 'false' } else { 'true' }
    $env:WHATSAPP_LOCAL_SHUTDOWN = 'true'
    $env:HOST = '127.0.0.1'
    $env:PORT = [string]$ports.Gateway
    $env:WHATSAPP_ADMIN_PORT = [string]$ports.Admin
    foreach ($name in 'backend','https') {
        $marker = Join-Path $state "$name.stop"
        if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker }
    }
    $dbPath = '"' + (Join-Path $state 'mongo') + '"'
    $mongo = Start-LocalProcess 'mongo' $Mongod @('--bind_ip','127.0.0.1','--port',$ports.Mongo,'--dbpath',$dbPath) $root
    Wait-LocalService $mongo 'MongoDB' {
        & $Python -c "import os; from pymongo import MongoClient; MongoClient(os.environ['MONGO_URL'],serverSelectionTimeoutMS=400).admin.command('ping')" 2>$null
        $LASTEXITCODE -eq 0
    }
    & $Python "$root\backend\migrate_auth_indexes.py" --apply --confirm MIGRATE_AUTH_IDENTIFIER_INDEXES --backup-file "$state\index-metadata-$([guid]::NewGuid()).json"
    if ($LASTEXITCODE -ne 0) { throw 'Local index migration failed.' }
    $gateway = Start-LocalProcess 'gateway' $Node @('server.mjs') "$root\whatsapp-service"
    Wait-LocalService $gateway 'Gateway' { (Invoke-RestMethod "http://127.0.0.1:$($ports.Gateway)/health" -TimeoutSec 1).ok }
    $backend = Start-LocalProcess 'backend' $Python @('..\scripts\local-backend.py') "$root\backend"
    Wait-LocalService $backend 'FastAPI' { (Invoke-RestMethod "http://127.0.0.1:$($ports.Hub)/api/" -TimeoutSec 1).ok }
    $https = Start-LocalProcess 'https' $Node @('scripts/local-https-proxy.cjs') $root
    Wait-LocalService $https 'HTTPS proxy' {
        & curl.exe --noproxy '*' --silent --max-time 2 --fail --cacert "$dev\tls\server-dev.crt" --output NUL "https://localhost:$($ports.Https)/reset-password"
        $LASTEXITCODE -eq 0
    }
    Write-Output "HUB http://localhost:$($ports.Hub)/login | HTTPS https://localhost:$($ports.Https)/reset-password"
    Write-Output "Local administrator configuration: $envFile"
    if ($ShowQr -and $Profile -eq 'local') {
        Start-Process -FilePath $Node -ArgumentList 'scripts/local-whatsapp-qr.cjs' -WorkingDirectory $root
    }
} catch {
    $failure = $_
} finally {
    $lock.Dispose()
}
if ($failure) {
    if ($records.Count) {
        try { & "$PSScriptRoot\local-stop.ps1" -Profile $Profile -Python $Python } catch { Write-Warning $_.Exception.Message }
    }
    throw $failure
}
