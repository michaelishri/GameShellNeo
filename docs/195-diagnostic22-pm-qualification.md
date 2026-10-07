# Diagnostic.22 suspend/resume qualification

7 October 2026; capture timestamps are UTC. NEO-133 is complete. The initial
freezer, driver and first late/noirq debug checks pass. The owner confirmed
the initial warning and normal dim-console return, then gave readiness for the
late/noirq check. Its warning/display were also confirmed, and the owner
authorized four repeats, which pass all automated checks. The owner confirmed
“Yep, all clear and back to normal” for the final warnings/display. The awake
RTC rehearsal also passes. Two actual connected-USB RTC sleeps pass the
automated checks. The owner did not hear the first warning and explicitly
requested the second. Its clear warning and normal dim-console return are
owner-confirmed without touching the cable or controls. The owner then noted
that the first warning may have been missed through inattention.
[Report 194](194-diagnostic22-installation-and-adc-validation.md) records the
verified installation and awake checks.

## Initial observed sequence

The owner explicitly confirmed watching/listening readiness for a freezer check
followed by one driver cycle, keeping USB connected and all controls untouched.
The freezer result was reviewed before the driver cycle started:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
```

The freezer uses the standard diagnostic inhibitor. The driver cycle additionally
owns the POWER input and retains original keypad handles with Wi-Fi tracing.
The freezer leaves the display on. The driver's long screen-warning record
passes with audio controls restored. The owner subsequently confirmed the
warning and normal dim-console return.

Both results belong to diagnostic.22/kernel `6.18.54-gameshellneo21`, boot
`7884d229-2309-47df-9af0-b6fe500ad9ac`. Each verifies both USB and independent
Wi-Fi SSH after completion. Private evidence beneath `.local/diagnostics/`:

| Stage | Capture | Run | Result SHA-256 |
| --- | --- | --- | --- |
| freezer | `20261007T053126.968157Z/cycle-1` | `8aef460d034944edb030bb5cca9fbcc5` | `d6a45454a7e9926aa572d49dbe91b8ecc63323dde0319ae54848b055290007eb` |
| devices | `20261007T053232.350714Z/cycle-1` | `dc9b081f2e2c4068b6c9e5bdbf1f7a28` | `d4b6a7234c6b7f610bc7682458b60204041bbf994f832a42870a2ad519f53039` |

The original task logs are `.local/neo133-freezer.log` and
`.local/neo133-driver.log`. Driver collection initially logged `No route to host`;
the original completed result was subsequently collected and both routes passed.
Preserve that transient without labeling it a kernel failure or deriving recovery
latency from an untimestamped collection error.

At this checkpoint PM success/fail is 2/0 with every failure counter zero.
SDIO usage stays 2 with active/on/forbidden runtime policy. The original keypad
connection is retained, process memory checks pass, power-key ownership is
handed back, and Wi-Fi tracing restores without loss. Brightness returns to 1
with backlight power 0. No further screen test is running at this checkpoint.

## First late/noirq check

After the owner confirmed “Yes and ready”, the saved task ran once:

```sh
task device:pm-platform WIFI_TRACE=1
```

Private capture: `.local/diagnostics/20261007T054331.905931Z/cycle-1/`;
run `69e5d1b3db6b4da8bbe1356f367ab482`. Result SHA-256:
`0cea3410af0f3072dfb41060cbfaa89a0100229ea91b89f9478957948974ad57`.
The task log is `.local/neo133-platform-initial.log`.

The completed result passes both independent SSH routes, process memory,
original keypad retention, POWER handback and loss-free Wi-Fi trace restoration.
The one-second level-5 warning completed with audio controls restored. The PM
stage took 7.897 seconds including the five-second debug delay; this is not a
real-sleep or wake-latency measurement.

Final PM is 3/0 with every failure counter zero. SDIO usage stays 2 with unchanged
active/on/forbidden runtime policy. Brightness returns to 1 and backlight power
0. The boot is unchanged. An initial collection `No route to host` is retained;
subsequent retrieval of the original result and both route proofs passed.
The owner then confirmed the warning/normal display and gave readiness for
four repeats. Each original result is reviewed before the next submission.

## Four-repeat batch

The owner confirmed the first late/noirq warning/normal console and readiness
for four repeats. Each used `task device:pm-platform WIFI_TRACE=1`; every
original result was reviewed before starting the next. Private originals are
`cycle-1/result.json` beneath the listed `.local/diagnostics/` capture:

| Repeat | Capture | Run ID | Stage seconds | PM successes afterward | Result SHA-256 |
| --- | --- | --- | ---: | ---: | --- |
| 1 | `20261007T054545.269969Z` | `096fc70a39c847ee81ffb900453fd120` | 7.938 | 4 | `4bfc2f5ed2a1dee1b8fb357d89da7ad5eedebbc7daae19bcecad98f21db9fdc6` |
| 2 | `20261007T054719.987800Z` | `e82f7bef0711425cbbd6cf7ca6764b45` | 8.006 | 5 | `4957b981a2d37bdb9b5fbbee76cb4858e0f1c8fa579a874efab088ab70f6c0dc` |
| 3 | `20261007T054853.760933Z` | `4ca7678832184133b978486679d1b106` | 8.045 | 6 | `3cb4665d5791a82a2bc29bbd75a67a3a7aa7e9940da04fc0020cadf21915c87c` |
| 4 | `20261007T055016.800012Z` | `4e50cd0e59784ad3af3955a5c63db8e8` | 7.849 | 7 | `07330be5ab982b1ad9f5e7aa3d7b9320153af6dc3b7402cfd5d3f9c81fe2450c` |

All four results pass both independent SSH routes, original keypad retention,
process memory, POWER handback, the long warning/restoration and loss-free
Wi-Fi trace restoration. Final PM is 7/0 with all failure counters zero.
Brightness/backlight power is 1/0. SDIO usage remains 2 throughout.
The timing column includes the five-second debug delay and is not wake latency.

The saved offline comparison `task check:sdio-ref-history -- --require-stable`
accepts all seven explicit result paths in chronological order. Its output is
`.local/neo133-reference-history.json`, SHA-256
`edbbfb78f627fe3b7afd680ccaf5418f5cf2f82870b1311bb52b6d51238f0426`.
All adjacent PM counters also match exactly, with no intervening PM cycle.
The owner confirmed the warnings and normal returns for the complete batch;
this baseline is supplied to the subsequent awake rehearsal.

Task logs `.local/neo133-platform-repeat-1.log` through `-4.log` preserve all
collection output. Repeats 1, 3 and 4 each logged an initial `No route to host`;
repeat 2 did not. All original completed results and independent route proofs
were obtained without retrying PM or requesting a cable action. This does not
assign a cause or establish the duration of any post-resume transport delay.
The owner confirmed all warnings/returns were normal. No cable or button action
was requested during this sequence.

## Read-only ADC check after debug resume

`task device:charge-inspect` passes on the same boot at PM7/0, using the admitted
schema-4 masked-helper and volatile-B8 contracts. Capture:
`.local/diagnostics/20261007T055220.388633Z/inventory.json`; SHA-256:
`a6eb1d703283ee4e95824deca09ff60640e2879bd0737df2ff7bb46ee5d2a971`.
Raw `ec/03`, masked/legacy formulas and the separate sysfs voltage sample agree
at 4.1569 V, with zero unused bits. The gauge reports 100%/Charging/2 mA.
REG33/34/B8/E0/E1/E6 match the initial awake inventory, and reported limits
remain 4.2 V/1.2 A/900 mA. No charger/gauge setting was changed.
This shows a compatible read after debug resume; it does not resolve absolute
accuracy, coherence, capacity or the earlier voltage discrepancy.

## Awake RTC rehearsal

Following the owner's final confirmation, the saved task ran while the screen
stayed on:

```sh
task device:sleep-rehearse QUALIFICATION=.local/neo133-reference-history.json
```

Capture: `.local/diagnostics/20261007T055731.923737Z/result.json`;
run `b1fef2d2d5cf4a149c39e496ee9c38ba`. Result SHA-256:
`05f1ad3b274b580dd58a18e3b659a9bde90ba1b93a55f7e07ee367f6ec621137`.
The original task log is `.local/neo133-rehearsal.log`.

One RTC event arrived with flags `0xa0`; IRQ31 advanced 1 to 2. The 30-second
alarm deadline was exercised while awake and the original alarm restored.
Power policy and input ownership returned to their original state, with no
retained policy, PM, RTC or console owner. Both independent SSH routes pass.
PM remains 7/0, SDIO usage 2 and brightness/backlight power 1/0 on the same boot.
This establishes awake alarm delivery and restoration, not wake from sleep.

## First actual connected-USB RTC wake

The owner gave fresh “Ready” for one actual sleep. At source checkpoint
`a765415`, the saved task was submitted once:

```sh
task device:sleep-rtc QUALIFICATION=.local/neo133-reference-history.json \
  REHEARSAL=b1fef2d2d5cf4a149c39e496ee9c38ba ATTENDED=1
