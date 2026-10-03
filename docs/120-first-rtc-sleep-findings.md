# First RTC-wake s2idle attempt (NEO-94)

Later recovery: [report 121](121-usb-reconnect-and-clean-boot.md) records the
owner's delayed same-boot console confirmation, an intervening Mac sleep/cable
reconnect, one successful prompted USB reconnect and a clean reboot restoring
ordinary diagnostic power-key handling. The original failed result below is
unchanged.

3 October 2026, Pacific/Auckland. Diagnostic.17 completed its first actual
`freeze` request and the RTC woke the kernel. The attempt **failed overall
qualification**: USB networking did not recover. Independent Wi-Fi SSH returned
on the original boot, allowing the original failure record to be preserved.
No second sleep request, reboot or policy cleanup was performed; no cable
change was requested.
The owner's visible-console confirmation is pending.

The experiment also exposed an incorrect assumption in the preparation's
residency check: this image has no registered CPU-idle driver, and its clocks
did not show stopped timekeeping. Functional s2idle/RTC wake and efficient CPU
sleep must be assessed separately. Neither battery savings nor deep retention
is established by this attempt.

## Identity and admission

- Image: `0.1.0-diagnostic.17`; kernel `6.18.54-gameshellneo17`.
- Boot: `0dc9db12-dcb4-465d-853c-1a087d9af332`.
- Attempt: `fe04cfff33b947f7bfa927f707cf144b`.
- Final-source awake rehearsal: `038a2d53ea5f49b7b78cadab1cbe7660`.
- Prerequisites: the seven accepted debug-stage records in
  `.local/neo92-final-reference-history.json`, with PM success 7/failure 0,
  SDIO usage 2 and both network routes working.

After fresh observer readiness, the saved command was submitted once:

```sh
task device:sleep-rtc QUALIFICATION=.local/neo92-final-reference-history.json REHEARSAL=038a2d53ea5f49b7b78cadab1cbe7660 ATTENDED=1
```

The device owned the key suppression, RTC alarm and temporary PM/trace controls.
It saved intent with `pm_test=none`, `pm_async=0`, and 29 seconds of alarm margin.
The host's repeated connection attempts only collected that same run; they did
not resubmit sleep. See [report 119](119-guarded-rtc-sleep-preparation.md) for
the original preparation and its recovery boundaries.

## What returned

| Observation | Saved result |
| --- | --- |
| Sleep path | One `machine_suspend[1]` begin/end, correctly inside late/noirq boundaries |
| Time between those markers | 28.948584 seconds; both markers on CPU3 |
| Wake attribution | `pm_wakeup_irq=31`, matching the qualified RTC interrupt |
| RTC notification | Immediately available at return: one event, flags `0xa0` (`RTC_IRQF \| RTC_AF`) |
| RTC interrupt count | 3 → 4; RTC wakeup-source count 0 → 1 |
| Alarm-to-return elapsed | 32.138928454 seconds, including entry/resume overhead |
| PM counters | Success 7 → 8; failure and individual failure-stage counters remain 0 |
| Process memory | Preserved |
| Keypad | Original handle, USB attributes and input paths retained |
| SDIO reference accounting | Usage 2 → 2, active, runtime forbidden/control `on` |
| RSB supplier accounting | Usage 2 → 2 in these two snapshots |
| Traces | Complete, no overrun/loss; both trace configurations restored |
| Settings | PM controls, display settings, radio configuration/power-save, charging and CPU policy unchanged |
| Audio | Idle state unchanged; no playback test performed |
| Kernel history | Original prefix retained; no new failure reported in PM counters |
| Wi-Fi SSH | Independently verified on the original boot |
| USB SSH | Did not recover; UDC `configured` → `not attached` |

The device's exact first failure is:

```text
ValueError: Device must be healthy, USB-powered and connected to Wi-Fi; failed: usb_configured
```

That health check precedes the clock-based residency check. Reviewing the saved
data separately also rejects the latter; neither failure was removed to obtain
a pass. A successful PM counter records a completed kernel transition, not
complete device usability.

## USB recovery remains unresolved

The read-only postmortem, more than six minutes after return, reports:

- AXP USB supply `present=1`, `online=1`.
- PHY extcon `USB=1`, `USB-HOST=0`.
- MUSB role `b_peripheral`.
- Configfs gadget still bound to `musb-hdrc.2.auto`.
- UDC `not attached`; `usb0` carrier 0 and operational state down.

These observations separate supply/cable detection from USB data attachment.
They do not identify whether the missing reconnection originates in MUSB, PHY
notification/rearming, or host behavior during the longer unresponsive interval.
The gadget service being active/exited does not prove the link works.

