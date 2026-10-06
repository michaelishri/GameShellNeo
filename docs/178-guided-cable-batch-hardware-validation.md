# Guided alternating cable batch: hardware validation

6 October 2026; capture timestamps are UTC. NEO-118, supporting NEO-110/117.

After the [hotspot recovery](177-cable-batch-preflight-timeout.md), a new guided
session has passed its first removal and attachment cases, including both owner
observations. Cycle 3 removal passes its automated checks and awaits the owner's
observation. The four-cycle workflow is not yet fully qualified. USB is unplugged at this
checkpoint; no extra awake reconnect belongs between these alternating cases.

The original session that stopped before sleep remains failed and unchanged.
The new session uses its own awake rehearsal and the unconsumed, observed
[seven-debug baseline](176-guided-cable-batch-debug-preparation.md). No image,
driver or diagnostic source changed. Starting host checkpoint: `cb2d70a`.

## Session and saved commands

| Item | Value |
| --- | --- |
| Image / kernel | `0.1.0-diagnostic.20` / `6.18.54-gameshellneo19` |
| Boot | `34483a13-9373-4ee3-8984-fd81a99bc5de` |
| Batch ID | `ac4662a0e6d14e23bfcf6e944cf37594` |
| Private batch directory | `.local/diagnostics/20261006T093507.694630Z` |
| Fixed sequence | Remove, attach, remove, attach |
| Starting PM / SDIO | 7 successes, zero failures / usage 2 |

```sh
task device:sleep-cable-batch-start \
  QUALIFICATION=.local/neo118-home-debug-history.json ATTENDED=1 CABLE_ACTION=1
task report:sleep-cable-batch \
  BATCH=.local/diagnostics/20261006T093507.694630Z \
  OBSERVATION=during-dark DISPLAY=normal
# Each subsequent step requires a separate described readiness response:
task device:sleep-cable-batch-next \
  BATCH=.local/diagnostics/20261006T093507.694630Z ATTENDED=1 CABLE_ACTION=1
```

Observation values above represent the owner's actual report, never an assumed
outcome. The runner stops after each original result and independent endpoint
inspection; reporting an observation does not start another test.

## Accepted cycle 1: removal

Awake rehearsal `72fdbaf883df4ad29b55129b59672a7c` passes with both routes,
unchanged connected cable state and full restoration. RTC IRQ31 advances 2 to 3
after 30.823 seconds; PM remains 7/0.

Actual sleep `a346aeb95a464a77a507a346b1bc3780` passes the full original-result
validator. PM advances 7 to 8 with all failure counters zero; RTC IRQ31 advances
3 to 4, with alarm delivery after 31.838 seconds and wake IRQ31. The trace has
the actual s2idle boundary and ordered late/noirq/RSB callbacks. Its 28.546-second
MONOTONIC interval is not a CPU-residency or energy measurement.

The original keypad handle, process memory, Wi-Fi, traces, console, RTC and
power-key policy restore correctly, with no retained owners. The long warning
is level 5 for 1,000 ms, followed by restored mixer state and idle amplifiers.
SDIO stays active/forbidden, control `on`, usage 2; MUSB and both supply wake
controls stay disabled.

The final cable state is `not attached`, carrier 0, PHY USB=0/HOST=0 and both
external supplies absent/offline. The separate Wi-Fi endpoint inspection
confirms that state before any later attachment. All cable handler deltas are
zero, accepted by the predeclared masked-removal criteria; this does not
timestamp the electrical edge. Wi-Fi SSH passes. Absent USB is not reported as
USB recovery. Three collection connection attempts failed before the same original
result was recovered; no PM command was resubmitted.

The owner answered **“Yes—unplugged during darkness; console normal.”** The
saved observer task binds that report to the unchanged result and marks one
accepted cycle, with batch state `ready` for the next separately readied step.

Evidence paths relative to the batch directory:

