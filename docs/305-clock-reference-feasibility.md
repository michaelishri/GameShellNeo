# MMIO reference feasibility: STOP (NEO-221 / NEO-192)

23 October 2026 NZDT. The bounded offline study does **not** qualify an
instrumented timer-reference experiment. Its source/configuration audit,
conditional arithmetic fixtures and compile-only ARM comparisons complete;
the required two-sided ordering and measurement premises remain unproven.
STOP is the result of this feasibility study, not a fix for the clock fault.
Independent review and publication remain pending.

No kernel interface, instrumentation, profile registration, image, MMIO/device
operation or additional capture is introduced. The original reader/counter,
returned ABI, clock modes, capacities, production queue and locks are unchanged.
NEO-217's single capture and both original source/evidence trees remain intact.
NEO-192 and its dependent PM gates remain open.

## Existing evidence and useful discriminator

The original MONOTONIC guard exception lacks raw values. The separate RAW
−750 ns event lacks consumed counter/writer tuples; neither can be reconstructed
from later reads. At nominal 24 MHz, 750 ns is arithmetically 18 ticks, without
establishing that the old fault involved exactly that counter difference.
NEO-217's complete finite capture supplies coherent tuple/copy/runtime evidence
for its own clean window, not either historical event.

A later reference measurement might distinguish disagreement between the
architectural counter and another observation path. Timer1 is already
initialized as a 32-bit downcounter at nominal 24 MHz, but shares the reference
clock. It is not an independent oscillator or absolute-time calibration.
An observed disagreement cannot independently identify the failing path,
CPU, SoC distribution or silicon cause. A clean probed run, especially one
with extra barriers, cannot establish a fix.

## Pinned source, configuration and emitted baseline

All seven sources match the complete map extracted from the locked Linux
6.18.54 archive, SHA
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`:

| Source | Audited boundary |
| --- | --- |
| `timer-sun4i.c` | Timer1 initialization, CNTVAL1 offset 0x28, registered callback |
| `mmio.c` | Registered downcounter uses `readl_relaxed` |
| `timer-of.c` | Mapping/clock initialization and failure cleanup |
| `sun8i-a23-a33.dtsi` | Selected timer node, mapping and OSC24M input |
| ARM `arch_timer.h` | Original 64-bit physical-counter read |
| ARM `io.h` | Relaxed and ordered accessor spellings |
| ARM `barrier.h` | Actual configuration's I/O barrier expansion |

The retained diagnostic.27 vmlinux SHA is
`66ac1e6c6b20d11019a72a741d0b54f045305bcc9bb63c6e834cb5c61c4f7479`,
build ID `a545d309c5f43e3e047cc124322e75e125aef3f5`. Actual configuration SHA
`7e12dbb20507c838ea3c674e3db21ff25f012742d36cd3286fe0844355b7df02`
matches NEO-217's captured configuration. Relevant selections are SMP,
ARM_DMA_MEM_BUFFERABLE, SUN4I_TIMER, CLKSRC_MMIO and ARM_ARCH_TIMER enabled,
HZ=100 and voluntary preemption. This is an existing artifact inspection,
not a new kernel build or claimed execution of new source.

Read-only baseline evidence SHA
`1b924c53f9dff37cc4c96cafd9ed2e42bbc49ba50fa7c08636121508cf050cf6`
pins the completed-image receipt, config, vmlinux notes and actual disassembly:

| Existing function | Emitted ordering |
| --- | --- |
| `arch_counter_get_cntpct` | ISB, one MRRC, return |
| `clocksource_mmio_readl_down` | Relaxed MMIO load, no DSB |
| `sun4i_timer_sched_read` | MMIO load followed by DSB |

The last helper is distinct from the registered MMIO clocksource callback.
Substituting its `readl` spelling would add DSB ahead of the original
ISB/MRRC. Adding observations also changes latency and any critical section;
none of those changes can be quietly treated as the original measurement.

## Primary ordering argument and stopping condition

Arm DDI 0406C.d, ID040418, permits physical-counter reads to execute
speculatively and out of order relative to other instructions. Its example
places ISB between a preceding memory poll and MRRC. The ISB descriptions
define instruction/context synchronization; that example does not establish
the proposed following relaxed-MMIO edge. The study has not justified a
two-sided temporal bracket for that fragment.
[ARMv7-A/R architecture manual, §B8.1.2](https://documentation-service.arm.com/static/5f8daeb7f86e16515cdb8c4e#page=1948),
[ISB, §A8.8.54](https://documentation-service.arm.com/static/5f8daeb7f86e16515cdb8c4e#page=390).

The official PDF is pinned at 18,635,697 bytes, SHA
`294668ae6480133b32d85e9567cc77c5eb0e1232decdf42cac7ab480e884f6e0`.
The web PDF parser refused its size; the bounded primary-source download and
local text extraction are retained. No secondary architecture summary is used
as the ordering contract.

Linux's relaxed-I/O contract orders accesses to the same peripheral; it does
not supply the missing CP15-counter/MMIO proof. Emitted source order alone is
insufficient. The comparison using ordered `readl` adds two DSBs, including
one before the counter; it is a measurement confound and is not asserted to
prove the whole bracket either.
[Locked Linux I/O ordering contract](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/Documentation/memory-barriers.txt?id=1b357ecb321392158d507b04672ffee57bfa071d#n2611),
[registered MMIO reader](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/mmio.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n26).

Initialization failure can unmap the timer resource or disable its clock.
There is no existing qualified diagnostic accessor/readiness/lifetime
interface. This study adds none. A future implementation would need a
separately reviewed successful-initialization/rate/control contract before
reading through that mapping; DT presence is insufficient.
[Timer initialization and cleanup](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/clocksource/timer-of.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n140).

## Conditional interval specification and six fixture families

The pure model accepts synthetic original downcounter values, separate
architectural values and seven explicit boolean premises. Missing readiness,
stable controls, accepted sequence, CPU continuity within each bracket,
no loss, proven ordering or a proven wrap bound prevents attribution. These
premises are declared assumptions, not assertions proved by this utility.
Every result retains `hardware_qualified:false` and `pm_admission:false`.

Downcounts map to increasing counts with `(~raw) & 0xffffffff`. A 32-bit wrap
at nominal 24 MHz is about 178.96 s; half range about 89.48 s. A short nominal
schedule cannot prove a faulty counter's frequency or wrap count. Per-pair
spans or inter-pair gaps at least half range remain ambiguous; a backwards
reference observation is not relabeled as a convenient forward wrap.

For spans `s1`, `s2` and an unambiguous inter-pair gap `g`, the conservative
nominal-rate/offset difference interval is `[g-2, s1+s2+g+2]` ticks. It includes
reference quantization and separate endpoint allowances; its full width is
`s1+s2+4`. Conditional resolution of an 18-tick discrepancy requires that
full width to be strictly below 18. Touching/quantization-overlapping brackets
remain inconclusive. Even a narrow compatible interval is not hardware health.

| Fixed family | Cases | Preserved result |
| --- | ---: | --- |
| Forward | 3 | Compatibility, stopped architectural value and rate/offset disagreement |
| Architectural reversal | 1 | Original 1000 → 982 ticks; exact nominal −750 ns arithmetic |
| MMIO-only reversal | 1 | Raw reference reversal retained; no counter blame |
| Wrap | 4 | Normal wrap, half-range ambiguities and unproved window refusal |
| Brackets | 4 | Touch, quantization, wide uncertainty and exact 18-tick boundary |
| Unqualified premises | 6 | Readiness, controls, sequence, migration, loss and ordering refusal |

An architectural reversal against forward non-overlapping reference intervals
can conditionally indicate disagreement between observation paths. A wide
bracket can preserve that ordering observation while failing to resolve the
historical magnitude. Neither result identifies which source failed.
All original fault values remain unchanged.

## Reproducible qualification and retained originals

```sh
task test:clock-reference-feasibility
task check:clock-reference-feasibility -- \
  --linux-archive <locked-linux-archive> \
  --baseline-evidence <preserved-existing-ordering-evidence.json> \
  --arm-manual <pinned-official-DDI0406C.d.pdf>
