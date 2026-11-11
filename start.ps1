param([switch]$Build)
& (Join-Path $PSScriptRoot 'start-platform.ps1') -Build:$Build
