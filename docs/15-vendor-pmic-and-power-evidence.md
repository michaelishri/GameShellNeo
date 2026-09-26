# Vendor evidence: AXP223 battery, wake and power sequencing

Research date: 27 September 2026. This report examines the supplied Chinese AXP223 revision 1.1 datasheet, R16/A33 system-configuration manuals and R16 hardware checklists. All page numbers below are **1-based PDF pages**. It supplements [battery and power policy](09-battery-and-power-policy.md), using the same Linux v6.18 source baseline. No software was built, device queried or hardware setting changed.

The documents make a battery-alarm wake path more concrete, identify gauge-calibration details missing from the current Linux integration, and expose a USB current-limit discrepancy worth resolving. They do not establish working A33 deep suspend, accurate percentage on the replacement battery, or week-long endurance. Vendor configuration examples describe the old BSP contract; they are not modern device-tree properties or settings validated for this GameShell.

## Evidence and scope

| Source | Relevant PDF pages | What it establishes |
| --- | --- | --- |
| [AXP223 datasheet, Chinese revision 1.1][axp] | 19–29, 39–50 | PMIC functions, wake sequence, charging, measurement and gauge registers. |
| [R16 System Configuration][r16-config] | 49–55, 59 | Vendor PMU policy/configuration fields and ARISC standby power-check configuration. |
| [A33 System Configuration V4][a33-config] | 49–55, 59–60 | Similar BSP fields; corroborates their role within the vendor software. |
| [R16 schematic checklist][check-schematic] | 4–5, 8 | Always-powered signals, rail constraints, battery and current-sense requirements. |
| [R16 PCB checklist][check-pcb] | 5–9 | Supply dependencies and measurement-sensitive routing. |
| [ClockworkPi mainboard schematic][clockwork] | 3, 6 | Published GameShell rail assignment, current-sense parts and optional TS wiring. |

The Chinese register tables for wake, charging, ADC, fuel gauge and thresholds were checked visually as well as through text extraction. The archive inventory records extraction integrity separately. The two reported CRC failures concern an A33 IIC guide and an old Ubuntu installation manual, not the core documents used here. A source file's presence does not establish correspondence with the owner's uninspected board revision or replacement pack. [Archive inventory](../allwinner/INVENTORY.json).

## Low-battery wake is documented, but needs a complete software path

The PMIC explicitly supports wake from two battery-capacity alarms, enabled by `REG43[1:0]`, alongside power-key and external-power events. Its sleep sequence is more specific than simply enabling an interrupt:

1. Write the wake-enable control at `REG31[3]`; the PMIC records the output-enable registers `10h`, `12h` and `13h`.
2. Disable the intended outputs through those registers.
3. On a permitted wake event, restore outputs in the specified power-up sequence and restore their **default output voltages**.

The wake-enable command bit clears itself after being written and must be written again each time this PMIC state-capture/restoration mechanism is used. It is not a persistent enable flag that software can poll to determine whether wake is armed. `REG31` also controls whether PWROK goes low on wake and how the IRQ signal participates in waking. These details are firmware/driver sequencing requirements, not an instruction to write the registers from userspace. [AXP223 PDF p. 20][axp20], [p. 39][axp39]. The later Crust trace shows `REG31[4]` keeps IRQ operation normal while firmware detects wake and uses `REG31[5]` to trigger restoration; this differs from assuming every PMIC IRQ directly restores the outputs. A firmware design using explicit rail restoration would need its own documented contract. [PMIC ownership analysis](18-pmic-history-and-suspend-contract.md).

The default-voltage restoration deserves special attention: a wake implementation must reconcile the PMIC's restored state with CPU clock/voltage operating points and Linux regulator state. A rail returning does not establish successful DRAM retention, CPU context recovery or safe clock restoration. The separate [sleep feasibility report](07-sleep-and-wake-feasibility.md) still governs the SoC/firmware dependency.

`REG43[1:0]` enables the two low-capacity IRQs; `REG4B[1:0]` contains their write-one-to-clear status. The vendor labels the second alarm as the shutdown-level alarm. That name does **not** show that it saves filesystems or powers Linux down by itself. The v6.18 MFD maps these IRQs, but the AXP223 battery child receives no interrupt resources and the battery driver has no alarm IRQ or suspend-wake handling. The new datasheet evidence therefore strengthens the case for a targeted driver/firmware extension without removing the integration gap. [AXP223 PDF pp. 47–48][axp47]; [Linux MFD][mfd]; [Linux battery driver][battery].

