# Native clock diagnostic and unavailable vDSO clock exports

10 October 2026. NEO-192, continuing reports
[260](260-clock-comparison-provenance.md),
[261](261-arm-clock-path-source-analysis.md) and
[262](262-clock-runtime-inventory.md).

**The current GameShell does not expose usable vDSO clock entry points.** The
new native three-route comparison stopped before taking any clock samples.
A separate same-boot inventory verified the mapped vDSO's identity and found
all four clock functions absent from both versioned and unversioned lookup.
This matches an ARM kernel boot-time rule omitted from report 261: the timer
DT flag causes Linux to remove those export names.

This is useful attribution evidence, not a fixed clock bug or successful
405,000-reading capture. The original backwards MONOTONIC bracket and the
later −750 ns RAW discrepancy remain unresolved. NEO-192 stays open; NEO-191
PM qualification and NEO-182 battery sleep remain pending.

## What was implemented

The saved offline build task is `task check:clock-native`. It verifies the
hash-locked Linux archive's ARM syscall/time64 definitions, vDSO signature,
version script and boot-time implementation. A pinned, network-disabled Docker
container runs the C capture fixtures natively and under ARM/QEMU, then builds
a dynamic ARM32 EABI5 hard-float executable. Compile-time assertions distinguish
libc's seconds64/nanoseconds32-plus-padding layout from the kernel and vDSO's
seconds64/nanoseconds64 layout. Both are 16 bytes on this target.

The build retains exact source, build script, ELF metadata, disassembly, hashes
and fixture output. The device runner rejects stale/tampered artifacts, checks
that its versioned imports exist in the previously hash-verified target libc,
and verifies the installed libc hash before and after execution. The comparator
imports `__clock_gettime64@GLIBC_2.34`; it does not substitute a legacy time32
structure for the explicit syscall or vDSO call.

`task device:clock-native` has fixed production bounds: 300 batches of 50
sequences, with one 100 ms pause per batch. Each sequence requests MONOTONIC,
RAW and BOOTTIME in the order libc → syscall403 → vDSO → libc → vDSO → syscall403
→ vDSO → syscall403 → libc. This covers all six directed adjacent route pairs.
It records CPU IDs at the ends of each family and retains all integer readings
in memory until output. It does not pin the process or claim per-read CPU
identity. Failed reads, invalid timespecs, interrupted pauses and metadata
changes stop the run; they are never retried or clamped.

The vDSO resolver uses `AT_SYSINFO_EHDR`, matches its dynamic-loader mapping,
opens that already-loaded object and verifies the handle's base. It resolves
`__vdso_clock_gettime64` at `LINUX_2.6`, then checks that the resolved address
belongs to the mapping. If that cannot be established, the comparison exits
before its sampling loop. There is no fallback to a differently labeled route,
hidden raw-address call, timer reconfiguration or removal of the admission check.
A callable vDSO entry could itself use a syscall fallback; the analyzer never
claims otherwise.

The host independently classifies every retained reading, preserving integer
precision, adjacent route disagreements, within-route and between-sequence
regressions, CPU counts and negative-delta context. Only the convenient event
summary is capped at 32; complete raw readings remain private. The offline
`report:clock-native` task requires a completed, hash-verified comparison and
writes a new report without overwriting the original.

## Stopped comparison and focused inventory

The first attempt used build `20261009T231425.767282Z` and saved its original
output at `.local/diagnostics/20261009T231750.335140Z/`:

```text
Cannot establish the mapped, versioned ARM time64 vDSO entry.
```

The command exited 1. No sample loop ran and no comparison summary was
published. Before/after inspections were saved despite failure; their state
and protected kernel evidence checks pass. The failed attempt was not rerun
as though successful. Its small private staging directory remains recorded in
`remote-stage.json`; the original source and binary remain in the build capture.

The next build added an explicit `--inspect-vdso` mode, exposed by the saved
`device:clock-vdso` task. This resolves the four clock names without invoking
any clock function. It distinguishes missing functions from a missing mapping,
a handle for the wrong object or a version mismatch. The normal comparison
still requires a verified time64 entry.

```sh
task check:clock-native
task device:clock-vdso BUILD=20261009T232021.120014Z RUNTIME_CAPTURE=20261009T230039.014366Z INSPECTION_REVISION=be6c719c1b8e1637b69fa3e94a96b370adfb84d2
```

The explicit inspection revision preserves this boot's original checkpoint
producer. It only selects the inspection bundle; it cannot select an old PM
test or bypass normal PM admission. Use timestamps from newly completed local
build/runtime tasks when repeating this workflow.

The completed live inventory is
`.local/diagnostics/20261009T232126.633257Z/`. It reports:

