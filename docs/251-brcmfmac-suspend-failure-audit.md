# Remaining brcmfmac suspend-failure leads (NEO-58)

10 October 2026, Pacific/Auckland. Source-only follow-up against project commit
`6391d7e` and the locked Linux 6.18.54 source with the current patch queue. No
device access, PM operation, image change or fault injection was performed.

The best next bounded repair is **mailbox transport-error propagation**. A
failed mailbox read can currently be interpreted as a firmware crash, receive
retransmission completion, protocol readiness and flow-control update. The
existing worker fault isolation cannot catch this because the mailbox helper
does not return an error. This narrows the already-recorded nested-helper audit
into a specific implementation and regression-test target; it does not explain
NEO-55's earlier authentication failure.

## What is already covered

The original [NEO-58 audit](80-brcmfmac-suspend-failure-audit.md) should not be
read as a description of today's unmodified driver. The current source has:

| Boundary | Existing implementation and evidence | Remaining limit |
| --- | --- | --- |
| KSO, clock and sleep operations | Patch 0014 checks low-level errors and uncertain transition state; [report 81](81-brcmfmac-sleep-error-propagation.md). | Nested packet/mailbox operations are separate call paths. |
| Worker collection and completion reuse | Patch 0015 serializes admission/accounting, bounds the collection wait and rejects reuse with outstanding waiters; [report 82](82-brcmfmac-freezer-lifecycle.md). | The collection deadline is not a bound on all SDIO I/O or teardown. |
| Retained-power rollback | Patch 0016 checks sleep/wake, owns PM wake references, returns host-flag failures and isolates failed restoration; [report 83](83-brcmfmac-pm-rollback.md). | A failed restoration still requires a fresh device lifetime; there is no qualified automatic recovery. |
| IRQ, PM, reset and removal ownership | Patch 0017 defers sleeping status reads and coordinates callbacks with F2's device lock; [report 84](84-brcmfmac-pm-lifecycle.md). | The reset worker still needs an explicit result/replay policy. |
| Worker entry and status refresh | Patch 0018 checks wake, status read/acknowledgement and flow-control refresh, preserves the initiating error and performs process-context cleanup; [report 89](89-wifi-worker-error-handling.md). | Its IRQ harness substitutes mailbox/packet helpers; it does not validate their internals. |
| Later command admission | Patches 0020–0022 cover regulatory requests, netdev transmission and band-query errors; [report 106](106-brcmfmac-regulatory-suspend.md), [report 109](109-wifi-transmit-suspend-ownership.md), and the [patch inventory](../kernel/README.md). | These do not change `brcmf_sdio_hostmail()` or its caller's error contract. |

This audit does not rerun those historical suites or replace their hardware
qualification records. The queue and actual source were inspected to avoid
reimplementing work already completed.

## The concrete mailbox failure

The current `brcmf_sdio_hostmail()` reads `tohostmailboxdata` into `hmb_data`,
conditionally acknowledges it when the read succeeded, then interprets
`hmb_data` regardless of the read or acknowledgement result. Its return type
is `u32`: it returns derived interrupt bits and loses `ret`. The caller
`brcmf_sdio_dpc()` removes `I_HMB_HOST_INT`, ORs in those derived bits and
continues receive/transmit dispatch. Neither error reaches patch 0018's
`failed:` path. [Pinned SDIO source][sdio], `brcmf_sdio_hostmail()` and
`brcmf_sdio_dpc()`; [worker patch](../kernel/patches/0018-brcmfmac-worker-errors.patch).

There are three distinct cases:

1. **Backplane-window setup fails.** `brcmf_sdiod_readl()` initializes its
   data result to zero and returns that zero with the error. The mailbox
   helper silently consumes the indication without reporting a transport
   failure. [Pinned bus-access source][bcmsdh], `brcmf_sdiod_readl()`.
2. **The four-byte mailbox transfer fails after successful window setup.**
   MMC's `sdio_readl()` explicitly returns `0xffffffff` with a nonzero error.
   `brcmf_sdiod_readl()` passes that value through. Every defined mailbox flag
   therefore appears set when `hostmail()` ignores the error. This is a
   specified failure sentinel, not a speculative uninitialized value.
   [Pinned MMC source][sdio-io], `sdio_readl()`; [bus-access source][bcmsdh],
   `brcmf_sdiod_readl()`; [SDIO source][sdio], mailbox flag definitions and
   `brcmf_sdio_hostmail()`.
