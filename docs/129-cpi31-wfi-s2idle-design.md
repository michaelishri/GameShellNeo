# CPI v3.1 WFI-only suspend-to-idle design (NEO-96)

3 October 2026, Pacific/Auckland. Research and proposed design only. No kernel
patch, configuration change, image build or hardware operation was performed
for this report. Diagnostic.18 remains the separate USB-resume experiment with
its CPU-idle configuration unchanged.

**Recommend a small, opt-in, board-gated driver with exactly one architectural
WFI state, plus explicit CPU-idle core support for entering state 0 during
s2idle.** Reuse `arm_cpuidle_simple_enter()` for both entry callbacks. Preserve
the core's existing tick-freeze/unfreeze sequence. This is a plausible minimal
implementation to qualify; source review does not establish hardware safety,
reliability or energy savings. There is no sufficient configuration-only fix
in the examined kernel.

The immediate next slice should implement and test that core contract and
driver in isolation, without adding it to the current USB diagnostic image.
Hardware qualification comes after the USB comparison has a reviewed baseline.

## Evidence and source identity

[Report 120](120-first-rtc-sleep-findings.md) records a real RTC-woken s2idle
loop of approximately 29 seconds, with failed USB recovery. Its BOOTTIME and
MONOTONIC syscall intervals both advanced approximately 31 seconds, with no
`timekeeping_freeze` pair. [Report 123](123-sleep-measurement-criteria.md)
separates functional wake, timekeeping, device recovery and energy acceptance.
The observed baseline has CPUs 0–3 online, driver `none`, governor `menu`,
clocksource `arch_sys_counter`, and no CPU-idle state directories. These are
recorded observations, not new measurements.

The source audited here is the fully patched locked Linux **6.18.54** tree at:

```text
.local/build/musb-sleep-tests/kernel-e846a8868bc1eae5/source
```

Line numbers below refer to that tree. Its adjacent `output/.config` has
`CPU_IDLE`, `SUSPEND`, `SMP`, `NO_HZ_IDLE`, `HIGH_RES_TIMERS`,
`GENERIC_CLOCKEVENTS_BROADCAST`, `ARM_ARCH_TIMER`, `GENERIC_SCHED_CLOCK`,
`SUN4I_TIMER` and `SUN5I_HSTIMER` enabled. `ARM_CPUIDLE` and
`ARM_PSCI_CPUIDLE` are disabled. The [project fragment](../kernel/gameshellneo.config)
and [source lock](../build/sources.lock.json) remain unchanged by this research.

Ten relevant local files were compared in memory against the stable
maintainer's public `gregkh/linux` **v6.18.54** sources and were byte-identical:
`drivers/cpuidle/{cpuidle.c,cpuidle-arm.c,cpuidle-psci.c}`,
`kernel/sched/idle.c`, `arch/arm/kernel/cpuidle.c`, `include/linux/cpuidle.h`,
`kernel/time/{tick-common.c,tick-broadcast.c,timekeeping.c}` and
`drivers/clocksource/arm_arch_timer.c`. URLs below name that fixed release,
rather than a moving branch. Board and RTC references explicitly identify
project source where its patches matter.

## Why the existing switches do not solve it

| Candidate | Actual source behavior | Decision |
| --- | --- | --- |
| Current ordinary ARM idle | `kernel/sched/idle.c:195–200` uses `default_idle_call()` before the s2idle callback branch when CPU-idle is unavailable. ARM's default handler can call `cpu_do_idle()`; ARMv7 implements DSB/WFI. | Driver `none` does not imply busy-spinning. The missing feature is the special s2idle integration. |
| `CONFIG_ARM_CPUIDLE=y` alone | `arm_idle_init_cpu()` rejects zero DT idle states and then requires a supported architecture backend. Its WFI initializer supplies `enter`, without `enter_s2idle`. | Insufficient. Do not invent idle-state nodes to pass initialization. |
| `CONFIG_ARM_PSCI_CPUIDLE=y` alone | `psci_idle_init_cpu()` requires CPU `enable-method="psci"`, additional DT idle states and an initialized `psci_ops.cpu_suspend`. Its WFI state has no s2idle callback. | Insufficient and introduces a separate firmware contract. |
| A new one-state driver without core changes | The selector starts at index 1. Both `cpuidle_enter_s2idle()` and its scheduler caller treat only a result greater than 0 as s2idle entry. | State 0's callback remains unreachable. |
| Duplicate WFI at state 1 or fabricated retention state | Could bypass the index restriction while misrepresenting the state table or modifying ordinary governor choices. | Reject; support the real baseline state explicitly. |

