# USB status polling investigation

Date: **2026-09-28 NZDT**. Ticket: **NEO-13**. Target: CPI v3.1,
`0.1.0-diagnostic.3`, Linux `6.18.54-gameshellneo3`.

## Finding

There is a plausible opportunity to remove recurring USB-status work while
running on battery, but the existing polling repairs a documented AXP223
interrupt limitation. A change that simply stops polling whenever USB is absent
could reintroduce USB detection failures. First establish the GameShell's USB
role and PMIC input-path state, then measure transitions on the unmodified
driver. This ticket is an investigation; it does not alter the kernel, charging
configuration or USB behavior.

The reason is more specific than an unreliable interrupt in general: when
N_VBUSEN prevents the PMIC using VBUS, a change in physical VBUS voltage can
occur without the plug/removal notification required by a USB consumer. Chen-Yu
Tsai documented this on **AXP223 with A23/A33**, including an A33-OlinuXino
failure in which MUSB timed out waiting for VBUS to rise. This is directly
relevant hardware history, although it is not a measurement of this GameShell.
[AXP223/A33 fix, `d7119224bfe6`](https://github.com/torvalds/linux/commit/d7119224bfe6e8efbf821a52db7da9530d790f07).

## What the installed source does

The locked source is
`.local/sources/linux-6.18.54/drivers/power/supply/axp20x_usb_power.c`.
The following observations come from that local source, including the applied
project patches:

| Item | Behavior |
| --- | --- |
| AXP223 match data | Uses `axp22x_irq_names` and sets `vbus_needs_polling = true`. |
| Interrupts requested | `VBUS_PLUGIN` and `VBUS_REMOVAL`. AXP20x variants additionally request `VBUS_VALID` and `VBUS_NOT_VALID`. |
| Polling decision | `vbus_needs_polling && !power->online`; `online` is the last sampled register bit 4, called `VBUS_USED` in Linux. |
| Delayed work | Reads register `0x00`, retains bits 5 and 4, and calls `power_supply_changed()` only when those retained bits change. |
| Repeat interval | Requeues itself after `msecs_to_jiffies(50)` while the polling condition holds. Execution and register-access time add to that delay; 20 reads/second is an approximate upper cadence, not a measured constant. |
| IRQ handling | Announces a supply change and unconditionally schedules a debounced register read. It does not infer the final state from which IRQ arrived. |
| Initial state | Zero-initialized `online` causes an initial immediate poll for AXP223 after IRQ registration. |
| Resume | Re-enables the IRQs as appropriate and schedules a status read even if the cached state had been online. |
| Getter semantics | `PRESENT` reads physical presence bit 5; `ONLINE` reads bit 4. These are separate properties and both are read from hardware. |

Consequently, no cable normally means `online = 0` and continuing workqueue/RSB
activity. Stable external power with `online = 1` stops this recurring loop.
A zero count for plug/removal IRQs after booting with the cable already attached
does not demonstrate an interrupt fault: there may have been no transition
since the handlers were registered.

The three relevant functions—`axp20x_usb_vbus_needs_polling`,
`axp20x_usb_power_irq` and `axp20x_usb_power_poll_vbus`—were compared with the
current upstream file retrieved on the research date. They are identical at
upstream revision `93e4b3076b5f2d853462b9777d083c77fc0b7b23`; therefore there is
no already-merged polling fix in that compared source to adopt. This is a
statement about these functions, not every difference between kernels or every
pending patch.
[Pinned upstream driver](https://github.com/torvalds/linux/blob/93e4b3076b5f2d853462b9777d083c77fc0b7b23/drivers/power/supply/axp20x_usb_power.c).

The existing [finite USB current-limit patch](../kernel/patches/0001-axp-finite-current-limit.patch)
and [NKMP optimization](../kernel/patches/0005-sunxi-nkmp-exact-match.patch) are
independent. Any later polling implementation must preserve both, the current
limits, OPPs, voltage sequencing and charger protection.

## Why upstream polls

The sequence of primary-source changes explains both the cost and the
compatibility constraint:

1. Hans de Goede added an A31/AXP221 PHY workaround to poll when the board
   itself drives VBUS. Ordinary VBUS interrupts did not cover that situation.
   [Commit `91d96f06a760`](https://github.com/torvalds/linux/commit/91d96f06a760f5f36586e972281e239bb9508596).
2. Chen-Yu Tsai extended the workaround to A23/A33 in 2018 after the AXP223
   failure described above. The issue had been hidden on boards whose ID pin
   already forced PHY polling.
   [Commit `d7119224bfe6`](https://github.com/torvalds/linux/commit/d7119224bfe6e8efbf821a52db7da9530d790f07).
3. In 2019 Tsai put polling into the PMIC power-supply driver so newer SoCs
   would receive the same workaround. His explanation says N_VBUSEN high can
   suppress VBUS detection interrupts whether it is driven by the PMIC or
   externally. The 50 ms interval was retained because the PMIC driver lacks
   the USB-role knowledge needed to decide when rapid detection is essential.
   [Commit `97ec136e7124`](https://github.com/torvalds/linux/commit/97ec136e7124fa12cf56ce706993e747c5f99a20).
4. Samuel Holland's 2020 investigation on AXP803 found that plug/removal IRQs
   follow the input's *used* state. He stopped polling only while online: loss
   of physical VBUS from that state necessarily also loses the used state,
   generating an IRQ. The final change retains a register read after every
   interrupt and resume, avoiding an assumption that an IRQ alone gives the
   latest state. The detailed experiments were on AXP803; their precise register
   behavior must not silently be presented as fresh AXP223 measurements.
   [Commit `bcfb7ae3f50b`](https://github.com/torvalds/linux/commit/bcfb7ae3f50be4d51346a8cf69097cf59b29d05b).
5. A later change moved the work to `system_power_efficient_wq` so it could run
   on an appropriate CPU rather than a fixed per-CPU workqueue. That migration
   is already present in our kernel; it does not eliminate recurring work.
   [Commit `0dd713ef2134`](https://github.com/torvalds/linux/commit/0dd713ef2134bac2ee25562990dd6ecbc6feb615).

Holland's series introduction independently describes the same optimization
opportunity: approximately 20 status reads per second provoked CPU frequency
changes, producing about 50 RSB transfers per second on his system. He did not
find a safe general way to remove battery-mode polling without returning the
decision to the USB PHY. Those are historical measurements, **not GameShell
results or a forecast of savings**.
[Author's series explanation](https://lkml.rescloud.iu.edu/2001.1/04620.html).

The local driver explicitly warns that MUSB needs VBUS-high reporting within
100 ms. Increasing the shared debounce constant indiscriminately would weaken
that behavior. Polling work, power-supply notifications, PHY debounce and
scheduler latency must be considered together; a nominal timer alone is not
an end-to-end timing guarantee.

## What the supplied AXP223 datasheet establishes

Source: [AXP223 Datasheet V1.1, 2013-11-28](../allwinner/extracted/R16/Firmware/AXP223%20Datasheet%20V1.1%2020131128.pdf),
from the owner's supplied archive. Printed page numbers below refer to the
document's own numbering. The private text extraction is
`.local/diagnostics/neo5-battery.JREzc0bg/axp223-datasheet.txt`.

| Register / section | Relevant meaning |
| --- | --- |
| `0x00[5]`, §10.2.1, p.32 | VBUS present indication. |
| `0x00[4]`, §10.2.1, p.32 | Whether VBUS is available/usable; Linux names the bit `VBUS_USED` and exposes it as `ONLINE`. The Chinese description does not by itself prove all IRQ edge conditions. |
| `0x00[1]`, §10.2.1, p.32 | Whether ACIN and VBUS are shorted on the PCB. Distinguish two reported inputs from two physically independent sources. |
| `0x30[7]`, §10.2.24, pp.38–39 | Selects whether the VBUS-to-IPSOUT path depends on N_VBUSEN or can be selected regardless of that pin. |
| `0x30[2]`, same section | Output level when DRIVEVBUS operates as an output. |
| `0x8f[4]`, §10.2.43 and §9.2.3 | Zero configures the pin as DRIVEVBUS output; one configures it as N_VBUSEN input. Interpret this together with `0x30` and the pin's electrical state. |
| `0x40[3:2]`, §10.2.50, p.46 | VBUS insertion/removal IRQ enables. |
| `0x48[3:2]`, §10.2.55, pp.47–48 | VBUS insertion/removal IRQ status. |
| §9.8, p.29 | IRQ output is asserted for events, status is retained, and writing a one clears the corresponding pending status bit. |

The IRQ names in the register table are not proof that *every* physical cable
or voltage transition generates an interrupt in every power-path mode. The
upstream AXP223 failure supplies a concrete counterexample to that assumption.
Do not clear or write IRQ-status registers for an observational experiment;
doing so could consume an event belonging to the kernel's regmap IRQ handler.

## GameShell-specific observations

The project DTS sets USB0 to `dr_mode = "peripheral"`, supplies its VBUS
presence information from the PMIC, and has no USB0 VBUS-drive regulator
specified. The USB1 supply serves the separate keypad connection. The local
`phy-sun4i-usb.c` consumer reads `POWER_SUPPLY_PROP_PRESENT`; supply-change
notifications schedule its detection work after 50 ms. Its A33-specific
VBUS-drive polling condition depends on `phys[0].regulator_on`. This makes a
fixed-peripheral optimization worth investigating, but does not establish the
PMIC pin's inherited state.
[Board DTS](../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts).

Visual inspection of the published mainboard schematic found a shared
USBVBUS/ACIN5V input feeding both the PMIC's ACIN and VBUS
pins on page 6. Page 7 connects the USB connector VBUS to the output of U22
(SY6280), whose input comes from the USB-5V boost supply. Its enable net joins
USB0-DRVVBUS, with a 100 kΩ pulldown, and that net reaches the PMIC's N_VBUSEN
pin. Thus peripheral configuration, PMIC pin mode and the external switch
matter together. These are published schematic connections, not electrical
measurements of the owner's v3.1 PCB.
[Pinned Clockwork schematic](https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/clockwork_Mainboard_Schematic.pdf).

Read-only live observations after the owner reconnected USB:

| Evidence | Observation and limit |
| --- | --- |
| `.local/diagnostics/20260927T112901.678926Z/status.txt` | Diagnostic.3 boot `9da0aa56-198a-4e1b-96cb-b9f41b3dc4e2`, six services active with no restarts, no failed units or kernel taint; battery reported 71%, charging, 4.1745 V. This establishes an accessible healthy baseline, not charging qualification. |
| `.local/diagnostics/neo13-usb/attached-state.txt` | USB present/online both 1; AC online 1; UDC configured; original 366 µs governor timing. Shared schematic inputs explain why both supply objects can report online. Plug/removal IRQ counts were both zero on this boot-attached sample. |
| `.local/diagnostics/20260927T094701.147084Z/governor-comparison.jsonl` | The first raw premeasurement snapshot on the earlier diagnostic.2 boot has one USB plug and one USB removal interrupt. |
| `.local/diagnostics/20260927T111327.916104Z/governor-comparison.jsonl` | The first raw premeasurement snapshot on the preceding diagnostic.3 boot has zero plug and one removal interrupt. |

Those historical counters show that the PMIC delivered some transitions. They
do not correlate each physical transition with an IRQ, bound detection latency,
or prove coverage in states where N_VBUSEN disables the input. No PMIC mode
register was read or written as part of these live observations. No fresh
disconnected polling trace or optimization A/B test has yet been performed.

## Candidate direction and conditions

The useful distinction is **a state with a guaranteed future detection event**
versus **a state needing polling**, not simply cable present versus absent.
The following is a proposed design direction, not established driver behavior:

| State | Candidate behavior and qualification needed |
| --- | --- |
| Online, input used | Keep the existing IRQ-driven behavior and debounced read. Already implemented upstream. |
| No VBUS, proven peripheral-only operation, PMIC input path receptive | Potentially stop recurring polling if the next external insertion is guaranteed to produce an IRQ. Requires board/power-path proof plus transition tests. |
| VBUS present but not used | Keep rapid polling unless an independent reliable detection path is established. This covers state changes that need not change `ONLINE`. |
| Board drives VBUS, changes role, or input path is disabled | Keep rapid detection under PHY/role awareness. Re-arm before the transition, including while cached `PRESENT` is still zero. |
| Unknown state, first probe, resume, or read error | Read or retry rather than interpreting unknown/stale data as an absent cable and becoming permanently quiet. |

The attractive expression `present && !online` is insufficient. If it stops
work while absent, then the system begins driving VBUS without a usable PMIC
IRQ, nothing necessarily restarts the work when the voltage rises. Retaining
polling only *after* observing present does not solve that transition.

For this project, a small board-specific change may ultimately be more
maintainable than a general PMIC rewrite, but merely matching the AXP223 chip
is too broad. A proven fixed peripheral configuration and its power-path
contract must be expressible and enforced. Alternatively, coordinate the
polling policy with the USB consumer that knows about VBUS-drive transitions.
Neither approach should silently modify N_VBUSEN, force input selection or
disable protection just to obtain interrupts.

The preferred next implementation investigation is therefore a role- and
power-path-aware decision: retain fast 50 ms work whenever the next voltage
transition might lack an IRQ, and become quiet only in a proven receptive
peripheral state. A slower background watchdog might recover a missed event
eventually, but cannot replace the rapid path where MUSB's sub-100 ms
requirement applies. Its extra reads and residual failure window would need
measurement and documentation as explicit tradeoffs.

Implementation also needs explicit state synchronization. A queued IRQ must
not be cancelled by a worker acting on an earlier sample; pending transitions
must remain observable across probe, stop/start and resume. A transient failed
read cannot count as confirmation of an absent input. In the existing source,
a failed poll retains cached `online`: an offline cached state retries, while
an online cached state can cease polling after the failed one-shot read. A
new design must assess that inherited weakness rather than accidentally
generalizing it to more states.

Initialization ordering has already caused a real regression in this driver:
an interrupt arriving before delayed-work initialization could crash probe.
Keep work initialized before requesting IRQs, and retain managed cancellation
and a fresh resume read.
[Upstream fix `b5e8642ed95f`](https://github.com/torvalds/linux/commit/b5e8642ed95ff6ecc20cc6038fe831affa9d098c).

## Evidence needed before a kernel change

1. Confirm the live compatible, USB role, available VBUS regulators and readable
   PMIC input-path configuration against the board schematic. DTS configuration
   alone does not prove an inherited bootloader register state or a pin voltage.
2. Observe several cable removal/insertion cycles on the unchanged image, using
   Wi-Fi for control. Correlate PMIC IRQ counters with `PRESENT`, `ONLINE`, PHY
   state, UDC state and time to restored USB networking. Keep read traffic low
   enough to avoid hiding the polling cost.
3. Attribute disconnected-idle work to the PMIC worker separately from PHY,
   battery-policy and user-space sampling. Compare attached and detached
   states as a mechanism check; they are not a valid battery-energy A/B test
   because attaching USB changes the supply source and other hardware activity.
4. If a candidate is justified, test initial boot both with and without cable,
   rapid reconnects, weak/interrupted supply, read-error recovery and lifecycle
   transitions. Cover any supported VBUS-drive mode; otherwise make the
   deliberately narrower peripheral-only contract explicit.
5. Compare battery-only stock/candidate measurements under matched conditions,
   retaining original governor settings and protection. Count timer/RSB work,
   CPU time and detection reliability as well as estimated power. Small gains
   are worthwhile; no minimum percentage saving is required.

Repeated normal plug/unplug success can support a CPI v3.1 candidate. It cannot
prove behavior for an electrically distinct host mode, brownout, failed RSB
transaction or future suspend/resume path that was not exercised. At this point
the exact disconnected polling cost, removable fraction and power saving on
the current GameShell remain measurement questions.

The source/history investigation for NEO-13 is complete. The next work is a
repeatable, instrumented detection check, followed by a narrowly justified
implementation if the evidence supports it. No kernel change has been made.
