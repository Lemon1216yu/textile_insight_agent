param([switch]$Build)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING='utf-8'
# docker compose writes benign warnings to stderr (e.g. orphan containers). Under
# $ErrorActionPreference='Stop' those become NativeCommandError and abort the script,
# so relax it for this call and check the exit code explicitly instead.
$ErrorActionPreference='Continue'
docker compose up -d --wait --wait-timeout 180
$dockerExit=$LASTEXITCODE
$ErrorActionPreference='Stop'
if ($dockerExit -ne 0) { throw 'Docker services unavailable' }
if (!(Test-Path '.venv/Scripts/python.exe')) { uv sync; if ($LASTEXITCODE -ne 0) { throw 'Dependency sync failed' } }
& .venv/Scripts/python.exe scripts/migrate_platform.py
if ($LASTEXITCODE -ne 0) { throw 'Platform migration failed' }
# Publish metric master data before the vector index step, so retrieval reads current wording.
& .venv/Scripts/python.exe scripts/publish_metrics.py
if ($LASTEXITCODE -ne 0) { throw 'Metric publication failed' }
& .venv/Scripts/python.exe scripts/seed_extended.py
if ($LASTEXITCODE -ne 0) { throw 'Extended seed failed' }
& .venv/Scripts/python.exe scripts/ensure_index.py
if ($LASTEXITCODE -ne 0) { throw 'Index unavailable' }
if ($Build -or !(Test-Path 'static/portal/index.html')) {
 Push-Location frontend
 try { npm ci; if ($LASTEXITCODE -ne 0) {throw 'Frontend dependencies failed'}; npm run build; if ($LASTEXITCODE -ne 0) {throw 'Frontend build failed'} } finally {Pop-Location}
}
$runtimeFile=Join-Path $PSScriptRoot 'artifacts/platform-processes.json'
$saved=@{}
if (Test-Path $runtimeFile) {
 # NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI/GBK
 # when there is no BOM, so non-ASCII comments corrupt parsing.
 $parsed=Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
 foreach ($prop in $parsed.PSObject.Properties) { $saved[$prop.Name]=$prop.Value }
}
$python=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
foreach ($service in @('worker','api')) {
 $existing=$null
 if ($saved[$service]) { $existing=Get-CimInstance Win32_Process -Filter ('ProcessId='+$saved[$service]) }
 if ($existing -and $existing.CommandLine -like '*textile*') { continue }
 if ($service -eq 'api') {
   $listener=Get-NetTCPConnection -LocalPort 8018 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
   if ($listener) {throw 'Port 8018 already in use; stop the project API before restarting'}
   $arguments=@('-m','uvicorn','textile.app:app','--host','127.0.0.1','--port','8018')
 } else { $arguments=@('-m','arq','textile.task_queue.WorkerSettings') }
 $started=Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput ('artifacts/'+$service+'.out.log') -RedirectStandardError ('artifacts/'+$service+'.err.log') -PassThru
 $saved[$service]=$started.Id
}
$saved | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding utf8
Write-Host 'API: http://127.0.0.1:8018 ; independent arq worker started. Logs: artifacts/api.err.log and worker.err.log'
