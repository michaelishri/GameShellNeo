# Measuring charging across sleep: AXP223 evidence and limits

Research date: 6 October 2026. Scope: CPI v3.1, the supplied AXP223 documents,
Allwinner's published AXP22 code, and locked Linux 6.18.54. This investigation
performed no device operations and changed no charging or gauge configuration.
It supports NEO-117's remaining charging criterion after the successful
[four-cycle USB sleep matrix](178-guided-cable-batch-hardware-validation.md).

## Decision

Prepare a read-only charger/gauge inventory and an awake telemetry baseline now.
Do **not** report charge gained during sleep from the current image: its battery
driver exposes instantaneous current, voltage and percentage, but no accumulated
charge property. The vendor code identifies a promising E2/E3 gauge value, yet
the AXP223 manuals omit its register contract. A reliable measurement extension
needs its semantics and coherent reads resolved first. A before/after `Charging`
status establishes the two endpoints, not continuous charging between them.
[Battery implementation][battery]; [vendor monitor][vendor-monitor].

This is a measurement limitation, not evidence that the charger stops during
sleep. Keeping the device asleep on USB insertion has already passed its
functional checks; direct charging evidence and efficient standby remain
separate qualifications.

## What the AXP223 documents establish

Page numbers below are one-based PDF pages. The supplied Chinese revision 1.1
and English revision 1.0 agree on the main gauge controls. The Chinese manual
is the clearer source for the result-valid interpretation; the English B9
translation is ambiguous. Linux interprets B9 bit 7 as a valid-result flag.
[Chinese p. 49][cn49]; [English p. 52][en52]; [battery implementation][battery].

| Address | Documented meaning | Measurement consequence |
| --- | --- | --- |
| B8[7] | Gauge enabled | Records configuration, not measurement quality. |
| B8[6] | Coulomb counting enabled | Does not expose an accumulated-charge reading by itself. |
| B8[5] | Full-capacity correction enabled | The gauge can participate in capacity adaptation. |
| B8[4] | Capacity correction in progress | A live status bit is needed to exclude observed calibration activity. |
| B8[3:0] | Reserved; preserve | No documented counter-reset recipe here. |
| B9[7], B9[6:0] | Result valid and remaining percentage | Percentage is bounded and processed; it is not a free-running charge integral. |
| E0[7] | Total capacity configured | This flag belongs to E0, not E2. |
| E0[6:0]:E1 | 15-bit configured total capacity, 1.456 mAh per unit | Configuration is not independently measured usable capacity or battery health. |
| E8[2:0] | Percentage-update interval selector | A gauge result can lag a transition. |
| E9[7:6] | Gauge cross-check interval selector | Cross-checking is separate from a current ADC sample. |
| EC[2:0] | OCV-related correction threshold tied to E6's low alarm | A gauge change need not represent charge transferred in that exact interval. |

The table follows [Chinese pp. 49–50][cn49], with the interval/correction
description on [p. 50][cn50]. The manuals do not document E2/E3, their valid bit,
an atomic-read latch, read-clear behavior, wrap/saturation behavior or reset
sequence. Absence from these manuals is an unresolved specification gap, not a
claim that the registers do not exist. [Chinese register tables][cn49];
[English register list, p. 34][en34].

The supplied Chinese document's SHA-256 is
`d4d2cc18904794abcabbd25f1b8727f020d0610217d11f3d77e7d013ba7217b6`.
Its claimed high-accuracy gauge mode depends on battery-specific setup. We have
not calibrated this board or the replacement generic BL-5C and must not attach
that advertised accuracy to its readings. [Chinese pp. 27–28][cn27];
[battery identification](30-bl5c-battery-identification.md).

## What the vendor implementation adds—and does not establish

Allwinner's `axp_charging_monitor()` reads E2/E3, masks the upper byte to seven
bits, and calculates `raw * 1456 / 1000` mAh. It reads E0/E1 with the same scale.
When E2/E3 exceeds configured full capacity, it **writes E2/E3 back to that
capacity**, setting bit 7 in the high byte. Thus this code treats the value as
remaining charge and actively bounds it; it is not an immutable lifetime
counter. It masks bit 7 when reading and does not validate it. That does not
establish E2[7]'s AXP223 semantics. [Pinned vendor monitor][vendor-monitor].

