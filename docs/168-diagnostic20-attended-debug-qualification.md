# Diagnostic.20 attended debug qualification

5 October 2026; capture timestamps are UTC. NEO-117.

One freezer, one driver and five late/noirq debug checks pass on diagnostic.20. Both SSH
routes recovered, the original keypad connection survived the driver/platform cycles,
and the MUSB/AC/USB supply wake policies stayed disabled. PM successes advanced
from zero to seven with all failure counters zero; SDIO usage stayed at 2.
The owner confirmed a clear driver warning and normal display return, then
gave fresh readiness for late/noirq. The first platform warning/display were
also confirmed normal before fresh readiness for four repeats. The final
four-cycle sound/display confirmation is pending.
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
After that result, the owner replied **"All normal; ready for four cycles"**
for the four-repeat batch. Each original result was reviewed before the next
one-cycle command was submitted.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# After fresh readiness, repeat the last command four times,
# reviewing each original result and both SSH proofs before continuing.
```

Each private capture is beneath this worktree's `.local/diagnostics/`, with
the original result in `cycle-1/result.json`.

| Stage | Capture | Run ID | Stage seconds | PM successes afterward |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261005T044559.767673Z` | `501a752ddb7b4d68a6768620bc2a550c` | 5.531 | 1 |
| Driver | `20261005T044720.266020Z` | `01104798c62c48f0b184dcaac4818726` | 7.692 | 2 |
| Late/noirq 1 | `20261005T045009.354827Z` | `3b760e93e1fb4549ab70750ae5f6f444` | 7.862 | 3 |
| Late/noirq repeat 1 | `20261005T045243.011281Z` | `6b30696f6596482b920c779afc4f2744` | 7.863 | 4 |
| Late/noirq repeat 2 | `20261005T045417.872315Z` | `1c94e866b46a45158717d9280673e0b6` | 7.942 | 5 |
| Late/noirq repeat 3 | `20261005T045547.500261Z` | `35a2bbe7553f4f268a748709e660b5ee` | 7.931 | 6 |
| Late/noirq repeat 4 | `20261005T045719.638005Z` | `9968b5330d9f4f059c8eda7ed14b3b50` | 8.010 | 7 |

All seven controllers exited zero, with `event=complete`, `passed=true`, original
boot identity and independent USB/Wi-Fi SSH proofs. Process memory and POWER
ownership/handoff checks passed without key events. PM failure counters remain
zero, the screen brightness returns to 1 and ordinary sleep stays disabled.
The three wake controls remain disabled in both before/after snapshots.

The driver/platform traces retained the original keypad handle without a disconnect,
hangup or held key. Keypad and Wi-Fi traces have no recorded loss and restore
correctly. Wi-Fi SDIO remains active, control `on`, runtime forbidden, usage 2.
These observations include the artificial five-second debug wait and do not
measure production resume latency or enter real sleep.
Every platform trace contains all four ordered late/noirq phases and successful
RSB noirq suspend/resume callbacks.

Each driver/platform warning records one level-5, 1,000 ms `screen-blank` cue with playback
and mixer restoration passing, and both speaker/headphone amplifiers off before
PM entry. The freezer check does not blank the display and has no warning.
The driver and first platform cue/display were owner-confirmed; final batch
observation is pending.

The driver, first platform and platform repeats 1, 3 and 4 recorded
`SSHException: No existing session`; their local logs also contain protocol-banner
timeouts. Each recovered the same
original completed run and then verified both SSH routes. No PM command was resubmitted,
and these transport errors do not identify a radio, USB-driver or Mac cause.
The existing transport-timing follow-up remains applicable.

Original result SHA-256 values, in table order:

```text
0544504a9c552a4ff0a0b5a2db844dd85104cd8d8e6034d3ce7340dc3153d27a
ee06e0c8d26da005f11e13018873c3da3510e333ea79968f1c96dec2835f7b46
52efd46e310d52782d499b7a2e899eddb19e84368cb57fd302aa350ccf836505
3b98b78b4d1b7348196738a357fc73026bc1bbc708c8cf6cc3fe2714ec6d519b
977f89e618aa9ec6b58555abd306734e90553821674dec107fef450e5d19d27a
3f1aca783ab19e17d1c5b94de6ea92bcd3feec557feabb6f42ce3e8452ece3d0
98ea4c3e3e827a48a91d97412b0a83dea237d77ac285c18ed5a66177d137bc7c
```

The saved `task check:sdio-ref-history -- --require-stable` command, given
exactly these seven result paths, confirms stable usage 2 and unchanged SDIO
runtime policy. Its summary is `.local/neo117-debug-history.json`, SHA-256:

```text
8b77eb77997d3d696fd280db362eb12da7b38084335832f0318ae9a993c68f17
```

Fresh read-only PM inspection `20261005T045906.970188Z/inspection.json`
passes the existing health validator with PM7/0, valid battery telemetry at
100%/Charging and unchanged wake controls. Its SHA-256 is
`6cc551a3930c95dc85bd6910020fe435101f9dd65eb83ec00aa61b3178bc7e70`.
The existing sleep controller's receipt validator accepted all seven originals
for the unchanged-USB profile, with zero prior sleep records in this new chain.
This was an offline admission check, not rehearsal or sleep submission.

## Remaining admission and qualification

The final display/sound confirmation, an awake rehearsal, an unchanged-cable
RTC comparison and an independent attachment baseline/rehearsal
remain ahead. Successful debug stages do not prove staying asleep and charging
on insertion, POWER wake, deep retention or energy savings. NEO-117 remains
in progress; the diagnostic.19 early-wake failure remains unchanged.
