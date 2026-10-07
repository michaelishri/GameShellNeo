# Diagnostic.23 suspend/resume qualification

7 October 2026; capture timestamps are UTC. NEO-138 is complete.
The initial freezer, driver and first late/noirq debug checks pass on diagnostic.23/kernel
`6.18.54-gameshellneo22`, boot `7cc788ef-2070-4ab9-887a-1af70c074713`.
The owner confirms the clear warnings and normal dim-console returns for the
initial stages and four late/noirq repeats. All seven debug checks pass at PM7/0.
The awake RTC rehearsal and first actual connected-USB RTC sleep also pass.
The owner confirms the actual sleep's clear warning and normal untouched
dim-console return. Final PM is 8/0. CPU retention, energy and broader
repeatability remain unqualified.
[Report 199](199-diagnostic23-installation-and-pty-validation.md) records the
verified installation, awake checks and measured terminal-startup improvement.

## Initial observed sequence

The owner explicitly confirmed watching/listening readiness, USB connected,
headphone socket empty and controls untouched. The saved workflow ran once per
stage, reviewing the freezer result before submitting the driver test:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
```

The freezer keeps the display on and uses the diagnostic inhibitor. The driver
test also owns POWER input, retains the original keypad handles and captures
Wi-Fi tracing. Its one-second level-5 warning passes playback/control-restoration
checks; the owner separately confirms audibility and normal display return.

| Stage | Capture beneath `.local/diagnostics/` | Run ID | Result SHA-256 |
| --- | --- | --- | --- |
| freezer | `20261007T094939.401336Z/cycle-1` | `65e721221544420398f7d5575a3886fb` | `be2172ab35c0d0d377cf46b715afcad09010f8c128b2f3fffd3787eee6954956` |
| devices | `20261007T095058.158555Z/cycle-1` | `9000b1b6eb1d454bbf58b289acd853c1` | `48ffb037a282ee93e64c620fe2840e5a78600a129c72c18e68c0743444646efe` |

Both completed results verify process memory and independent USB/Wi-Fi SSH on
the original boot. PM success/fail advances 0/0 → 1/0 → 2/0, with every failure
counter zero. The stage intervals are 5.387 seconds for freezer and 7.882 seconds
for devices, including the five-second debug delay. They are not real sleep or
wake-latency measurements.

The driver result retains the original keypad handle, USB device number and
input sysfs identity, with zero disconnects or supply-disable trace events.
Keypad and Wi-Fi tracing restore without loss. POWER ownership is handed back.
SDIO usage stays 2 with unchanged active/on/forbidden runtime policy. Brightness
returns to 1 with backlight power 0.

## Collection timing

Both saved timing captures validate with no recorded errors and exactly one
PM submission each. Each has six collection attempts separated by the existing
five-second waits. The host capture spans are 52.109 seconds for freezer and
64.588 seconds for devices; these include preflight, submission, diagnostic
observation, collection and independent route proofs, not just the PM interval.
The longest driver collection attempt takes 16.749 seconds and succeeds.
Neither absence of an exception nor that attempt duration establishes exact
post-resume network-ready time or the cause of historical collection errors.

Timing SHA-256 values (`host-timing.jsonl` in the respective cycle directories):

- Freezer: `fa9001689466e15730df2005507ce3547d9d8b98f69bdac89e6651706acde937`.
- Devices: `8e6fa322c37ac085747f4eb60e79c3d96a0f5c6277cb039425d143f296363ddf`.

Original task logs: `.local/neo138-freezer.log` and `.local/neo138-driver.log`.
Offline summaries: `.local/neo138-freezer-timing.json` and
`.local/neo138-driver-timing.json`, produced with
`task device:ssh-timing-report CAPTURE=<cycle-directory>`.

## First late/noirq check

The owner confirmed “Warning clear; console normal; ready for late/noirq.”
`task device:pm-platform WIFI_TRACE=1` ran once and passed. Its capture is
`.local/diagnostics/20261007T095343.437451Z/cycle-1/`, run
`75955722802c4146895ca024db56de99`. Result SHA-256:
`27de5c921a9eba99064f18829a4cedcf0f5f9a108a74f0e852dafc37c41ed4d9`.
The stage interval is 7.878 seconds including the five-second debug delay.

Both independent SSH routes recover on the original boot. Process memory,
original keypad handle/device identity, zero disconnects/supply-disable events,
POWER handback and loss-free keypad/Wi-Fi trace restoration pass. The one-second
level-5 warning passes its software checks and restores controls. PM is 3/0,
all failure counters are zero, SDIO usage remains 2 with unchanged runtime
policy, and brightness/backlight power returns to 1/0.

One of five collection attempts fails before the original completed result is
retrieved. Paramiko logs an SSH-banner read error; the calling collector records
`SSHException: No existing session`. The same attempt's `device.ssh` span fails
after 10.016 seconds. Its containing collection span lasts 19.920 seconds;
these nested intervals must not be added. The overall capture validates and
contains one PM submission. Nothing was resubmitted and no cable action was
requested. This is retained as a transport-collection failure, not silently
discarded because the PM result passes; cause and timing relative to device
availability remain to be established.

The original task log is `.local/neo138-platform-initial.log`. Offline timing
summary: `.local/neo138-platform-initial-timing.json`. Timing SHA-256:
`a1cb206d1bf2787964b4c58a861b7e4b7b49dd1a81f546eff0cb765e408c3578`.
The owner confirmed “All normal; ready for four cycles,” authorizing the repeat
batch below.

## Four late/noirq repeats

Each repeat used `task device:pm-platform WIFI_TRACE=1`. Its original completed
result was reviewed before the next was submitted. The owner confirms clear
warnings and normal dim-console returns after the full batch.

| Repeat | Capture beneath `.local/diagnostics/` | Run ID | Stage seconds | PM afterward | Result SHA-256 |
| --- | --- | --- | ---: | --- | --- |
| 1 | `20261007T095643.813925Z/cycle-1` | `bae498deb91f48e79ec962184ecb0a5f` | 7.889 | 4/0 | `d76b2c83567c9b598815430d59b37847ee1ccdfc87530433dfb0bd39d8cc5910` |
| 2 | `20261007T095821.527320Z/cycle-1` | `56a879ed0fac49b09754f9b9d9d1b9b9` | 8.044 | 5/0 | `597a175959666eb7e4d54e1567807918221e67d55dd06c6e603b25f0c1ac607f` |
| 3 | `20261007T095943.936001Z/cycle-1` | `733d808a3e3a413dbff56e8546bba2c4` | 7.843 | 6/0 | `691af820264b9d9123e43397facc06553266b2be0e0114c30ce7a6c3c4a0ca01` |
| 4 | `20261007T100116.061889Z/cycle-1` | `69816c6780c34bb694f720f87602ca5d` | 7.912 | 7/0 | `7a99a50fb7a61ef037f8aa2423c28654953633bfbaf7bb4a2ec8cdb112705c71` |

All four verify both independent SSH routes, original keypad retention, process
memory, POWER handback, long-warning playback/restoration and loss-free traces.
Every PM failure counter remains zero. SDIO usage stays 2 with unchanged runtime
policy, and brightness/backlight power remains 1/0. Stage durations include the
five-second debug delay and are not wake latency.

The saved offline `task check:sdio-ref-history -- --require-stable` accepts all
seven explicit result paths in chronological order. Its output is
`.local/neo138-reference-history.json`, SHA-256
`90b0858ca53cf8afe691203927be08d653916266d613a6cedd6703a6bc45c33d`.
Adjacent full PM counter snapshots match exactly, with successes progressing
0 → 7 and no intervening cycle. This file is the fresh qualification input for
the awake rehearsal; diagnostic.22's continuation is not reused.

Repeats 1, 2 and 4 each have one failed collection attempt followed by retrieval
of the original result and successful route proofs. Repeat 1 fails at the USB
tunnel with `No route to host`; repeats 2 and 4 fail in device SSH with
`No existing session` (repeat 4 also logs the banner-read error). Repeat 3's
complete timing capture has no errors. The PM tests were not resubmitted.
The saved trace identifies the affected host phase; it still does not establish
whether device/network unavailability extended beyond the expected debug
transition. The faster awake manager startup has not eliminated these collection
errors, so their investigation remains open.

The validated `host-timing.jsonl` hashes for repeats 1–4 are:

- `f0fec8af7c92cdc00678ad3f84415fd7ba0673dbcc3a24826ca950f5dc1e8b3f`.
- `9518972bbd220c0388a6cf4bfca13072c1fba5507a7d3e77f5c5c85430346647`.
- `95a553dbd34ad0c359eb9e1f972ba562c1ee159a476f45d6232379d1fe109f59`.
- `3b467c2281c1eddc8c81ea04eeb2509a2e220658388c32fc2be2e15d847c0bd6`.

Original logs and offline timing summaries are
`.local/neo138-platform-repeat-{1,2,3,4}.log` and the matching `-timing.json`
files. No source, driver, charging or audio-level change was made during the batch.

## Awake RTC rehearsal

The owner confirmed the complete batch and was informed that the next awake RTC
rehearsal keeps the screen on. It ran using the fresh seven-check history:

```sh
task device:sleep-rehearse QUALIFICATION=.local/neo138-reference-history.json
```

Capture: `.local/diagnostics/20261007T100317.640716Z/result.json`, run
`6dac26e6365247dea7ceeeb0d2664c7b`, SHA-256
`e4a7941e60067c904ba4aa79438d0cf5a047dc453a3bee2830e5107a1ec7c1fa`.
The original log is `.local/neo138-rehearsal.log`.
One RTC event arrives with flags `0xa0`; IRQ31 advances 1 → 2, and the original
disabled alarm is restored. Process memory and both SSH routes pass. POWER
input and the original logind policy are handed back, with no retained policy,
PM controls, RTC or console owner. Tracing restores. The same boot remains at
PM7/0, SDIO usage 2 and brightness/backlight power 1/0.

This validates awake alarm delivery and cleanup, not waking from sleep.
The validated host timing contains no errors; its SHA-256 is
`09fe6356bfd14d5183c4d1cfd2f3bfa4875098abb42c472b2ec22d5b175a9fd8`.
The owner then separately confirmed watching/listening readiness for actual sleep.

## First actual connected-USB RTC sleep

At source checkpoint `4186995`, the saved task was submitted once:

```sh
task device:sleep-rtc QUALIFICATION=.local/neo138-reference-history.json \
  REHEARSAL=6dac26e6365247dea7ceeeb0d2664c7b ATTENDED=1
