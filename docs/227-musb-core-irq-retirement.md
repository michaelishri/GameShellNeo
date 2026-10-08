# Retiring the MUSB core IRQ action before resource release

9 October 2026, Pacific/Auckland. NEO-165, a source-only NEO-106 continuation
on `work/musb-irq-retirement`, based on `d8a6899`. NEO-108 image installation
remains parked; no GameShell connection, card operation or image build occurs.

## Boundary being fixed

After role cleanup, the old remove path exits the platform and destroys DMA
before freeing the core IRQ action in `musb_free()`. The failed-probe `fail3`
path likewise destroys DMA before that action is removed. A still-registered
handler can therefore reach resources whose cleanup has already run. This
is the source ordering described in [report 141](141-musb-removal-backend-contracts.md),
not an attributed CPI hardware incident.

[Patch 0039](../kernel/patches/0039-musb-core-irq-retirement.patch) introduces
`musb_shutdown_irq()` and `musb_free_irq()`. Normal removal keeps the existing
host/gadget cleanup first. Failed probe reaches `fail3` after
[NEO-164's role unwind](226-musb-probe-role-unwind.md). Both paths then:

1. Skip IRQ work if no core action was acquired (`nIrq < 0`).
2. Run the existing platform disable hook outside the controller lock.
3. Mask the Mentor core interrupt sources and clear DEVCTL under that lock.
4. Drop the lock, attempt the existing wake-reference disarm, and call
   `free_irq()` with this controller's `dev_id`.
5. Set `nIrq` to `-ENODEV` after the drain returns, preventing a second free
   when the allocation finalizer runs.

The allocation finalizer retains an idempotent action-release fallback, which
does not access controller registers. On the wired paths it either has no
acquired action or sees one already retired. IRQ number zero remains valid.
No `disable_irq()` is applied to the shared line; other devices retain their
own actions. The original IRQ number remains valid through wake disarm and
the drain. A failed wake disarm is logged; terminal wake-reference recovery
remains unresolved, as it was before this patch. The existing `irq_wake`
indicator also continues to select the failed-probe wakeup-source cleanup.

## Validation plan and commands

```sh
task test:musb-irq
task test:musb-irq-kunit
task check:musb-irq-drivers
task check
```

The source runner extracts the actual IRQ helpers, allocation finalizer,
normal remove function and failed-probe tail. It also checks the acquisition
boundary: IRQ ownership is published only after `request_irq()` succeeds,
and failed role setup reaches the tested tail. It executes 34 cases on native
and ARM32, covering acquired/unacquired action, IRQ zero, wake present/absent,
wake-disarm failure, DMA present/absent, remove/failure paths and repeat free.
MMIO, PM, client/DMA cleanup and IRQ APIs are controlled boundaries. Nine
native negative controls exercise late/early removal, missing probe drain,
missing/double free, waiting under the controller lock, global line disable,
wrong wake IRQ number and masking an unowned action. This is not execution of
the entire controller probe or an actual interrupt synchronization test.

The separate Linux UML KUnit suite compiles the full production MUSB driver
with KASAN and lockdep. A test-only patch appends the fixture; it does not
replace production functions. Four cases use the real release helper and
Linux IRQ core with a simulated interrupt source:

- An unowned action leaves the peer intact.
- Releasing an owned action twice does not remove the peer's action.
- A threaded handler is held open while another kernel thread calls the
  release helper. Observing the action unlink under the descriptor lock proves
  that `free_irq()` has entered its drain. Cleanup must remain unfinished and
  modeled resources live until the held handler returns. The peer still runs
  after release, while the removed handler does not.
- Three successive request/release cycles retain independent peer delivery.

This is a single-CPU UML kernel using real IRQ actions, wait/synchronization
and threads. The source and handler are synthetic, not the physical MUSB ISR;
real wake-disarm, hardware masking, DMA, SMP and full removal are not tested.
The strict validator requires exactly the requested suite and every case
passing, rejects kernel diagnostics, and retains independent accepted binary,
configuration, result and log copies. Restart and IRQ suites share the runner
but have separate source hooks, identities and result validation.

The ARM matrix compiles project gadget, host, dual-role, combined module and
no-PM driver configurations against the complete candidate queue. It does
not produce a bootable image.

## Results

Validation is in progress; final receipts and review results will be recorded
after the checks finish.

The first UML execution correctly rejected the original fixture: its peer
`dev_id` aliased the controller because `musb` was the fixture's first member.
The peer now uses its own counter's address consistently for request, callback
and release. Follow-up specification review also found that fixture init
manually cleaned up failed setup even though KUnit invokes exit after failed
init. Init now leaves cleanup to KUnit, and exit accepts a null fixture after
allocation failure. The reviewer confirmed both corrections. The production
patch was unchanged; the initial failed run is not accepted evidence.

## Remaining NEO-106 obligations

Removing this action is one necessary lifetime boundary. Existing platform
disable hooks and Mentor masks do not establish complete masking of every
backend wrapper or independent DMA source. MediaTek L1/DMA masking, the MPFS
parent clock-before-child ordering, independent DMA callbacks and backend
timers/notifiers/role setters remain in report 141's backend audit. This patch
does not change those hooks or claim safe removal on every backend.

Core delayed work can still be queued by client cleanup or other producers
after the earlier cancellation in normal remove. Runtime-PM callbacks, the
core OTG timer, backend producers and session references need coordinated
terminal retirement while their resources are valid. DMA destruction still
follows platform exit in normal remove; its independent resource needs remain
unresolved. Failed PM acquisition also does not establish hardware access.

Those boundaries require further implementation and tests before complete
teardown or physical controller unbind/rebind is qualified. The older
extcon/Sunxi lifetime candidates stay separate; no automatic integration is
implied. No boot-time or power saving is claimed.