Sources: [scheduler idle path][idle], `arch/arm/kernel/process.c:75–81` and
`arch/arm/mm/proc-v7.S:78–82` ([ARM process][process], [ARMv7 instruction][v7]);
`drivers/cpuidle/cpuidle-arm.c:45–124` and `arch/arm/kernel/cpuidle.c:86–145`
([generic ARM][arm-driver], [ARM backend][arm-backend]);
`drivers/cpuidle/cpuidle-psci.c:318–409` ([PSCI driver][psci-driver]);
`drivers/cpuidle/cpuidle.c:84–106,191–205` ([CPU-idle core][core]).

The generic ARM and PSCI registration policies can eventually be reconsidered
upstream. For this qualification, changing their behavior across unrelated
ARM platforms is a broader experiment than an opt-in CPI driver.
The missing-callback observation above concerns their built-in **WFI state 0**:
`dt_idle_states.c:init_state_node()` assigns both callbacks to parsed additional
DT states. It would be incorrect to say these drivers never support s2idle.
[DT state initialization][dt-idle].

## Proposed smallest truthful implementation

### 1. Allow a valid state-0 s2idle callback

Make the return contract explicit: a nonnegative result identifies the state
whose s2idle callback ran; a negative result means no such entry occurred.
Use a negative error such as `-ENODEV` for no suitable callback. The existing
disabled-CPU-idle header stub already returns `-ENODEV`. Keep the scheduler's
reschedule-race `-EBUSY` result negative. [Declarations/stub][header],
`kernel/sched/idle.c:133–139` ([idle wrapper][idle]).

The narrow approach needs changes to `drivers/cpuidle/cpuidle.c` and
`kernel/sched/idle.c`, with updated contract comments:

1. Preserve selection of existing eligible states above index 0.
2. If none is selected, explicitly consider state 0 only when its
   `enter_s2idle` exists and its per-CPU state is enabled. Reject a coupled
   state; respect driver/user disabled or unusable state handling.
3. If no valid state exists, return the negative no-entry result without
   freezing the tick or changing IRQ state.
4. Otherwise run the existing `enter_s2idle_proper()`, then re-enable IRQs and
   return the actual index, including 0.
5. Change the scheduler success check to `entered_state >= 0`, so successful
   state-0 entry does not immediately fall through into a second idle call.

This can leave the shared `find_deepest_state()` and ordinary idle fallback
semantics unchanged. An alternative generalized selector must preserve those
other callers and handle zero-latency states deliberately. Simply changing its
loop start or changing only one `> 0` comparison is incomplete. This is a
design proposal derived from the [core][core] and [scheduler][idle] contracts.

**The return-contract correction is global kernel-core behavior; the driver
opt-in and board match do not scope that correction to CPI.** Keep it as a
separately reviewable core patch. The complete call-site inventory from the
audited tree is:

| Site | Required treatment |
| --- | --- |
| `kernel/sched/idle.c:call_cpuidle_s2idle()` | The only direct caller of `cpuidle_enter_s2idle()`; propagate its index/error, preserving the wrapper's `-EBUSY` race result. |
| `kernel/sched/idle.c:cpuidle_idle_call()` | The only caller of that wrapper; change its success comparison to accept 0. |
| `include/linux/cpuidle.h` | Declaration plus `!CONFIG_CPU_IDLE` stub; the stub's negative return already matches the proposed contract. |
| `find_deepest_state()` in `drivers/cpuidle/cpuidle.c` | Its callers are `cpuidle_find_deepest_state()`, `cpuidle_enter_s2idle()` and timer-broadcast-failure fallback in `cpuidle_enter_state()`. Leave the shared helper unchanged in the narrow design. |
| `cpuidle_find_deepest_state()` | Its scheduler caller at `idle.c:228` still needs a usable ordinary fallback state; do not apply the new no-callback sentinel to this separate API. |

Other drivers with no state-0 callback retain their effective fallback behavior
after the paired core/scheduler update. Any driver already advertising a valid
state-0 callback can newly reach it when no deeper callback qualifies. Review
that generic consequence and test non-CPI fixtures, even with the new board
driver disabled. An option-off build alone does not establish compatibility.

