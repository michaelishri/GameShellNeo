# Native libc/syscall clock comparison

10 October 2026. NEO-192. This follows the unavailable vDSO clock exports in
[report 263](263-native-clock-vdso-availability.md).

**One completed native two-route capture retained 270,000 readings with zero
ordering discrepancies.** The fixed run covers MONOTONIC, RAW and BOOTTIME,
comparing libc's time64 API with explicit ARM syscall403. Both network routes,
device state and original fault evidence remain intact. An offline replay
reproduces the complete classification.

This is a short non-reproduction, not a resolved clock fault. The original
battery guard's backwards MONOTONIC bracket and report 260's −750 ns RAW
cross-route discrepancy remain open. No driver fix, clock reliability, PM
qualification, latency improvement or energy saving is claimed.

## Explicit experiment

The existing native diagnostic now has two fixed comparison plans. The new
`--libc-syscall` mode is selected by `device:clock-native-pair`, while the
original three-route command still requires a callable time64 vDSO entry.
There is no automatic fallback between these plans.

Before sampling, the new mode verifies the actual vDSO mapping/loaded handle
and requires both time64 and time32 clock names to be unavailable through
versioned and unversioned lookup. This preserves the observed boot's routing
conditions. It does not call a hidden entry or alter the DT flag. A different
export state stops this experiment before sampling and needs separate analysis.

The new raw header identifies `native-clock-libc-syscall`, routes
`[0,1,0,1,0,1]`, absence of both clock exports and no direct vDSO call. Route 0
is the linked libc time64 API; route 1 is explicit syscall403 using the kernel
time64 structure. The captured imports and runtime hashes preserve the ABI
checks from report 263. Source/libc behavior supports syscall fallback inside
libc on this boot; this measurement does not trace every internal instruction.

For each of the three clocks, one sequence alternates libc → kernel three
times. There are 300 batches of 50 sequences, with a 100 ms pause per batch:
15,000 sequences and 270,000 readings. The process stays unpinned and records
CPU IDs before and after each six-read family. It saves every integer timestamp
without clamping, retrying failed reads or writing measurement output inside
the sampling loop. Runtime remains bounded by the existing device timeout.

The analyzer checks:

- Every adjacent pair within a clock family, in both route directions.
- Successive readings within each route.
- The last and first reading of each route across sequences.
- The final reading of one sequence against the first reading of the next
  sequence for the same clock, including the kernel → libc boundary.

The last check matters because each route could increase individually while
a cross-route boundary still moves backwards. Negative classifications retain
the original values and their context. All raw rows remain available even if
the convenient first-events summary reaches its 32-event cap. The validator
requires the explicitly selected operation, route order, complete bounds and
export state; it cannot silently relabel three-route or inventory output.

## Reproduction and private evidence

```sh
task check:clock-native
task device:clock-native-pair BUILD=20261010T001344.437496Z RUNTIME_CAPTURE=20261009T230039.014366Z INSPECTION_REVISION=be6c719c1b8e1637b69fa3e94a96b370adfb84d2
task report:clock-native CAPTURE=20261010T001521.979733Z
```

Use newly printed timestamps for future builds/captures. The explicit ancestor
revision selects only the protected checkpoint's original inspection producer;
it does not relax normal PM admission or change the installed guard.

| Evidence | Private location |
| --- | --- |
| Native/ARM build, fixtures and manifest | `.local/diagnostics/20261010T001344.437496Z/` |
| Completed live capture, state and analysis | `.local/diagnostics/20261010T001521.979733Z/` |
| Independent offline replay | `.local/diagnostics/20261010T001646.082455Z/` |
| Build / focused / full check logs | `.local/neo192-pair-build.log`, `.local/neo192-pair-unit.log`, `.local/neo192-pair-check.log` |
| Device / replay logs | `.local/neo192-pair-device.log`, `.local/neo192-pair-replay.log` |

The ARM binary SHA-256 is
`a4ec6dd34157d6545bb2e77b1a827b3bb4561b70ce9023830f0f3c448cddc94e`.
The raw NDJSON SHA-256 is
`9fb4606d6ef858644f612724426d6efe07e97852d5171fb0377e1b9a1c54aae9`.
The report task verifies the latter before replay and writes a fresh analysis,
leaving the original untouched. Every original classification/statistic equals
the replayed result.

## Observed results and limits

| Clock | Readings | Negative ordering checks | Minimum libc → kernel gap | Minimum kernel → libc gap |
| --- | ---: | ---: | ---: | ---: |
| MONOTONIC | 90,000 | 0 | 1,166 ns | 1,125 ns |
| RAW | 90,000 | 0 | 1,125 ns | 1,125 ns |
| BOOTTIME | 90,000 | 0 | 1,208 ns | 1,166 ns |

For each clock, the analyzer checked 45,000 libc → kernel and 30,000 kernel →
libc adjacent pairs, 30,000 within-route gaps per route, 14,999 between-sequence
gaps per route and 14,999 cross-route sequence boundaries. All are nonnegative.
These checks overlap readings and are not independent statistical trials.

The gap columns describe differences between consecutive returned timestamps.
They include call spacing and surrounding execution; they are not isolated
syscall latency benchmarks or measurements of counter accuracy. A fixed offset
smaller than the call spacing could remain hidden. Longer gaps also include
scheduling and the deliberate pauses.

Each clock family had 2,250 starting CPU observations on CPU 1 and 12,750 on
CPU 2. No endpoint pair differed. CPUs 0 and 3 were not observed, despite the
unchanged allowed-affinity mask of 15. Matching endpoint CPUs do not rule out
migration away and back or prove each intermediate read's CPU. This is not
all-core qualification, and a short sample cannot clear an intermittent fault.
The native run's lack of a recurrence also does not establish that Python
caused the earlier failure.

The before/after checks retain:

- Boot `2170b296-d964-4d16-bdb1-c135b0e7b812` and kernel `6.18.54-gameshellneo24`.
- PM success/failure **53/0**, battery-service **NRestarts=1**, all inspected
  services active and unchanged settings.
- The 1,660-record protected anchor SHA-256
  `150774f032096ebf16652e5f751db9d5162679f7fbb8c8e675387ca5fff252cb`
  and full checkpoint hash
  `c3160b6df3e8a1c42cb85b62af1ae63a7b31d56ae4d21eef09b7e2ebef22a6d1`.
- Working USB and Wi-Fi routes. No new kernel fault, reboot, sleep, screen
  blanking, affinity/clocksource write, service restart or charger change.

The completed temporary executable was removed from its owned remote staging
directory after capture. Build receipts, raw output and state remain private
on the host. No installed image component was replaced.

## Validation and next step

Both fixed C plans pass native and ARM/QEMU fixtures, including failed reads,
CPU-observation failure, interrupted pause, overflow and preservation of
decreasing raw values. The ARM production build and ABI assertions pass.
Eighteen Python tests cover both complete synthetic plans, cross-route and
route-specific anomalies, sequence boundaries, mode/identity rejection,
explicit command selection, failure preservation and hash-verified offline
replay. Full checks pass **24 runtime tests and 953 tooling tests**, with one
optional skip, both existing C checks, Bash syntax and ShellCheck.

NEO-192 remains in progress. The useful next investigation is to define a
bounded CPU-coverage experiment and inspect the physical-counter/timekeeper
path for a concrete failure hypothesis. The current unpinned capture cannot
qualify all four CPUs or exclude migration-related behavior. Retain both prior
faults and the already-prepared guard evidence handling; do not add retries or
clamping, reset restart history or resume NEO-191/NEO-182 PM work on the strength
of this clean short capture.
