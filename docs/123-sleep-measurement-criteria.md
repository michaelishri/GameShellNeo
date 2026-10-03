# Functional sleep, timekeeping and CPU-idle criteria (NEO-96)

3 October 2026, Pacific/Auckland. The RTC sleep recorder now distinguishes a
functional wake from evidence of suspended timekeeping, CPU retention and energy
savings. This corrects the assumption identified in [report 120](120-first-rtc-sleep-findings.md).
The original failed USB result remains failed and unchanged. No kernel, idle
driver, bootloader or device-tree state was changed in this slice.

## Why the previous clock criterion was wrong

The pinned Linux 6.18.54 path permits the following sequence:

1. `kernel/power/suspend.c:s2idle_enter()` records `machine_suspend[1]`, pushes
   CPUs into their idle loops and waits for a wake event.
2. `kernel/sched/idle.c:cpuidle_idle_call()` takes `default_idle_call()` when
   no usable CPU-idle driver is available. This branch precedes the special
   s2idle CPU-idle callback path.
3. ARM's ordinary handler in `arch/arm/kernel/process.c` can reach
   `cpu_do_idle()`; `arch/arm/mm/proc-v7.S:cpu_v7_do_idle()` executes DSB/WFI.
   Absence of a registered CPU-idle driver does not mean busy-spinning.
4. The separate `drivers/cpuidle/cpuidle.c:enter_s2idle_proper()` path calls
   `tick_freeze()`, then the state's `enter_s2idle` callback, then `tick_unfreeze()`.
5. `kernel/time/tick-common.c` suspends timekeeping when the last online CPU
   enters that freeze path. The first CPU to leave resumes it. Those two CPUs
   need not be the same.

Consequently, a near-zero BOOTTIME-minus-MONOTONIC interval can accompany a real
RTC-woken s2idle loop on the present image. It does not establish low current,
nor disprove the functional transition. Conversely, a clock difference alone
does not identify a hardware CPU power state.

## Revised acceptance

| Layer | Required evidence | Limit |
| --- | --- | --- |
| RTC wake | Explicit `freeze` intent with `pm_test=none`; one correct RTC IRQ increment, immediate alarm event, matching wake IRQ, bounded deadline and restored alarm | Does not prove the devices recovered |
| Actual s2idle path | One complete, timestamped `machine_suspend[1]` pair inside complete late/noirq callbacks; no trace loss or callback error; sufficient wait inside the loop | Loop time is not hardware CPU residency |
| Timekeeping | Ordered `timekeeping_freeze` pairs inside that loop plus a positive clock difference exceeding measured sampling uncertainty | Software timer behavior, not CPU/DRAM retention or battery savings |
| Device recovery | Existing USB/Wi-Fi, input, memory, display settings, audio, PM counters, reference counts, journal and owned-policy checks | Human screen observation and wider reliability still need their own evidence |
| Power efficiency | Separately qualified CPU-idle behavior and controlled battery measurements | Always unqualified by this recorder alone |

The recorder retains the 30-second alarm, 15-second minimum entry margin,
single wakeup-count handshake and single sleep submission. It still rejects an
early/unrelated wake, wrong IRQ, missing alarm, failed restoration, debug return,
missing/repeated boundaries and out-of-order callbacks. Normal sleep stays
masked; observer readiness, current-boot prerequisites and a same-source awake
rehearsal remain required.

The final entry margin is now recorded after the durable-intent/guard overhead.
The syscall's BOOTTIME duration must fit that admitted deadline. Additionally,
the trace must support at least five seconds in the s2idle loop and the expected
remaining alarm interval, allowing two seconds for RTC integer-second sampling
and scheduling. Entry overhead is removed from that expected interval. A long
resume delay followed by an alarm delivered while awake cannot supply missing
in-loop time.

MONOTONIC trace time excludes suspended timekeeping. To assess in-loop duration,
the validator adds a clock difference only when paired in-loop freeze events
and bounded clock sampling support it, subtracting sampling uncertainty. It
does not impose a minimum MONOTONIC duration on a timer-frozen interval.

## Measurement implementation

[`sleep_rtc.py`](../tools/sleep_rtc.py) brackets each BOOTTIME read with two
MONOTONIC reads. It records both endpoints, their midpoint and the derived
interval uncertainty. Non-finite/backwards readings, incomplete brackets and
samples spanning more than 50 ms fail validation. A negative clock difference
beyond uncertainty, or a positive difference without a matching freeze trace,
is rejected for new bracketed samples (with 1 microsecond arithmetic tolerance).

