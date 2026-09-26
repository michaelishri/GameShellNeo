# Battery support and power policy: feasibility before implementation

Research date: 27 September 2026. This report addresses the [agreed requirements](06-base-requirements.md) using the local ClockworkPi sources and upstream Linux **v6.18**, with a comparison against v6.12. These are tagged source snapshots, not claims about every subsequent stable backport. No image was built, PMIC register changed, or device tested. The replacement battery's specifications and usable capacity remain unknown.

The subsequently supplied Chinese AXP223 manual adds details on wake rearming, default-voltage restoration and coupled alarm/calibration thresholds. [Report 15](15-vendor-pmic-and-power-evidence.md) records these findings and a USB input-current encoding discrepancy that must be resolved before modifying that configuration.

## Findings that affect the first image

Standard Linux support provides a credible foundation for percentage, charging status, battery voltage/current and external-power detection. The harder work is validating those readings against the actual battery, completing protection during sleep, and avoiding unnecessary wakeups. Rewriting the entire PMIC driver is not justified by this audit; targeted upstream-compatible extensions have identifiable purposes. These conclusions follow the driver and integration gaps below, rather than assuming that all AXP-family features apply to AXP223.

The main blockers and opportunities are:

- **Low-battery wake is incomplete in the audited Linux integration.** AXP223 has relevant hardware alarms, but the battery driver is not connected to them.
- **Percentage availability is not calibration.** A displayed number alone cannot establish pack health, remaining runtime or reliable shutdown margins.
- **The USB supply driver polls every 50 ms while its input is offline.** This is a specific awake-idle efficiency candidate to investigate before designing a replacement.
- **Automatic-sleep policy can remain separate from the launcher.** A small policy service using standard input, power-supply and logind interfaces can implement the agreed behavior.

## Hardware and Linux responsibility

ClockworkPi's board DTS identifies an AXP223 on RSB and enables the battery and USB power supplies. Its supplied PMIC interrupt goes through `r_intc`. The battery node contains no `monitored-battery` reference describing the installed cell. The published schematic is evidence of the board design, while the precise owner's revision and replacement pack still require inspection. [Local DTS][board-dts]; [schematic][schematic]; [hardware assessment](02-hardware.md).

Upstream represents AXP223 battery/ADC functionality through AXP221-compatible children. That compatibility is intentional. USB is different: `axp223.dtsi` overrides the inherited USB compatible string, and the MFD registers an AXP223-specific USB child. Preserve that distinction in the new board description. [AXP22x DTS][axp22x-dts]; [AXP223 DTS][axp223-dts]; [MFD driver][mfd].

| Interface | What the audited AXP223 path can report | Qualification |
| --- | --- | --- |
| Battery `capacity` | PMIC percentage | Invalid fuel-gauge result returns an error; absent battery can report 100%, so also check `present`. |
| Battery `status`, `present` | Charging/discharging/full state and battery detection | Confirm transitions physically; do not infer USB state from percentage. |
| Battery `voltage_now`, `current_now` | Voltage and signed battery current | Positive charging, negative discharging. |
| Battery `health` | Limited PMIC condition reporting | `Good` is not an assessment of retained capacity. |
| USB `present`, `online` | Cable/input detection and usable supply state | A plugged-in input is not necessarily supplying the load. |
| USB `input_current_limit` | Configured input limit | Not measured USB current. |

Sources: [battery property implementation][battery]; [USB properties and AXP223 variant][usb]. Linux expresses these electrical readings in microvolts/microamps; percentage is a different quantity from charge in microamp-hours. Discover supplies by type and device identity instead of baking a particular sysfs pathname into future applications. [Linux power-supply ABI][supply-class].

There is no `charge_counter`, `charge_full`, `cycle_count` or battery-temperature property in this battery driver's property list. Its probe does not initialize an OCV curve or a complete gauge-calibration procedure. The AXP221-compatible battery-info callback consumes minimum design voltage and maximum constant charge current; it does **not** apply every property a generic battery binding can describe. [Battery source][battery].

The AXP223 datasheet documents fuel-gauge and coulomb-counter controls at B8h, a valid-result bit and percentage at B9h, and a configured capacity at E0h/E1h. It also describes low-battery interrupts and battery-alarm wake from PMIC sleep. These are hardware capabilities, not proof that the OS has configured or qualified them. [X-Powers AXP223, 2013 revision, sections 9.1.4 and 10.2.60–64][datasheet].

**Recommendation:** first capture read-only telemetry and identify which firmware or bootloader state the gauge inherits. If percentage is unreliable, investigate AXP223-specific calibration and missing driver support. A generic `simple-battery` OCV table is not evidence that this driver programs the hardware gauge. Do not copy an AXP209 or AXP818 calibration recipe merely because register names resemble each other. Keep any estimated health/runtime explicitly separate from the kernel's hardware readings.

