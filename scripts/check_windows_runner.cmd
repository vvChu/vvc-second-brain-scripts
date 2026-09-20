@echo off
:: ============================================================
:: VvC Second Brain — Check Windows Runner Status
:: ============================================================
echo ============================================================
echo   VvC Second Brain - Check Windows Runner Status
echo ============================================================
echo.
powershell -NoProfile -Command "& { $task = Get-ScheduledTask -TaskName 'VvC_KBCompiler' -ErrorAction SilentlyContinue; if ($task) { Write-Host ('Task Scheduler VvC_KBCompiler: ' + $task.State) } else { Write-Host 'Task Scheduler VvC_KBCompiler: Khong tim thay' }; $py = Get-CimInstance Win32_Process -Filter 'Name like \"%%python%%\"' | Where-Object { $_.CommandLine -like '*daemon.py*' -or $_.CommandLine -like '*book_ingest.py*' }; if ($py) { Write-Host 'Running Daemons:'; $py | ForEach-Object { Write-Host ('  - PID ' + $_.ProcessId + ': ' + $_.CommandLine) } } else { Write-Host 'Running Daemons: Khong co daemon nao dang chay tren Windows.' } }"
echo.
pause
