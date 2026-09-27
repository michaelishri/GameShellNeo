# NKMP clock-search optimization

Date: **2026-09-27**. Ticket: **NEO-12**, in progress. Target: CPI v3.1.

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
It has not yet been flashed or qualified on the owner's board.

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
| Hardware qualification | Pending |

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
The owner has been asked to shut down and move the Samsung DEV card to the
Mac; physical flashing and boot qualification are pending.

Physical qualification requires moving the Samsung development card to the
Mac, identifying it afresh, flashing through the shared task, then booting it
in the GameShell. The original card and its recovery backup remain available.

After flashing, check the new release, USB/Wi-Fi access, services, display,
battery policy and kernel health. Exercise CPU load and recovery across the
supported policy before capturing quiet-window worker activity, function
samples and battery power. Retain the original 366 µs governor limit for the
primary comparison. Match brightness, radio state, USB disconnection and
sampling overhead; record signal, temperature and battery state. A different
boot and battery trajectory limit direct before/after power comparisons.

While the host compiled the kernel, the owner reconnected USB to recharge.
The 10:21:36 UTC status check reached diagnostic.2 through the Mac's USB link:
all six checked services were healthy with zero restarts, no failed units,
valid battery monitoring, 19% Charging and a reported 3.9248 V. This confirms
access and current software status, not charging qualification. No comparative
power measurement ran during charging. Private capture:
`.local/diagnostics/20260927T102131.296892Z/status.txt`.

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
