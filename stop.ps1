param([switch]$Infrastructure)
& (Join-Path $PSScriptRoot 'stop-platform.ps1') -Infrastructure:$Infrastructure
