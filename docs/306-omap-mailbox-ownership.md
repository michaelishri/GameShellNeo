# OMAP2430 MUSB mailbox ownership

23 October 2026 NZDT. NEO-222 is a bounded software child of NEO-102, related to
NEO-106. Development and qualification use accepted base `02c633a`. Candidate
0063 remains outside production images. Native, sanitizer, ARM32, six selected
OMAP configurations and all 12 actual Linux lifetime cases pass. Independent
acceptance remains pending. No physical controller fault or hardware result
is claimed.

## Original schedules and source boundary

The original core publishes an unowned global callback before later probe
stages can fail. OMAP publishes another global parent pointer and queues work
which subsequently looks up the child. Its exit shuts down the PHY before
canceling that work. Independent PHY event producers can survive child unbind.

The unchanged reference bodies reproduce four schedules on retained static
fixture storage:

| Schedule | Observed boundary |
| --- | --- |
| A | A worker admitted before exit resumes after PHY retirement. |
| B | An admitted dispatcher queues work after the late cancellation. |
| C | Published callback ownership survives failed core probe and parent retirement. |
| D | An old admitted event reaches a replacement child. |

The reference executes actual core mailbox and OMAP callback/work/exit/remove
bodies. Core publication and fail2 statements are wrapped with modeled
acquisition. That wrapper is a bounded reachability reference; it does not
execute complete real probe. Work, device, PM, PHY and MMIO effects are modeled.
The separately retained Linux probe case exercises actual core initialization.

## Owned retirement and callback context

The explicit `musb-omap-mailbox` profile consists of unchanged retirement
candidates, unchanged 0029 and new 0063. It does not contain 0026 or depend on
NEO-219. The 33 production patches, old profiles and locks remain unchanged.

Core registration rejects a second owner. Removal and probe-error paths revoke
the exact owner and wait for admitted global SRCU dispatch before invoking the
backend handoff. Registration failure also closes that attempted backend child
without revoking another controller's ownership. The handoff precedes client
cleanup rather than relying on the later platform exit.

OMAP disables and drains mailbox work first. A running worker may still need the
parent runtime-resume callback, so the child gate remains open until that drain
finishes. It then unpublishes the child and waits for admitted child SRCU readers,
including the two parent runtime callbacks. Only afterward can clients and PHY
resources retire. There is no controller or parent PM spinlock across these
waits. Driver-core child locking does not stand in for parent-PM retirement.

| Caller | Admission and context |
| --- | --- |
| PHY dispatcher, including IRQ context | Global then child SRCU; the callback only records status under a short spinlock and queues work. |
| Mailbox work | Child SRCU covers the actual sleeping PM/hardware sequence. |
| Parent runtime suspend/resume | Child SRCU covers each unchanged admitted callback body. No child returns zero without hardware or glue-flag effects. |
| Probe unwind/remove | Process-context owner mutex and SRCU/work drains, outside controller locks. |

Pinned Linux permits nested SRCU readers but prohibits a reader from waiting on
its own domain's grace period. No reader takes the owner mutex used by the
writer. Static SRCU module registration/cleanup is supplied by Linux; dynamic
parent SRCU is a devres action after child removal and parent PM disable.
The six configuration guards require the actual `TREE_SRCU` or `TINY_SRCU`
implementation; Linux 6.18 has no `CONFIG_SRCU` selection symbol.

Admitted runtime-PM sequences, reference accounting and errors remain unchanged.
Closed/no-child callbacks retain the original successful no-op behavior. The
last accepted parent-owned status is retained across rebind: some providers do
not replay an event merely because the child rebinds. This is cached initialization,
not proof of a fresh physical state. An old admitted dispatch or work item must
finish before the new child can publish.

## Qualification and retained originals

The saved Tasks are `test:omap-musb-mailbox-reference`,
`test:omap-musb-mailbox`, `check:omap-musb-mailbox-drivers` and
`test:omap-musb-mailbox-kunit`. They use the pinned archive and builder with
network disabled, input hashes and managed container ownership.

The original baseline receipt is
`.local/build/omap-musb-mailbox-tests/reference-first/reference-evidence.json`
(SHA-256 `02b86abbd78af68ba70ee9c196173ce608c2496c8fc664ab569df3f471d89e48`).
It records four reproduced schedules, distinct from earlier extraction and
fixture-compilation failures which executed none of them.

