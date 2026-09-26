# AXP223 history and the Linux–firmware suspend contract

Research date: 27 September 2026. This is a source investigation and proposed integration contract, not an implemented driver change. It follows [vendor PMIC evidence](15-vendor-pmic-and-power-evidence.md) and [battery policy](09-battery-and-power-policy.md). No kernel or firmware was built, PMIC register written, device tested, or public message sent.

## Findings and decisions

**Keep the AXP223 identity and its upstream capability table.** The 100 mA entry was deliberately introduced, reviewed and documented; it was not an accidental recent inheritance from AXP209. Conflicting X-Powers documents remain insufficient to establish which description matches the installed silicon.

**Fix or otherwise resolve a separate, demonstrable setter regression before relying on USB current-limit configuration.** In the audited Linux code, requesting 100, 500 or 900 mA selects the table's unlimited entry. Changing the compatible to AXP221 does not solve that error. A DT maximum also does not establish an initial hardware limit.

**Give Linux normal-operation ownership and firmware an exclusive, bounded suspend interval.** Linux should own gauge/charger policy and PMIC interrupt masks. Sleep firmware should own the rail transition and restore sequence only after Linux has stopped PMIC traffic. The selected mechanism determines whether the PMIC's save/restore arming bit is needed; it is not a generic requirement of every Linux sleep operation. Evidence and qualifications follow.

## USB current-limit history

### The 100 mA distinction was intentional

Quentin Schulz proposed explicit AXP223 USB support in November 2016, with a second revision in December. The merged commit is **`50111d3f886ac95cb76aefb6ceb0d1b6e78eefc0`**, authored 9 December 2016, acknowledged by Chen-Yu Tsai and signed off by power-supply maintainer Sebastian Reichel. It distinguishes AXP223 from AXP221 specifically because the former was considered to support a 100 mA VBUS limit. The series introduced a separate compatible and board DTS changes, and the power-supply changes were included for Linux 4.11. [Merged patch][intro]; [review acknowledgement][intro-ack]; [4.11 pull request][pull411].

The 2022 table refactor, **`28ca77c9bb8c895ed13163d8b74dafdc90cf44e1`**, preserved that distinction: AXP223 uses `[900000, 500000, 100000, -1]`; AXP221 uses `[900000, 500000, -1, -1]`. Values are microamps, indexed by the two-bit register selector; `-1` represents no limit. The USB binding also explicitly describes the AXP223 100 mA capability. [Table refactor][table-refactor]; [v6.18 USB binding][usb-binding].

There is conflicting documentation from the chip vendor itself:

| Document inspected | Selector `10` | Provenance and limitation |
| --- | --- | --- |
| Supplied Chinese AXP223 v1.1, 2013-11-28, PDF p. 39 | Unlimited (`1x`) | Original local Allwinner archive. |
| English AXP223 v1.1, 2013-11-28, PDF p. 38 | 100 mA; `11` unlimited | X-Powers-branded document hosted by distributor Micros; cover, revision history and register table visually checked. |
| R16 BSP configuration manual, PDF p. 51 | Lists 500/900 mA and unlimited | Configuration contract rather than an exhaustive silicon capability statement. |

Sources: [Chinese PDF p. 39][chinese39]; [English PDF p. 38][english38]; [R16 PDF p. 51][r16-51]. The downloaded English PDF has 56 pages and SHA-256 `d8a42c2a89bb466e1a4d5395e7aabb832bf6501d19fcdea006e71603bfecbc83`. The two datasheets carry the **same revision and date**. They cannot be ordered into a reliable silicon-change history using their revision labels. The English version supplies documentary support for the upstream choice, but the patch discussion reviewed here provides no bench results or explicit identification of the author's datasheet edition.

