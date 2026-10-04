# Retiring the USB session before system sleep

4 October 2026. NEO-112; diagnostic.19 candidate for CPI v3.1.

Diagnostic.18 physically disconnected its USB pull-up for sleep without retiring
the gadget's logical session. When the owner removed the cable during sleep,
RTC wake and the display worked, but USB still reported configured/carrier1 even
though the supply and PHY reported absence. [Report 153](153-usb-removal-sleep-state-failure.md)
preserves that failed original. This candidate closes the logical session during
the deliberate sleep detach, before saving controller context. Hardware
qualification remains outstanding; no live recovery or new sleep was attempted
during this implementation.

## Driver changes

[Patch 0033](../kernel/patches/0033-musb-sleep-session-retirement.patch) builds on
0025's fixed-peripheral, non-wakeup detach path. It masks controller interrupts,
drains any in-flight controller IRQ outside the controller lock, finishes the
existing deferred-work drain, then calls `musb_g_disconnect()` under the lock
if a negotiated session remains. Context saving follows. The system-PM reference
still holds the controller powered while the function driver disables endpoints.

The normal disconnect callback retires the ECM connection and its data endpoint
requests; UDC state becomes not-attached and negotiated speed becomes unknown.
No userspace gadget restart, carrier write or synthetic PMIC interrupt is used.
The existing pull-up intent survives unless the callback explicitly changes it.
Resume restores controller/IRQ readiness before applying that intent, allowing
a connected host to enumerate a fresh session. An absent host need not produce
another edge to retire the previous session.

Disconnect notification is admitted only while negotiated speed is known. Speed
is cleared before dropping the lock for the callback. Nested or delayed duplicate
disconnect paths therefore cannot notify the same retired session again. This
also changes duplicate notification outside PM; ordinary first disconnect and
next-session behavior are covered in the source tests.

[Patch 0030](../kernel/patches/0030-musb-gadget-callback-lifetime.patch) is a
prerequisite, selected unchanged from the separately prepared callback-lifetime
candidate in [report 137](137-musb-gadget-callback-lifetime.md). It admits and
counts asynchronous gadget callbacks under the controller lock, retains the
admitted driver pointer while dropping that lock, and drains outstanding
callbacks before UDC unbind. Request completions remain available during
teardown. This prevents the added process-context disconnect notification from
relying solely on IRQ synchronization for function-driver lifetime.

The other prepared wake-policy, startup, CPU-idle, battery and controller-removal
candidates are not included. Full controller destruction, pending runtime-resume
request ownership and arbitrary EP0/DMA cancellation remain separate work.

## Why removal interrupt counts can remain zero

The locked Linux 6.18.54 source provides a reproducible explanation independent
of the stale gadget state:

1. Both AXP AC and USB supply suspend callbacks mask their removal interrupts.
   Enabling insertion as a wake source does not keep removal enabled.
2. The AXP22X regmap IRQ chip uses `init_ack_masked = true`, enable registers at
   `0x40`, and status/acknowledge registers at `0x48`.
3. `regmap_irq_sync_unlock()` acknowledges masked status bits during mask
   synchronization. A synchronization before removal is unmasked can clear a
   latched removal without dispatching its nested handler.
4. Resume and PHY reconciliation can still read the current supply/cable state.
   A later awake insertion can dispatch normally.

The original trace resumes PEK at monotonic 1663.515369, AC at 1663.516688,
USB at 1663.518013 and PHY at 1663.519704. This is consistent with an intervening
shared-regmap synchronization. It does not prove that this particular physical
edge latched, or identify the exact acknowledge transaction on the board.

The saved `test:power-irq-mask` task extracts the actual locked regmap enable,
disable and synchronization functions and AXP22X bit mappings. Six native/ARM32
scenarios reproduce lost masked dispatch with either supply ordering and with
insertion wake enabled or disabled; awake removal and a no-masked-ack control
remain observable. Two deliberately broken variants must fail assertions.
Registers, electrical edges and nested dispatch are modeled boundaries.
There is no PMIC driver, wake policy, charging or register-setting change.

## Prospective diagnostic criteria