## Charging configuration is a board-and-battery contract

The battery binding accepts an optional `monitored-battery` reference to a `simple-battery`; the generic binding defines design characteristics. The current GameShell DTS omits that reference. Adding one should follow identification of the replacement cell, rather than assuming the original advertised 1,200 mAh pack is still installed. [AXP battery binding][battery-binding]; [generic battery binding][generic-battery]; [local DTS][board-dts].

AXP223 charge-current programming in the driver uses 300 mA plus 150 mA steps. Without battery information it derives its maximum from the existing register; incomplete battery information can trigger a 300 mA fallback. The AXP22x voltage setter accepts 4.1 V and 4.2 V. Treat these as implementation facts, not recommended settings for an unidentified replacement pack. [Battery source][battery].

For USB input, the AXP223 driver has 100/500/900 mA entries; AXP221's table differs. An M2 Mac connected through a cable or adapter does not justify selecting the largest limit automatically. Qualify the chosen gadget's USB power declaration, input limit, cable path and measured charging behavior together. The AXP223 USB property list lacks USB voltage/current measurements, so standard software telemetry cannot provide a USB-side efficiency measurement. [USB source][usb].

The subsequent history trace establishes that the AXP223-specific 100 mA entry was intentional and is supported by an English vendor datasheet; the same-revision Chinese table conflicts. Preserve AXP223 identity and the existing table pending physical qualification. More urgently, the inspected setter has a separate selection bug: it can choose the trailing `-1`/unlimited entry for a positive request. Correct and regression-test that path before relying on writes or a device-tree clamp. Reading back a programmed code still does not measure actual input current. [PMIC history and setter trace](18-pmic-history-and-suspend-contract.md).

Follow-up should record battery label/model, permissible charge voltage/current, charger configuration before and after boot, and behavior while awake, asleep and shut down. Also verify whether this board/pack combination supplies a real thermistor signal before describing temperature protection as working. PMIC die temperature is not battery temperature. The vendor documents separate temperature sensing and power-path functions; the wiring and configured implementation determine what is actually available. [AXP223 datasheet, features and charger description][datasheet]; [schematic][schematic].

## Critical battery: three different mechanisms

An orderly OS shutdown, an alarm that wakes sleeping software, and hardware undervoltage power removal have different roles. The vendor describes automatic low-input protection and a PMIC power-off command; neither alone demonstrates that Linux can save state and unmount filesystems before power disappears. [AXP223 datasheet, section 9.1.3][datasheet].

The v6.18 MFD IRQ table maps `AXP22X_IRQ_LOW_PWR_LVL1` and `LOW_PWR_LVL2`, but its AXP223 battery child receives no IRQ resources. The battery driver requests no interrupt and installs no suspend/wake callbacks. This gap also exists in v6.12. Therefore enabling the existing battery node does not establish wake-to-shutdown protection. [MFD source][mfd]; [battery source][battery]; [v6.12 comparison][battery612].

A plausible driver extension would route battery alarm resources, program validated thresholds, acknowledge events correctly, publish standard power-supply changes, and establish wake handling through the PMIC and SoC interrupt chain. Linux requires wake IRQ handling distinct from ordinary interrupt delivery. The full A33 suspend path must also work; the companion sleep report addresses that dependency. [Linux suspend interrupts][suspend-irqs]; [sleep feasibility](07-sleep-and-wake-feasibility.md).

Proposed policy, pending tests:

1. While awake, monitor voltage, capacity validity, charging status and external power. Use events where supported plus modest periodic sampling; increase sampling near the critical region.
2. Select shutdown thresholds from the actual discharge curve and worst-case shutdown time. Do not designate a universal percentage or voltage yet. Include hysteresis/debounce for noisy readings, without masking sustained low voltage.
3. Check immediately before sleep and after wake. A critical condition takes priority over inactivity and SSH/USB automatic-sleep exemptions.
4. During sleep, prefer a verified PMIC alarm that wakes sufficiently early for an orderly shutdown. If unavailable, investigate a separately verified timer wake/check cycle and its endurance cost. Neither option is established yet.
5. Until this path passes, classify unattended long-duration battery sleep as **unqualified**. Hardware cutoff protects differently and does not satisfy the requested orderly-shutdown behavior.

Unavailable or contradictory readings must produce an explicit degraded state. The policy should avoid entering long unattended sleep when it cannot establish a safe reserve; it should not silently reinterpret a failed capacity read as either 0% or 100%.

## An efficiency issue already visible in upstream code

