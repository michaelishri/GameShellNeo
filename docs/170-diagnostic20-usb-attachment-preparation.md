# Diagnostic.20: independent USB-attachment preparation

5 October 2026; capture timestamps are UTC. NEO-117 and NEO-110.

The fresh freezer/driver/five-late-noirq sequence passes on diagnostic.20,
preparing independent evidence for attaching USB during sleep. PM successes
advanced from 8 to 15, with every failure counter zero and Wi-Fi SDIO usage
remaining 2. All three USB/supply wake controls stayed disabled. The owner
confirmed normal sounds/display and physically unplugged USB; live absent-state
validation and the awake attachment rehearsal then passed. The subsequent
attended attachment attempt passed in [report 171](171-diagnostic20-usb-attachment-sleep-validation.md);
this preparation baseline is now consumed.

The successful connected-USB sleep in [report 169](169-diagnostic20-first-rtc-wake.md)
remains separate evidence. Its consumed first-sleep baseline was not replayed
or reused for this attachment case.

## Admission and attended sequence

The owner explicitly answered **"Ready—I'm watching and listening"** for the
whole seven-stage preparation, with USB connected, the headphone socket empty
and controls untouched. Instructions explained that the cable action would
come afterward. Each one-cycle command was submitted once and its original
result, restoration and independent USB/Wi-Fi proofs were reviewed before
continuing.

| Identity | Value |
| --- | --- |
| Host source checkpoint | `373b1ae`, `work/power-insertion-wake` |
| Image / kernel | `0.1.0-diagnostic.20` / `6.18.54-gameshellneo19` |
| Boot | `86a43151-7d9b-44bd-83b3-cc1b9fcff215` |
| Starting PM success/fail | 8/0 |
| Starting wake policy | MUSB, `axp20x-usb`, `axp22x-ac`: disabled |

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# Repeat the last command four times, reviewing each original result first.
```

## Original results

Each capture is beneath this worktree's `.local/diagnostics/` and contains
`cycle-1/result.json`.

| Stage | Capture | Run ID | Stage seconds | Final PM successes |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261005T053706.561235Z` | `e2a3e8a9d1264864ac87a613e708a0b4` | 5.652 | 9 |
| Driver | `20261005T053837.543894Z` | `00629869f3e64924bc1f557c941d7507` | 8.157 | 10 |
| Late/noirq 1 | `20261005T054005.869345Z` | `80bba925fdd441df8333a7d3dc595825` | 7.792 | 11 |
| Late/noirq 2 | `20261005T054130.658813Z` | `b1ef9087d3994e6ebdfd03db24d1fc6a` | 7.771 | 12 |
| Late/noirq 3 | `20261005T054259.655277Z` | `b525442f57384514bd0f3f1d043aad7b` | 7.806 | 13 |
| Late/noirq 4 | `20261005T054429.589614Z` | `66f0d4e2602145cfb7ba73e615a972b1` | 7.930 | 14 |
| Late/noirq 5 | `20261005T054550.004884Z` | `ebb2b3c51cce4f669a1b846e86d18bb9` | 7.924 | 15 |

Every controller exited zero with a completed passing result and both SSH
routes independently verified to the original boot. Process memory, untouched
POWER ownership and handback passed. All failure counters stayed zero. All
six driver/platform runs retained the original keypad handle without held keys,
and their keypad/Wi-Fi traces were complete and restored. Every platform trace
passed the four ordered late/noirq phases and RSB noirq suspend/resume callbacks.

Before/after snapshots retain brightness 1, MUSB and both supply wake controls
disabled, and SDIO active/forbidden with control `on` and usage 2. Every dark
interval has one recorded level-5, 1,000 ms warning with successful playback,
restored mixer and speaker/headphone amplifiers off before PM. The freezer
does not blank the screen. These stages include a five-second debug delay;
they do not enter actual sleep or measure production wake latency.

The driver and late/noirq cycles 1 and 5 each retain one
`SSHException: Timeout opening channel.` during collection. Late/noirq cycle 2
retains `SSHException: No existing session`, with a protocol-banner error in
its local log. Each collector recovered the same original completed run and
verified both routes. No PM command was resubmitted; the existing transport
timing follow-up remains applicable without assigning a driver or Mac cause.

