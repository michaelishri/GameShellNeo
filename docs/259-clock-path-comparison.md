# Prepared Python/kernel clock comparison

10 October 2026. NEO-192, following the clock evidence in
[report 257](257-awake-clock-regression-investigation.md) and the uninstalled
guard candidate in [report 258](258-battery-clock-fault-handling.md).

The next diagnostic compares the guard's ordinary Python clock APIs with
explicit ARM EABI `clock_gettime64` calls. Its focused tests and pinned-source
ABI check pass. **There is no hardware result yet:** the sandbox denied socket
creation before reaching the Mac, and automatic permission review timed out
for the authorized attempt. The installed guard and original fault evidence
remain unchanged.

## Repeatable commands

```sh
task check:clock-abi       # Host-only verification of the locked Linux archive
task device:clock-compare # One bounded awake capture over the normal USB SSH route
```

The device task keeps the screen on. It changes no clocksource, CPU affinity,
service, PM control or charger setting and requires no physical action. It does
not request sleep, sound or a camera capture.

## Verified ABI boundary

The host verifies the SHA-256 of the already-downloaded Linux archive named in
`build/sources.lock.json`, then reads eight source files without extracting or
executing them. It checks and saves hashes for:

- ARM's syscall table: common entry 403 is `clock_gettime64`/`sys_clock_gettime`.
- EABI's syscall base of zero.
- `__kernel_timespec`: signed 64-bit seconds followed by signed 64-bit
  nanoseconds, rather than the legacy ARM 32-bit timespec.
- MONOTONIC, MONOTONIC_RAW and BOOTTIME clock IDs 1, 4 and 7.
- ELF constants identifying 32-bit, little-endian ARM with EABI version 5.

Before resolving or calling `libc.syscall`, the device helper checks its running
process: Linux/armv7l, ELF identity, endianness, integer/pointer widths, and the
ctypes structure's 16-byte size, eight-byte alignment and field offsets 0/8.
Other ABIs are rejected. Clock IDs cannot be supplied by the caller. The return
code, errno and timespec fields are checked; failed/invalid kernel reads retain
their original fields and stop without a fallback or retry.

This avoids guessing a native `struct timespec` layout or invoking an ARM
syscall number on an x86 or ARM64 process. It does not prove which internal path
Python takes. The normal API might use vDSO or a system-call fallback; results
must be described as **Python API versus explicit kernel calls**, not as a
proven vDSO comparison.

## Measurement and evidence

The fixed workload is 300 batches of 50 sequences, with a 0.1-second pause per
batch. Every sequence visits each clock family separately and reads:

`CPU → Python → kernel → Python → kernel → Python → CPU`

Comparisons stay within the same clock domain. The recorder detects decreasing
Python values, decreasing kernel values, inconsistent interleaved ordering and
regression between consecutive sequences. An interleaved discrepancy is a lead,
not proof that either path is responsible. It stores the first 32 discrepant
sequences with previous/current raw records, exact category/sequence totals,
explicit truncation, and the first/last completed sequence.

CPU histograms count where each clock family's first CPU observation occurred;
separate counts record differing CPU observations across that family. Equal CPU
IDs cannot exclude migration away and back, and these are not per-read CPU
identities. Affinity is observed before/after and never changed. Unobserved CPUs
must not be claimed as tested.

Read errors preserve a partial sequence and identify the failing phase. They
cannot produce a completed comparison. The host independently reclassifies
saved discrepancies from raw values, checks work/CPU counts and metadata, and
rejects incomplete evidence. There is a 90-second device timeout with five-second
kill grace, plus a host timeout. The task takes the existing local PM lock and
refuses an already-active device PM diagnostic. Before/after state and PM
counters are checked; this is not a claim of exclusive ownership against every
external actor.

Matching image/kernel, active services and configured USB power are required.
The known service restart can be inspected without granting PM admission.
After a submitted command, the host attempts postflight inspection even if
the command fails; it never resubmits the measurement automatically. A completed
result also requires unchanged device state/kernel continuity and independent
Wi-Fi proof. Every successful summary explicitly retains:

```json
{"clock_reliability_qualified": false, "pm_admission": false}
```

The work is diagnostic CPU load. It must not be mixed with idle-power or battery
endurance measurements, and a short clean result cannot clear the original
service failure.

## Validation and current execution status

Eleven new offline tests pass. They cover ABI rejection before syscall
resolution, 64-bit seconds, kernel errors and malformed timestamps, changed
source definitions, fixed work/equal ticks, ordering classification, event caps,
partial failure, CPU/metadata/work validation, forged classifications, and
postflight collection without resubmission after a transport failure.

`task check:clock-abi` passes against the actual hash-verified Linux 6.18.54
archive. Its private receipt is under
`.local/diagnostics/20261009T222018.521432Z/abi-sources.json` in the active
worktree. Python compilation, Bash syntax and ShellCheck also pass.

The full sandboxed check reports **24 runtime tests passing; 924 tooling tests
run, with five local-socket fixture errors and one optional skip**. The five
errors are the existing transport fixtures denied socket operations by the
sandbox. The full suite is not claimed as passing. Automatic review timed out
twice for the unrestricted offline-suite request, so those checks remain
pending. Log: `.local/neo192-clock-paths-sandbox-check.log`.

The sandboxed device command saves its ABI receipt at
`.local/diagnostics/20261009T222412.982732Z/` and fails at socket creation before
contacting the Mac. There is no before/after device snapshot, clock capture,
camera observation or successful summary in that attempt. Its log is
`.local/neo192-clock-paths-device.log`. The separately requested authorized
device command was not started because automatic review timed out.

No new physical test is needed. The next execution step is the complete offline
suite with local-socket access, then one awake comparison through the existing
Mac route. NEO-192 remains open, and NEO-191/182 remain pending the unresolved
clock failure. No restart counter, incident record or installed producer was
changed to make testing proceed.