Historical two-read samples remain readable, with unknown uncertainty recorded
as `null`. Their raw clock difference is reported but contributes no extra
duration and cannot qualify suspended timekeeping. The old misleading
`suspended_seconds` field is replaced with separate elapsed-clock, trace and
timekeeping evidence.

The functional-wake assessment is saved before general device-recovery
validation. A future USB failure can therefore coexist with a recorded RTC wake
sub-result, while the overall run still fails. Result scope and command output
explicitly distinguish functional/recovery checks from power qualification.
Before/after CPU-idle snapshots preserve the driver, governor, online CPUs,
clocksource and any available state definitions/counters; these are observations,
not automatic power qualifications.

Two saved commands make the work repeatable:

```sh
# No remote access or changes to the original file; writes a separate assessment.
task report:sleep-evidence RESULT=.local/diagnostics/20261003T031337.546862Z/result-via-wifi.json
# Uses .env; samples clocks and reads idle/timer/PM state without programming an alarm.
task device:sleep-clock-inspect
```

The offline report keeps the original result's pass flag, error and SHA-256,
checks that its bytes remain unchanged, records the assessment sources and
always sets `overall_requalified=false`. Its command status describes the
measurement checks only. It rejects in-progress results.

## Validation and observed state

The original final result was assessed offline at
`.local/diagnostics/20261003T091123.719924Z/sleep-evidence.json`:

- RTC/trace/deadline checks pass under the corrected criteria.
- The trace supports 28.948584 seconds in the s2idle loop.
- BOOTTIME/MONOTONIC advance 31.423590335/31.423588251 seconds; their difference
  is about 2.084 microseconds, with no recorded sampling bound.
- There are zero timekeeping-freeze pairs; timekeeping suspension is not observed.
- CPU retention and energy remain unqualified.
- Original `passed=false` and the USB configuration failure remain unchanged.
  Input SHA-256 is `2214f1658a89438355d90bd5e5ce929dba169a5de576e9570dbe1de341ab304a`.

Awake inspection at `20261003T090952.442121Z/clock-inspection.json` confirmed
boot `4ffd75dc-2dae-4164-8bd2-90ad08ed1885`, CPUs 0–3 online, CPU-idle driver
`none`, governor `menu`, clocksource `arch_sys_counter` and no state directories.
All eight bracketed samples validated; the widest bracket was about 110.584
microseconds. PM counts stayed 0/0 and settings stayed `pm_test=none`, `pm_async=1`.
This is sampler qualification while awake, not a new sleep experiment.

The current-boot startup check at `20261003T091238.612742Z` also passed, including
both independent SSH routes. It requested zero power cycles.
The ten-second awake RTC alarm test at `20261003T091424.426563Z` then passed
delivery and restoration, preparing this boot's RTC prerequisite without
entering sleep or changing the display.

`task check` passes: 13 runtime tests, 452 tooling tests (one intentionally
skipped), compiled current-selector and Mac mount-guard regressions, Bash syntax
and ShellCheck. The sleep suite now has 38 tests, including running timekeeping,
timer freeze on different CPUs, clock uncertainty, malformed/lost traces,
late-awake-alarm false positives, preserved USB failures and read-only commands.

## CPU-idle implementation still to do

The running configuration already enables CPU_IDLE, NO_HZ_IDLE and high-resolution
timers. Those switches alone do not provide the missing `enter_s2idle` callback.
The generic ARM driver also rejects a WFI-only configuration without additional
DT idle states/backend operations, and its state initializer supplies `enter`,
not `enter_s2idle`.

There is a second integration detail to solve: the pinned CPU-idle selection
code searches from state index 1 and invokes the timer-freeze path only for an
index greater than 0. Simply registering WFI as state 0, even with a callback,
would not reach that path. Inventing a deeper DT state to satisfy selection
would misdescribe the hardware.

The next implementation audit should evaluate a real WFI-only s2idle callback
with explicit framework support for the baseline state. It must preserve IRQ
masking, all-CPU tick-freeze balance and RTC/key wake routing, avoid firmware
core-off and DRAM changes, and include source-level selection/error tests before
an instrumented image is built. Whether this is the best maintained kernel
integration remains open; no candidate is installed or claimed safe yet.

NEO-96 remains in progress for that driver/timer work. NEO-95's traced USB
reproduction can now use correct functional criteria on the current image,
after rebuilding its current-boot debug prerequisites and rehearsing with the
new sources. Changing CPU idle at the same time would add another variable to
the unresolved USB comparison.
