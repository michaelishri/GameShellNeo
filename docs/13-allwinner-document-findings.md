# Findings from the supplied Allwinner document collection

Research date: 2026-09-27. This report assesses the six files supplied in `GameShellNeo/allwinner`, including both ZIP archives. It extends the [earlier feasibility investigation](11-feasibility-summary-and-validation-plan.md). Original files were preserved; archive extraction and document analysis were the only project changes.

## Main conclusion

**The collection materially strengthens the evidence for pursuing R16 deep sleep.** The vendor documents explicitly describe R16 super standby, ARISC involvement, CPU power controls and DRAM self-refresh configuration. We can now investigate a documented vendor design instead of relying chiefly on related A33 experiments and historical forum discussion. The remaining task is recovering or implementing the complete sequence and integrating it with the modern kernel, bootloader and actual GameShell board. The configuration descriptions alone do not provide that implementation or establish a standby-current result. [R16 System Configuration, PDF pages 11, 13–14 and 58–59][r16-config]; [detailed sleep/memory analysis](14-vendor-suspend-and-memory-evidence.md).

The PMIC material also adds concrete wake and battery details, including a self-clearing command that must be reissued each time the PMIC output-state capture/restoration facility is used. This is conditional on the selected firmware mechanism, not a universal userspace sleep action. The USB input-current encoding discrepancy received a subsequent history investigation: English vendor documentation supports Linux's deliberate 100 mA entry, while a separate current-limit setter defect needs correction. [PMIC document analysis](15-vendor-pmic-and-power-evidence.md); [subsequent history and contract](18-pmic-history-and-suspend-contract.md). The platform guides explain the historical BSP layout and several supply/pin dependencies. [Platform and driver analysis](16-vendor-platform-and-driver-evidence.md).

## What the collection contains

| Input | Inspected contents | Value |
| --- | --- | --- |
| Four standalone A33 PDFs | Datasheet v1.0, 35 pages; datasheet v1.1, 35 pages; user manual v1.0, 580 pages; user manual v1.1, 574 pages | Compare feature/register descriptions and document revisions |
| `Allwinner A33 Development Materials.zip` | 38 files: 35 PDFs and three schematic-project files | Android/BSP integration, system configuration, reference schematic and component support lists |
| `R16.zip` | 53 files: 38 PDFs and 15 CAD/archive/support entries | R16 manuals, PMIC datasheet, Tina/Android guides, board checklists and DRAM reference layouts |
| Combined | 91 ZIP members; 77 PDFs including the four standalone files; 2,951 extractable pages | Searchable research collection with a documented integrity boundary |

Counts come from local archive/PDF inspection. The page total includes the 20-page text recovered from one CRC-failed document; another failed document has no readable pages. It is not a count of individually visually reviewed pages. [Complete linked catalogue](../allwinner/README.md); [hashes, counts and integrity metadata](../allwinner/INVENTORY.json).

The directories named `Firmware` contain documentation. Neither ZIP contains a complete Linux/U-Boot source tree or a ready-to-use ARISC firmware binary. The two nested RARs list eight CAD files, all matching already expanded ZIP entries by name, size and CRC metadata. Their headers were inspected without separately decompressing the RAR streams. CAD project files and PADS text exports are useful design references, but they do not supply suspend executable code. [Archive and nested-member inventory](../allwinner/INVENTORY.json).

## Findings that affect the engineering plan

| Finding | Consequence for GameShellNeo | Evidence |
| --- | --- | --- |
| R16-specific documentation names super standby and ARISC, and exposes CPU/DRAM retention controls | Continue the firmware investigation with greater confidence that this is an intended vendor power-management path; still qualify it on CPI hardware | [R16 System Configuration, pp. 11, 13–14, 58–59][r16-config]; [report 14](14-vendor-suspend-and-memory-evidence.md) |
| The long manuals still provide only a brief SDRAM chapter, while “memory configuration” guides mostly describe Android memory allocation | These documents do not close the DRAM controller/PHY retention-programming gap | [R16 manual, p. 281][r16-manual]; [report 14](14-vendor-suspend-and-memory-evidence.md) |
| PMIC sleep/wake settings have specific rearming and voltage-restoration behavior | Design suspend/resume ordering and repeated-cycle tests around those details, rather than testing one successful wake | [AXP223 datasheet, pp. 20, 39][axp]; [report 15](15-vendor-pmic-and-power-evidence.md) |
| Vendor wireless examples describe shared supplies and wake/clock dependencies | Map the actual AP6212 wiring before reducing radio power; a reference tablet's rail assignments are not GameShell facts | [report 16](16-vendor-platform-and-driver-evidence.md) |
| The supplied Tina quickstart describes an old Linux 3.4/vendor bootloader environment | Use it to locate historical implementation ideas, while retaining the proposed modern Linux base | [R16 Tina quickstart, pp. 4–6][tina]; [report 16](16-vendor-platform-and-driver-evidence.md) |
| SDK download instructions describe access to separately supplied source | The archives provide useful source-location clues, but do not provide the source payload or establish current access | [report 16](16-vendor-platform-and-driver-evidence.md) |

The example standby-power threshold in the configuration material is a diagnostic setting. It is **not a measured consumption result**, a guaranteed sleep budget or evidence for a week of standby. Likewise, reference operating-point tables and board voltages are not validated tuning values for the owner's device. The detailed reports preserve these distinctions.

