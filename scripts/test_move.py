import shutil
from pathlib import Path
with open('d:/VvC_Notes/test_j1/file.txt', 'w') as f:
    f.write('hello')
try:
    shutil.move('d:/VvC_Notes/test_j1/file.txt', 'd:/VvC_Notes/test_j2/file.txt')
    print('Move successful')
except Exception as e:
    print(f'Move failed: {e}')
