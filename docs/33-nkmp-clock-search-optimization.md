# NKMP clock-search optimization

Date: **2026-09-27 UTC** (27–28 September in New Zealand).
Ticket: **NEO-12**, completed. Target: CPI v3.1.

## Purpose and current status

The diagnostic.2 measurements identified substantial CPU time spent deciding
how to change CPU frequency. Its governor worker used about 35.5% of one CPU
in quiet conditions. Temporarily increasing the update interval halved that
worker's CPU time; estimated battery power fell only 2–3%. A separate kernel
instruction sample located 43.42% directly in NKMP search/calculation, with
another 30.36% in integer division whose callers were not captured.
[Report 32](32-governor-rate-comparison.md) contains the captures and caveats.

The first implementation reduces work inside each clock search. It retains
the original update interval, CPU operating points, voltages and register
programming. Native and ARM32 equivalence checks passed. A separately versioned
`0.1.0-diagnostic.3` image with `6.18.54-gameshellneo3` has built and passed
offline verification.
It has been flashed to the Samsung DEV card with a matching full-image
readback. The owner observed the login screen; USB/Wi-Fi and live integration
checks passed on the new kernel. Storage and five-minute CPU/memory load/recovery
checks also passed. At the unchanged governor setting, recorded worker CPU
time fell about **92.3%**, from 35.5% to 2.7% of one CPU. Separate function
samples support the reduced search cost. Estimated battery power was 2.66%
lower, with charge-state and measurement limitations detailed below. The
original 366 µs setting is restored and postchecks passed.

## Change and reasoning

The upstream function tries combinations of multipliers N/K and dividers M/P,
calculates each output, rejects outputs above the request, and retains a new
combination only when it is strictly closer to the request. On this A33 CPU
PLL the permitted ranges produce **1,536 candidate evaluations per search**:
32 N values × 4 K values × 4 M values × 3 P values (1, 2, 4).

[Patch 0005](../kernel/patches/0005-sunxi-nkmp-exact-match.patch) exits after
saving the first exact match. Once the difference is zero, no later candidate
can strictly improve it. The existing strict comparison already retains the
first equally good result, so the selected N/K/M/P tuple remains the same.
The exit is inside the improvement branch: a zero request retains the original
zero-result behavior instead of assigning a previously unselected tuple.

Loop ordering, arithmetic, limits, non-exact rounding, fallback behavior and
the output-assignment path are preserved. The patch does not alter PLL lock
waiting, clock reparenting, register writes, voltage sequencing or notifiers.
The calculation has no production side effects to preserve after a match.
This argument also holds when the calculation's unsigned return value is
truncated on ARM32: the original comparison is unchanged.

## Repeatable validation

Run `task test:nkmp`. It is also the first test stage in `task build`.
[The helper](../tools/check-nkmp.py) verifies the locked Linux archive SHA-256,
reads only the relevant archive members, applies the real patch to an isolated
copy, and extracts the actual original and patched calculation/search functions.
The existing kernel scratch tree is not modified by the test.

The C harness compares the returned rate and **all four factors**, and counts
candidate evaluations. The board initializer is checked against the tested
factor bounds, and CPU operating points are extracted from `sun8i-a33.dtsi`.
For each tested constraint/parent combination, requests cover every distinct
output breakpoint, neighboring integers, a representative point in each gap,
zero, one and the platform's maximum unsigned long. Four constraint shapes and
six parents exercise the actual A33 range, larger divider ranges, non-unit
minimum factors, fixed factors, zero/tiny parents, non-round parents and
32-bit truncation. Synthetic shapes do not establish another board's support.

The functions use a userspace shim for `do_div`'s quotient and 32-bit divisor.
The calculation ignores the macro's remainder. This checks arithmetic and
selection, not the kernel division assembly, timing or hardware behavior.
Instrumentation adds only an evaluation counter to each calculation function.

