# MUSB removal contracts across platform and DMA backends

4 October 2026, Pacific/Auckland. NEO-106.

Removing the core IRQ action before releasing backend resources is a necessary
lifetime boundary, but it is not a complete MUSB shutdown protocol. Every
backend still requires accessible controller state through endpoint teardown;
several have independent timers, DMA completions, role callbacks or parent
IRQs. Runtime-PM retirement also has to precede the resource release needed by
its callbacks. The pinned backends contain concrete exceptions that prevent
certifying one generic reordering as sufficient.

This is read-only implementation research for
[work/musb-removal-lifetime](https://github.com/michaelishri/GameShellNeo/tree/work/musb-removal-lifetime),
starting at `666965f`. It complements [report 139](139-musb-teardown-power-audit.md).
No code, build, simulation, device or ticket operation was performed for this
report. Findings establish source dependencies, not observed hardware faults.

## Scope and source identity

The audit covers all nine platform glue objects and four DMA objects enumerated
by the pinned [MUSB Makefile][makefile]: OMAP2430, DSPS, TUSB6010, DA8xx,
UX500, JZ4740, Sunxi, MediaTek and PolarFire SoC; Inventra, TUSB/OMAP, UX500 and
CPPI41 DMA. PIO is included as the absence of a DMA controller, not another
callback provider. Selected DMA-engine providers, role-switch, notifier, PM
and driver-core code were followed where they own a synchronization contract.
This does not qualify every possible external PHY or DMA provider selected by
board data.

The authoritative local input remains Linux 6.18.54 plus patches 0001–0026,
0029 and 0030 in the callback-lifetime worktree's shared cache:

```text
.local/worktrees/musb-callback-lifetime/.local/build/musb-sleep-tests/
  .sources/source-678e8b9cc728a438bd7d779d8d352f049da83c48d8b89ddef3214cf4b33aed68/source
```

Recorded source-tree SHA-256:
`1e581a1d5ac1eb7873ea81bb549989f3371aee90ee7866c22119f3bed74acd1f`.
The archive/patch identity and limitations are in report 139. Public stable-tree
links below identify the owning files; the local patched source is authoritative
for the candidate. This audit did not mutate or freshly fingerprint that cache.

## Shared core obligations

`musb_remove()` currently unregisters host/gadget clients before platform exit,
but frees its core IRQ only afterwards, in `musb_free()`. It also destroys DMA
after platform exit. The probe `fail3` path destroys DMA before releasing the
core IRQ. Both orders are material: a still-installed handler may dereference
hardware or DMA state after its owner has released it. Sources:
[musb_core.c][core], `musb_remove()`, `musb_free()`, `musb_init_controller()`.

The client calls cannot be treated as software-only cleanup:

- Gadget unbind can synchronously disconnect ECM and disable endpoints before
  reaching `musb_gadget_stop()`. `musb_gadget_disable()` writes endpoint/core
  registers; `nuke()` aborts/releases DMA and gives back requests. Completion
  callbacks run with `musb->lock` temporarily released. Source:
  [musb_gadget.c][gadget], disable/nuke/giveback; report 139's UDC/ECM call chain.
- `usb_remove_hcd()` disconnects devices and drains endpoint URBs before HCD
  stop. MUSB unlink/disable reaches FIFO/CSR writes, DMA abort and giveback.
  The HCD stop callback calls `musb_stop()`. Source: [musb_host.c][host],
  `musb_urb_dequeue()`, `musb_h_disable()`, `musb_cleanup_urb()`, `musb_h_stop()`;
  [USB HCD core][hcd], `usb_remove_hcd()`, `usb_hcd_flush_endpoint()`.
- `musb_dma_completion()` enters the host/gadget endpoint handlers under the
  controller lock. Independent DMA callbacks therefore need the same controller,
  endpoint, request and role state as the core IRQ. Source: [core][core],
  `musb_dma_completion()`.

Closing patch 0030's function-driver notification gate does not retire these
request completions or controller-state users. Likewise, HCD root-hub timer
retirement does not retire `musb->otg_timer`, backend `musb->dev_timer` or DMA
timers. The core creates its controller IRQ itself with `IRQF_SHARED` and calls
`usb_add_hcd(hcd, 0, 0)`, so HCD removal does not free that action.
[Core][core], [host][host], host setup; [report 137](137-musb-gadget-callback-lifetime.md).

## Platform backend matrix

Each row names the functions that own its resource and producer boundaries.

| Backend | Resources that cleanup still needs | Independent producers and source-level conflicts |
| --- | --- | --- |
| **Sunxi** | `sunxi_musb_init()` owns controller clock/reset, generic PHY initialization and a retained child PM hold. Exit drops the hold, drains glue work once, exits PHY, asserts reset and disables clock. DMA creation returns `NULL`. | `sunxi_musb_interrupt()` reads registers without an enabled/removing gate. `sunxi_musb_host_notifier()` queues parent-owned glue work; set-VBUS/mode/recover also queue it. `.disable` only clears `ENABLED`. Raw extcon unregister lacks an in-flight callback barrier, and the PHY detector emits events after dropping its mutex. Child-only unbind leaves the parent-owned notifier registration unless explicitly retired. [sunxi.c][sunxi], named functions; report 139. |
| **DA8xx** | Init enables clock, acquires legacy PHY, initializes/powers generic PHY and configures wrapper MMIO. Exit deletes `dev_timer`, powers off/exits PHY, disables clock and puts legacy PHY. CPPI41 completion's `da8xx_dma_controller_callback()` writes wrapper EOI. | `otg_timer()` reads registers before taking `musb->lock`, may rearm itself and write wrapper state. Core interrupt and `.try_idle` can rearm it. `.disable` masks wrapper interrupts but does not retire the timer. Core IRQ and CPPI41 callback must finish while wrapper/clock resources remain available. [da8xx.c][da8xx], init/exit/disable/interrupt/timer and DMA callback. |
| **DSPS** | Init maps wrapper registers, initializes/powers optional generic PHY and starts `dev_timer`; exit deletes the timer, exits PHY and removes debugfs. CPPI41 callback accesses the parent `usbss_base` mapping. | `otg_timer()` gets child PM and queues `dsps_check_status()` through `pending_list`; status processing can rearm the timer. An optional **parent-owned VBUS IRQ** calls `dsps_mod_timer()` independently of the core IRQ. `.disable` calls `timer_delete_sync()` although gadget stop invokes it while holding `musb->lock`, which the timer also takes. Parent remove unregisters child before devres frees the VBUS IRQ. [musb_dsps.c][dsps], timer/disable/VBUS IRQ/init/exit/remove/DMA callback. |
| **TUSB6010** | Init powers the chip via GPIO, maps its synchronous window and installs custom accessors/FIFO offsets. Exit drains `dev_timer`, clears global `the_musb`, powers the chip off, unmaps the sync window and puts PHY. TUSB DMA completion/release accesses those windows. | Hardware OTG events arrive through the core action; idle `dev_timer` changes chip clock/power state under `musb->lock`. `.disable` masks wrapper/core/DMA/GPIO interrupts but only deletes the timer non-synchronously. `tusb_draw_power()` uses global `the_musb` through the PHY `set_power` hook, with no NULL/admission guard in that function. Clearing the global does not itself drain a caller or revoke the hook. [tusb6010.c][tusb], init/exit/disable/`musb_do_idle()`/draw-power. |
| **OMAP2430** | Exit accesses `OTG_FORCESTDBY`, powers off/exits generic PHY, clears `musb->phy`, then cancels mailbox work. Parent runtime suspend/resume also accesses child MMIO and generic PHY. | `omap2430_musb_mailbox()` schedules parent-owned work; worker gets child PM, changes mode/VBUS, touches registers and issues PHY notifications. Core's global `musb_phy_callback` is cleared only after platform exit; its documented contract requires the PHY producer disabled while registering/unregistering. Cancel-after-PHY-exit leaves worker/resource ordering unproven. Core IRQ free and child PM disable do not retire mailbox admission or parent PM. [omap2430.c][omap], mailbox/init/exit/runtime callbacks; [core][core], `musb_mailbox()`. |
| **UX500** | Parent probe enables clock; parent remove keeps it enabled until after child unregister. Child init gets legacy PHY and registers an atomic notifier; exit unregisters it and puts PHY. UX500 DMA callbacks independently reach core state. | `musb_otg_notifications()` may directly change VBUS/controller state, independently of core IRQ. `usb_unregister_notifier()` uses atomic-notifier unregister, which calls `synchronize_rcu()`; this provides a real reader drain and must not be treated like Sunxi's raw extcon chain. No private MUSB timer/work is introduced here. [ux500.c][ux500], notifier/init/exit/remove; [USB PHY header][usb-phy], notifier wrappers; [notifier.c][notifier], atomic unregister. |
| **JZ4740** | Parent clock remains on until child removal completes. Child init powers generic PHY if present and registers a role switch; exit unregisters role switch then powers off/exits PHY. | `jz4740_musb_interrupt()` invokes Inventra DMA handling through `musb->dma_controller` before taking its own controller-lock section. Thus core IRQ must be drained before DMA object free. Role callback dereferences `glue->musb->xceiv` and emits atomic PHY notifications. Role-switch unregister has no explicit in-flight setter drain; see below. [jz4740.c][jz], interrupt/role-set/init/exit/remove. |
| **MediaTek** | Parent probe acquires PM on the **parent** and enables clocks. Child exit powers off/exits PHY and disables those clocks, then performs a PM put/disable on the **child**. | Main IRQ multiplexes USB and Inventra DMA. Its L1 status/mask reads occur outside the controller lock; it calls DMA handling on the retained pointer. Generic core masks do not mask `USB_L1INTM`'s DMA source, and there is no `.disable` hook. OTG role setters directly access controller MMIO/PHY. Parent/child PM ownership and child-only rebind need correction before generic PM reordering can be claimed complete. [mediatek.c][mtk], interrupt/role-set/init/exit/probe/remove. |
| **PolarFire SoC (MPFS)** | Child init gets PHY and initializes `dev_timer`; exit deletes it. Dedicated Inventra DMA may be present. Parent owns controller clock. | Core interrupt, `.try_idle` and the timer itself can rearm `dev_timer`; timer reads MMIO before taking `musb->lock`. **Parent `mpfs_remove()` disables its clock before unregistering the child.** Therefore moving child core IRQ free earlier does not restore the resource prerequisite for host/gadget/IRQ cleanup. This needs parent ordering work. [mpfs.c][mpfs], timer/interrupt/init/exit/remove. |

These are dependencies visible in the pinned source, not statements that every
listed event can occur in every role or board configuration. In particular,
CPI remains fixed peripheral and PIO.

Role-switch synchronization is a separate limitation. In
[drivers/usb/roles/class.c][roles], `usb_role_switch_set_role()` checks
`registered` **before** taking `sw->lock`; unregister sets it false and calls
`device_unregister()` without taking/draining that lock. An already-admitted
setter, or a caller that passed the check before waiting for the mutex, is not
excluded by that sequence alone. MTK/JZ backend memory/resource retirement
therefore needs its consumer/lifetime synchronization established; merely
moving unregister earlier is not a complete proof.

## DMA ownership and completion matrix

The MUSB DMA abstraction supplies abort/release hooks but no general terminal
quiesce-and-drain callback. `musb_stop()` even retains a FIXME about disabling
DMA. Destruction cannot replace proving all active transfers and callbacks are
retired. Source: [musb_dma.h][dma-header], `struct dma_controller`;
[core][core], `musb_stop()`.

| DMA backend | Completion path | Abort/destruction and required ordering |
| --- | --- | --- |
| **Inventra HSDMA** | `dma_controller_irq()` takes `musb->lock`, reads DMA/endpoint registers and calls `musb_dma_completion()`. OMAP/MPFS creation requests a separate DMA IRQ. JZ/MTK use `create_noirq()` and call it from the main IRQ. | Busy-channel abort clears endpoint DMA bits and DMA control/address/count registers. `dma_controller_stop()` only releases software channel bookkeeping; it does **not** call abort. Destroy releases any dedicated IRQ then frees the object. Therefore channels must already be quiesced; main-IRQ variants must retire the main action before object free, dedicated-IRQ variants before backend resource release. [musbhsdma.c][hsdma], abort/stop/create/create-noirq/destroy. |
| **CPPI41** | DMA-engine callback acknowledges DA8xx EOI or DSPS USBSS first, then takes `musb->lock` for normal completion. It can complete/reprogram transfers or arm `early_tx`; that hrtimer polls FIFO MMIO under the same lock and can restart itself. | Abort removes early-TX membership, writes core/wrapper registers and repeatedly calls DMA-engine termination on `-EAGAIN`. Destroy cancels `early_tx` **before** releasing DMA channels. A live DMA callback can rearm the timer unless earlier transfer/callback retirement has been established. Core IRQ removal does not retire the independent DMA provider. Wrapper/USBSS resources must remain available even for the aborted callback, because acknowledgment precedes its abort-result check. [musb_cppi41.c][cppi], callback/abort/recheck/destroy; DA8xx/DSPS DMA callbacks. |
| **UX500** | `ux500_dma_callback()` takes `musb->lock` and calls core completion; DMA-engine callback lifetime is independent of the main IRQ. | Abort writes endpoint CSRs and calls deprecated `dmaengine_terminate_all()`. Channel release clears software allocation state; controller stop releases DMA-engine channels before freeing its object. The actual DMA provider's callback-drain behavior matters; core free_irq is not that drain. [ux500_dma.c][uxdma], callback/abort/release/stop/destroy. |
| **TUSB/OMAP** | `tusb_omap_dma_cb()` takes `musb->lock`, accesses TUSB endpoint/FIFO windows, may perform residual PIO, and completes the MUSB transfer. | Abort calls `dmaengine_terminate_all()`. Channel release calls **`dmaengine_terminate_sync()`**, then touches TUSB endpoint-map registers. Gadget `nuke()` invokes release while holding the same controller lock needed by the callback: a synchronous-wait/lock conflict. Destroy frees channel/private callback data **before** releasing the DMA-engine channels that may synchronize callbacks. It cannot serve as a substitute for earlier callback retirement. [tusb6010_omap.c][tusbdma], callback/abort/release/destroy; [gadget][gadget], `nuke()`. |

The pinned DMA-engine implementation is more specific than an assumption that
`dma_release_channel()` never waits. Its `dma_chan_put()` calls
`dmaengine_synchronize()` before `device_free_chan_resources` on the last
reference. However `dmaengine_synchronize()` only invokes a provider hook if
present. OMAP implements it using `vchan_synchronize()`; the inspected CPPI41
and STE DMA40 providers do not install that hook. Source:
[drivers/dma/dmaengine.c][dmaengine], release/put;
[include/linux/dmaengine.h][dma-api], synchronization helpers;
[omap-dma.c][omapdma], `omap_dma_synchronize()` and device operations;
[cppi41.c][cppi-provider] and [ste_dma40.c][dma40], device operations.

CPPI41 is also a concrete exception to treating cancellation as passive.
Its provider's `cppi41_irq()` invokes callbacks directly. `cppi41_stop_chan()`
polls teardown descriptor queues through `cppi41_tear_down_chan()`, which
invokes the client's callback synchronously with `DMA_TRANS_ABORTED`. MUSB's
aborted branch avoids reacquiring `musb->lock` but still performs the platform
acknowledgment first. This polling loop has no source dependency on delivery of
the main MUSB IRQ; it does require live DMA-provider and wrapper hardware.
Provider channel-free merely checks PM/pending state and is not a replacement
for active transfer termination. [CPPI41 provider][cppi-provider], named functions;
[MUSB CPPI41][cppi], callback/abort.

The API distinguishes stopping transfer admission from synchronizing callbacks.
Synchronous DMA termination must run in non-atomic context and cannot be called
from its own completion callback. Those waits also cannot safely retain a lock
needed by an already-running callback. [Official DMA-engine guide][dma-doc];
[pinned DMA header][dma-api]. No general DMA-safe failed-power path is established
by this report.

## Early core IRQ release: what is supported

The source establishes the following necessary conditions, rather than a
universal linear sequence:

1. Preserve controller/PHY/wrapper accessibility through the existing client
   cleanup and DMA abort/release operations. Unregistering clients can issue
   their last endpoint operations and completions.
2. Quiesce all sources assigned to the core action, then remove/drain that
   action before freeing objects or backend resources it may access. The
   JZ/MTK DMA pointer creates a strict core-IRQ-before-DMA-object-free dependency.
3. Retire independent DMA callbacks, backend timers, parent IRQs, role/PHY
   notifications and mailbox/glue work before their state/resources disappear.
   This remains necessary even after core IRQ free.
4. Close producer admission or use permanent work/timer shutdown before final
   drains. Release the controller lock before waits for IRQs, timers, work,
   notifications or DMA callbacks that need that lock.

`free_irq()` removes the selected action and waits for running handlers;
`synchronize_irq()` alone permits future dispatch. On shared IRQs the device's
own source must be quiesced without disabling unrelated users. [IRQ guide][irq-doc].
The core's `musb_disable_interrupts()` only handles Mentor USB/TX/RX masks and
pending status. It does not establish MTK L1/DMA masking, independent DMA IRQ
shutdown or a backend notifier barrier. Source: [core][core], interrupt masking;
[mtk][mtk], init/interrupt/ops.

The defensible *candidate window* for an early core IRQ release is after
client cleanup while hardware resources still exist, and before DMA object or
backend teardown. Its sufficiency still depends on the source-mask and
independent-producer conditions above. Releasing it before client cleanup has
not been proven safe for every endpoint/DMA contract. Releasing it only before
platform exit but after freeing a JZ/MTK DMA object is too late for that object.

Wake ownership must be handled while the valid IRQ number remains available.
Patch 0026's `musb_cleanup_wakeup()` uses `nIrq`; an early action release must
not erase that number before wake cleanup or cause a second `free_irq()` in
`musb_free()`. A failed wake disarm retains its existing unresolved terminal
ownership limit; action removal is not evidence that the IRQ wake reference
was released. [Core][core], wake helpers; [report 131](131-musb-wake-irq-ownership.md).

## Work and timer closure

`disable_delayed_work_sync()` prevents later queues while disabled; ordinary
cancellation only drains the instances it can exclude from concurrent enqueue.
`timer_shutdown_sync()` additionally prevents timer rearm. Neither operation
may be applied to an uninitialized object, nor awaited under a lock the worker
or timer needs. Source: pinned `kernel/workqueue.c`, disable/cancel helpers;
`kernel/time/timer.c`, shutdown/delete helpers;
[official workqueue][work-doc] and [timer][timer-doc] documentation.

For terminal core removal, the four delayed works and `otg_timer` require
explicit stage ownership. Their producers include client endpoint operations,
core IRQ, runtime resume and backend callbacks. Closing `irq_work` has a PM
bookkeeping consequence: `musb_pm_runtime_check_session()` owns an additional
get when `musb->session` becomes set, and releases it when the session clears.
No separate removal-side session release exists. Once that worker is retired,
terminal cleanup must account for any hold it owned, not assume disabling PM
balances it. [Core][core], work initialization, session checker, remove.

Backend `dev_timer` is distinct from the core OTG timer and is initialized only
by DA8xx, DSPS, TUSB and MPFS. Even `timer_shutdown_sync(dev_timer)` would not
make DSPS's parent VBUS IRQ safe after the `musb` allocation is freed: the
handler still obtains/dereferences the child pointer before attempting the
ignored rearm. Likewise, disabling Sunxi/OMAP work prevents execution but does
not make a notifier/mailbox caller safe after its work-owner memory is gone.
Backend producer lifetime must precede owner release. Sources: the backend
matrix's timer/VBUS/mailbox functions.

Final shutdown belongs to terminal instance teardown, not ordinary gadget stop
or system sleep, where restart is required. A fresh child allocation naturally
receives fresh core timers/work; parent-owned workers, registrations and flags
may survive child unbind and need an explicit rebind contract. Existing core
resume-list nodes are not workqueue items: disabling delayed work or PM does
not cancel callbacks or retire their raw request data. [Core][core],
`musb_queue_resume_work()`, `musb_run_resume_work()`; [gadget][gadget], queue/dequeue.

## Runtime-PM retirement: supported boundary and conflicts

The core runtime callbacks save/restore registers and run pending resume work.
`pm_runtime_disable()` can service a pending resume before it increments the
disable depth, then waits for outstanding PM activity. `pm_runtime_barrier()`
may also resume and only supplies a barrier, not permanent callback admission
closure. Therefore these operations need to complete while the hardware,
backend and resume-callback data they can use remain valid, and without the
controller/list locks. [Core][core], runtime callbacks;
[drivers/base/power/runtime.c][rpm], disable/barrier; [runtime-PM guide][rpm-doc].

For a powered path, a successfully acquired temporary runtime reference is the
defensible prerequisite for PM retirement before platform exit. The pinned
`rpm_resume()` permits a positive success result for a disabled device whose
current and saved state are both active. Thus later nested gets in existing
cleanup are not inherently forbidden by early disable, provided physical
resource and parent ownership remain valid. This is a helper contract, not
proof that all backends honor those prerequisites.

Specific remaining obligations are:

- **Sunxi:** its backend-held child reference is independent of the temporary
  core and possible session holds. Disable must not be mistaken for balancing
  any of them; exit's put still releases the backend's own count.
- **OMAP:** parent runtime callbacks access child MMIO/PHY. Retiring child PM
  does not itself retire the parent or close mailbox work. The child/parent
  active relation and explicit resource holds must remain valid through the
  final parent-dependent operation.
- **MediaTek:** parent probe gets/enables PM on `glue->dev`, while child backend
  exit puts/disables `musb->controller`. These are different devices. An early
  core disable adds another disable-depth transition unless that existing
  ownership is reconciled; parent clock/PM lifetime is also tied to child exit.
- **DSPS:** its timer can request child PM and queue deferred status callbacks.
  A core PM barrier does not close its timer/VBUS-IRQ producer or invalidate
  `pending_list` entries already created.
- **Failure and rebind:** `pm_runtime_get_sync()` increments on error; the newer
  get helper balances failure internally. `pm_runtime_disable()` and
  `pm_runtime_reinit()` do not reset usage count. Leaked temporary, backend or
  session references can therefore outlive a child-only unbind. Clearing
  `musb` software fields is not reference accounting.

Sources: the corresponding backend init/exit functions; [PM header][pm-header],
get helpers; [runtime.c][rpm], `rpm_resume()`, disable/reinit. The driver core's
temporary unbind get is put before invoking remove, so it supplies no implicit
child hold across `musb_remove()`; parent unbind holds are on the parent.
[drivers/base/dd.c][dd], `__device_release_driver()`.

A failed runtime acquisition remains a separate recovery design. Freezing PM
does not establish accessible registers, complete endpoint cleanup or retire
raw request data. In particular, a pending resume that runs during disable
must not be allowed to restart a request whose function driver has already
cancelled/freed it. No early-disable proposal here establishes failed-power
teardown safety.

## Partial initialization and rebind ledger

The common failure labels do not correspond to one fully initialized object.
The necessary ownership ledger follows [core][core], `allocate_instance()` and
`musb_init_controller()`:

| Stage reached | Resources that may exist | Cleanup constraint |
| --- | --- | --- |
| Allocation only | Core memory, list heads, host allocation, locks, invalid `nIrq` | Core delayed work, core OTG timer, UDC and backend resources may not be initialized. |
| Backend init returned error | Backend-specific partial acquisition | Core jumps to `fail1`, without calling platform exit. Backend init must unwind its own partial state; indiscriminate core timer/work cleanup is invalid. |
| Backend init succeeded; missing ISR/DMA ops or failed initial PM get | Backend PHY/clock, backend timer/work/notifier; possibly global PHY callback | `fail2` exits platform, but the three core delayed works and core OTG timer are not initialized yet. Patch 0029 disables PM on its own failed-get path before exit. |
| Core PHY/DMA setup | Legacy PHY initialized; DMA creation may return valid controller, `NULL`, or `ERR_PTR` | DMA can already own a separate IRQ before core work/timer setup. Error-pointer handling must not enter destroy; `NULL` means PIO fallback. |
| `musb_core_init()` failed | Three core delayed works initialized | Goes to `fail3` before `timer_setup(otg_timer)`: unconditional OTG shutdown here is invalid without earlier initialization or a stage flag. |
| Core IRQ/wake setup | Core OTG timer initialized; action exists only after successful request | `nIrq` records successful action ownership. Wake initialization can then fail. DMA/core action retirement must precede their owners' release. |
| Host/UDC registration and platform mode setup | HCD/UDC may be registered and clients may have bound | `port_mode` alone does not prove registration success. A mode-setting error reaches `fail3` after successful role setup, without generic role cleanup. DA8xx propagates `phy_set_mode()` error, so this boundary is material. |

The OTG branch explicitly removes the host if gadget setup fails, but that does
not cover a later platform-mode error. Gadget work and callback wait state are
initialized in gadget setup, not allocation. Any shared finalizer must preserve
the distinctions above and prevent double host/UDC removal, work operations on
uninitialized storage, or IRQ release without ownership.

Backend-local partial failure/rebind also needs explicit coverage:

- DA8xx acquires legacy PHY before generic-PHY init/power can fail; its local
  error labels disable the clock but do not put that acquired legacy PHY.
  UX500 notifier-registration failure likewise returns after acquiring PHY
  without its exit-side put. These are source-visible ownership gaps, not
  reasons to call the full backend exit after every failed init.
- DSPS arms its timer during successful init before core runtime setup. Its
  final debugfs helper always returns zero in this source; it is not a failing
  tail requiring speculative unwind. Early later core failures still need to
  retire this already-initialized backend timer and any deferred status work.
- Sunxi notifier ownership is on the surviving parent, while child init
  registers it. Unbind/rebind needs registration and detector/work lifetime
  accounting, including PHY-init failure after registration.
- MTK child exit disables parent-acquired clocks, while child init does not
  re-enable them. Child-only rebind cannot be justified by the normal parent
  probe sequence; the PM-device mismatch above compounds this lifetime issue.
- TUSB DMA uses a global channel-pointer array. Destroy frees its entries
  without clearing them; a later partially failed create can encounter stale
  slots while its generic cleanup loops over the whole array. UX500 DMA's
  allocation-failure cleanup similarly loops every channel although later
  channels' `private_data` may not yet have been initialized. These require
  backend allocation-stage review before reusing a generic destroy path.

Sources: [DA8xx][da8xx] init error labels; [UX500][ux500] init;
[DSPS][dsps] init/debugfs; [Sunxi][sunxi] init;
[MTK][mtk] init/exit/probe; [TUSB DMA][tusbdma] create/destroy and global pool;
[UX500 DMA][uxdma], controller start/stop and channel release.

## Sunxi extcon callback retirement options

The required barrier starts before notifier selection, not at callback entry.
`notifier_call_chain()` fetches `nb` and caches `next_nb` before invoking a
callback. Ordinary `extcon_unregister_notifier()` unlinks under `edev->lock`
without waiting for that traversal. A callback-local count cannot protect a
callback whose block was already selected but whose body has not started.
The pinned `extcon_sync()` has exactly two raw-chain dispatch sites: the cable
chain and the all-cables chain. Source: [notifier.c][notifier], traversal and
raw unregister; [extcon.c][extcon], sync/register/unregister.

A **provider-scoped dispatch mutex** could cover the Allwinner detector's two
`extcon_set_state_sync()` calls and an explicit unregister helper, provided the
helper takes it outside `phy->mutex`. This would serialize selection against
unlink for that provider. It cannot be assumed to cover the extcon used by
every Sunxi controller: `sunxi_musb_probe()` independently resolves the extcon
phandle and the named generic PHY. Neither the code nor the binding requires
their providers to be identical. Hardcoding that association would add a probe
restriction. All event emitters would need to use the mutex, and callbacks
must not reenter a path that waits for the same mutex. Source:
[Sunxi][sunxi], probe; [Allwinner PHY][sun4i-phy], detector;
[Sunxi binding][sunxi-binding]. This is a design option, not an implemented or
qualified interface.

A **dedicated per-extcon SRCU domain around the existing raw dispatches** is a
more general candidate. It would preserve the raw notifier API and callback
context, with an opt-in process-context synchronous unregister operation:

1. Enter the domain before reading either notifier-chain head; keep both raw
   dispatches inside it and leave it after the last dispatch.
2. Unlink the requested block under the existing extcon spinlock, drop that
   lock, then wait for that domain's grace period. A previously selected block
   remains inside a reader until its dispatch completes.
3. Preserve existing ordinary unregister semantics. Use explicit child-owned
   registration for Sunxi, and synchronous removal before the final glue-work
   drain and PHY/resource release, including PHY-init error unwind. Prevent
   concurrent re-registration or mixed ownership of that same notifier block.

This construction uses `srcu_read_lock()` rather than converting the chains to
`srcu_notifier_head`. The latter's documented call-chain context is process
context; extcon explicitly accommodates interrupt callers. In contrast, the
pinned SRCU read-lock API permits matching read lock/unlock in the same IRQ
context. The proposed envelope adds no sleeping reader-side operation and
does not relax a callback's original context constraints. Source:
[notifier header][notifier-header], chain-context contracts;
[SRCU header][srcu-header], `srcu_read_lock()`;
[extcon.c][extcon], `extcon_sync()`.

The source contracts support that selection-to-return barrier in principle,
with the following implementation obligations still requiring review:

- The synchronous operation must run in process context, outside the same
  extcon domain's callbacks and outside locks those callbacks may need. This
  applies even when removing a different block or cable ID. Cross-domain waits
  must not form a cycle. SRCU expressly forbids direct or indirect waits on
  one's own domain. A single per-device domain can wait for unrelated cable
  callbacks; that is a consequence to document, not a timing guarantee.
- Registration ownership and the return-value contract must be explicit. A
  failed unlink must not silently promise a successful removal/drain. In
  particular, `-ENOENT` after another unsynchronized unregister does not by
  itself prove no callback retained the block. Sunxi should track its own
  successful registration and retire it exactly once before freeing it.
- Initialize the domain before exposing a successfully allocated extcon
  object, propagate initialization failure, select the required SRCU support,
  and pair initialization with free on registered, never-registered and
  failed-registration paths. Preserve the existing NULL-safe free behavior.
  Review devres allocation/unregistration/free order and child-only rebind.
- The caller must keep the extcon provider alive through unlink and the wait.
  `cleanup_srcu_struct()` is not a consumer or provider drain: it warns and
  declines cleanup when readers are active. `extcon_dev_unregister()` frees
  the cable notifier-head array **before** `extcon_dev_free()`. A domain cleanup
  added only to free cannot make a concurrent provider unregister or dispatch
  safe. Providers still must stop their own event producers before destroying
  extcon state. Nor would an envelope ending after notifier dispatch protect
  the later sysfs/uevent work in `extcon_sync()` from provider destruction.

Sources: [SRCU implementation][srcu-tree], `synchronize_srcu()` and
`cleanup_srcu_struct()`; [extcon.c][extcon], allocation/free/register/unregister;
[extcon devres][extcon-devres], managed release; [extcon Kconfig][extcon-kconfig].
No framework or driver change was made for this report.

Neither option by itself retires the Allwinner detector's own hardware access.
The detector drops `phy0->mutex` before dispatch, and an OTG force-session-end
path can reacquire it afterwards without rechecking `phy0_init`; passby and
optional dual-route updates follow outside that mutex. An already-admitted
detector therefore needs a separate resource-lifetime argument. Conversely,
waiting for the entire detector from generic `phy_exit()` can deadlock because
the generic PHY core holds the same mutex that the detector can acquire.
These conditional paths are not a claim that fixed-peripheral CPI executes
them. Source: [Allwinner PHY][sun4i-phy], detector/exit;
[generic PHY core][phy-core], `phy_exit()`. The proposed SRCU boundary addresses
the consumer's selected-callback interval without depending on that provider
association or claiming to solve the provider's complete teardown.

## What a candidate can and cannot claim

A bounded core change can establish action ownership and final core
work/OTG-timer retirement with explicit initialization/registration state.
It can also move child PM retirement into a window where its own resources are
still valid and account for its own references. Those are useful, reviewable
improvements. They cannot alone establish backend producer quiescence, DMA
callback lifetime, shared-source masking, parent clock/PM correctness or
failed-power recovery across all nine backends.

Before claiming generic removal safety, the implementation/evidence needs to
resolve the matrix's conflicts or explicitly bound its claim. Targeted checks
should exercise both Inventra IRQ topologies, independent DMA callbacks and
timer rearm, DSPS VBUS IRQ after child retirement, OMAP mailbox/parent PM,
role setters already admitted at unregister, backend init failures, mode error
after role registration, and same-child rebind with counted PM ownership.
For the proposed extcon boundary, include selection before callback entry,
IRQ-context dispatch, both chains, probe failure, child rebind, and a provider
that differs from the generic PHY; separately establish provider lifetime.
Waiting tests must prove lock release, not merely successful returns from
stubs. CPI PIO qualification does not discharge those other backend contracts.

## Primary-source references

All function claims above were read in the pinned local source. The official
documentation supplies API contracts; public stable-tree links are navigation
to the unpatched owning files.

[makefile]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/Makefile?h=v6.18.54
[core]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_core.c?h=v6.18.54
[gadget]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_gadget.c?h=v6.18.54
[host]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_host.c?h=v6.18.54
[hcd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/core/hcd.c?h=v6.18.54
[sunxi]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/sunxi.c?h=v6.18.54
[da8xx]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/da8xx.c?h=v6.18.54
[dsps]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_dsps.c?h=v6.18.54
[tusb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/tusb6010.c?h=v6.18.54
[omap]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/omap2430.c?h=v6.18.54
[ux500]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/ux500.c?h=v6.18.54
[jz]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/jz4740.c?h=v6.18.54
[mtk]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/mediatek.c?h=v6.18.54
[mpfs]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/mpfs.c?h=v6.18.54
[usb-phy]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/usb/phy.h?h=v6.18.54
[notifier]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/notifier.c?h=v6.18.54
[notifier-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/notifier.h?h=v6.18.54
[srcu-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/srcu.h?h=v6.18.54
[srcu-tree]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/rcu/srcutree.c?h=v6.18.54
[extcon]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/extcon/extcon.c?h=v6.18.54
[extcon-devres]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/extcon/devres.c?h=v6.18.54
[extcon-kconfig]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/extcon/Kconfig?h=v6.18.54
[sun4i-phy]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/phy/allwinner/phy-sun4i-usb.c?h=v6.18.54
[phy-core]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/phy/phy-core.c?h=v6.18.54
[sunxi-binding]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/Documentation/devicetree/bindings/usb/allwinner,sun4i-a10-musb.yaml?h=v6.18.54
[roles]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/roles/class.c?h=v6.18.54
[dma-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_dma.h?h=v6.18.54
[hsdma]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musbhsdma.c?h=v6.18.54
[cppi]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_cppi41.c?h=v6.18.54
[uxdma]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/ux500_dma.c?h=v6.18.54
[tusbdma]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/tusb6010_omap.c?h=v6.18.54
[dmaengine]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/dma/dmaengine.c?h=v6.18.54
[dma-api]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/dmaengine.h?h=v6.18.54
[omapdma]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/dma/ti/omap-dma.c?h=v6.18.54
[cppi-provider]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/dma/ti/cppi41.c?h=v6.18.54
[dma40]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/dma/ste_dma40.c?h=v6.18.54
[rpm]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/power/runtime.c?h=v6.18.54
[pm-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/pm_runtime.h?h=v6.18.54
[dd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/dd.c?h=v6.18.54
[dma-doc]: https://docs.kernel.org/driver-api/dmaengine/client.html
[irq-doc]: https://docs.kernel.org/core-api/genericirq.html#c.free_irq
[rpm-doc]: https://docs.kernel.org/power/runtime_pm.html
[work-doc]: https://docs.kernel.org/core-api/workqueue.html#c.disable_delayed_work_sync
[timer-doc]: https://docs.kernel.org/driver-api/basics.html#c.timer_shutdown_sync
