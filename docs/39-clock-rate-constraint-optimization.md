# Fixed-parent clock rate-constraint optimization

Date: **2026-09-28 NZDT**. Ticket: **NEO-18**.

Patch 0007 reads the effective clock rate limits once per fixed-parent NM or
NKM factor search. Previously, the search reconstructed the same limits for
every eligible factor combination. Actual-source comparisons passed on native
Linux and emulated ARM32, and the affected kernel objects compiled for ARM.
The patch is prepared for a future image; it is not installed on the GameShell.

## Change and scope

`ccu_is_better_rate()` obtains the effective minimum and maximum through
`clk_hw_get_rate_range()`. The clock core combines provider and consumer limits
by walking the consumer list twice. The fixed-parent NM and NKM loops previously
called that comparator for every candidate, repeating those walks.
[Original comparator](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_common.c#L42),
[boundary getter](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L781).

[Patch 0007](../kernel/patches/0007-sunxi-clock-rate-range.patch) moves the existing
comparison body into an inline helper accepting explicit limits. Each fixed
search obtains its limits once and passes them to that helper. The exported
comparator remains available and still obtains fresh limits on every call for
other callers. NKM's parent-adjusting search is byte-for-byte unchanged.

The patch preserves factor iteration order, strict comparison and tie behavior,
range rejection, integer rounding, native-width overflow, and selected factors.
It adds no early exit and changes no register programming, operating points,
voltage, CPU governor policy, fractional/SDM handling or post-divider treatment.
The previous NKMP CPU-clock optimization remains a separate patch.
[NM source](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_nm.c),
[NKM source](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_nkm.c).

## Why the snapshot is valid here

The clock core's normal rate determination and rate setting execute under its
prepare lock. Consumer range changes and consumer-list changes use that same
lock; the boundary getter asserts it is held. The two modified searches contain
arithmetic, validity checks and comparisons, with no nested clock-provider
callbacks that could alter constraints. A local snapshot therefore represents
the same limits throughout each search.
[Rate determination](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L1560),
[rate setting and consumer ranges](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L2584).

This is not a persistent cache: the next invocation reads the limits again.
The provider-side `clk_hw_set_rate_range()` itself is a direct assignment; the
locked sunxi driver uses it during clock registration. The claim is about the
reviewed call paths, not arbitrary concurrent provider mutation. Parent-adjusting
NKM has nested callbacks and a different tie rule, so it keeps the original
comparator path.
[Provider setter](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/clk.c#L833),
[sunxi registration](https://github.com/gregkh/linux/blob/v6.18.54/drivers/clk/sunxi-ng/ccu_common.c#L158).

## Reproducible checks

```sh
task test:clock-ranges
task check:clock-drivers
```

[The workflow](../tools/check-clock-ranges.py) verifies the locked Linux archive
hash, extracts the actual original functions and applies patch 0007 to a private
copy. It rejects changes outside the tested functions and added header helper
in those inputs. A33 factor definitions are checked against the locked source.
The generated harness includes both implementations, the actual clock-core
boundary getter, and the kernel's actual `abs` macros.

[The C tests](../kernel/tests/clock_range_test.c) compare returned rates and every
selected N/M or N/K/M factor. Coverage includes:

- Every distinct output of the A33 video-shaped NM and DDR0-shaped fixed NKM
  searches at 24 MHz, neighboring requests and gaps, in floor and closest modes.
- Audio-shaped NM and MIPI-shaped NKM limits, smaller and empty ranges,
  exact/restricted/reversed constraints, and constraints changing between calls.
- Core and consumer constraints, NKM ratio restrictions, zero and extreme parent
  rates, and signed/unsigned word-width boundaries.
- Direct comparator cases including differences at the signed-minimum boundary.
  Compilation uses the kernel's `-fno-strict-overflow` convention; tests retain
  inherited arithmetic rather than replacing it with an idealized distance.

| Comparison cases | Native, 64-bit `unsigned long` | Emulated ARM32 |
| --- | ---: | ---: |
| NM rate and factors | 13,153 passed | 13,153 passed |
| Fixed NKM rate and factors | 3,677 passed | 3,677 passed |
| Comparator results | 2,744 passed | 2,744 passed |
| Total | **19,574 passed** | **19,574 passed** |

The test instruments the actual range getter. For representative unrestricted
searches at a 24 MHz parent and 432 MHz request:

| Search shape | Original range queries | Patched queries |
| --- | ---: | ---: |
| A33 video NM: 128 × 16 | 2,048 | 1 |
| A33 DDR0 NKM: 32 × 4 × 4 | 512 | 1 |

NKM candidates rejected by its ratio checks did not query limits previously.
An empty or wholly rejected search consequently changes from zero lookups to
one; the suite covers this without claiming a reduction for every input.

These checks use modeled clock objects, consumer-list iteration and the
`do_div` quotient. They do not execute the kernel's lock implementation, prove
all possible inputs, reproduce physical PLL behavior, or measure board time.

## Integration and evidence

The isolated ARM build applied the complete project patch queue and compiled
`ccu_common.o`, `ccu_nm.o`, `ccu_nkm.o` and the existing wrapper consumer
`ccu_mux.o`. All 132 configuration assertions passed. The objects are ELF32
ARM EABI5. Kernel `checkpatch.pl` reported zero errors and zero warnings for
patch 0007.

Archive verification and isolated object compilation are now shared by the
clock and USB checks through [kernel_checks.py](../tools/kernel_checks.py).
Each workflow retains its own scratch tree, evidence and lock. Normal
`task build` includes the clock equivalence check; `task check` remains usable
without the archive or Docker.

The USB workflow was rerun after extracting that shared helper: the original
forty-case model still produced eight lifetime violations, the patched model
produced zero, and the complete ARM driver rebuilt with the same object hash
recorded in report 38. `task check` passed 13 runtime tests, 58 tool tests (one
optional user-systemd case skipped), the current-limit regression and shell
lint. Its log is `.local/build/neo18-check.log`.

Private evidence is under `.local/build/clock-range-tests/`:

- `compile-evidence.json`: archive, patch, harness, generated header, workflow,
  shared helper, config and object hashes, plus pinned builder identity.
- `native.txt` and `arm32.txt`: compiler identities and comparison results.
- `kernel-b7eb9af33723931c/`: full isolated source, output and ELF headers.
- The task log is `.local/build/clock-drivers.log`.

Patch SHA-256:
`d605192dd1b672e57305437f92b3ae1d391edd9061010e2770fe0a932cbfa1c1`.
Resolved config SHA-256:
`088d97999930260b6d8dd163df46a50487d48648a3a16841245d62434787de2e`.

## Expected benefit and remaining work

The proven reduction is repeated constraint processing during these searches.
The current image's CPU DVFS uses NKMP, and no continuous NM/NKM idle workload
has been established. Fractional and audio SDM paths can bypass these searches.
Do not translate the lookup counts into a percentage of total CPU, boot-time
or battery improvement. This optimization can benefit relevant clock setup or
mode changes; its board-level magnitude remains unmeasured.

Use the normal kernel-reset/build workflow for the next image and retain
diagnostic.3 for recovery. Then verify boot/display behavior, blanking and
restoration, peripheral access and any affected clock transitions. Measure
actual latency separately if attribution is needed. No GameShell/Mac access,
flashing, charger changes or physical interaction was part of this work.