The accepted native/configuration run 41596 records 32 cases per native,
ASan/UBSan and ARM32 execution plus nine compiling assertion controls. Its
receipt is `.local/build/omap-musb-mailbox-tests/compile-evidence.json`, SHA-256
`4621e2942a7f0b3ee8f64371811596ab8293dab69721bad0619002909f4be791`.
Independent retained inputs, binaries, controls, patch bytes and configuration
artifacts are under `compiled-first-41596/`. LSan is disabled because of the
host ptrace environment; the fixture uses retained static storage. ASan and
UBSan remain enabled.

The six complete configurations genuinely select the OMAP backend: gadget PIO,
host PIO, dual-role DMA, modules PIO, PM without system sleep and PM disabled.
Each compiles core and OMAP plus the selected role objects; the module case
also compiles the aggregate core object. These results do not qualify DMA
retirement merely because the DMA object compiles.

The Linux suite declares 12 exact cases: no owner, held dispatch, held work,
coalesced status, owner identity, core probe unwind, child rebind, parent remove,
held parent suspend/resume, closed/no-child parent PM and rebound parent PM.
It compiles the complete core/backend and uses real Linux SRCU, workqueues,
platform-device lifetime, generic PHY references and runtime-PM execution under
UML KASAN/lockdep. MMIO, PHY lookup/provider effects and most child lifecycle
callbacks are synthetic seams invoking actual lifetime helpers. The probe
unwind case instead enters actual `musb_init_controller()` and injects runtime-get
rejection. No full controller setup or complete remove claim follows from that.

Run 94555 failed before runtime because a test-local `struct musb` exceeded the
kernel stack-frame limit. Its exact inputs, source metadata, effective config,
log and terminal managed result are retained under
`.local/build/omap-musb-mailbox-kunit/failed-94555/`. The fixture now uses KUnit
allocation. Corrected original run 99421 passes all 12 cases. Its managed run
`73a984d81acf46c9ab477a1e5da7fd65` exited zero and ownership is released.

The Linux receipt is `.local/build/omap-musb-mailbox-kunit/evidence.json`, SHA-256
`b5bb3628525eb71e7cfcb6be9cdd189d37f5b3e22ce8c449405f1c95408b21a0`.
The independently retained artifact directory is
`kernel-3454479a3f804339/accepted-runs/9d8cc5969e584131a75f40c2a337122e`
under the same private build directory. It retains the kernel, effective
configuration, raw KTAP and JSON report. The expected injected probe rejection
prints one `musb_init_controller failed` line and one driver-core `error -22`
line, immediately before `probe_unwind_test` passes. No sanitizer, lockdep or
atomic-context failure was accepted.

The real-PM construction verifies parent runtime status against the glue flags
and actual generic-PHY counts, including closed/no-child no-op behavior and a
newly initialized rebound child. It does not introduce a flag reset or broader
PM policy change. Held work resumes the real parent while its child SRCU read
is active; held parent callbacks run through actual runtime-PM APIs and generic
PHY mutexes while removal waits.

Other retained failed originals include reference extraction/compilation,
candidate fixture preparation/linking, an attempt to compile an unselected role
object, and the invalid SRCU-symbol guard. None is counted as a passing schedule
or configuration. Native baseline, first candidate and final configuration
receipts remain distinct.

The original-base host check passes 24 runtime tests and 1,310 tooling tests
with nine existing opt-in skips, plus compiled C regressions, Bash syntax and
ShellCheck. The candidate passes checkpatch with zero errors and warnings.
These checks do not replace the separate kernel and original-container evidence.

## Remaining gates

Obtain independent Standards and Spec acceptance of the fixed source and
qualification bundle. A later integration base needs current-input equivalence
and fresh final reviews before publication. The bounded PM/glue construction
passes; it does not establish every possible PM policy or controller state.
A broader PM policy prerequisite must be reported before extending this
admission change.

Provider and other-backend lifetime, independent DMA callbacks, failed-power
MMIO, full system-PM traversal, SMP, image selection and physical qualification
remain open. No device, selector, installed release or clock acceptance changed.
NEO-102 and NEO-106 remain open even if this child is accepted.
