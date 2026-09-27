# Replacement BL-5C battery identification

Status: **partially identified; charging qualification remains open**,
27 September 2026. This supports Kaneo NEO-10 and the charging-voltage
investigation in [report 29](29-hardware-qualification.md#charging-voltage-discrepancy-neo-10).
No hardware settings were changed for this research.

## What the owner supplied

The owner identified the installed replacement as **BL-5C** and supplied an
[AliExpress purchase listing](https://www.aliexpress.com/item/1005001822206061.html)
with text describing a Li-ion battery, nominal 3.7 V, 1,020 mAh, 22 g and
3.4 × 5.3 cm, sold for radios and several Nokia models. The text also claims
CE certification. These are owner-supplied seller claims: direct access to
the listing failed during this research, and no exact-pack manufacturer
datasheet, charge-voltage limit, charge-current limit or conformity document
has been established. The listing does not establish Nokia manufacture,
authenticity, measured capacity or the claimed certification.

The owner subsequently confirmed that **no brand or manufacturer is printed
on the pack**: it is a generic replacement. This resolves the label question;
there is no known named manufacturer to pursue from the supplied information.
The intended replacement type is identified, but this does not establish the
cell manufacturer or electrical limits of the particular pack.

## What primary documents establish

The following documents have identifiable manufacturer authorship but are
accessed through third-party mirrors. None identifies the owner's pack.

| Manufacturer document | Battery described | Charging information | Relevance and limit |
| --- | --- | --- | --- |
| [ANSMANN A-Nok2 datasheet, part 5060053V1, 6 June 2006](https://docs.rs-online.com/ab5a/0900766b80cf37fc.pdf) | BL-5C-compatible replacement; 3.7 V nominal, 600 mAh | 4.2 V end-charge; CC/CV charging; 300 mA standard and 600 mA maximum | Explicit replacement-pack limits, but for a different manufacturer/model/capacity |
| [Nokia RM-291 service manual, Issue 1, 2007, printed p. 8–16](https://www.manualslib.com/manual/2476544/Nokia-Rm-291.html?page=186) | Nokia BL-5C, 970 mAh, Li-ion | 4.2 V charging | Historical Nokia specification, not a datasheet for the installed replacement |
| [Nokia RH-18/36/38 engine-module document, Issue 1, October 2003, printed p. 22](https://www.scribd.com/document/770995083/NOKIA-1100-9) | Nokia BL-5C, 850 mAh, Li-ion | 4.23 V charging | Older document differs; it must not be used to approve a higher target for this unidentified pack |

**Nominal voltage is not the charge endpoint.** The ANSMANN sheet explicitly
separates its 3.7 V nominal rating from its 4.2 V end-charge value. The owner's
3.7 V listing therefore does not mean that a battery reading above 3.7 V is
inherently wrong. Conversely, it does not supply a maximum charging voltage.
[Source: ANSMANN datasheet](https://docs.rs-online.com/ab5a/0900766b80cf37fc.pdf).

The two Nokia documents are not fully consistent on charging voltage. This
research does not resolve whether that reflects battery revisions, the
associated phone's charging implementation or documentation differences.
Their specifications cannot be transferred to an unidentified replacement.
The ANSMANN 600 mA maximum likewise belongs to its 600 mAh pack; it is not
a universal BL-5C limit or a justified setting for this owner's battery.

## Implications for the GameShell readings

The existing device evidence reports a 4.200 V charger target and
4.2548–4.2559 V battery readings during charging. Its programmed charging
current and software maximum were both 1.200 A, while one charging sample
reported +220 mA. These are different quantities: a programmed current limit
does not prove that current flowed. The target, sample values and evidence
limitations are recorded in [report 29](29-hardware-qualification.md#charging-voltage-discrepancy-neo-10).

No identified document qualifies **1.200 A for this particular replacement**.
Dividing that setting by the advertised 1.020 Ah gives approximately
**1.18 C**; this is arithmetic using an unverified capacity, not a permitted
charge-rate rule. Capacity alone supplies no maximum charge current. Reusing
a setting from the original installation is not pack-specific validation.

The ADC code's 1.1 mV/LSB conversion agrees with the AXP223 datasheet. An
unplugged raw value of 3674 produced 4.0414 V through both IIO and the battery
interface. As [report 29](29-hardware-qualification.md#charging-voltage-discrepancy-neo-10)
explains, those interfaces use the same ADC; their agreement checks the
software conversion, not physical voltage accuracy. BL-5C identification
does not resolve the 55.9 mV target/readout discrepancy or establish physical
overcharge.

## What remains necessary

- Obtain matching charge-voltage, maximum-current and charging-temperature
  specifications only if the seller can trace the unbranded pack to them;
  otherwise record those limits as unavailable. The owner has already
  answered the brand question; repeat label requests are not useful.
  A compatible-model list or CE marketing claim cannot fill the gaps.
- Continue NEO-10's read-only configuration/ADC investigation. Independent
  voltage measurement remains the way to check the analog reading; the
  owner currently has no suitable measurement equipment.
- Keep extended charging and termination qualification deferred. Do not
  invent an ADC correction, raise a target to match the reading, or transfer
  another BL-5C pack's current limit. No charger-setting change is proposed
  by this report.

Battery-only operation and charging-state transitions already passed their
functional checks. Electrical charging limits, telemetry accuracy and usable
capacity remain separate, unqualified properties. These unresolved properties
do not prevent software-only policy tests or other work over battery-powered
Wi-Fi access. Any later independent measurement or change to a traceable pack
should be recorded explicitly; neither has been performed or required as a
condition for all project work.
