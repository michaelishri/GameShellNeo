# MUSB teardown power and producer lifetime audit

4 October 2026, Pacific/Auckland. NEO-105.

The pinned teardown paths require more than checking the return from a runtime
PM get. Gadget disconnect can disable endpoints before `musb_gadget_stop()` is
called; platform remove can requeue work after cancelling it; and Sunxi releases
PHY/clock resources before the core removes its shared IRQ handler. These are
source-order findings. They do not establish that the GameShell has encountered
failed-power teardown, inaccessible-register faults or a particular race.

This report audits Linux 6.18.54 with patches 0001–0026, 0029 and 0030, including
the generated overlay patch. It extends [report 136](136-musb-startup-runtime-pm.md),
[report 137](137-musb-gadget-callback-lifetime.md) and
[report 138](138-kernel-source-reuse.md). No driver patch, image, installed-device
configuration or staged diagnostic.18 is changed by this audit.
The source audit and bounded reproduction are complete; production teardown
remediation and its qualification remain open.

## Source identity and evidence limits

The authoritative input is the read-only source cache in the callback-lifetime
worktree:

```text
.local/worktrees/musb-callback-lifetime/.local/build/musb-sleep-tests/
  .sources/source-678e8b9cc728a438bd7d779d8d352f049da83c48d8b89ddef3214cf4b33aed68/source
```

