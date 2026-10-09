# Diagnostic.25 staged suspend/resume qualification

9 October 2026; evidence timestamps are UTC. NEO-172 is complete under
NEO-108. All seven freezer/driver/late-noirq debug checks pass on diagnostic.25/kernel
`6.18.54-gameshellneo24`, boot `2170b296-d964-4d16-bdb1-c135b0e7b812`.
Both SSH routes recover, the original keypad connection survives and the owner
confirms clear warnings and normal dim-console returns. The awake RTC rehearsal
and first actual connected-USB RTC sleep also pass, bringing PM success/fail to
**8/0**. All four CPU s2idle callbacks run, with independent timekeeping-freeze
evidence and a 29.340-second BOOTTIME–MONOTONIC gap. The owner confirms hearing
the warning and seeing the normal dim console return without touching the cable
or controls. This establishes one successful coordinated sleep/wake run; repeat
and cable coverage, broader reliability and energy savings remain unqualified
on this image. [Report 233](233-diagnostic25-installation.md) records installation
and the passing awake prerequisites.

## Initial attended sequence

The owner confirmed readiness before these saved tasks ran, sequentially from
`work/musb-restart-integration`. The original freezer result was reviewed before
submitting the driver cycle:

```sh
task device:pm-test STAGE=freezer CYCLES=1 SOCKET_STATE=0
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1 SOCKET_STATE=0
```

The freezer leaves the display on. The driver cycle plays the one-second level-5
speaker warning before darkness and restores the mixer controls and amplifier
idle state. The owner separately confirmed that the warning was clear and the
normal dim console returned, then confirmed readiness for one late/noirq check.

| Stage | Capture under `.local/diagnostics/` | Run ID | Stage interval |
| --- | --- | --- | ---: |
| freezer | `20261009T053850.132174Z/cycle-1` | `7167aa5f8b384d7181de90130eb4ce4a` | 5.245 seconds |
| devices | `20261009T054009.041629Z/cycle-1` | `17cde4a6a32541e7b2603aa39a93d5b9` | 7.717 seconds |

The intervals include the five-second debug delay; they do not measure real
sleep or wake latency. Both results verify process memory and independent USB
and Wi-Fi SSH on the original boot. PM success/fail advances **0/0 → 1/0 → 2/0**,
with every failure counter zero. Backlight brightness returns to 1 with power 0.
All four WFI s2idle usage/time counters remain zero, as expected for debug stages.

The driver trace retains the original keypad handle, USB device number and input
sysfs identity, with zero keypad disconnects or supply-disable events. The saved
handle check first passes 0.201 seconds after the stage returns; that is software
handle availability, not a physical key-delivery measurement. POWER ownership is
handed back. Keypad and Wi-Fi tracing restore without recorded loss. The saved
`test-pm-stages.py` validators and `check-pm-stages.py` retention check were also
run against the original saved driver result.

SDIO runtime usage remains 2 before and after both stages, with unchanged policy:
`control=on`, `runtime_enabled=forbidden`, `runtime_status=active`. The existing
`task check:sdio-ref-history -- --require-stable <freezer-result> <driver-result>`
passes and saves `.local/neo172-initial-reference-history.json`. This is stable
snapshot evidence, not isolated reference attribution or an energy measurement.

## Original evidence

Private task logs are `.local/neo172-freezer.log` and `.local/neo172-driver.log`.
The driver's original collection log retains one forwarded-channel failure:
`ChannelException(2, 'Connect failed')`; the task log reports `No route to host`.
The existing bounded collector subsequently retrieves the same submitted run,
and both independent route proofs pass. No PM operation was resubmitted, no
socket-state capture was enabled, and the abandoned SSH-stall investigation was
not resumed. The transport error does not establish its underlying cause.

| Original result | SHA-256 |
| --- | --- |
| Freezer `result.json` | `22f7d0d5570b655dc8f575ea732ccdbd1a680d6095682ce187693f698ab35f0b` |
| Driver `result.json` | `2ef4990da1b15d1f50748adfba52e173753d6956cf7b7938c3eeb8ae1919a5da` |

## First late/noirq check

