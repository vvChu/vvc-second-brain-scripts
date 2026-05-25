' VvC Second Brain — Silent Sleep Daemon Launcher
' Runs sleep.py completely hidden (no CMD window).
' Used by Task Scheduler: VvC_SleepDaemon
'
' Strategy: Use pythonw.exe directly (no cmd /c wrapper) to guarantee
' ZERO console windows. Output goes to sleep_daemon.log via Python logging.

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set working directory
WshShell.CurrentDirectory = "D:\VvC_Notes\scripts"

' Launch Sleep Daemon (hidden, wait for completion since it's a batch job)
' pythonw.exe = windowless Python — NEVER creates a console window
WshShell.Run """.venv\Scripts\pythonw.exe"" sleep.py", 0, True

Set WshShell = Nothing
