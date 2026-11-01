"""X11 backend loader. Native libraries are imported by linux.py on first use."""

from __future__ import annotations


def build_hal():
    from dobby.hal.linux import LinuxHAL

    return LinuxHAL()