The same source enables capacity correction through B8[5] and initializes E0/E1
from a configured battery capacity when needed. Its header also names B8[5]
`COULOMB_CLEAR` and B8[6] `COULOMB_SUSPEND`, conflicting with the AXP223 manuals
and the implementation's correction operation. These names are not safe reset
instructions. [Vendor initialization][vendor-init]; [vendor header][vendor-header].

The evidence therefore supports **a candidate 1,456 µAh step at E2/E3**, not a
qualified monotonic counter. Hardware saturation, automatic corrections,
retention, reset and coherent-read semantics remain unspecified here. AXP22
family source is useful corroboration, not a replacement for an AXP223 contract.
Do not copy the vendor's clamping or initialization writes into a measurement
feature merely to make readings appear consistent.

The examined vendor tree is pinned to
`6964d467510849e3e262518cb87bff7ef92e01f5`; downloaded source SHA-256:
`e641f6f675b2fb4830fd7ba550390e4fb34d3cd9dfc39ca6f85027885f7880ba`
for `drivers/power/axp_power/axp22-sply.c`.

## Linux ABI and access constraints

Linux defines `charge_counter` as relative accumulated charge without an
empty/full endpoint. A bounded, writable remaining-charge gauge with calibration
corrections is a poor match. **Do not add `charge_counter` for E2/E3 on the present
evidence.** If AXP223 validation establishes it as remaining charge, `charge_now`
is the more appropriate candidate, in µAh. `charge_full` would also need a
justified learned/full interpretation; the battery label belongs to design
information and cannot be silently substituted. [Power-supply ABI][abi].

The AXP288 driver is a useful design comparison: it checks a 15-bit word's valid
flag, exposes its E2/E3 value as `charge_now`, and scales by 1,456 µAh. It is
**another chip's implementation**, not proof of AXP223 validity, corrections or
read protocol. [AXP288 fuel-gauge driver][axp288].

On Linux 6.18.54, AXP223 uses the shared AXP22x regmap:

- The maximum accessible address is **E6**. E8/E9/EC cannot be obtained through
  the current map. Extending the maximum would broaden the shared readable map;
  the separately defined writable range must also remain deliberate. A future
  extension needs an access-table and variant review.
- B9 and the current/voltage ADC range are volatile. **B8, E0/E1 and E2/E3 are
  not volatile**, under `REGCACHE_MAPLE`. The first successful read can populate
  the cache; later reads can return it without hardware access. B8's calibration
  status therefore cannot be claimed live from repeated ordinary reads.
- E2/E3 are within the readable address limit despite being absent from the
  AXP22x symbolic definitions/property list. Accessibility is not documentation
  or measurement validation.

Sources: [AXP223 selection and AXP22x tables][mfd]; [register constants][header];
[regcache read behavior][regcache]; [regmap read behavior][regmap].

A read-only diagnostic must label nonvolatile values as **regmap-reported,
possibly cached configuration**. It must not quietly enable `cache_bypass`,
disable caching, clear the gauge, reconfigure capacity, or use a parallel raw
bus accessor behind the driver's ownership. Targeted debugfs reads must verify
the map's range/layout and returned register address; a broad dump also touches
unrelated and undocumented registers. The debugfs implementation reads through
`regmap_read()`, so being read-only does not make it an uncached hardware
snapshot. [Regmap debugfs][debugfs].

There is another independent issue for a future driver: the current RSB regmap
backend offers single-register reads, and AXP22x has 8-bit values. A two-byte
`regmap_bulk_read()` must not be described as an atomic hardware latch merely
because it is one C call. Establish the device's latch/read protocol; if an
appropriate repeated-read technique is justified, bound its attempts and return
an error for unstable samples. Repeated matching reads alone do not prove the
absence of gauge corrections or reset. [RSB backend][rsb];
[regmap bulk-read implementation][regmap].

## What a sleep measurement could prove

