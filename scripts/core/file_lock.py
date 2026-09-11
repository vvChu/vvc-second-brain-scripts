"""VvC Second Brain — Cross-Process & Cross-Thread File Lock.

Standard library only (msvcrt on Windows, fcntl on Unix, threading.Lock in-process).
Provides safe per-path concurrency controls.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

_logger = logging.getLogger("vvc.file_lock")


class CrossProcessFileLock:
    """Khóa tệp đa tiến trình và đa luồng sử dụng 100% thư viện chuẩn Python.
    Hỗ trợ Windows (msvcrt) và Unix (fcntl).
    """

    _master_lock = threading.Lock()
    _path_locks: dict[str, threading.Lock] = {}
    _global_lock = threading.Lock()  # Backward-compatibility alias

    def __init__(self, lock_path: Path | str, timeout: float = 15.0, delay: float = 0.05):
        self.lock_path = Path(lock_path).resolve()
        self.timeout = timeout
        self.delay = delay
        self.fd: int | None = None
        self._thread_acquired = False
        lock_key = str(self.lock_path).lower() if sys.platform == "win32" else str(self.lock_path)
        self._thread_lock = self._get_thread_lock(lock_key)

    @classmethod
    def _get_thread_lock(cls, path_key: str) -> threading.Lock:
        with cls._master_lock:
            if path_key not in cls._path_locks:
                cls._path_locks[path_key] = threading.Lock()
            return cls._path_locks[path_key]

    def acquire(self) -> bool:
        """Thử lấy khóa đa luồng và đa tiến trình.
        
        Returns:
            True nếu lấy được khóa, False nếu quá thời gian chờ (timeout).
        """
        # Nếu đã sở hữu khóa từ trước, trả về True ngay
        if self._thread_acquired and self.fd is not None:
            return True

        # 1. Khóa mức luồng trước để tránh xung đột nội bộ tiến trình trên cùng tệp khóa
        if not self._thread_lock.acquire(timeout=self.timeout):
            _logger.error(f"Thread lock acquisition timed out for {self.lock_path}")
            return False

        self._thread_acquired = True
        start_time = time.time()

        # Đảm bảo thư mục cha tồn tại
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        # 2. Khóa mức tiến trình (File lock hệ điều hành)
        while True:
            try:
                # Mở tệp khóa (tạo mới nếu chưa có)
                self.fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT)

                if sys.platform == "win32":
                    import msvcrt
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    # Thử khóa 1 byte đầu tiên (LK_NBLCK: chế độ không chặn)
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    # Khóa độc quyền không chặn trên Unix
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Khóa thành công!
                return True

            except (OSError, IOError):
                # Nếu khóa thất bại, đóng file descriptor ngay lập tức và thử lại
                if self.fd is not None:
                    try:
                        os.close(self.fd)
                    except OSError:
                        pass
                    self.fd = None

                # Kiểm tra quá thời gian chờ (Timeout)
                if time.time() - start_time > self.timeout:
                    if self._thread_acquired:
                        self._thread_lock.release()
                        self._thread_acquired = False
                    _logger.error(f"File lock acquisition timed out for {self.lock_path}")
                    return False

                time.sleep(self.delay)

    def release(self) -> None:
        """Giải phóng khóa mức tiến trình và mức luồng."""
        try:
            if self.fd is not None:
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        os.lseek(self.fd, 0, os.SEEK_SET)
                        msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.fd, fcntl.LOCK_UN)
                except OSError as e:
                    _logger.warning(f"Failed to unlock file {self.lock_path}: {e}")
                finally:
                    try:
                        os.close(self.fd)
                    except OSError:
                        pass
                    self.fd = None
        finally:
            if self._thread_acquired:
                self._thread_lock.release()
                self._thread_acquired = False

    def __enter__(self) -> CrossProcessFileLock:
        if not self.acquire():
            raise TimeoutError(f"Could not acquire lock on {self.lock_path} within {self.timeout}s")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
