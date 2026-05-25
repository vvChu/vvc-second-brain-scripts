import re

content = """# Brain Dump (Inbox)

## Inbox

## Processed
- [[link1]]"""

match = re.search(r"(##\s*Inbox[ \t]*\n)(.*?)(?=\n##\s*|\Z)", content, re.IGNORECASE | re.DOTALL)
print("Match found:", bool(match))
if match:
    print("Group 1:", repr(match.group(1)))
    print("Group 2:", repr(match.group(2)))
    after = content[match.end(2):]
    print("After:", repr(after))
