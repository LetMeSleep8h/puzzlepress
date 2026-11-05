"""The production lock: active runs refused, crashed runs reclaimed, unknown owners kept."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from puzzlepress.errors import ProjectError
from puzzlepress.production.lock import production_lock, read_lock

HOLDER = """
import os, sys, time
from pathlib import Path
from puzzlepress.production.lock import production_lock
lock, ready, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
with production_lock(lock):
    ready.write_text(str(os.getpid()), encoding="utf-8")
    if mode == "crash":
        os._exit(0)  # Dies holding the lock: no cleanup runs.
    while not (ready.parent / "release").exists():
        time.sleep(0.05)
"""


def hold(tmp_path: Path, lock: Path, mode: str) -> tuple[subprocess.Popen[bytes], int]:
    ready = tmp_path / f"ready-{mode}"
    process = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock), str(ready), mode])
    deadline = time.monotonic() + 60
    while not ready.exists() or not ready.read_text(encoding="utf-8"):
        assert process.poll() is None or mode == "crash", "holder exited early"
        assert time.monotonic() < deadline, "holder never took the lock"
        time.sleep(0.05)
    return process, int(ready.read_text(encoding="utf-8"))


def test_holding_records_the_owner_and_releasing_removes_the_file(tmp_path: Path) -> None:
    lock = tmp_path / ".out.produce.lock"
    with production_lock(lock) as held:
        record = read_lock(lock)
        assert record == held.record and record.pid == os.getpid()
        assert record.host == socket.gethostname() and held.recovered is None
    assert not lock.exists()
    with production_lock(lock):  # Reusable at once.
        pass


def test_an_active_run_in_another_process_is_refused(tmp_path: Path) -> None:
    lock = tmp_path / ".out.produce.lock"
    process, pid = hold(tmp_path, lock, "hold")
    try:
        with pytest.raises(ProjectError) as raised:
            with production_lock(lock):
                pass
        issue = raised.value.issues[0]
        assert issue.code == "production_in_progress"
        assert f"process {pid}" in issue.message and "active" in issue.message
        assert read_lock(lock).pid == pid  # Never taken or removed.
    finally:
        (tmp_path / "release").write_text("", encoding="utf-8")
        process.wait(timeout=60)
    with production_lock(lock) as held:  # Free once that run ends.
        assert held.recovered is None


def test_a_crashed_run_is_reclaimed_and_reported(tmp_path: Path) -> None:
    lock = tmp_path / ".out.produce.lock"
    process, pid = hold(tmp_path, lock, "crash")
    process.wait(timeout=60)
    assert lock.exists() and read_lock(lock).pid == pid  # Left behind by the crash.
    with production_lock(lock) as held:
        assert held.recovered is not None and held.recovered.pid == pid
        assert read_lock(lock).pid == os.getpid()
    assert not lock.exists()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", "empty"),
        (b"not json", "not a lock record"),
        (b'{"lock_version": 99, "pid": 1}', "not a lock record"),
        (
            json.dumps(
                {"lock_version": 1, "pid": 1, "host": "other-pc", "started": "t", "token": "x"}
            ).encode(),
            "another computer (other-pc)",
        ),
    ],
)
def test_an_owner_that_cannot_be_confirmed_is_never_removed(
    tmp_path: Path, content: bytes, reason: str
) -> None:
    lock = tmp_path / ".out.produce.lock"
    lock.write_bytes(content)
    with pytest.raises(ProjectError) as raised:
        with production_lock(lock):
            pass
    issue = raised.value.issues[0]
    assert issue.code == "production_in_progress" and reason in issue.message
    assert str(lock) in issue.message and "delete that file" in issue.message
    assert lock.read_bytes() == content


def test_a_released_record_is_not_reported_as_abandoned(tmp_path: Path) -> None:
    lock = tmp_path / ".out.produce.lock"
    record = {
        "lock_version": 1,
        "pid": 1,
        "host": socket.gethostname(),
        "started": "t",
        "token": "x",
        "released": True,
    }
    lock.write_text(json.dumps(record), encoding="utf-8")
    with production_lock(lock) as held:
        assert held.recovered is None


def test_word_search_production_takes_the_same_lock(tmp_path: Path) -> None:
    from puzzlepress.production.produce import produce
    from tests.helpers import DEMO

    output = tmp_path / "out"
    process, pid = hold(tmp_path, tmp_path / ".out.produce.lock", "hold")
    try:
        with pytest.raises(ProjectError) as raised:
            produce(DEMO, output)
        assert raised.value.issues[0].code == "production_in_progress"
        assert not output.exists()
    finally:
        (tmp_path / "release").write_text("", encoding="utf-8")
        process.wait(timeout=60)
    result = produce(DEMO, output)
    assert result.notes == () and (output / "production.json").is_file()
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".")) == []
