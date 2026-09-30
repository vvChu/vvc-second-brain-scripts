@echo off
:: ============================================================
:: VvC Second Brain — Start Windows Runner
:: ============================================================
echo ============================================================
echo   VvC Second Brain - Start Windows Background Runner
echo ============================================================
echo 0. Checking Cross-Machine Fencing Lease...
python "D:\VvC_Notes\scripts\core\cross_machine_fencing.py" --check
if errorlevel 1 (
    echo.
    echo [ERROR] Cannot start Windows Runner: Active daemon detected on Linux Server Spark!
    echo De bat runner tren Windows, hay tat daemon tren Spark truoc:
    echo   ssh spark "systemctl --user stop vvc-daemon vvc-book-ingest"
    echo Hoac chay: python "D:\VvC_Notes\scripts\core\cross_machine_fencing.py" --force
    echo.
    pause
    exit /b 2
)

echo.
echo 1. Enabling Task Scheduler 'VvC_KBCompiler'...
powershell -NoProfile -Command "Enable-ScheduledTask -TaskName 'VvC_KBCompiler' -ErrorAction SilentlyContinue; Write-Host '  [OK] Task enabled.'"

echo.
echo 2. Launching daemons via run_watcher.vbs...
wscript.exe //B //NoLogo "D:\VvC_Notes\scripts\run_watcher.vbs"

echo.
echo 3. Checking running processes...
timeout /t 3 >nul
tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul
echo.
echo [Luu y] Neu chay runner tren Windows, hay dam bao da tat daemon tren Server Spark:
echo   systemctl --user stop vvc-daemon vvc-book-ingest
echo ============================================================
pause