```

Capture: `.local/diagnostics/20261007T100552.286876Z/result.json`, run
`17538b4f0c3a4d158beb9e2b3cc38088`, SHA-256
`8ccfbb6483f4c0895c161486c40f6044ca9ccb89b65873f94d53a8551810520a`.
The original log is `.local/neo138-first-sleep.log`.

Functional RTC wake, both independent SSH routes, process memory and original
keypad retention pass. Keypad, USB and Wi-Fi traces restore without loss.
The one-second level-5 warning passes playback/restoration checks; the owner
confirms hearing it and seeing the normal dim console return without touching
the cable or controls. POWER input and the original logind policy return, with
no retained policy, drop-in, PM controls, RTC or console owner.

RTC IRQ31 advances 2 → 3 with one alarm event (`0xa0`). The alarm-to-return
interval is 31.768 seconds; entry-to-return is 31.160 seconds. The complete
trace supports 28.748 seconds inside the actual s2idle boundary, with all four
late/noirq phases and RSB noirq suspend/resume present. No timekeeping freeze
pair is observed; the clock gap is within sampling uncertainty. These are
sleep/diagnostic intervals, not normal wake latency or CPU-residency evidence.

Final PM is 8/0, every failure counter is zero, SDIO usage stays 2 with unchanged
runtime policy, and brightness/backlight power is 1/0 on the original boot.
This first connected-USB sleep is functionally qualified; repeated sleeps,
other power/cable profiles, CPU retention and energy remain separate work.

## Sleep collection timing and its limits

The actual sleep's host timing capture validates with no errors and one PM
submission. Seven collection clock samples were recorded. One successful
`clock.sample` span lasts 35.403 seconds, mainly a 35.232-second command-response
wait. The sampled device BOOTTIME is 1739.085768 seconds, near the recorded
entry at 1738.937384 seconds; the result was delivered after the sleep interval.
Do not treat this whole command duration as a delay after resume.

For an explicit bounded comparison, the shortest post-return sample brackets
device BOOTTIME 1799.339492 seconds within a 0.637073-second host span. If
`Hbegin` and `Hend` are that host span's monotonic endpoints and `C` is the
sampled device BOOTTIME, the clock-offset interval is `[Hbegin-C, Hend-C]`.
Mapping the recorded return at 1770.096935 seconds through that interval puts
the long collection span's end approximately 3.80–4.44 seconds after return.
Its start lies about 0.45 seconds before to 0.19 seconds after the entry sample.
These bounds assume negligible relative clock drift over this short capture;
they are transport/sample brackets, not exact network-ready times.

The evidence shows a successful response spanning sleep and a remaining
post-return tail. It does not attribute that tail to kernel resume, SSH
scheduling, TCP retransmission or host USB handling. Nor does a successful
command prove the cause of the separate late/noirq collection failures.
Their timestamped evidence remains available for analysis without another
physical test.

Offline timing summary: `.local/neo138-first-sleep-timing.json`, from
`task device:ssh-timing-report CAPTURE=.local/diagnostics/20261007T100552.286876Z`.
Original timing SHA-256:
`eb746be671b22c926f812e6af60d6b2564a17f35aa10fd3b7410b336a61cec24`.

## Next qualification

The unused continuation is
`.local/diagnostics/20261007T100552.286876Z/qualification-next.json`, SHA-256
`89a9e9a983b1533a065218decf2ad6f141f2ae10a873dc837f0603ffecb80c06`.
It contains seven debug references and this one actual sleep. The original awake
rehearsal is `6dac26e6365247dea7ceeeb0d2664c7b`.
Next, obtain readiness for a bounded four-cycle connected-USB actual-sleep batch,
reviewing each original result and preserving the continuation lineage. No
further sleep test is running at this completed checkpoint.