After fresh readiness, one `task device:pm-platform WIFI_TRACE=1 SOCKET_STATE=0`
passed. Capture `20261009T054314.713122Z/cycle-1` retains run
`9a540c855fc74d4a98cad0490b254dcf`; `result.json` SHA-256 is
`a14932125d97669eabd8f25c04d0c2d4a906f935c13b958de9fab35ba588d178`.
The 7.870-second stage includes the five-second debug delay. PM advances
**2/0 → 3/0**, with the same boot and all failure counters zero. The original
keypad handle/device/input identity survives, with no keypad disconnect or
supply-disable event; the first saved handle check passes after 0.176 seconds.
Both SSH routes recover. POWER handback, speaker/mixer restoration and complete
restored keypad/Wi-Fi traces pass. All four s2idle usage/time counters remain
zero. The reference-history check across all three results passes with SDIO
usage 2 throughout. The owner confirms clear warning and normal dim-console
return, and readiness for four repeats.

The original collection errors retain `SSHException: Timeout opening channel.`
The saved collector subsequently retrieves the same run, with independent route
proofs passing. No second PM submission or separate transport investigation was
performed. Private task log: `.local/neo172-platform-first.log`.

## Four late/noirq repeats

With fresh owner readiness, the same saved platform task ran four times. Each
original result was collected and reviewed before submitting the next cycle.
All four pass with both independent SSH proofs, preserved process memory,
original keypad handle/device/input identity, no keypad disconnect or supply
disable, restored complete traces, POWER handback and speaker/mixer restoration.
The owner confirms clear warnings and normal untouched display returns across
the complete batch. No further screen test ran while awaiting that confirmation.

| Repeat | Capture under `.local/diagnostics/` | Run ID | Stage interval | PM success/fail after |
| --- | --- | --- | ---: | --- |
| 1 | `20261009T054521.357195Z/cycle-1` | `f65b291f5e714bb8946fe0dac0aee128` | 7.864 seconds | 4/0 |
| 2 | `20261009T054637.807857Z/cycle-1` | `e3c35523f2b54c39a086d654de270669` | 7.980 seconds | 5/0 |
| 3 | `20261009T054751.730836Z/cycle-1` | `fc1fd4630e1343f2862df49b189cc474` | 7.872 seconds | 6/0 |
| 4 | `20261009T054915.846890Z/cycle-1` | `8da7f2ffd49a4b268b17f0d1368f0f8a` | 7.886 seconds | 7/0 |

The intervals include the five-second debug delay. All four CPUs' s2idle
usage/time counters remain zero; brightness/backlight power returns to 1/0.
Every failure counter remains zero. Original result SHA-256 values, in order:

- `d9896ec65b83d82f47b0028f05fbf92b3fae4fd70b374ad68c847dc2d9f69686`
- `52c1809aa018b5ba12eff875bd6d60e0bb6fd779b626a602ee0ce0e077966c27`
- `d0e663fbe9baf7118cc2a0e04396fb84472da2cc00ce89f22e79f8773a351029`
- `0e86bc531301d72288b379fb5019ff303da5f4b6c250c86f7494a8033eea999f`

Repeat 1 retains one `Timeout opening channel` collection error; repeat 2 has
no recorded collection error. Repeats 3 and 4 each retain one forwarded-channel
failure (`No route to host` / `ChannelException`). Every original result is
subsequently collected, with both route proofs passing. No PM operation was
resubmitted. Original logs are `.local/neo172-platform-repeat{1,2,3,4}.log`.

## Completed debug admission

`task check:sdio-ref-history -- --require-stable` passes on all seven explicit
result paths in chronological order. SDIO usage stays at 2 with unchanged
policy, and adjacent complete PM counter snapshots match: successes progress
0 → 7 without an intervening cycle. The saved history is
`.local/neo172-reference-history.json`, SHA-256
`31cf2c685c67c7420b0bbb36fdf774e089feb526f27e1405f4eedfecad253bb2`.

A fresh read-only `device:pm-inspect ROUTE=usb` capture at
`20261009T055041.751836Z` passes full health and the existing sleep controller's
seven-debug admission against that history. The same boot/image, PM7/0 and zero
s2idle counters remain. Inspection SHA-256:
`eed980762d9e17a3d2bf2215a0693f0c54eeb27a15e183ee856da72d83f56e71`.
The saved admission check is `.local/neo172-debug-receipt-check.json`;
receipt hashes are canonical device-result digests, distinct from the raw-file
hashes above. No original evidence was rewritten during offline checks.

## Awake RTC rehearsal

After the owner's batch confirmation, this saved task ran once:

```sh
task device:sleep-rehearse QUALIFICATION=.local/neo172-reference-history.json SOCKET_STATE=0
```

