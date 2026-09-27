# USB detection capture

Date: **2026-09-28 NZDT** (27 September UTC).
Ticket: **NEO-14**. Target: CPI v3.1, diagnostic.3,
Linux `6.18.54-gameshellneo3`.

## Purpose

[Report 34](34-usb-status-polling-investigation.md) found that the AXP223's
50 ms USB polling compensates for modes in which physical VBUS changes lack
the required interrupt. Before changing that policy, capture the board's
existing mode, interrupt delivery and observable USB recovery using the
unchanged kernel. This is functional instrumentation, not a power benchmark
or proof of the physical USB detection deadline.

## Shared workflow

```sh
task device:usb-detect CYCLES=0 SECONDS=8
task device:usb-detect CYCLES=4
```

Start with the board running on battery and USB unplugged. The first command
is a smoke capture with no cable actions. The second uses Wi-Fi for control,
starts an independent on-device recorder and prints `ready`. Each of four
cycles is: connect USB for twenty seconds, disconnect for ten seconds. Finish
unplugged. Each attachment must reach authenticated USB SSH through the Mac on
the original boot, followed by a settled disconnected state. Initial
attachment, unverified attachment and overlapping cycles cannot count as
successful cycles. A one-second settling interval includes late removal IRQs.

[The recorder](../tools/record-usb-detection.py) takes nominal 20 ms snapshots
of the UDC state, cached MUSB OTG mode, PHY extcon state and PMIC IRQ counters.
The counters are identified by the AXP22x hardware interrupt resources rather
than assuming fixed Linux IRQ numbers. It receives kernel-originated
power-supply netlink events separately. Supply properties and battery-guard
health are read at startup, about once a second, and after sampled state
changes. It records sample start/end times, the preceding observation time,
sampling gaps and process CPU cost. It does not dump MUSB registers that may
have interrupt side effects.

[The host task](../tools/check-usb-detection.py) saves the trace privately,
validates sequence/boot/time/counter integrity, and verifies USB SSH separately
from the Wi-Fi observer. Host and device monotonic clocks are separate; their
raw readings must not be subtracted across machines. USB SSH check duration
includes Mac authentication, forwarding, routing and device authentication.
It is not a controller detection latency.

The recorder stops on invalid/stale battery monitoring, charge at or below
20%, kernel taint, unexpected hardware/configuration, failed reads, counter
resets or netlink receive/truncation errors. It has an internal duration and a
systemd cap. Clean recorder completion stops the service and removes staged
files, including when the requested cycle validation fails. Local evidence is
retained; an incomplete trace or failed cleanup also leaves the remote files
for recovery and attempts to capture the diagnostic journal. A second
run refuses an existing unit; the host lock is shared with the older USB
reconnection task. [Host regressions](../tools/tests/test_usb_detection.py)
check malformed/reset/missing counters, spoofed/unrelated netlink messages,
partial traces, boot/sequence errors, initial and unverified connections,
delayed removal interrupts, overlapping cycles and failure cleanup ownership.

## Read-only configuration check

The precheck reached the board through USB with six healthy services, zero
restarts, no failed units and no taint. The battery reported 83% Charging and
**4.2658 V**, again above its reported 4.2000 V charge target. This is the
existing NEO-10 discrepancy, not a newly established electrical diagnosis.
The owner disconnected USB while the host prepared the test and confirmed
continued battery operation. Charger/current/gauge settings were untouched.

Private precheck: `.local/diagnostics/20260927T113900.321394Z/status.txt`.
Boot ID throughout preparation: `9da0aa56-198a-4e1b-96cb-b9f41b3dc4e2`.

The helper verifies the locked AXP223 debugfs layout (`0-e6`, 8-bit registers
and seven-byte formatted rows), then uses individual positioned reads for
**only** registers `00`, `30`, `40` and `8f`. It never reads the IRQ-status
registers as part of this configuration check, changes cache controls or
bypasses regcache. Local source establishes that `00`/`40` are volatile, while
`30`/`8f` may be served from cache. See `drivers/base/regmap/regmap-debugfs.c`
and `drivers/mfd/axp20x.c` in the locked kernel; register definitions are in
report 34's supplied AXP223 datasheet references.

The smoke capture recorded:

| Observation | Value / interpretation |
| --- | --- |
| Power-supply compatible | `x-powers,axp223-usb-power-supply` |
| Live DT USB role | `peripheral` |
| PMIC `00` | `0x01`; USB present/usable bits clear in this unplugged sample |
| PMIC `30` | `0x60`; bit 7 clear (N_VBUSEN path selection applies), bit 2 clear (DRIVEVBUS output low when in output mode) |
| PMIC `8f` | `0x01`; bit 4 clear (DRIVEVBUS output mode) |
| PMIC `40` | `0x6c`; USB plug/removal enable bits 3/2 both set |
| Supply properties | USB and AC both absent/offline |
| UDC / OTG / extcon | `not attached` / `b_idle` / `USB=0`, `USB-HOST=0` |
| Regulator summary | Keypad supply is a USB1 consumer; no USB0 VBUS source regulator shown |
| USB IRQ counts | Plug 0, removal 1; these are cumulative counts since this boot |

These control values are consistent with a non-driving peripheral setup and
enabled USB interrupts. Cached control values are not independent measurements
of the pin, external power switch or charger behavior. Successful cable
transitions add evidence about the currently exercised configuration;
they cannot establish all PMIC modes or unsupported host behavior.

## Validation before cable actions

`task check` passed 13 runtime tests and 58 tool tests (one optional user-systemd
case skipped), compiled current-limit regressions and shell lint. The sixteen
new USB tests passed. No kernel or image rebuild was needed.

Two eight-second smoke captures ran on battery. The first verified staging,
hardware reads, recorder completion, trace download and cleanup. Its CPU metric
included process setup, so the helper was corrected to report capture CPU time
separately from total process CPU time. The second used that corrected metric:

- Private evidence: `.local/diagnostics/20260927T114823.084243Z/`.
- 400 samples in 8.0048 seconds; largest observed sample-start gap 22.96 ms.
- Capture CPU time 3.3186 seconds; total process CPU time 3.7488 seconds.
- Battery monitoring valid, 84% Discharging; all supply inputs offline.
- Clean final marker, service shutdown and temporary-file removal passed.

The observed CPU cost is substantial, about 41% of one CPU according to the
process clock. This is intentionally short-lived diagnostic work. It rules
out interpreting this trace as an idle-power measurement and can influence
scheduling/clock behavior. The CPU-accounting uncertainties already recorded
in reports 31–33 remain relevant. A nominal 20 ms interval is not guaranteed
under all loads, and software observations lack a physical cable-edge time.

## Four-cycle hardware capture

Private directory: `.local/diagnostics/20260927T115015.290966Z/`. The recorder
reached `ready` at 11:50:22 UTC. The host verified USB SSH for the first three
connections, taking 1.18, 1.32 and 1.21 seconds for the individual SSH checks.
These durations start when the host attempted verification, not at cable insertion.

The existing Wi-Fi transport subsequently timed out. The on-device service
continued recording independently, and a fresh Wi-Fi session recovered access.
The original host `summary.json` remains **failed**: this is not rewritten as
an automatically passed batch. The recovered trace is retained separately as
`recovered-device-trace.jsonl`; sequence, boot, clock and counter validation
passed, including the clean final marker after the service was stopped.

The trace recorded **six attachments and five removals**. The owner clarified
that the cable was still connected and they may have performed five
disconnections. This explains the extra transitions; they are not evidence of
spontaneous reconnects. All five complete observed cycles advanced both USB
plug and removal counters once, and the final attachment advanced the plug
counter once. AC input IRQs followed the same pattern, consistent with the
published shared-input wiring. All six attachments reached UDC `configured` /
OTG `b_peripheral`; all five removals reached `not attached` / `b_idle`.
Only the first three USB SSH returns were verified by the original host run.

For all six attachments, a USB power-supply online notification was received
before the first sample with an advanced plug-interrupt counter. The observed
leads were **90.58, 112.73, 91.36, 70.12, 66.90 and 114.13 ms**. This ordering
is consistent with the existing poll finding input power before the later
plug IRQ. It is not an electrical-edge timestamp, an exact hardware IRQ delay
or a guarantee that IRQ-only detection meets the MUSB deadline. Removing
polling may change detection latency even in this apparently receptive mode.

