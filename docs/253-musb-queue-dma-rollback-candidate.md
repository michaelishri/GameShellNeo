# MUSB failed-queue DMA rollback candidate

10 October 2026. NEO-186, following the [NEO-106 source audit](250-musb-queue-failure-audit.md).
An isolated one-line candidate returns DMA ownership before a failed queue
operation returns to its caller. Actual-source native/ARM32 regressions,
sanitizers and two complete ARM driver configurations pass. This candidate
is **outside the active image patch queue**; diagnostic.25 and its hardware
qualification remain unchanged. No device connection or physical test ran.

## Correction and ownership boundary

The [candidate patch](../kernel/candidates/0038-musb-queue-dma-rollback.patch)
adds `unmap_dma_buffer(request, musb)` after list removal and restart-flag
rollback when `musb_queue_resume_work()` returns a negative result.
For this non-null, always-zero-returning callback, the reachable error is
failed deferred-work allocation, before that callback is installed or runs.
The controller lock still protects the existing cleanup. The request has
not been handed off to a new transfer or completion callback.

The existing unmap helper performs the correct operation for each state:
driver-owned mappings are unmapped and their DMA address invalidated;
caller-supplied mappings are synchronized back to the CPU with their address
preserved. Both become unmapped from MUSB's perspective. PIO, absent-channel,
incompatible and failed-map cases remain no-ops. Direction, length and DMA
device are unchanged. The error and runtime-PM reference balancing are retained.

There is no new request access after a successful restart callback. The
mapping helper's channel guard and endpoint-disable/teardown ordering are
unchanged. The separate channel-release-before-unmap and pre-lock
mapping/endpoint-disable race questions from report 250 remain unresolved;
this patch is not complete controller or DMA teardown.

## Saved validation

```sh
task test:musb-queue-dma
task check:musb-queue-dma-drivers
task check
```

The [checker](../tools/check-musb-queue-dma.py) verifies the locked archive,
replays the relevant existing patches including 0037 into separate scratch
sources, then applies the candidate. It requires that the gadget source
differs by exactly the single rollback call. The native fixture extracts
the complete production mapping/unmapping, queue, resume-work admission and
restart-callback functions. DMA API, hardware start, allocation, PM and
locking boundaries are modeled; their arguments and ownership effects are
asserted. None of this is a concurrent hardware test.

The [C fixture](../kernel/tests/musb_queue_dma_test.c) runs **74 scenarios per
execution**: 37 in each transfer direction. Seven mapping profiles cover
driver-owned, caller-supplied, DMA-disabled, absent channel, rejected
compatibility, failed mapping and an absent compatibility hook. For each it
checks allocation failure followed by retry of the **same request**, successful
deferred and active queues, disabled endpoints and failed runtime-PM gets.
Additional defensive free-during-start cases check success-path lifetime.
Those synthetic cases are not a claim that queue-time completion is permitted
by the gadget API or occurs on CPI hardware.

| Check | Result |
| --- | --- |
| Native candidate | All 74 scenarios passed |
| Native AddressSanitizer + UndefinedBehaviorSanitizer | All 74 passed, including real frees |
| Static ARM32 binary under QEMU | All 74 passed |
| Six negative controls | All failed assertions as intended |
| Complete ARM MUSB core and gadget objects | Board/Sunxi and separate MediaTek/Inventra DMA compile profiles passed |

The negative controls omit rollback, leave the mapping state or owned address
uncleared, omit caller-owned CPU synchronization, unmap caller-owned memory,
or reverse the direction. The original buggy queue is the missing-rollback
control. Successful compilation of a defective variant alone never counts as
a successful negative control; it must fail an assertion during execution.

For full-driver compilation, the tool constructs a separate source manifest
containing the normal image queue plus this candidate. It verifies that the
complete compiler source contains exactly the functions tested by the fixture,
then compiles the core/gadget objects and checks the resolved configuration.
The DMA profile enables compile-test, MediaTek glue and Inventra DMA; it is
not a supported board image. Both resolved configs and object hashes are saved.

Evidence is `.local/build/musb-queue-dma-tests/compile-evidence.json`, with
archive, candidate, harness, generator, build-helper and source-lock hashes,
generated-source identity, compiler profiles and results. The saved full log
is `.local/build/musb-queue-dma-drivers.log`; outer log
`.local/neo186-candidate-final.log` preserves the final invocation. The first
attempt stopped while compiling a negative control because its intentionally
unused fixture function triggered `-Werror`; the annotation was corrected and
the complete task rerun. Its failure remains in `.local/neo186-candidate.log`.

Candidate SHA-256:
`2d821d8dda762d0babf7a3e5c6496fceb15934581861450b6a443adf7561cacf`.
Compiler-evidence SHA-256:
`9bf07b4b018aedeb62e1138487c33a445a19cde76b77d3633fa8909d09f1bf21`.
The full `task check` also passes 16 runtime and 893 tooling tests (one existing
optional skip), compiled C checks and Bash/ShellCheck. Its output is saved in
`.local/neo186-check.log`.

## Integration and remaining limits

The normal exporter reads `kernel/patches`, while this patch lives under
`kernel/candidates`. The new tasks are explicit checks, not additions to
`task build`; no installed image inputs, source lock, collector or PM helper
were changed. Existing 0037 receipts continue to describe their original
source, including the documented deferred mapping bug.

Before promotion, assign the candidate a normal patch-queue entry, update the
affected source suites to test that queue (including their old failed-mapping
expectation), run the full restart/lifetime qualification, and give any image
a new identity. CPI regression can cover its PIO queue/restart behavior, but
does not qualify physical DMA/IOMMU/cache-coherency behavior on other boards.
The candidate's test coverage is not a measured GameShell speed or power gain.
NEO-186 remains in review for integration; full NEO-106 removal stays open.
