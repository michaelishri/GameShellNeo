# MUSB failed-queue DMA ownership audit

10 October 2026, Pacific/Auckland. Research supporting NEO-106 and its separate
failed-queue mapping follow-up. Baseline: `6391d7e` on
`work/musb-restart-integration`.

The failed-resume-work allocation path still returns a mapped request to its
caller without releasing the mapping. A small, independent fix is justified:
call `unmap_dma_buffer()` in `musb_gadget_queue()`'s negative resume-work result
branch, alongside request unlink and restart-flag rollback. The concrete
callback used here cannot return an error after starting or completing a
request. This makes the rollback narrower than general controller teardown.
Sources: pinned `musb_gadget.c`, `musb_queue_resume_work()` in `musb_core.c`,
and [patch 0037](../kernel/patches/0037-musb-resume-request-ownership.patch).

CPI's Sunxi MUSB backend uses PIO, so this is shared-driver correctness work;
it does not establish a GameShell DMA fault, power saving or faster transfer.
This report involved source inspection only: no device contact, image build,
sleep, reboot or physical test. Implementation and test results belong in the
subsequent fix record.

## Inputs and provenance

The [source lock](../build/sources.lock.json) pins Linux `v6.18.54`, upstream
commit `1b357ecb321392158d507b04672ffee57bfa071d`, archive SHA256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
The inspected local tree is `.local/sources/linux-6.18.54`; its gadget/core
functions include the project's restart changes. Relevant file hashes were
read afresh, rather than treating a public upstream page as the patched tree:

| Input | SHA256 |
| --- | --- |
| `drivers/usb/musb/musb_gadget.c` | `f7cdd35bff620dbc3d233c6599a7db690b1bb5d4965a8c501bbde863e408f96f` |
| `drivers/usb/musb/musb_core.c` | `1b3bd5d041efa1ad1668e59fdaf5947056626e7efcf61d73dd3e4cd81e46bb38` |
| `kernel/patches/0037-musb-resume-request-ownership.patch` | `1f43648b48c14bd29a6aff68bdeb26077bf8d4888f174afb2b24fbf3396e8137` |

Earlier findings and scope are retained in [report 139](139-musb-teardown-power-audit.md),
[report 141](141-musb-removal-backend-contracts.md) and
[report 225](225-musb-resume-request-ownership.md). The completed restart
integration is recorded separately in [report 239](239-musb-restart-integration-review.md).
Those reports did not close failed-queue mapping or full NEO-106 removal.
The public stable-tree source page was unavailable during this audit;
function-level conclusions below were checked against the pinned local files.
Official gadget and DMA API documentation was also read online.

## Exact failure and request ownership

For an otherwise valid request, `musb_gadget_queue()` obtains a runtime-PM
reference, initializes the transfer fields, maps its buffer, takes
`musb->lock`, checks the endpoint descriptor, and adds the request to the
endpoint list. If it becomes an idle endpoint's head without an existing
restart obligation, the function sets `restart_pending` and calls
`musb_queue_resume_work()`.

The helper's actual return paths are:

| Condition | Result | Has this invocation started the requested restart? |
| --- | --- | --- |
| Null callback | `-EINVAL` before locking | No; this caller supplies a non-null static function. |
| Runtime-suspended controller and failed `devm_kzalloc(GFP_ATOMIC)` | `-ENOMEM` | No callback and no pending-list node. |
| Runtime-suspended controller and successful allocation | `0` | Work owns the future callback; no immediate restart. |
| Controller not runtime-suspended | Callback's return value | Callback executes synchronously under the caller's controller lock. |

Source: pinned `musb_core.c`, `musb_queue_resume_work()`. Its comment mentions
returning `-EINPROGRESS`, but the implementation has no such return path.
Do not confuse this with `pm_runtime_get()`'s separately accepted
`-EINPROGRESS` earlier in `musb_gadget_queue()`.

