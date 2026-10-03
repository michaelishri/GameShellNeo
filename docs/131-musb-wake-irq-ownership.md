# MUSB IRQ-wake ownership and policy (NEO-98)

4 October 2026, Pacific/Auckland. The pinned MUSB core owns an IRQ-wake
reference continuously from successful probe until teardown. Disabling its
`power/wakeup` policy does not release that reference. A replacement should
own a successful wake enable only for the system-sleep transition and balance
that specific operation, including abort and error paths.

For this tree, checked MUSB suspend/resume ownership is the stronger candidate
than a direct conversion to `dev_pm_set_wake_irq()`: the latter implements
policy selection, but its arm/disarm callbacks ignore IRQ-chip errors. The
checked approach matches the existing
[IRQ-wake error-ownership patch](../kernel/patches/0019-wake-irq-error-ownership.patch).
Neither approach alone proves that USB can electrically wake the board.

This is a read-only source audit of `.local/sources/linux-6.18.54` with patches
0001–0025, plus previously saved evidence. This research task wrote only this
report. It changed no hardware, runtime policy, patch, configuration or staged
image. A separate isolated draft reviewed below belongs to the coordinating
implementation task and does not change this audited baseline.
Diagnostic.18 remains built, verified and staged on the Mac, awaiting card
installation. Its disabled USB-wake feature flag **does not fix the unconditional
probe-time IRQ-wake reference**. Its connection-lifecycle experiment and the
original RTC-wake/USB-recovery failure remain separate NEO-95 evidence:
[failure](125-traced-rtc-wake-usb-failure.md),
[design](126-musb-system-sleep-design.md), and
[staged candidate](128-musb-system-sleep-candidate.md).

## Existing ownership, defaults and cleanup

Paths below are relative to the pinned Linux tree. The public links identify
the same upstream version; local MUSB sleep changes are identified separately
by [patch 0025](../kernel/patches/0025-musb-system-sleep-pullup.patch).

| Pinned source / function | Observed behavior |
| --- | --- |
| `drivers/usb/musb/musb_core.c:allocate_instance()` | Zero-allocates the controller and starts `nIrq` at `-ENODEV`, so early failure does not free an unrequested IRQ. |
| `musb_init_controller()` | Initializes glue/PHY/runtime PM, masks controller interrupts, initializes IRQ work, endpoints and timer, then calls `request_irq(nIrq, musb->isr, IRQF_SHARED, ..., musb)`. Only successful request stores `nIrq`. |
| Same function, immediately after IRQ request | Calls `enable_irq_wake(nIrq)` unconditionally. Success sets the `irq_wake` bit and calls `device_init_wakeup(dev, 1)`, ignoring its return value. Wake-enable failure clears the bit but does **not** fail controller probe. |
| Same function, later failures | Host/gadget/mode setup can fail after wake setup. `fail3` drains works and unwinds DMA/PHY/runtime PM; `fail2` calls `device_init_wakeup(dev, 0)` when `irq_wake` is set, then exits the platform; `musb_free()` subsequently releases the wake reference and IRQ. |
| `musb_free()` | If an IRQ was requested, calls `disable_irq_wake()` only when `irq_wake` is set, ignores its return, and calls `free_irq(..., musb)`. It serves failed probe and removal. |
| `musb_remove()` | Cleans up host/gadget, masks the controller, exits glue, drops/disables runtime PM and shuts down DMA/PHY, then calls `musb_free()` and unconditionally disables device wake capability. |

These are lifetime operations, not operations conditional on system-sleep
policy. The existing source even labels its probe wake handling as unfinished.
[MUSB core][musb], [MUSB state fields][musb-h].

