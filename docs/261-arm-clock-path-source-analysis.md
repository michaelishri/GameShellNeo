# ARM clock paths and the saved RAW discrepancy

**Correction from the subsequent same-boot investigation:**
[report 263](263-native-clock-vdso-availability.md) identifies an omitted
boot-time gate in `arch/arm/kernel/vdso.c`. The observed timer DT flag makes
Linux remove the clock export names, and the live mapped vDSO resolves none
of the four clock functions. A mapping and `CONFIG_VDSO=y` therefore do not
establish clock-function availability on this board. The counter-access
comparison below remains useful source analysis, but a working direct vDSO
route is no longer the supported explanation for the saved discrepancy.

10 October 2026. NEO-192. This source investigation follows the single
750 ns cross-path discrepancy in
[report 260](260-clock-comparison-provenance.md). It identifies a concrete
counter-access distinction worth measuring: the kernel uses the physical
architectural counter, while an ARM32 vDSO high-resolution read uses the virtual
counter. It does **not** establish that Python took the vDSO path during the
event, that either counter is defective, or that this explains the original
battery-guard exception.

This slice only inspected saved evidence, local sources and primary online
documentation. It did not access the GameShell, change a driver or clocksource,
run another measurement, enter sleep, or reset any fault evidence. The separate
[runtime inventory](262-clock-runtime-inventory.md) records the installed
Python/libc boundary.

## Evidence and source identity

The saved event remains exactly as reported in report 260: sequence 51,
`CLOCK_MONOTONIC_RAW`, with CPU 1 observed at both ends. Its last explicit
syscall result was `62049008553837` ns; the following Python result was
`62049008553087` ns. The difference is −750 ns. Python-only readings and
kernel-only readings each increased, and the complete capture did not report
a between-sequence regression. Matching endpoint CPU IDs do not establish the
CPU of every intervening read or exclude migration away and back.

The original private capture is
`.local/diagnostics/20261009T225220.923744Z/`. Its preserved `before.json` also
contains these boot observations:

- CPU identifier `410fc075`, identifying Cortex-A7 r0p5.
- `arch_timer: cp15 timer running at 24.00MHz (phys).`
- `CPU: All CPU(s) started in HYP mode.`
- `arch_sys_counter` as the active clocksource, with `CONFIG_VDSO=y` and
  `CONFIG_ARM_ARCH_TIMER=y`.