Allwinner's published `linux-3.4-sunxi`, pinned at **`6964d467510849e3e262518cb87bff7ef92e01f5`**, adds implementation evidence. Its AXP22 supply driver's active USB work function selects `00` for 900 mA, `01` for lower nonzero configured limits, and `11` for unlimited. It does not exercise `10`. The file also has an older initialization block inside `#if 0`; that disabled block is not runtime evidence. This supports the vendor BSP's 500/900 mA policy without proving that 100 mA is physically unavailable. Do not confuse the separate AXP81x implementation with this AXP22 path. [Vendor `axp22-sply.c`, especially `axp_usb` and insertion handling][vendor].

**Conclusion:** close the idea that table reuse alone establishes a Linux bug. Retain the AXP223 compatible. The physical meaning of selector `10` on the owner's board remains unqualified; neither a successful register readback nor a plausible battery-current reading proves a USB input ceiling. Resolving silicon behavior would need stronger revision-specific vendor evidence or a controlled input-current measurement.

### A different regression affects every finite request

Two January 2024 commits changed the setter:

- **`bec924d27a1fda74ec9ae9a1bae1e32723e32bcb`** renamed the writable property to `input_current_limit` and replaced exact matching with a reverse search intended to round a requested limit to a supported value.
- **`b02fbd830edf9f2cce076d93b787827aac1e402a`** corrected the AXP803/813 register and changed the bound to the number of table entries. This makes the search start at the AXP223 table's final `-1` entry.

The first change already assumes an unsuitable ordering for the descending AXP223 table; together they produce the unlimited selection below. These commits addressed property semantics and AXP803/813 handling, not the disputed AXP223 100 mA capability. [Property/setter change][setter-change]; [table-size/register change][size-change].

The relevant v6.18 logic starts at `table_size - 1` and stops when `table[reg] <= requested`. For AXP223, `table[3]` is `-1`, so it immediately satisfies every positive request:

| Requested limit | Selector chosen | Driver's own interpretation |
| --- | --- | --- |
| 100,000 µA | `11` | Unlimited |
| 500,000 µA | `11` | Unlimited |
| 900,000 µA | `11` | Unlimited |

This follows directly from the source and was checked with a small host-side transcription of the selection logic using the fetched table. It is not a hardware measurement. Unlike selector `10`, both datasheets agree that `11` is unlimited. Simply skipping negative entries would still be insufficient: a reverse scan through the descending finite entries can choose 100 mA for a 900 mA request. The eventual fix must handle both ascending and descending variant tables and reserved/unlimited entries. [Linux v6.18 setter and tables][usb618].

The same relevant logic was present in both additional snapshots fetched on the research date:

- Upstream master **`6812ce4e4379ffc99c52401ec28f0d7ffbc36206`**.
- Stable `linux-6.18.y` **`1b357ecb321392158d507b04672ffee57bfa071d`**.

These are pinned observations, not claims about future backports. Searches of patch discussions and the inspected file history found no corrective patch for this particular selection error. [Pinned master source][usb-master]; [pinned stable source][usb-stable].

The DT limit added by **`6934da720aac7b0feb99d08ff27fd245a962d8d2`** is also narrower than its name may suggest. Probe stores `input-current-limit-microamp`; the setter clamps subsequent requests against it. Probe does not apply that maximum to the inherited register value. The clamp then feeds the faulty selector. A property of 500,000 µA therefore proves neither correct boot-time configuration nor a correct later write. [DT clamp change][dt-clamp]; [v6.18 probe/setter][usb618].

### Initial image policy

These are proposed requirements for implementation:

1. Preserve AXP223 identification and defer any chip-capability-table change. Avoid depending on selector `10` for the first qualification image.
2. Resolve the setter separately with a small upstream-compatible change or a verified later fix. Require exact 100/500/900 mA mapping under the existing AXP223 table; test non-exact values, below-minimum requests, negative/unlimited values and all affected variant tables. Define below-minimum behavior explicitly rather than accidentally exceeding the request.
3. Use a finite setting whose documentation agrees—500 mA is a candidate **only when the attached source and negotiated USB state permit it**. Do not treat the M2 Mac, a cable, or an adapter's presence as evidence that 900 mA is available.
4. Establish the intended limit across bootloader, kernel probe and runtime, then verify register readback using the corrected path. Keep USB input limit separate from battery charge current, which still requires the replacement pack's specifications.
5. Audit board power routing before claiming a port-wide current ceiling. The published ClockworkPi schematic joins the named `ACIN5V` and `USBVBUS` inputs at the PMIC. Determine how shorted-input detection and path selection affect the limit on the actual revision; do not infer whole-port current from a VBUS register alone. [ClockworkPi PDF p. 6][schematic6]; [AXP223 power-path description, PDF pp. 21–22][chinese21].

