# Fixed-peripheral USB polling policy

Date: **2026-09-28 NZDT**. Ticket: **NEO-15**.
Scope: design for the owner's **CPI v3.1**, using the locked Linux
`6.18.54` source and diagnostic.3 configuration. This report proposes an
experiment; no policy described here has been deployed.

Subsequent implementation: [report 41](41-usb-polling-experiment.md) records
diagnostic.5 preparation and the reusable policy/compiled-DTB tests. Physical
qualification remains pending. Diagnostic.4 is the newer tested recovery
baseline; the diagnostic.3 references below describe this design's original
source/evidence context.

## Decision

Develop a small, explicitly enabled experiment that retains USB interrupts and
changes the recurring **confirmed-absent** status read from 50 ms to 250 ms.
Retain fast reads for unknown state, read errors and VBUS present without the
input being used. Retain the existing interrupt-driven behavior while online.
Do not eliminate polling or change PMIC charging, protection or pin modes.

The source supports this narrower experiment because this image already builds
MUSB in gadget-only mode and the sunxi glue rejects runtime changes away from
the fixed peripheral role. The familiar MUSB 100 ms VBUS-rise warning concerns
the A-device/source transition. It is not, by itself, a reason to reject a
slower absent check on an enforced peripheral. Peripheral connect timing still
matters and must be tested; neither a 250 ms timer nor the existing captures
establishes a physical timing guarantee. The evidence and limits are detailed
below.

This refines [report 34](34-usb-status-polling-investigation.md), which correctly
kept the shared 50 ms workaround until the role and power path were understood.
[Report 35](35-usb-detection-capture.md) establishes interrupt delivery in the
tested peripheral state, with substantial observer overhead. Its software
notifications preceded sampled plug-counter changes by approximately
67–122 ms. An IRQ-first design may therefore respond later than the current
polling path even when no interrupt is lost.

## What the 100 ms warning means

