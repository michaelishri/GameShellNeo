# CPI WFI suspend-to-idle source candidate (NEO-96)

4 October 2026, Pacific/Auckland. Implementation and isolated source validation;
no image assembly, installation, live configuration change or hardware sleep.

The [candidate branch](https://github.com/michaelishri/GameShellNeo/tree/work/cpi-wfi-s2idle)
implements [report 129's design](129-cpi31-wfi-s2idle-design.md): one board-gated
architectural WFI state and a separately reviewable CPU-idle core correction.
The driver remains disabled by default. Diagnostic.18, already verified and
staged on the Mac, remains the independent USB-recovery experiment.

## Changes and scope

Patch **0027-cpuidle-state-zero-s2idle.patch** changes two coordinated sites:

- `cpuidle_enter_s2idle()` still prefers the existing eligible deeper state.
  When the shared selector returns its ordinary fallback index 0, the function
  requires an enabled, non-coupled state with an `enter_s2idle` callback.
  Otherwise it returns `-ENODEV`, leaving local interrupt state unchanged.
- The scheduler now accepts any nonnegative entered-state index. A successful
  state-0 callback therefore exits the idle call without falling through to a
  second ordinary entry. The existing reschedule-race `-EBUSY` path remains.

The shared selector, ordinary-idle fallback, `enter_s2idle_proper()` and
`tick_freeze()`/`tick_unfreeze()` are unchanged. Per-CPU disable bits retain the
driver/user policy: an unusable state has driver-disable set; a state marked
initially off may still be explicitly enabled by the user. No new callback
return/error interpretation or claim of physical residency is introduced.

**This core correction is global even when the board driver is disabled.**
Other drivers without an eligible state-0 callback keep the ordinary fallback;
drivers advertising one can now enter it. The tests exercise non-CPI state
tables, disabled states and deeper-state selection. They do not qualify every
CPU-idle driver or architecture. Existing deeper-state callback/coupling rules
remain unchanged by this narrow correction.

Patch **0028-cpuidle-cpi-wfi-integration.patch** adds the default-off
`ARM_CPI_WFI_CPUIDLE` Kconfig/Makefile hooks. The new overlay source becomes part
of generated patch 0003. Patch number 0026 is reserved for the independent
[MUSB IRQ-wake candidate](131-musb-wake-irq-ownership.md).

The new `cpuidle-cpi-wfi.c` driver:

- Requires ARM, Sunxi, OF, CPU-idle and suspend support, then matches root
  compatible `clockwork,clockworkpi-cpi3` at initialization. This compatible
  does not distinguish every board subrevision; hardware scope remains CPI v3.1.
- Registers driver `cpi_wfi`, one `WFI` state, safe index 0, and the existing
  `arm_cpuidle_simple_enter()` for both ordinary and s2idle entry.
- Uses the ARM convention of 1 microsecond latency/residency metadata, with
  power unspecified and no special flags. These are not measured board values.
- Uses the standard registration API and its all-possible-CPU default mask;
  propagates failures without replacing an existing driver. The standard
  registration loop unwinds previously registered CPU devices on failure.

There is no new governor, PSCI idle backend, fabricated DT state, timer-stop
flag, CPU offlining, firmware, DRAM operation or retention implementation.
Ordinary awake idle can acquire additional framework overhead compared with
the current no-driver path; its effect needs measurement alongside sleep.

## Reproducible validation

From the candidate checkout, with the pinned build environment available:

```sh
task test:cpuidle-s2idle
task check:cpuidle-kernel
task check
```

The first task reads the SHA-256-verified Linux **6.18.54** archive, applies the
two patches to private input copies, and extracts the actual entry, scheduler,
registration-loop, ARM callback and tick-freeze functions. The state/usage
structures and flag constants also come from the locked header. It checks
that ordinary selection, the core entry body, tick coordination and ARM WFI
wrapper remain byte-identical to the original source.

**618 scenarios pass natively and on ARM32 under QEMU:**

| Coverage | Cases | What is exercised |
| --- | ---: | --- |
| Selection/entry | 15 | State 0, missing callbacks, user/driver-disabled and coupled states, initially-off but re-enabled state, deeper choices, latency fallback, immediate/error callback return, IRQ-leak warning recovery and RCU-owned entry |
| Actual scheduler caller | 13 | No double entry, negative fallback, early/racing reschedule, unavailable driver/device, ordinary one-state/governor paths, forced latency and existing stopped tick |
| Board/registration | 11 | Descriptor and callback, wrong board, propagated registration errors, failure on each of four CPUs, complete registration and unregistration |
| Actual tick coordination | 579 | All 24 entry orders × 24 return orders across four CPUs, plus return before all CPUs freeze at depths 1–3 |

**Eleven native negative controls fail by assertion.** They deliberately break
zero-success handling, negative no-entry handling, disable/coupled gating,
IRQ-before-unfreeze ordering, unfreeze balancing, all-CPU/early timekeeping
freeze, board matching, registration error propagation or partial rollback.

The harness models CPU identity, interrupts, locks, clock-event/timekeeping
boundaries, context tracking and lower registration APIs. The real registration
loop/unregister loop are executed; lower allocation/sysfs/driver ownership
operations are fault-injected shims. Likewise the actual tick-depth algorithm
runs, but not actual concurrent CPUs or a physical timer. These are executable
source regressions, not kernel lockdep, PREEMPT_RT or hardware evidence.

The ARM compile task uses the complete patched source tree and actual Kbuild
units in four configurations:

| Configuration | Complete objects checked |
| --- | --- |
| Project + CPI driver enabled | CPU-idle core, CPI driver, scheduler policy unit, tick-common, ARM CPU-idle and ARMv7 processor assembly |
| Project + CPI driver disabled | The same existing units without the new driver |
| Suspend disabled | Existing core/scheduler/timer/ARM units with the new option disabled |
| CPU-idle disabled | Scheduler policy unit, exercising the disabled CPU-idle header path |

`kernel/sched/idle.c` is included by `build_policy.c`; it must be compiled using
`kernel/sched/build_policy.o`, not as a standalone object. All four configurations
pass. Both project configurations also pass the existing 164 configuration
assertions. Explicit compile-only configurations have distinct scratch identities
and verify their resolved overrides; they do not pretend to satisfy image policy.

The saved disassembly shows `arm_cpuidle_simple_enter()` calling the architecture
processor table's idle slot. The ARMv7 idle implementation contains exactly
`dsb`, `wfi`, `bx lr`, with no interrupt-enable or firmware instruction in that
body. Multiple processor-family names alias that function, so the check resolves
`cpu_v7_do_idle` through the symbol table rather than relying on objdump's chosen
display label. This does not identify the live processor table or measure WFI.

Repository checks pass **13 runtime and 464 tooling tests**, with two skips:
the optional user-systemd recovery test and the test requiring a prepared locked
Armbian source checkout. Bash/ShellCheck and existing native helper tests pass.
Kernel checkpatch reports zero errors/warnings for both patches and the driver
with DCO checking disabled; no human sign-off is asserted.

Evidence lives under `.local/build/cpuidle-s2idle-tests/`: JSON manifests contain
source hashes, native outcomes, ARM32 output, configuration and object hashes;
the WFI disassembly is saved alongside them. Build logs use
`.local/build/cpuidle-s2idle.log` or `cpuidle-kernel.log`.

Recorded compile-evidence SHA-256:
`ccdece6358ee96b38ead906a56042998713f7afc8be4a89d4b02d30dc17dd3ad`.
Its recorded source hashes were checked against the completed candidate files.

## Remaining gates

1. Qualify diagnostic.18's USB recovery first, preserving its separate baseline.
2. Integrate the [NEO-100 battery clock candidate](133-battery-boottime.md) before
   enabling timer/timekeeping freeze. BOOTTIME freshness must work through real
   sleep; awake-only profilers must reject intervening sleep. Sleeping-battery
   protection and final decision/sleep serialization remain separate work.
3. Assign a new image/kernel identity, enable only this experimental driver,
   perform a full kernel/link/image/DT build and offline checks, and inspect the
   installed driver, four CPU state tables, timer selection and live DT.
4. Repeat the installed image's fresh awake RTC and PM prerequisite sequence,
   then perform an explicitly attended bounded RTC sleep. Require correct
   all-CPU freeze/resume traces, clock accounting, restored timer activity and
   device recovery. Short-circuit callback return is not proof of sleep time.
5. Compare awake overhead and asleep energy using software telemetry and timed
   battery runs. CPU-idle usage counters and successful compilation cannot
   establish battery-life improvement or the week-long standby goal.

The source lock/configuration fragment is deliberately unchanged on this branch;
the enabled setting is an isolated compile override only. Do not assemble or
stage this branch under diagnostic.18's identity. NEO-96 remains in progress.