`device_init_wakeup(dev, true)` first marks the device capable, then enables
its wakeup source. Under `CONFIG_PM_SLEEP`, `device_wakeup_enable()` can fail
with `-ENOMEM` or `-EEXIST`; capability can already be true when it fails.
Existing MUSB ignores that error, so successful IRQ wake does not guarantee
successful wakeup-source allocation. `device_init_wakeup(dev, false)` removes
the source and capability; it does not disable IRQ wake. The managed
`devm_device_init_wakeup()` also ignores the initialization result in this
version, so substituting it would not solve the allocation-error issue.
[Wakeup interface: `device_init_wakeup()`][wakeup-h],
[source allocation/attachment: `device_wakeup_enable()`][wakeup].

The default enabled policy follows from MUSB's successful probe wake-enable
branch, not from `IRQF_SHARED`. `musb_host_setup()` additionally calls
`device_wakeup_enable(hcd->self.controller)` and ignores its result.
`musb_host_alloc()` passes `musb->controller` to `usb_create_hcd()`: this is the
same controller device, not a second IRQ-wake owner. It matters when preserving
preexisting disabled policy or testing host/OTG initialization. The root hub
has its own device policy. [MUSB host allocation/setup][host],
[USB HCD root-hub wake policy][hcd].

## What the generic wake-IRQ API provides

`drivers/base/power/wakeirq.c:dev_pm_set_wake_irq(dev, irq)` allocates a small
record and attaches it to `dev->power.wakeirq`. It does not request a second
IRQ, install a handler, call `enable_irq_wake()` or validate irqchip wake
support. It rejects negative IRQ numbers, allocation failure and an existing
device wakeirq; the latter produces `-EEXIST`. `dev_pm_attach_wake_irq()` does
not replace the existing attachment. [Wake-IRQ implementation][wakeirq].

The device-level attachment and the current wakeup source have different
lifetimes:

| Event | Pinned helper behavior |
| --- | --- |
| Register while policy is enabled | Attach to both `dev->power.wakeirq` and the current wakeup source. |
| Disable policy in sysfs | Destroy/detach the wakeup source; retain `dev->power.wakeirq`. No IRQ-wake call occurs at that write. |
| Next suspend with policy disabled | No wakeup source carrying this attachment is walked for arming; MUSB contributes no wake reference. |
| Reenable policy before another transition | Allocate a new source; `device_wakeup_attach()` reattaches the retained wakeirq. The next transition can arm it. |
| Clear the attachment | `dev_pm_clear_wake_irq()` detaches from the current source, clears the device pointer and frees the record. An ordinary I/O IRQ is neither freed nor disarmed by this function. |

Thus disabling policy must not call `dev_pm_clear_wake_irq()` if reenable is to
work automatically. Conversely, clearing an attachment is not a substitute
for balancing an already armed IRQ. Clearing without any attachment is safe;
clearing after a failed registration because a *different owner* already had
one would destroy that owner's attachment. Store successful registration
ownership and clear only that attachment. [Wake-IRQ helpers][wakeirq],
[source attach/detach/enable/disable][wakeup].

Using `devm_pm_set_wake_irq()` alone does not align cleanup with MUSB's manual
IRQ lifetime. Driver-core managed-resource cleanup follows the remove callback,
while MUSB frees its IRQ inside that callback. Explicitly ordered attachment
cleanup is therefore needed unless the whole relevant lifetime is refactored.
[Managed wakeirq helper][wakeirq],
[driver core: `device_remove()` / `device_unbind_cleanup()`][driver-core].

There are material error limits. `dev_pm_arm_wake_irq()` is `void`, rereads
`device_may_wakeup()`, and discards `enable_irq_wake()`'s result.
`dev_pm_disarm_wake_irq()` also rereads policy and discards the disable result;
it records no successful-arm ownership. An injected enable failure can
therefore be followed by an unbalanced disable. An injected disable failure
can retain IRQ depth without a helper-owned flag, allowing subsequent arming
to stack a reference. Policy/source changes by kernel code during a transition
also cannot be assumed to balance correctly. Ordinary userspace policy
changes before and after a completed transition are the intended case; tasks
are frozen during system sleep. [Arm/disarm functions][wakeirq],
[IRQ reference accounting][irq-manage].