3. **The mailbox read succeeds but its acknowledgement fails.** The helper
   still publishes all decoded state despite the failed write. A transport
   error does not establish whether the write took effect, so blind replay
   could repeat side effects. It should not be added as an implicit retry.
   [Pinned SDIO source][sdio], `brcmf_sdio_hostmail()`.

For the all-ones read sentinel, the current function can:

- Call `brcmf_fw_crashed()` because `HMB_DATA_FWHALT` appears set. That helper
  logs a firmware crash, requests a coredump and schedules reset work when its
  lifetime checks permit it. A failed host read is not proof of a firmware
  crash. [Pinned core source][core], `brcmf_fw_crashed()`.
- Clear `rxskip` and return `I_HMB_FRAME_IND` because `HMB_DATA_NAKHANDLED`
  appears set, despite lacking a valid retransmission acknowledgement.
- Change `sdpcm_ver`, run the debug console-address helper when compiled,
  and change flow-control state/counters from the same invalid value.

The latter two effects follow directly from `brcmf_sdio_hostmail()`'s branch
order. These are **source-established possible effects** under injected
transport errors, not observed board events. No claim is made about the cause
of NEO-55, how often these errors occur, measured energy savings, or the
firmware's behavior after an uncertain acknowledgement. [Pinned SDIO
source][sdio], `brcmf_sdio_hostmail()`; [NEO-55 source
audit](76-wifi-resume-authentication-source-audit.md).

## Bounded implementation and tests

Give the mailbox operation separate error and interrupt-status outputs, for
example `int brcmf_sdio_hostmail(struct brcmf_sdio *bus, u32 *status)`. Set the
status output to zero, check the read immediately, then check the
acknowledgement immediately. Only after both succeed should the existing
mailbox semantics run and status be published. Count attempted register
operations rather than unconditionally adding two. In the caller, route a
nonzero result to the existing `failed:` label while the SDIO host is still
claimed. This reuses the established fatal-worker ownership and cold-restart
policy; it does not invent an automatic reset/retry policy. This is a proposed
repair, not a patch implemented by this report.

The existing harness currently cannot establish that repair:
[`brcmfmac_irq_checks.extracted()`](../tools/brcmfmac_irq_checks.py) extracts
the status reader, DPC, ISR and worker, while
[`brcmfmac_irq_test.c`](../kernel/tests/brcmfmac_irq_test.c) supplies a
`brcmf_sdio_hostmail()` stub that returns `hw.mailbox_result`. The
`lost_mailbox_service` negative control proves dispatch to the stub, not
correct parsing/error handling inside the real helper. Extend the actual
source extraction and fixtures rather than adding only another dispatch
assertion. [Existing scope](88-wifi-deferred-interrupt-service.md).

| Scenario | Required result |
| --- | --- |
| Read fails with zero or all-ones returned data | Exact error propagates; no ACK, crash callback, NAK state change, readiness update or flow-control publication. Count one attempted mailbox read. |
| Read succeeds; ACK fails | Exact ACK error propagates; no decoded side effects or retry; count both attempted accesses. |
| Either failure with unrelated pending RX/TX/control work | DPC reaches existing cleanup before packet dispatch; first error retained, pending control waiters completed, IRQ cleanup performed once, later I/O rejected. |
| Successful NAK/ready/flow-control/halt messages | Existing valid-message semantics and register sequence preserved. A genuine successfully read/acknowledged halt must remain distinguishable from the failed-read sentinel. |
| Repeated worker entry after failure | No second mailbox operation or duplicate fault cleanup; host claim/release remains balanced. |
| Negative controls | Removing either error check, continuing DPC after the error, or publishing status before acknowledgement must fail assertions. |

Run this with the established native/ARM32 actual-source method, normal and
DEBUG configurations, and full changed-driver compilation. Hardware
qualification belongs in a later image/test slice. A controlled hardware
fault experiment would need its own protocol; ordinary successful sleep
cycles alone cannot demonstrate the injected error cases.

## Other leads retained, without widening this repair

