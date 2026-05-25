import re

def _extract_inbox_sections(content: str):
    match = re.search(r"(##\s*Inbox[ \t]*\n)(.*?)(?=\n##\s*|\Z)", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return "", "", ""
    before = content[:match.start(2)]
    inbox = match.group(2).strip()
    after = content[match.end(2):]
    return before, inbox, after

current_content = """# Brain Dump (Inbox)

Paste random thoughts, ideas, or snippets here. The Watchdog will extract them into Permanent concepts.

## Inbox
https://substack.com/@itsddvn/note/c-255585635?r=615amq

## Processed
- [[bay_nang_suat_ai_3]]
- [[phan_tang_ky_nang_trong_ky_nguyen_ai_2]]
"""

dump_text = "https://substack.com/@itsddvn/note/c-255585635?r=615amq"

before, inbox, after = _extract_inbox_sections(current_content)
print(f"Inbox: {repr(inbox)}")
print(f"After: {repr(after)}")

if before and inbox:
    new_inbox = inbox.replace(dump_text, "").strip()
    if new_inbox:
        new_inbox = "\n" + new_inbox + "\n"
    else:
        new_inbox = "\n\n"
        
    if not after.startswith("\n"):
        after = "\n" + after
    new_content = before + new_inbox + after
    print("New content:")
    print(repr(new_content))