The AXP223 USB variant sets `vbus_needs_polling`. Its work function reschedules after `DEBOUNCE_TIME`, defined as 50 ms, whenever the input is offline. That is approximately 20 scheduled polls per second on battery. The driver needs to distinguish input presence from input becoming usable, so deleting polling without understanding those transitions can break detection. This behavior remains in v6.18. [USB source: `axp20x_usb_vbus_needs_polling`, `axp20x_usb_power_poll_vbus`, `axp223_data`][usb].

This creates a concrete experiment: trace wakeups and compare a justified event-driven or less frequent fallback design, preserving insertion/removal, marginal-input and resume correctness. The source establishes scheduled work, **not** its measured energy cost or whether it prevents a particular sleep state. Investigate awake idle and suspend separately.

The AXP22x ADC path enables its selected measurement channels and configures a 100 Hz sample rate at probe. ADC sampling is not 100 CPU interrupts per second. Reducing it or disabling channels needs a documented understanding of gauge, charging and alarm dependencies first. [ADC source][adc]. Board supply constraints also deserve review: ClockworkPi retains several radio/peripheral regulators and Wi-Fi power through suspend. Functional deferral of Bluetooth, audio or HDMI does not establish that their hardware is powered down. [Local DTS][board-dts].

## A launcher-independent policy design

The following is a proposed implementation boundary, not new functionality. Keep kernel drivers responsible for hardware, use systemd/logind for suspend/shutdown coordination, and place product policy in one small service with a versioned configuration file. This gives a future launcher a stable service to query and configure.

| Event/condition | Proposed action consistent with the requirements |
| --- | --- |
| Last meaningful local input + 120 seconds, on battery | Request the qualified sleep mode if no automatic-sleep exemption applies. |
| Configured timeout disabled | Do not initiate inactivity sleep. |
| USB supply becomes usable | Hold an automatic-sleep exemption. |
| Authenticated SSH connection exists | Hold an automatic-sleep exemption, including an idle remote shell. |
| Last exemption ends | Start a fresh inactivity interval; avoid immediate sleep during cable removal or logout. |
| Short power-button press | Deliberate sleep remains available with USB power or SSH connected. |
| Resume | Restore local interaction promptly, refresh telemetry, restart inactivity timing, then reconnect Wi-Fi as appropriate. |
| Confirmed critical discharge | Request orderly shutdown, regardless of inactivity exemptions. |

Systemd distinguishes `idle` inhibition from `sleep` inhibition. Use that distinction so USB and SSH prevent automatic sleep without vetoing a deliberate button press. Keep genuine suspend coordination, including bounded preparation delays, separate. Logind exposes `PrepareForSleep` and inhibitor lifetimes through file descriptors; preparation callbacks need a delay inhibitor to avoid racing suspend. [Systemd inhibitors][inhibitors].

`HandlePowerKey=suspend` is a candidate for the button. Logind's own automatic action depends on correct idle reporting by all sessions; a bare console/evdev environment does not automatically meet that contract. Choose one timing authority. A straightforward initial design is `IdleAction=ignore` with the policy service tracking input and explicitly checking exemptions and relevant inhibitors before asking logind to suspend. Alternatively, integrate correct session idle reporting and let logind own the timer. Do not accidentally stack two two-minute timers. [Logind configuration][logind]; [login1 D-Bus contract][login1].

Define activity as meaningful keypad/console input initially, with a future application activity/inhibitor API. Treat held keys as activity and exclude unrelated periodic device chatter. For SSH, verify interactive shells, noninteractive commands, file transfers and forwarding-only connections. Counting visible terminals alone misses some of these; authenticated transport/session lifecycle tracking must recover after service restarts and drop stale exemptions after disconnection. These are proposed acceptance requirements for the implementation, not assumed behavior of stock SSH or logind.

Use NetworkManager's normal suspend integration if it is the selected network manager. Its API distinguishes radio preference from temporary sleep state, and its `Sleep` method is intended for system suspend tracking rather than direct client invocation. Preserve the user's previous Wi-Fi preference and reconnect only when previously enabled. Actual radio rail power-down belongs to the SDIO/driver/regulator integration; a userspace disconnect alone proves no power saving. [NetworkManager API][networkmanager]; [local supply declarations][board-dts].

## What can be measured without external equipment

The AXP22x ADC scales battery current at 1 mA per count and voltage at 1.1 mV per count. Those are resolutions, not guaranteed board-level accuracy. A `current_now` read is an awake instantaneous sample; it cannot measure the period while Linux and userspace are suspended. [ADC source][adc].

Use repeated timed experiments to establish user-visible endurance:

