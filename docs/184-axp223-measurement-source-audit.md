# AXP223 measurement and gauge source audit

7 October 2026. NEO-122, supporting NEO-10 and NEO-117. Scope: supplied
X-Powers AXP223 manuals, published Allwinner AXP22 source, and the recorded
CPI v3.1 observations. This source investigation made no device connection or
charger/gauge write. Linux implementation changes and their validation are
separate from the hardware claims below.

## Findings

The source evidence does **not** establish battery capacity, physical overcharge,
an ADC calibration offset, or the cause of the percentage changes. It confirms
the existing voltage conversion and charge-target encoding, exposes an additional
charger control with conflicting documentation, and leaves important gauge and
ADC contracts unspecified. The observed 97% → 77% with an uncalibrated 42.48 mAh
estimate, and 82% → 86% with about 6.28 mAh, must remain separate observations.
Neither pair supplies a calibrated full-capacity denominator.
[Recorded observations](183-partial-discharge-charging-validation.md).

| Question | Source-backed conclusion |
| --- | --- |
| Battery voltage scale | 12-bit battery-voltage result, 1.1 mV per code; this specifies resolution/conversion, not absolute accuracy. [AXP223 Chinese p. 28][cn28] |
| Charger target accuracy | The electrical table specifies 4.2 V with −0.5%/+0.5% bounds. It is a charger specification, not the battery ADC's error budget. [Chinese p. 14][cn14] |
| Additional voltage control | REG34[2] concerns target/CV voltage changing with charging current. Chinese and English manuals reverse its polarity; neither provides a formula. [Chinese p. 40][cn40]; [English p. 43][en43] |
| Capacity unset | E0[7]=0 means total capacity is unconfigured. The manuals do not state the exact resulting percentage algorithm, fallback capacity, or mode-selection rule. [Chinese p. 27][cn27], [p. 49][cn49] |
| B8 calibration | Bit 5 enables total-capacity correction; bit 4 describes correction in progress. These are not an ADC trim or a documented generic counter reset. [Chinese p. 49][cn49] |
| ADC read coherence | The manuals identify the component registers but specify no high/low read latch or atomic snapshot procedure. [Chinese pp. 31–32][cn31]; [English p. 34][en34] |

## Voltage accuracy and the target/readout discrepancy

The supplied Chinese ADC table maps code 000h to 0 mV and FFFh to 4.5045 V,
with 1.1 mV steps. It also gives 1 mA steps for both battery-current channels.
The electrical-characteristics section and ADC description provide no battery
ADC gain, offset, total-error or temperature-drift limit. The 0.5% internal
reference claim on the feature page is not a complete ADC accuracy specification;
the gauge's advertised 2% applies to its battery-specific high-accuracy mode.
Neither can be assigned to these uncalibrated voltage/current samples.
[Chinese p. 6][cn6], [pp. 14–18][cn14], [p. 27][cn27], [p. 28][cn28].

Applying the electrical table's ±0.5% to 4.2 V gives 4.179–4.221 V. The observed
4.2559 V is 55.9 mV above the nominal setting and 34.9 mV above that calculated
upper endpoint. Therefore **charger tolerance alone does not account for the
reported difference**. This arithmetic compares a specification with an
uncalibrated ADC report and possibly cached configuration; it does not prove
the physical terminal voltage exceeded the charger specification. The English
electrical table agrees on ±0.5% and states VIN=5 V, BAT=3.8 V, TA=25°C. Its
feature-page ±5% wording conflicts with that table and with the supplied Chinese
feature-page ±0.5%; using ±5% as a convenient explanation is unsupported.
[Chinese p. 5][cn5], [p. 14][cn14]; [English p. 8][en8], [p. 13][en13];
[existing configuration/cache limits](181-charge-inventory-validation.md).

REG33=c6 decodes to charging enabled, a 4.2 V target, a programmed 1.2 A current,
and the 10% charge-end current selector. These are programmed controls, not
measurements of instantaneous current or evidence of correct termination.
[Chinese p. 40][cn40].

There is a relevant additional control at **REG34[2]**:

| Source | Bit meaning and polarity | Default |
| --- | --- | --- |
| AXP223 Chinese v1.1, p. 40 | CV charging voltage follows charging-current changes: 0 does not follow; 1 follows | 1 |
| AXP223 English v1.0, p. 43 | Target voltage changes with charge current: 0 on; 1 off | 1 |
| AXP221 Chinese v1.6, p. 40 | Same wording and polarity as the Chinese AXP223 manual | 1 |