The PMIC also has a minutes-based timer at `8Ah`, with a timeout status and IRQ. This is a candidate building block for a future periodic check, not proof that a timer currently wakes the selected Linux sleep state or restores the PMIC's sleeping outputs correctly. Both delivery and consumption would need testing. [AXP223 PDF p. 43][axp43], [pp. 47–48][axp47].

Hardware low-voltage cutoff is separate again. The datasheet compares **ALDOIN** against VOFF, programmable from 2.6 to 3.3 V in 100 mV steps. The published ClockworkPi schematic connects ALDOIN to `PS`; it is therefore misleading to describe this register simply as a precise battery-terminal cutoff. The power path, load and wiring affect the relationship. Select an earlier orderly-shutdown margin only after pack and load characterization. [AXP223 PDF p. 22][axp22], [p. 39][axp39]; [ClockworkPi PDF p. 6][clockwork6].

## Percentage, calibration and critical alarms are connected

The Chinese document clarifies several gauge semantics:

| Register | Documented meaning | Consequence for GameShellNeo |
| --- | --- | --- |
| `B8h[7:6]` | Gauge and coulomb-counter enables. | Gauge presence alone does not prove battery-specific configuration. |
| `B8h[5:4]` | Capacity-calibration enable and status; status `0` means not calibrating, `1` means calibrating. | Use the Chinese status meaning when resolving ambiguous English translations. |
| `B9h` | Bit 7 validates the percentage in bits 6:0. Reset value is `64h`, with validity clear. | A raw value of 100 can be invalid. Preserve the Linux validity check. |
| `E0h/E1h` | Configured capacity, a 15-bit value multiplied by 1.456 mAh; `E0h[7]` flags configuration. | This is configured capacity, not independently measured usable capacity or a current charge counter. |
| `E6h` | Warning 1: 5–20%; warning 2: 0–15%. Reset `A0h` corresponds to 15% and 0%. | Do not assume the reset second threshold leaves enough time for shutdown. |
| `E8h/E9h` | Percentage-update and gauge cross-correction intervals. | Percentage cadence differs from ADC sampling; polling faster need not yield a new estimate. |
| `ECh` | Starts gauge correction when OCV-derived percentage reaches warning-2 threshold plus a selectable offset. | Changing the critical alarm threshold also moves this calibration trigger. Audit them together. |

Sources: [AXP223 PDF p. 49][axp49] and [p. 50][axp50]. These are register semantics, not a complete calibration procedure.

The R16 BSP manual exposes battery-path resistance in milliohms, battery capacity in mAh, capacity-correction enable, 32 OCV-to-percentage entries, warning thresholds and update timers. It says specifying capacity selects coulomb-based accounting, otherwise voltage-based accounting. This describes the vendor software's configuration behavior; it should not be generalized into a rule about what the silicon or mainline Linux does when a DT property is absent. [R16 PDF pp. 49–51][r16-49]; [A33 V4 PDF pp. 49–52][a33-49].

The current Linux battery driver does not program those OCV/calibration controls or expose all of the gauge's information. Its AXP221-compatible battery-info callback consumes minimum design voltage and maximum charge current, not every field representable by `simple-battery`. A small DT addition alone will not reproduce the BSP gauge setup. [Linux battery driver][battery].

There are visible transcription/specification problems in these manuals. For example, the R16 OCV list places 3.58 V before 3.52 V, and some charge-current lists contain `4500` where surrounding entries imply 450 mA. The AXP223 ADC table prints a formula inconsistent with its explicit 100/200/400/800 Hz list. Treat such conflicts as questions for source-code or revision-history checking; do not normalize them silently into a register recipe. [R16 PDF pp. 49–50][r16-49]; [AXP223 PDF p. 43][axp43].

A useful future read-only inventory should capture gauge enables, capacity-valid/configured state, configured capacity, OCV configuration, warning thresholds, update intervals and calibration state before considering changes. Record bootloader/OS version and whether battery or USB power was removed: the PMIC documents retained data buffers while at least one supply remains, so a software reboot is not equivalent to loss of all PMIC power. This does not prove that every gauge register persists identically. [AXP223 PDF p. 33][axp33].

## Charge limits need pack-specific evidence