```

Original capture: `.local/diagnostics/20261007T082122.368046Z/result.json`;
run `f616892ce72a42799c1a1ad11c85e403`, SHA-256:
`66c16dd7339b632208df154901f00e3703a650e76e64612f663c04f910182b57`.
The task log is `.local/neo133-first-sleep.log`.

The saved result passes functional RTC wake, both independent SSH routes,
process memory, original keypad retention and complete USB/Wi-Fi trace
restoration. POWER input and original logind policy return, with no retained
policy, RTC, PM or console owner. The long warning's playback/control-restoration
checks pass. These software checks do not prove the speaker was heard.

RTC IRQ31 advanced 2 to 3 and is the recorded wake IRQ. The alarm-to-return
interval is 31.925 seconds; the bracketed entry-to-return interval is 31.309
seconds. The trace supports a 28.877-second s2idle interval, with all four
late/noirq phases and RSB noirq suspend/resume present. No timekeeping freeze
pair was observed; the clock gap is within sampling uncertainty. CPU retention
and energy remain unqualified. These durations do not measure normal wake
latency.

PM is 8/0 with all failure counters zero, SDIO usage remains 2 and brightness/
backlight power is 1/0 on the original boot. The separate read-only ADC capture
`.local/diagnostics/20261007T082339.545899Z/inventory.json` passes:
raw `ec/02`, corrected/legacy/sysfs 4.1558 V, 100%/Charging/2 mA, fresh B8=`c0`
and unchanged sampled controls/limits. Its SHA-256 is
`7dc120740a204d4afbb0d807a522f89a83a322209293d4d80d9b92bd303f514a`.
This remains an uncalibrated sequential measurement, not charge-during-sleep
or voltage-accuracy evidence.

The owner reported “I didn't hear the tone” and explicitly requested another
test. Preserve this first result as an automated pass with the warning unheard;
its display/untouched-return confirmation was not separately supplied. Do not
replace that observation with a later successful attempt.

## Requested second actual sleep

The owner explicitly requested a repeat. The completed first result permits
one new submission using its continuation and the original awake rehearsal:

```sh
task device:sleep-rtc \
  QUALIFICATION=.local/diagnostics/20261007T082122.368046Z/qualification-next.json \
  REHEARSAL=b1fef2d2d5cf4a149c39e496ee9c38ba ATTENDED=1
