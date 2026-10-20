$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:N8N_LISTEN_ADDRESS = '127.0.0.1'
$env:N8N_DIAGNOSTICS_ENABLED = 'false'
$runtime = Get-Content -LiteralPath "$PSScriptRoot\config\n8n-runtime.json" -Raw | ConvertFrom-Json
if (!(Test-Path -LiteralPath $runtime.node) -or !(Test-Path -LiteralPath $runtime.cli)) {
    throw 'The configured n8n installation is unavailable. Restore its local paths in config/n8n-runtime.json. No packages were downloaded.'
}
& $runtime.node $runtime.cli