`REG33` documents charger enable, targets of 4.1/4.22/4.2/4.24 V, termination at 10% or 15% of programmed charge current, and current codes from 300 to 2,100 mA in 150 mA steps. It lists codes through `1100`; the existence of a four-bit field is not permission to assume the remaining values are supported. `REG34` supplies precharge and constant-current timeout settings. These are chip capabilities, not recommended values for the unknown replacement pack. [AXP223 PDF p. 40][axp40].

The datasheet's `REG33` reset value implies 1,200 mA, while the charger narrative discusses defaults of 450 or 1,200 mA. Actual inherited configuration must be read rather than inferred from either statement. The vendor config separately sets charge current for runtime, screen-off, suspend and shutdown; its example increases current in the latter states. That is evidence of a BSP policy choice, not a requirement to copy it. Current Linux does not acquire those vendor fields just because the files exist. [AXP223 PDF p. 23][axp23], [p. 40][axp40]; [R16 PDF pp. 49–50, 53][r16-49]; [Linux battery driver][battery].

Power-off is not necessarily charger-off: `REG32[7]` excludes RTC and the charging module from its output shutdown. Battery behavior during plugged-in shutdown must therefore be part of qualification, alongside awake and sleeping charge tests. [AXP223 PDF p. 39][axp39].

**USB current-limit discrepancy:** the Chinese AXP223 table assigns `REG30[1:0]` values `00 = 900 mA`, `01 = 500 mA`, and `1x = unlimited`. The R16 BSP manual likewise lists 500/900 mA and unlimited. In contrast, v6.18's AXP223 variant uses the AXP20x table, where `10` means 100 mA; the AXP221 variant uses a different table. [AXP223 PDF p. 39][axp39]; [R16 PDF p. 51][r16-51]; [Linux USB driver][usb].

**Subsequent resolution of the source-history question:** Linux added the AXP223-specific 100 mA behavior deliberately in the 4.11 development cycle. An English X-Powers datasheet with the same stated revision/date explicitly supports that encoding. The conflicting Chinese table does not justify changing the compatible string, nor is there evidence here for a silicon-revision explanation. Preserve the existing variant/table pending physical qualification. The same investigation found a separate, demonstrable setter defect: positive requests can select the table's `-1`/unlimited entry. That software path needs a focused correction and regression checks before relying on current-limit writes. [History, exact commits and proposed correction boundary](18-pmic-history-and-suspend-contract.md).

## Temperature sensing and board-level measurement limits

The PMIC provides a TS input for a thermistor, selectable bias current and charge-temperature thresholds. It explicitly permits grounding TS when battery-temperature monitoring is unused. The published ClockworkPi schematic shows the TS signal and a zero-ohm R24 option, with a note to fit that option when temperature detection is unused. Establish the actual board stuffing and pack wiring before claiming cell-temperature protection. PMIC internal temperature and battery temperature remain different measurements. [AXP223 PDF p. 25][axp25], [p. 43][axp43]; [ClockworkPi PDF p. 6][clockwork6].

The AXP223 measurement table supports the 1.1 mV voltage and 1 mA current scales described in report 09. The hardware checklist specifies 10 mΩ, 1% sense resistors and careful sense routing; ClockworkPi's published R17/R18 values match that specification. Battery contacts, wiring resistance, component tolerance and operating conditions remain part of the measurement path. Resolution therefore cannot be promoted to calibrated whole-board accuracy. [AXP223 PDF p. 28][axp28]; [schematic checklist PDF p. 5][check5]; [PCB checklist PDF pp. 5–9][pcb5]; [ClockworkPi PDF p. 6][clockwork6].

The checklist recommends battery internal resistance below 100 mΩ, but supplies no measurement of the installed replacement. The BSP's `pmu_battery_rdc` is a configuration input, not proof that software has measured the pack. Retain timed runtime and sleep/endurance tests as the available practical evidence; do not claim a trustworthy health percentage or rail-level efficiency from these documents. [Schematic checklist PDF p. 4][check4]; [R16 PDF p. 49][r16-49].

## Rail dependencies and the vendor's 50 mW figure

Several dependencies must survive power optimization. DC5LDO takes its input from DCDC5, DC1SW from DCDC1, and VCC-RTC supplies the always-powered PL domain. The checklist places the PMIC IRQ pull-up on VCC-RTC and reserves PL0/PL1 for PMIC communication. These are reasons to audit a full supply-and-wake graph before switching apparently unused outputs off. Follow the actual GameShell net assignments: the published board connects DCDC2 to system/GPU and DCDC3 to CPU, rather than assuming that generic application labels define the board. [AXP223 PDF pp. 26–27][axp26]; [schematic checklist PDF p. 4][check4]; [ClockworkPi PDF pp. 3, 6][clockwork3].