The callback's own integer return is currently ignored inside
`enter_s2idle_proper()`. Preserve balanced unfreeze even after an immediate WFI
return; do not interpret the new success result as proof of physical residency
or use a callback return value as a new suspend-error channel. [Core][core].

### 2. Register one WFI state for the qualified board

Add one built-in driver, its Makefile entry and a default-off Kconfig option,
for example `ARM_CPI_WFI_CPUIDLE`. Constrain it to ARM, `ARCH_SUNXI`, OF,
CPU-idle and suspend support. At initialization require the project's existing
root compatible `clockwork,clockworkpi-cpi3`; do not bind every A33 device.
That compatible does not itself distinguish every board subrevision, so the
qualification scope remains the owner's CPI v3.1.

Proposed descriptor:

| Field | Proposed value/reason |
| --- | --- |
| Driver | A short explicit name such as `cpi_wfi`; no preferred governor override |
| State count / safe index | 1 / 0 |
| State name / description | `WFI` / `ARM WFI` |
| `enter`, `enter_s2idle` | Both `arm_cpuidle_simple_enter` |
| Latency / target residency | Existing ARM WFI convention of 1 µs each; policy metadata, not measured CPI latency |
| Power value | 0, meaning unspecified; no invented board wattage |
| Flags | None: no polling, coupled, timer-stop, TLB-flush or driver-owned RCU handling |
| CPU mask | All possible CPUs, using the registration core's default |

`arm_cpuidle_simple_enter()` calls `cpu_do_idle()` and returns the index; it is
already compiled by `CONFIG_CPU_IDLE` and marked `__cpuidle`. No PSCI call,
CPU-PM notifier, SRAM trampoline, cache shutdown or DRAM operation is needed
for that function. Use `cpuidle_register(drv, NULL)` and propagate errors;
do not report successful registration after partial failure or displace an
existing driver. Registration supplies each CPU device and rolls back on
failure. [ARM helper][arm-backend], [ARM build selection][arm-make],
[driver registration][registration], [device registration][core].

The board compatible is in the patched
`arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts:14`.
The WFI metadata convention is in
`arch/arm/include/asm/cpuidle.h:17–31` ([ARM state definition][arm-header]).
The [CPU-idle documentation][cpuidle-doc] explains the limits of software state
statistics and unspecified power values.

The experimental configuration would enable only this new driver in addition
to the existing prerequisites. Keep generic ARM/PSCI idle disabled; retain the
existing PSCI boot support. No governor, OPP, CPU count, timer DT property,
bootloader or deeper idle-state change belongs in this slice.

## IRQ, timer and all-CPU requirements

The s2idle callback must preserve local IRQ masking for its entire execution
and must not change clock-event devices. It must not call `default_idle_call()`:
that wrapper enables IRQs before returning. A bare reuse of the ARM helper
satisfies the source-level callback constraint, leaving context tracking to
the core. [Callback contract][header], [default wrapper][idle],
[ARM helper][arm-backend].

ARMv7 WFI can finish on a physical interrupt even while the corresponding
CPSR mask is set; waking the core and taking the interrupt exception are
separate steps. It may also complete earlier. Consequently the sequence can
restore timekeeping before enabling IRQ delivery, and WFI must remain part
of the kernel idle loop. This does not bypass interrupt-controller masking:
the RTC/PMIC wake interrupt must still reach the CPU.
[ARM architecture manual, B1.8.14, printed B1-1202][arm-architecture].

The existing sequence to preserve is:

| Phase | Owner and obligation |
| --- | --- |
| Enter system s2idle | `s2idle_enter()` pushes all online CPUs into idle. Unlike platform suspend, this branch does not offline secondary CPUs. |
| Each CPU prepares | IRQs remain disabled. `tick_freeze()` shuts down that CPU's clock-event device. |
| Last online CPU arrives | The freeze-depth check suspends scheduler clock and timekeeping; timekeeping also suspends the broadcast clock-event device. |
| Wait | Each CPU executes WFI, with no driver timer/IRQ manipulation. |
| First CPU returns after all CPUs froze | `tick_unfreeze()` restores timekeeping, broadcast and its local tick under the freeze lock, before normal IRQ handling. An earlier return before all-CPU freeze only resumes that CPU's local tick. |
| Other CPUs return | Each resumes its local tick and balances its freeze entry. The s2idle wake path kicks idle CPUs to restore consistent state. |