Until these conditions are met, telemetry should describe a configured register value, not a verified host-current limit. Battery-only endurance tests remain useful and separate from USB-input qualification.

## A concrete PMIC ownership contract

The following describes a proposed design, bounded by the currently incomplete A33 deep-suspend path. It should apply whether the eventual suspend implementation uses a secure monitor, Crust, or another small firmware component; choose one coordinator rather than two independent PMIC sequencers.

| Resource | Linux while running/preparing | Firmware during the exclusive sleep interval | Return requirement |
| --- | --- | --- | --- |
| RSB controller and PMIC bus | Normal parent/child drivers; stop work before handoff. | Acquire only after Linux quiesces; no concurrent access. | Release bus; Linux resets/reinitializes RSB before child access. |
| Battery gauge, ADC and charger | Battery/ADC drivers own configuration and published state. | Leave agreed settings active; no unreported recalibration or charging-policy changes. | Refresh telemetry and report alarms before normal idle policy resumes. |
| PMIC IRQ enables/status | Regmap IRQ core and child drivers own masks, wake selection and acknowledgement. | Observe the SoC wake signal; preserve pending PMIC evidence. | Linux dispatches/acknowledges events, unless a documented firmware protocol transfers the cause. |
| CPU/DRAM/system rails | Regulator framework and consumers establish valid operating points. | Sole owner of agreed suspend/restore rail transitions. | Valid voltages before clocks/DRAM resume; coherent Linux register/cache state. |
| PEK button behavior | Existing input driver; logind/product policy handles deliberate sleep. | Wake detection only. | Consume the wake interaction once; avoid immediate resuspend from the same press. |

### Existing Linux pieces and missing battery integration

The v6.18 AXP223 MFD already maps both low-battery alarms, but does not give their resources to the battery child. A targeted extension should request the appropriate nested IRQs, publish power-supply changes, select cell-qualified thresholds and enable wake for the critical alarm. Non-wake nested IRQs need deliberate masking during suspend; they are not automatically disabled like ordinary device IRQs. The USB and PEK drivers already demonstrate that distinction. [MFD][mfd]; [battery driver][battery]; [USB suspend callbacks][usb618]; [PEK callbacks][pek].

The standard chain is: battery/PEK child requests wake → regmap IRQ forwards wake accounting to the PMIC parent IRQ → `sun6i-r` records the permitted interrupt in R_INTC → firmware sees the wake source. Linux's R_INTC syscore callbacks program those masks for suspend. This existing machinery should be used rather than an unrelated firmware copy of the battery mask. It still needs end-to-end testing on the selected A33 sleep path. [Regmap IRQ core][regmap-irq]; [R_INTC driver][r-intc].

The initial wake policy should enable PEK and the qualified critical-battery alarm. USB automatic-sleep exemption does not imply a requirement to wake on cable insertion; leave that as an explicit separate policy. Wi-Fi/keypad wake remain unnecessary for the agreed scope. Preserve a pending critical alarm while entering sleep: drain old events deliberately, check the current condition, and abort the transition if the reserve or wake setup is invalid. After wake, critical-battery handling takes priority over SSH/USB idle exemptions.

### What current Crust actually does