The sysfs store itself neither takes `device_lock()` nor checks
`device_set_wakeup_enable()`'s return value in this version. A successful write
of `enabled` need not prove source allocation; readback matters. This supports
retaining diagnostic.18's existing readback checks. Probe serialization also
does not exclude a sysfs policy write in the interval after initialization
exposes capability attributes and before its default source attachment.
[Power sysfs: `wakeup_store()`][sysfs],
[capability/source initialization][wakeup].

The ordinary I/O helper has no additional runtime-PM reference or handler.
Its runtime enable/disable helpers return immediately unless dedicated wake
flags are present. `dev_pm_set_dedicated_wake_irq()` is a different API: it
requests a separate threaded IRQ and its handler can resume the device through
runtime PM. It is unsuitable for re-requesting MUSB's already owned, shared
main IRQ. [Ordinary and dedicated wake-IRQ implementations][wakeirq].

## IRQ core, shared ownership and s2idle

`kernel/irq/manage.c:irq_set_irq_wake()` owns a **per-IRQ descriptor**
`wake_depth`, not a depth per `request_irq()` action. The first enable calls
the irqchip and sets `IRQD_WAKEUP_STATE` on success. Later enables increment
depth without calling the chip. The last disable calls the chip and clears
the state on success. Failed first enable restores depth to zero; failed last
disable restores it to one. Disabling zero depth warns. Ordinary IRQ
enable/disable depth is separate. [IRQ wake implementation][irq-manage],
[descriptor fields][irqdesc].

Consequently, one driver must drop only the reference it acquired. It must not
loop until the descriptor appears disabled, reset depth directly, or treat
another sharer's reference as its own. MUSB policy disabled means *MUSB no
longer contributes a reference*; a legitimate sharer can still keep the whole
line wake-enabled. `IRQF_SHARED` permits other handlers but is not evidence that
one is present. `free_irq()` removes the action and synchronizes handlers; it
does not provide a driver's missing `disable_irq_wake()` balance.
[IRQ management and `free_irq()`][irq-manage].

The pinned system PM sequence is:

1. `drivers/base/power/main.c:dpm_suspend_noirq()` arms registered wakeirqs,
   calls `suspend_device_irqs()`, then executes device noirq callbacks.
2. `kernel/irq/pm.c:suspend_device_irq()` marks a wake-enabled IRQ
   `IRQD_WAKEUP_ARMED`; it suspends ordinary non-wake IRQs. IRQs with
   `IRQF_NO_SUSPEND` users and nested-thread IRQs have separate handling.
3. The normal IRQ flow's `irq_can_handle_pm()` handles an armed wake IRQ through
   `irq_pm_handle_wakeup()`, which makes it pending/suspended, disables it and
   calls `pm_system_irq_wakeup()`. This defers the normal device handler until
   resume, while recording a system wake event.
4. `dpm_resume_noirq()` resumes noirq devices, resumes device IRQs, and then
   disarms registered wakeirqs. Its suspend-error unwind takes this path too.
   Ordinary MUSB `.resume` runs later.

[PM ordering][pm-main], [IRQ suspend/resume][irq-pm],
[IRQ flow handling][irq-chip], [system wake notification][wakeup].

`kernel/power/suspend.c:suspend_enter()` reaches this same noirq sequence
before `s2idle_loop()`. `pm_system_wakeup()` sets the suspend-abort condition
and calls `s2idle_wake()`. Therefore IRQ wake bookkeeping matters for `freeze`
even without a platform deep-suspend implementation. `IRQF_NO_SUSPEND` is not
a replacement: it permits handlers during suspend and does not itself request
system wake. Combining it with shared wake handling has extra requirements
that MUSB's ordinary `IRQF_SHARED` request does not implement.
[Suspend path][suspend], [wakeup notification][wakeup],
[kernel interrupt/suspend documentation][irq-doc].