Sources: `kernel/power/suspend.c:91–130,441–447` ([system s2idle][suspend]);
`kernel/time/tick-common.c:440–501,518–583` ([tick coordination][tick]);
`kernel/time/timekeeping.c:1938–1995,2003–2065` ([timekeeping][timekeeping]);
`kernel/time/tick-broadcast.c:557–609` ([broadcast][broadcast]). The first CPU
to return need not be the last to enter. A missing driver/device, disabled
s2idle state or repeated early wake on one online CPU can prevent all-CPU
freeze. A full device-suspend test alone cannot prove this path.

Three timer distinctions prevent incorrect fixes:

- **Clock event versus counter.** `arch_sys_timer` is the per-CPU interrupt
  source; `arch_sys_counter` supplies time. `arch_timer_shutdown()` clears
  the event timer's enable bit. It does not disable the shared counter.
- **IRQ suspend versus timer shutdown.** The architecture driver requests
  per-CPU IRQs; `__request_percpu_irq()` adds `IRQF_NO_SUSPEND`. Device IRQ
  suspension therefore is not the mechanism that stops these timer events.
  The clock-event shutdown in tick freeze is essential.
- **Hardware timer-stop flag versus software freeze.** With no `always-on`
  property, the ARM timer advertises `CLOCK_EVT_FEAT_C3STOP`. This is not a
  request to label architectural WFI `CPUIDLE_FLAG_TIMER_STOP`. That state
  flag invokes ordinary-idle broadcast entry; the special s2idle core already
  owns timer suspension. Do not add `always-on` to hide the distinction.

Sources: `drivers/clocksource/arm_arch_timer.c:594–613,674–711,1017–1044,1156–1178`
([architecture timer][timer]); `kernel/irq/manage.c:2476–2502`
([per-CPU IRQ registration][irq-manage]); `kernel/irq/pm.c:65–98`
([IRQ suspend][irq-pm]); `drivers/cpuidle/driver.c:167–176` and
`drivers/cpuidle/cpuidle.c:221–237` ([registration][registration], [core][core]);
[timer DT binding][timer-binding].

The inherited `sun8i-a23-a33.dtsi:78–86` has four timer PPIs, a 24 MHz rate,
and `arm,cpu-registers-not-fw-configured`; it does not supply `always-on` or
`arm,no-tick-in-suspend`. Confirm the **live** tree and selected clock-event
device before a trial, because firmware can amend the handoff. The timer
driver marks the counter suspend-nonstop unless the latter property says
otherwise. This supports an expectation that counter-derived sleep time will
be available for WFI, not proof of the hardware result.
[Inherited timer node][a23-dt], `arch_counter_register():907–943` and
`arch_timer_of_init():1129–1184` ([timer][timer]).

On return, `timekeeping_resume()` can recover elapsed sleep from a nonstop
clocksource, then a persistent clock; RTC compensation is a separate fallback.
Preserve this path and test its result rather than injecting artificial clock
offsets. [Timekeeping][timekeeping], [suspend-clocksource selection][clocksource].

## Firmware and physical-state limits

The locked boot artifact is **ClockworkPi U-Boot
2018.01-rc1-00118-gd19ddc958a**, SHA-256
`d7154f264edfed57fe00e2dcbfe30c0c876b3e6a8a6e2ae5bcf7b84d470a208c`;
it is not the upstream U-Boot v2026.07 implementation examined in older
research. The [lock][lock] identifies the [vendor binary source][vendor-boot].
Do not infer this binary's complete suspend ABI from its version string,
multicore boot, or the kernel's compiled PSCI support.

As a separate reference, upstream U-Boot v2026.07's sunxi ARMv7 implementation
does not replace the generic unsupported CPU-suspend/system-suspend stubs.
That explains why choosing a newer upstream bootloader is not an established
shortcut. Linux's PSCI system-suspend support also requires firmware feature
advertisement. The WFI-only proposal needs neither a new monitor ABI nor a
claim that the existing binary provides CPU_SUSPEND.
[Sunxi monitor][uboot-sunxi], [generic monitor stubs][uboot-psci],
[Linux PSCI implementation][psci-fw].