The inspected Crust snapshot is **`499a362645e6ce6ac1fd8ea8d0f25d4df6690688`**. Its AXP223 suspend hook sets `REG31[4] | REG31[3]`; its shared resume hook sets `REG31[5]`. The datasheet describes bit 3 as arming the PMIC output-state save/restore facility and bit 4 as allowing ordinary IRQ operation while preventing IRQ-triggered PMIC restoration. Crust subsequently polls wake sources and software-triggers restoration. Thus it combines **PMIC state capture/restoration with firmware-controlled wake**, rather than simply letting the PMIC independently restore on every IRQ. [Crust AXP223][crust-pmic]; [shared PMIC operations][crust-common]; [Crust state machine][crust-system]; [Chinese PDF pp. 20, 39][chinese20].

For this mechanism, rearm bit 3 each time before the relevant rail changes; the bit self-clears. Do **not** add that write to ordinary Linux s2idle merely because suspend was requested. A different firmware implementation that explicitly snapshots and restores every relevant rail may not need the PMIC save/restore facility at all. The chosen mechanism must be documented in the firmware contract.

The generic Crust state machine attempts to disable CPU supply during suspend and additionally handles DRAM/system-related rails during shutdown. However, the inspected regulator list has no AXP221/223 branch: an AXP223-only configuration leaves these supply handles unbound. The generic calls therefore do not establish actual GameShell CPU-rail gating. Board-specific supply bindings are required. On resume the generic path expects PMIC restoration, with explicit enables as a fallback. The AXP regulator driver implements enable-state access, not voltage snapshot/restoration. These are reference pieces, not a complete power-gating or DVFS-correctness implementation. [Crust state machine][crust-system]; [regulator bindings][crust-regulator-list]; [AXP regulator driver][crust-regulator].

The datasheet's promise to restore **default voltages** is material. Before restoring a CPU clock that requires a higher voltage, firmware must either restore the exact qualified pre-sleep voltage state, or hold a documented conservative clock/voltage state until Linux completes restoration. Include GPU/system and DRAM dependencies, not just the CPU rail. The current AXP22x Linux regmap caches nonvolatile control registers using `REGCACHE_MAPLE`; firmware changing hardware behind that cache can invalidate later reads or read-modify-write operations. Specify which registers are restored exactly and which require targeted invalidation/reconciliation. Blindly replaying the entire regcache is not an adequate design because output enables, self-clearing controls and interrupt state have different semantics. [Chinese PDF p. 20][chinese20]; [MFD regmap configuration][mfd].

Crust's ABI already restricts RSB use to boot/suspend and requires Linux to reset it on resume. Crust resets the controller, changes mode and assigns a runtime address when using the bus. Linux's RSB system-sleep callbacks reset/reinitialize the controller at the noirq stage. The integration still needs to verify consistent slave addressing and parent-before-child resume ordering; a bus reset is not the same as reconstructing all PMIC state. [Crust ABI][crust-abi]; [Crust RSB][crust-rsb]; [Linux RSB][rsb].

### Gauge and wake-event details to settle before implementation

Keep the battery voltage/current ADC and gauge running while relying on a capacity alarm. Lowering ADC sampling or disabling measurement channels must wait until gauge/alarm dependencies are established. Keep charger limits stable across handoff unless there is an explicit pack-qualified reason to change them. Low-warning threshold 2 and `ECh` calibration onset are coupled, as recorded in report 15; configuration must update the intended policy together, not move a shutdown threshold in isolation. [Chinese PDF pp. 43, 49–50][chinese43].

Extending calibration support also needs a regmap audit: v6.18's AXP22x maximum register is `E6h`, so `E8h/E9h/ECh` are outside that map. Hardware-updated and self-clearing fields need correct volatility/side-effect treatment. This is a concrete kernel integration task, not a reason for a userspace raw-register daemon. [MFD access tables][mfd].

Do not clear PMIC alarm status from both firmware and Linux. Prefer preserving it for Linux's regmap IRQ dispatch; if firmware must acknowledge it, return the cause through a versioned record before clearing. Also test the power-key event after resume: the current PEK driver's special wake-press clearing is AXP288-specific, not AXP223. Product policy must avoid treating the same wake press as a fresh request to sleep. [PEK resume handling][pek].

