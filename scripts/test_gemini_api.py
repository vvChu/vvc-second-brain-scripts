import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(r'd:\VvC_Notes\scripts')))
from core.llm import _call_gemini_api

models_to_test = [
    'gemini-3.1-pro-preview',
    'gemini-3-flash-preview',
    'gemini-3.1-flash-lite-preview'
]

test_prompt = """You are a diagram topology extractor. I have a set of diagram nodes with their text content and IDs.
Based on the text content, infer the logical flow (directed edges) between these nodes to represent a flowchart.
Output ONLY a JSON array of objects with "source" and "target" fields.

NODES:
[{"id": "1", "text": "Nền tảng chia sẻ"}, {"id": "2", "text": "Tế bào phát triển"}, {"id": "3", "text": "Đối tác"}]"""

print('Starting Gemini REST API Model Evaluation...')
for m in models_to_test:
    print(f'\n--- Testing {m} ---')
    start = time.time()
    try:
        res = _call_gemini_api(test_prompt, model=m, timeout=30)
        dur = time.time() - start
        if res:
            # check if valid JSON
            try:
                json.loads(res.replace('```json', '').replace('```', '').strip())
                print(f'SUCCESS ({dur:.1f}s) - Output is Valid JSON')
                print(res)
            except json.JSONDecodeError:
                print(f'SUCCESS ({dur:.1f}s) - Output is NOT valid JSON')
                print(res)
        else:
            print(f'FAILED or empty ({dur:.1f}s)')
    except Exception as e:
        print(f'ERROR: {e}')