With only today's interfaces, collect before/after battery presence, validated
percentage, status, signed current, voltage, and external-power state. Preserve
actual sleep/RTC timestamps and the normal PM result. This can establish that
the device stayed asleep and returned with an operational charging path. A
percentage rise is supporting gauge evidence. Neither a status string nor
interpolating two current samples proves charge was transferred during sleep.
The driver selects instantaneous charging/discharging ADC data for `current_now`.
[Battery implementation][battery]; [power-supply units][abi].

If a qualified remaining-charge reading becomes available, use this accounting:

`observed charge change = awake-entry contribution + sleep contribution + awake-exit contribution + gauge/error effects`

Sample immediately before and after the actual sleep operation with timestamp
brackets, rather than around SSH reconnection or collection. A remote collection
delay must not extend the supposed sleep interval. Keep all raw samples and
record calibration/configuration state, battery continuity, boot identity, and
any gauge-invalid condition. A positive total delta can only isolate positive
sleep contribution if a defensible upper bound on awake charging and a bound on
gauge/error effects have been established and exceeded. Without those bounds,
report an observed gauge increase **across** sleep, not a measured sleep-only
charge gain. This is the measurement model proposed by this report.

The proposed 1,456 µAh step illustrates why short tests may be inconclusive:
300 mA for 30 seconds is 2.5 mAh, only about 1.72 such steps; 2 mA for 30 seconds
is about 0.0167 mAh. These are arithmetic examples, not predictions or calibrated
readings for this device. Choosing a longer interval improves resolution but
does not remove correction, charging taper or timing uncertainty.

At a reported 100%, a flat percentage or remaining-charge value is expected to
be non-discriminating: the gauge is bounded, charging may taper/terminate, and
the configured full value may differ from real usable capacity. A test should
start after a controlled, observed partial discharge, with stable external power
and no charging-setting changes. Do not drain overnight or infer battery wear
from a single full-charge plateau. [Vendor clamp][vendor-monitor];
[existing charger/discharge distinction](179-software-charge-inhibit-and-discharge.md).

## Bounded next steps

1. Implement an allowlisted, read-only inventory using documented fields,
   existing sysfs telemetry and explicit cache/unsupported labels. Capture the
   locked kernel/image identity. Leave E2/E3 uninterpreted and untouched.
2. Save a repeatable awake baseline sampler. Record per-sample read intervals,
   monotonic/boottime values, missed samples, current sign and status. Describe
   any awake integration as an uncalibrated sampled estimate; never bridge a
   sleep gap with interpolation.
3. When attended hardware work resumes, partially discharge by unplugging USB,
   then check a stable awake charging baseline. Preserve the existing charger
   voltage/current settings. Choose duration and battery range from observed
   behavior rather than promising a fixed amount of charge.
4. Before implementing a new gauge property, resolve AXP223 E2/E3 valid/latch,
   correction, reset and saturation semantics from additional primary evidence
   or a separately specified diagnostic validation. Address volatile fields and
   variant sharing in the driver; do not build a userspace cache-bypass workaround.
5. Run the attended sleep comparison with original-result collection and
   established warning/recovery controls. If measurements remain insufficient,
   retain NEO-117's direct-charge criterion as unqualified while retaining its
   already-passed stay-asleep behavior. Standby-energy optimization can proceed
   as a separate measured question without overstating this result.

These steps add no unattended sleep, reboot, forced discharge, charger writes or
new claims of calibrated battery accuracy.

[cn27]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=27>
[cn49]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=49>
[cn50]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=50>
[en34]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=34
[en52]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=52
[vendor-monitor]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L1573-L1601
[vendor-init]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L2045-L2075
[vendor-header]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.h#L28-L31
[battery]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_battery.c?h=v6.18.54
[mfd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mfd/axp20x.c?h=v6.18.54
[header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/mfd/axp20x.h?h=v6.18.54
[abi]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/Documentation/power/power_supply_class.rst?h=v6.18.54
[axp288]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp288_fuel_gauge.c?h=v6.18.54
[regcache]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regcache.c?h=v6.18.54
[regmap]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap.c?h=v6.18.54
[debugfs]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/regmap/regmap-debugfs.c?h=v6.18.54
[rsb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/bus/sunxi-rsb.c?h=v6.18.54
