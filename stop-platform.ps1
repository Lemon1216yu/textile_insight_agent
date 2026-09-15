param([switch]$Infrastructure)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimeFile=Join-Path $PSScriptRoot 'artifacts/platform-processes.json'
$pids=@()
if (Test-Path $runtimeFile) {
  # NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI/GBK
  # when there is no BOM, so non-ASCII comments corrupt parsing.
  $parsed=Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
  foreach ($prop in $parsed.PSObject.Properties) { if ($prop.Value) { $pids+=[int]$prop.Value } }
}
if ($pids.Count -eq 0) {
  # Fallback: locate project processes by command line.
  $pids=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
          Where-Object { $_.CommandLine -like '*textile*' } |
          Select-Object -ExpandProperty ProcessId)
}
foreach ($processId in $pids) {
  $processInfo=Get-CimInstance Win32_Process -Filter ('ProcessId='+$processId)
  if ($processInfo -and $processInfo.CommandLine -like '*textile*') {
    $children=Get-CimInstance Win32_Process -Filter ('ParentProcessId='+$processId)
    foreach ($child in $children) { if ($child.CommandLine -like '*textile*') {Stop-Process -Id $child.ProcessId -Force} }
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
  }
}
if ($Infrastructure) {docker compose stop}
Write-Host 'Project processes stopped. Persistent database volumes retained.'
