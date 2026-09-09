@echo off
echo ================================================
echo  VvC Second Brain - Register Auto-Start Task
echo ================================================
echo.
echo This will register a Windows Task that starts the 
echo Knowledge Compiler watcher when you log in.
echo.
echo Requesting Administrator privileges...
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
schtasks /Delete /TN "VvC_KBCompiler" /F >nul 2>&1

echo [2/2] Creating scheduled task...
if exist "%~dp0vvc_kbcompiler.xml" (
    schtasks /Create /XML "%~dp0vvc_kbcompiler.xml" /TN "VvC_KBCompiler" /F
) else (
    schtasks /Create /TN "VvC_KBCompiler" /TR "wscript.exe \"%~dp0run_watcher.vbs\"" /SC ONLOGON /RL LIMITED /F
)

if %errorlevel% EQU 0 (
    echo.
    echo ================================================
    echo  SUCCESS! Task registered.
    echo  The watcher will start automatically at logon.
    echo.
    echo  Starting watcher now...
    schtasks /Run /TN "VvC_KBCompiler"
    echo  [OK] Watcher is running!
    echo.
    echo  To manage:
    echo    schtasks /Run    /TN "VvC_KBCompiler"  (start)
    echo    schtasks /End    /TN "VvC_KBCompiler"  (stop)
    echo    schtasks /Query  /TN "VvC_KBCompiler"  (status)
    echo    schtasks /Delete /TN "VvC_KBCompiler"  (remove)
    echo ================================================
) else (
    echo.
    echo [FAILED] Could not create task. Try running as Administrator.
)

echo.
pause
