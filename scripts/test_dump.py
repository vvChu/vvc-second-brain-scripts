import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from services.brain_dump import _synthesize_and_save_concepts, _process_urls

dump_text = "https://substack.com/@itsddvn/note/c-255585635?r=615amq"
print("Processing URLs...")
url_content = _process_urls(dump_text)
print(f"URL content length: {len(url_content)}")

print("Calling LLM synthesis...")
saved_stems = _synthesize_and_save_concepts(dump_text, url_content, "test_source")
print(f"Saved stems: {saved_stems}")
