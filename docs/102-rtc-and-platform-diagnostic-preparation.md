# RTC deadline and late/noirq preparation (NEO-80)

2 October 2026. Prepares the next attended boundary described in
[report 98](98-shallow-sleep-readiness.md). No late/noirq or actual-sleep test
has been submitted. The running board remains diagnostic.13.

## RTC result and ownership

The saved awake test delivered one `RTC_IRQF | RTC_AF` notification for a
requested ten-second alarm, then restored the original disabled logical alarm.
The accepted exact-run result is
`.local/diagnostics/20261002T102154.963254Z/result.jsonl`, run
`8f8c0e16399544a8b82b21f00827897f`. Delivery took 10.492 seconds, within the
fixed 8–15 second acceptance window. The board stayed awake; neither the RTC
clock nor any power/charging policy was changed.

An earlier device run also delivered/restored successfully at 10.807 seconds,
but its host wrapper incorrectly selected the last JSON line, which belonged
to `ExecStopPost` cleanup. That host failure is preserved at
`.local/diagnostics/20261002T101804.636032Z/`. The corrected parser selects one
exact run ID and rejects missing or duplicate results; a regression covers
the extra cleanup message. The later complete host/device run passed.

The helper uses the Linux RTC character-device UAPI, with explicit 36-byte
`rtc_time` and 40-byte `rtc_wkalrm` layouts on the host and ARM32. It rejects
an existing enabled alarm, records the original disabled state before mutation,
uses RTC time for the deadline, checks logical readback, waits for the alarm
notification with a fixed timeout, and restores/readbacks the original state.
It never uses `RTC_SET_TIME`. The source's `RTC_WKALM_RD` returns the RTC core's
logical alarm; it is not independent hardware-register readback and its pending
field is not a hardware pending-bit observation.

Both normal and failed operations restore through the saved owner. A boot,
controller or alarm change prevents overwriting another owner's alarm.
Systemd also runs independent cleanup after process exit. Operation and
restoration errors are recorded separately. Device-owned records are under
`/var/lib/gameshellneo/rtc-tests/<run-id>/`, with the interrupted ownership
record at `/run/gameshellneo-rtc-alarm.json`. Alarm IRQ delivery while awake
does **not** qualify wake from a sleeping CPU, deep suspend, or recovery from
a hung resume. Other kernel alarmtimer users need a single ownership policy
before a product sleep controller is introduced.

```sh
task device:rtc-inspect  # Read current RTC/calendar/logical alarm
task device:rtc-smoke    # Ten-second awake delivery and restoration
task device:rtc-restore  # Recover saved same-boot ownership after interruption
```

Inspection does not install a cleanup hook or change an alarm. Restoration
requires the saved record and refuses foreign state. A failed run is not
silently resubmitted. Private host captures retain its helper directory and
run ID for investigation.

The final shared-lock version also passed on diagnostic.13: power-key smoke
capture `20261002T103246.186323Z`, followed by RTC capture
`20261002T103254.681594Z`, run `143aaef77ea24b3882308d37890a4e65`, with one alarm
notification after 10.279 seconds and successful restoration. Final read-only
PM capture `20261002T103307.857613Z` retained the same boot, `pm_test=none`,
`pm_async=1`, and the original PM success/failure counters. No PM test was run.

## Guarded platform diagnostic

```sh
# Only after installation, preflight and explicit owner readiness:
task device:pm-platform
```

This is one `pm_test=platform`, `state=freeze` debug cycle. The pinned kernel
runs device late/noirq callbacks and their reverse callbacks, with the existing
five-second debug return **before** `s2idle_loop()`. The command never selects
`none`, `core`, `processors` or `mem`; normal sleep targets remain masked.
A userspace runtime deadline cannot recover a kernel stuck inside resume, so
this new boundary requires an attended first test.

Admission requires:

- The existing exact image/kernel/radio/health checks and both management routes.
- An image manifest containing the exact checked wake-ownership patch 0019.
- Disabled Armbian RAM logging and no loaded logrotate pre/post hooks.
- A passed, restored awake RTC delivery record from the same boot and kernel,
  plus a currently disabled alarm and no unresolved RTC owner.
- Exclusive power-key ownership, a verified diagnostic inhibitor, and PM/keypad
  tracing. The power key must remain untouched; no gesture experiment is mixed
  into this first boundary test.

A shared device-side nonblocking lock excludes concurrent RTC alarms, standalone
power-key ownership checks, PM experiments and explicit PM recovery. There is no automatic retry.
The existing transient service, independent restoration, durable PM records and
exact-run collection remain. Asynchronous PM is temporarily disabled, restored
and checked. A readback immediately before entry must still show the selected
debug stage and five-second delay. Wi-Fi metadata capture accompanies the fixed
platform command; its restoration and both independent SSH routes must pass.

Trace qualification requires one correctly ordered begin/end pair for each of
`dpm_suspend_late`, `dpm_suspend_noirq`, `dpm_resume_noirq` and
`dpm_resume_early`. RSB must have a successful, matched noirq callback within
both the suspend and resume intervals. Nonzero callback errors, missing events,
overruns, unrestored tracing and actual-sleep trace markers reject the run.
The original trace is retained for examining other devices and ordering; these
checks do not assert that every possible late access or race has been excluded.

The power-key controller's abnormal-termination limitations in
[report 101](101-diagnostic-power-key-ownership.md) still apply. Actual sleep
remains blocked pending independent gesture ownership and attended wake tests.

## Host qualification and source basis

Ten RTC tests cover the UAPI layouts, calendar rollover, IRQ type/count,
existing alarm refusal, ownership/restore errors, timeout cleanup, same-boot
qualification, exact-run parsing and concurrent-owner rejection. Five platform tests cover admission,
trace loss/order/error mutations, service guards, explicit entry admission and
restoration. Existing PM tests continue to cover rejected stages, control
readback races, killed-worker restoration and ambiguous SSH submission.
These are deterministic host checks, not kernel scheduling or physical wake
qualification. The final `task check` passed 13 runtime and 346 tooling tests (one existing
optional skip), compiled helpers and shell lint. Log: `.local/neo80-host-check.log`.

Implementation references are the pinned Linux 6.18.54 sources:
`include/uapi/linux/rtc.h`, `drivers/rtc/{dev,interface,rtc-sun6i}.c`,
`kernel/power/suspend.c`, `drivers/base/power/main.c` and
`include/trace/events/power.h`. Report 98 links the upstream sources and explains
why `platform` is the next valid s2idle debug boundary.

## Prepared attended sequence

1. Install diagnostic.14 after fresh card identification, full flash readback
   and ejection. Confirm the normal login screen. Preserve diagnostic.13
   recovery and the original card backup.
2. Verify the installed image, services, journal policy and both SSH routes.
   Run the saved awake power-key ownership and RTC alarm checks on this new
   boot. Earlier diagnostic.13 RTC evidence cannot satisfy the platform gate.
3. With explicit readiness, run a freezer check and one ordinary `devices`
   cycle with power-key ownership and traces. Confirm the dim console returns.
4. With fresh readiness for the new boundary, run one `device:pm-platform`.
   Keep USB connected and controls untouched. Inspect its trace and independent
   restoration/recovery before considering any repeat batch.
5. Preserve any failed/interrupted evidence and recover before another attempt.
   Do not infer actual wake or energy savings from debug passes. Physical
   waking-key behavior and the product short/2-second/8-second gestures remain
   separate, supervised qualification work.