| File | SHA-256 |
| --- | --- |
| `cycle-1/awake/result.json` | `7623d89a6f1244a52372569e53aac4a595fc0da96d2d083e059a6343ebf7a793` |
| `cycle-1/sleep/result.json` | `066b353f8ba7a1ca6f4c700dce7d7296992ba4980a330374d1deb12fd3d114e6` |
| `cycle-1/endpoint/connection-inspection.json` | `d5fcba17892895ed4ebef9c7cf4a638a08f06b93ab4c7ba6ca6dec4e1a191cb1` |

## Accepted cycle 2: attachment

The owner separately readied the next step, leaving USB absent between cycles.
Awake rehearsal `14876f7b0c1d433f954160d9452c7b93` passes with Wi-Fi, PM8/0
unchanged and RTC count 4 to 5 after 30.523 seconds. Actual sleep
`6b315e29c97a451880770135f5906d8a` passes with PM8 to 9, zero failures, RTC
count 5 to 6 and wake IRQ31. Alarm delivery occurs after 31.905 seconds; the
s2idle trace interval is 28.628 seconds. Original input, memory, warning audio,
policy, console, alarm and trace restoration pass, with SDIO usage 2 throughout.

After resume, USB is configured with carrier 1, PHY USB=1/HOST=0 and both supplies
present/online. Both SSH routes pass, followed by an independent matching
endpoint inspection. All four cable-handler deltas remain zero under the
declared masked-insertion criteria. Two `Timeout opening channel` collection
errors are retained; the same original was recovered without repeating sleep.

The owner confirmed **“Yes—stayed dark after USB; then console returned.”**
The immutable observer report is accepted, and the batch now has two accepted
cycles. This confirms the requested visible stay-asleep behavior for this case;
it does not measure charge acceptance while the CPU is asleep.

| File | SHA-256 |
| --- | --- |
| `cycle-2/awake/result.json` | `c37efa08d9434e23e5fccf09025d08522c0dc3f7498cb0f04e5a6e61c8accc3e` |
| `cycle-2/sleep/result.json` | `949f8b215c70ba7b8cce547c2e54550e66da0217e38ff3894f39db01853007e0` |
| `cycle-2/endpoint/connection-inspection.json` | `12c12f6dc53af16091764b1bf1e91bd3e8b042fdade3a6d4c310f7381333c338` |

## Cycle 3: automated removal pass; observation pending

After fresh readiness, awake rehearsal `36d194f75af74816a5acc99f5991a759`
passes with PM9/0 unchanged, RTC count 6 to 7 and alarm delivery after 30.080
seconds. Sleep `9ad3ff198e494ab4bd70294729f4c8dd` passes with PM9 to 10,
zero failures, RTC count 7 to 8 and wake IRQ31. Alarm delivery takes 32.269
seconds, with a 28.881-second s2idle trace interval. SDIO usage stays 2.

Original input, memory, long warning, console, RTC, traces and policy restoration
pass. USB ends absent, carrier0, PHY USB=0/HOST=0, with both supplies offline;
Wi-Fi and the independent endpoint inspection pass. Cable-handler deltas remain
zero. One channel-open timeout and two connect failures are retained during
collection of the same original. No sleep was resubmitted. The controller is
stopped in `awaiting-observation`; the owner's first report remains pending.

| File | SHA-256 |
| --- | --- |
| `cycle-3/awake/result.json` | `6428c028e6ac4bf66275be3c19cfa1579237828b99680444292a3f9f8ed234e8` |
| `cycle-3/sleep/result.json` | `108d7c4afede474e9b0e0ef958a29abc32a74ed992592f6ac67a913254a0f464` |
| `cycle-3/endpoint/connection-inspection.json` | `0877a479cb2bc4af3d949e2a5e81e6b016bb3ef1e55052fd4647f1683e37774f` |

The final attachment has not run. Charging during sleep,
standby energy, CPU retention, Mac sleep, power-button wake and production policy
remain separate qualification work. Ordinary automatic/button sleep is disabled.
