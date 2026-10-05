# Diagnostic.20 attended debug qualification

5 October 2026; capture timestamps are UTC. NEO-117.

The first freezer, driver and late/noirq debug checks pass on diagnostic.20. Both SSH
routes recovered, the original keypad connection survived the driver/platform cycles,
and the MUSB/AC/USB supply wake policies stayed disabled. PM successes advanced
from zero to three with all failure counters zero; SDIO usage stayed at 2.
The owner confirmed a clear driver warning and normal display return, then
gave fresh readiness for late/noirq. Confirmation of that return and readiness
for four repeats are pending.
No actual sleep has run on this image and no further screen test is running.

[Report 167](167-diagnostic20-installation-and-awake-checks.md) records verified
installation and awake admission. The image is `0.1.0-diagnostic.20`, running
the unchanged `6.18.54-gameshellneo19` kernel on boot
`86a43151-7d9b-44bd-83b3-cc1b9fcff215`. The host source checkpoint is `6dcdd77`
on `work/power-insertion-wake`.

## Attended debug checks

The owner explicitly answered **"Ready—I'm watching and listening"** for the
freezer check followed by one driver cycle. The instructions were to leave USB
connected, the headphone socket empty and controls untouched, and listen for
the long warning before the dark interval. The first original result was
reviewed before the driver command was submitted; neither was resubmitted.
The owner then replied **"Warning clear; console normal; ready for late/noirq"**
before the first platform command was submitted.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
```

Each private capture is beneath this worktree's `.local/diagnostics/`, with
the original result in `cycle-1/result.json`.

| Stage | Capture | Run ID | Stage seconds | PM successes afterward |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261005T044559.767673Z` | `501a752ddb7b4d68a6768620bc2a550c` | 5.531 | 1 |
| Driver | `20261005T044720.266020Z` | `01104798c62c48f0b184dcaac4818726` | 7.692 | 2 |
| Late/noirq 1 | `20261005T045009.354827Z` | `3b760e93e1fb4549ab70750ae5f6f444` | 7.862 | 3 |

All three controllers exited zero, with `event=complete`, `passed=true`, original
boot identity and independent USB/Wi-Fi SSH proofs. Process memory and POWER
ownership/handoff checks passed without key events. PM failure counters remain
zero, the screen brightness returns to 1 and ordinary sleep stays disabled.
The three wake controls remain disabled in both before/after snapshots.

The driver/platform traces retained the original keypad handle without a disconnect,
hangup or held key. Keypad and Wi-Fi traces have no recorded loss and restore
correctly. Wi-Fi SDIO remains active, control `on`, runtime forbidden, usage 2.
These observations include the artificial five-second debug wait and do not
measure production resume latency or enter real sleep.
The platform trace contains all four ordered late/noirq phases and successful
RSB noirq suspend/resume callbacks.

Each driver/platform warning records one level-5, 1,000 ms `screen-blank` cue with playback
and mixer restoration passing, and both speaker/headphone amplifiers off before
PM entry. The freezer check does not blank the display and has no warning.
The driver cue and display were owner-confirmed; the first platform observation
is pending.

Both driver and platform collectors recorded `SSHException: No existing session`;
their local logs also contain protocol-banner timeouts. Each recovered the same
original completed run and then verified both SSH routes. No PM command was resubmitted,
and these transport errors do not identify a radio, USB-driver or Mac cause.
The existing transport-timing follow-up remains applicable.

Original result SHA-256 values, in table order:

```text
0544504a9c552a4ff0a0b5a2db844dd85104cd8d8e6034d3ce7340dc3153d27a
ee06e0c8d26da005f11e13018873c3da3510e333ea79968f1c96dec2835f7b46
52efd46e310d52782d499b7a2e899eddb19e84368cb57fd302aa350ccf836505
```

## Remaining admission and qualification

After the owner's observation and fresh readiness, repeat the one-cycle
`task device:pm-platform` command four times, reviewing each original result
before submitting the next. Each dark
interval requires the long warning and each result must pass before continuing.

An unchanged-cable RTC comparison and independent attachment baseline/rehearsal
remain ahead. Successful debug stages do not prove staying asleep and charging
on insertion, POWER wake, deep retention or energy savings. NEO-117 remains
in progress; the diagnostic.19 early-wake failure remains unchanged.