| Check | Result |
| --- | --- |
| vDSO mapping found | Yes |
| Loaded handle base matches `AT_SYSINFO_EHDR` | Yes |
| Requested symbol version | `LINUX_2.6` |
| `__vdso_clock_gettime64` | Absent, versioned and unversioned |
| `__vdso_clock_gettime` | Absent, versioned and unversioned |
| `__vdso_gettimeofday` | Absent, versioned and unversioned |
| `__vdso_clock_getres` | Absent, versioned and unversioned |
| Installed libc | glibc 2.41, matching the saved binary hash |
| Clock samples taken | 0 |

The inventory's raw SHA-256 is
`30d89079ba916a0f78fa5da6ede5174e06195dafdd20a4cb8ddc40eb8ee79e90`.
The final ARM diagnostic binary SHA-256 is
`55ece7a05c9eb551e8e6333e61cfa248299af235fa118b97fc1297a463a94b7f`.

## Why Linux hides these exports

The pinned `arch/arm/kernel/vdso.c` implements the following boot sequence:

1. `cntvct_functional()` finds the ARM timer node. If it has
   `arm,cpu-registers-not-fw-configured`, the function returns false.
2. `patch_vdso()` responds by calling `vdso_nullpatch_one()` for all four clock
   functions listed above.
3. That helper sets each dynamic symbol's `st_name` to zero. The mapping and
   code may remain present, but those functions can no longer be found by name.
4. `vdso_init()` patches the shared vDSO before it is installed into processes.

The earlier runtime inventory already records that exact timer property, and
the saved boot log selects the physical architectural counter. The new live
lookup result matches this source behavior. The policy avoids an extra vDSO
dispatch that would only need to fall back to a syscall; it is not evidence of
a broken dynamic loader or a missing build option.

The file was read from the SHA-256-verified Linux 6.18.54 archive at commit
`1b357ecb321392158d507b04672ffee57bfa071d`. Its own SHA-256 is
`76958abbf396e29e59c1e0b06f5b9eda17ebe9addd58dd7031f7f3935b4429dd`.
The exact-source receipt is saved with the second native build. The relevant
upstream source is [ARM vDSO initialization, lines 59–199](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/kernel/vdso.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n59).
The web reader could not retrieve that pinned page; the inspected content came
from the local hash-verified archive. The ordinary dynamic-loader lookup
approach also appears in the pinned kernel's vDSO correctness selftest.

## Revised interpretation and next investigation

Report 261 correctly describes what a direct ARM vDSO read would do, but missed
the gate that prevents that route on this boot. Report 262 correctly describes
the installed libc's candidate dispatch branches, without establishing their
availability. Both reports now point to this correction.

With the named vDSO clock functions unavailable, the expected installed libc
route is its syscall fallback. This is an inference from the same-boot live
exports, pinned kernel initialization and verified libc implementation; it is
not a retrospective per-instruction trace of the original guard event. It
substantially weakens the proposed physical-versus-virtual counter mismatch
for the earlier RAW discrepancy. A vDSO mapping alone was insufficient evidence.

The next useful measurement is an **explicitly specified two-route native
libc/syscall comparison**, with CPU context and retained raw readings, followed
by inspection of physical-counter/timekeeper behavior if it reproduces a
decrease. Do not silently downgrade the three-route task or force vDSO access
through a raw address. Normal scheduling can migrate between the endpoint CPU
observations, so source-level ordering and actual counter behavior still need
careful separation. Neither the original MONOTONIC failure nor the RAW event
has yet been assigned a root cause.

There may eventually be an optimization in qualifying the board's virtual
counter and vDSO clock support. That would require bootloader, per-CPU timer
configuration and retention/resume evidence before changing the inherited DT
flag. No timing, battery-life or energy improvement is measured here, and that
possible optimization must not be used to hide the current clock fault.

## Device preservation and validation

The completed inventory retained boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`, kernel
`6.18.54-gameshellneo24`, PM success/failure **53/0**, and battery-service
`NRestarts=1`. Before/after state and protected kernel evidence checks pass;
USB and Wi-Fi access both pass. No screen blanking, sleep, reboot, affinity or
clocksource write, service restart, installed guard replacement or charger
setting change occurred.

Offline validation includes host and ARM/QEMU capture fixtures, ARM production
ABI assertions, the linked ELF's time64/import checks and twelve Python tests.
Those tests cover all 405,000 synthetic readings, integer values above floating
point exactness, route-specific and cross-route regressions, partial evidence,
identity changes, raw hash checks, build tampering, target import compatibility,
missing exports and one failed remote attempt with postflight and no retry.
The final full suite passes **24 runtime tests and 947 tooling tests**, with
one optional skip, both existing C checks, Bash syntax and ShellCheck.
Logs are `.local/neo192-native-build-v2.log`,
`.local/neo192-native-unit.log`, `.local/neo192-native-final-check.log`,
`.local/neo192-native-device.log` (the stopped comparison) and
`.local/neo192-vdso-device.log` (the completed inventory).
