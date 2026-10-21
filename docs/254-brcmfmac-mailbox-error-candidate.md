# Wi-Fi mailbox transport-error candidate

10 October 2026. NEO-187, following the [NEO-58 audit](251-brcmfmac-suspend-failure-audit.md).
The isolated [0039 candidate](../kernel/candidates/0039-brcmfmac-mailbox-errors.patch)
checks mailbox reads and acknowledgements before interpreting firmware flags.
Native/ARM32 scenarios and complete normal/DEBUG ARM driver compilation pass.
It is outside the active image patch queue. No device connection, image change,
firmware change, audio or PM operation was performed for this work.

## Corrected boundary

The old helper returned derived interrupt bits and discarded transport errors.
A failed backplane-window operation can return zero; a failed four-byte SDIO
transfer returns all ones with an error. The latter value contains every
mailbox flag, including firmware halt. Decoding it could schedule crash handling,
clear receive-retransmission state, publish protocol readiness and change flow
control without valid data. A failed acknowledgement also allowed those effects.
Report 251 records the pinned source and precise failure contracts; no such
failure has been demonstrated on this board.

`brcmf_sdio_hostmail()` now returns an error separately from its interrupt-status
output. It clears that output, attempts the read and checks its result, then
attempts the ACK and checks its result. Only after both succeed does it run the
existing decoder. Its access counter records one attempted operation after a
read failure and two after an ACK failure or success.

The DPC caller checks the error while it still owns the SDIO host. Failure takes
patch 0018's established cleanup path before pending receive, transmit or control
work is dispatched. That path retains the initiating error, marks the bus down,
stops the watchdog, completes pending control waiters and quiesces IRQs once.
Subsequent worker/ISR entries cannot repeat the failed mailbox access. Valid
NAK, ready, version, flow-control and genuine firmware-halt handling is preserved.

There is no added retry. An ACK failure does not establish whether the firmware
received it; blindly repeating decoded effects would require a separate protocol.
This candidate retains the existing cold-restart policy after fatal transport
errors. It neither repairs firmware nor introduces automatic reset/reprobe.

## Repeatable validation

```sh
task test:brcmfmac-mailbox
task check:brcmfmac-mailbox-drivers
task test:brcmfmac-worker
task test:brcmfmac-irq
task check
```

The [checker](../tools/check-brcmfmac-mailbox.py) verifies the locked Linux 6.18.54
archive, builds a separate source manifest containing the complete normal queue
plus candidate 0039, and extracts the actual mailbox, ISR, status reader, DPC,
worker, OOB rearm and IRQ-quiesce bodies from that source. Complete ARM driver
compilation uses the same source. The normal exporter still reads only
`kernel/patches`; candidate 0038 is not implicitly included with this work.

The [shared fixture](../kernel/tests/brcmfmac_irq_test.c) selects the actual
mailbox helper only for the new task. The earlier IRQ and worker suites retain
their historical source queues and mailbox stub, so old receipts are not silently
reinterpreted. Register, clock, packet-dispatch, workqueue, firmware-crash and
console-read boundaries remain modeled; real firmware and Linux scheduling are
not executed by these tests.

The new mode adds 82 scenarios to the existing 49 worker/IRQ scenarios:

- 12 direct-helper failures: read versus ACK, zero versus all-ones data, and
  `-EIO`, `-ETIMEDOUT` or `-EILSEQ`. Each checks the exact error, output zeroing,
  access counts and absence of decoded state changes.
- 48 worker failures: the same fault matrix with hard/deferred ISR admission
  and in-band/OOB ownership. RX, TX and a control request are pending. Each checks
  no packet dispatch, single cleanup, waiter completion, host balance and no
  additional access after subsequent ISR/worker entries.
- 22 successful messages: empty, NAK, device/firmware ready, mismatched version,
  three flow-control states, genuine halt, combined valid flags and an unknown
  bit, each with receive skipping initially set or clear. These retain the old
  valid-message effects and diagnostics.

DEBUG adds the two existing clock-error cases and checks the console-read
boundary on readiness. The fixture models that boundary as a no-op for a normal
build, matching the production conditional helper; it does not execute firmware
console transfers or coredump/reset work.

Negative controls include the established IRQ/worker mutations plus omitted
mailbox read/ACK checks, lost output initialization or frame publication, lost
DPC error exit, lost NAK/flow/halt effects, inaccurate access counting, changed
errno and decoding before acknowledgement. Each must compile and then fail an
assertion. Returning the right ACK error after publishing state is also rejected.

| Check | Result |
| --- | --- |
| Native normal / DEBUG | 131 / 133 scenarios passed |
| Static ARM32 under QEMU, normal / DEBUG | 131 / 133 scenarios passed |
| Native negative controls | All 43 compiled and failed assertions as intended |
| Complete ARM `brcmfmac.o`, board / `CONFIG_BRCMDBG=y` | Both passed, including resolved configuration checks |
| Existing worker task | 49/51 normal/DEBUG IRQ scenarios and 105 lifecycle/PM/reset scenarios passed on native and ARM32; existing negative controls rejected |
| Historical IRQ task | 23 native/ARM32 scenarios passed, preserving its four pre-worker-fix characterizations; existing negative controls rejected |
| Host `task check` | 16 runtime and 893 tooling tests passed (one existing optional skip), plus C and shell lint |

Evidence is saved under `.local/build/brcmfmac-mailbox-tests/`, including source
and input hashes, generated function/type hashes, full patch manifest,
normal/DEBUG native and ARM32 results, assertion logs and compiler configurations.
The driver task keeps its full log at `.local/build/brcmfmac-mailbox-drivers.log`.

Candidate SHA-256:
`57d4eb89378b79002ce179fe249e8d82bff98cc1956b95bd96404ce1ab447756`.
Compiler-evidence SHA-256:
`afdd2373e177f20ee9934beb7e3a6a4d6382c1126b7f6e1504e26ca6203ac8ec`.
The final invocation log is `.local/neo187-candidate-final.log`; host checks are
in `.local/neo187-check.log`. The first run stopped on a DEBUG fixture mismatch:
`DEBUG` was defined inside the generated driver header, after its console-read
stub had compiled. The flag now applies to the complete native translation unit,
as it already does for ARM32. The full candidate suite and both driver builds
then passed. `.local/neo187-candidate.log` and the archived stage log preserve
that failed attempt. No production-code change was needed to correct the fixture.
Existing-suite runs are saved in `.local/neo187-worker-regression-final.log` and
`.local/neo187-irq-regression-final.log`, with their stage logs under `.local/build/`.

## Promotion and remaining work

NEO-187 needs source-suite integration and a separately identified image before
hardware qualification. Promote the candidate into the active queue deliberately,
update the build/source tasks to include it, then qualify ordinary Wi-Fi traffic,
retained-power suspend/resume and repeated recovery on CPI v3.1. Successful sleep
cycles alone cannot demonstrate injected transport failures; retain the source
fault tests as their distinct evidence. Obtain owner readiness for physical or
screen tests.

NEO-58 remains open. RX FIFO cleanup polling, a missing clock-ready notification,
generic OOB wake-reference cleanup and automatic recovery still have the separate
ownership/policy questions recorded in report 251. This change does not establish
the cause of historical Wi-Fi failures, improve RF reception, or prove a measured
speed or energy saving. The abandoned SSH-stall investigation is not reopened.