The cache metadata records tree SHA-256
`1e581a1d5ac1eb7873ea81bb549989f3371aee90ee7866c22119f3bed74acd1f`.
The locked archive SHA-256 is
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`;
the upstream commit is `1b357ecb321392158d507b04672ffee57bfa071d`.
These are retained input identities, not a newly run complete-tree verification.
[The project source lock](../build/sources.lock.json) and the cache metadata
own those identities. Public upstream links below identify the owning files;
local patches remain authoritative where they differ. Kernel.org source-page
fetches were unavailable during this audit, so source conclusions were checked
against the pinned local files, not inferred from search snippets. Official
runtime-PM, IRQ, workqueue and timer documentation was also consulted.

## Does a PM failure mean inaccessible registers on CPI?

No. `pm_runtime_get_sync()` reports a PM operation result and increments the
usage count even on failure. `pm_runtime_resume_and_get()` balances a failed
acquisition internally. Neither helper measures register accessibility. The PM
framework distinguishes software PM state from physical power state, and uses
successful resume as an operational contract. A failed acquisition removes that
contract; it does not identify which clock, reset, bus or power-domain resource
failed. Sources: [include/linux/pm_runtime.h][rpm-header], `pm_runtime_get_sync()`,
`pm_runtime_get_active()`; [runtime-PM documentation][rpm-doc].

In the pinned `drivers/base/power/runtime.c`, `rpm_resume()` can return:

| Condition | Result and meaning |
| --- | --- |
| An earlier fatal runtime error remains recorded | `-EINVAL`; the current attempt may never call the driver. |
| Runtime PM is disabled | Usually `-EACCES`; the active/previously-active case instead returns positive success. |
| A required runtime-managed parent cannot become active | `-EBUSY`. |
| Runtime-resume callback fails | Its error, subject to `rpm_callback()` translating callback `-EACCES` to `-EAGAIN`. |
| Already active or completed resume | Positive or zero success, respectively; the newer get helper normalizes success to zero. |

Asynchronous/nowait calls have additional in-progress behavior. Arbitrary
injected `-EIO` or `-ETIMEDOUT` values therefore test a caller's failure handling;
they do not prove that the Sunxi driver produces those errors. In particular,
`musb_runtime_resume()` restores context, runs pending resume callbacks, logs
their errors, clears `is_runtime_suspended`, and returns **zero**. It contains no
Sunxi clock-enable operation. `musb_runtime_suspend()` saves context and marks
the state; it does not gate the Sunxi clock. Sources: [runtime.c][rpm-source],
`rpm_resume()`, `rpm_callback()`; [musb_core.c][core], runtime callbacks.

Sunxi enables its controller clock, deasserts its optional reset and initializes
the generic PHY in `sunxi_musb_init()`. It then retains a runtime-PM reference
specifically to prevent unsupported MUSB runtime suspend. Its platform driver
has no runtime-PM callbacks. Its exit explicitly drops the retained reference,
exits the PHY, asserts reset and disables the controller clock. The A33/R16
backend has the reset resource. The PHY provider similarly owns clocks/reset
in its init/exit; its power-on/off operations principally control VBUS supply.
Sources: [sunxi.c][sunxi], `sunxi_musb_init()`, `sunxi_musb_exit()`,
`sunxi_musb_driver`, `sun8i_a33_musb_cfg`; [phy-sun4i-usb.c][phy],
`sun4i_usb_phy_init()`, `sun4i_usb_phy_exit()`, power-on/off.

Thus an ordinary successfully initialized CPI instance has explicit backend
resource ownership and a retained PM hold. Establishing an actual failed get
requires identifying its PM-state, parent/domain or forced-failure origin.
Conversely, software ownership is not a hardware readback guarantee, and this
audit does not authorize generic MUSB to ignore PM errors on other backends.
CPU-idle behavior is not evidence of these device-resource failures.

## Gadget unbind reaches endpoints before stop

Normal UDC unbind proceeds as follows in [UDC core][udc],
`gadget_unbind_driver()`:

1. Disallow new connection and cancel UDC VBUS work.
2. Under `connect_lock`, disconnect the gadget, suppress/drain asynchronous
   callbacks, and conditionally synchronize `gadget->irq`.
3. Call the function driver's `unbind()` outside that lock.
4. Call `usb_gadget_udc_stop_locked()`, which invokes `udc_stop()` and clears
   `udc->started` without inspecting the integer return.
5. Clear class-driver ownership.

`usb_gadget_disconnect_locked()` is not only a pull-up request. For a connected,
started, non-deactivated gadget, it calls the controller's pull-up operation
and then the gadget driver's `disconnect()` synchronously. MUSB's pull-up
operation queues `gadget_work`; it does not acquire power synchronously.
That worker checks its own PM get, but failure there does not prevent the
synchronous function-driver disconnect or report failure through the earlier
pull-up return. Sources: [UDC core][udc], `usb_gadget_disconnect_locked()`;
[musb_gadget.c][gadget], `musb_gadget_pullup()`, `musb_gadget_work()`.

For this project's configfs ECM gadget, the concrete endpoint path is
`configfs_composite_disconnect()` → `composite_disconnect()` →
`__composite_disconnect()` → `reset_config()` → `ecm_disable()` →
`gether_disconnect()`/`usb_ep_disable()`. Enabled data and notification endpoints
reach `musb_gadget_disable()`, which selects an endpoint, writes interrupt-enable
and maximum-packet registers, calls `nuke()`, clears descriptors and queues
`irq_work`. Consequently these accesses can precede both callback suppression
and the unchecked get in gadget stop. Whether particular endpoints are enabled
depends on connection/configuration state. Sources:
[configfs.c][configfs], [composite.c][composite], [f_ecm.c][ecm],
[u_ether.c][ether], named functions; [musb_gadget.c][gadget],
`musb_gadget_disable()` and `nuke()`.

Patch 0030 supplies the requested asynchronous callback drain for suspend,
resume, disconnect, reset and setup. It preserves request completions, as UDC
requires. This closes notification admission before unbind; it does not promise
that endpoint cancellation, the earlier class-issued disconnect, controller
IRQs or register access have stopped. MUSB still does not publish a gadget IRQ
field; its callback count supplies the notification barrier described in
[report 137](137-musb-gadget-callback-lifetime.md).

`musb_gadget_stop()` itself ignores `pm_runtime_get_sync()` failure before HNP,
VBUS/PHY calls, `musb_stop()`, pull-up writes and logical detachment. HNP has
state-dependent register/callback behavior; `musb_stop()` masks controller
interrupts and writes `DEVCTL`. Returning immediately on failed get would leave
MUSB's driver pointer/connection state behind while UDC reports stopped and
unbind has already freed function state. Clearing just the pointer would still
leave the endpoint, DMA, timer and hardware obligations unresolved. Bind-error
cleanup has a different stop-before-unbind order; sysfs soft disconnect also
stops without the full unbind/suppression sequence. Sources: [gadget][gadget],
`musb_gadget_stop()`; [core][core], `musb_hnp_stop()`, `musb_stop()`;
[UDC core][udc], `gadget_bind_driver()`, `soft_connect_store()`.

## Platform remove, host cleanup and backend exit

The actual order in [musb_core.c][core], `musb_remove()`, is:

| Stage | Work performed and remaining access paths |
| --- | --- |
| Initial cancellation | Remove debugfs; cancel `irq_work`, `finish_resume_work`, `deassert_reset_work`. Host, gadget and controller IRQ producers still exist. |
| PM acquisition | Call unchecked `pm_runtime_get_sync()`. |
| Client removal | `musb_host_cleanup()` then `musb_gadget_cleanup()`. Endpoint cleanup may touch MMIO and enqueue work. Gadget cleanup does cancel `gadget_work` after unregister, covering pull-up work queued by unregister. |
| Controller masking | Platform disable; under controller lock, mask core interrupts and clear `DEVCTL`. Sunxi platform disable only clears `ENABLED`. |
| Wake/backend teardown | Clean up wake ownership, then platform exit. Sunxi drops its PM hold, cancels glue work, powers off/exits PHY, asserts reset, disables clock and releases any SRAM ownership. |
| Late core cleanup | Clear autosuspend use; put runtime PM synchronously; disable runtime PM; clear PHY callback; destroy DMA; shut down legacy USB PHY. |
| Final free | `musb_free()` removes the core IRQ action, then releases the HCD reference. Device-managed allocations/mappings are subsequently released by driver core. |

Host cleanup is not merely software unlinking. `usb_remove_hcd()` disconnects
the root hub and descendants before `usb_stop_hcd()` invokes `musb_h_stop()` /
`musb_stop()`. USB endpoint flushing reaches `musb_urb_dequeue()` and
`musb_cleanup_urb()`; endpoint disable can reach that cleanup too. It selects
endpoints, aborts DMA when present, flushes FIFOs, changes CSR state and completes
URBs. `usb_hcd_flush_endpoint()` waits for the queue to empty, so skipping the
completion side is not a safe failed-power alternative. Sources:
[hcd.c][hcd], `usb_remove_hcd()`, `usb_stop_hcd()`,
`usb_hcd_flush_endpoint()`; [hub.c][hub], `usb_disconnect()`;
[message.c][message], `usb_disable_device()`, `usb_disable_endpoint()`;
[musb_host.c][host], cleanup/dequeue/disable functions.

`musb_host_setup()` uses `usb_add_hcd(hcd, 0, 0)`: the MUSB core separately
requests its controller action with `IRQF_SHARED`. Therefore the HCD's optional
IRQ free does not retire this action. `sunxi_musb_interrupt()` unconditionally
reads/acknowledges controller status under `musb->lock`; it does not check
`ENABLED`, callback admission or a removing flag. Masking the controller does
not prevent an already-dispatched handler from reaching the lock later, or a
shared-line dispatch from another action. Backend exit occurs after the masking
lock is released and before `free_irq()`. The ordering lacks a barrier proving
no handler will access the backend after resource release. This is a source
contract gap; actual shared users or an observed late board interrupt have not
been established. Sources: [core][core], initialization/remove/free;
[host][host], `musb_host_setup()`; [sunxi][sunxi], interrupt handler.

`free_irq()` removes the selected action and waits for executing handlers;
shared users must be preserved and the device interrupt source must first be
quiesced. `synchronize_irq()` alone does not prevent future dispatch. Waiting
while holding the controller lock would deadlock a handler needing that lock.
[Official IRQ documentation][irq-doc].

Late PM cleanup is a separate register path. After backend exit drops its hold,
a final `pm_runtime_put_sync()` can run idle/suspend when the usage/state rules
permit; `musb_runtime_suspend()` then saves registers after the clock teardown.
Other references, including a session hold, can prevent that transition, so it
is not unconditional. `pm_runtime_disable()` can also process a pending resume
before disabling. A successful teardown design must establish PM callback
retirement while the resources those callbacks need still exist. Sources:
[core][core], remove/runtime callbacks; [runtime.c][rpm-source],
`__pm_runtime_idle()`, `rpm_idle()`, `__pm_runtime_disable()`.

The pinned driver core does not provide an implicit child-device hold across
this remove callback: `__device_release_driver()` takes a get, handles device
links, then performs its corresponding put **before** `device_remove()`.
`platform_remove()` adds no child PM get. A parent glue unbind reference belongs
to the parent device, not the child usage count. This removes one proposed
reason for dismissing the late-put boundary; it still does not establish the
complete live reference count or PM state. Sources: [dd.c][dd],
`__device_release_driver()`; [drivers/base/platform.c][platform], `platform_remove()`.

## Work, timer, request and DMA retirement

Cancellation is not a permanent admission gate. The workqueue guarantee depends
on excluding racing enqueues; `disable_work_sync()` and its delayed equivalent
also reject later queue attempts while disabled. A final timer can use
`timer_shutdown_sync()` to prevent rearming, with its documented locking rules.
These primitives exist in the pinned tree, but choosing one does not establish
that the rest of removal can function without that work.
[Workqueue documentation][work-doc], [timer documentation][timer-doc].

| Owner | Producers and teardown boundary |
| --- | --- |
| `irq_work` | Core interrupt handling, endpoint enable/disable and session polling queue it; session checking can requeue it. Remove cancels before client removal and before IRQ retirement, with no final cancellation or disabled admission. A worker that fails its get avoids MMIO but still dereferences its owner. |
| `finish_resume_work` | Resume interrupt and host port-resume handling can queue it. Its callback directly accesses `POWER` and the root hub. Initial removal cancellation precedes IRQ/host producer shutdown. |
| `deassert_reset_work` | Host port reset queues/requeues it. Its callback can access reset/PHY/controller state. Initial cancellation precedes HCD removal. |
| `gadget_work` | Pull-up requests queue it. Cleanup correctly cancels after UDC unregister; ordinary gadget stop does not itself provide a complete work/producer retirement protocol. |
| `otg_timer` | OTG state transitions and host port suspend arm it. Callback accesses MUSB state and may disconnect or schedule backend VBUS work. Remove/free never synchronously delete or shut it down. Event-local `timer_delete()` calls are not final lifetime barriers. |
| `pending_list` | `musb_queue_resume_work()` stores callback/data when runtime suspended. `musb_run_resume_work()` executes/frees nodes during resume; remove has no explicit invalidation/drain. The gadget callback's data is a raw `musb_request *`; giveback/dequeue/endpoint disable do not remove the corresponding pending node. Device-managed node freeing does not retire request lifetime or complete the request. |

Sources: [core][core], `musb_interrupt()`, session checker, resume-work helpers,
OTG timer, deassert-reset work, remove/free; [virthub][virthub], port
resume/reset; [gadget][gadget], endpoint enable/disable, queue/dequeue,
`musb_ep_restart_resume_work()`, cleanup. The pending-request case identifies
missing explicit lifetime coupling; a complete reachable interleaving under
runtime resume/cancel still needs a targeted test. Executing pending callbacks
after function unbind or simply deleting their nodes is not an acceptable
substitute for settling request ownership first.

For CPI, the board config enables Sunxi MUSB gadget mode and its DTS fixes
`dr_mode = "peripheral"`. `sunxi_musb_dma_controller_create()` returns `NULL`;
its destroy is empty and init selects PIO. Thus no active MUSB DMA engine must
be stopped on this backend. The shared driver must nevertheless support other
backends: `nuke()` writes FIFO/CSR registers before channel abort/release;
host cleanup also invokes backend abort; final DMA destruction may access
hardware and retire separate IRQs. DMA buffers cannot be unmapped/freed merely
because CPU register access failed while hardware might still own them.
Sources: [board configuration](../kernel/gameshellneo.config),
[sun8i-r16-clockworkpi-cpi3.dts][board-dts],
[sun8i-a33.dtsi][soc-dts]; [sunxi][sunxi], DMA hooks/init;
[gadget][gadget], `nuke()`; [host][host], `musb_cleanup_urb()`.

Concrete non-Sunxi examples are [musbhsdma.c][hsdma], `dma_channel_abort()` (endpoint
and DMA-register writes) and `musbhs_dma_controller_destroy()` (separate IRQ
free); [musb_cppi41.c][cppi41], `cppi41_dma_channel_abort()` (MMIO plus DMA-engine
termination) and destroy (high-resolution timer retirement); and `ux500_dma.c`,
abort/stop (endpoint MMIO and DMA-engine channel release). These demonstrate why
the core's stop comment is not a DMA-quiescence contract. This audit does not
claim to have qualified every backend's DMA-engine implementation.

Host/HNP timer cases are shared-driver obligations, not established active CPI
paths. Neither fixed peripheral mode nor PIO removes the concrete endpoint,
controller IRQ, gadget/core work and Sunxi notifier lifetime boundaries.

## Sunxi extcon producer ownership

`sunxi_musb_init()` registers `host_nb` with device-managed ownership on the
**parent glue device**, then initializes PHY0. The notifier sets flags and
queues `glue->work` unconditionally. Child exit cancels that work once without
unregistering the notifier. Parent `sunxi_musb_remove()` unregisters the child
before its own device-managed cleanup releases the notifier and glue memory.
Child-only unbind leaves that parent-owned registration live. Sources:
[sunxi][sunxi], init/notifier/exit/remove; [extcon devres][extcon-devres],
`devm_extcon_register_notifier()`; [driver core][dd],
`device_remove()`, `device_unbind_cleanup()`.

The `ENABLED` guard in `sunxi_musb_work()` matters: after normal platform disable,
new work returns before touching MUSB registers or PHY state. It does **not**
make queued work harmless after glue memory is freed, since the guard itself
reads that memory. Existing work already past the guard is drained by the
current cancellation; later notifier work is not permanently excluded.

Explicit unregister-before-cancel would fix registration ownership but is not,
by itself, an in-flight notifier barrier in this pinned implementation.
`extcon_sync()` releases `edev->lock` before `raw_notifier_call_chain()`.
`extcon_unregister_notifier()` removes the entry under that lock, while raw
notifier unregister supplies no wait for readers. A dispatcher may already
have selected `host_nb` before entry to its callback. A callback-local flag or
active count cannot alone protect that pre-entry interval. Sources:
[extcon.c][extcon], `extcon_sync()`, `extcon_unregister_notifier()`;
[notifier.c][notifier], `notifier_call_chain()`, raw unregister;
[include/linux/notifier.h][notifier-header], raw-chain caller synchronization contract.

The board's PHY provider gives a tractable producer boundary, but no completed
fix is established here:

- Both direct extcon emissions originate in
  `sun4i_usb_phy0_id_vbus_det_scan()`. GPIO IRQ, power-supply notification,
  PHY mode changes and PHY power-on/off schedule detection rather than calling
  extcon directly.
- Detection checks `phy0_init` under `phy0->mutex`, then drops that mutex before
  emitting extcon events. `phy_exit()` publishes `phy0_init = false`, but does
  not wait for a detector already past that check.
- Publishing false, excluding re-init, then draining detection **outside** the
  mutex could retire this provider's already-selected notifier calls. Later
  IRQ/notifier-triggered scans would see false and return. However generic
  `phy_exit()` holds that mutex while invoking the provider's exit callback:
  adding synchronous cancellation directly inside `sun4i_usb_phy_exit()` can
  deadlock a detector waiting for it. A suitable external lifecycle operation,
  provider restructuring or notifier-layer synchronization is needed.
- Cross-platform detection also has post-unlock PHY accesses for session-end,
  passby and rerouting. Those need quiescence before PHY resources are dropped,
  not only a post-exit drain. CPI's fixed peripheral role avoids the OTG
  session-end condition; A33 PHY0 has no PMU and no dual-route, so passby returns
  and rerouting is absent. That limits the board-specific MMIO claim without
  supplying the missing notifier-memory barrier.

Sources: [PHY provider][phy], detection/init/exit, IRQ/notifier, mode/power
callbacks, `sun4i_usb_phy_passby()`, probe and `sun8i_a33_cfg`;
[PHY core][phy-core], `phy_exit()`. The existing system-sleep detector disable
from patch 0012 occurs outside the PHY mutex; it does not implement child
unbind teardown. Provider removal already unregisters its power notifier,
frees detect IRQs and cancels detection, but removing the MUSB consumer does
not require removing this shared PHY provider.

A detector redesign using `mutex_trylock()` plus state-aware rescheduling could
avoid waiting on the mutex held by exit, but is not a proven small fix. It must
cover every acquisition, including the post-notifier OTG reacquisition, prevent
re-init from making old work valid again, preserve ordinary contended events,
and avoid repeated retries or post-cancel requeues. Dropping the generic PHY
mutex inside its provider callback also requires a new ownership proof; neither
approach is proposed as an implementable patch by this audit.

## Extracted-source ordering reproduction

Run the bounded audit from
[work/musb-teardown-audit](https://github.com/michaelishri/GameShellNeo/tree/work/musb-teardown-audit):

```sh
task test:musb-teardown-audit
```

[tools/check-musb-teardown.py](https://github.com/michaelishri/GameShellNeo/blob/work/musb-teardown-audit/tools/check-musb-teardown.py) verifies the
locked archive and extracts the relevant source files, applies MUSB patches
0011/0025/0026/0029/0030 with zero fuzz, then compiles
[kernel/tests/musb_teardown_audit.c](https://github.com/michaelishri/GameShellNeo/blob/work/musb-teardown-audit/kernel/tests/musb_teardown_audit.c).
Its 13 extracted functions were also compared byte for byte with the full
patched source cache identified above. They comprise the PM get/put wrappers;
Sunxi disable, exit and interrupt; MUSB interrupt masking, stop, remove and
free; gadget endpoint disable, cleanup and stop; and the actual UDC stop
wrapper. Constants come from the same source headers.

The reported run completes 20 stop cases and 24 peripheral-remove cases for
each variant, natively and under ARM32 emulation in the pinned builder. The
native and ARM32 outputs agree. Passing this audit means it reproduces the
expected ordering and ownership observations, **not** that removal is safe.

| Extracted-source variant | Stop cases | Remove cases | Residual `irq_work` cases | Post-clock injected-handler cases |
| --- | ---: | ---: | ---: | ---: |
| Existing source | 20 | 24 | 12 | 12 |
| Move `irq_work` cancellation after gadget cleanup | 20 | 24 | 0 | 12 |
| Release controller IRQ before platform exit | 20 | 24 | 12 | 0 |
| Apply both diagnostic transformations | 20 | 24 | 0 | 0 |

The two transformations are diagnostic controls, not production patches.
Moving cancellation isolates the modeled endpoint-disable producer. Releasing
the IRQ action before exit isolates the injected-handler boundary; the control
also invalidates `nIrq` to avoid duplicate release. Neither transformation
proves correct host, DMA, notifier, PM or partial-probe teardown.

Stop tests cover zero/positive success and `-EIO`, `-EACCES`, `-EBUSY` and
`-ETIMEDOUT`, with generic-PHY and legacy-transceiver branches. Negative errors
are paired with both accessible and inaccessible modeled registers; successful
gets are paired with accessible registers. In all eight stop cases assuming
inaccessible registers, the existing source still accesses them. Logical
detachment and balanced temporary references nevertheless complete. This
demonstrates that PM return and register accessibility must be modeled
separately; it does not identify a reachable Sunxi power failure.

Remove tests vary an extra retained reference, successful/failed PM get,
initial register accessibility, an enabled endpoint and an injected controller
handler at clock teardown. The endpoint's real disable function queues work
after the first cancellation. The real Sunxi handler performs three status
reads when the injected boundary permits its action to remain live. The
fixture checks final driver/state/reference/IRQ ownership and work state.

Two native negative controls deliberately introduce an early return from
failed gadget stop or omit the final IRQ release. They fail the intended
logical-detachment or IRQ-ownership assertion. Compiler failures or unrelated
assertions are not accepted as successful negative evidence. These mutations
were not run under ARM32.

The runner writes `.local/build/musb-teardown-tests/evidence.json`, including
archive, patch, fixture, runner, helper, extracted-source and binary hashes,
the builder identity, architecture outputs and negative-control failures.
The retained extracted header is restored to the untransformed source. The
final guarded rerun passed; its evidence SHA-256, independently read back, is
`3760be04e085a3b34f7d5319d796cda753a0501d7c55ec0e279355f0a336f19c`.
Repository checks also pass: 13 runtime and 487 tooling tests, with two existing
skips, plus compiled current-limit/Mac mount-guard checks and shell lint.

The fixture uses synchronous controlled boundaries for locks, scheduling,
MMIO, PM internals, PHY calls, request completion and UDC/function-driver
unregister. Its `usb_del_gadget_udc()` substitute invokes actual endpoint
disable followed by actual UDC stop; it does not execute the full earlier
disconnect/suppression/unbind chain. `nuke()` is a boundary substitute, and
`musb_interrupt()` does not enqueue additional work. Thus the final-cancel
control does not test the still-live interrupt or notifier producers. Host
cleanup is constrained to the peripheral no-op and DMA is absent, matching
the audited CPI backend boundary without qualifying other roles/backends.

The injected handler represents a selected or shared action reaching the
controller after resource teardown; it is not Linux IRQ scheduling, electrical
delivery or a reproduced board interrupt. The late-idle counter records a
zero usage count while runtime PM remains enabled after modeled resource loss.
It does not run PM-core status/error checks, parent/domain callbacks or
`musb_runtime_suspend()`, and therefore does not establish a real late context
save. Timer, pending-request and extcon/PHY producer findings remain source
audits; these cases do not simulate their full concurrent lifetimes.

## Fix boundaries and review gates

Narrow source changes can be developed independently of a generic failed-power
recovery design: retire the core IRQ action while its backend resources still
exist; close work admission or perform final cancellation after producers are
retired; shut down the initialized OTG timer at final removal; and align Sunxi
notifier ownership with the child lifecycle. Each needs partial-probe, role,
restart and dependency review. In particular, moving IRQ free must preserve
interrupts needed by DMA/client teardown, invalidate `nIrq` to prevent duplicate
free, and keep wake-ownership cleanup ordered correctly. Merely moving a
cancellation later does not exclude the remaining IRQ/notifier producers.

Robust truly inaccessible-hardware recovery is broader. It must start before
UDC disconnect/endpoint disable, distinguish logical detachment from hardware
quiescence, block new submissions/callbacks, retire requests and resume data,
and provide a backend-specific means to stop bus mastering/interrupt generation
without unsafe register access. Reset or clock-off is only usable after proving
its hardware contract and interaction with host/gadget callbacks. This cannot
be supplied by an early return from `udc_stop()`, a boolean “powered” guess, or
blindly skipping direct core writes while endpoint/PHY/DMA helpers still run.

NEO-106 tracks the planned removal-producer implementation, including the
IRQ/work/timer/PM ordering and PHY/extcon synchronization. The work should
proceed in separately reviewable steps:

1. Define terminal removal ownership and implement the bounded controller
   retirement changes. Cover initialized-resource tracking, work admission,
   final timer shutdown, controller IRQ removal while backend resources remain
   available, and PM callback retirement before backend exit. Prove which
   client/DMA operations still require IRQs before choosing their final order;
   the two diagnostic transformations alone are insufficient.
2. Give queued resume operations an explicit relationship to request lifetime.
   Reject new submissions during terminal teardown and invalidate or settle
   pending request work before cancellation can free its data. Preserve the
   request-completion contract and ordinary soft stop/restart behavior.
3. Establish Sunxi notifier unregister and in-flight callback synchronization
   at the producer/provider layer, then retire glue work before its owner or
   suppliers disappear. Cover child-only unbind, full parent removal, init
   failure and rebind. Resolve the PHY mutex and pre-entry raw-notifier windows
   before claiming unregister-plus-cancel is safe.
4. Design genuinely inaccessible-hardware recovery from the earliest endpoint
   cleanup boundary. Define a backend quiescence contract for interrupt
   generation, bus mastering and reset/power state, and carry it through UDC,
   endpoint and host cleanup. Test both failed power and successful teardown
   without discarding logical ownership or suppressing required completions.

Extend validation beyond the current ordering fixture with callback suppression
and completions, pending resume data, notifier retirement, actual runtime-PM
states/reference ownership and ordinary start/stop/rebind. Relevant role and
PM configurations, partial-probe failures, full-kernel concurrency checks and
later hardware qualification remain separate gates. A synthetic accessibility
switch exposes whether code respects an assumed boundary; it cannot establish
that Sunxi loses register access for the injected PM error. No production
teardown change or hardware recovery qualification is claimed by this audit.

One adjacent source issue is kept separate: `musb_gadget_queue()` maps a request
before `musb_queue_resume_work()`; its negative-result branch removes the list
entry without the unmap used by the disabled-endpoint branch. It warrants a
DMA-backend ownership audit and should not be conflated with CPI's PIO teardown.
Source: [musb_gadget.c][gadget], queue/mapping helpers.

## Primary-source links

Function names above identify the exact owning code in the pinned local tree.
These stable-tree URLs are navigation references to the unpatched upstream
version; patches 0011/0012/0025/0026/0029/0030 must be considered where relevant.

[core]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_core.c?h=v6.18.54
[gadget]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_gadget.c?h=v6.18.54
[host]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_host.c?h=v6.18.54
[virthub]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_virthub.c?h=v6.18.54
[sunxi]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/sunxi.c?h=v6.18.54
[udc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/gadget/udc/core.c?h=v6.18.54
[configfs]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/gadget/configfs.c?h=v6.18.54
[composite]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/gadget/composite.c?h=v6.18.54
[ecm]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/gadget/function/f_ecm.c?h=v6.18.54
[ether]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/gadget/function/u_ether.c?h=v6.18.54
[hcd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/core/hcd.c?h=v6.18.54
[hub]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/core/hub.c?h=v6.18.54
[message]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/core/message.c?h=v6.18.54
[rpm-source]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/power/runtime.c?h=v6.18.54
[phy]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/phy/allwinner/phy-sun4i-usb.c?h=v6.18.54
[phy-core]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/phy/phy-core.c?h=v6.18.54
[extcon]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/extcon/extcon.c?h=v6.18.54
[extcon-devres]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/extcon/devres.c?h=v6.18.54
[dd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/dd.c?h=v6.18.54
[notifier]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/notifier.c?h=v6.18.54
[rpm-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/pm_runtime.h?h=v6.18.54
[platform]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/platform.c?h=v6.18.54
[board-dts]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts?h=v6.18.54
[soc-dts]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/arch/arm/boot/dts/allwinner/sun8i-a33.dtsi?h=v6.18.54
[hsdma]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musbhsdma.c?h=v6.18.54
[cppi41]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/usb/musb/musb_cppi41.c?h=v6.18.54
[notifier-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/notifier.h?h=v6.18.54
[rpm-doc]: https://docs.kernel.org/power/runtime_pm.html
[irq-doc]: https://docs.kernel.org/core-api/genericirq.html#c.free_irq
[work-doc]: https://docs.kernel.org/core-api/workqueue.html#c.cancel_work_sync
[timer-doc]: https://docs.kernel.org/driver-api/basics.html#c.timer_shutdown_sync
