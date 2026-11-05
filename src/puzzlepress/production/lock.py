"""One production writer per output directory, safe across crashes.

The lock is an operating-system lock on `.<output>.produce.lock` beside the output
(`fcntl.flock` on POSIX, `msvcrt.locking` on Windows). The kernel releases it when
the holding process exits for any reason, so a crashed run never blocks the next
one, and a lock held by a live process is never taken: that run is active and a
second one is refused. The file also records who holds it (lock version, process
ID, host name, start time, a random token) for messages.

When the file exists but nobody holds the lock, the earlier run ended without
removing it. It is reclaimed only when its record says it was written on this
host by this lock version: then the operating system's answer is authoritative.
A record from another host (a shared drive, where another computer may still be
running), or one that is empty or unreadable (an earlier PuzzlePress version that
used the file alone as the lock, or a crash while writing the record) cannot be
attributed safely and is refused with the file's path, never removed.
"""

import json
import os
import secrets
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import ProjectError, ValidationIssue

LOCK_VERSION = 1
# Windows locks a byte range; locking one byte far past the record keeps the record
# readable by the process that is refused.
_WINDOWS_LOCK_OFFSET = 1 << 30
_RECORD_LIMIT = 4096
_BINARY = getattr(os, "O_BINARY", 0)


@dataclass(frozen=True)
class LockRecord:
    pid: int
    host: str
    started: str
    token: str
    released: bool = False  # Written by a holder that finished but could not remove it.

    def describe(self) -> str:
        return f"process {self.pid} on {self.host}, started {self.started}"


@dataclass(frozen=True)
class HeldLock:
    path: Path
    record: LockRecord
    recovered: LockRecord | None  # The abandoned lock this run reclaimed, if any.


def _refuse(message: str) -> ProjectError:
    return ProjectError((ValidationIssue("output", "production_in_progress", message),))


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_record(fd: int) -> tuple[LockRecord | None, bool]:
    """(record, empty): the parsed record, and whether the file held nothing at all."""
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, _RECORD_LIMIT)
    if not raw.strip(b"\0 \r\n\t"):
        return None, True
    try:
        data = json.loads(raw.rstrip(b"\0").decode("utf-8"))
        if not isinstance(data, dict) or data.get("lock_version") != LOCK_VERSION:
            return None, False
        record = LockRecord(
            int(data["pid"]),
            str(data["host"]),
            str(data["started"]),
            str(data["token"]),
            data.get("released") is True,
        )
    except (UnicodeError, ValueError, KeyError, TypeError):
        return None, False
    return record, False


def read_lock(path: Path) -> LockRecord | None:
    """The record in a lock file, for messages and tests; None when unreadable."""
    try:
        fd = os.open(path, os.O_RDONLY | _BINARY)
    except OSError:
        return None
    try:
        return _read_record(fd)[0]
    except OSError:
        return None
    finally:
        os.close(fd)


def lock_held(path: Path) -> bool:
    """Whether a live process holds the production lock at `path` right now.

    Probes by taking and at once releasing the lock, never waiting and never writing
    or removing the file. A run that tries to start during the probe's instant is
    refused as if another run were active (it reports so and can be started again),
    so Studio probes only for jobs whose worker it did not start itself.
    """
    try:
        fd = os.open(path, os.O_RDWR | _BINARY)
    except FileNotFoundError:
        return False
    except OSError:
        return True  # Unreadable: cannot show it is free, so treat it as held.
    try:
        if not _try_lock(fd):
            return True
        _unlock(fd)
        return False
    finally:
        os.close(fd)


def _same_file(fd: int, path: Path) -> bool:
    try:
        return os.path.samestat(os.fstat(fd), os.stat(path))
    except OSError:
        return False


def _write_record(fd: int, record: LockRecord) -> None:
    data: dict[str, object] = {
        "lock_version": LOCK_VERSION,
        "pid": record.pid,
        "host": record.host,
        "started": record.started,
        "token": record.token,
    }
    if record.released:
        data["released"] = True
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(data, sort_keys=True).encode("utf-8"))
    os.fsync(fd)


@contextmanager
def production_lock(path: Path) -> Iterator[HeldLock]:
    """Hold the production lock at `path` for the duration of the block."""
    host = socket.gethostname()
    for _ in range(5):
        # Knowing whether this call created the file tells a fresh lock apart from an
        # empty one an earlier run left behind.
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | _BINARY, 0o644)
            existed = False
        except FileExistsError:
            try:
                fd = os.open(path, os.O_RDWR | _BINARY)
            except FileNotFoundError:
                continue  # Its holder just removed it; try to create it again.
            existed = True
        if not _try_lock(fd):
            try:
                holder, _ = _read_record(fd)
            except OSError:
                holder = None
            os.close(fd)
            who = holder.describe() if holder else "another process"
            raise _refuse(
                f"A production run for this output is active ({who}). Wait for it to "
                f"finish, then run again. Lock: {path}"
            )
        # POSIX: the file may have been unlinked by its previous holder between our
        # open and our lock; such a lock guards nothing, so open the path again.
        if sys.platform != "win32" and not _same_file(fd, path):
            os.close(fd)
            continue
        break
    else:
        raise _refuse(f"Could not settle the production lock {path}; run again.")
    try:
        previous, empty = _read_record(fd)
        if existed and (previous is None or previous.host != host):
            reason = (
                f"was written on another computer ({previous.host}), which may still be "
                "producing into this shared folder"
                if previous is not None
                else "is empty, so it may belong to an earlier PuzzlePress version still running"
                if empty
                else "is not a lock record PuzzlePress can read"
            )
            raise _refuse(
                f"The production lock {path} {reason}. Its owner cannot be confirmed, so it "
                "is left in place. If no production run is active, delete that file and run "
                "again."
            )
        record = LockRecord(
            os.getpid(),
            host,
            datetime.now(UTC).replace(microsecond=0).isoformat(),
            secrets.token_hex(8),
        )
        _write_record(fd, record)
    except BaseException:
        _unlock(fd)
        os.close(fd)
        raise
    try:
        abandoned = previous if existed and previous and not previous.released else None
        yield HeldLock(path, record, abandoned)
    finally:
        if sys.platform == "win32":
            # Mark the record released and unlock; the file stays if another process
            # has it open (it then holds the lock or is about to try), which the
            # released record makes harmless.
            try:
                _write_record(fd, LockRecord(record.pid, host, record.started, record.token, True))
            except OSError:
                pass
            _unlock(fd)
            os.close(fd)
            try:
                os.unlink(path)
            except OSError:
                pass
        else:
            # Unlink while holding the lock: a waiter that opened this file notices
            # (`_same_file`) and opens the path again.
            try:
                os.unlink(path)
            except OSError:
                pass
            _unlock(fd)
            os.close(fd)