Diagnostic.19 explicitly records `sleep_cable_irq_policy = masked-removal-v1`
in its source lock. Matching installed-image features and kernel identity are
required by PM admission. Only this opted-in CPI v3.1 removal case permits
zero or one dispatch for each removal handler, with no insertion dispatch,
counter regression or extra dispatch. The original exact-count policy remains
the default for older images. Attachment still requires one insertion dispatch
per supply; awake rehearsal still permits no transition.

This corrects an overstrong assumption in the first diagnostic: a masked handler
is not a reliable electrical-edge counter. All endpoint gates remain mandatory:
absent AC/USB, absent PHY, not-attached UDC and carrier0 after removal; unchanged
boot/image/input ownership, clean PM return, RTC/trace evidence and independent
Wi-Fi recovery are still required. Physical action and normal display return
remain separately reported by the owner. A stored `cable_irq_observation` records
actual deltas and whether both handlers ran; accepted results revalidate it.
No record claims precise electrical timing or energy qualification.

This policy does not reclassify report 153. Its original result and observer
report remain failed and unchanged, including the genuine stale UDC/carrier
failure. Updated helper sources require fresh prerequisites and an awake
rehearsal; the old consumed baseline cannot admit another sleep.

## Repeatable verification

```sh
task check
task check:musb-sleep-configs
task test:power-irq-mask
```

The sleep harness executes 68 actual-source scenarios, including cable absent
or retained, pending IRQ before retirement, duplicate disconnect, callback-driven
connection changes, closed unbind admission and the existing role/wake/quirk
and resume-failure cases. The callback harness executes 134 actual-source
scenarios, including request completion from disconnect and duplicate callback
suppression. Both run natively and on ARM32; 21 broken variants must fail
assertions. Native callback concurrency uses pthread-controlled boundaries,
not the kernel scheduler or IRQ implementation.

The driver build matrix covers the board peripheral configuration, host-only,
dual-role, modules, no system sleep, and no PM. The module case links the MUSB
objects and checks shared callback-helper symbols. Full-image kernel compilation
and linking are separate from these focused object builds.

Repository checks pass 13 runtime and 548 tooling tests (two existing optional
skips), compiled C checks and ShellCheck. Seven new host tests exercise masked
dispatch combinations, unchanged strict cases, stale endpoints, image/kernel
binding, tampered assessments and failed-original preservation. Both patches
pass the locked kernel's checkpatch with zero errors and warnings.

Private evidence lives in the isolated worktree's `.local/build/musb-sleep-tests/`
and `.local/build/power-irq-mask-tests/`, with saved logs. The final matrix records
patch/harness, archive, toolchain, configuration and object hashes.

## Image and hardware handoff

The candidate identity is `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19`.
Diagnostic.18 was checkpointed as `diagnostic18-before-session-retirement` before
changing the build. The existing retention task verified recovery copies before
removing one older raw image and two older kernel snapshots, reclaiming about
4.74 GiB. The newest three of each were retained at that point.

Build/image hashes and offline verification will be recorded after completion.
The candidate must then pass flash/readback, startup and awake checks, fresh
attended debug prerequisites, an unchanged-cable RTC comparison, and a fresh
removal rehearsal/one-shot with separate physical observations. Attachment needs
its own baseline afterward. Normal sleep remains masked; neither faster resume
nor lower energy consumption is claimed.

The running diagnostic.18 was left untouched. Its failed-test power-key
suppression remains pending deliberate recovery; do not ask for short-button
shutdown while that guard is retained. A later card swap should follow a
confirmed remote shutdown and the normal physical handoff.

## Pinned source map

- `drivers/usb/musb/{musb_core.c,musb_gadget.c,musb_gadget_ep0.c}`: PM detach,
  IRQ/work ordering, callback ownership, disconnect and endpoint completion.
- `drivers/usb/gadget/{composite.c,function/f_ecm.c,function/u_ether.c}`:
  function disconnect, endpoint disable and ECM link retirement.
- `drivers/usb/gadget/udc/core.c`, `include/linux/wait.h`: callback admission,
  unbind and locked-condition drain.
- `drivers/power/supply/{axp20x_ac_power.c,axp20x_usb_power.c}`: supply PM masks.
- `drivers/mfd/axp20x.c`, `drivers/base/regmap/regmap-irq.c`: AXP22X IRQ mapping,
  mask synchronization and acknowledge semantics.

All are read from the archive pinned by [sources.lock.json](../build/sources.lock.json),
with the repository patch queue applied where relevant.
