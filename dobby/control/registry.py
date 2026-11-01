"""Which Dobby agents are running, by pid.

Every Dobby server writes ``agents/<pid>.json`` (name, priority, start time).
The overlay helper reads it so input from ANY Dobby process counts as an
agent, not as the person taking over. Without this, two agents would keep
pausing each other.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from .lease import pid_alive


def agents_dir(root: Path) -> Path:
    return Path(root) / "agents"


def register(root: Path, agent_id: str, name: str, pid: int, priority: int = 0) -> Path:
    d = agents_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{pid}.json"
    tmp = d / f".{pid}.tmp"
    tmp.write_text(json.dumps({"id": agent_id, "name": name, "pid": pid, "priority": priority,
                               "started": time.time()}), encoding="utf-8")
    os.replace(tmp, path)
    return path


def unregister(root: Path, pid: int) -> None:
    try:
        (agents_dir(root) / f"{pid}.json").unlink()
    except OSError:
        pass


def list_agents(root: Path) -> List[Dict[str, object]]:
    out = []
    d = agents_dir(root)
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            pid = int(rec.get("pid", 0))
        except (OSError, ValueError, AttributeError):
            continue
        if pid_alive(pid):
            out.append(rec)
    return out


class AgentPidCache:
    """Cheap repeated lookups of live Dobby pids (refreshed at most every ``ttl`` s)."""

    def __init__(self, root: Path, ttl: float = 1.0) -> None:
        self.root = Path(root)
        self.ttl = ttl
        self._pids: Set[int] = set()
        self._at: Optional[float] = None

    def pids(self) -> Set[int]:
        now = time.monotonic()
        if self._at is None or now - self._at >= self.ttl:
            self._at = now
            try:
                self._pids = {int(r["pid"]) for r in list_agents(self.root)}
            except Exception:  # noqa: BLE001 - never break the input monitor
                pass
        return self._pids

    def __contains__(self, pid: int) -> bool:
        return pid in self.pids()
