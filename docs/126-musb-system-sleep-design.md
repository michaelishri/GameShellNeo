# MUSB peripheral disconnect ownership across system sleep (NEO-95)

3 October 2026, Pacific/Auckland. This is a source and upstream-history audit,
not a driver qualification. The strongest next experiment is a controller-owned
temporary disconnect across system sleep, retaining the gadget's requested
connection state and reconnecting only when the controller can answer the host.
The evidence points to a missing MUSB system-sleep lifecycle operation exposed
by the Sunxi implementation; it does not establish a Sunxi silicon defect.

The audit used the actual patched tree at `.local/sources/linux-6.18.54`,
including the existing Sunxi PHY detection-work suspend fix. No hardware was
accessed or changed for this report. The original failed sleep record remains
failed. [Report 125](125-traced-rtc-wake-usb-failure.md) is the authoritative
record of the reproduction and its limits.

## Evidence and a directly relevant upstream proposal

The GameShell capture shows a combined `0x2d` USB interrupt inside MUSB resume,
followed by ECM endpoint disable and `USB_STATE_NOTATTACHED`, with no subsequent
enumeration in the bounded trace. The Mac no longer saw the USB device and had
not slept during the attempt. Five-second PM debug tests had passed; the actual
roughly 30-second sleep failed. This is consistent with the host exhausting its
enumeration attempts while the peripheral cannot service them, but does not
prove that sequence electrically. [Report 125](125-traced-rtc-wake-usb-failure.md)
records the combined status as one observation, not independently timed bus
events.

