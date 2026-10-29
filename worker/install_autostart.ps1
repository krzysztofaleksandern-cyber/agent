# Registers the devagent host worker to start automatically at logon (Windows Task Scheduler).
# Run in PowerShell from the repo root:  powershell -ExecutionPolicy Bypass -File worker\install_autostart.ps1
# Reads config from worker\.env (copy worker\.env.example first).

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$worker = Join-Path $root "worker\operator_worker.py"
$envf   = Join-Path $root "worker\.env"

if (-not (Test-Path $envf)) { Write-Error "Missing worker\.env (copy worker\.env.example and fill it in)"; exit 1 }

# Find pythonw.exe (no console window) next to python.exe
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe).Source }

$taskName = "devagent-worker"
$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$worker`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal= New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started '$taskName'. It will run at every logon."
Write-Host "Stop:      Stop-ScheduledTask  -TaskName $taskName"
Write-Host "Remove:    Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
