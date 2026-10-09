# Awake clock-regression investigation

10 October 2026. NEO-192, blocking the camera-assisted NEO-191 PM sequence.
The battery monitor's original exception is preserved in
[report 256](256-camera-pm-preflight.md). A new bounded observation completes
60,000 clock sequences without reproducing it. The root cause is still open;
the installed battery guard, clocksource, image and PM admission are unchanged.

## Confirmed failure boundary

The installed battery guard and service unit exactly match the repository:

| File | SHA-256 |
| --- | --- |
| `battery_guard.py` | `5f97cad9ad6f51668d97121c7adb56178aefd309eb6bef6264638e1cf759d62f` |
| `gameshellneo-battery.service` | `373857580a6ab617b45f2da1df5f72c6a8ff6123e5c8069773b4adf8c4dcb570` |

The saved traceback points to the second `clocks()` call in the sampling loop.
That helper obtains MONOTONIC, BOOTTIME, then MONOTONIC. It raises if the second
MONOTONIC integer is smaller than the first; equality is accepted. Both clock
calls sit outside the exception handler for sysfs reads, so this error exits
the service instead of publishing a degraded observation. Systemd restarts it
after ten seconds. The earlier published battery JSON can remain until the new
process samples again. The existing PM validator catches the restart count.

This conflicts with the monotonic-clock contract described by
[Python's documentation](https://docs.python.org/3/library/time.html#time.monotonic),
but the original raw integers and CPU context were not saved. A traceback
establishes which branch executed, not the regression magnitude, frequency or
underlying timer defect. A wall-clock/NTP step is not an adequate explanation
for these particular calls. No clock value is clamped or reclassified as valid.

## Source boundaries to investigate

The device reports `arch_sys_counter`, with `timer` also available. Python
reports `clock_gettime(CLOCK_MONOTONIC)` with integer nanosecond APIs; this is
not a float-conversion comparison. That API report alone does not distinguish
userspace vDSO execution from a fallback system call.

The pinned Linux 6.18.54 source supplies the next comparison boundaries:

- `drivers/clocksource/arm_arch_timer.c`: the named architectural clocksource
  calls its selected architectural counter reader.
- `arch/arm/include/asm/arch_timer.h`: ARM32 physical/virtual counter readers
  issue an instruction synchronization barrier then a 64-bit CP15 read.
- `arch/arm/include/asm/vdso/gettimeofday.h`: the ARM vDSO hardware-counter
  path reads CNTVCT, with explicit clock-gettime syscall fallbacks.
- `lib/vdso/gettimeofday.c`: high-resolution and RAW conversions select their
  timekeeping data and use a fallback when the direct path cannot be used.

These are source inspection findings, not a measured call-path attribution.
The present Python-level recorder intentionally does not modify the selected
clocksource or CPU placement, read privileged counter registers, or inject
faults. A future direct-syscall versus vDSO comparison needs a verified ARM ABI
and identical measurement boundaries before attributing a discrepancy. No
Allwinner-family erratum is assumed to apply to this A33/R16 board by name.

## Saved measurement task

```sh
task device:clock-observe
```

The [device recorder](../tools/observe-clocks.py) runs 300 fixed batches of 200
sequences, pausing 0.1 seconds after each batch. Each sequence records a CPU
observation, RAW, MONOTONIC, BOOTTIME, MONOTONIC, RAW, and another CPU observation.
CPU observations bracket the calls; equal IDs cannot exclude migration away
and back, and they do not identify the CPU of every individual clock read.

It detects decreasing MONOTONIC/RAW values inside a sequence or between
adjacent sequences, and decreasing BOOTTIME between sequences. It preserves
both the previous and current raw records for the first 32 anomalous sequences,
plus exact total/category counts and explicit truncation. A read exception
stops the recorder without retry. There is no success-based repeat loop.
Fixed iteration bounds do not depend on the suspect clock reaching a deadline.

The [host runner](../tools/check-clock-observation.py) serializes against local
PM tasks, rejects an active device PM diagnostic, saves before/after snapshots,
and uses a 60-second device timeout with five-second kill grace plus a host
timeout. The measurement runs as the ordinary device user. It does not write
to clocks, battery controls, affinity or system settings. It validates exact
work counts, recomputes retained anomaly classifications from their raw values,
checks preserved state/kernel-record continuity and independently proves
Wi-Fi recovery after the USB operation.

The runner allows observation of the already-known restart condition while
services are active; it does **not** replace or relax the PM admission validator.
Its summary explicitly sets `pm_admission: false` and
`clock_reliability_qualified: false`, even for zero anomalies. This task is a
diagnostic workload, not an idle-power measurement or a long-term reliability
test. Its timeouts and the fixed-work cap also do not prove clock correctness.

## First capture

Private evidence: `.local/diagnostics/20261009T213556.111905Z/` in the active
worktree, including original `before.json`, `observation.json`, `after.json`,
source hashes and `summary.json`.

| Observation | Result |
| --- | --- |
| Completed sequences | 60,000 |
| Decreasing-value sequences | Zero in this capture |
| Minimum MONOTONIC bracket | 3,542 ns |
| Minimum RAW bracket | 7,541 ns |
| First-to-last RAW interval | About 41.96 seconds |
| Recorded process CPU time | About 12.03 seconds |
| CPU IDs at first and last sequence | CPU 2 at both boundaries |
| Different CPU IDs within a bracket | Zero; this is not all-CPU coverage |
| Device state | Same boot, PM53/0, restart count still 1, screen/controls unchanged |
| Network proof | USB operation and separate Wi-Fi proof passed |

The 12-second CPU cost illustrates why this capture must not be mixed with
idle/energy measurements. Neither the positive bracket minima nor the absence
of a regression establishes timing accuracy, migration safety or long-term
clock reliability. The original service failure remains valid evidence.

`observation.json` SHA-256:
`bebe0a8b1587c2d0fa805853d55b367b23ed9d4e834ac2fb4ea407e5df37299f`.
`summary.json` SHA-256:
`949ef8b04b5b25ef028f70d5eb0eaa689537692b7035449db75ac2002ab93389`.
The original saved unit-journal excerpt has SHA-256
`96c2018858a4b4c40a11a36bbe433402deb50682e5d719164ac36b5d8b41fdf0`.

## Validation and next boundary

Six offline recorder tests cover decreasing/equal values, category attribution,
fixed work, event caps, read-failure propagation, missing work, forged raw-event
classification, boot mismatch and changed device state. The full host check
passes **16 runtime and 910 tooling tests** (one existing optional skip), both
C checks and shell lint. Its saved output is `.local/neo192-check.log`.

NEO-192 remains in progress. Next separate the clock-source/call-path question
from robust guard fault handling: a clock fault should preserve its raw values,
publish degraded status and invalidate consecutive low-battery history without
becoming a valid sample or silently clearing the incident on the next read.
That requires tests and an explicit observation/admission contract before
replacing the installed guard. It is not a substitute for resolving a driver
or timekeeping defect if one is established. No such runtime correction is
included here.

Keep the original boot and restart evidence while investigating. Do not clear
service counters, switch clocks or reboot simply to resume the seven PM checks.
The camera workflow is available once health admission is resolved. NEO-182's
physical-unplug and clean 60-second battery trial remain separate pending work.
