import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(r'd:\VvC_Notes\scripts')))
from services.excalidraw_worker import _generate_excalidraw

diagram_name = "test_diagram.excalidraw.md"
context_text = """
This is a test diagram.
The main concept is "Nền tảng VvC".
"Nền tảng VvC" supports "Người dùng".
"Nền tảng VvC" also connects to "Hệ sinh thái AI".
"""

print(f"Starting end-to-end diagram generation for {diagram_name}...")
start = time.time()
try:
    _generate_excalidraw(diagram_name, context_text)
    dur = time.time() - start
    print(f"Generation completed in {dur:.1f}s.")
except Exception as e:
    print(f"Pipeline failed: {e}")
