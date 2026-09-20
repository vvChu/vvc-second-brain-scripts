@echo off
:: ============================================================
:: VvC Second Brain — Start Windows Runner
:: ============================================================
echo ============================================================
echo   VvC Second Brain - Start Windows Background Runner
echo ============================================================
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