The relevant upstream history is specific. The 2015 AXP221 workaround polls
while the board drives VBUS; the 2018 AXP223/A33 extension reports MUSB timing
out while waiting for that sourced VBUS to rise. The later power-supply change
moved frequent polling into the PMIC driver because that driver could not know
which USB roles needed rapid detection.
[AXP221 workaround](https://github.com/torvalds/linux/commit/91d96f06a760f5f36586e972281e239bb9508596),
[AXP223/A33 failure](https://github.com/torvalds/linux/commit/d7119224bfe6e8efbf821a52db7da9530d790f07),
[PMIC polling change](https://github.com/torvalds/linux/commit/97ec136e7124fa12cf56ce706993e747c5f99a20).

The locked source connects that history to the current implementation:

- `musb_core.h` defines `OTG_TIME_A_WAIT_VRISE` as 100 ms and identifies it as an
  OTG protocol timer. In `musb_core.c`, the session-request path enables VBUS
  and moves through the A-device states; the comment associates the rise
  timeout with `VBUS_ERROR`.
- `sunxi_musb_work()` enters `A_WAIT_VRISE` and requests PHY power when host
  mode is selected. Its peripheral branch instead selects `B_IDLE` and clears
  the session bit.
- `sun4i_usb_phy_power_on()` enables the VBUS regulator, then requests a 50 ms
  detection scan specifically to meet `OTG_TIME_A_WAIT_VRISE`. The ordinary
  recurring PHY polling interval is already 250 ms; that separate fast scan
  is what protects the initial source transition.

Sources: [MUSB constants](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_core.h),
[MUSB core](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_core.c),
[sunxi glue](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/sunxi.c),
[sun4i PHY](https://github.com/gregkh/linux/blob/v6.18.54/drivers/phy/allwinner/phy-sun4i-usb.c).
The same functions were inspected in `.local/sources/linux-6.18.54`.

**Inference:** the source's A-device rise deadline does not apply unchanged to
the GameShell waiting for an external host to provide VBUS. This does not make
peripheral insertion timing unrestricted, nor justify weakening a generic
AXP223 driver used by host/OTG boards.

### Separate USB peripheral timing

The USB-IF **USB 2.0 Connect Timing Update** ECN, pages 4–6, distinguishes:

| Interval | Meaning |
| --- | --- |
| `TSVLD_CON_PWD`, maximum 1 second | VBUS becoming session-valid to an already powered peripheral indicating connect on D+/D− and being ready for enumeration. |
| `TCON_RST`, minimum 100 ms | Host software debounce after the peripheral indicates connect, before reset. |
| `TUNIT_CON`, maximum 100 ms | Time the applicable peripheral may draw unit-load current before connecting. This is a separate current/timing condition. |

The ECN replaces the original powered-peripheral connect maximum of 100 ms
with 1 second. It does not replace MUSB's host-side A-device rise timer, and
the host's debounce period is not spare time before the peripheral connects.
Source: [USB-IF USB 2.0 specification package](https://www.usb.org/document-library/usb-20-specification),
[official archive](https://www.usb.org/sites/default/files/usb_20_20250603.zip),
member `usb_20_20250603/usb_20_20240927/usb_20_20240927/Connect Timing ECN.pdf`.

The archive and text extraction were obtained directly from USB-IF on the
research date and retained privately under `.local/research/neo15-usb-timing/`.
Archive SHA-256: `5fe9c53c04033818af396e8852b3acbca5c3a76ba92fab549fd81cd0ea7b3692`.
ECN PDF SHA-256: `31528541e9d829b1401fd0c747829012c56e6d6d6b12d8f1591ff4cb6549b73b`.

**Implication, not a compliance result:** a nominal 250 ms fallback plus the
PHY's 50 ms debounce leaves a plausible budget inside the powered-peripheral
connect interval. Scheduling, register access, power-supply notification and
gadget readiness also consume time. Our capture does not timestamp physical
VBUS or D+/D−, and USB input-current behavior is not qualified by this study.
USB SSH recovery time is a useful functional measure, not the ECN's connect
timestamp. This reasoning addresses the awake, gadget-ready case; it does not
qualify cold boot, weak-battery startup or future deep-sleep recovery. The
unresolved battery-voltage discrepancy remains NEO-10.

## How this board reports VBUS

The board DTS connects USB0's PHY to the AXP223 USB power supply. The PHY reads
`POWER_SUPPLY_PROP_PRESENT`, rather than `ONLINE`. Its supply notifier
schedules a scan with a 50 ms debounce; the scan updates the PHY's forced VBUS
state and `EXTCON_USB`. Fixed peripheral mode makes its ID result high. The
sunxi glue subscribes to the PHY's `EXTCON_USB_HOST` state; it does not provide
an independent, faster VBUS-voltage sensor.
[Board DTS](../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts),
[PHY source](https://github.com/gregkh/linux/blob/v6.18.54/drivers/phy/allwinner/phy-sun4i-usb.c),
[glue source](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/sunxi.c).

Consequently, delaying a PMIC notification can delay the controller seeing
VBUS. The 250 ms fallback has a real responsiveness cost. Its benefit is fewer
otherwise repetitive battery-mode status reads, while an interrupt can still
bring the next read forward. The NEO-14 ordering supports treating that cost
as something to measure, not claiming IRQ delivery is always the fastest path.

There is also an inherited PHY limitation: a failed supply-property read falls
back to VBUS high. A successful PMIC worker read and a later PHY property read
are separate operations; fixing retries in one does not prove error handling
in the other. Include this distinction in fault testing and do not interpret
every reported high state as a confirmed successful voltage read.
[PHY `sun4i_usb_phy0_get_vbus_det()`](https://github.com/gregkh/linux/blob/v6.18.54/drivers/phy/allwinner/phy-sun4i-usb.c).

The supplied AXP223 datasheet and the published Clockwork schematic remain the
electrical references summarized in report 34. NEO-14 read `0x30=0x60` and
`0x8f=0x01`, consistent with the low DRIVEVBUS output configuration. These
control-register reads may be cached and are not a measurement of the pin.
The proposed fallback deliberately avoids requiring a claim that every future
physical insertion must generate an IRQ. It does require the software to remain
in the qualified peripheral topology.
[AXP223 datasheet](../allwinner/extracted/R16/Firmware/AXP223%20Datasheet%20V1.1%2020131128.pdf),
[Clockwork schematic](https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/clockwork_Mainboard_Schematic.pdf).

## Enforcing the narrow role contract

This image has stronger restrictions than a peripheral string in a DTS:

1. [The kernel fragment](../kernel/gameshellneo.config) already selects
   `CONFIG_USB_MUSB_GADGET=y`. The resolved `.local/build/kernel/.config` has
   MUSB host and dual-role disabled. MUSB's Makefile excludes its host/virtual
   hub objects in that configuration. Separate EHCI/OHCI support remains
   enabled for the keypad; gadget-only MUSB does not disable those controllers.
   [MUSB Kconfig](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/Kconfig),
   [MUSB Makefile](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/Makefile).
2. With that build configuration, `sunxi_musb_probe()` accepts the peripheral
   DT role but cannot select its compiled-out host/OTG probe branches.
3. The generic MUSB sysfs `mode` file accepts a request and delegates it to the
   platform. `sunxi_musb_set_mode()` accepts the existing mode but rejects a
   different mode unless the instance's `port_mode` is `MUSB_OTG`. Therefore
   writing `host` or `otg` cannot switch the fixed-peripheral instance through
   this API. This conclusion is from source inspection; no mode-changing write
   was attempted on the device.
   [MUSB `mode_store()`](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/musb_core.c),
   [sunxi role guard](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/musb/sunxi.c).

The generic PHY's own `set_mode()` can change its role and the extcon host
notifier is not independently a fixed-role guard. Thus the contract includes
the actual PHY/controller graph and the existing consumer implementation;
gadget-only Kconfig alone is not a universal prohibition on all possible PHY
clients. Any future role-switching driver, DT overlay or USB0 supply-control
change requires requalification before enabling this policy.
[PHY mode setter](https://github.com/gregkh/linux/blob/v6.18.54/drivers/phy/allwinner/phy-sun4i-usb.c).

The proposed activation checks are all required:

| Gate | Required result |
| --- | --- |
| Explicit experimental selection | Proposed local parameter `axp20x_usb_power.gameshellneo_slow_poll=1`, immutable at runtime and default disabled. This is an experimental project policy, not a new generic DT hardware property or an upstream API claim. |
| PMIC and board | AXP223 USB supply on the expected CPI board compatible. Other chips/boards retain stock behavior. The root compatible does not itself distinguish every physical CPI revision; qualification remains limited to the owner's v3.1. |
| Build mode | MUSB gadget enabled; MUSB host and dual-role disabled. Preserve the existing sunxi mode guard. |
| Supply-to-PHY graph | Exactly the expected enabled A33 PHY uses this supply through `usb0_vbus_power-supply`. Reject missing, ambiguous or alternate GPIO VBUS detection. |
| PHY-to-controller graph | One enabled expected A33 MUSB consumer of PHY index 0, explicitly peripheral. Reject ambiguous or additional consumers. |
| VBUS sourcing | No `usb0_vbus-supply`, PMIC `x-powers,drive-vbus-en` property or alternate USB0 source-control path in this diagnostic topology. USB1 keypad supply is separate. |
| PMIC startup configuration | Normal regmap reads succeed with `0x30` bits 7 and 2 clear, and `0x8f` bit 4 clear, consistent with the observed non-driving configuration. No writes or cache bypass. Mismatch/read error retains stock polling. Cached control values do not independently prove pin voltage. |
| IRQ setup | Both expected plug/removal handlers register successfully. Do not check the final IRQ-enable mask before registration has had the opportunity to enable it. |
| Sleep support | The initial experiment requires the current `CONFIG_SUSPEND=n` configuration. Enabling sleep requires a separately proven resume contract first. |
| Future topology changes | Disable the experiment until the changed topology is reviewed and tested. Do not infer safety from a stale state captured before the change. |

Any failed or uncertain policy gate leaves the original policy active and
reports why the experiment was refused. Required IRQ/resource registration
failures still fail probe and unwind; they must not be converted into successful
probe with a missing interrupt handler. A board match must never silently enable it for
all AXP223 devices. Eligibility starts false and stays false until every gate
has completed; early IRQ work therefore cannot select 250 ms prematurely.
No host/OTG DT mutation is supported while the experiment is bound.
`of_usb_get_dr_mode_by_phy()` is useful for reading a role,
but returns the first matching enabled controller; by itself it does not prove
that a consumer is unique.
[USB OF helper](https://github.com/gregkh/linux/blob/v6.18.54/drivers/usb/common/common.c).
The PMIC's `x-powers,drive-vbus-en` property also enables registration of its
drive-VBUS regulator; rejecting it prevents that alternate control path from
silently entering the experiment's topology.
[AXP regulator probe](https://github.com/gregkh/linux/blob/v6.18.54/drivers/regulator/axp20x-regulator.c).

This avoids a new cross-driver runtime policy interface in the first patch.
A broader host/OTG implementation would need such coordination, with fast
detection armed before changing role or enabling the VBUS source. It is outside
this experiment.

## Proposed state and scheduling rules

The table is a design requirement for the candidate, not current behavior.
The 50 ms IRQ debounce and the 250 ms absent fallback must be separate
constants; increasing the existing shared debounce is not the implementation.
The new status-error and recurring-rearm rules apply to the enabled experiment.
The default-off path retains the existing polling behavior, including the
inherited cached-online read-error limitation described in report 34. A generic
retry fix for other boards would be a separate change with its own coverage.

| State or event | Candidate action |
| --- | --- |
| Opt-in disabled or activation gate fails | Existing 50 ms offline polling and existing IRQ behavior. |
| Probe / initial unknown state | Immediate status read; do not start with an assumed absent input. |
| Successful read: `PRESENT=0`, `ONLINE=0` | Queue next fallback read after 250 ms if the experiment is active. |
| Successful read: `PRESENT=1`, `ONLINE=0` | Continue 50 ms reads. This is the state in which presence and input usage differ. |
| Successful normal online state | Existing IRQ-driven behavior, without recurring offline polling. Treat an inconsistent `ONLINE=1`, `PRESENT=0` result as unknown and retry after 50 ms; it must not qualify for quiet operation. |
| Plug/removal IRQ | Preserve immediate supply notification and the 50 ms debounced register read; it must bring a pending slower read forward. |
| Status read error | Preserve last valid state, publish no invented absence, retry after 50 ms even if the last valid state was online. |
| Resume, if supported later | Invalidate slow-policy eligibility, schedule a fresh read, restore IRQ state correctly, and reconcile the contract before re-enabling the slower interval. Firmware may have changed PMIC state while asleep; blindly trusting cached control values is insufficient. |
| Teardown / failed probe | Stop event sources and synchronously cancel work before its referenced state or supply is released. |

For recurring worker rearm use `queue_delayed_work()`, which leaves an already
pending deadline intact. Keep `mod_delayed_work()` for the IRQ's 50 ms request.
Otherwise a worker finishing an absent read could replace a concurrently queued
IRQ's fast deadline with 250 ms. With queue-only recurring rearm, an IRQ queued
first keeps its pending deadline, while an IRQ arriving after the slow rearm
moves that deadline forward. This needs a meaningful race regression test,
alongside the status-state tests.
[Kernel workqueue semantics](https://docs.kernel.org/core-api/workqueue.html),
[locked PMIC driver](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_usb_power.c).

Initialization and resource release order require review during implementation.
Work must be initialized before IRQ registration. Register its managed
cancellation after supply registration and before IRQ registration, so release
frees IRQs, then cancels work, then releases the supply the work references. The locked
driver registers its managed delayed-work cancellation before registering the
power supply; because managed actions unwind in reverse order, this is a
source-level ordering concern to address and test, not an observed GameShell
failure. The original early-IRQ initialization crash is already documented
upstream and must not be reintroduced.
[PMIC probe](https://github.com/gregkh/linux/blob/v6.18.54/drivers/power/supply/axp20x_usb_power.c),
[reverse managed release](https://github.com/gregkh/linux/blob/v6.18.54/drivers/base/devres.c),
[managed work cancellation](https://github.com/gregkh/linux/blob/v6.18.54/include/linux/devm-helpers.h),
[early-IRQ fix](https://github.com/torvalds/linux/commit/b5e8642ed95ff6ecc20cc6038fe831affa9d098c).
Keep a cleanup-order correction separate from the interval-policy change and
test it independently. Disabling the experimental parameter restores polling
behavior; returning to byte-identical driver code requires diagnostic.3.

## Expected benefit and validation

The nominal recurring read rate while confirmed absent changes from roughly
20 per second to roughly 4: **80% fewer calls in that particular steady state**.
That arithmetic excludes IRQs, errors, execution time and other consumers.
It is not an 80% CPU, total RSB traffic or battery-life prediction. The PMIC
already stops recurring reads while online, so this candidate does not promise
an equivalent charging-mode saving. Retain small measured gains if reliability
holds; there is no minimum saving threshold.
Verified reduction of unnecessary recurring work can justify retaining the
candidate even if battery-estimate noise hides the power difference. In that
case, report the reduction in work and leave the battery benefit unproven.

Before enabling an image by default:

1. Test the actual policy decision and scheduling integration: all valid and
   inconsistent bit combinations, opt-in/gate rejection, initial read, transient
   errors with both cached states, IRQ/worker interleavings, probe failure and
   teardown. Test graph ambiguity, not merely the happy-path DTS.
2. Build the candidate with the locked toolchain and preserve the existing
   current-limit/NKMP patches, governor settings, OPPs, voltages and charging
   policy. Compare the resolved config and DT against diagnostic.3.
3. Boot with USB attached and absent, verify the policy's selected/refused
   status, then test four cable cycles and rapid reconnection with Wi-Fi control.
   Confirm stable UDC state, USB SSH recovery and keypad operation. Record
   failures as failures even if evidence can later be recovered.
4. Compare bounded, low-overhead counts of the actual PMIC poll function and
   CPU time in matched battery-only idle conditions. Aggregate RSB interrupts
   are not a direct poll-function count. Run the detailed NEO-14 recorder
   separately for functional correlation; its approximately 41–45% of one CPU
   observer cost makes it unsuitable for measuring a small power optimization.
5. Investigate missed/late IRQs, interrupted supply and read-error recovery in a
   controlled environment. A 250 ms fallback limits a nominal software wait;
   it does not guarantee that a very brief attachment or removal is captured.
   Capture clock limits must remain explicit.

The current resolved kernel has `CONFIG_SUSPEND` disabled. Sleep/resume and
USB wake are not validated by these tests. Enabling suspend later requires
separate lifecycle validation and cannot inherit a pass from cable testing.
Physical USB timing and electrical compliance also remain separate from this
software-only experiment.

Rollback is to boot without the experimental opt-in, retaining the stock
polling policy. Keep the known-good diagnostic.3 image/card recovery route.
If the new image loses USB but Wi-Fi remains available, collect evidence before
reverting; never make USB the only recovery route for testing its detection.
No PMIC mode or charge-register restoration should be needed because this
experiment must not write those settings.

## Work completed for this design

The source, upstream history, official USB timing ECN, resolved local config
and board graph were reviewed. A read-only device health check at
**12:10:32 UTC** found all six monitored services healthy with no restarts,
failed units or kernel taint. USB was detached and the battery reported
81% Discharging at 3.8687 V. Evidence:
`.local/diagnostics/20260927T121027.777790Z/status.txt`.

This ticket changes documentation only. Implementing the guarded policy,
building/flashing it and qualifying its behavior are subsequent work. No new
physical cable test or power-saving result is claimed here.
