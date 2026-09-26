# R16/A33 relationship and newly supplied sources

Research date: 2026-09-27. This supplement assesses the owner's datasheet, GameShell standby discussion, CSDN article/download links and linux-sunxi A33 page. It accompanies the [sleep investigation](07-sleep-and-wake-feasibility.md). No hardware was accessed or software built.

**Local archive follow-up:** the owner subsequently supplied both development collections and four A33 PDFs. They have now been extracted and assessed in [reports 13–16](13-allwinner-document-findings.md), with an [inventory and integrity record](../allwinner/README.md). The web-access failures below remain the history of the earlier URL checks; archive contents are no longer an uninspected lead.

## Why A33 material is relevant to the R16

**Upstream software explicitly treats R16 boards as A33-compatible.** Linux v6.18's [R16 Parrot evaluation-board description][parrot-dts] includes `sun8i-a33.dtsi` and uses `allwinner,sun8i-a33` as its SoC compatible. U-Boot v2026.07's [Parrot configuration][parrot-uboot] selects `CONFIG_MACH_SUN8I_A33`. ClockworkPi's [CPI board patch][cpi-dts] likewise includes the A33 description. This provides implementation evidence for researching both names.

It does not make an arbitrary A33 tablet configuration suitable for GameShell. DRAM parameters, PMIC supplies, panel wiring, USB roles and wireless power controls are board-specific. Even the reference Parrot configuration includes peripheral and memory settings that must not be imported as GameShell facts. The useful distinction is **shared SoC support versus independently verified board configuration**. [Reference-board source][parrot-dts]; [CPI source][cpi-dts].

For power management, search terms should include `A33`, `R16`, `sun8i-a33`, `AR100`, `ARISC`, `PSCI` and `AXP223`. AR100/ARISC material and ARM CPU code serve different parts of the suspend path; locating one does not establish a complete implementation. The [sleep report](07-sleep-and-wake-feasibility.md) traces that boundary through Linux, U-Boot and Crust.

## Assessment of the supplied links

| Source | Assessment and use |
| --- | --- |
| [R16 datasheet v1.4][r16-datasheet] | Useful vendor reference for electrical characteristics, pin functions and power capabilities. A register-level retention sequence still requires other evidence; inspection limitations are recorded in report 07. |
| [GameShell power-key standby discussion][standby] | Valuable first-person experiment. Its evidence and limits are now incorporated into [report 07](07-sleep-and-wake-feasibility.md). |
| [R16 audio-capture blog][audio-blog] | An audio tutorial with concrete mismatches against upstream PMIC definitions. Do not treat its hardware examples as a board specification. See the comparison below. |
| [CSDN download 10399935][archive-10399935] | Indexed by linux-sunxi as an A33 software/hardware development collection. Download page failed; contents, versions and provenance were not verified. |
| [CSDN download 10132044][archive-10132044] | Indexed as a complete A33 information collection. Download page failed; contents, versions and provenance were not verified. |
| [linux-sunxi A33 page][a33-index] | Useful document index: vendor manuals, development collections and mirrors. Follow its links to original documents and check current source code for support status. |

The two CSDN archive links are explicitly the references behind the A33 development-material collection on the wiki. It also links separate R16 hardware materials and an Android SDK mirror. Thus these are related leads rather than five independent confirmations of working sleep. The inspected index reports revision `24450`; direct archive requests returned HTTP 521/timeouts and the research browser could not open the MEGA folders. No archive inventory, firmware availability or licensing conclusion is claimed. [Document index and archive references][a33-index].

## A concrete problem with the audio blog

The article's section 3.1.3 presents a PMIC sequence using I²C bus 0. It labels bit 7 of register `0x12` as enabling “LDO4.” That example does not match the examined upstream definitions. [Article being assessed][audio-blog].

In Linux v6.18, `0x12` is `AXP22X_PWR_OUT_CTRL2`; its bit 7 controls **DC1SW**. **DLDO4** uses bit 6 of that register. The AXP22x regulator table and mask definitions establish the distinction. GameShell's existing board description also connects its AXP223 through **RSB**, rather than the article's I²C-bus-0 arrangement. [Register addresses][axp-header]; [regulator mapping and masks][axp-regulator]; [CPI PMIC bus description][cpi-dts].

This is sufficient reason to reject that example as implementation guidance for this board. It does not establish that every general audio concept in the article is wrong. Audio remains deferred under the [agreed scope](06-base-requirements.md); any later audio work should start from the actual board wiring and the relevant upstream ASoC drivers.

## Documents and code to prioritize

1. **The R16 vendor user manual alongside its datasheet.** The [v1.2 user manual][r16-manual] is a much longer programming reference. Its contents were inspected, but detailed DRAM-retention coverage remains unverified. Do not equate a document's length with completeness.
2. **The A33 vendor manual as a comparison.** [Version 1.1][a33-manual] is accessible and identifies its September 2014 revision. Compare relevant registers with R16 material and working code before applying a sequence.
3. **The AXP223 manual and actual board schematics.** These establish the external power/wake side. The [battery report](09-battery-and-power-policy.md) separates hardware alarm capabilities from missing Linux integration.
4. **Historical A33 suspend implementation and modern Crust.** The [sleep report](07-sleep-and-wake-feasibility.md) records both the historical vendor-firmware route and the missing modern DRAM/monitor work. These provide a more focused investigation path than porting a whole obsolete SDK.
5. **Development archives, if obtainable.** Inventory filenames, document revisions, source versus binaries, licenses and checksums before depending on any content. Look specifically for DRAM self-refresh entry/exit, ARISC/AR100 loading, SRAM layout, clock switching and wake sequencing. These are proposed search targets, not claims about what the inaccessible archives contain.

The additional sources strengthen the rationale for investigating A33/R16 firmware. They do not remove the modern deep-suspend integration gap or establish a week-long standby result. Remaining document/archive work is recorded in [FOLLOW-UP.md](../FOLLOW-UP.md).

## Sources

[parrot-dts]: https://github.com/torvalds/linux/blob/v6.18/arch/arm/boot/dts/allwinner/sun8i-r16-parrot.dts
[parrot-uboot]: https://github.com/u-boot/u-boot/blob/v2026.07/configs/parrot_r16_defconfig
[cpi-dts]: ../../GameShell/Code/Kernel/v0.6/515_dts.patch
[r16-datasheet]: https://linux-sunxi.org/images/b/b3/R16_Datasheet_V1.4_%281%29.pdf
[r16-manual]: https://linux-sunxi.org/images/c/ca/Allwinner_R16_User_Manual_V1.2.pdf
[a33-manual]: https://dl.linux-sunxi.org/A33/A33%20user%20manual%20release%201.1.pdf
[standby]: https://forum.clockworkpi.com/t/enabling-standby-mode-using-the-power-key/5695
[audio-blog]: https://blog.csdn.net/weixin_30633869/article/details/154330714
[archive-10399935]: https://download.csdn.net/download/qq_24814779/10399935
[archive-10132044]: https://download.csdn.net/download/sinat_26495969/10132044
[a33-index]: https://linux-sunxi.org/A33
[axp-header]: https://github.com/torvalds/linux/blob/v6.18/include/linux/mfd/axp20x.h
[axp-regulator]: https://github.com/torvalds/linux/blob/v6.18/drivers/regulator/axp20x-regulator.c
