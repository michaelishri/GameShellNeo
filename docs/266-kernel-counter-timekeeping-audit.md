# Kernel counter and timekeeping audit

10 October 2026. NEO-192, following
[reports 261](261-arm-clock-path-source-analysis.md)–[265](265-native-clock-cpu-coverage.md).

**The source audit identifies a missing measurement boundary, not a fix:**
the counter value actually consumed by a clock syscall and its coherent
timekeeper state. Normal sequence-count protection prevents accepting mixed
updates, but neither it nor counter-underflow detection compares against the
previous timestamp returned to the caller. A counter fault can therefore
produce a decreasing result without a sequence-count failure. There is no
event-time counter or timekeeper record establishing that this happened here.

This work inspects local sources and saved evidence only. It does not access
the GameShell, change its image, install instrumentation, or run a new
hardware experiment. NEO-192 remains unresolved; NEO-191/NEO-182 PM work stays
blocked. Retain the original boot, PM53/0 and battery-service NRestarts=1.

## Evidence boundary

The original guard failure is a Python MONOTONIC → BOOTTIME → MONOTONIC
bracket whose second MONOTONIC value was smaller. The old guard did not save
those integers; the service exited and restarted ten seconds later. Its
magnitude and per-read CPU context cannot be recovered from the traceback.
The distinct [report 260](260-clock-comparison-provenance.md) RAW event retained
`62049008553837` ns from syscall403 followed by `62049008553087` ns from Python:
−750 ns, while each route's own readings increased. Neither establishes that
the second read was too low rather than the first too high, or that the two
faults have a common cause. [Original boundary](257-awake-clock-regression-investigation.md).

The same-boot export inventory found all vDSO clock names absent, matching the
ARM boot-time gate for `arm,cpu-registers-not-fw-configured`. Together with the
installed Python/libc imports and disassembly, this supports syscall fallback
for the ordinary API. It does not retrospectively trace the failing calls.
A vDSO mapping alone does not support the earlier physical-versus-virtual
path explanation. The unpinned and four-core pinned native captures
each retained 270,000 readings without a discrepancy; their spacing and
coverage limits remain, and they do not clear either fault.
[Runtime inventory](262-clock-runtime-inventory.md),
[export correction](263-native-clock-vdso-availability.md),
[native results](264-native-libc-syscall-comparison.md),
[CPU coverage](265-native-clock-cpu-coverage.md).