There is a particularly close primary-source report: Nguyen Minh Tien's
27 September 2026 patch proposal describes a T113-S3 Sunxi board losing its
gadget connection after s2idle. Its proposed explanation is that session teardown
with SOFTCONN still set lets the peripheral present itself while interrupts are
masked. The patch saves context, clears SOFTCONN for sleep, and relies on context
restoration to reconnect. The author reports 30 successful patched Sunxi cycles
and a BeagleBone Black comparison. These are the author's results on different
hardware, not GameShell qualification. [Original patch email](https://lkml.rescloud.iu.edu/2609.3/07285.html).

Andreas Kemnade's 30 September reply says that other glue implementations power
off the PHY, hiding this difference, and asks for that distinction to be
documented. This supports auditing the shared lifecycle rather than naming a
new silicon quirk. Neither the proposal nor this reply establishes that the
patch was accepted or merged. It is absent from the pinned implementation.
[Author reply](https://lkml.rescloud.iu.edu/2609.3/15700.html).

The proposal is useful evidence, but its small register change does not address
the asynchronous gadget worker, an intervening request to stay disconnected,
or reconnect timing within context restoration. Those need explicit treatment
in a maintainable local candidate.

## What the pinned source actually owns

Paths in this table are relative to `.local/sources/linux-6.18.54`.

| Source and function | Relevant behavior and consequence |
| --- | --- |
| `drivers/usb/musb/musb_core.c:musb_suspend()` | Acquires one runtime-PM reference; failure balances it with `pm_runtime_put_noidle()`. Disables platform/interrupt processing, drains `irq_work`, ordinarily clears DEVCTL, then saves context. Peripheral forced disconnect is still a FIXME. The successful reference is retained until system resume. |
| `musb_core.c:musb_save_context()` / `musb_restore_context()` | Saves POWER including SOFTCONN. Restore writes POWER before restoring most endpoint registers, preserving the live SUSPENDM/RESUME bits. A saved asserted pull-up therefore reconnects early unless the sleep path masks it. These helpers are shared with runtime PM. |
| `musb_core.c:musb_resume()` | Restores context, enables interrupts/platform, restores fixed-host session where appropriate, runs queued resume callbacks under `musb->lock`, then releases the system-suspend runtime reference. It does not explicitly reconcile peripheral connection intent. |
| `drivers/usb/musb/musb_gadget.c:musb_gadget_pullup()` | Stores the latest request in `softconnect` under `musb->lock` and queues `gadget_work` when it changes. `softconnect` is intent, not proof of enumeration. |
| `musb_gadget.c:musb_gadget_work()` / `musb_pullup()` | The worker gets runtime PM, takes the controller spinlock, and applies SOFTCONN from the current intent. It does not currently gate system sleep, check the PM-get result, or check that a gadget driver remains bound. |
| `musb_gadget.c:musb_gadget_start()` / `musb_gadget_stop()` / `musb_gadget_cleanup()` | Start resets intent and installs the driver; stop clears the driver under the controller lock. Cleanup cancels gadget work before unregistering the UDC. A new resume path must account for work queued by unregister/disconnect as well as work that predated cleanup. |
| `musb_gadget.c:musb_g_disconnect()` / `musb_g_reset()` | Own gadget protocol transitions and callbacks. Disconnect drops and reacquires `musb->lock` around the gadget driver's callback. It is not a helper that preserves uninterrupted ownership of that lock. Reset can return OTG state to peripheral without having completed host enumeration. |
| `drivers/usb/musb/sunxi.c:sunxi_musb_interrupt()` | Reads and acknowledges the supported interrupt registers, adjusts EP0 address on reset, then calls the core handler under the controller lock. The combined status must remain visible to this normal path. |
| `sunxi.c:sunxi_musb_disable()` / `sunxi_musb_enable()` | Disable clears a glue flag; it does not synchronously power down the peripheral PHY. Enable sets the flag and schedules glue work. Calling enable alone is not a general proof that all asynchronous PHY/role work has finished. |
| `drivers/phy/allwinner/phy-sun4i-usb.c:sun4i_usb_phy_suspend()` / `sun4i_usb_phy_resume()` | The local fix disables and drains detection work during system sleep, then reenables it and schedules cable reconciliation. It does not turn a controller SOFTCONN request into a safe system-sleep disconnect. |

The controller's `is_peripheral_active()` macro means only `!is_host`;
it does not mean a gadget is bound, configured, or transferring. `is_suspended`
means USB bus suspend, and `is_runtime_suspended` means runtime PM. Neither is
an appropriate substitute for a new system-sleep ownership flag. See
`drivers/usb/musb/musb_core.h` for those definitions.

There is relevant regression history. Commit `17539f2f4f0b` removed a broad
`musb_start()` call from resume because it overwrote the restored SOFTCONN bit
and broke enumeration on DM3730. This is a concrete reason to preserve requested
pull-up state instead of restarting the whole controller indiscriminately.
[Upstream commit](https://github.com/torvalds/linux/commit/17539f2f4f0b).
Commit `7f88a5ac393f` subsequently restored the fixed-host SESSION operation that
the narrower resume lost. Host restart and peripheral connection are separate
responsibilities. [Maintainer's stable backport email](https://lkml.iu.edu/2006.1/03170.html).

The older interrupt-masking change `6fc6f4b87cb3` itself fixed interrupts arriving
before controller restart on AM335x. Moving interrupt enable ahead of valid
controller state would risk reintroducing that class of failure.
[Upstream commit](https://github.com/torvalds/linux/commit/6fc6f4b87cb3).

## Candidate scope

Prefer an initially narrow shared-core policy for **fixed peripheral mode**
whose USB system wake is disabled, excluding `MUSB_PRESERVE_SESSION` for the
first candidate. In concrete terms: `port_mode == MUSB_PERIPHERAL`,
`!device_may_wakeup(dev)`, and no preserve-session quirk. Implement the transition
beside MUSB's existing system PM and gadget connection ownership. This expresses the required
behavior directly: a peripheral that cannot answer or wake promptly must cease
advertising itself while its system sleeps. The GameShell device tree selects
`dr_mode = "peripheral"`. Preserve host and OTG paths, including SESSION handling,
and leave unrelated runtime autosuspend behavior unchanged.

That recommendation needs a companion CPI policy change: USB system wake is
currently **enabled**. The parent investigation read the live MUSB device's
`power/wakeup` through the existing read-only device task and saved
`.local/neo95-musb-wakeup-policy.txt`. In the pinned
`musb_init_controller()`, successful `enable_irq_wake()` is followed by
`device_init_wakeup(dev, 1)`, with an explicit FIXME about wake IRQ handling.
Absence of a DT `wakeup-source` property does not prove wake policy is disabled.
Set the board's default USB `power/wakeup` policy to disabled through normal
image/device configuration, consistent with the user's power-button/RTC wake
requirements and permission to disconnect USB during sleep. Check that policy
explicitly at test admission. Do not silently change every MUSB platform's
probe-time default. This is a choice of wake source, not a userspace reconnect
workaround. The system-wakeup flag is different from `musb->may_wakeup`, which
records the host's permission for USB remote wake. The PM documentation makes
this capability/policy distinction explicit. [Device PM documentation](https://docs.kernel.org/driver-api/pm/devices.html).

Disabling the policy flag does not itself balance the driver's existing
probe-time `enable_irq_wake()` call. The candidate must not claim that it fixes
hardware wake-IRQ ownership merely by selecting a no-wake policy. Auditing the
old unconditional wake-IRQ setup is separate from preventing the peripheral
pull-up from advertising an unavailable controller.

A Sunxi opt-in flag could contain deployment risk while only CPI v3.1 is tested,
but should be documented as a limited initial enablement, not a demonstrated
Sunxi-specific hardware defect. It is weaker architectural evidence than the
fixed-role/wakeup policy. Conversely, enabling forced disconnect for every
MUSB peripheral would change wake-enabled devices and `MUSB_PRESERVE_SESSION`
platforms such as DA8xx without qualification. Do not expand that behavior based
only on the GameShell trace or another board's 30 reported cycles.

## Required transition invariants

The following is a design recommendation derived from the source, not a claim
that a tested implementation already exists.

1. **Keep intent distinct from temporary suppression.** Leave `softconnect`
   unchanged when system sleep temporarily removes the pull-up. A separate
   controller-owned system-sleep gate suppresses physical connection. Pull-up
   requests during the gated interval still update intent, so a request to stay
   disconnected is honored after resume. Do not restore a stale saved boolean
   over a newer request.
2. **Quiesce asynchronous ownership before touching the session.** After
   successfully obtaining the system-suspend runtime reference, set the gate
   under `musb->lock`. Producers must not queue new connection work while gated;
   the worker must also check the gate under the same lock. Drain/cancel pending
   `gadget_work` outside the spinlock. A worker already executing before the
   gate must finish before detach and context save proceed. Cancellation alone
   does not exclude racing enqueues. The workqueue API documents that limitation.
   [Workqueue documentation](https://docs.kernel.org/core-api/workqueue.html).
3. **Detach before session teardown.** Clear only SOFTCONN through the supported
   POWER access while hardware is runtime-active, before DEVCTL/session teardown
   can expose an unserviceable new session to the host. Keep the pull-up absent
   throughout sleep and context restore. Either save the physically detached
   POWER value or mask SOFTCONN during gated restore; do not let saved context
   silently reconnect it early. Do not modify SUSPENDM/RESUME semantics.
4. **Reconnect only after readiness.** Complete controller/endpoint restoration,
   interrupt/platform setup and existing queued-resume work before clearing the
   gate and applying the latest request. Serialize that final decision with
   pull-up requests and gadget stop under the controller lock. Require a still
   bound gadget and the qualifying peripheral role. For glue with asynchronous
   PHY preparation, establish the actual readiness dependency rather than
   assuming that scheduling glue work means it has completed. The fixed Sunxi
   peripheral path and resumed PHY supplier need an explicit source audit.
5. **Leave protocol events to their proper owner.** Preserve normal interrupt
   acknowledgment and the documented stage-0 handling order. Fresh host reset
   and enumeration should reconstruct the configuration. If the implementation
   deliberately adds an immediate logical disconnect callback, it needs a
   separate lifetime/serialization argument and must avoid duplicate callbacks;
   merely calling `musb_g_disconnect()` under a lock does not provide one. Do not
   set CONFIGURED, carrier, or gadget speed to simulate recovery.
6. **Balance PM references on every path.** One successful system-suspend get
   must have exactly one matching release on resume or local rollback. Each
   worker owns only its own temporary reference. A failed PM get must not access
   registers. `pm_runtime_get_sync()` increments even when it fails;
   `pm_runtime_resume_and_get()` avoids that failure-side increment. A focused
   worker correction should preserve these documented semantics and report the
   failure rather than writing to an unavailable controller.
   [Runtime PM documentation](https://docs.kernel.org/power/runtime_pm.html).
7. **Unbind and remove win over reconnect.** A queued or currently running
   reconnect must not outlive `musb_gadget_stop()` or controller teardown.
   Clear connection intent/invalidate the driver under the same synchronization
   used by the final reconnect; drain outside it before resources disappear.
   A sleep gate only prevents sleep-time races: it does not replace a lifecycle
   rule for normal unbind or remove. A stop followed by a new bind must not replay
   the old instance's intent. Check unregister-generated work, not just work
   present before `usb_del_gadget_udc()`.
8. **Abort must restore functionality.** If another device aborts suspend after
   MUSB successfully suspended, normal MUSB resume must ungate and restore its
   latest request. If MUSB itself fails after changing state, it must undo those
   changes locally before returning the error. `drivers/base/power/main.c`
   marks a device suspended only after its callback succeeds and skips resume
   for a device not marked suspended. A failed callback cannot depend on a later
   resume to clean up its own partial operation. Resume failure must keep the
   gadget safely disconnected and retain an observable error, not advertise a
   ready peripheral.

The public `usb_gadget_disconnect()` / `usb_gadget_connect()` pair is not a
drop-in temporary gate. In the pinned `drivers/usb/gadget/udc/core.c` these take
`connect_lock`, alter UDC connection intent and may invoke the gadget disconnect
callback under the UDC mutex. They cannot be called under `musb->lock`, and
blindly reconnecting afterward can overwrite an intentional user/function
disconnect. Their semantics are useful to contrast with the controller-local
temporary suppression described above.

Do not assume UDC core automatically makes a new PM-time manual callback safe:
the pinned MUSB gadget operations provide no `udc_async_callbacks` hook, and
MUSB does not populate `gadget.irq`. The UDC unbind path calls its optional
async-disable operation and only synchronizes `gadget.irq` when nonzero.
Introducing new callbacks during this interval therefore needs an explicit
lifetime solution. Direct connection suppression followed by normal IRQ/reset
handling avoids adding that new callback path. Sources:
`musb_gadget.c:musb_gadget_operations`, `musb_core.c:musb_init_controller()`,
and `drivers/usb/gadget/udc/core.c:gadget_unbind_driver()`.

Likewise, do not call synchronous work cancellation while holding a spinlock
the worker needs. Do not add a PM get under that spinlock. The existing ordinary
worker order is PM get, controller lock, supported-register update, unlock,
PM put; preserve that order. No new lock may invert it through system resume.

## Source-level regression scenarios

Tests should execute the candidate's actual transition code with controlled
register/PM/workqueue boundaries where practical. A duplicated state-machine
model or assertions that merely search for expected strings are insufficient
evidence of these properties. Cross-compilation complements those tests; it
does not model physical bus enumeration.

| Scenario | Required result |
| --- | --- |
| Connected fixed peripheral, successful sleep/resume | Intent stays on; physical pull-up is off before session teardown and throughout restoration; reconnect is last; system and worker PM references return to baseline. |
| Intent already off | No forced connect during suspend, restore, or resume. |
| Worker queued before gate, or already inside PM get | Gate plus drain prevents a late pull-up write after detach; no spinlock/workqueue deadlock. |
| Request off during gate; on/off requests interleaved with final resume | Latest serialized intent wins; no stale reconnect. |
| Restore entered with saved SOFTCONN on | Gate prevents premature reassertion before endpoints/interrupt handling are ready. |
| Runtime resume with no system-sleep gate | Existing context/connection behavior remains; no system disconnect or extra persistent reference. |
| Runtime-PM get fails | No MMIO, balanced usage count, recorded error; an unowned reference is never put. |
| Immediate suspend abort and later-device abort | Gate/work eligibility and connection return to a functional state; no reliance on the full sleep delay for host disconnect recognition. |
| Unbind during queued work; remove; stop then rebind | No register access after teardown, no stale callback/driver dereference, no old intent replay or pending reconnect after stop. |
| No gadget driver, absent VBUS, cable removed during sleep | No fabricated configuration; future real attach follows ordinary detection/IRQ paths. |
| Fixed host, dual-role/OTG, wake-enabled peripheral, preserve-session platform | The initial policy either excludes these branches or has separately justified behavior; host SESSION and role transitions remain unchanged. |
| Combined suspend/disconnect/reset status on resume | Normal acknowledgment and stage-0 order remain; events are neither reordered nor discarded to obtain a green result. |

For an aborted short transition, validate that the host can observe the detach
and new attach. If a minimum off interval is required, derive it from the
controller/USB timing contract and test it; do not introduce an arbitrary long
sleep or repeated gadget restart as a substitute for lifecycle correctness.

## What still needs hardware evidence

A source-correct candidate remains experimental until a fresh image passes its
startup and PM debug gates, then separately attended actual sleep with the
cable untouched. Capture both host and device, retain a pre-test Mac sleep/wake
record, and require fresh enumeration, ECM endpoint activation, link carrier,
independent USB SSH and Wi-Fi SSH, unchanged boot, keypad retention, normal
console, restored PM/RTC/trace settings and balanced reference counts. A kernel
PM success increment alone remains insufficient.

Then repeat actual sleep, separately check physical reconnect and host sleep,
and qualify sleep with USB absent. A longer asleep interval and an immediate
abort exercise different host timing from the five-second debug delay. A new
kernel can change trace timing and accepted prerequisites; do not reuse the
consumed diagnostic.17 baseline or rewrite its failed record.

The current evidence does not prove electrical D+ transitions, exact host retry
timing, improved power draw, reliable remote USB wake, other board revisions,
or non-Sunxi behavior. It supports implementing and testing the lifecycle
correction while continuing to describe those properties as unqualified.

The audited files' SHA-256 values identify the source inspected before a new
candidate changes it:

```text
musb_core.c   84aff85f1b7485075252491d3d63ae2037d497a66eeaea070a8d5501f6ce78b8
musb_gadget.c c0948905903b9e2998408d01adefbb69195bd493f165c209b350e019760a97a4
sunxi.c      6ea162efa73eec96923b424f8550133bfd62d8bbd5515b139d29a8d7f28f11d3
```
