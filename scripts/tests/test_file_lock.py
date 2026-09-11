"""Tests for core/file_lock.py (CrossProcessFileLock)."""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.file_lock import CrossProcessFileLock


def test_file_lock_basic_acquire_release(tmp_path):
    """Test basic lock acquisition and release."""
    lock_path = tmp_path / "test.lock"
    lock = CrossProcessFileLock(lock_path, timeout=2.0)

    assert lock.acquire() is True
    assert lock.fd is not None
    assert lock_path.exists()

    lock.release()
    assert lock.fd is None


def test_file_lock_context_manager(tmp_path):
    """Test using CrossProcessFileLock as a context manager."""
    lock_path = tmp_path / "context.lock"

    with CrossProcessFileLock(lock_path, timeout=2.0) as lock:
        assert lock.fd is not None
        assert lock_path.exists()

    assert lock.fd is None


def test_file_lock_thread_exclusion(tmp_path):
    """Test that two threads cannot hold the lock on the same path simultaneously."""
    lock_path = tmp_path / "exclusive.lock"
    lock1 = CrossProcessFileLock(lock_path, timeout=1.0)
    lock2 = CrossProcessFileLock(lock_path, timeout=0.1)

    assert lock1.acquire() is True

    acquired2 = []

    def try_lock2():
        res = lock2.acquire()
        acquired2.append(res)
        if res:
            lock2.release()

    t = threading.Thread(target=try_lock2)
    t.start()
    t.join()

    # Second thread should fail to acquire within 0.1s
    assert acquired2 == [False]

    lock1.release()
    assert lock1.fd is None


def test_file_lock_thread_handover(tmp_path):
    """Test that after thread 1 releases, thread 2 can acquire the lock."""
    lock_path = tmp_path / "handover.lock"
    lock1 = CrossProcessFileLock(lock_path, timeout=1.0)
    lock2 = CrossProcessFileLock(lock_path, timeout=1.0)

    assert lock1.acquire() is True

    acquired2 = []

    def hold_and_release():
        time.sleep(0.05)
        lock1.release()

    def wait_and_acquire():
        res = lock2.acquire()
        acquired2.append(res)
        if res:
            lock2.release()

    t1 = threading.Thread(target=hold_and_release)
    t2 = threading.Thread(target=wait_and_acquire)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert acquired2 == [True]


def test_file_lock_different_paths_concurrent(tmp_path):
    """Test that locks on different paths do not block each other."""
    path1 = tmp_path / "lock1.lock"
    path2 = tmp_path / "lock2.lock"

    lock1 = CrossProcessFileLock(path1, timeout=1.0)
    lock2 = CrossProcessFileLock(path2, timeout=1.0)

    assert lock1.acquire() is True
    assert lock2.acquire() is True

    lock1.release()
    lock2.release()


def test_file_lock_timeout_error_in_context_manager(tmp_path):
    """Test TimeoutError is raised when context manager fails to acquire."""
    lock_path = tmp_path / "timeout.lock"
    lock1 = CrossProcessFileLock(lock_path, timeout=1.0)
    assert lock1.acquire() is True

    def attempt():
        with CrossProcessFileLock(lock_path, timeout=0.1):
            pass

    t_error = []

    def thread_attempt():
        try:
            attempt()
        except TimeoutError as e:
            t_error.append(e)

    t = threading.Thread(target=thread_attempt)
    t.start()
    t.join()

    assert len(t_error) == 1
    lock1.release()


def test_file_lock_creates_parent_dirs(tmp_path):
    """Test lock creation handles nested non-existent directory."""
    nested_lock = tmp_path / "nested" / "sub" / "deep.lock"
    with CrossProcessFileLock(nested_lock, timeout=1.0) as lock:
        assert lock.fd is not None
        assert nested_lock.exists()


def test_file_lock_already_acquired_idempotent(tmp_path):
    """Test calling acquire() again on already held lock returns True without deadlock."""
    lock_path = tmp_path / "idempotent.lock"
    lock = CrossProcessFileLock(lock_path, timeout=1.0)
    assert lock.acquire() is True
    assert lock.acquire() is True
    lock.release()
    assert lock.fd is None


def test_file_lock_multiprocess_exclusion(tmp_path):
    """Test OS-level locking across separate Python interpreter processes."""
    import subprocess
    lock_path = tmp_path / "proc_exclusive.lock"
    runner_py = tmp_path / "runner.py"
    runner_py.write_text("""
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from core.file_lock import CrossProcessFileLock

lock_path = sys.argv[2]
delay = float(sys.argv[3])
hold = float(sys.argv[4])

time.sleep(delay)
t0 = time.time()
with CrossProcessFileLock(lock_path, timeout=4.0):
    elapsed = time.time() - t0
    print(f"acquired:{elapsed:.3f}", flush=True)
    time.sleep(hold)
print("released", flush=True)
""")

    scripts_dir = str(Path(__file__).parent.parent)
    # Proc 1 acquires at 0.0s, holds for 0.4s
    p1 = subprocess.Popen(
        [sys.executable, str(runner_py), scripts_dir, str(lock_path), "0.0", "0.4"],
        stdout=subprocess.PIPE,
        text=True,
    )
    # Proc 2 attempts to acquire at 0.1s, must wait until Proc 1 releases (~0.3s delay)
    p2 = subprocess.Popen(
        [sys.executable, str(runner_py), scripts_dir, str(lock_path), "0.1", "0.1"],
        stdout=subprocess.PIPE,
        text=True,
    )

    out1, _ = p1.communicate()
    out2, _ = p2.communicate()

    assert p1.returncode == 0
    assert p2.returncode == 0
    assert "acquired:" in out1
    assert "acquired:" in out2

    # Extract wait duration for Proc 2
    for line in out2.splitlines():
        if line.startswith("acquired:"):
            wait_time = float(line.split(":")[1])
            assert wait_time >= 0.20, f"Proc 2 was not blocked by Proc 1: wait_time={wait_time}"