Sources: [AXP223 Chinese][cn40], [AXP223 English][en43],
[AXP221 Chinese][22140]. The AXP223 table disagreement was checked against
rendered PDF pages, not only extracted text. The AXP221 corroboration does not
resolve the AXP223 discrepancy. Preserve the raw bit and identify the conflicting
interpretations instead of exposing an authoritative `compensation_enabled`
boolean. No source examined supplies the adjustment's magnitude, direction,
transfer function, or linkage to a measured battery resistance. Calling this
a known 55.9 mV compensation would be speculation.

Both AXP223 manuals classify REG34 as RW, with no read-clear or other read
side effect specified. A narrow read-only inventory addition is supported,
retaining the same possibly-cached label as REG33. A default value in a manual
does not establish this board's live value. The Chinese charger description
also mentions automatic target adjustment when external supply voltage is low,
without a quantitative rule; this is another qualification on treating REG33
as a complete analog model, not an explanation of the current observation.
[Chinese p. 23][cn23], [p. 40][cn40]; [English p. 42][en42], [p. 43][en43].

Allwinner's shared AXP22 implementation programs charger timing with mask 0xc2,
preserving REG34[2]. Its other charger-control-2 setters alter timeout fields
or bits 4/5. These paths provide no follow-current formula or polarity test.
No documented user ADC offset/gain trim or fine charger-voltage trim was found
in the AXP223 register descriptions. This is a limit of the examined public
contract, not proof that silicon has no factory trim.
[Vendor charger initialization][vendor-charge]; [vendor timing setters][vendor-time];
[vendor bits 4/5][vendor-control]; [Chinese register descriptions, pp. 32–50][cn32].

## What an unset E0/E1 and B8=c0 establish

The supplied manual describes a simple gauge mode that avoids precise
battery-parameter initialization and a high-accuracy mode with battery-specific
optimization. It does not publish the internal percentage formula or explicitly
say that clearing E0[7] selects simple mode, disables coulomb use, selects an
OCV-only estimator, or substitutes a specific capacity. Thus even a fresh E0/E1
read of 00/00 would establish **unconfigured total capacity**, not zero usable
capacity and not a documented fallback algorithm. Current observations have
the additional cache limitation described in report 181.
[Chinese p. 27][cn27], [p. 49][cn49]; [inventory](181-charge-inventory-validation.md).

Allwinner initializes an OCV curve and optional resistance/capacity parameters;
it explicitly writes E0/E1=00/00 when configured capacity is zero, then still
reads B9 as the percentage. Its monitor reads B9 directly and labels separate
E4/E5 debug values OCV/coulomb percentages. This corroborates multiple gauge
inputs but supplies no AXP223 internal fusion/fallback algorithm.
[Vendor curve][vendor-curve]; [vendor setup][vendor-init];
[vendor monitor][vendor-monitor]. Vendor family code is evidence of its own
behavior, not a full AXP223 register specification or this board's boot history.

For B8, the Chinese manual specifies:

- Bit 7: gauge enabled; bit 6: coulomb counting enabled.
- Bit 5: total-capacity correction function enabled.
- Bit 4: total-capacity correction in progress; zero means not currently
  correcting, not proof that calibration never occurred.
- Bits 3:0: reserved, preserve.

[Chinese p. 49][cn49]. B8=c0 is the documented default. If read freshly, it
would show the two systems enabled and those two correction bits clear at that
instant. It would not establish calibration quality. The correction-status bit
is hardware status despite its RW table classification, so software caching
can hide a transition. AXP221 v1.6 also documents B8[4] this way. A targeted
search did not locate an AXP809 register manual establishing its bit-4 contract;
do not claim all three variants are manual-verified solely from shared code.
[AXP221 p. 49][22149]; [cache analysis](180-sleep-charge-measurement-design.md).

Disabling total-capacity correction is not documented as disabling every
percentage correction: E8 describes update timing, E9 cross-check timing,
and EC an OCV-percentage threshold for gauge correction. Their dependency on
B8[5] is not fully specified. Consequently B8=c0 cannot certify that each B9
percentage change equals current integrated over that interval. The conflicting
vendor header names for B8 bits are also not reset instructions.
[Chinese p. 50][cn50]; [vendor header][vendor-header].

