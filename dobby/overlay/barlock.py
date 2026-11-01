"""Which overlay helper owns the idle control bar and menu bar icon."""

from __future__ import annotations

import fcntl
import os

BAR_LOCK = os.path.expanduser("~/.dobby/overlay/bar.lock")


class BarOwner:
    """Several Dobby servers can run at once (one per app or session), each
    with its own helper. Only the helper holding this lock shows the idle
    "ready" bar and the menu bar icon; the others show their bar only while
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