1. Record image/kernel/DT identifiers, pack identity, starting charge procedure, brightness, radios, load, ambient conditions and all attached cables.
2. Benchmark a repeatable awake workload to an agreed orderly-shutdown endpoint. Log voltage/current/percentage sparsely enough to keep logging overhead small and consistent.
3. Test progressively longer unattended sleep intervals, recording before/after telemetry and post-wake usable runtime. Compare with a matched no-sleep control and powered-off storage interval.
4. Unplug USB for endurance tests. Avoid Wi-Fi polling or an SSH session during sleep measurements; both perturb the agreed policy or workload.
5. Repeat promising results. Do not extrapolate a week from a short interval with an unchanged integer percentage. Short tests can reject excessive drain much more readily than prove very low drain.

Integrating awake current can provide an **uncalibrated estimate** of charge used, with units and sampling error recorded. Timed runtime establishes the tested device's endurance under those conditions. It does not independently separate worn battery capacity from PMIC measurement error or determine individual rail losses. The power-supply ABI deliberately distinguishes percentage, instantaneous current and measured charge counters. [Power-supply documentation][supply-class].

For scale only, a hypothetical **usable** 1,200 mAh pack permits `1200 / 168 ≈ 7.14 mA` average battery drain for seven days. Reserving 10% reduces that to approximately **6.43 mA**, or **23.8 mW** at an illustrative 3.7 V. These are arithmetic budgets, not measured consumption or a claim about the replacement pack. A 1 mA measurement step is already material at this scale. Count all losses and periodic wakeups in that budget, and substitute actual usable capacity when defensible.

## Acceptance and follow-up

The [combined validation plan](11-feasibility-summary-and-validation-plan.md) places these checks alongside boot, peripheral and sleep tests. Before calling the battery/policy portion of the base complete, demonstrate:

- Plausible percentage/current/voltage and correct presence/status transitions through boot, charging, unplugging, sleep and wake; explicit handling of invalid telemetry.
- A documented cell-specific charge configuration and sufficient shutdown reserve, with repeatable orderly shutdown under a representative load.
- The two-minute default, changed/disabled timeout, USB exemption, SSH exemption and deliberate button sleep; include SCP/SFTP, remote command, forwarding-only and abrupt-disconnect cases.
- Wi-Fi enabled/disabled state preservation, eventual reconnection, and separate local-resume/network timing.
- A battery alarm or other verified mechanism that wakes the selected sleep mode and completes shutdown before hardware power loss. Also test sleep entry near the threshold.
- Timed endurance results with the old and new software under matched conditions where practical; retain uncertainty and failed results.

Implementation candidates are therefore the subsequently identified USB current-limit setter fix, a battery-alarm/wake extension, explicit battery configuration after pack identification, possible USB supply polling improvement, and a small policy service. Whole-driver replacement remains an option if tests reveal a broader structural problem; this audit does not establish that need. [Current implementation plan](20-base-implementation-plan.md).

## Sources

Source code was inspected directly, including tagged downloads from the kernel project's mirror when GitHub throttled requests. Datasheets are vendor-authored documents hosted by linux-sunxi; some English register descriptions are inconsistent, so they are not presented as a ready-to-run register programming recipe.

[board-dts]: ../../GameShell/Code/Kernel/v0.6/515_dts.patch
[schematic]: ../../GameShell/clockwork_Mainboard_Schematic.pdf
[axp22x-dts]: https://github.com/torvalds/linux/blob/v6.12/arch/arm/boot/dts/allwinner/axp22x.dtsi
[axp223-dts]: https://github.com/torvalds/linux/blob/v6.12/arch/arm/boot/dts/allwinner/axp223.dtsi
[battery]: https://github.com/torvalds/linux/blob/v6.18/drivers/power/supply/axp20x_battery.c
[battery612]: https://github.com/torvalds/linux/blob/v6.12/drivers/power/supply/axp20x_battery.c
[usb]: https://github.com/torvalds/linux/blob/v6.18/drivers/power/supply/axp20x_usb_power.c
[adc]: https://github.com/torvalds/linux/blob/v6.18/drivers/iio/adc/axp20x_adc.c
[mfd]: https://github.com/torvalds/linux/blob/v6.18/drivers/mfd/axp20x.c
[battery-binding]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/power/supply/x-powers%2Caxp20x-battery-power-supply.yaml
[generic-battery]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/power/supply/battery.yaml
[datasheet]: https://dl.linux-sunxi.org/AXP/AXP223-en.pdf
[supply-class]: https://www.kernel.org/doc/html/latest/power/power_supply_class.html
[suspend-irqs]: https://docs.kernel.org/power/suspend-and-interrupts.html
[inhibitors]: https://systemd.io/INHIBITOR_LOCKS/
[logind]: https://github.com/systemd/systemd/blob/v257/man/logind.conf.xml
[login1]: https://github.com/systemd/systemd/blob/v257/man/org.freedesktop.login1.xml
[networkmanager]: https://www.networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html
