$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try { & npm.cmd run dev --workspace orchestration }
finally { Pop-Location }
