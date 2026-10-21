# Native clock comparison across all four CPUs

10 October 2026. NEO-192. Follows the unpinned two-route comparison in
[report 264](264-native-libc-syscall-comparison.md).

**One completed capture covered all four cores evenly and retained 270,000
readings with zero ordering discrepancies.** Every requested CPU matched the
recorded endpoints and batch affinity checks. The diagnostic restored its
original mask; USB/Wi-Fi, PM counters and original fault evidence remain
unchanged. Offline replay reproduces the result. This closes the earlier
capture's CPU-coverage gap, while leaving the underlying clock fault unresolved.

## Experiment and scope

The prior capture observed CPU 1 and CPU 2 only. The new explicit
`device:clock-native-cpus` task selects `--libc-syscall-cpus`, rotating through
CPU 0, 1, 2 and 3 at batch boundaries. Its distinct operation identity is
`native-clock-libc-syscall-cpus`. The existing two-route and three-route tasks
remain unpinned; neither automatically becomes this experiment.

There are 300 batches of 50 sequences, with a 100 ms pause after each batch.
Each sequence reads MONOTONIC, RAW and BOOTTIME, alternating the linked libc
time64 API and explicit ARM syscall403 three times per clock. The fixed bound
is 15,000 sequences / 270,000 readings: 75 batches, 3,750 sequences and 67,500
readings on each core. Every integer timestamp is retained, including any
negative ordering result. No read is retried or clamped and no output is
written inside the sampling loop.