Previously saved GameShell evidence in
`.local/diagnostics/20261003T095154.319623Z/result.json` shows IRQ 164 as
`GICv2 103 Level musb-hdrc.2.auto`, with no second action named on that line.
Counts were 72,758 before and 73,405 after the failed test; they are interrupt
counts, not wake-reference counts. The SoC DT declares `GIC_SPI 71` for `mc`,
corresponding to hardware IRQ 103. Both GIC driver chip variants set
`IRQCHIP_SKIP_SET_WAKE | IRQCHIP_MASK_ON_SUSPEND`.
`set_irq_wake_real()` returns success directly for the skip flag. For this
path, the source change controls software IRQ suspend treatment; it must not
be described as programming an additional GIC wake-routing register.
[SoC DT][sunxi-dt], [GIC chip flags][gic], [wake setter][irq-manage].

`CONFIG_GENERIC_IRQ_DEBUGFS` is disabled in the inspected diagnostic.18
isolated build configuration. This audit has no live `wake_depth` measurement.
The persistent MUSB contribution is a source-derived finding, not a newly
observed numeric depth or proof that USB caused the recorded wake.

## Candidate contract and compatibility choices

The recommended candidate is explicit checked ownership in the MUSB core,
initially qualified on the fixed Sunxi peripheral. It should use a separate
`bool` for an owned IRQ-wake reference, rather than reusing a packed flag word
whose neighboring bits can be updated asynchronously. Successful wake-source
initialization, capability changes and generic attachment ownership, if any,
are separate facts from successful IRQ arming.

| Boundary | Required candidate behavior |
| --- | --- |
| Fresh controller probe | Preserve request/initialization order: initialize handler-visible state and mask controller sources before requesting the IRQ; begin wake setup only after request success. Do not advertise success with failed source allocation. |
| Capability compatibility | Preserve the old usable-controller outcome when IRQ wake is unsupported. A blind unconditional `device_init_wakeup(true)` plus generic attachment would instead advertise capability without testing it; a first wake-enabled suspend could silently fail to arm. |
| Existing device state | Preserve preexisting source/capability/policy. An `-EEXIST` result never authorizes clearing another source or wakeirq. Either explicitly borrow existing state with separately tracked ownership, or reject an unsupported ownership arrangement before mutation. A precheck alone does not serialize concurrent owners: the design needs a sole-owner/coordination contract. |
| Suspend admission | Resolve any previously owned failed disarm before acquiring another wake reference. Acquire the existing system runtime-PM reference; check its result and balance a failed get. If policy permits wake, check `enable_irq_wake()` and mark ownership only on success, before gadget/platform/context mutation. On arm error, release the temporary runtime reference and return the error without partially suspending the controller. |
| Successful suspend / later-device abort | Retain exactly the successful arm until MUSB resumes; failed later device/late/noirq suspend must still reach balanced MUSB resume. No enable when policy is disabled. |
| Resume | Attempt disarm based on saved ownership, not a fresh policy read. Always restore controller state and balance the existing system-PM reference even when disarm fails. Preserve/report the relevant first error alongside resume-work errors; retain wake ownership after failed disarm so the next suspend cannot stack a reference. Keep patch 0025's connection/error contract intact. |
| Removal and failed probe | Quiesce MUSB's sources/work, release owned wake state outside `musb->lock` while glue/IRQ-chip resources still exist, and only then free the requested IRQ. Destroy only owned source/capability state. For a generic attachment, clear it before `free_irq()`. Update both the shared error ladder and normal removal. |

This avoids adding another runtime-PM reference beyond MUSB's existing
system-sleep lifetime. Arming in ordinary `.suspend`, before controller
mutation, also leaves a simple failure return path; it does not need to move
fallible setup into `.suspend_noirq`. These are design requirements,
not hardware-qualified behavior. [Current MUSB PM/error paths][musb],
[local checked-ownership precedent](../kernel/patches/0019-wake-irq-error-ownership.patch).

