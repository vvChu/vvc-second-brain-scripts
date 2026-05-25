' VvC Second Brain — Silent Daemon Launcher (v8.8)
' Runs daemon.py and book_ingest.py as fully detached headless processes.
' Used by Task Scheduler: VvC_KBCompiler
'
' Strategy: Launch pythonw.exe directly (no cmd wrapper).
'   - pythonw.exe is the headless Python executable (no console window).
'   - daemon.py has built-in Headless Stdio Hardening that redirects
'     stdout/stderr to os.devnull when no console is attached.
'   - This eliminates the "cmd /c exits → Python dies" problem entirely.
'   - intWindowStyle = 0 (hidden) is safe for pythonw since it never
'     needs a console window, unlike python.exe which Defender monitors.
'
' v8.8: Replace cmd /c wrapper with direct pythonw.exe invocation.
'       Fixes daemon dying after ~2 minutes when cmd window auto-closes.

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set working directory
WshShell.CurrentDirectory = "D:\VvC_Notes\scripts"

' Kill all python/pythonw instances running daemon.py or book_ingest.py via PowerShell filter
' to prevent ghost processes while avoiding killing unrelated tasks.
WshShell.Run "powershell -WindowStyle Hidden -Command ""Get-CimInstance Win32_Process -Filter 'Name like ""%python%""' | Where-Object { $_.CommandLine -like '*daemon.py*' -or $_.CommandLine -like '*book_ingest.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }""", 0, True
WScript.Sleep 2000

' Launch LLM OS Daemon — pythonw.exe runs headless without a console
WshShell.Run """D:\VvC_Notes\scripts\.venv\Scripts\pythonw.exe"" ""D:\VvC_Notes\scripts\daemon.py""", 0, False

' Small delay to avoid race conditions
WScript.Sleep 2000

' Launch Book Ingestion Daemon — pythonw.exe runs headless without a console
WshShell.Run """D:\VvC_Notes\scripts\.venv\Scripts\pythonw.exe"" ""D:\VvC_Notes\scripts\book_ingest.py""", 0, False

Set WshShell = Nothing