The recovered recorder ran for 262.220 seconds, taking 13,067 snapshots. Its
largest observed start-to-start gap was 46.70 ms; no gap exceeded the 100 ms
warning threshold. Capture process CPU time was 116.298 seconds, reinforcing
that this is an intrusive diagnostic, not an idle-power run. No loss/truncation
error was reported, although that does not establish event completeness beyond
the available software interfaces. Temporary remote files were removed after
recovery; the failed summary and full evidence remain private.

The collector had repeatedly downloaded the growing trace. That imposed
unnecessary network traffic, especially on the known weak Wi-Fi connection;
the exact cause of the transport timeout is not established. The task now
fetches only appended data in at most 32 KiB SFTP reads, retains a byte offset,
rejects truncation and reconnects once for failed read-only/idempotent commands.
It does not blindly replay service creation or other startup mutations. New
regressions cover bounded incremental reads, stale transport recovery and
failed retry limits. The final one-cycle check below validates the corrected
workflow; no kernel or driver behavior has changed.

An eight-second smoke capture of the corrected transfer path passed at
12:03:59 UTC, including file ownership, incremental download and cleanup.
Private evidence: `.local/diagnostics/20260927T120343.770848Z/`. It recorded
400 samples in 8.0103 seconds, a largest gap of 32.29 ms and 3.4498 seconds of
capture CPU time. The board remained unplugged on the same boot.

## Final corrected-workflow check

`task device:usb-detect CYCLES=1 SECONDS=300` passed at 12:05:38 UTC.
Private evidence: `.local/diagnostics/20260927T120411.949334Z/`. The owner
performed one connection and removal, then confirmed continued battery operation.

- USB SSH authenticated on the original boot and verified the USB endpoint and
  configured controller. One initial SSH attempt failed with `No existing
  session`; the next succeeded, taking 1.551 seconds. This duration excludes
  the failed attempt and is not end-to-end reconnection latency.
- USB plug and removal IRQ counters each advanced once, as did AC counters.
  The settled final sample had both power inputs absent/offline, UDC
  `not attached` and OTG `b_idle`.
- The trace completed with 3,920 samples in 78.758 seconds. Its largest observed
  sampling gap was 50.86 ms, with no gap above 100 ms. Capture CPU time was
  35.174 seconds, about 45% of one CPU.
- The online notification preceded the first advanced plug-counter sample by
  122.48 ms. Together with the first batch, this reinforces the need to assess
  notification timing before replacing polling with IRQ-only detection. The
  observation is subject to the same sequential-read and observer limits.
- Incremental trace retrieval, final validation, service stop and removal of
  the staged files passed without transport recovery during trace collection.

The battery guard was valid throughout, but its ten-second update interval
means a snapshot immediately after unplugging can still contain the previous
Charging record. The final cycle included a reported 4.2636 V charging sample;
the existing NEO-10 voltage discrepancy remains unresolved. Supply properties,
guard freshness and guard status are separate observations.

Postcheck at 12:06:24 UTC found all six monitored services healthy with no
restarts, no failed units and no kernel taint. The board remained on the same
boot, with USB detached and battery monitoring valid at 84% Discharging,
3.8951 V. Both corrected-run temporary directories were absent and the
recorder unit was unloaded/inactive. No kernel warning-or-higher journal
entries were present since 11:39 UTC. An initial postcheck SSH connection
failed with `No existing session`; a fresh invocation succeeded. Wi-Fi
reliability remains a separate limitation. Private status evidence:
`.local/diagnostics/20260927T120623.681311Z/status.txt`.

## Consequences for the optimization

Observed plug/removal interrupt delivery makes a software policy improvement
worth pursuing in this fixed peripheral configuration. It does not justify
simply deleting the 50 ms poll: the existing software notifications arrived
before sampled plug-counter changes in every recorded attachment. The next
design needs an explicit role/input-path contract and a prompt detection path,
including initial reads, errors, relevant transitions and eventual resume.
Boot-attached/boot-unplugged coverage and timing under that candidate remain
open in [FOLLOW-UP](../FOLLOW-UP.md).

This ticket establishes reusable instrumentation and observed behavior. It
does not establish energy savings, physical-edge timing, all-mode interrupt
coverage or charging accuracy. No kernel/image rebuild or PMIC writes were
performed. The original batch remains marked failed despite recovery of its
complete on-device evidence; the corrected smoke and single-cycle runs passed.
