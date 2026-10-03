"""Process-owned locks and staged database publication."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time

LOCK_TIMEOUT = 30.0


class IndexBusyError(RuntimeError):
    """A reader or publisher could not acquire the database gate."""


class FileLock:
    def __init__(self, path, timeout=0):
        self.path = Path(path)
        self.timeout = timeout
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise IndexBusyError('Index busy; retry after active readers or management operations finish.') from exc
                    time.sleep(min(.05, remaining))
            self.stream = stream
            return self
        except BaseException:
            stream.close()
            raise

    def close(self):
        if self.stream is not None:
            stream, self.stream = self.stream, None
            # Closing the descriptor releases OS locks, including after crashes.
            stream.close()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.close()


def reader_lock(db_path):
    if os.name != 'nt':
        return None
    return FileLock(str(Path(db_path).resolve()) + '.publish.lock', LOCK_TIMEOUT).acquire()


@contextmanager
def management_lock(db_path):
    lock = FileLock(str(Path(db_path).resolve()) + '.lock')
    try:
        lock.acquire()
    except IndexBusyError as exc:
        raise RuntimeError('Another index/embed operation is active; retry after it completes') from exc
    try:
        yield
    finally:
        lock.close()


def publish_database(stage, target):
    """No database handles may remain open in the publishing process."""
    target = Path(target).resolve()
    if os.name != 'nt':
        os.replace(stage, target)
        return
    deadline = time.monotonic() + LOCK_TIMEOUT
    with FileLock(str(target) + '.publish.lock', LOCK_TIMEOUT):
        while True:
            try:
                os.replace(stage, target)
                return
            except OSError as exc:
                if getattr(exc, 'winerror', None) not in (5, 32, 33):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IndexBusyError('Index publication blocked by an open file; close older runtimes and retry.') from exc
                time.sleep(min(.05, remaining))
