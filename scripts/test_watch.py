import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class Handler(FileSystemEventHandler):
    def on_created(self, event):
        print(f'Created: {event.src_path}')
    def on_modified(self, event):
        print(f'Modified: {event.src_path}')

observer = Observer()
observer.schedule(Handler(), path='d:/VvC_Notes/test_junction', recursive=True)
observer.start()

# Wait 1s, then create a file in the TARGET directory (like GDrive would)
time.sleep(1)
with open('G:/My Drive/VvC_Vault/test_junction_file.txt', 'w') as f:
    f.write('hello')

time.sleep(2)
observer.stop()
observer.join()