The PMIC also supports simultaneous or reversed-sequence output shutdown and selectable PWROK timing. Those controls can interact with reset and wake; they are not independent boot-time shortcuts. The documented automatic/forced-PWM regulator modes and ADC/TS sampling controls identify possible efficiency experiments, but provide no measured savings on this board. [AXP223 PDF p. 40][axp40], [pp. 42–43][axp42].

The R16/A33 `[s_powchk]` example configures ARISC power checking during vendor “super standby.” Its `s_system_power = 50` is a **maximum permitted power threshold in mW**, not a measured standby result. The example enables the feature with bit 31 but leaves the separate exception-wake bits clear. Rail-mask interpretation depends on vendor `aw_pm.h`; the explanatory and example masks even differ. Importing that number or mask cannot establish mainline sleep support or power consumption. [R16 PDF p. 59][r16-59]; [A33 V4 PDF pp. 59–60][a33-59].

The earlier seven-day illustration remains unchanged: a hypothetical usable 1,200 mAh pack, 10% reserve and illustrative 3.7 V allow about 23.8 mW average battery-side consumption. A BSP threshold of 50 mW supplies no evidence that the actual machine meets or misses that target. The replacement pack's usable capacity and sleep drain remain unmeasured.

## Follow-up work proposed by this evidence

These are research and later qualification items, not actions performed in this report:

1. **Identify hardware and pack.** Confirm board revision, battery label/specification, TS/R24 population and wiring; match actual regulator consumers to the published schematic.
2. **Correct and qualify current-limit selection.** The source-history investigation is complete in [report 18](18-pmic-history-and-suspend-contract.md). Preserve AXP223 identity, fix the independent setter defect, and record the remaining physical-measurement limit.
3. **Implement and qualify the PMIC ownership contract.** Report 18 proposes wake-mask programming, conditional per-use arming, IRQ acknowledgement, rail snapshots/default restoration, DVFS ordering and Linux state reconciliation together with the SoC suspend implementation.
4. **Design a battery-alarm extension.** Route the existing MFD alarms to the battery driver, integrate Linux wake handling, and validate wake-to-orderly-shutdown. A repeated power-key wake test is insufficient evidence for this path.
5. **Audit gauge configuration before calibration.** Include warning-2/calibration coupling and invalid percentage handling. Derive cell-specific values from evidence, not the manuals' illustrative OCV table or the original pack's advertised capacity.
6. **Qualify charging and endurance across states.** Establish charge limits for the replacement pack; test USB insertion/removal, suspend, resume and plugged-in shutdown. Use the timed-test method in report 09 and keep the vendor 50 mW threshold out of measured-result tables.

## Source links

[axp]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf>
[axp20]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=20>
[axp22]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=22>
[axp23]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=23>
[axp25]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=25>
[axp26]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=26>
[axp28]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=28>
[axp33]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=33>
[axp39]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=39>
[axp40]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=40>
[axp42]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=42>
[axp43]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=43>
[axp47]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=47>
[axp49]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=49>
[axp50]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=50>
[r16-config]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf>
[r16-49]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=49>
[r16-51]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=51>
[r16-59]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=59>
[a33-config]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_System Configuration说明书_V4.pdf>
[a33-49]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_System Configuration说明书_V4.pdf#page=49>
[a33-59]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_System Configuration说明书_V4.pdf#page=59>
[check-schematic]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(原理图部分)_V1_0.pdf>
[check4]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(原理图部分)_V1_0.pdf#page=4>
[check5]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(原理图部分)_V1_0.pdf#page=5>
[check-pcb]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(PCB部分)_V1_0.pdf>
[pcb5]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(PCB部分)_V1_0.pdf#page=5>
[clockwork]: ../../GameShell/clockwork_Mainboard_Schematic.pdf
[clockwork3]: ../../GameShell/clockwork_Mainboard_Schematic.pdf#page=3
[clockwork6]: ../../GameShell/clockwork_Mainboard_Schematic.pdf#page=6
[battery]: https://github.com/torvalds/linux/blob/v6.18/drivers/power/supply/axp20x_battery.c
[mfd]: https://github.com/torvalds/linux/blob/v6.18/drivers/mfd/axp20x.c
[usb]: https://github.com/torvalds/linux/blob/v6.18/drivers/power/supply/axp20x_usb_power.c
