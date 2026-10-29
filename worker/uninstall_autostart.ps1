# Removes the devagent worker autostart task.
$ErrorActionPreference = "SilentlyContinue"
Stop-ScheduledTask -TaskName "devagent-worker"
Unregister-ScheduledTask -TaskName "devagent-worker" -Confirm:$false
Write-Host "Removed 'devagent-worker' autostart (if it existed)."