For an initial **fresh-controller-only** implementation, reject preexisting
capability, source or generic wakeirq before mutation, and explicitly own
capability creation before calling `device_init_wakeup(true)`. That ownership
survives its allocation failure and sysfs policy changes in the initialization
window. An `-EEXIST` from a source attached during this owned window is different
from encountering a preexisting foreign source. A source can exist even when
capability has independently been cleared, so a capability check alone does
not establish freshness. This narrower contract can fail a previously usable
preconfigured controller; it is deliberate compatibility scope, not a universal
drop-in conversion. [Independent source/capability setters][wakeup].

There are two defensible capability strategies, with different limits:

* A **balanced probe-time enable/disable** can bridge compatibility with the
  current fresh-controller behavior. Failed enable leaves the controller
  usable without newly advertising capability. Successful enable must be
  recorded immediately, and successful disable must release it before normal
  probe completes. Then initialize device wake policy with checked allocation
  and owned-state cleanup. This retains a transient probe operation, not a
  permanent reference. A failed balancing disable must be surfaced and kept
  owned for teardown; it cannot be treated as successful initialization.
* An **explicit glue/platform capability contract** avoids using a mutating
  operation as a probe. It is cleaner long term, but requires auditing and
  declaring support for existing backends rather than assuming every main IRQ
  is a system-wake source. DT presence of a main IRQ, helper allocation success,
  and a board's ability to resume from some other source are insufficient.

A balanced probe is not a universal hardware capability test. Another sharer's
nonzero depth bypasses the chip callback; successful setup cannot certify
electrical wake or all sleep states. A chip may also reject a later transition
after succeeding at probe, so system-suspend calls still need checked results.
Generic `dev_pm_set_wake_irq()` remains a reasonable standard helper where
its existing failure model is acceptable and capability/ownership are known;
adopting it here does not meet the stronger checked-error contract by itself.
[Reference accounting][irq-manage], [helper semantics][wakeirq].

Permanent disarm failure is a real limit. The IRQ core intentionally preserves
the reference on a failed last disable, and MUSB's platform remove callback
returns `void`. The driver can report the failure and retain ownership while
its object exists, but cannot claim full cleanup after an unrecoverable chip
failure merely by clearing a flag or calling `free_irq()`. Teardown needs a
documented failure diagnostic and a backend recovery boundary; fault tests
must report outstanding debt rather than force-clear shared state. For the
observed valid GICv2 IRQ, `IRQCHIP_SKIP_SET_WAKE` excludes an ordinary chip
enable/disable callback failure, which narrows the local case without proving
all MUSB backends safe. [IRQ wake failure behavior][irq-manage],
[MUSB remove signature/order][musb], [GIC flags][gic].

## Runtime PM, glue and configuration boundaries

The audited in-tree MUSB glue implementations contain no second
`enable_irq_wake()` or `dev_pm_set_wake_irq()` for the main MUSB IRQ. Sunxi
passes its parent resources to the `musb-hdrc` child; it does not separately
request or attach that main IRQ for wake. This is a source-search result for
this tree, not permission to clear an attachment supplied by a future glue,
bus layer or out-of-tree driver. A separate device sharing the Linux IRQ has
separate device-level ownership but shares descriptor wake depth.
[Sunxi probe][sunxi], [MUSB directory][musb-tree], [IRQ depth][irq-manage].

`sunxi_musb_init()` explicitly holds `pm_runtime_get(musb->controller)` to
prevent unsupported Sunxi runtime PM; `sunxi_musb_exit()` balances it. Preserve
that existing reference. For this fixed peripheral, removing the lifetime IRQ
wake reference does not authorize a new runtime-suspend path or clock/PHY
shutdown. [Sunxi initialization/exit][sunxi].

