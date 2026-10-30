# Install infinityoc-recover as a global opencode skill (Windows).
$ErrorActionPreference = "Stop"
$target = Join-Path $env:USERPROFILE ".config\opencode\skills\infinityoc-recover"
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
Copy-Item -Recurse -Force $PSScriptRoot $target
Write-Host "installed: $target"
Write-Host "test:"
Write-Host "  python `"$target\scripts\recover.py`" <session-id-or-fragment>"
