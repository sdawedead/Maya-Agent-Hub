$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = "C:\NOMADIC_TIDE\MAYA_AGENT_HUB"
Write-Host "Installing MAYA_AGENT_HUB to $Target" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Path "$Source\*" -Destination $Target -Recurse -Force
$Python = (Get-Command py -ErrorAction SilentlyContinue)
if ($Python) { $Action = New-ScheduledTaskAction -Execute "py" -Argument '-3 "C:\NOMADIC_TIDE\MAYA_AGENT_HUB\main.py"' -WorkingDirectory $Target }
else { $Action = New-ScheduledTaskAction -Execute "python" -Argument '"C:\NOMADIC_TIDE\MAYA_AGENT_HUB\main.py"' -WorkingDirectory $Target }
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
try {
  Register-ScheduledTask -TaskName "MayaAgentHub" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Nomadic Tide Maya Agent Hub" -RunLevel Highest -Force | Out-Null
  Write-Host "Windows startup task installed." -ForegroundColor Green
} catch {
  Write-Host "Could not create startup task automatically. Run PowerShell as Administrator if you want autostart." -ForegroundColor Yellow
}
Write-Host "Starting Agent Hub on port 8065..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList '/c','C:\NOMADIC_TIDE\MAYA_AGENT_HUB\run.cmd' -WorkingDirectory $Target
Write-Host "Open http://localhost:8065" -ForegroundColor Green
