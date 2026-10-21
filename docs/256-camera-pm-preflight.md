# Camera-observed PM qualification: preflight stopped

10 October 2026. NEO-191, following NEO-189/190's authorized Mac camera workflow
and NEO-184's pending PM evidence qualification. **No PM cycle, screen blanking,
sound, reboot or physical action was performed.** Camera permission and readable
display observations work; an independent battery-service health failure stops
the planned debug sequence.

## Camera workflow adopted

The active `work/musb-restart-integration` branch now includes the owner's camera
tooling and instructions from main commits `ff27ea9` and `3ecaa0d`, imported as
`05d3826` and `3ece8f3`. The installed app's source identity matches, so it was
reused without rebuilding or another permission request. The main checkout's
uncommitted owner changes were preserved.

`task mac:camera-status` reports authorized permission without opening the camera.
`task mac:camera-capture` then saves a fresh 1920 × 1080 still. Direct visual
inspection shows an unobscured illuminated GameShell display with readable
console output, ending in the earlier `PM: suspend exit` message. This is a
baseline observation, not a newly observed resume or input-response test.
Both operations report successful completion and `camera_stopped: true`; the
successful downloaded captures are removed from the Mac by the existing helper.
Raw images remain private and ignored by Git.

The new authorization replaces human readiness/return confirmation for simple
screen observations with camera readiness and direct image inspection. A
bounded sequence must start before each authorized screen test. Video-only
evidence cannot confirm audible warnings, and it does not replace health,
network, input, timing or energy checks. Physical actions still require the
owner. The long warning remains part of the existing test commands.

## Independent health failure

USB and Wi-Fi inspections reach the same diagnostic.25 boot:
`2170b296-d964-4d16-bdb1-c135b0e7b812`, kernel `6.18.54-gameshellneo24`.
PM counters remain 53 successes / zero failures; brightness is 1 and
`bl_power=0`. The battery monitor is currently valid and reports 100%/Charging.
The protected kernel checkpoint retains its original 1,660-record boot anchor.

The existing PM admission validator rejects `services`: the battery service is
active but has `NRestarts=1`; every other monitored service has zero restarts.
The saved unit journal records an unhandled
`ValueError('non-increasing clock observation')` from `battery_guard.py`, at the
`finished = clocks()` call. The service exits and systemd starts it again about
ten seconds later. Its recorded restart is 9 October, 21:15:47 UTC, before this
camera/preflight session. The installed guard and unit hashes match the repo.

The relevant condition is `right < left` between two `time.monotonic_ns()`
reads bracketing BOOTTIME. The original exception did not record either raw
value, so the size and source of the regression are unknown. The active
clocksource is `arch_sys_counter`; `timer` is also listed as available. No
clocksource, counter, service policy or charging setting was changed.

This is a real admission failure, not a camera limitation. The planned freezer,
devices and five late/noirq checks remain unexecuted. The restart counter was
not cleared, and the device was not rebooted to bypass it. NEO-192 now tracks
preservation, bounded awake measurement, guard fault handling and the separate
underlying clock cause; it blocks NEO-191's PM qualification.

## Private evidence

Paths below are under the active worktree's ignored `.local/`:

| Path | Evidence |
| --- | --- |
| `diagnostics/20261009T212919.466316Z` | Camera authorization/status result |
| `diagnostics/20261009T212931.032675Z` | Fresh still, readiness, completion/shutdown and direct visual inspection |
| `diagnostics/20261009T212917.069846Z` | USB inspection, complete kernel checkpoint and service restart count |
| `diagnostics/20261009T212947.933584Z` | Independent Wi-Fi inspection of the same boot |
| `neo191-battery-journal.txt` | Original battery exception and restart log excerpt |
| `neo191-battery-unit.txt` | Current service PID, start time, result and restart count |
| `neo191-clocksource.txt` | Current/available clocksources |
| `neo191-battery-installed-hashes.txt` | Installed guard and unit identity |

The six imported camera tests pass. No camera timing is used as a latency or
power measurement. NEO-184's earlier awake smoke remains historical evidence;
no new debug acceptance or NEO-182 battery qualification follows from this
preflight. Resume the planned sequence only after the clock/service failure is
addressed, with a new health check and a readable camera baseline.