## Acceptance gates

Before a first image claims these capabilities, require:

- Correct finite USB limit selection and readback; rejection/rounding tests independent of physical selector-`10` qualification; documented boot-time limit ownership.
- Repeated suspend/resume at low and high CPU operating points, with voltage/clock ordering and register/cache agreement recorded.
- Successful PEK wake, critical-alarm wake and sleep-entry alarm-race tests; no immediate resuspend from the wake press.
- RSB recovery and telemetry refresh after every wake, without periodic work accessing a controller owned by firmware.
- Orderly low-battery shutdown before hardware cutoff, including charging/unplugging transitions and invalid percentage handling.
- Timed endurance evidence with the actual replacement pack; no extrapolated electrical guarantee from a PMIC setting or a short unchanged-percentage observation.

The remaining research uncertainty is narrow: selector `10` on the installed silicon, the shorted-input power-path behavior, and the final A33 firmware implementation. The setter error and absence of battery-alarm integration are actionable source findings. They support a small documented patch set while preserving upstream device identities and subsystem boundaries.

## Sources

[intro]: https://github.com/torvalds/linux/commit/50111d3f886ac95cb76aefb6ceb0d1b6e78eefc0
[intro-ack]: https://lkml.iu.edu/1611.3/01140.html
[pull411]: https://lkml.iu.edu/1702.2/02149.html
[table-refactor]: https://github.com/torvalds/linux/commit/28ca77c9bb8c895ed13163d8b74dafdc90cf44e1
[usb-binding]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/power/supply/x-powers%2Caxp20x-usb-power-supply.yaml
[english38]: https://www.micros.com.pl/mediaserver/info-uiaxp223.pdf#page=38
[chinese20]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=20>
[chinese21]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=21>
[chinese39]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=39>
[chinese43]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=43>
[r16-51]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=51>
[schematic6]: ../../GameShell/clockwork_Mainboard_Schematic.pdf#page=6
[vendor]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c
[setter-change]: https://github.com/torvalds/linux/commit/bec924d27a1fda74ec9ae9a1bae1e32723e32bcb
[size-change]: https://github.com/torvalds/linux/commit/b02fbd830edf9f2cce076d93b787827aac1e402a
[dt-clamp]: https://github.com/torvalds/linux/commit/6934da720aac7b0feb99d08ff27fd245a962d8d2
[usb618]: https://github.com/torvalds/linux/blob/v6.18/drivers/power/supply/axp20x_usb_power.c
[usb-master]: https://github.com/torvalds/linux/blob/6812ce4e4379ffc99c52401ec28f0d7ffbc36206/drivers/power/supply/axp20x_usb_power.c
[usb-stable]: https://github.com/gregkh/linux/blob/1b357ecb321392158d507b04672ffee57bfa071d/drivers/power/supply/axp20x_usb_power.c
[mfd]: https://github.com/torvalds/linux/blob/v6.18/drivers/mfd/axp20x.c
[battery]: https://github.com/torvalds/linux/blob/v6.18/drivers/power/supply/axp20x_battery.c
[pek]: https://github.com/torvalds/linux/blob/v6.18/drivers/input/misc/axp20x-pek.c
[regmap-irq]: https://github.com/torvalds/linux/blob/v6.18/drivers/base/regmap/regmap-irq.c
[r-intc]: https://github.com/torvalds/linux/blob/v6.18/drivers/irqchip/irq-sun6i-r.c
[rsb]: https://github.com/torvalds/linux/blob/v6.18/drivers/bus/sunxi-rsb.c
[crust-pmic]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/pmic/axp223.c
[crust-common]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/pmic/axp20x.c
[crust-system]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/common/system.c
[crust-regulator]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/regulator/axp20x.c
[crust-abi]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/docs/abi.md
[crust-rsb]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/regmap/sunxi-rsb.c

[crust-regulator-list]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/common/regulator_list.c