The Cortex-A7 manual describes WFI as processor standby with the processor
still powered. It describes L2 WFI and power removal using additional
integration sequences. Executing WFI on four CPUs does not establish that
those additional sequences happened.
[Cortex-A7 TRM DDI 0464F, §2.4.2, printed pp. 2-14–2-17][a7-manual].
The local Allwinner R16 manual separately exposes `STANDBYWFI` in CPU status
registers, but those are status bits, not a complete retention implementation
([R16 v1.0, PDF pp. 91–95][r16-manual]). Polling them from an active Linux CPU
would perturb an all-CPU-idle experiment. Neither that polling nor direct
register writes are part of the recommended first slice.

## Concrete qualification sequence

### Source tests before an experimental image

Exercise the real modified selection/entry code with mocked callbacks and
tick/IRQ hooks, using the repository's established compiled-source-test style
or an appropriately scoped KUnit fixture. A duplicate Python selector is not
sufficient. Required cases are:

| Case | Required result |
| --- | --- |
| One enabled state 0 with s2idle callback | Callback runs once with index 0; tick freeze/unfreeze balance; scheduler accepts 0 and does not perform a second entry. |
| State 0 missing callback or disabled by user/driver | Negative no-entry result; no callback or freeze; ordinary fallback remains usable. |
| Eligible deeper state plus state 0 | Existing deeper-state selection and positive index remain; state 0 is not called. |
| Deeper states missing callbacks or disabled | Skip them and select enabled callback-bearing state 0; if state 0 also lacks a callback or is disabled, return the negative no-entry result. |
| Pending reschedule race | `-EBUSY` from the wrapper does not become success; no lost reschedule or unbalanced IRQ state. |
| Immediate/spurious WFI return | Exactly one balanced core entry/exit; no hardware-duration claim from callback success. |
| Coupled/unsupported state 0 | Cannot enter the new baseline callback path. |
| Registration failure or wrong board | No partial usable driver, no takeover; ordinary ARM idle remains available. |
| Driver option off / existing other drivers | Existing behavior preserved; build the touched core under relevant suspend/CPU-idle configurations. |

Cross-build the actual locked ARM configuration with the proposed option;
inspect the callback call chain and generated entry code for DSB/WFI and the
absence of firmware or IRQ-enable operations. Run the repository checks
appropriate to the patch and updated collector fixtures. These are future
tests, not results from this report.

### Awake admission, then one attended RTC trial

After the independent USB result is reviewed, prepare a separately identified
image and repeat current-boot qualification and awake rehearsal. Before sleep,
require all four online CPUs to expose the same single `state0`, including
`state0/s2idle/usage` and `state0/s2idle/time`. Check registration logs, state
disable bits, idle/timer health, wake routing and the current image identity.
The s2idle sysfs subdirectory is created only for a callback-bearing state:
`drivers/cpuidle/sysfs.c:355–400` ([sysfs implementation][sysfs]).
Its availability requires `CONFIG_SUSPEND`, registration and the callback;
it does **not** require a change to `CONFIG_CPU_IDLE_GOV_MENU`. The current
menu governor can remain selected, since s2idle bypasses governor selection.
[Sysfs][sysfs], [scheduler selection][idle].

Capture the live timer node, selected clocksource, each CPU's clock-event
device, broadcast device, IRQ identities/affinities and baseline counts.
`arch_sys_counter` alone does not identify the active event device or PPI.
Use `/proc/timer_list` and clock-event sysfs where available; retain the
existing RTC alarm-delivery/restoration prerequisite and independent recovery
routes. Do not offline CPUs or change the timer source to make the first
result pass.

Then use the existing single-submission, attended 30-second RTC procedure with
fresh admission records. Its acceptance must retain every functional wake and
device-recovery check in [report 123](123-sleep-measurement-criteria.md), and add:

- A positive `state0/s2idle/usage` delta on **each** online CPU.
- Complete, ordered `timekeeping_freeze` begin/end events inside the actual
  `machine_suspend[1]` interval, with no trace loss. Multiple short freeze
  episodes may be legitimate; assess their extent rather than demanding
  identical entry/exit CPU numbers.
- Bracketed BOOTTIME-minus-MONOTONIC evidence exceeding sampling uncertainty
  and consistent with the RTC deadline. A tiny total frozen interval is an
  implementation failure for this experiment even if functional RTC wake passes.