Pinned source inspection gives a concrete next investigation: MUSB system
suspend disables its interrupts/platform path and clears DEVCTL unless the
session-preservation quirk applies; resume restores context and enables the
platform. The peripheral-active branch itself contains an unresolved disconnect
comment. Sunxi's platform enable schedules its work, while disable clears its
enabled flag. These are candidate paths, **not an established root cause**:

- `drivers/usb/musb/musb_core.c:2807–2895`.
- `drivers/usb/musb/sunxi.c:97–144,299–317`.
- `drivers/usb/musb/musb_gadget.c`, pull-up/disconnect/reset handling.

NEO-95 tracks cause isolation, a justified driver correction, source regression
tests and attended recovery qualification. No rebind, service restart, register
write or cable replug was used to hide this failure.

## CPU-idle support and the measurement correction

The recorded syscall interval is:

| Clock | Elapsed seconds |
| --- | --- |
| BOOTTIME | 31.423590335 |
| MONOTONIC | 31.423588251 |
| Difference | 0.000002084 |

That difference is negligible sampling skew, not a measured sleep residency.
There is no `timekeeping_freeze` trace pair. The live snapshot reports
`current_driver=none`, governor `menu`, and no per-CPU idle-state directories.
The running config has `CONFIG_CPU_IDLE=y` but neither `CONFIG_ARM_CPUIDLE` nor
`CONFIG_ARM_PSCI_CPUIDLE`. The prior [awake profile](31-awake-power-profile.md)
already documented the deliberate exclusion of unqualified core-off states.

Pinned Linux 6.18.54 explains why the preparation's strict clock requirement
cannot establish the intended property on this baseline:

1. `kernel/sched/idle.c:193–220` selects ordinary idle when no CPU-idle driver
   is available, before reaching the special s2idle callback path.
2. `drivers/cpuidle/cpuidle.c:144–207` uses `tick_freeze()` for states with a
   suitable `enter_s2idle` callback; this is not implied by `CONFIG_CPU_IDLE=y`.
3. `kernel/time/tick-common.c:517–583` suspends timekeeping only when all online
   CPUs reach that tick-freeze path.
4. `kernel/power/suspend.c:91–158` can still wait in the s2idle loop for a real
   wake event. The complete interval, immediate RTC event and recorded wake IRQ
   establish that functional path here.

This is not evidence of CPU busy-spinning: ordinary ARM idle can execute WFI.
It is also not proof of low current. Report 119's wording that a BOOTTIME minus
MONOTONIC interval is required for any genuine s2idle interval was too broad.
The original acceptance/result remains failed; it is not retroactively relabeled.

NEO-96 will separate functional-wake criteria from CPU-idle/timer-stop and energy
criteria, and investigate a supported implementation. Merely enabling ARM's
generic idle driver is insufficient: `drivers/cpuidle/cpuidle-arm.c:90–116`
rejects absent DT idle states and requires an architecture backend. Do not
invent deeper states or enable unqualified PSCI core-off as a shortcut.

## Preserved state and repeatable collection

Device cleanup restored this run's RTC, PM and trace controls, with no cleanup
errors. It deliberately **retained the owned power-key ignore policy and its
drop-in** after the failed health check. The PEK recorded no input events and
its descriptor closed; this does not authorize blind policy deletion. Normal
sleep targets remain masked. A short power press currently has its ordinary
shutdown action suppressed. Recovery policy and any physical intervention must
be coordinated separately; no further test is running.

The saved collector now supports either route and captures current CPU-idle,
USB, alarm-cleanup and ownership evidence without changing device settings:

```sh
task device:sleep-collect RUN=fe04cfff33b947f7bfa927f707cf144b ROUTE=wifi
# ROUTE=usb remains the default. Collection never retries the PM request.
```

The original result and the live snapshot are separate files. The collector
records whether their boots match, rather than presenting a post-reboot state
as original recovery. A Wi-Fi collection is not a substitute for the required
USB recovery proof. Three new host tests check wrong-route/run rejection,
unchanged failed evidence and collection without submission/upload; all 27
sleep-recorder tests pass. The read-only collector also ran on the board and
retrieved an identical original failure record on the same boot.

Private evidence:

- Original attempt, result recovered via Wi-Fi, cleanup and service journal:
  `.local/diagnostics/20261003T031337.546862Z/`.
- Saved collector result and live postmortem:
  `.local/diagnostics/20261003T032058.099867Z/`.
- Transcripts: `.local/neo94-first-rtc-sleep.log`,
  `.local/neo94-wifi-collection.log`, `.local/neo94-collection-tests.log`.

NEO-94 remains open. USB recovery, CPU-idle qualification, visible-console
confirmation, repeated/long-duration sleep, physical key wake, resume latency
and battery energy remain outstanding. The first attempt has consumed its
seven-cycle admission generation; do not alter counters or automatically reuse
that qualification for another sleep request.