## Electrical and board-reference material

The R16 datasheet in this archive is **v1.0, dated 18 December 2014**, with 35 pages. It is different from the previously linked 30-page v1.4 datasheet. Its power-sequence drawing on physical page 32 is readable locally and was visually inspected: it distinguishes RTC, CPU, CPUS, system and DRAM supplies and shows reset timing. The diagram is a full power-up/down reference, not a retained-memory suspend/resume recipe. The annotated default 64 ms reset interval should not be treated as a complete boot-time measurement or copied into a resume path without justification. [R16 datasheet, cover and p. 32][r16-datasheet].

The archive's R16 user manual is **v1.0, dated 30 December 2014**, with 568 pages. The previously located online manual was v1.2, with 529 pages. Page references and register claims must identify the revision; the newer cover date does not itself prove a missing programming sequence is present. [Local R16 manual, cover][r16-manual]; [earlier source guide](12-r16-a33-source-guide.md).

The A33 reference schematic is an 18-page **tablet reference design**, with a visually inspected power tree on page 3. It separates DCDC3 for the CPU, DCDC5 for DRAM and DC5LDO for CPUS, and shows peripheral consumers. This is useful when interpreting SoC power-domain names, but ClockworkPi's own schematic and the owner's board remain the authority for actual wiring. In particular, the reference tablet's LCD, motor, camera and radio supply consumers cannot be imported indiscriminately. [A33 tablet reference, pp. 1–3][reference-schematic]; [GameShell hardware analysis](02-hardware.md).

The R16 PCB files include PADS ASCII exports with parts and signal sections, including DRAM supply and strobe nets. These may help a later electrical comparison, but no full PCB connectivity, signal-integrity or proprietary CAD review was performed. Similarly, the DRAM support lists distinguish datasheet-only, sample-tested and production-tested status; appearing in a list is not proof of the part fitted to this GameShell. [CAD inventory](../allwinner/INVENTORY.json); [DRAM support list, p. 1][dram-list].

## Integrity and reading limits

Two ZIP members fail their stored CRC checks:

- A33 `Firmware/A33_IIC驱动开发说明书.pdf`. Its recovered bytes open as 20 pages, but it is excluded as authoritative evidence. The separate R16 IIC guide passed CRC and provides a usable counterpart.
- R16 `代码下载编译环境搭建/Android编译服务器系统安装标准手册(发布版)-Ubuntu12.04x64LTS_20130608-2.pdf`. The recovered file opens with zero readable pages.

The other **89 entries pass ZIP CRC validation**. Original and extracted-file SHA-256 hashes are recorded to identify these exact copies; hashes identify the copies rather than independently authenticating their provenance. No original file was repaired or overwritten. Reobtaining the two damaged documents is recorded as a low-priority follow-up because neither blocks the central power-management investigation. [Inventory](../allwinner/INVENTORY.json).

All PDFs were inventoried and passed through text extraction; relevant manuals and guides received targeted reading, with visual checks of critical tables/diagrams. Camera, modem, sensor, certification and old build-host material received lower-priority triage because it falls outside the agreed base-image scope. Some covers and diagrams contain little extractable text, so text search alone is not treated as a complete graphical audit. Detailed reports cite physical PDF pages and flag inconsistencies in the vendor material.

## Recommended next research

**Follow-up completed:** reports [17](17-vendor-firmware-and-dram-trace.md), [18](18-pmic-history-and-suspend-contract.md) and [19](19-modern-suspend-integration.md) perform the focused source/history investigation proposed below. Actual A33 DRAM operations and historical firmware interfaces were found, alongside an existing monitor integration to assess. [Report 20](20-base-implementation-plan.md) replaces the broad search with concrete implementation checkpoints. The original archive findings and integrity limits above are unchanged.

The most valuable missing evidence is now more specific: an R16/A33-compatible standby implementation covering the secure monitor, ARISC/AR100 interface, DRAM self-refresh entry/exit, clock switching, regulator transitions and resume entry. Historical SDK names and paths can guide that search. A compatible firmware binary, if found, would still require its interface, board assumptions and usable license to be established; its mere existence would not qualify it for the modern base.

In parallel, resolve the PMIC register discrepancies and preserve a read-only baseline from the actual board when available. The source findings justify continued investigation without changing the agreed goals or claiming achieved performance. Concrete remaining work is recorded in [FOLLOW-UP.md](../FOLLOW-UP.md).

## Local sources

[r16-config]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf>
[r16-manual]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf>
[r16-datasheet]: <../allwinner/extracted/R16/IC/R16_Datasheet_V1.0.pdf>
[axp]: <../allwinner/extracted/R16/Firmware/AXP223 Datasheet V1.1 20131128.pdf>
[tina]: <../allwinner/extracted/R16/代码下载编译环境搭建/R16_Tina SDK Quick Start Guide.pdf>
[reference-schematic]: <../allwinner/extracted/Allwinner A33 Development Materials/Hardware/标案原理图/a33(a23)_tablet_std_v1_0_162.pdf>
[dram-list]: <../allwinner/extracted/R16/Hardware/R16支持列表/Allwinner Axx SDRAM Support List-V1.02_20150412.pdf>
