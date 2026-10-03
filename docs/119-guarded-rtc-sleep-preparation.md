# Guarded RTC-wake sleep preparation (NEO-93)

3 October 2026, Pacific/Auckland. Added a separate one-shot s2idle recorder and
an awake rehearsal. Diagnostic.17's kernel and normal sleep policy are unchanged.
Both awake rehearsals pass, including the final helper revision.
The separately attended real-sleep attempt is ready for observer readiness. No actual sleep has been submitted
in this preparation.

[Report 118](118-diagnostic17-hardware-qualification.md) supplies the completed
freezer/driver/five-late-noirq baseline and stable SDIO references. The remaining
boundary is entry into the idle loop with a real timed wake, rather than the
five-second debug return. This is Linux s2idle, not A33 DRAM retention/Crust.
[Linux sleep-state documentation](https://docs.kernel.org/admin-guide/pm/sleep-states.html)
distinguishes `freeze`/s2idle from suspend-to-RAM.

## Separate commands and admission

```sh
# Awake only; no write to /sys/power/state or /sys/power/wakeup_count.
task device:sleep-rehearse QUALIFICATION=.local/neo92-final-reference-history.json

# Only after fresh readiness to observe this particular real-sleep attempt:
task device:sleep-rtc QUALIFICATION=.local/neo92-final-reference-history.json REHEARSAL=<successful-run-id> ATTENDED=1

# Retrieve the exact original run after uncertain SSH; never repeat submission.
task device:sleep-collect RUN=<original-run-id>
```

These are saved Taskfile workflows implemented by
[the host controller](../tools/check-sleep-rtc.py) and
[the device recorder](../tools/sleep_rtc.py). Existing `device:pm-*` debug-stage
commands still reject real sleep. The host requires the explicit attended flag
before accessing the device; the device CLI separately requires it for real
sleep. A flag does not replace the observer's readiness response.

The host recomputes qualification from explicit saved results referenced by
the supplied reference-history file. It requires both-route proofs, one freezer,
one driver and five platform cycles, one boot/image, stable usage 2, complete
late/noirq traces and no intervening PM generation. A receipt identifies those
seven runs and hashes their complete device results. The device verifies the
receipt against its own persistent originals, checks current health and the
wake/SDIO patch identities, and requires the same-boot awake RTC qualification.
The actual-sleep mode additionally requires a successful awake rehearsal with
identical helper-source hashes, boot and PM counters. Changed code requires a
new rehearsal. Another active diagnostic or unresolved ownership prevents entry.

This deliberately admits one first experiment: a completed real PM attempt
changes the counters, so that baseline cannot silently admit another attempt.
Further repetitions require review and an explicitly extended protocol.

## Entry, deadline and evidence

The device holds the shared PM experiment lock, the ancestor logind inhibitor,
the original exclusive PEK input handle and the independently persistent
boot-local ignore policy from [report 113](113-diagnostic-power-key-policy.md).
It records the original key IRQ counts and refuses any event/dispatch during
this RTC-only experiment. Keypad and Wi-Fi tracing retain their existing
restoration and no-loss checks. Audio must be idle.

A distinct owned record protects the temporary serialized (`pm_async=0`)
setting. The helper requires `pm_test=none` already selected and never unmasks
normal sleep or changes that selector. Disk synchronization finishes before
arming the **30-second RTC deadline**. The original disabled alarm is saved;
an enabled/pending foreign alarm is rejected. Programming uses `/dev/rtc0`
`RTC_WKALM_SET`, followed by logical alarm readback. The RTC time itself is never
set. Ownership carries this run's ID and is restored on ordinary return/error.

Before the single state write, the recorder:

1. Rechecks untouched input/inhibitor ownership.
2. Reads `wakeup_count` in a subprocess with a three-second timeout.
3. Requires at least **15 seconds** remaining on its unchanged RTC alarm.
4. Flushes a durable entry-intent record containing the mode, counter and controls.
5. Rechecks the key, alarm margin and live controls, writes the saved wakeup count
   once, then writes `freeze` once. Any rejection is preserved without retry.

The kernel's `wakeup_count_show()` calls `pm_get_wakeup_count(..., true)` and can
wait for an active wake source; nonblocking-open flags do not bound this sysfs
callback. The subprocess timeout bounds the awake read. The read/write handshake
rejects events arriving before entry; it is not an asleep watchdog.
[Upstream sysfs power ABI](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/ABI/testing/sysfs-power).
The exact inspected implementation is pinned Linux 6.18.54:
`kernel/power/main.c:778–844` and `drivers/base/power/wakeup.c:953–1018`.

The service is device-owned, without an SSH output pipe. A lost connection
collects the same saved run ID rather than resubmitting PM. Its persistent
entry/result files are under `/var/lib/gameshellneo/sleep-tests/<run>/` with
file and directory synchronization. Host copies, exact helper hashes, receipt,
submission errors and collection errors stay in `.local/diagnostics/<capture>/`.

## What counts as RTC sleep/wake success

A successful sysfs write alone is insufficient. The recorder requires:

- Exactly one RTC alarm notification already available at return, with
  `RTC_IRQF | RTC_AF`, the expected R_INTC hardware-40 mapping, and one increment
  of that RTC interrupt count. It does not wait awake for a later alarm and then
  mislabel an early wake as RTC success.
- `pm_wakeup_irq` matching the qualified RTC Linux IRQ, a bounded alarm-time
  window, and at least five seconds of suspend time from the difference between
  BOOTTIME and MONOTONIC elapsed times. This timing is diagnostic evidence, not
  a calibrated current or production latency measurement.
- One `machine_suspend[1]` begin/end inside the late/noirq trace boundaries,
  no callback errors/lost records, and normal RSB suspend/resume callbacks.
- One PM success with no new failures, preserved process memory and original
  keypad handle/identity, stable SDIO accounting, intact kernel history,
  restored PM/radio/charging/display settings and idle audio.
- Both USB and independent Wi-Fi SSH returning on the original boot. The owner
  must separately confirm normal visible console/brightness.

The pinned `s2idle_enter()` emits the machine-suspend boundary even if its
pending-wake check returns immediately. Therefore the trace marker alone is not
proof of residency. `kernel/power/suspend.c:91–158` and
`kernel/time/tick-common.c:510–583` explain the idle/timekeeping paths used by
the combined timing and trace checks.

## Handoff and failure handling

Before restoring logind's ordinary shutdown policy, a continuously held guard
must see **no input events and no PEK press/release IRQ increments**, a released
healthy input handle, the expected PM generation and the same policy/process
identity. These checks bracket policy restoration. They are specific to the
untouched RTC experiment: Linux clearing a held key at suspend is not physical
release proof, and a power-key wake is not accepted by this test.

An event or cleanup error during final handoff fails the run. If ordinary policy
was already restored, the still-inhibited controller attempts to re-establish
its ignore policy before exiting and records whether that succeeded. It never
removes or overwrites a foreign ownership marker. The host also rejects a
result with recorded key events or incomplete handoff.

The saved service cleanup uses the original helper's `--recover --run-id`.
It attempts only RTC, PM and trace resources tagged for that run, retaining
errors and foreign owners. It **never restores poweroff policy after an unknown
controller interruption**. No unconditional power-policy cleanup command was
added. A retained ignore policy means the short button no longer requests
shutdown; preserve the result and use the established remote shutdown/cold-boot
recovery after review. Do not delete markers or blindly rerun the experiment.

The RTC can wake a functioning suspended kernel; it cannot fix a deadlocked
resume path. The systemd runtime limit and cleanup code cannot run while frozen
or inside a stuck kernel operation. USB also suspends, and there is no connected
UART or persistent kernel crash log. A durable intent without a completed result
records an interrupted attempt, not its failing callback. The existing PMIC
cutoff and physical recovery limits remain unchanged. The production short/
2-second/8-second gestures and physical key-wake qualification are separate work.

## Validation

The new failure tests exercise admission/provenance, changed boot/image/counts,
missing both-route evidence, bounded counter read, no-write rehearsal, exact
one-shot ordering, failed/short writes, expired/foreign alarms, durable intent,
ownership-scoped restoration, continued cleanup after an error, trace/residency
attribution and untouched-key policy handoff. Late cleanup failures re-arm
suppression in the policy model; foreign ownership is retained. Existing policy
process-death tests remain in the full suite.

```sh
python3 -m unittest discover -s tools/tests -p test_sleep_rtc.py -v
task check
```

**24 new tests**, **13 runtime and 423 tooling tests** pass (one existing optional
skip), along with the C helper regressions and shell lint. These host fixtures
cannot establish physical wake delivery or arbitrary kernel-hang recovery.
Evidence: `.local/neo93-targeted-tests.log` and `.local/neo93-host-check.log`.
No kernel rebuild or card swap is needed for these diagnostic helpers.

The first awake rehearsal, run `4048a2ff28ff47e4ac05d6893e31f095`, passed on
boot `0dc9db12-dcb4-465d-853c-1a087d9af332`, kernel `6.18.54-gameshellneo17`.
The alarm arrived after **30.846 seconds**, RTC IRQ 31 advanced 1→2, PEK events
remained empty and PM counters remained 7 successes/0 failures. All owned
controls/alarms/policy were restored and both SSH routes passed. Evidence:
`.local/diagnostics/20261003T025950.381724Z/` and
`.local/neo93-awake-rehearsal.log`. That helper revision predates the final
handoff refinement; its rehearsal cannot admit the revised real-sleep command.

The final rehearsal, run `038a2d53ea5f49b7b78cadab1cbe7660`, passed on the
same boot using the final helper sources. The alarm arrived after **30.391
seconds**, with 29 seconds remaining at the recorded entry-margin check. RTC
IRQ 31 advanced 2→3, PEK events stayed empty and PM counters remained **7/0**.
SDIO usage remains **2**, with the original forbidden/control-on policy. Idle
audio, alarm, PM controls, key policy and both SSH routes all passed. No
ownership marker or ignore drop-in remains. The separately retrieved service
cleanup record reports no errors, and the transient service has exited.

Final evidence: `.local/diagnostics/20261003T030252.553566Z/`,
`.local/neo93-final-awake-rehearsal.log`,
`.local/neo93-final-rehearsal-cleanup.json` and `.local/neo93-final-unit.log`.
This completes preparation and awake qualification. RTC wake from actual sleep,
physical wake gestures and energy/latency remain unqualified.