```

The saved checker verifies the full seven-source map, exact existing baseline,
primary-document hash and all ten current qualification inputs. Its owned
network-none container uses the pinned builder, read-only inputs, one CPU and
512 MiB. The comparison C file is compiled only; it has no main function and
is never executed or linked into a kernel. It models selected accessor
spellings, rather than claiming to be a newly compiled kernel implementation.

Corrected attempt `28f35e4123704c9694dfba8362336d07`, receipt SHA
`24be23ef827074d9387f2311cbbedb481a62676644497de322cb92cfeb0fb968`,
passes nine Python tests and 19 native, ASan/UBSan and actual ARM C cases.
Original session 10970 and managed run `7d6ea6349d474d8d94b6122c4fe7b23f`
exit 0, with no OOM or stop; no owned container remains running. All three
runtime outputs agree on original raw vectors and conditional calculations.
The three unexecuted ARM fragments emit one ISB/one MRRC each; relaxed and
original have zero DSB, ordered `readl` has two. Actual ARM fixture execution
qualifies pure arithmetic, not timer behavior or a physical counter route.

The first successful 18-case/eight-test attempt and source snapshot remain
historical: receipt SHA
`80f794561869dcc2092ea74af8a338fc8927c4654ad7e3c9d8bf560b6531b6cb`,
managed run `0d63a3857e284498b70dc9a6589f9583`, original session 92836,
exit 0/no OOM/no stop. Subsequent audit corrected the resolution flag from
reference-only width to the full comparison width. The added exact-threshold
negative control distinguishes that correction; the original 18 vectors and
all original logs/results remain unchanged. An earlier Task YAML parse failure
occurred before any fixture/managed launch; its exact draft and failure are
retained separately. No failed or superseded result is relabeled as current.

## Outcome and remaining gates

**STOP:** a valid two-sided ordering contract, accepted observation perturbation,
qualified provider lifetime and measured reference resolution are absent.
Compilation and synthetic agreement do not fill those gaps. This bounded
feasibility work can be reviewed and published with a STOP outcome while
NEO-192 remains open.

The combined accepted-source/current-input checks, exact preservation proof
and entirely fresh independent Standards/Spec reviews remain pending before
publication. A future measurement needs separate authorization, qualification,
source/image identities and exclusive device grants; none follows from this
report. No barrier change, clocksource switch, retry or PM admission is proposed
as a fix.