The concrete callback, `musb_ep_restart_resume_work()`, returns zero on both
its busy-endpoint handoff and its normal exit. `musb_ep_restart()` itself
returns `void`. Therefore the current non-null callback cannot return a
negative status after its work has consumed, completed or requeued the request.
For this call site, the reachable negative helper result is the allocation
failure, before any new restart callback runs. The controller lock remains
held throughout that failed call and its existing list/flag cleanup. Sources:
pinned `musb_gadget.c`, these three functions; patch 0037.

Currently that cleanup removes the request and clears `restart_pending`,
then drops the lock and balances the PM reference. It omits the DMA rollback
already present in the disabled-endpoint branch. A negative queue return
does not transfer responsibility to a future completion callback: the gadget
API promises completion only for a successful submission. It also forbids
calling the submitted request's completion from inside `usb_ep_queue()`.
Source: pinned `drivers/usb/gadget/udc/core.c`, `usb_ep_queue()` documentation;
[official gadget API](https://docs.kernel.org/driver-api/usb/gadget.html).

Existing synthetic synchronous-completion cases remain valuable defensive
ownership tests for the restart machinery. They do not establish ordinary
CPI PIO behavior or override the gadget API contract. In particular, do not
place unconditional request cleanup after the successful callback: earlier
completion paths may have given the request back or freed it. The proposed
cleanup is confined to the proven pre-callback failure arm.

## What the missing rollback loses

`map_dma_buffer()` and `unmap_dma_buffer()` distinguish three states:

| State at failure | Required rollback | Current failed-queue consequence |
| --- | --- | --- |
| `MUSB_MAPPED` | `dma_unmap_single()` with the original device, size and direction; reset DMA address to `DMA_ADDR_INVALID`; clear mapping state | The driver's mapping remains live after the failed return. |
| `PRE_MAPPED` | `dma_sync_single_for_cpu()`; retain the caller's DMA address; clear MUSB's mapping state | The buffer is not handed back through the matching CPU synchronization. |
| `UN_MAPPED` | No DMA API operation | PIO, unavailable channel, incompatible buffer, or failed mapping remains a no-op. |

Source: pinned `musb_gadget.c`, mapping helpers. For IN/TX the direction is
`DMA_TO_DEVICE`; OUT/RX uses `DMA_FROM_DEVICE`. The Linux DMA API requires
matching mapping ownership and appropriate CPU/device synchronization; an
abandoned software submission does not remove those obligations.
[DMA mapping guide](https://docs.kernel.org/core-api/dma-api-howto.html).

Retry makes the owned-mapping case worse than a temporary leaked flag. On the
next queue call, `map_dma_buffer()` first resets `map_state` and then notices
the still-valid DMA address. It treats that formerly MUSB-owned address as
`PRE_MAPPED`. A later successful giveback can synchronize it for the CPU but
will not release the original driver-owned mapping. Simply freeing a failed
request cannot fix this: `musb_free_request()` traces and frees the request
object without DMA cleanup. Sources: pinned `musb_gadget.c`, these functions.

## All four DMA backends and the CPI boundary

The relevant operations during the failure path are mapping and compatibility
checks, not backend transfer programming. None of the four inspected
compatibility choices starts a transfer. An allocation failure occurs before
`musb_ep_restart()`, `txstate()` or a later RX handler could program this
new request. This is why rollback does not need to abort an active DMA
transfer for this specific failure.

| Backend | Mapping eligibility in this path | Consequence for the proposed rollback |
| --- | --- | --- |
| Inventra HSDMA | No `is_compatible` hook; an allocated channel allows the common mapping helper to proceed. | Both owned and caller-supplied mappings need matching rollback. |
| TUSB/OMAP | No `is_compatible` hook; an allocated channel uses the common mapping helper. | Same rollback; do not involve its separate channel abort/release callbacks. |
| UX500 | `ux500_dma_is_compatible()` checks packet/buffer alignment, transfer alignment and minimum length. | Accepted buffers need rollback; rejected buffers remain unmapped. |
| CPPI41 | Gadget compatibility permits bulk TX and rejects gadget RX because of the documented hardware advisory; non-bulk is rejected. | Eligible bulk TX needs rollback; rejected gadget requests remain unmapped. |
| Sunxi/CPI and PIO | `sunxi_musb_dma_controller_create()` returns `NULL`; endpoint enable sets no DMA channel, and Sunxi init selects its PIO mode. `CONFIG_MUSB_PIO_ONLY` separately makes capability false when selected. | No mapping is created; calling the existing helper adds no DMA operation. |

Sources: pinned `drivers/usb/musb/musbhsdma.c`, `dma_channel_allocate()` and
`musbhs_dma_controller_create()`; `tusb6010_omap.c`,
`tusb_dma_controller_create()`; `ux500_dma.c`, named predicate;
`musb_cppi41.c`, `cppi41_is_compatible()`;
`sunxi.c`, named creation/init functions; `musb_dma.h`, `is_dma_capable()`;
`musb_gadget.c`, endpoint enable/mapping/restart. These are source conclusions,
not DMA-engine hardware tests or proof that all backends reach a runtime-sleep
allocation failure on real boards.

## Recommended implementation and qualification

Keep the patch limited to the negative `musb_queue_resume_work()` result arm:
unlink the rejected request, clear restart ownership, and run its existing
mapping rollback while the controller lock still excludes endpoint teardown.
Preserve the negative return, PM balancing and absence of a completion callback.
Do not alter success-path lifetimes, request status conventions, or generic
DMA-channel teardown as part of this change.

The current [request fixture](../kernel/tests/musb_request_resume_test.c)
uses substitute mapping helpers. Its failed-work-allocation case explicitly
expects one mapping and zero unmaps, documenting the deferred bug rather than
testing rollback. Change that expectation and add coverage using the extracted
production mapping helpers, so tests can distinguish unmap from CPU sync:

1. Owned and caller-supplied mappings, IN and OUT, failed work allocation:
   exactly one matching rollback, no completion/start, empty request/pending
   lists, clear restart flags and balanced PM references.
2. Retry the same request after failure, then complete or cancel it. An owned
   mapping must be newly created rather than silently reclassified as supplied.
   A supplied address must remain unchanged and have matching device/CPU syncs.
3. DMA-disabled, no-channel, compatibility rejection and mapping-error cases:
   no invalid unmap/sync. Preserve disabled-endpoint and failed-PM behavior.
4. Successful deferred/active paths, including existing completion/free and
   requeue boundary tests: no new request access or early unmap after success.
5. A negative control that removes the rollback must fail; reject incomplete
   scenario receipts. Retain ARM32 coverage and compile relevant DMA-capable
   alternatives before calling the shared-driver patch qualified.

The full-driver KUnit restart suite is complementary to mapping-helper models;
it does not supply physical DMA/IOMMU or cache-coherency evidence. Since the
GameShell is PIO, later board regression testing can qualify its unaffected
queue/restart paths but cannot substitute for DMA-backend hardware qualification.

## Separate teardown lead: channel lifetime is not mapping lifetime

The audit found a second precise boundary that should remain with NEO-106:
`nuke()` aborts/releases an endpoint's DMA channel and sets `ep->dma = NULL`
before walking its request list and calling `musb_g_giveback()`. The latter
calls `unmap_dma_buffer()`, which returns immediately when `ep->dma` is null.
A request still carrying a mapping at that point can therefore bypass its
mapping cleanup. CPPI41's TX programming-failure branch likewise releases
and nulls its channel before the intended PIO fallback invokes the helper.
Sources: pinned `musb_gadget.c`, `nuke()`, `musb_g_giveback()`,
`unmap_dma_buffer()` and `txstate()`.

Do not fix those paths by casually deleting the helper's channel guard.
They require proving transfer and callback quiescence, preserving DMA failure
semantics and reviewing the pre-lock mapping versus endpoint-disable boundary.
The backend-specific abort/release contracts and lock conflicts in
[report 141](141-musb-removal-backend-contracts.md) still apply. A useful next
audit is an extracted production `nuke()`/mapping reproduction with explicit
active, aborted and callback-in-flight states, followed by backend-specific
retirement design. The small queue-allocation rollback neither settles that
ordering nor completes controller IRQ/work/timer/PM removal.
