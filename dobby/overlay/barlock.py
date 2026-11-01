"""Which overlay helper owns the idle control bar (and menu bar icon, if on)."""

from __future__ import annotations

import fcntl
import os

BAR_LOCK = os.path.expanduser("~/.dobby/overlay/bar.lock")


class BarOwner:
    """Several Dobby servers can run at once (one per app or session), each
    with its own helper. Only the helper holding this lock shows the idle
    "ready" bar (and the menu bar icon, if on); the others show their bar only while
    they work, are paused or ask Allow/Deny. The lock is released when the
    helper exits, and another helper takes over on its next try."""

    def __init__(self, path: str = BAR_LOCK) -> None:
        self.path = path
        self.fh = None

    @property
    def owned(self) -> bool:
        return self.fh is not None

    def try_acquire(self) -> bool:
        if self.fh is not None:
            return True
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fh = open(self.path, "a+")
        except OSError:
            return False
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True

    def release(self) -> None:
        if self.fh is not None:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except OSError:
                pass
            self.fh = None


def waiting_dir(bar_lock: str = BAR_LOCK) -> str:
    """Where helpers mark that their AI waits for a wake (next to the bar lock)."""
    return os.path.join(os.path.dirname(bar_lock), "waiting")


def mark_waiting(path: str, pid: int, on: bool) -> None:
    """Create or remove ``<path>/<pid>`` while this helper's AI waits."""
    marker = os.path.join(path, str(pid))
    try:
        if on:
            os.makedirs(path, exist_ok=True)
            open(marker, "a").close()
        else:
            os.unlink(marker)
    except OSError:
        pass


def others_waiting(path: str, own_pid: int) -> bool:
    """True if another live helper's AI waits for a wake. Drops stale markers."""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    found = False
    for name in names:
        if not name.isdigit() or int(name) == own_pid:
            continue
        try:
            os.kill(int(name), 0)
        except ProcessLookupError:
            mark_waiting(path, int(name), False)
            continue
        except OSError:
            pass  # alive, owned by someone else
        found = True
    return found