- Per-CPU timer and scheduler operation restored after return: exercise
  bounded CPU-affined timer waits/work on CPUs 0–3, check interrupt progress
  while awake, and reject stalls, clock jumps, IRQ-state warnings, RCU stalls
  or new kernel errors. Restore ordinary operation and recheck both networks,
  input, display, audio, memory and PM/reference accounting.

Architectural timer IRQ counts can include entry/resume work and cannot alone
measure the frozen interval. Trace any unexpected repeated wake activity in a
later bounded diagnostic if needed; do not introduce per-CPU polling during
sleep. Keep wake attribution tied to the admitted RTC IRQ, not to whichever
CPU first returns from WFI.

Two measurement traps need explicit collector coverage. The s2idle core does
not emit the ordinary `power:cpu_idle` events around its callback, so their
absence is not an entry failure. Its `s2idle_time` is measured using
`local_clock_noinstr()`. On this ARM configuration that derives from generic
`sched_clock`, whose suspend/resume path freezes the reading and rebases the
counter. Consequently **do not require `state0/s2idle/time` to equal wall-clock
sleep duration**. Use usage counters as callback evidence and the independent
clock/trace assessment for suspended timekeeping.
[CPU-idle accounting][core], [local clock mapping][sched-header],
`kernel/time/sched_clock.c:271–310` ([scheduler-clock suspension][sched-clock]).

The battery collector also needs an explicit clock audit before enabling this
path. [The current battery guard](../runtime/usr/local/lib/gameshellneo/battery_guard.py)
timestamps samples and consecutive-observation gaps with `time.monotonic()`;
[PM admission](../tools/test-pm-stages.py) checks age using that same clock.
Once MONOTONIC stops during sleep, a pre-sleep sample can appear young after
wake, and a long sleep gap need not reset the observation sequence. Add a
sleep-inclusive BOOTTIME timestamp or require a newly observed sample after
resume, with fixtures for the stopped-clock interval. Preserve older image
evidence and evaluate shutdown-debounce semantics separately. This is a source
inference for the proposed clock behavior, not a newly observed battery fault.

Repeat reliability, physical power-key wake, longer intervals, different
external-power conditions and controlled battery measurements are subsequent
qualification stages. Their results must remain separate from the first
driver/timer acceptance. NEO-96 remains in progress; this report establishes
an implementation candidate and its tests, not qualified sleep efficiency.

[core]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/cpuidle/cpuidle.c
[idle]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/sched/idle.c
[process]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/kernel/process.c
[v7]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/mm/proc-v7.S
[arm-driver]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/cpuidle/cpuidle-arm.c
[dt-idle]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/cpuidle/dt_idle_states.c
[arm-backend]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/kernel/cpuidle.c
[arm-make]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/kernel/Makefile
[arm-header]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/include/asm/cpuidle.h
[psci-driver]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/cpuidle/cpuidle-psci.c
[registration]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/cpuidle/driver.c
[header]: https://github.com/gregkh/linux/blob/v6.18.54/include/linux/cpuidle.h
[suspend]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/power/suspend.c
[tick]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/time/tick-common.c
[timekeeping]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/time/timekeeping.c
[broadcast]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/time/tick-broadcast.c
[timer]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/clocksource/arm_arch_timer.c
[timer-binding]: https://github.com/gregkh/linux/blob/v6.18.54/Documentation/devicetree/bindings/timer/arm%2Carch_timer.yaml
[irq-manage]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/irq/manage.c
[irq-pm]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/irq/pm.c
[a23-dt]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi
[clocksource]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/time/clocksource.c
[cpuidle-doc]: https://docs.kernel.org/admin-guide/pm/cpuidle.html
[lock]: ../build/sources.lock.json
[vendor-boot]: https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin
[uboot-sunxi]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/cpu/armv7/sunxi/psci.c
[uboot-psci]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/cpu/armv7/psci.S
[psci-fw]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/firmware/psci/psci.c
[arm-architecture]: https://documentation-service.arm.com/static/5f8daeb7f86e16515cdb8c4e
[a7-manual]: https://documentation-service.arm.com/static/602cf701083323480d479d18
[r16-manual]: ../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf
[sysfs]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/cpuidle/sysfs.c
[sched-header]: https://github.com/gregkh/linux/blob/v6.18.54/include/linux/sched/clock.h
[sched-clock]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/time/sched_clock.c
