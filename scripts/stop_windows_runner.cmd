@echo off
:: ============================================================
:: VvC Second Brain — Disable Windows Runner (Switch to Server)
:: Stops local daemons and disables Windows Task Scheduler.
:: ============================================================
echo ============================================================
echo   VvC Second Brain - Disable Windows Background Runner
echo ============================================================
echo.

echo 1. Stopping running daemon.py and book_ingest.py on Windows...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter 'Name like \"%%python%%\"' | Where-Object { $_.CommandLine -like '*daemon.py*' -or $_.CommandLine -like '*book_ingest.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host '  [OK] Stopped process PID:' $_.ProcessId }"

echo.
echo 2. Disabling Windows Task Scheduler 'VvC_KBCompiler'...
powershell -NoProfile -Command "Disable-ScheduledTask -TaskName 'VvC_KBCompiler' -ErrorAction SilentlyContinue; Write-Host '  [OK] Task VvC_KBCompiler has been disabled.'"

echo.
echo 3. Verifying remaining pythonw processes...
powershell -NoProfile -Command "$procs = Get-Process pythonw -ErrorAction SilentlyContinue; if ($procs) { Write-Host '  [WARN] pythonw still running:' ($procs | Select-Object -ExpandProperty Id) } else { Write-Host '  [OK] No background pythonw processes running.' }"

echo.
echo ============================================================
echo  HOAN TAT! Da tat toan bo daemon ngam tren Windows.
echo  Server Spark gio la Runner duy nhat xu ly Vault.
echo ============================================================
pause
