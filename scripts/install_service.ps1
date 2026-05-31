<#
.SYNOPSIS
    Install VvC KB Compiler as Windows Scheduled Tasks (v7.0 Lean Compiler).
.DESCRIPTION
    Creates a Python venv (if needed), installs deps, and registers two
    Scheduled Tasks:
      - VvC_KBCompiler  : Runs at logon via run_watcher.vbs
                          (daemon.py + book_ingest.py, headless via pythonw)
      - VvC_SleepDaemon : Runs weekly (Sunday 02:00 AM) via run_sleep.vbs
                          (sleep.py - wiki health, MOC rebuild, log rotation)
.NOTES
    Run as Administrator!
    v7.0: Lean Compiler architecture. Uses VBS launchers (no bat wrapper).
          Correct filenames: daemon.py, book_ingest.py, sleep.py.
#>

$ErrorActionPreference = "Stop"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VaultRoot  = Split-Path -Parent $ScriptDir
$VenvDir    = Join-Path $ScriptDir ".venv"
$PythonW    = Join-Path $VenvDir "Scripts\pythonw.exe"
$TaskName   = "VvC_KBCompiler"
$SleepTask  = "VvC_SleepDaemon"
$VbsWatcher = Join-Path $ScriptDir "run_watcher.vbs"
$VbsSleep   = Join-Path $ScriptDir "run_sleep.vbs"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " VvC Second Brain - Service Installer (v7.0)"    -ForegroundColor Cyan
Write-Host " Lean Compiler Architecture"                       -ForegroundColor DarkCyan
Write-Host "================================================" -ForegroundColor Cyan

# --- Step 1: Check/Create venv ---
Write-Host "`n[1/5] Checking Python virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path $VenvDir)) {
    Write-Host "  Creating venv at $VenvDir..."
    python -m venv $VenvDir
    Write-Host "  [OK] venv created"
} else {
    Write-Host "  [OK] venv already exists"
}

if (-not (Test-Path $PythonW)) {
    Write-Error "  [FAIL] pythonw.exe not found at $PythonW. Check venv setup."
    exit 1
}
Write-Host "  [OK] pythonw.exe found"

# --- Step 2: Install dependencies ---
Write-Host "`n[2/5] Installing dependencies..." -ForegroundColor Yellow
$pip = Join-Path $VenvDir "Scripts\pip.exe"
& $pip install -r (Join-Path $ScriptDir "requirements.txt") --quiet 2>&1 | Out-Null
Write-Host "  [OK] Core dependencies installed"

try {
    & $pip install -e "D:\GitHubProjects\ccba-agent-platform\packages\ccba-ai" --quiet 2>&1 | Out-Null
    Write-Host "  [OK] ccba-ai installed"
} catch {
    Write-Host "  [SKIP] ccba-ai not available (optional)" -ForegroundColor DarkYellow
}

# --- Step 3: Remove existing tasks ---
Write-Host "`n[3/5] Removing old tasks (if any)..." -ForegroundColor Yellow
foreach ($tn in @($TaskName, $SleepTask)) {
    $existing = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $tn -Confirm:$false
        Write-Host "  [OK] Removed: $tn"
    }
}

# --- Step 4: VvC_KBCompiler (daemon.py + book_ingest.py via run_watcher.vbs) ---
Write-Host "`n[4/5] Creating Watcher Task '$TaskName'..." -ForegroundColor Yellow

if (-not (Test-Path $VbsWatcher)) {
    Write-Error "  [FAIL] run_watcher.vbs not found at $VbsWatcher"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "//B //NoLogo `"$VbsWatcher`""

$trigger = New-ScheduledTaskTrigger -AtLogOn

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# AllowStartIfOnBatteries = True, DontStopIfGoingOnBatteries = True
# Ensures daemon keeps running on battery (e.g., laptop unplugged)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "VvC Second Brain v7.0: Launches daemon.py + book_ingest.py silently via run_watcher.vbs at logon." | Out-Null

Write-Host "  [OK] '$TaskName' created (At Logon, runs on battery)" -ForegroundColor Green

# --- Step 5: VvC_SleepDaemon (sleep.py via run_sleep.vbs, weekly SUN 02:00) ---
Write-Host "`n[5/5] Creating Sleep Task '$SleepTask'..." -ForegroundColor Yellow

if (-not (Test-Path $VbsSleep)) {
    Write-Error "  [FAIL] run_sleep.vbs not found at $VbsSleep"
    exit 1
}

$sleepAction = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "//B //NoLogo `"$VbsSleep`""

$sleepTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "02:00AM"

$sleepSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $SleepTask `
    -Action $sleepAction `
    -Trigger $sleepTrigger `
    -Principal $principal `
    -Settings $sleepSettings `
    -Description "VvC Second Brain v7.0: Weekly consolidation (lint, heal, MOC rebuild, log rotation) via sleep.py every Sunday 02:00 AM." | Out-Null

Write-Host "  [OK] '$SleepTask' created (Every Sunday 02:00 AM)" -ForegroundColor Green

# --- Start watcher immediately ---
Write-Host ""
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
$taskInfo  = Get-ScheduledTask -TaskName $TaskName
$sleepInfo = Get-ScheduledTask -TaskName $SleepTask

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Installation complete! (v7.0 Lean Compiler)"    -ForegroundColor Green
Write-Host ""
Write-Host " Watcher  : $($taskInfo.State)  (daemon.py + book_ingest.py)" -ForegroundColor White
Write-Host " Sleep    : $($sleepInfo.State)  (sleep.py, Sunday 02:00 AM)" -ForegroundColor White
Write-Host ""
Write-Host " Scripts  :" -ForegroundColor Yellow
Write-Host "   Watcher -> $VbsWatcher"  -ForegroundColor White
Write-Host "   Sleep   -> $VbsSleep"    -ForegroundColor White
Write-Host ""
Write-Host " Manage tasks:" -ForegroundColor Yellow
Write-Host "   Start-ScheduledTask -TaskName $TaskName"       -ForegroundColor White
Write-Host "   Stop-ScheduledTask  -TaskName $TaskName"       -ForegroundColor White
Write-Host "   Start-ScheduledTask -TaskName $SleepTask"      -ForegroundColor White
Write-Host "   Stop-ScheduledTask  -TaskName $SleepTask"      -ForegroundColor White
Write-Host ""
Write-Host " Logs:" -ForegroundColor Yellow
Write-Host "   $(Join-Path (Join-Path $ScriptDir 'logs') 'daemon.log')"          -ForegroundColor White
Write-Host "   $(Join-Path (Join-Path $ScriptDir 'logs') 'book_ingestion.log')"  -ForegroundColor White
Write-Host "   $(Join-Path (Join-Path $ScriptDir 'logs') 'sleep_daemon.log')"    -ForegroundColor White
Write-Host "================================================" -ForegroundColor Cyan
