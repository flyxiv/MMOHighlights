import subprocess
import sys
import time

import pytest

CHILD_SLEEPS = "import time; time.sleep(60)"

# The parent starts a long-running child, binds it, prints its pid, then exits abruptly.
PARENT = f"""
import os, subprocess, sys
from app.recorder.procgroup import bind_to_parent
child = subprocess.Popen([sys.executable, "-c", {CHILD_SLEEPS!r}],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
bind_to_parent(child.pid)
print(child.pid, flush=True)
os._exit(1)
"""


def _alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, errors="replace"
    ).stdout
    return str(pid) in out


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only behaviour")
def test_child_dies_when_parent_crashes():
    parent = subprocess.run([sys.executable, "-c", PARENT], capture_output=True, text=True, timeout=30)
    pid = int(parent.stdout.strip())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = _alive(pid)
    if alive:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    assert not alive, "the child outlived its crashed parent"