Only the diagnostic's own thread changes affinity. Linux treats affinity as
a per-thread property, and PID 0 selects the caller. Because the effective
mask can be narrowed by CPU availability or cpuset restrictions, the recorder
checks the mask returned by `sched_getaffinity()` after setting it.
[Linux sched_setaffinity manual](https://man7.org/linux/man-pages/man2/sched_setaffinity.2.html).

The recorder requires the original mask to be 15, already allowing CPUs 0–3.
It then verifies a single-bit mask at both ends of every batch and the requested
CPU before and after every clock's six readings. Unexpected masks, CPU IDs,
failed reads or interrupted pauses stop the capture. After success or a
returned failure, it attempts to restore the original mask and verifies the
readback. A restoration error makes the result incomplete. A killed process
cannot leave this affinity change attached to another process or service.

The raw header saves all 300 affinity receipts and the fixed schedule. Each
sample saves its requested CPU and actual endpoint observations. The footer
saves the restore result and final metadata. Offline analysis requires the
complete schedule and exact JSON types, all mask checks, CPU agreement and
successful restoration; totals alone cannot qualify coverage.

All original ABI, binary/import, installed-libc, same-boot and vDSO-export gates
remain. Both clock exports must be absent from the verified loaded vDSO;
the mode does not force an unavailable entry. The host retains its PM lock,
before/after protected-kernel inspection and separate USB/Wi-Fi checks. This
experiment neither sleeps, reboots, blanks the screen, changes charger or
clocksource settings, restarts services nor changes other tasks' affinity.

## Interpretation limits

Ordering checks cover adjacent routes, successive reads within each route,
same-route sequence boundaries and the cross-route kernel → libc boundary
between sequences. For CPU mode, the latter is also grouped by previous and
current CPU, without resetting the saved timestamp at migration.

The fixed schedule exercises cyclic transitions 0→1, 1→2, 2→3 and 3→0. It does
not cover every directed core pair. Each handoff includes the 100 ms pause and
affinity-change overhead; a small counter offset could be hidden inside that
elapsed time. Adjacent timestamp gaps likewise include execution spacing and
are not isolated syscall-latency measurements.

Affinity readbacks and matching endpoints provide deliberate per-core coverage,
but there is no per-read CPU trace. Pinning also changes the scheduling
conditions from the original unpinned failure. A clean short capture cannot
exclude a migration-only, rare or Python-specific manifestation, establish
counter accuracy or qualify suspend. The original battery-guard MONOTONIC
failure and report 260's −750 ns RAW discrepancy remain separate evidence.

## Repeatable commands

```sh
task check:clock-native
task device:clock-native-cpus BUILD=20261010T003416.492637Z RUNTIME_CAPTURE=20261009T230039.014366Z INSPECTION_REVISION=be6c719c1b8e1637b69fa3e94a96b370adfb84d2
task report:clock-native CAPTURE=20261010T003534.539457Z
```

Future runs use the newly printed build/capture timestamps. The explicit
ancestor revision selects only the original inspection producer matching the
protected checkpoint; it does not relax normal PM admission or replace the
installed guard. Raw captures and copied binaries remain private under ignored
`.local/diagnostics/`.

## Observed result

| Clock | Readings | Negative ordering checks | Minimum libc → kernel gap | Minimum kernel → libc gap |
| --- | ---: | ---: | ---: | ---: |
| MONOTONIC | 90,000 | 0 | 1,167 ns | 1,167 ns |
| RAW | 90,000 | 0 | 1,166 ns | 1,166 ns |
| BOOTTIME | 90,000 | 0 | 1,249 ns | 1,208 ns |

For each clock, all four CPUs have exactly 3,750 starting and matching ending
observations. All 300 batch masks equal the expected single bit, with zero
affinity-call errors. Original/final affinity is 15 and restore status is zero.

Each clock has 3,675 same-core sequence boundaries per CPU, 75 boundaries each
for 0→1, 1→2 and 2→3, and 74 for 3→0. All 14,999 boundaries are nonnegative.
Observed cross-core gaps are approximately 100.49–109.53 ms, dominated by the
deliberate pauses. This is not a tight inter-core counter-offset measurement.
The remaining checks match report 264: 45,000 libc → kernel and 30,000 kernel →
libc adjacent pairs per clock, 30,000 within-route gaps per route, and 14,999
same-route sequence gaps per route. These counts overlap readings and are not
independent statistical trials.

The device remains on boot `2170b296-d964-4d16-bdb1-c135b0e7b812`, kernel
`6.18.54-gameshellneo24`, clocksource `arch_sys_counter`, PM success/failure
**53/0**, and battery-service **NRestarts=1**. All inspected services remain
active, the backlight remains powered at brightness 1, and both network routes
pass. No new kernel fault is detected. The protected 1,660-record anchor remains
`150774f032096ebf16652e5f751db9d5162679f7fbb8c8e675387ca5fff252cb`;
the full 1,661-record checkpoint remains
`c3160b6df3e8a1c42cb85b62af1ae63a7b31d56ae4d21eef09b7e2ebef22a6d1`.
No installed image component was replaced. The completed temporary diagnostic
was removed from its owned remote staging directory.

## Evidence and validation

| Evidence | Private location |
| --- | --- |
| Native/ARM build, fixtures and manifest | `.local/diagnostics/20261010T003416.492637Z/` |
| Live capture, state and analysis | `.local/diagnostics/20261010T003534.539457Z/` |
| Independent offline replay | `.local/diagnostics/20261010T003648.084431Z/` |
| Build and full-check logs | `.local/neo192-cpus-build.log`, `.local/neo192-cpus-check.log` |
| Device and replay logs | `.local/neo192-cpus-device.log`, `.local/neo192-cpus-replay.log` |

The ARM binary SHA-256 is
`7dc1c93affc44b66c62a039294f07edecc8f060ed1be9c833f101086019d4512`.
The complete raw NDJSON is 6,681,123 bytes, SHA-256
`bb1b81da98b9719118cc890aa69ecff8cbc8f21b557ee10c6014ff5fdc6c5f23`.
The replay verifies this hash and writes a fresh report; all original analysis
fields match the replay, with the original raw data and analysis preserved.

Native and ARM/QEMU fixtures cover all three fixed plans, all four CPU targets,
set/readback failures and wrong masks at every batch boundary, failed
restoration, an unexpected CPU, failed clock reads, interrupted pauses,
overflow and decreasing raw timestamps. Restoration is exercised on both
successful and returned-failure paths. Unpinned plans make no affinity callback
calls. The ARM production build and time64 ABI assertions pass.

The 23 focused Python cases cover complete synthetic recordings, every
comparison boundary, all-core counts, an injected cross-core regression,
incomplete/mismatched masks and CPU observations, restoration failure, boolean
type confusion, mode relabeling, one bounded failed execution with retained
evidence/postflight, and hash-verified offline replay. Full repository checks
pass **24 runtime tests / 958 tooling tests**, one optional skip, existing C
checks, Bash syntax and ShellCheck.

NEO-192 remains in progress. This short clean result does not explain the
original guard failure or the earlier RAW discrepancy, identify a defective
core, or establish an efficiency improvement. Next inspect the pinned physical
counter read and kernel timekeeping paths against the saved evidence before
choosing another measurement. Keep NEO-191/NEO-182 PM work pending; do not clear
the fault, reset restart history or deploy a retry/clamping workaround.