Capture `20261009T055130.078635Z` retains run
`e2d0187e79604413907a92b22963d79e`, with original result SHA-256
`821f52639c762f4707e19cdf36f737a9f97e83695a36237a1bf4fc537ace5678`.
Full health, source-bound qualification, functional/recovery checks and both
independent SSH proofs pass on the same boot. The alarm is delivered after
30.588 seconds while awake; this is not wake-from-sleep evidence. The screen
stays on, PM remains 7/0 and all four s2idle usage/time counters stay zero.
Process memory survives, the RTC alarm is restored, POWER is handed back and
no policy/control/RTC/console ownership marker or diagnostic drop-in remains.
The original power-key policy and amplifier idle state are restored. No
collection error is recorded. Private log: `.local/neo172-rehearsal.log`.

## First actual coordinated sleep

Following separate fresh readiness, the saved task ran once:

```sh
task device:sleep-rtc QUALIFICATION=.local/neo172-reference-history.json \
  REHEARSAL=e2d0187e79604413907a92b22963d79e ATTENDED=1 SOCKET_STATE=0
```

The original result passes on the same boot. RTC IRQ31 wakes the device and both
independent SSH routes recover. Process memory verifies, the original keypad
handle remains healthy, and backlight brightness/power returns to 1/0. PM
advances **7/0 → 8/0**, with every failure counter zero. SDIO runtime usage stays
at 2 with unchanged policy. The one-second level-5 warning passes playback and
control restoration; the owner confirms a clear warning and normal dim-console
return without cable or button intervention.

All four `cpi_wfi` s2idle callback counters advance from 0 to 1. An independent
trace records one timekeeping-freeze pair and the expected late/noirq and RSB
suspend/resume phases. Paired clock samples give:

| Measurement | Value |
| --- | ---: |
| BOOTTIME interval | 31.775631090 seconds |
| MONOTONIC interval | 2.435420014 seconds |
| BOOTTIME–MONOTONIC gap | 29.340211076 seconds |
| Clock sampling uncertainty | 0.000019313 seconds |
| Alarm elapsed interval | 32.513586258 seconds |

The recorded s2idle boundary spans 130 microseconds of MONOTONIC time because
that clock stops during timekeeping suspension. It is not a 130 µs sleep or
resume-latency measurement. Callback participation and the independent freeze
trace establish coordinated Linux s2idle, not CPU/DRAM power-off, exact physical
residency or energy savings. The post-return battery sample remains valid on
this boot with BOOTTIME age 4.580 seconds; battery calibration is still open.

POWER is handed back with verified logical release and descriptor closure, and
no key events. All policy/control/RTC/console ownership markers are cleared;
no diagnostic policy drop-in remains. Keypad, Wi-Fi and USB traces restore
without recorded loss/overrun. Original power-key policy and amplifier idle
state are restored. No collection error is recorded and no sleep was resubmitted.

| Evidence | Value |
| --- | --- |
| Capture | `.local/diagnostics/20261009T055321.131756Z` |
| Run | `a32fc935233f4717a338c3f751725d0a` |
| Result SHA-256 | `8b0a1cfd35d983a19684744b1f773f761373779603f6a4cc5b1e031b67db3dd6` |
| Continuation SHA-256 | `5918b1ab31b4582647396b9b6d7116bd1e366c3a4c7250e150944657dc19f12d` |

The offline `task report:sleep-evidence RESULT=<original-result>` independently
recomputes and passes the RTC, trace, paired-clock and WFI checks. Assessment
capture: `.local/diagnostics/20261009T055508.129808Z/sleep-evidence.json`.
It does not alter or requalify the original result. Original task log:
`.local/neo172-first-sleep.log`; assessment log: `.local/neo172-sleep-evidence.log`.

## Final health and next gates

A subsequent read-only `task device:pm-inspect ROUTE=usb` capture at
`20261009T055509.755655Z` passes full health validation. It retains the same
boot/image, PM8/0, normal dim backlight and four s2idle counts of 1. Inspection
SHA-256 is `efab7ec7ba29e72aa1ea89b489b2d1bbd79ce896ba8732b790dff02e8b87999c`.
The existing sleep-controller admission accepts the unused
`20261009T055321.131756Z/qualification-next.json` against this newer snapshot,
revalidating all seven debug results and one actual sleep. Saved check:
`.local/neo172-sleep-receipt-check.json`. No gate was weakened.

NEO-172's staged checks and first RTC wake are complete. No further sleep or
screen test is running. The next bounded gate is four attended connected-USB
sleep/wake repeats, followed by relevant USB reconnect and cable/power profiles
under NEO-108. Obtain fresh watching readiness, retain the long warning, review
each original result and stop on failure. These passes do not establish that
the deferred-restart race occurred on this board, nor energy, latency or broad
reliability improvements from its reviewed fix. The newer incomplete NEO-106
controller-removal stack is outside diagnostic.25.
