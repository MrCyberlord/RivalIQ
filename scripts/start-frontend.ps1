$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try { & npm.cmd run dev }
finally { Pop-Location }
