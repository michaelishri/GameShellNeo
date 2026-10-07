# Diagnostic.23 suspend/resume qualification

7 October 2026; capture timestamps are UTC. NEO-138 is in progress.
The initial freezer, driver and first late/noirq debug checks pass on diagnostic.23/kernel
`6.18.54-gameshellneo22`, boot `7cc788ef-2070-4ab9-887a-1af70c074713`.
The owner confirms the clear warning and normal dim-console return, and gave
readiness for the first late/noirq check. Its separate display observation and
readiness for repeats are pending. Rehearsal and actual sleep remain unqualified.
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
The owner has been asked to confirm this stage's warning/display and readiness
for four repeats. No further screen test is running at this checkpoint.

## Remaining qualification

After the owner's observation/readiness response, review each of four repeats
before advancing. A complete same-boot debug history is required before the
awake RTC rehearsal and an actual RTC-wake attempt. No real sleep has run on
this kernel at this checkpoint.