Other backends have different lifecycles: OMAP2430's runtime callbacks operate
the PHY and low-level controller state; DA8xx's system callbacks power down
PHY/clock; DSPS saves wrapper/DMA context; TUSB6010 explicitly programs its
own idle wake masks. AM335x's PHY has a separate wake policy and wake-control
register path. They are not evidence of a duplicate main-IRQ reference, but
they show why removing a persistent irqchip request requires runtime-idle and
system-sleep qualification beyond Sunxi. Neither ordinary wakeirq registration
nor manual system callbacks automatically reproduce every possible backend's
previous runtime wake routing. [OMAP2430][omap], [DA8xx][da8xx], [DSPS][dsps],
[TUSB6010][tusb], [AM335x PHY][am335x].

| Configuration | Source consequence and build requirement |
| --- | --- |
| `CONFIG_PM=y`, `CONFIG_PM_SLEEP=y` | Real source allocation, system PM and IRQ arm/disarm traversal. This is the inspected diagnostic.18 configuration, with MUSB gadget/Sunxi built in. |
| `CONFIG_PM=y`, `CONFIG_PM_SLEEP=n` | `wakeirq.o` still builds and ordinary registration allocates a device record, but source attachment is stubbed and no system PM traversal runs. Wake-policy helpers use `should_wakeup`; do not infer a real source object from initialization success. |
| `CONFIG_PM=n` | Wakeirq registration/clear APIs are success/no-op stubs. MUSB's PM callbacks are absent. A new ownership design must compile without accessing conditionally absent `dev->power` members. |
| Host, gadget, dual-role; built-in/module | Exercise all applicable setup/error paths and the host-side source enable; compile all supported combinations touched by the change. Gadget-only success cannot qualify host/OTG behavior. |

The current `enable_irq_wake()` wrapper itself is not a `CONFIG_PM_SLEEP`
no-op; do not rely on that assumption to remove configuration guards.
[Wakeirq build selection][pm-make], [wakeirq stubs][wakeirq-h],
[wakeup stubs][wakeup-h], [IRQ wrappers][interrupt-h], [MUSB PM guards][musb].

## Required actual-source regression and failure matrix

The coordinating task drafted `kernel/patches/0026-musb-wake-irq-policy.patch`
only in `.local/worktrees/musb-wake-irq-policy`. A read-only review during this
audit found the expected paired probe, checked system arm/disarm, retained
failed-disarm ownership and pre-platform teardown cleanup. Review requested
that the freshness precondition also check an existing wakeup source when
capability is false. At this review point the draft had no new regression or
hardware qualification, and was not applied to the main source or staged.18.

Subsequent coordinating-task update: that freshness guard is now present in
the separate [implementation branch][candidate]. Its source checks pass 89
native/ARM32 scenarios and 14 negative controls, and six complete ARM driver
object configurations compile. The branch's report 132 identifies the tested
subset and remaining fault-injection gates below. No candidate image has been
built or installed; these results do not change diagnostic.18 or establish
hardware wake behavior.

The following is an acceptance matrix for that candidate. It should compile
the extracted, patched **actual** MUSB setup/PM/cleanup functions and relevant
wakeup/IRQ-core functions, using controlled allocation, irqchip and PM shims.
A separate handwritten model cannot demonstrate that the changed error ladder
or actual helper behavior is correct. Preserve the existing 61 sleep-connection
scenarios and their faulty-variant checks described in
[report 128](128-musb-system-sleep-candidate.md).