```

The second result passes automated checks. Capture:
`.local/diagnostics/20261007T082435.420412Z/result.json`; run
`5c2a86dc09df4687afbe2c84948f304f`, SHA-256:
`715152d5d3bd15b41084576ee8e0bb3f76aa5625e725467cef660453a43ec175`.
The original output is `.local/neo133-second-sleep.log`. One initial collection
`No route to host` is preserved; the original completed result and both route
proofs subsequently passed without another PM submission.

Functional RTC wake, both independent SSH routes, original keypad retention,
memory and trace/policy restoration pass. The long warning's software checks
pass with unchanged volume/duration. No policy, RTC, PM or console owner remains.
PM is 9/0, every failure counter remains zero, SDIO usage is 2 and brightness/
backlight power is 1/0. The alarm-to-return interval is 31.936 seconds and the
trace supports 28.693 seconds inside s2idle. CPU retention, energy and ordinary
wake latency remain unqualified.

The owner confirmed “Yes—warning clear; dim console returned untouched” for
the second test and then noted possible inattention during the first warning.
No audio settings changed between the two tests. This establishes audibility
and normal display return for the repeat while preserving the first observation.
No further screen test is running. The current continuation is
`.local/diagnostics/20261007T082435.420412Z/qualification-next.json`; the initial
baseline and first continuation are consumed and must not be reused for a new
sleep. The original awake rehearsal remains
`b1fef2d2d5cf4a149c39e496ee9c38ba`.

## Remaining qualification

Both actual sleeps pass automated checks, and the second has the owner's clear
warning, normal display and untouched-return confirmation. The first warning
remains recorded as unheard, subsequently attributed by the owner to possible
inattention. The next slice is bounded connected-USB repeatability using the
second continuation, with fresh readiness for the batch. The seven debug
checks and awake rehearsal remain qualified as recorded above.
Battery/cable/POWER wake profiles, energy and physical battery accuracy remain
separate; these debug checks do not establish real sleep or charging in sleep.