The baseline is the Linux 6.18.54 source selected by
[sources.lock.json](../build/sources.lock.json), commit
`1b357ecb321392158d507b04672ffee57bfa071d`. Line references below refer to that
fixed tree inspected under `.local/sources/linux-6.18.54/`, rather than a moving
upstream branch. The web reader could not retrieve the fixed kernel.org source
page; local source supplies the implementation evidence. Current upstream
[ktime documentation](https://docs.kernel.org/core-api/timekeeping.html)
independently confirms the MONOTONIC, BOOTTIME and RAW API distinctions.
The archive SHA-256 matches the lock, and 27 inspected upstream files match
their archive entries byte for byte. The hash receipt is retained privately at
`.local/diagnostics/20261010T004240.019924Z/source-audit.json`.

The captured configuration from report 265 has SHA-256
`8940a14f8c8a91caa6daabe096519bf1be091ace529bd71a94a3cbac8ac1a5e9`.
The audit also verifies the captured hashes of the CPI WFI overlay and patches
0027/0028 against their current source files. This establishes the inspected
configuration and board-source inputs; it does not claim a newly built binary
is the running kernel.

## The actual syscall readers

ARM syscall403 dispatches to `sys_clock_gettime`; legacy syscall263 dispatches
to `sys_clock_gettime32`. Both wrappers call the selected clock's
`clock_get_timespec` operation before serializing the result. Time32 versus
time64 therefore does not select a separate timekeeping algorithm. The
time64 wrapper uses a kernel-local `timespec64` and copies its completed
seconds/nanoseconds into `__kernel_timespec`. A copy failure becomes EFAULT;
it does not select another sample.
[ARM table](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/tools/syscall.tbl?id=1b357ecb321392158d507b04672ffee57bfa071d#n421),
[time64 wrapper](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1136),
[time32 wrapper](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1291),
[result copy](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/time.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n903).

| Clock | Kernel read and coherent state | Additional syscall offset |
| --- | --- | --- |
| MONOTONIC | `ktime_get_ts64()`: `xtime_sec`, `tkr_mono` conversion, `wall_to_monotonic` under `tk_core.seq` | Time namespace monotonic offset |
| MONOTONIC_RAW | `ktime_get_raw_ts64()`: `raw_sec` and `tkr_raw` conversion under the same sequence counter | The same namespace monotonic offset |
| BOOTTIME | `ktime_get_boottime_ts64()` → `ktime_get_boottime()` → `ktime_get_with_offset(TK_OFFS_BOOT)`: `tkr_mono.base`, `offs_boot` and `tkr_mono` conversion under the same sequence counter | Time namespace boottime offset |

[POSIX handlers](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n217),
[MONOTONIC reader](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n955),
[RAW reader](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1645),
[BOOTTIME wrappers](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/timekeeping.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n97),
[offset reader](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n851).

`getboottime64()` is a different API: it returns the wall-clock time of boot,
`offs_real - offs_boot`, and can change with wall-time corrections. Its direct
field reads are not the implementation of `clock_gettime(CLOCK_BOOTTIME)`.
Likewise, the documented update-ordering caveat for `ktime_get_mono_fast_ns()`
concerns the separate NMI-safe latch accessor. These syscall handlers use
neither it nor the coarse getters. Finding an unsynchronized or intentionally
weaker accessor elsewhere in the file is not evidence against these calls.
[Wall-time-of-boot API](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2408),
[fast accessor caveat](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n459).

Within one unchanged task namespace, libc and explicit syscalls receive the
same namespace offset. Namespace offsets are frozen when initialized for
tasks and further writes are rejected. Namespace identity remains useful
capture metadata; a fixed namespace offset is not a route-specific −750 ns
explanation. This is a source inference, not an event-time namespace trace.
[Offset addition](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/time_namespace.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n73),
[freeze](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/namespace_vdso.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n89),
[write rejection](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/namespace.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n313).

## What the sequence counter protects

The published and shadow timekeepers share an associated raw spinlock and
sequence counter. Writers modify shadow state while holding the IRQ-saving
raw lock; publication makes the sequence odd, updates derived data, copies
shadow into published state, then makes the sequence even. The writer's
sequence transitions have write barriers. Readers begin with an acquire load
of an even sequence, read all needed fields and the clock, then use a read
barrier before checking the sequence again. They repeat if it changed. The
specific header here uses `smp_load_acquire()` at reader entry; assuming an
older header's exact barrier spelling would be inaccurate.
[Core structures](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n52),
[lock initialization](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1772),
[publication](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n708),
[acquire load](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/seqlock.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n157),
[reader loop](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/seqlock.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n266),
[retry and writer barriers](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/seqlock.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n388).

On ARM SMP, the generic acquire implementation uses a single-copy sequence
load followed by the architecture memory barrier; ARM defines the relevant
SMP barriers with DMB instructions and compiler memory clobbers. Although a
64-bit memory field can require multiple ARM32 loads, a concurrent normal
writer invalidates that attempt. Simple torn seconds, anchor or multiplier
reads are therefore not an identified hole in this protocol. This depends
on correct compiled code, hardware ordering and every relevant writer
obeying the protocol; source inspection does not prove those at the event.
The caller's completed stack result and successful syscall copy also should
not be confused with asynchronously reading a shared 64-bit counter.
[Generic acquire](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/asm-generic/barrier.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n147),
[ARM barriers](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/barrier.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n77).

Successful sequence validation proves consistency relative to participating
writers, not a good counter value, absence of migration, or order against an
earlier successful read. It is also an internal concurrency retry, distinct
from adding a userspace retry that discards an observed clock fault.

## Delta protection is not a previous-result floor

For an ordinary read, the relevant calculation is:

```text
delta = (counter - cycle_last) & mask
subsecond_ns = (delta * mult + xtime_nsec) >> shift
```

The read helper checks `delta > max_cycles`. If that is true and the high bit
of the masked delta is set, it returns the base subsecond value instead of
the apparent negative interval. Otherwise an excessive multiplication uses
the overflow-safe helper. A normal small positive delta takes the ordinary
fixed-point path. `max_cycles` is a multiplication bound, not an acceptable
inter-read drift tolerance.
[Read conversion](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n372),
[bound calculation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/clocksource.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n951).

Consequences derived from that implementation:

- Two successive counter values can both exceed `cycle_last`, yet the second
  can be smaller than the first. Both pass the ordinary path; sequence-count
  validation cannot detect that because no writer need have run.
- A first read too far ahead can cause the same observed ordering failure as
  a second read too far behind. The saved timestamps cannot choose between
  these cases.
- Even taking the negative-delta branch only returns the update anchor's
  time. It does not retain or reproduce a later value already returned to a
  caller. Detector presence is not proof that the syscall cannot regress.
- With a coherent unchanged RAW tuple, positive `mult`, and ordinary bounded
  arithmetic, increasing accepted counter values cannot produce a decreasing
  result through truncation alone. The next measurement must record the tuple
  to determine whether those premises held.

The writer uses a different check: `clocksource_delta()` returns zero if the
masked difference exceeds `max_raw_delta`, computed as approximately seven
eighths of the counter mask. That threshold permits long idle accumulation.
An ordinary tick with insufficient accepted delta returns without advancing;
`timekeeping_forward_now()` instead assigns both anchors to the new reading
even when the accepted delta was zero. Thus writer type and consumed counter
are relevant if an anomalous read affects an update. This conditional source
behavior is not evidence that any such update happened during either fault.
[Writer delta](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping_internal.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n33),
[threshold](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/clocksource.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n986),
[forward-now](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n765),
[tick advance](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2328).

## Tick, NTP, wall-time and suspend invariants

Periodic and tickless tick maintenance call `update_wall_time()`, which advances
the shadow timekeeper under the raw lock. High-resolution syscall reads still
read the counter between updates; they are not simply the last jiffy. During
normal accumulation, RAW's anchor advances by an integer cycle interval while
its shifted base increases by that interval times its unchanged multiplier.
Subtracting the new anchor from a fixed counter cancels that base increment;
second normalization moves equivalent units between seconds and nanoseconds.
This algebra rules out ordinary RAW tick-boundary rounding as a sufficient
explanation, subject to the stated coherent-state and arithmetic premises.
[Periodic update](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/tick-common.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n86),
[tickless update](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/tick-sched.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n139),
[accumulation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2290).

NTP adjustment changes `tkr_mono.mult` and compensates `tkr_mono.xtime_nsec`
for the remaining unaccumulated cycles, preserving the conversion at the
adjustment point. The special underflow normalization also adjusts seconds;
it is not permission to publish a backward sample. `tkr_raw.mult` is not
changed by this adjustment. A wall-clock step updates `wall_to_monotonic` in
the opposite direction, and leap-second handling has the corresponding
offset update. Routine NTP or setting the wall clock therefore is not an
adequate explanation for the RAW event or the original MONOTONIC failure.
The audit does not exclude an actual implementation error without the
event-time state needed to test these invariants.
[Frequency compensation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2095),
[normalization](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2216),
[wall-time step](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1434),
[leap-second handling](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2261).

Suspend forwards outstanding awake time before marking timekeeping suspended.
Resume injects an accepted sleep duration into wall time and `offs_boot`, with
the opposite change to `wall_to_monotonic`, and rebases both cycle anchors.
RAW receives no sleep-duration addition. This explains BOOTTIME including
suspend while MONOTONIC and RAW exclude it. A stale or bad resumed counter
would still be a separate defect requiring evidence. An awake WFI interval
or a batch pause does not by itself establish that the system-suspend paths
ran, and an old PM success count does not establish correct counter retention.
[Sleep injection](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1857),
[resume](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1938),
[suspend](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2003).

## Physical-counter access and board idle path

For the captured boot configuration, the timer driver selects the physical
counter reader. Its ARM32 implementation executes ISB followed by a single
64-bit `MRRC` read of CNTPCT. The similarly named stable helper simply calls
that implementation on this architecture. There is no software loop stitching
together independently read high and low words. That narrows the mechanism;
it does not establish that the hardware value returned was correct.
[Reader selection](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n907),
[ARM32 reads](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/arch_timer.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n94).

The driver clears userspace physical-counter permission; it enables virtual
counter permission when no relevant workaround prevents it. A userspace
CNTPCT instruction is therefore not a supported way to collect the actual
physical value used by these syscalls. Instrument that consumed kernel value
instead of changing permissions or calling hidden vDSO code. A permitted
virtual-counter read would still be a separate observation.
[User-access setup](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n782).

The [CPI WFI driver](../kernel/overlay/drivers/cpuidle/cpuidle-cpi-wfi.c) uses
`arm_cpuidle_simple_enter()` for both ordinary idle and s2idle. That calls
`cpu_do_idle()`; the ARMv7 assembly is DSB, WFI, return. These callbacks do not
rewrite the counter or CNTVOFF. [Patch 0027](../kernel/patches/0027-cpuidle-state-zero-s2idle.patch)
admits eligible state zero into s2idle and handles its return correctly; it
does not change the clock conversion. The timer's separate CPU-PM notifier
preserves counter-access control, CNTKCTL, rather than resetting CNTPCT; the
simple WFI callback does not invoke that notifier itself. No timer-register
rewrite is identified in this board callback. Hardware counter behavior
across idle and any indirect effect of earlier PM activity remain unmeasured.
[Idle wrapper](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/kernel/cpuidle.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n28),
[ARMv7 idle](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/mm/proc-v7.S?id=1b357ecb321392158d507b04672ffee57bfa071d#n78),
[timer CPU-PM notifier](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n969).

Arm's Cortex-A7 r0p5 manual describes the counter value entering the processor
through an external 64-bit bus, `CNTVALUEB[63:0]`. A counter-observation fault
would not, by itself, identify the CPU core rather than the SoC's counter or
distribution path. The published Cortex-A7 erratum 803269 mentions CNTPCT,
but applies to r0p2–r0p4 accesses in processor debug state. The captured cores
are r0p5, and ordinary clock syscalls are not that debug-state operation.
Linux's PM debug tests are a different meaning of “debug.” This erratum does
not supply a matching explanation; this limited review does not establish
that the platform has no relevant errata.
[Cortex-A7 manual, §9.2](https://documentation-service.arm.com/static/602cf701083323480d479d18),
[Cortex-A7 errata, 803269](https://documentation-service.arm.com/static/5fa2a109b209f547eebd3660).

## Why a quiet clocksource log is insufficient

The captured configuration does not enable the hidden
`CONFIG_CLOCKSOURCE_WATCHDOG` option. In that build branch, watchdog scheduling
is absent and `clocksource_mark_unstable()` is empty. A continuous source can
still receive the high-resolution eligibility flag. The lack of an unstable
clocksource warning therefore is not an independent validation of these
counter readings.
[Kconfig](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/Kconfig?id=1b357ecb321392158d507b04672ffee57bfa071d#n9),
[watchdog-disabled implementation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/clocksource.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n732).

Enabling that facility alone would also not automatically monitor this source:
`arch_sys_counter` is registered as continuous, without
`CLOCK_SOURCE_MUST_VERIFY`. Watchdog enrollment puts sources with that flag on
the list to be checked and treats other eligible sources as reference
candidates. A useful independent-counter comparison would need an explicitly
reviewed reference, enrollment and detection threshold. It is not a substitute
for preserving the input of a sub-microsecond discrepant syscall. The ordinary
negative-delta conversion branch discussed above itself emits no warning.
[Architectural source flags](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n150),
[watchdog enrollment](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/clocksource.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n623).

Keep the counter-based clocksource, interrupt-generating clock-event device
and scheduler timestamp facility distinct. They can share hardware, but a
working timer interrupt or scheduler log timestamp does not prove the
clocksource conversion used by a particular syscall.
[Kernel timer roles](https://docs.kernel.org/timers/timekeeping.html).

## Hypotheses and discriminating evidence

| Explanation | Present assessment | Evidence needed |
| --- | --- | --- |
| Transient counter ahead/behind, or CPU-dependent counter observations | Mechanically compatible with a coherent syscall regression; not measured | Actual consumed counts and CPU attribution within accepted reader attempts |
| Corrupt or discontinuous timekeeper update | Unresolved; normal update algebra and publication do not identify a defect | Accepted conversion tuples plus the intervening writer's input, old/new state and update kind |
| Python/libc result conversion or memory corruption | Not eliminated by clean native runs; no defect identified in saved ABI/import analysis | Kernel result paired with the exact userspace timespec and integer for the same call |
| Ordinary fractional-nanosecond truncation, tick or NTP adjustment | Insufficient explanation under audited normal-path invariants; RAW excludes NTP rate adjustment | A violated premise, not merely proximity to a tick |
| ARM32 timekeeper tearing during a normal writer | Sequence protocol addresses this; no missing reader protection identified | Compiled-code/order evidence or a writer outside the protocol |
| BOOTTIME's sleep offset or `getboottime64()` implementation | Does not explain two MONOTONIC reads decreasing; wrong accessor for the latter | An actual state corruption or relevant reader path |
| Physical-versus-virtual vDSO route offset | Contradicted as the supported current route explanation by absent clock exports | New direct evidence of a different event-time route before reconsidering |

## Next measurement specification: preserve the consumed value

The next implementation slice is an offline, default-off diagnostic candidate
with fault-injection fixtures before a kernel build or live experiment.
Another clean fixed-count userspace comparison alone would
not distinguish the remaining kernel hypotheses. The useful capture must
connect the actual API return to its input, without changing how bad readings
are accepted or replacing one with a fresh read.

1. **Identify calls without the suspect clock.** Use PID/TID, a monotonically
   increasing diagnostic call ordinal, clock ID and syscall number. Preserve
   the original Python bracket as well as a native libc/syscall route when
   designing workloads; a native-only non-reproduction cannot absolve the
   original Python boundary. Retain boot, binary/config hashes, namespace,
   allowed affinity and task scheduling metadata.
2. **Record the accepted kernel attempt.** Capture the single `cycles` value
   actually used for that call's conversion, clocksource identity, accepted
   even sequence, retry count, actual read CPU, `cycle_last`, `mask`, `mult`,
   `shift`, `xtime_nsec`, relevant seconds/base/offset fields, `max_cycles`,
   chosen conversion branch, and source/change generation fields. Attribute
   CPU at the counter instruction with an explicitly reviewed migration-safe
   mechanism; userspace CPU endpoints or a CPU recorded later are insufficient.
   Any added preemption restriction must be reported as a scheduling
   perturbation. Preserve invalidated attempts separately if captured; they
   are not returned samples.
3. **Join the copy boundary.** Retain the final kernel timespec after namespace
   addition, syscall status, exact userspace timespec fields/bytes and the
   resulting Python/native integer for that same ordinal. This separates a
   decreasing kernel result from a changed value after the kernel conversion.
   A post-event reread of a register or `gettime` result is not a substitute.
4. **Retain nearby writer records.** Include tick/frequency/forward-now/source
   change/suspend-resume kind, writer CPU and its actual counter input,
   accepted delta, old/new anchors and conversion tuples. Use preallocated
   bounded memory and explicit loss/overflow counts, avoid printk or tracing
   callbacks that recursively read the clock, and export after capture. Do
   not depend on a clock deadline for the work bound or globally sort records
   using the clock under investigation. Preserve original values and stop
   once at the predeclared work/event bound; do not rerun until clean.
5. **Replay and decide offline.** For an unchanged accepted tuple, decreasing
   consumed cycles with matching decreasing kernel results localizes the
   symptom to counter observation, but does not identify silicon, idle or
   migration as its cause. Increasing cycles with a decreasing correctly
   reconstructed result across an update points to the tuple transition.
   Reconstruction disagreement points to instrumentation, arithmetic, source
   identity or corruption and must be resolved before attribution. Correct
   kernel output followed by a different userspace value moves the boundary
   to copying/runtime conversion. Incomplete or lost records remain
   inconclusive; absence of a recurrence is not qualification.

`ktime_get_snapshot()` is a useful source precedent: one counter read feeds
RAW and wall/boot conversions inside a sequence-validated snapshot, carrying
clocksource/change metadata. It does not export all conversion fields or
capture the count consumed by a separate syscall. Calling it beside a syscall
would create a different observation, so a wrapper around that API alone
would not meet this design.
[Snapshot implementation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1046).

No retry/clamping fix, clocksource switch, extra timer barrier, vDSO gate
removal, or restart-history reset follows from these findings. Keep the
[prepared guard fault handling](258-battery-clock-fault-handling.md) separate
from root-cause diagnosis and PM admission.

## Validation and remaining work

The archive digest, 27 upstream source-file comparisons, captured configuration
digest and three board-input digests passed verification. This report changes
documentation only; no runtime test, power saving or driver fix is claimed.
Before deploying a diagnostic, validate tuple replay, rejected sequence
attempts, call correlation, migration attribution, bounded storage and loss
reporting with synthetic faults and the actual ARM implementation. The
unmodified result must remain observable when injected counts move backwards.
Build and hardware qualification follow only after those checks; NEO-192's
original incident remains the admission blocker.
