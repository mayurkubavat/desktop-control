# Shared control: two AI agents, one desktop

Each AI client (Claude Code, Claude Desktop, Antigravity) starts its own Dobby
server. Shared control makes them take turns on the mouse and keyboard.

## How it works

- Every acting HAL call (click, move, drag, scroll, type, key, hotkey, focus)
  takes a lease stored in `~/.dobby/control/lease.json`, changed only under an
  OS file lock. Reading the screen never needs the lease.
- A whole tool call is one turn: the first action takes the lease and it stays
  busy until the tool returns, so another agent never cuts in between a click
  and the typing that follows.
- With nobody waiting, the holder keeps control. When another agent waits, the
  holder hands over between steps after `release_control`, after 10 s idle, or
  after a 60 s slice. Higher `DOBBY_AGENT_PRIORITY` wins the queue; waiting time
  ages priority up so nobody starves. `DOBBY_CONTROL_PREEMPT=1` lets higher
  priority take over at the next step boundary.
- A holder whose process died loses the lease at once.
- After a handoff, if the other agent acted since this agent last read the
  screen, the first action is skipped with "look again" (like a take-over).
- The overlay ignores synthetic input from every registered Dobby process
  (`~/.dobby/control/agents/<pid>.json`), so two agents no longer pause each
  other. While queued, the overlay shows "Waiting for <agent>".
- The person still outranks everyone: take-over, Pause and Stop work as before.
  Turbo never skips the lease.

## Dobby picker (control bar ▾)

When more than one Dobby runs, the ▾ menu on the control bar lists them under
"Dobbys", each with its state (this bar, in control, waiting, paused). Each
entry's submenu pauses or resumes, or stops, just that Dobby; "All Dobbys"
pauses or resumes every one. Commands go through
`~/.dobby/control/commands/<pid>.json`, which each Dobby checks before every
action. A paused Dobby lets go of a turn it held between steps, so the others
keep working, and looks again after Resume if they acted meanwhile. It gives up
after 10 minutes paused.

## Tools

`control_status`, `request_control(max_wait_s)`, `release_control`,
`hold_control(seconds)` (capped at 120 s). All are in the core profile.

## Configuration (per client, in its MCP server `env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOBBY_AGENT_NAME` | MCP client name, else `Dobby-<pid>` | Name shown to the other agent and as the overlay label |
| `DOBBY_AGENT_PRIORITY` | 0 | Higher goes first in the queue |
| `DOBBY_CONTROL` | on (off under pytest and replay) | `0` disables the lease |
| `DOBBY_CONTROL_IDLE_GRACE` | 10 | Seconds idle before a waiter may take over |
| `DOBBY_CONTROL_SLICE` | 60 | Longest hold while someone waits |
| `DOBBY_CONTROL_MAX_WAIT` | 45 | How long a tool waits before reporting who has control |
| `DOBBY_CONTROL_HOLD_CAP` | 120 | Upper bound for `hold_control` |
| `DOBBY_CONTROL_PREEMPT` | off | Priority preemption at step boundaries |
| `DOBBY_CONTROL_DIR` | `~/.dobby/control` | Lease and registry location |
