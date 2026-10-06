$ErrorActionPreference = "Stop"

# Elevate once: firewall and C:\ install are more reliable as Administrator.
$wid = [Security.Principal.WindowsIdentity]::GetCurrent()
$prp = New-Object Security.Principal.WindowsPrincipal($wid)
if (-not $prp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Requesting Administrator permission for firewall + portal integration..." -ForegroundColor Yellow
    Start-Process powershell.exe -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $MyInvocation.MyCommand.Path + '"'))
    exit
}

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = "C:\NOMADIC_TIDE\MAYA_AGENT_HUB"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "`n=== MAYA AGENT HUB v2 UPGRADE ===" -ForegroundColor Cyan

# Stop only the process that owns 8065 AND clearly belongs to MAYA_AGENT_HUB.
try {
    $listeners = Get-NetTCPConnection -LocalPort 8065 -State Listen -ErrorAction SilentlyContinue
    foreach ($l in $listeners) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($l.OwningProcess)" -ErrorAction SilentlyContinue
        if ($p -and (($p.CommandLine -like '*MAYA_AGENT_HUB*') -or ($p.CommandLine -like '*main.py*'))) {
            Write-Host "Stopping old Agent Hub process PID $($l.OwningProcess)..." -ForegroundColor DarkGray
            Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
} catch {}
Start-Sleep -Milliseconds 800

New-Item -ItemType Directory -Force -Path $Target | Out-Null
if (Test-Path "$Target\config.json") { Copy-Item "$Target\config.json" "$Target\config.pre-v2.$Stamp.json" -Force }
if (Test-Path "$Target\agent_hub.sqlite3") { Copy-Item "$Target\agent_hub.sqlite3" "$Target\agent_hub.pre-v2.$Stamp.sqlite3" -Force }

# Preserve database/history. Update application files and v2 profile config.
$copyItems = @('main.py','run.cmd','test.cmd','config.json','README.md','PORTAL_CARD.txt','static','portal')
foreach ($item in $copyItems) {
    $src = Join-Path $Source $item
    if (Test-Path $src) { Copy-Item $src -Destination $Target -Recurse -Force }
}
Copy-Item $MyInvocation.MyCommand.Path -Destination "$Target\upgrade_v2.ps1" -Force

# Reliable current-user autostart without a visible CMD window.
$Startup = [Environment]::GetFolderPath('Startup')
$VbsPath = Join-Path $Startup 'MayaAgentHub.vbs'
$RunPath = "$Target\run.cmd"
$vbs = @"
Set sh = CreateObject("WScript.Shell")
sh.Run Chr(34) & "$RunPath" & Chr(34), 0, False
"@
Set-Content -Path $VbsPath -Value $vbs -Encoding ASCII
Write-Host "[OK] Autostart installed: $VbsPath" -ForegroundColor Green

# Allow only the Tailscale IPv4 CGNAT range to reach port 8065 remotely.
$RuleName = 'MAYA Agent Hub 8065 - Tailscale only'
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8065 -RemoteAddress '100.64.0.0/10' -Profile Any | Out-Null
Write-Host "[OK] Firewall: TCP 8065 allowed from Tailscale 100.64.0.0/10" -ForegroundColor Green

# Safely inject one portal card through index.html. Always back up the file first.
$PortalCandidates = @(
    'C:\NOMADIC_TIDE\server_portal',
    'C:\NOMADIC_TIDE\server-portal',
    'C:\NOMADIC\TIDE\server_portal'
)
$Portal = $PortalCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Portal) {
    $Index = Join-Path $Portal 'index.html'
    if (-not (Test-Path $Index)) {
        $Index = Get-ChildItem -Path $Portal -Filter index.html -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    }
    if ($Index) {
        $IndexDir = Split-Path -Parent $Index
        $Public = Join-Path $Portal 'public'
        $AssetDir = if (($IndexDir -eq $Portal) -and (Test-Path $Public)) { $Public } else { $IndexDir }
        Copy-Item "$Target\portal\maya-agent-card.js" (Join-Path $AssetDir 'maya-agent-card.js') -Force
        $html = Get-Content $Index -Raw
        if ($html -notmatch 'maya-agent-card\.js') {
            Copy-Item $Index "$Index.maya-backup-$Stamp" -Force
            $tag = '  <script src="/maya-agent-card.js"></script>'
            if ($html -match '</body>') { $html = $html -replace '</body>', ($tag + "`r`n</body>") }
            else { $html += "`r`n$tag`r`n" }
            Set-Content -Path $Index -Value $html -Encoding UTF8
            Write-Host "[OK] Portal card injected. Backup: $Index.maya-backup-$Stamp" -ForegroundColor Green
        } else {
            Write-Host "[OK] Portal card already installed." -ForegroundColor Green
        }
    } else {
        Write-Host "[SKIP] server_portal found, but index.html was not found. Portal itself was not modified." -ForegroundColor Yellow
    }
} else {
    Write-Host "[SKIP] server_portal folder not found. Agent Hub still works normally." -ForegroundColor Yellow
}

# Start Agent Hub hidden.
Start-Process wscript.exe -ArgumentList ('"' + $VbsPath + '"')

$ok = $false
for ($i=0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8065/api/status' -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
}

$TailscaleIP = $null
try {
    $ts = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    $tsExe = if ($ts) { $ts.Source } elseif (Test-Path 'C:\Program Files\Tailscale\tailscale.exe') { 'C:\Program Files\Tailscale\tailscale.exe' } else { $null }
    if ($tsExe) { $TailscaleIP = (& $tsExe ip -4 2>$null | Select-Object -First 1).Trim() }
} catch {}

Write-Host "`n=== RESULT ===" -ForegroundColor Cyan
if ($ok) { Write-Host "[OK] Agent Hub API is ONLINE" -ForegroundColor Green }
else { Write-Host "[WARN] Agent Hub did not answer yet. Run $Target\run.cmd manually to see the error." -ForegroundColor Yellow }
Write-Host "PC:        http://localhost:8065" -ForegroundColor White
if ($TailscaleIP) { Write-Host "Tailscale: http://$($TailscaleIP):8065" -ForegroundColor Cyan }
else { Write-Host "Tailscale: use http://<server-tailscale-ip>:8065" -ForegroundColor DarkGray }
Write-Host "Portal:    http://localhost:8070" -ForegroundColor White
Write-Host "`nBusiness / Job / Land agent profiles were upgraded to our current rules." -ForegroundColor Green
Write-Host "Server Caretaker auto-restart stays OFF until exact project start commands are verified." -ForegroundColor Yellow
Write-Host "`nDone. Opening Command Center..." -ForegroundColor Cyan
Start-Process "http://localhost:8065"
if ($Portal) { Start-Process "http://localhost:8070" }