The source baseline is Linux 6.18.54, commit
`1b357ecb321392158d507b04672ffee57bfa071d`, as recorded in
[sources.lock.json](../build/sources.lock.json). The archive's independently
calculated SHA-256 is
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`, matching
the lock. The sixteen source files in the final table were compared byte for
byte with that archive and match. Thus the analysis below concerns the exact
pinned release rather than today's moving upstream branch. Source hyperlinks
use that fixed commit and line anchors; their contents were inspected locally
because the web reader could not retrieve the pinned kernel.org pages.

## Two possible userspace routes, one explicit kernel route

The recorder's explicit ARM EABI syscall 403 is the time64 `clock_gettime`
entry. For RAW, the POSIX-clock table selects `posix_get_monotonic_raw()`, which
calls `ktime_get_raw_ts64()` and then applies the monotonic time-namespace
offset. The ordinary and time32 syscall wrappers both ultimately dispatch
through the same clock's `clock_get_timespec` operation; timespec width alone
does not select a different RAW timekeeper.
([Syscall dispatch](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1136),
[RAW handler](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n229),
[time32 wrapper](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1291).)

Python's normal API can reach a libc implementation that uses the vDSO or
falls back to a syscall. The kernel's ARM vDSO provides both time64 and time32
fallback helpers; its time64 fallback also invokes syscall 403. A vDSO mapping
or `CONFIG_VDSO=y` alone does not establish clock exports;
those can be removed at boot. Even a resolved exported function does not prove
the internal branch taken by an individual call. See the correction above.
([ARM fallbacks](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/vdso/gettimeofday.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n36).)

For a direct vDSO RAW read, `__cvdso_clock_gettime_common()` selects `CS_RAW`
and `do_hres()`. That reads the vDSO RAW timekeeping data and the architectural
counter without entering the kernel. Unsupported modes or a failed direct
path lead to the syscall fallback. This source route is a candidate route for
the Python result, not a measured attribution.
([Clock selection and fallback](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/lib/vdso/gettimeofday.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n287).)

## Physical and virtual counter access

The inherited A23/A33 timer DT node supplies 24 MHz and
`arm,cpu-registers-not-fw-configured`. On ARM32 that flag makes
`arch_timer_of_init()` select the physical secure PPI. `arch_counter_register()`
then selects `arch_counter_get_cntpct()` when there is no counter workaround.
The preserved `(phys)` boot line independently supports this selection on the
running image. `arch_sys_counter` itself is only the clocksource name; the
selected read-function pointer determines physical versus virtual access.
([A23/A33 timer node](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi?id=1b357ecb321392158d507b04672ffee57bfa071d#n78),
[PPI selection](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1161),
[counter registration](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n907).)

The accessors differ as follows:

| Source route | Counter instruction | Ordering present |
| --- | --- | --- |
| Kernel physical accessor | `mrrc p15, 0, ..., c14` (`CNTPCT`) | `isb()` immediately before the read |
| Kernel virtual accessor, if selected | `mrrc p15, 1, ..., c14` (`CNTVCT`) | `isb()` immediately before the read |
| ARM32 vDSO direct accessor | `read_sysreg(CNTVCT)`, expanding to the same virtual-counter `mrrc` | `isb()` immediately before the read |

These are single 64-bit CP15 reads into a register pair, not two independent
32-bit reads of a memory-mapped counter. The source therefore does not expose
a simple high-word/low-word software tearing bug. Both instruction paths
already contain an instruction synchronization barrier. On ARMv7 its inline
assembly also has a compiler `memory` clobber; adding another barrier without
an established missing ordering requirement is not yet a justified fix.
([Kernel accessors](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/arch_timer.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n94),
[vDSO accessor](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/vdso/gettimeofday.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n114),
[CP15 expansion](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/vdso/cp15.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n14),
[barrier definition](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/barrier.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n18).)

Arm describes the virtual count as the physical count minus the virtual offset.
The Cortex-A7 TRM also describes the externally supplied counter bus and lists
the separate physical count, virtual count and offset registers. Thus the CPU
model alone does not certify the SoC's counter integration.
([Arm Generic Timer guide, section 3.5](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/Learn%20the%20Architecture/Generic%20Timer.pdf?revision=c710e7a7-9f52-4901-8c9d-91b19f44f9c7),
[Cortex-A7 TRM, sections 9.2–9.3](https://documentation-service.arm.com/static/602cf701083323480d479d18?token=).)

### CNTVOFF initialization narrows the offset hypothesis

A fixed physical-versus-virtual offset remains a useful *measurement
hypothesis*: nonzero call spacing can hide an offset in almost every
interleaved sequence and reveal a negative difference only when that spacing
is unusually short. A rare interleaved failure is therefore not by itself
proof of an intermittent hardware read glitch.

However, the saved boot evidence argues against simply assuming that firmware
left the offset uninitialized. The kernel's primary and secondary entry paths
call the HYP stub installer. When the CPU entered in HYP mode and supports the
architectural timer, that installer writes zero to `CNTVOFF`. The preserved
boot line says all CPUs entered in HYP mode. Together, source and boot evidence
support zero initialization on all cores; they are not a current register
readback and do not prove the value stayed zero throughout the boot.
([Primary/secondary entry](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/kernel/head.S?id=1b357ecb321392158d507b04672ffee57bfa071d#n96),
[HYP validation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/kernel/hyp-stub.S?id=1b357ecb321392158d507b04672ffee57bfa071d#n81),
[CNTVOFF initialization](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/kernel/hyp-stub.S?id=1b357ecb321392158d507b04672ffee57bfa071d#n145).)

The A23/A33 non-PSCI secondary-start routine points directly to
`secondary_startup`; the separate secure-mode `CNTVOFF` initialization in the
A83T machine definition should not be credited to A33. The pinned legacy
U-Boot input is a binary, and no exact source tree for that binary was found in
the inspected inputs. This investigation does not substitute newer U-Boot
source as proof of the installed binary's behavior.
([A23/A33 secondary boot](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/mach-sunxi/platsmp.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n156),
[A83T-specific initialization](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/mach-sunxi/sunxi.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n77),
[bootloader lock](../build/sources.lock.json).)

## Conversion and update behavior

Both normal RAW conversion paths implement the same fixed-point expression:

```text
delta = (counter - cycle_last) & mask
nanoseconds = (delta * mult + shifted_base_nanoseconds) >> shift
result = raw_seconds * 1_000_000_000 + nanoseconds
```

The vDSO receives `cycle_last`, `mask`, `mult`, `shift`, `raw_sec` and
`tkr_raw.xtime_nsec` from the same timekeeper used by the kernel. RAW uses
`tkr_raw`, not the NTP-adjusted MONOTONIC multiplier. RAW accumulation advances
its cycle anchor and shifted base together. With the same coherent parameters
and counter value, the ordinary formulas agree; ordinary fractional-nanosecond
rounding is not a sufficient explanation for −750 ns.
([Kernel conversion](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n378),
[vDSO conversion](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/lib/vdso/gettimeofday.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n43),
[data publication](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/vsyscall.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n18),
[RAW accumulation](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n2300).)

There are deliberate exceptional-path differences. The kernel checks a delta
against `max_cycles`, handles multiplication overflow, and suppresses a delta
whose high mask bit indicates motion behind the last timekeeper anchor. The
generic vDSO has optional overflow protection and no corresponding explicit
negative-delta suppression in this default conversion. Neither is a general
comparison against the previous value returned to a process: a bad counter
read can move backward relative to a previous read while remaining ahead of
the timekeeper anchor. The saved event does not include raw counter values or
the contemporaneous conversion data, so it cannot establish whether an
exceptional branch was taken.
([Kernel exceptional paths](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n378),
[vDSO delta handling](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/lib/vdso/gettimeofday.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n20).)

Both paths use sequence-counter retry protocols. The kernel RAW reader retries
if the timekeeper changed while reading. The vDSO waits for an even sequence,
orders data reads with `smp_rmb()`, then checks the sequence again after a
second read barrier. Publication marks both vDSO clock records invalid before
writing and uses write barriers before making them valid. This is designed to
avoid mixed 32-bit reads of concurrently updated 64-bit fields.
([Kernel RAW reader](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n1645),
[vDSO reader](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/lib/vdso/gettimeofday.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n149),
[vDSO sequence helpers](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/vdso/helpers.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n10).)

The timekeeping update routine additionally opens the kernel sequence before
publishing vDSO data, copies the new kernel timekeeper, then closes the kernel
sequence. Its comment explicitly identifies cross-vDSO/kernel backward-time
ordering as the reason. A routine tick/update is therefore not an adequate
explanation without evidence of a violated invariant, unexpected counter
value or implementation defect. Different sequence counters alone do not
prove an unprotected race.
([Update ordering](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n708).)

## Errata: established scope and limits

The pinned ARM32 header makes `has_erratum_handler()` false and its stable
counter wrappers call the normal accessor. This establishes an implementation
limitation, not that the hardware is error-free.
([ARM32 timer header](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/include/asm/arch_timer.h?id=1b357ecb321392158d507b04672ffee57bfa071d#n15).)

Linux has an Allwinner A64 workaround for unreliable low counter bits near
rollovers. Its configuration depends on ARM64 and SUNXI, and its DT property
enables a bounded repeated-read strategy. When an applicable workaround
requires special virtual-counter reads, the generic timer driver disables
the direct vDSO fast path. That is useful design precedent **if** a comparable
defect is established here, but neither the Allwinner name nor a similar
symptom extends an A64 erratum to Cortex-A7 R16/A33.
([A64 configuration scope](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/Kconfig?id=1b357ecb321392158d507b04672ffee57bfa071d#n380),
[A64 read workaround](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n277),
[vDSO workaround policy](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/arm_arch_timer.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n491).)

Arm's public Cortex-A7 Software Developers Errata Notice v14, dated 6 May
2016, was checked, including its revision summary and counter-related entries.
It does not identify a matching architectural-counter regression. Its PMU
event-counter issues are not evidence about `CNTPCT`/`CNTVCT`. This is a limited
negative finding about that document: it neither rules out an undocumented
CPU issue nor certifies Allwinner's external counter distribution.
([Arm Cortex-A7 SDEN v14](https://documentation-service.arm.com/static/5fa2a109b209f547eebd3660?token=).)

At 24 MHz, 750 ns corresponds arithmetically to 18 counter ticks. That does not
mean a raw counter was observed to jump by 18: the two timestamps were read at
different instants, with intervening return/call overhead and possible
scheduling. The actual counter and offset values were not captured. Nor can
the event's position just after a batch pause identify WFI/idle exit as its
cause.

## What the evidence now supports

| Claim | Status |
| --- | --- |
| One saved Python/API versus explicit-kernel RAW ordering discrepancy occurred | Proven by retained integer results and independent host reclassification |
| The running kernel reports physical architectural timer access at 24 MHz | Proven by preserved boot log, with matching pinned source route |
| Direct ARM32 vDSO access uses the virtual counter | Proven by pinned source; event-time use by Python remains unproven |
| Kernel startup should initialize CNTVOFF to zero on the observed HYP-entry path | Strong source-plus-boot inference; no register readback |
| Normal conversion rounding explains −750 ns | Unsupported; normal formulas are the same |
| Fixed or per-CPU path offset could be hidden by measurement spacing | Plausible hypothesis; no measured offset yet |
| R16/A33 suffers the documented A64 timer erratum | Unsupported |
| This reproduces the guard's original Python MONOTONIC regression | False: the clock family and comparison boundary differ |

The next useful boundary is the installed libc dispatch and exact runtime
binary provenance, followed by a separately designed bounded comparison if
those findings justify it. Any further recorder should separate explicit
kernel, direct vDSO and ordinary API results rather than infer one route from
another; CPU placement and raw counter access require their own explicit
design. Preserve original failures and avoid success-based reruns. A driver
change needs an identified failure mechanism and a measurement that can show
the correction without masking bad samples.

NEO-192 remains unresolved. The original MONOTONIC guard failure, PM admission
block and uninstalled guard candidate all remain as documented in reports
257–260. No reliability, suspend-resume or energy qualification follows from
this source analysis.

## Verified local source hashes

All paths below are relative to the locked Linux archive root. Each matched
the corresponding file under `.local/sources/linux-6.18.54/`.

| File | SHA-256 |
| --- | --- |
| `arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi` | `72e9a1aee9b797830d295ee591c8e447f8c2374dba796acd414e9cb1ec466335` |
| `arch/arm/include/asm/arch_timer.h` | `4ad6a3011117480f804e50bf888a386fce7830bc35365897de020aa15324507c` |
| `arch/arm/include/asm/barrier.h` | `81af4951183749c6918dee9f6dbb5b2493e6eb2e5122ba8d9f2a0f9ab8692a55` |
| `arch/arm/include/asm/vdso/cp15.h` | `f04636a58c2869114e0820e744df43fe4d13da08035603c1e5474b9c2106f009` |
| `arch/arm/include/asm/vdso/gettimeofday.h` | `d7e5c603abf1543196a59b02d24f4ff067c308edf2fc84e5f8cc87b17b75bfa9` |
| `arch/arm/kernel/head.S` | `9ed44dcfaacfa52916c8dd420eb4e8b8a3033c92154c1c43917b308d0510d6c9` |
| `arch/arm/kernel/hyp-stub.S` | `c972f77d3ca5e3e4ac9cc0dd9535dc0a706684ba5e5123b4b0e0301d7e0f8870` |
| `arch/arm/mach-sunxi/platsmp.c` | `715bbfa3543be47d24c9a34e12bdff83060b75add7cd3433d47943a2bc72b1e3` |
| `arch/arm/mach-sunxi/sunxi.c` | `2ece02c0883b1a4ee8fb6bf2acc1eafe9c5eb37deedd1d319d0d9fbe50965326` |
| `drivers/clocksource/Kconfig` | `af11220021629edb4ad6e1a7d71b5c1419b636a0c9f546e4d6412b41b62d7697` |
| `drivers/clocksource/arm_arch_timer.c` | `0613e2f5d21a736e98fb993db17e8db5c8e050b813c59035fb5bd4a696dd7ead` |
| `include/vdso/helpers.h` | `5e8a5f34aa84e12669a5a842593f29fc0c9c66fdc637fb275e4841ed6a7be784` |
| `kernel/time/posix-timers.c` | `fc461ffc3f9bc10598424252ed3fe0f7d647ff3237b440f3a158d4a5b829ef08` |
| `kernel/time/timekeeping.c` | `110b4e828af0e8c6bcdfb926fa117c89e18fa41171acc3fe4a7a67b00ac01b57` |
| `kernel/time/vsyscall.c` | `c48d298e8a73f298917337fd2305b4366130140d9819175d4c934f5c060970af` |
| `lib/vdso/gettimeofday.c` | `5ba1b4bf2ccd1c26ba2f0caac7b5552635136bc2749ca1b30793882c7d064f3f` |