E8[2:0] explicitly selects these percentage-update intervals, in encoding order:
`000=30 s`, `001=60 s`, `010=120 s`, `011=164 s`, `100=0 s`, `101=5 s`,
`110=10 s`, `111=20 s`. Its documented reset value is 00h. The description does
**not** specify a one-percentage-point step, minimum time per point, smoothing
formula, or raw-measurement resampling rule. E9's separate cross-check interval
defaults to 60 seconds. [Chinese p. 50][cn50].

Rechecking the original ten-second samples gives a more specific observation:
the discharge trace detects one-point falls near 20, 50, 80, 110 seconds and
every approximately 30 seconds thereafter through 590 seconds; the accepted
charging trace detects one-point rises near 30, 60, 90 and 120 seconds. These
are detection times at the sampler's resolution, not exact hardware transition
timestamps. This regularity is consistent with the documented default interval;
it establishes neither the live E8 value nor a one-point limiter or physical
charge-per-point. Source traces and hashes are recorded in
[report 183](183-partial-discharge-charging-validation.md#evidence):
`20261007T003528.956284Z/idle-sample.jsonl` and
`20261007T005302.169072Z/charge-baseline.jsonl`.

E8/E9/EC have documented RW descriptions and no specified read-clear effect, but
are above the existing Linux AXP22x map maximum E6. Reading them through the
owning driver requires a deliberate map/access review. BA/BB resistance,
BC/BD OCV and the C0–DF curve are used in vendor source but omitted from the
examined AXP223 register lists; do not classify them as manual-documented
read-only diagnostics merely because addresses are accessible.
[Chinese pp. 31–32][cn31]; [vendor curve][vendor-curve];
[existing map and undocumented-register audit](180-sleep-charge-measurement-design.md).

The source-based next step is to establish fresh gauge/configuration evidence
through the owning driver and trace initialization, preserving original values.
Programming the generic pack's advertised 1,020 mAh or enabling correction would
change the object being investigated without supplying pack calibration.
The pack's actual limits remain unavailable as recorded in
[battery identification](30-bl5c-battery-identification.md).

## ADC byte layout and coherence

Battery voltage is split between REG78 (high eight bits) and REG79 (low four).
The ADC data registers are listed read-only, with no documented read-clear
behavior. The manuals do not specify what unused bits of the low-byte register
return, whether reading either byte latches its partner, a required byte order,
or how a sample update interacts with a multi-register bus transaction.
Accordingly, one bulk-read API call or two matching samples cannot be promoted
to a manufacturer-guaranteed atomic measurement.
[Chinese p. 27][cn27], [p. 28][cn28], [pp. 31–32][cn31]; [English p. 34][en34].

There is a documentation inconsistency for current: the ADC table specifies
12-bit, 1 mA-per-step channels reaching 4.095 A, while the Chinese register list
and English v1.0 list REG7B/7D as low **five** bits. The pinned vendor conversion
uses `(high << 4) | (low & 0x0f)` for voltage and both current channels. This
supports the existing 12-bit interpretation but does not establish unused-bit
values or eliminate the manual inconsistency. A Linux helper that accepts the
whole low byte deserves a width-mask audit independently of read coherence;
there is no captured evidence here that nonzero unused bits caused the observed
voltage. [Chinese p. 28][cn28], [p. 32][cn32]; [English p. 34][en34];
[vendor conversions][vendor-conversion].

A bounded, read-only capture of the documented ADC bytes can test for nonzero
unused bits and record the difference between masked/unmasked assembly. It
should preserve each raw byte and timing bracket, report errors, and avoid
calling sequentially assembled bytes a coherent snapshot. Any repeated-read
algorithm proposed later needs explicit assumptions and bounded failure; the
manuals examined do not supply its correctness contract. Such a diagnostic can
resolve a software representation question but cannot calibrate the analog
measurement. Independent terminal-voltage evidence remains necessary to decide
whether the persistent target/readout discrepancy represents a physical voltage
error. [Register contract][cn31]; [existing electrical qualification limits](29-hardware-qualification.md#charging-voltage-discrepancy-neo-10).

## Locked Linux implementation audit

The local Linux 6.18.54 source agrees with the documented 1.1 mV battery
voltage conversion. `axp22x_adc_raw()` requests 12 bits, the IIO scale is
1.1 mV, and the battery driver converts the processed reading to microvolts.
REG78/79 lie in the volatile ADC range: the ordinary voltage read does not
reuse the nonvolatile register cache. Capacity reads take the valid bit and
percentage directly from B9, also volatile. These paths contain no software
capacity denominator that can be corrected using the pack's advertised rating.
[ADC driver][linux-adc]; [battery driver][linux-battery]; [MFD map][linux-mfd].

There are two separate source concerns. First, the shared AXP22x map omits B8
from its volatile ranges although AXP223 B8[4] is live status. The same map
serves AXP221, AXP223 and AXP809, so a correction should be scoped to a verified
variant or accompanied by the other variants' register audits. This is a
status-read correctness issue, not an established cause of the voltage or
percentage observations. Second, `axp20x_read_variable_width()` shifts the high
byte and ORs in the entire low byte without a width mask. Reserved bits could
therefore alter the result if hardware returned them set; no such instance has
been established on this board. [MFD map][linux-mfd]; [shared helper][linux-header].

That helper performs two separate `regmap_read()` calls. The RSB regmap backend
supplies individual register-read/write operations, and the regmap lock does
not remain held across both helper calls. A bulk API alone would not establish
an ADC snapshot or stop the hardware ADC updating. With no documented latch
contract, byte coherence remains a separate unresolved issue; it is not a
reason to apply a guessed voltage offset. Ordinary REG33 configuration caching
also does not prove that its value is stale. [Shared helper][linux-header];
[RSB backend][linux-rsb].

## Source identities and bounded recommendations

All PDF page numbers above are one-based PDF pages. The supplied Chinese
AXP223 v1.1, dated 2013-11-28, has SHA-256
`d4d2cc18904794abcabbd25f1b8727f020d0610217d11f3d77e7d013ba7217b6`.
The X-Powers-authored English AXP223 v1.0, dated 2015-05-25, obtained through
the linux-sunxi mirror has SHA-256
`0f1d7c74068bcef1425870b49a4380294414d9a5272860133380fda0ca0135c7`.
The AXP221 v1.6 manufacturer document is a family comparison obtained from a
distributor mirror, not an AXP223 erratum.

Allwinner source is pinned to
`6964d467510849e3e262518cb87bff7ef92e01f5`; the examined `axp22-sply.c` has
SHA-256 `e641f6f675b2fb4830fd7ba550390e4fb34d3cd9dfc39ca6f85027885f7880ba`.
The source checks validate the report's register interpretations, not hardware
accuracy. Search failures and omitted manual fields are recorded as unresolved
contracts, not negative proof about undocumented silicon behavior.

1. Extend the read-only inventory with raw REG34 and disputed-bit labeling;
   retain cache provenance and perform no charger-policy write.
2. Address demonstrated software issues at the owning driver layer: dynamic
   B8 status caching and correct ADC width handling are separate questions from
   analog calibration. Review all affected variants before changing shared code.
3. Keep E0/E1 unset evidence, B9 validity, B8 status and raw ADC evidence distinct.
   Do not invent a capacity, OCV-only explanation, offset, trim or reset recipe.
4. Keep electrical voltage/termination, battery capacity and sleep-only charge
   gain unqualified until their independent evidence gaps are closed. This
   investigation does not require repeating extended charging experiments or
   changing the existing charger settings to collect a useful software audit.

[cn5]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=5>
[cn6]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=6>
[cn14]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=14>
[cn23]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=23>
[cn27]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=27>
[cn28]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=28>
[cn31]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=31>
[cn32]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=32>
[cn40]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=40>
[cn49]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=49>
[cn50]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf#page=50>
[en8]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=8
[en13]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=13
[en34]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=34
[en42]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=42
[en43]: https://linux-sunxi.org/images/e/e5/AXP223_Datasheet_V1.0_en.pdf#page=43
[22140]: https://atta.szlcsc.com/upload/public/pdf/source/20180326/C81850_99D196A92C959F02656600EC9B0BF580.pdf#page=40
[22149]: https://atta.szlcsc.com/upload/public/pdf/source/20180326/C81850_99D196A92C959F02656600EC9B0BF580.pdf#page=49
[vendor-charge]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L577-L635
[vendor-time]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L1251-L1306
[vendor-control]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L2030-L2054
[vendor-curve]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L1861-L1924
[vendor-init]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L2045-L2078
[vendor-monitor]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L1576-L1624
[vendor-conversion]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.c#L346-L370
[vendor-header]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/power/axp_power/axp22-sply.h#L28-L31
[linux-adc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/iio/adc/axp20x_adc.c?h=v6.18.54
[linux-battery]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/power/supply/axp20x_battery.c?h=v6.18.54
[linux-mfd]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mfd/axp20x.c?h=v6.18.54
[linux-header]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/linux/mfd/axp20x.h?h=v6.18.54
[linux-rsb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/bus/sunxi-rsb.c?h=v6.18.54