- **RX cleanup can delay worker retirement.** `brcmf_sdio_rxfail()` can execute
  65,535 count-poll iterations, reading two registers each time, without
  checking those read errors. Error sentinel bytes can keep it running rather
  than reaching a verified empty FIFO. The packet worker reaches its freezer
  checkpoint after DPC returns, so this is a concrete reason the existing
  five-second collection timeout is not an end-to-end I/O bound. Audit frame,
  retransmission and cleanup ownership before changing it; do not fold all
  packet recovery semantics into the mailbox fix. The function is unchanged
  from the locked archive. [Pinned SDIO source][sdio],
  `brcmf_sdio_rxfail()` and `brcmf_sdio_dataworker()`.
- **Missing clock-ready interrupt remains a separate policy gap.** Patch
  0018 deliberately leaves a legitimate `CLK_PENDING` request pending without
  spinning. It has no new deadline/recovery policy if that notification never
  arrives. Preserve that distinction from an actual mailbox transport error.
  [Report 89](89-wifi-worker-error-handling.md).
- **Host PM flags do not need an invented zero-clear rollback.** The current
  retained callback checks capabilities, calls the setter last and returns
  failures. The MMC setter rejects unsupported bits before ORing its shared
  flags; a zero call would not clear them. The initial audit's host-flag issue
  is already addressed at that boundary. [Pinned MMC source][sdio-io],
  `sdio_set_host_pm_flags()`; [rollback
  patch](../kernel/patches/0016-brcmfmac-pm-rollback.patch).
- **Generic OOB wake-reference cleanup is still separate.** Registration
  checks its initial `enable_irq_wake()` but ignores the matching disable
  result. PM-owned references do not repair registration-owned leakage.
  CPI v3.1 uses in-band interrupts, so this is lower priority for the supported
  board and already tracked. [Pinned bus source][bcmsdh],
  `brcmf_sdiod_intr_register()`; [report 83](83-brcmfmac-pm-rollback.md).
- **Automatic recovery is not supplied by the reset helper.** The generic
  reset worker ignores the bus callback result, and the SDIO callback ignores
  `mmc_hw_reset()`'s result. Existing lifecycle checks reject conflicting or
  quarantined resets. Busy replay, reset failure and synchronous/asynchronous
  reprobe ownership still need their own design. Do not use the false
  firmware-halt branch as a recovery mechanism. [Pinned core source][core],
  `brcmf_core_bus_reset()`; [SDIO source][sdio], `brcmf_sdio_bus_reset()`;
  [report 84](84-brcmfmac-pm-lifecycle.md).

## Source provenance and limits

The [source lock](../build/sources.lock.json) pins upstream commit
`1b357ecb321392158d507b04672ffee57bfa071d`. The local archive was SHA-256
verified as
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
The brcmfmac entries in the extracted tree's `.gameshellneo-patches.json`
match the current patch files 0014–0018 and 0020–0022. The tree is **patched**,
not the pristine archive. Its inspected files have these hashes:

| File | SHA-256 |
| --- | --- |
| `brcmfmac/sdio.c` | `44ceb7c83ec77865b3f1b302d8e9563f3e106f7d2d4aa84d9120272c70388ddf` |
| `brcmfmac/bcmsdh.c` | `3ccdaed542cc43614fadf11a8e50ab4cdd989266d40b13e3bb29fee22519e120` |
| `brcmfmac/core.c` | `ae348e49004b171eb99f8f850ef531fcf705ff57f71125438b25e10302c52b17` |
| `drivers/mmc/core/sdio_io.c` | `2f9db1b81f01d359faa689fb7609c04d6a9fdd7d833d16e201f74d7201e51e44` |

`brcmf_sdio_hostmail()`, `brcmf_sdio_rxfail()` and `brcmf_sdio_txfail()` were
compared with the verified archive's bodies and are unchanged. Mailbox source
is at local `sdio.c:1151`; its caller is at `sdio.c:2679`, existing fatal
cleanup at `sdio.c:2653`, and MMC's failed-read sentinel at `sdio_io.c:584`.
These line numbers describe the inspected patched tree, not the upstream
links. External kernel.org page retrieval was unavailable during this audit;
the verified local primary sources, patch files and checked-in harnesses
provided the evidence. No secondary-source claim or current-upstream fix is
assumed.

[sdio]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c?h=v6.18.54
[bcmsdh]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c?h=v6.18.54
[core]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54
[sdio-io]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/sdio_io.c?h=v6.18.54
