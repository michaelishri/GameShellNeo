# brcmfmac TX recovery review and offline acceptance

12 October 2026 NZDT. NEO-197's isolated offline candidate scope is complete.
NEO-58 retains deliberate image integration and matching board qualification.
Neither diagnostic.26 nor the live GameShell was modified.

The independent Standards and Spec reviews used
`git diff 6da261d3e7b812b25e818b036fab2482d86e6236...310c41e73e804365b5c8b5d0173bd5b6d0344d9e`:
one commit containing candidate 0049, the actual-source tests and
[report 279](279-brcmfmac-tx-recovery.md). Both reviewers separately checked
the subsequent fixture-only cleanup against `310c41e`.

## Standards

No documented-standard violations. The driver fix addresses the underlying
error contract and keeps hardware and energy claims within the available
evidence, consistent with `AGENTS.md`.

One low-priority judgement call, possible **Primitive Obsession**, identified
integer fault stages and helper indices such as `fault == 5` and `index == 27`,
also repeated in Python mutation targets. The cleanup resolves it with
`enum recovery_fault` and separate helper failure, success, exhaustion and
prior-error groups. Ordinary matrix indexing remains. The follow-up reviewer
confirmed all 31 helper scenarios and 107 total TX cases remain represented,
with no new documented-standard violations or substantive smells.

**Standards: zero hard violations; one low-priority suggestion resolved;
no outstanding finding.**

## Spec

No Spec findings. The complete applied source preserves the three-pair flush
budget, control retry budget, and original send completion when recovery
succeeds. Every recovery stage checks its result before further I/O;
exhaustion latches `-ETIMEDOUT`, and prior errors remain intact.

Fatal data recovery releases the host, postprocesses and completes the dequeued
batch once, retains untouched queued packets, and prevents later polling,
dequeueing or flow unblocking. DPC then reacquires the host for quarantine.
Fatal control recovery enters quarantine while already holding the host,
leaving existing cleanup to publish the error and complete the pending request.

No missing offline requirement, unrequested scope expansion or incorrect
implementation was identified. Fixture boundaries are explicit: packet
preparation/postprocessing, packing, transport and worker packet calls are
controlled seams. They do not establish complete-kernel concurrency or physical
FIFO behavior. The separate polling-status error remains outside this fix.

The cleanup review confirmed exact helper mapping: old 0–23 become failure
0–23; 24–26 become success 0–2; 27 becomes exhaustion 0; 28–30 become prior-error
0–2. Operation counts, statistics, first-error preservation, repeated cleanup,
host balance and equivalent mutation targets are retained.

**Spec: zero findings in either review; no outstanding finding.**

## Final evidence

`task test:brcmfmac-tx-recovery` completed successfully after cleanup:

- 107 TX and 115 RX cases in native, ASan/UBSan with leak detection, and ARM32
  execution; 17 TX, four packet and five control-FIFO mutations rejected.
- 179 normal / 181 debug worker cases in all three execution modes and 48
  assertion-based worker mutations rejected.
- All 19 current inputs match the new manifest. All 1,014 artifacts in each
  old and new attempt rehash correctly; extracted production bodies match.
- Complete board/debug objects and their configurations from report 279 were
  rehashed. Applied source and patch queue are unchanged. The fixture rerun
  did not rebuild those objects; it reuses their unchanged production inputs.

The follow-up attempt is
`.local/build/brcmfmac-tx-recovery/attempts/2dd27f94c427479785bc76daafa3f180/`.
Its manifest SHA-256 is
`71d70b012b4b354ea57beb71df11349552ee814bb8b7bbf7f3c04cbf46c0f970`.
The private `review-cleanup-verification.json` receipt SHA-256 is
`e2d81086848774db7a8527d6bf67faa760d25df123b7206dce3979d43f8b5755`.
Report 279 retains the original 44/107 reproduction, full object hashes,
candidate identity and detailed coverage/limitations.

NEO-198 now tracks the independent `sendfromq()` polling-status error contract.
Missing clock-ready notification, reset/reprobe ownership and subsequent
integration/hardware work remain with NEO-58. No attribution is made to
NEO-55's authentication delay, and abandoned NEO-154 work is not resumed.