| Execution | Compiler | Cases | Searches shortened | Result |
| --- | --- | ---: | ---: | --- |
| Native x86-64, 64-bit unsigned long | Host GCC 15.2.0 | 12,628 | 3,421 | Identical rate and factor selections |
| ARM32 under QEMU, 32-bit unsigned long | Pinned builder GCC 14.2.0 | 12,302 | 4,068 | Identical rate and factor selections |

Different counts arise from distinct output breakpoints after 32-bit
truncation. These are broad boundary tests plus a source-level equivalence
argument, not an exhaustive enumeration of every possible driver input.

All A33 CPU operating points are exact matches with a 24 MHz parent:

| CPU MHz | Original evaluations | Patched evaluations | Selected N/K/M/P |
| ---: | ---: | ---: | --- |
| 120 | 1,536 | 49 | 5 / 1 / 1 / 1 |
| 240 | 1,536 | 109 | 10 / 1 / 1 / 1 |
| 312 | 1,536 | 145 | 13 / 1 / 1 / 1 |
| 408 | 1,536 | 193 | 17 / 1 / 1 / 1 |
| 480 | 1,536 | 229 | 20 / 1 / 1 / 1 |
| 504 | 1,536 | 241 | 21 / 1 / 1 / 1 |
| 600 | 1,536 | 289 | 25 / 1 / 1 / 1 |
| 648 | 1,536 | 313 | 27 / 1 / 1 / 1 |
| 720 | 1,536 | 349 | 30 / 1 / 1 / 1 |
| 816 | 1,536 | 577 | 17 / 2 / 1 / 1 |
| 912 | 1,536 | 601 | 19 / 2 / 1 / 1 |
| 1,008 | 1,536 | 625 | 21 / 2 / 1 / 1 |

This removes **59.3–96.8% of candidate evaluations** at those requests. It is
not a measured wall-time speedup, overall CPU reduction or battery saving.
Non-exact requests still perform the complete search.

Private evidence: `.local/build/nkmp-tests/{native.txt,arm32.txt,evidence.json}`
and `.local/build/nkmp.log`. Input identities:

