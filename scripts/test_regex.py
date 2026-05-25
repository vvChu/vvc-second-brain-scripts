import re

content = """# Brain Dump (Inbox)

## Inbox

## Processed
- [[link1]]"""

match = re.search(r"(##\s*Inbox\s*\n)(.*?)(?=\n##\s*|\Z)", content, re.IGNORECASE | re.DOTALL)
print("Match found:", bool(match))
if match:
    before = content[:match.start(2)]
    inbox = match.group(2).strip()
    after = content[match.end(2):]
    print(f"Before: {repr(before)}")
    print(f"Inbox: {repr(inbox)}")
    print(f"After: {repr(after)}")
