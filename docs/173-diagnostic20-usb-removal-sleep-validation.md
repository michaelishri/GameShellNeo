# Diagnostic.20: USB removal during sleep

5 October 2026; capture timestamps are UTC. NEO-117 and NEO-110.

One attended USB-removal-during-sleep case passes with diagnostic.20's supply
wake policy. The owner heard the warning, unplugged once during darkness as
instructed, and confirmed the normal dim console returned. The trace records
RTC wake; Wi-Fi recovered and the original keypad connection survived. Both
the original result and a subsequent read-only inspection report USB absent,
with the gadget disconnected and battery discharging.

Together with [report 171](171-diagnostic20-usb-attachment-sleep-validation.md),
this establishes one passing case in each cable direction on this image.
Repetition and charging through the sleep interval remain open. No energy or
general sleep-reliability claim follows from these individual cases.

## Admission and original evidence

[Report 172](172-diagnostic20-usb-removal-preparation.md) records the independent
seven-stage debug baseline, owner-confirmed warnings/display and passing awake
removal rehearsal. The owner then gave fresh readiness for one actual sleep:
wait ten seconds after darkness, unplug once and leave USB absent. If the
screen returned first, the instruction was to leave the cable connected.

The saved task was submitted once:

```sh
task device:sleep-cable-remove \
  QUALIFICATION=.local/neo117-remove-debug-history.json \
  REHEARSAL=c7f482d799ba4deb89990207953877b1 \
  CABLE_ACTION=1 ATTENDED=1
```

| Identity | Value |
| --- | --- |
| Host source checkpoint | `b8ebf39`, `work/power-insertion-wake` |
| Image / kernel | `0.1.0-diagnostic.20` / `6.18.54-gameshellneo19` |
| Boot | `86a43151-7d9b-44bd-83b3-cc1b9fcff215` |
| Run | `a7790eb5c6404dfd9765ef7ca30746c0` |
| Original capture beneath this worktree | `.local/diagnostics/20261005T061941.834263Z/result.json` |
| Original result SHA-256 | `d4f2d85750f8adbc403f462fefe5a60c7c315af6a5b913597a794659c1c6d6ed` |

The controller exited zero, collected the complete/passed original over Wi-Fi,
and independently verified Wi-Fi SSH on the same boot. USB proof is deliberately
false for the absent-cable endpoint. No collection error was recorded, and no
sleep resubmission, service restart, driver reload or network repair was used.
This independent baseline is now consumed and must not be replayed.

## Automated outcome

| Check | Observation |
| --- | --- |
| Actual sleep | One s2idle boundary, `pm_test=none`; ordered late/noirq phases and RSB callbacks |
| Submitted interval | 31.773 seconds BOOTTIME |
| In-loop s2idle trace | 29.366 seconds MONOTONIC |
| Alarm interval | 32.501 seconds from arming to userspace return |
| Wake | IRQ31; RTC count 6 → 7; one event with flags `0xa0` |
| Initial/entry cable state | UDC configured, carrier 1, PHY USB 1/HOST 0, both supplies present/online |
| Final cable state | UDC not attached, carrier 0, PHY USB/HOST 0, both supplies absent/offline |
| Wake policy | MUSB and both supply controls disabled before/after |
| PM counters | Success 23 → 24; fail and every failure counter zero |
| Input/memory | Original keypad handle retained without disconnect, errors or held keys; memory check passes |
| SDIO | Active/forbidden, control `on`, usage 2 unchanged |
| POWER/restoration | No POWER activity; checked handback, original policy restored, no retained diagnostic owner/drop-in |
| Audio/display | Level-5, 1,000 ms warning before entry; mixer and idle amplifiers restored; brightness 1, backlight power 0 afterward |
| Battery after resume | Valid telemetry, 99%, Discharging, 4.0216 V |

All cable-handler deltas are zero: ACIN/VBUS plugin remain 0 and removal remain
1. This satisfies the prospective `masked-cable-v2` policy: requested removal
dispatch may be zero or one, while opposite events must remain unchanged.
The RTC event, wake IRQ, source identity and correct electrical-state readings
remain required. A masked status can be acknowledged without a nested handler
dispatch; these counters do not timestamp physical cable separation.

## Owner observation and preserved absent state

The owner answered **"Yes—unplugged during darkness; console normal"** to the
question confirming the long warning, one unplug after ten seconds of darkness
before return, and normal dim-console recovery. The separate report preserves
that observation without rewriting the device result:

```sh
task report:sleep-cable \
  RESULT=.local/diagnostics/20261005T061941.834263Z/result.json \
  OBSERVATION=during-dark DISPLAY=normal
task device:sleep-connection-inspect ROUTE=wifi
task report:sleep-evidence \
  RESULT=.local/diagnostics/20261005T061941.834263Z/result.json
```

| Evidence beneath `.local/diagnostics/` | SHA-256 |
| --- | --- |
| `20261005T061941.834263Z/result-cable-observation.json` | `7fff370975a96b9de86da2ce6e7a907b79c04df6281471737c46f449b3168bc9` |
| `20261005T062215.755209Z/connection-inspection.json` | `6d4390601517d4a4d9673732d98f345799c43aec54273e288cc13cdef6eb337a` |
| `20261005T062215.767931Z/sleep-evidence.json` | `c11acb43e425f50aec2cc6fa8968da323e6636dd2270b6c2d1e7aadbd848deb7` |

The observer report passes the attended-case criteria. The strict absent-state
validator accepts the independent inspection on the original boot, with all
cable counters unchanged. The offline RTC/trace/clock assessment also passes.
All three were saved before requesting a separate awake reconnect.

## Separate reconnect and remaining work

After the absent-state evidence was saved, the owner performed the requested
single reconnect and 30-second wait, answering **"USB reconnected; console
normal."** Two separate read-only checks then passed:

```sh
task device:pm-inspect
task device:sleep-connection-inspect ROUTE=wifi
```

| Route / evidence beneath `.local/diagnostics/` | SHA-256 |
| --- | --- |
| USB PM/health: `20261005T062423.676950Z/inspection.json` | `d32a8d9b0f6f8ebd733c7d01a6de9174de48e0fe6e718c18b79a1910cbbe4fbb` |
| Wi-Fi connection: `20261005T062423.672446Z/connection-inspection.json` | `dbfa719d9e9e37dea2bd9996f0611fb113df3e38909a4491fc4d7719fd3eafc2` |

Both reach the original boot. The strict health and present-state validators
pass: configured UDC, carrier 1, PHY USB 1/HOST 0, both supplies present/online,
PM24/0 and SDIO usage 2. All three wake controls remain disabled. Each AC/VBUS
insertion count advances from 0 to 1; removal counts stay 1. Thus awake cable
detection still works with system wake disabled. The original sleep-result
hash is unchanged, and its absent-cable USB proof remains false; this later
reconnection is separate evidence.

Battery telemetry is 99%/Charging after reconnection. The 4.2559 V reading
repeats the existing uncalibrated charging-voltage observation under NEO-10;
no charging setting was changed. USB remains connected, with normal dim console
and no further sleep test running.

The BOOTTIME/MONOTONIC gap is below sampling uncertainty, with no observed
timekeeping-freeze pairs. These results do not qualify CPU/DRAM retention,
battery savings, precise cable-edge timing or sub-second production wake
latency. The battery percentage change across external-power removal is not an
energy measurement. Ordinary automatic/button sleep remains disabled.

NEO-117 and NEO-110 remain in progress for repeat coverage and the separate
charging-through-sleep question. Historical failures and consumed baselines
remain intact; further physical tests require a separately described session.
