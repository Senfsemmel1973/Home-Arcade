"""Bounded data storage. No shell, sudo, Apache edits or network listener.

Linux uses flock and no-follow descriptor opens. Windows lock is test support.
Parents belong to the dedicated application account, never shared upload dirs.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat
import time


class Refused(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def demand(condition, message, status=400):
    if not condition:
        raise Refused(message, status)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + '\n').encode()


def safe_parents(path):
    p = Path(path).absolute()
    for q in [p, *p.parents]:
        if q.exists() or q.is_symlink():
            s = q.lstat()
            demand(not stat.S_ISLNK(s.st_mode) and not (hasattr(q, 'is_junction') and q.is_junction()),
                   'Symbolische Links/Junctions sind nicht erlaubt.')
            if os.name == 'posix':
                demand(s.st_uid in (0, os.geteuid()) and not s.st_mode & 0o022,
                       'Unsicherer Eigentümer oder beschreibbarer Elternpfad.')
    return p


def read(path, limit=2097152):
    p = safe_parents(path)
    fd = os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        s = os.fstat(fd)
        demand(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= limit,
               'Nur begrenzte reguläre Dateien sind erlaubt.')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        demand(len(data) <= limit and os.fstat(fd).st_mtime_ns == s.st_mtime_ns,
               'Datei während des Lesens verändert.')
        return data
    finally:
        os.close(fd)


def sync_dir(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic(path, data, replace=True):
    import uuid
    p = Path(path)
    safe_parents(p.parent)
    temp = p.parent / ('.tmp-' + str(uuid.uuid4()))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            demand(not p.is_symlink(), 'Symlink-Ziel verweigert.')
            if p.exists():
                read(p)  # Reject hardlinks/special files before replacement.
            os.replace(temp, p)
        else:
            if os.name == 'posix':
                import ctypes
                libc = ctypes.CDLL(None, use_errno=True)
                result = libc.renameat2(-100, os.fsencode(temp), -100, os.fsencode(p), 1)
                if result:
                    err = ctypes.get_errno()
                    raise OSError(err, os.strerror(err))
            else:
                os.rename(temp, p)  # Windows rename refuses replacement.
        sync_dir(p.parent)
    finally:
        if temp.exists():
            temp.unlink()


@contextlib.contextmanager
def locked(path, timeout=5):
    safe_parents(Path(path).parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        st = os.fstat(fd)
        demand(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'Unsichere Lockdatei.')
        if os.name == 'nt':
            import msvcrt
            if st.st_size == 0:
                os.write(fd, b'0')
            def acquire():
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            def release():
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(fd, fcntl.LOCK_UN)
        until = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError:
                demand(time.monotonic() < until, 'Import belegt; bitte erneut versuchen.', 409)
                time.sleep(.02)
        try:
            yield
        finally:
            release()
    finally:
        os.close(fd)