- Linux archive: `9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
- Patch 0005: `bfb241ae1a3195c64397fef79212949719071b56924c099f6f47a677d06e5835`.
- C harness: `8c0c3c5897d06598596c3298032367717c079e7f2af6e3220200a0e9d93a1cd4`.
- Generated function header: `28378fac42868451c7cf98cd3961a678cc9edd7ea76224e6eda4cd3fcc8d3a37`.

`task check` also passed: 13 runtime tests, 41 tool tests, compiled current-limit
regressions and shell lint. One optional user-systemd test was skipped in this
run; its earlier explicit execution is recorded in report 32.

## Candidate build and hardware qualification

The source lock advances only the diagnostic image/kernel suffixes. Linux,
the builder, Debian snapshots, board configuration and existing patches remain
at their recorded inputs. `task kernel:reset` preserved the previous kernel
source, build, installation and manifest in
`.local/previous-kernels/20260927T101401Z-574906/` before a fresh patched build.
The old artifact metadata was separately preserved there as
`artifact-metadata.tar`. Earlier image files remain available.

The fresh kernel build completed successfully, recording 15 kernel/module
artifacts for `6.18.54-gameshellneo3`. The resolved configuration is byte-for-byte
identical to diagnostic.2 (SHA-256
`088d97999930260b6d8dd163df46a50487d48648a3a16841245d62434787de2e`), and all
132 configuration assertions passed. The compiled DTB is also identical to
diagnostic.2 (SHA-256
`8280b127316f641aab60a1d341832adfc4fbc7cec3ae65a559bbd33224b40cd4`).

`task check:kernel` verified all 15 recorded artifacts; `task check:dt` produced
no binding/schema/DTB diagnostics. The final `task test:nkmp` rerun passed the
same native and ARM32 cases after the helper's failure logging and provenance
were improved. `task build:image` completed and its offline verifier passed:
MBR boundaries, bootloader readback, FAT16/ext4 checks, U-Boot CRCs/addresses,
kernel/DTB/module/radio hashes, private identity permissions and service policy.

| Artifact | Value |
| --- | --- |
| Filename | `GameShellNeo-0.1.0-diagnostic.3-cpi31-64f092d5770e.img` |
| Raw bytes | 4,294,967,296 |
| SHA-256 | `64f092d5770ef344cb2e9d22b16780aebe94a5501732130f6b22c21910554523` |
| Kernel release | `6.18.54-gameshellneo3` |
| Hardware qualification | NEO-12 checks passed; overall NEO-5 qualification remains open |

The raw image and evidence remain private in `.local/artifacts/`. The old
diagnostic.2 image was hashed again after assembly and still matches
`d3458c373a4281f12e424b8e3448da2f55c21309d34f2fa70b4a90b4b5eb21d8`.
The build reported non-target binfmt registration failures for AArch64,
RISC-V and LoongArch; the explicitly registered ARM handler and `arch-test
armhf` succeeded, and the target's installation and verification completed.

`task mac:stage` compressed and transferred the candidate to the Mac. Both the
compressed checksum and complete decompressed image checksum passed there.
The gzip transfer contains 264,318,562 bytes, SHA-256
`524531a99acdf24e08b8fe9f5284369ec7da0db01e49a1c0a6efd23c0cb30696`.
The owner confirmed shutdown and moved the Samsung DEV card to the Mac.
Fresh inspection identified the external physical USB card as `disk16`,
64,013,467,648 bytes, 512-byte sectors, media `Micro SD/M2`, existing FAT volume
`armbi_boot`, UUID `756E795A-FA10-319A-8161-7149A8C7F640`.

`task mac:preflight` passed before `task mac:flash DISK=disk16`. The flash wrote
all 4,294,967,296 bytes, read back the same complete range and matched the raw
image SHA-256 above. The card was ejected successfully. Private flash log and
result: `.local/diagnostics/20260927T105524.449111Z/`.
The owner reinserted the card, reconnected USB and reported the login screen.
The original card and recovery backup remain available.

### First boot

USB SSH confirmed `6.18.54-gameshellneo3` and image `0.1.0-diagnostic.3`.
Boot ID: `6c2112b6-84d5-479c-a29b-a067df545be3`. Direct Wi-Fi SSH also passed.
All six checked services were active with zero restarts; there were no failed
units or kernel taint. The live integration task passed image identity,
regulatory-database selection, single Wi-Fi-daemon ownership, journal ACLs,
loopback BPF control/deny/allow-exception behavior and the agreed country state
(configured NZ, access point's accepted AU global announcement).

The installed battery guard retained SHA-256
`834c5b6c1b834b22752ec21ed7088fc8e1eea10f35cd164edaaac45fea42a6f0`;
all nine isolated on-device battery-test methods passed without changing the
live guard or requesting a real shutdown. Initial telemetry was 72% Charging,
**4.1712 V** at 10:59:12 UTC and 4.1833 V at 10:59:48.
Charger/gauge programming is unchanged.

The ready marker was 16.859 seconds after the kernel started. Systemd reported
2.520 seconds kernel + 19.497 seconds userspace, with graphical.target after
14.472 seconds of userspace. These first-boot observations do not measure total
power-button-to-ready time or establish a startup improvement/regression.

Private first-boot evidence:

- `.local/diagnostics/20260927T105906.948531Z/status.txt`: USB status.
- `.local/diagnostics/20260927T105936.714373Z/`: integration checks.
- `.local/diagnostics/20260927T105948.426612Z/status.txt`: direct Wi-Fi status.
- `.local/diagnostics/20260927T105951.053321Z/`: installed battery-guard tests.
- `.local/diagnostics/20260927T110027.708373Z/stability.jsonl`: successful load/recovery test.

### Load and recovery

`task device:stability ROUTE=usb` ran from 11:00:33 to 11:06:09 UTC. Its 128 MiB
temporary storage file passed SHA-256 verification using a direct read. Four
CPU workers and one 256 MiB memory worker then ran for five minutes with
verification enabled: all five passed, none failed, and the tool reported no
untrustworthy metrics. Every sampled load frequency was 1,008 MHz; peak sampled
temperature was 65.772 °C. The three subsequent recovery samples were 240 MHz,
with temperature falling to 55.890 °C. Kernel taint remained zero and boot
identity was unchanged. Temporary files were removed.

This is a load/recovery check, not exhaustive electrical/OPP qualification.
After the owner disconnected USB, the board cooled to 42.768 °C before the
battery-only comparison started. No further stress workload ran during it.

While the host compiled the kernel, the owner reconnected USB to recharge.
The 10:21:36 UTC status check reached diagnostic.2 through the Mac's USB link:
all six checked services were healthy with zero restarts, no failed units,
valid battery monitoring, 19% Charging and a reported 3.9248 V. This confirms
access and current software status, not charging qualification. No comparative
power measurement ran during charging. Private capture:
`.local/diagnostics/20260927T102131.296892Z/status.txt`.

### Battery-only governor comparison

The same command as diagnostic.2 ran from approximately 11:13 to 11:21 UTC:
`task device:governor-compare ROUTE=wifi SECONDS=120 RATE_US=10000`.
Each phase had thirty seconds to settle, followed by thirteen battery samples
over 120 seconds. The owner confirmed USB disconnected, controls untouched and
the device resting in the same location. No concurrent SSH diagnostics or
function sampling ran in these windows.

The boot ID remained unchanged throughout, as did worker PID 67/start tick 135,
four online CPUs, schedutil, the 120–1,008 MHz policy, brightness 1, backlight
power state 0 and Wi-Fi power saving off. Both external-power inputs remained
offline; the battery guard was valid and kernel taint zero. The task passed and
verified restoration of **366 µs**, including its independent stop hook.

| Diagnostic.3 measurement | Original before, 366 µs | Slower, 10,000 µs | Original after, 366 µs |
| --- | ---: | ---: | ---: |
| Counter window, seconds | 120.383 | 120.351 | 120.418 |
| Governor-worker CPU seconds | 3.40 | 3.45 | 3.17 |
| Governor-worker % of one CPU | 2.824 | 2.867 | 2.632 |
| Estimated battery power, W | 1.00733 | 1.02237 | 1.01278 |
| Estimated battery current, mA | 261.17 | 265.96 | 264.08 |
| Timer IRQs/second | 108.64 | 121.22 | 104.59 |
| RSB IRQs/second | 23.98 | 23.28 | 23.56 |
| IRQ-work IPIs/second | 15.19 | 15.77 | 14.23 |
| Context switches/second | 231.27 | 305.32 | 219.76 |
| Wi-Fi MMC IRQs/second | 27.18 | 43.46 | 26.26 |
| Peak sampled temperature, °C | 40.986 | 39.528 | 39.042 |
| Battery voltage range, V | 3.8522–3.8621 | 3.8390–3.8500 | 3.8280–3.8390 |
| Reported charge, start → end | 80% → 78% | 78% → 77% | 76% → 75% |
| Endpoint Wi-Fi signal, dBm | −80 → −78 | −85 → −79 | −80 → −82 |

At the unchanged 366 µs setting, diagnostic.2 recorded **35.474% and 35.581%**
of one CPU in the governor worker. Diagnostic.3 recorded **2.824% and 2.632%**.
Comparing the two pairs' means gives a **92.32% reduction in recorded worker
CPU time** (35.528% → 2.728%). Context-switch rates fell from an average
495.85/s to 225.51/s, and timer IRQ rates roughly halved. These are observed
whole-system rates in the test, not a direct count of PLL transitions or an
isolated per-call benchmark. The equivalence tests, unchanged configuration,
specific code change and live observations together support retaining the fix.

The two unchanged-policy power windows averaged **1.01005 W**, versus
**1.03761 W** previously: a **27.55 mW / 2.66% lower software estimate**.
This is a useful direction to track, not a calibrated saving or endurance
prediction. The images ran in different boots after charging: the earlier
windows reported 42% and 3.706–3.764 V; these reported 75–80% and 3.828–3.862 V.
Temperature was still settling and radio signal varied. These conditions and
the uncalibrated current sensor prevent attributing the exact difference to
this patch. Current alone is also insufficient because voltage changed.

Slowing governor updates on diagnostic.3 gave no CPU or power advantage in this
run. Its radio interrupt rate was higher and signal briefly weaker, so it does
not isolate the effect of the interval. Keep **366 µs** as the normal policy;
the earlier large slowdown benefit has not persisted after the search fix.

The CPU-accounting issue is smaller but remains unresolved. Aggregate
`/proc/stat` coverage was 98.68–98.88%; CPU0 covered 95.94–96.64% of elapsed
time, while other CPUs were near 99.5–99.7%. Aggregate busy time was only
0.81–0.83% of four CPUs, inconsistent with the summed process observations.
Do not describe these as exact overall utilization or claim the accounting
bug is fixed. Process-counter and instruction-sampling evidence have their
own limits, recorded here and in report 32.

Private raw capture:
`.local/diagnostics/20260927T111327.916104Z/governor-comparison.jsonl`.
The six old/new phase summaries used for the comparisons above are retained in
`.local/diagnostics/neo12-comparison/diagnostic3-comparison-summary.json`.

### Separate function profile and final checks

`task device:governor-profile ROUTE=wifi SECONDS=30` then sampled the same
worker using the same perf 6.18.54 binary, kernel-only `cpu-clock:k` event,
requested 99 Hz rate, 64-page buffer and no callchains. The original 366 µs
setting remained unchanged. The profile passed, retained worker identity and
reported **155 samples, zero lost**, with resolved kernel symbols.

| Symbol | Diagnostic.2 samples / share | Diagnostic.3 samples / share |
| --- | ---: | ---: |
| `ccu_nkmp_find_best.constprop.0` | 315 / 29.61% | 18 / 11.61% |
| `ccu_nkmp_calc_rate` | 147 / 13.82% | 8 / 5.16% |
| `__udivsi3` | 323 / 30.36% | 21 / 13.55% |
| `finish_task_switch` | 164 / 15.41% | 49 / 31.61% |
| `_raw_spin_unlock_irqrestore` | 26 / 2.44% | 16 / 10.32% |
| All symbols | 1,064 / 100% | 155 / 100% |

Direct search/calculation samples fell from **462 to 26**, and their share
from 43.42% to 16.77%. This supports the attribution made before the patch.
A larger percentage in scheduling does not imply more scheduling work: its
sample count also fell. The remaining search/division samples show room for
further investigation, but 155 samples are too few to rank small differences
precisely. Division callers were not captured, and software timer sampling can
miss execution with interrupts disabled. The two-second health checks and perf
itself add work; these samples are separate from the power windows and do not
measure exact function time or energy.

Private evidence: `.local/diagnostics/20260927T112137.586275Z/`, containing
`governor-profile.jsonl`, `perf.data`, record/report text and the boot's symbol
map. The optional missing `tips.txt` notice did not affect capture/reporting.

Final Wi-Fi status at 11:23 UTC confirmed all six checked services active with
zero restarts, no failed units, valid battery monitoring, 74% Discharging,
3.7928 V and no kernel taint. Root-read kernel logs had no new entries since
the load test ended. A final readback confirmed 366 µs; the restoration record
was absent and both transient comparison/profile units were inactive and
unloaded. Captured status: `.local/diagnostics/20260927T112311.086017Z/status.txt`.
All temporary test workloads have finished.

Retain patch 0005 and close NEO-12's bounded optimization work. Precise energy
savings, endurance, CPU accounting, exhaustive board qualification and charger
limits remain separate follow-ups. No permanent governor policy, OPP, voltage,
charger or battery-gauge change was introduced.

## Opportunities for deeper refactoring

The owner asked whether a larger refactor could produce better performance.
The owner also confirmed that small cumulative optimizations are worthwhile;
there is no minimum percentage saving required. Track CPU work, wakeups,
memory, responsiveness and power separately, retaining small correct gains
while using repeat measurements to distinguish small power changes from noise.
There are credible opportunities, with separate evidence requirements:

| Area | Possible change | Why it may help | What must be preserved or measured |
| --- | --- | --- | --- |
| NKMP search | Derive candidate N mathematically for each remaining factor combination | Avoid scanning every N; could also help non-exact requests | Integer rounding, all limits, first-tie ordering, overflow/truncation behavior and supported users of the generic driver |
| Frequency policy | Revisit transition latency and request pacing after the search fix | Reduce repeated clock/regulator work | Load response and recovery; the earlier slower setting was an experiment, not a selected permanent policy |
| AXP USB status polling | Evaluate event-driven updates with a bounded fallback | The current offline polling wakes periodically even without a cable | Attach/detach detection, charger/status correctness and recovery from missed events |
| Wi-Fi power management | Qualify firmware power saving and recovery | Radio idle power may matter more than radio-thread CPU time | Reachability, latency, reconnects and measured battery power at comparable signal strength |
| Display/peripheral lifecycle | Follow through on full power-state transitions | Backlight-off alone does not turn off every display supply or engine | Panel reinitialization, shared rails, clock ownership and reliable restoration |
| Board-specific kernel and startup | Audit unused built-ins/modules and the measured boot dependency chain | Reduce image/memory footprint, unnecessary probes and readiness delays | CPI v3.1 drivers, recovery/access paths and an explicitly measured readiness milestone |

The local awake battery service samples every ten seconds; the USB-power
driver's offline delayed-work interval is 50 ms. This identifies a much more
frequent source of work to investigate, but does not measure either component's
energy cost. Rewriting the battery service in another language has no measured
priority over reducing the kernel's unnecessary work.

For the arithmetic refactor, selecting the largest permissible N is not enough:
integer rounding can make multiple values equally good, and the old traversal
chooses the first tuple in K/N/M/P order. Reordering the loops requires explicit
tie handling. Wide intermediate arithmetic must also respect existing ARM32
return-value truncation, or use a verified fallback where a faster formula's
preconditions do not hold. The harness provides an independent reference for
this work, but will need added cases for any new formula's arithmetic edges.

For positive arithmetic without overflow or return-value truncation, let
`A = parent × K` and `D = M × P`. The output is `floor(A × N / D)`. The greatest
N whose output does not exceed a request R can be derived from
`N < (R + 1) × D / A`, then clamped to the permitted range. After calculating
that output, derive the smallest N yielding the same output to preserve ties.
Comparing candidate tuples in the original K/N/M/P order preserves selection
across the remaining combinations. On A33 this replaces the 32-value N loop
with calculations for at most 48 K/M/P combinations. Those calculations are
more expensive than a simple loop increment; only a benchmark can establish
the net improvement over the exact-match exit. Zero parents, infeasible ranges
and arithmetic overflow require explicit handling before this is usable code.

An OPP-specific lookup table would reduce work for today's board settings but
would bake those settings into a generic driver. The preferred next candidate
is a general calculation with validated limits. It should earn its additional
complexity through measured improvement over this small patch on the board.
Whole-system standby improvements still depend on the separate DRAM/firmware
work; a faster awake clock search cannot deliver week-long sleep by itself.
