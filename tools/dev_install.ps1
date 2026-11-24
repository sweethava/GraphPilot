# Dev setup (Windows): link this repo's plugin folder into Designer, so edits apply after a Designer restart.
# Run with Designer CLOSED:  powershell -ExecutionPolicy Bypass -File tools\dev_install.ps1
# Also moves the pre-release "claude_mcp_bridge" plugin out of the way (to a backup folder, not deleted),
# because both would try to open the bridge on port 9881.

$ErrorActionPreference = "Stop"
if (Get-Process -Name "Adobe Substance 3D Designer" -ErrorAction SilentlyContinue) {
    Write-Error "Close Substance 3D Designer first."
}
$repo    = Split-Path -Parent $PSScriptRoot
$plugins = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Adobe\Adobe Substance 3D Designer\python\sduserplugins"
$link    = Join-Path $plugins "graphpilot"
$legacy  = Join-Path $plugins "claude_mcp_bridge"

if (Test-Path $legacy) {
    $backup = Join-Path $repo ("_backup_claude_mcp_bridge_" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Move-Item $legacy $backup
    Write-Host "moved old plugin to $backup"
}
if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType) { $item.Delete() } else { Write-Error "$link exists and is not a link; remove it manually." }
}
New-Item -ItemType Junction -Path $link -Target (Join-Path $repo "graphpilot") | Out-Null
Write-Host "linked $link -> $(Join-Path $repo 'graphpilot')"
Write-Host "Start Designer: the GraphPilot panel should appear."
