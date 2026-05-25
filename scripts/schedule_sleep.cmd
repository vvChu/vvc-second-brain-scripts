@echo off
echo ================================================
echo  VvC Second Brain - Schedule Sleep Daemon
echo ================================================
echo.
echo This registers a weekly Sleep Consolidation task
echo that runs every Sunday at 02:00 AM.
echo.

:: Self-elevate
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo Requesting administrative privileges...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    if exist "%temp%\getadmin.vbs" ( del "%temp%\getadmin.vbs" )
    pushd "%CD%"
    CD /D "%~dp0"

echo [1/2] Removing old task if exists...
schtasks /Delete /TN "VvC_SleepDaemon" /F >nul 2>&1

echo [2/2] Creating weekly scheduled task...
schtasks /Create /TN "VvC_SleepDaemon" /TR "\"%SYSTEMROOT%\System32\wscript.exe\" \"%~dp0run_sleep.vbs\"" /SC WEEKLY /D SUN /ST 02:00 /RL LIMITED /F

if %errorlevel% EQU 0 (
    echo.
    echo ================================================
    echo  SUCCESS! Sleep Daemon scheduled.
    echo  Runs every Sunday at 02:00 AM.
    echo.
    echo  To manage:
    echo    schtasks /Run    /TN "VvC_SleepDaemon"  (run now)
    echo    schtasks /End    /TN "VvC_SleepDaemon"  (stop)
    echo    schtasks /Query  /TN "VvC_SleepDaemon"  (status)
    echo    schtasks /Delete /TN "VvC_SleepDaemon"  (remove)
    echo ================================================
) else (
    echo.
    echo [FAILED] Could not create task. Try running as Administrator.
)

echo.
pause