Original result SHA-256 values, in table order:

```text
e2e82a6b60ace30e2ba578fe270505ccb29259dbdc20ca31e9e8fe6b60c5f0dd
fb776f9df82371bf8296411d153c1ef35ca90bc839eb9fffb1c6c9d372ecd756
26bce1a5b883575daa9640a6a9c25fed7cec6e558444cb895335cb3e7c00cb6a
5199301c50c519f468778131b2157815088e62630a9a59054a71d572a21c0268
ab5a76143ef7fe2c1180536d82b4f2ef989d2a1bd56de4f324d09cb6d52fae50
95dd7dbce2035398a9c66abe808b7b14c842fb8008d0c735bcbae7747939f9ea
517aabb96f5a95f2e4741efdbf5ea1be83f6415957e2343894e9583690ef3b1a
```

## Attachment admission and handoff

The saved `task check:sdio-ref-history -- --require-stable` command, supplied
exactly those seven paths, passed. Its summary is
`.local/neo117-attach-debug-history.json`, SHA-256
`d2d0e7a6f8d2d17c27670120630639d40ecb015c9e86243c8b64cdb2f4b77442`.
Fresh read-only PM inspection `20261005T054722.698229Z/inspection.json` passes
health checks with PM15/0; SHA-256
`80f9861e871d4941e22cbe402ffdffc59e0b6d98ef2ffd304e438106ecef5b1e`.
The existing sleep controller's receipt validator accepts all seven originals
for `usb-attach`, with no sleep records in this independent chain. This offline
validation did not submit a rehearsal or sleep.

The owner confirmed **"All normal; USB unplugged; GameShell running"** after
being asked to confirm clear warnings/normal display and physically remove the
GameShell's micro-USB cable. The Mac remains awake on the same Wi-Fi.

Saved `task device:sleep-connection-inspect ROUTE=wifi` capture
`20261005T054932.425837Z/connection-inspection.json` passed strict absent-state
validation: UDC not attached, carrier 0, PHY USB/HOST 0 and both supplies
absent/offline on the original boot. ACIN/VBUS plugin counters were 0 and both
removal counters 1. Its SHA-256 is
`bfdd361080912ba813c543b8668104eafb36a4e9fbe46fc076feb2fff8100539`.

## Awake attachment rehearsal

```sh
task device:sleep-cable-attach-rehearse \
  QUALIFICATION=.local/neo117-attach-debug-history.json \
  CABLE_ACTION=1 UNPLUGGED=1
```

Capture `20261005T055022.819976Z/result.json`, run
`c548a689188f4c1983b57d4febbf80a9`, passed with the original sources/boot;
SHA-256 `8a7c969a12fd79796a0d2f633a00da3d5bffc5c6774e9b077790d962af3e382a`.
The alarm delivered one event, flags `0xa0`, after 30.015 seconds. RTC IRQ31
count advanced 3 to 4 and its original disabled alarm was restored. All three
cable observations stayed absent with all four handler counters unchanged.

Original power policy, input handback and tracing/controls restored, with no
retained policy/drop-in, RTC, PM-control or console ownership. Independent Wi-Fi
SSH passed. USB recovery was not tested because the cable stayed unplugged.
PM remains 15/0. The rehearsal kept the screen on and submitted no actual sleep.

Fresh readiness was requested for the single attachment attempt: long warning,
wait ten seconds after darkness, connect USB once, then leave it connected.
If the display returns before attachment, leave USB unplugged. The expected
new behavior is to stay asleep when USB is connected and wake on the RTC at
roughly 30 seconds total. That separately readied attempt and the preserved
original/observer results are recorded in report 171. No sleep is currently running.

The new policy's intended outcome is staying asleep on insertion and charging;
these debug checks do not establish that outcome. POWER wake, deep retention,
energy use and charge acceptance remain separately unqualified. The original
diagnostic.19 early-wake failure is unchanged. NEO-117 remains in progress.