| Scenario / fault | Required observation |
| --- | --- |
| Fresh probe, supported wake | Request precedes wake setup; any compatibility probe balances; enabled default preserved; no MUSB lifetime wake reference remains. |
| `request_irq()` fails | No wake call, no source allocation, no `free_irq()` for this request. |
| Probe wake enable unsupported | Ordinary USB probe still succeeds; no newly advertised wake capability; no bogus disable. |
| Balanced-probe disable fails | Error visible; ownership retained through cleanup attempt; persistent failure reported as unresolved, never fabricated success. |
| Wakeup-source allocation fails after capability is set | Error checked; only newly created capability/source state undone; wake reference and IRQ cleaned in order. |
| Preexisting enabled source, disabled capable device, source with capability false, existing wakeirq | Explicit contract exercised; no unrelated source/attachment erased on `-EEXIST`; preexisting disabled policy not silently reset by host setup. |
| Policy writes during owned capability initialization | Allocation/attachment errors remain checked; cleanup removes capability owned by this core without generalizing that permission to foreign preexisting state. |
| Generic attachment allocation failure, if that alternative is used | Owned initialized policy unwound, foreign state retained; no fake successful registration or unowned clear. |
| Host/gadget/mode failure after wake initialization | All acquired wake state released once before IRQ teardown; early failures never release unowned state. |
| Policy enabled → disabled → enabled across completed cycles | No manual IRQ arm on disabled cycle; exactly one successful owned arm/disarm on enabled cycles; generic alternative must reattach the retained record to the new source. |
| Runtime get fails | Existing PM usage balanced; no IRQ-wake operation after failure, gadget gate, detach or context mutation. |
| System wake enable fails | Suspend returns error before controller mutation; PM reference balanced; resume/cleanup do not issue an unowned disable. |
| Later device/late/noirq failure or pending wake | MUSB resume/abort balances the successful arm; policy and connection state restored under the existing candidate contract. |
| Policy changes between arm and resume | Manual release follows the saved ownership, even when current policy differs. Generic helper's failure here remains an explicit limitation. |
| Disarm fails, then next suspend | Controller recovery and PM balance still occur; error remains visible; ownership retained; next attempt resolves debt or fails without stacking. |
| Resume work also fails | Preserve the relevant first error, report the other; retain patch 0025's no-reconnect-on-gated-failure behavior and balance PM. |
| Shared IRQ with another owner at depth one | MUSB arm adds only its contribution; disarm/remove returns to the other owner's depth; policy-off leaves that owner untouched. |
| Shared owner's order changes | Check zero/nonzero boundary callbacks and injected last-disable failure for each ordering; no assumed ownership of global depth. |
| IRQ suspend with policy on/off | Verify real `IRQD_WAKEUP_STATE`/`IRQD_WAKEUP_ARMED`, pending/suspended behavior and normal-handler deferral; include s2idle/noirq abort. |
| Awake runtime use and repeated bind/unbind | No extra PM usage or ordinary IRQ-depth changes; requested action and owned wake state freed once, before backing resources disappear. |
| PM/PM_SLEEP and role build matrix | No missing symbol/field, false source ownership, leaked attachment or accidental wake behavior in stub configurations. |

Useful mandatory negative controls are unconditional probe arming, disable
without successful arm, clearing ownership despite failed disable, policy
reread on resume, clearing a foreign wakeirq after `-EEXIST`, freeing the IRQ
before wake cleanup, missing capability rollback after allocation failure,
and stacking a second arm after a retained failed disarm. Actual-source tests
should reject each intentionally faulty variant. Compile complete affected
driver objects as an integration check; shim tests do not establish scheduler,
irqchip electrical or PHY timing behavior.

## Hardware gates and remaining limits

Keep diagnostic.18's staged NEO-95 comparison identifiable. A later wake-owner
candidate needs its own source/image identity and fresh baseline; do not
silently replace staged.18 or reclassify diagnostic.17's failed result. First
verify boot, the policy readback, controller/IRQ identity, USB enumeration,
independent USB/Wi-Fi management and ordinary runtime behavior. Then use the
established attended PM-debug and awake-RTC admission sequence before actual
sleep. No sleep or card-write operation is authorized by this research note.

