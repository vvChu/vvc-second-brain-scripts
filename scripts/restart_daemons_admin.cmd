@echo off
:: Run this script as Administrator to restart daemons cleanly
echo Restarting daemons via VBS launcher...
wscript.exe //B //NoLogo "D:\VvC_Notes\scripts\run_watcher.vbs"
echo Done! Daemons restarted.
echo.
echo Verifying...
timeout /t 5 >nul
tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul
pause
