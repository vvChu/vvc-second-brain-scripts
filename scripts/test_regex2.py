import re

content = """# Brain Dump (Inbox)

## Inbox

## Processed
- [[link1]]"""

match = re.search(r"(##\s*Inbox\s*\n)(.*?)(?=\n##\s*|\Z)", content, re.IGNORECASE | re.DOTALL)
print("Group 1:", repr(match.group(1)))
print("Group 2:", repr(match.group(2)))