With USB policy disabled, qualify RTC/POWER wake and untouched-cable USB
recovery separately, with the existing keypad/display/boot/reference and
recorder-restoration checks. IRQ metadata or controlled tracing must establish
the candidate's owned contribution before, during and after the transition;
an interrupt count or sysfs policy alone is insufficient. Test repeated cycles,
abort, USB absent, physical reconnect and host sleep as separate conditions.
A policy-enabled USB wake test requires its own stimulus, trace and fallback;
an RTC wake with USB attached does not qualify remote USB wake.

Outstanding decisions are the compatibility bridge versus an explicit
platform capability contract, the supported preexisting-state contract, and
the diagnostic/recovery boundary for permanent teardown disarm failure.
Other MUSB backends and runtime-idle wake paths remain unqualified. The audit
supports correcting software ownership; it establishes no electrical wake
capability, deep retention, lower current, battery-life gain or resolution of
the original USB enumeration failure.

## Source identity and primary references

The public v6.18.54 copies of `wakeirq.c`, `wakeup.c` and `kernel/irq/manage.c`
were fetched read-only and matched the local files byte for byte. MUSB differs
because the local patches are applied; implementation conclusions above use
the local tree, including patch 0025. No moving upstream branch is used as the
implementation authority.

| Local source | SHA-256 |
| --- | --- |
| `drivers/usb/musb/musb_core.c` | `8efd91ec6c55527d20fca917bd283b72f1ff272cd804b5ffb642d7930258f0a5` |
| `drivers/base/power/wakeirq.c` | `7edd4bd6052d5348f98a736b7ada75bd239f6426bf726e5cd9958d6fe9a70a68` |
| `drivers/base/power/wakeup.c` | `13c81b0d2640b9c21dd652d29d97101259e17cadb7aa1a4313c5b56d862a3673` |
| `kernel/irq/manage.c` | `eda67d982c82929f6f123dc3a3c568e7de9dac72c4174ed9634228d53f96dcc4` |
| `kernel/irq/pm.c` | `e6080439cec4e1c64e04b1d334a31dcad4a5531a880878d9905f8d6e4fd9118b` |
| `drivers/base/power/main.c` | `0842ea9473ca90bdb3d745912ea47e2826107a5369316d64665e7b597fc01132` |

[musb]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_core.c
[musb-h]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_core.h
[musb-tree]: https://github.com/gregkh/linux/tree/v6.18.54/drivers/usb/musb
[host]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_host.c
[hcd]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/core/hcd.c
[wakeirq]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/power/wakeirq.c
[wakeup]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/power/wakeup.c
[wakeup-h]: https://github.com/gregkh/linux/blob/v6.18.54/include/linux/pm_wakeup.h
[wakeirq-h]: https://github.com/gregkh/linux/blob/v6.18.54/include/linux/pm_wakeirq.h
[sysfs]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/power/sysfs.c
[pm-main]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/power/main.c
[pm-make]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/power/Makefile
[driver-core]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/dd.c
[irq-manage]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/irq/manage.c
[irqdesc]: https://github.com/gregkh/linux/blob/v6.18.54/include/linux/irqdesc.h
[irq-pm]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/irq/pm.c
[irq-chip]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/irq/chip.c
[interrupt-h]: https://github.com/gregkh/linux/blob/v6.18.54/include/linux/interrupt.h
[suspend]: https://github.com/gregkh/linux/blob/v6.18.54/kernel/power/suspend.c
[irq-doc]: https://github.com/gregkh/linux/blob/v6.18.54/Documentation/power/suspend-and-interrupts.rst
[gic]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/irqchip/irq-gic.c
[sunxi-dt]: https://github.com/gregkh/linux/blob/v6.18.54/arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi
[sunxi]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/sunxi.c
[omap]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/omap2430.c
[da8xx]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/da8xx.c
[dsps]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_dsps.c
[tusb]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/tusb6010.c
[am335x]: https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/phy/phy-am335x.c
[candidate]: https://github.com/michaelishri/GameShellNeo/tree/work/musb-wake-irq-policy
