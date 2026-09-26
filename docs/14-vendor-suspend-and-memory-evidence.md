# Vendor evidence for R16 suspend, memory retention and power control

Research date: 27 September 2026. This report examines the manuals supplied in `GameShellNeo/allwinner`, including documents extracted from the R16 and A33 archives. It supplements [the upstream sleep/wake investigation](07-sleep-and-wake-feasibility.md). No image was built, vendor executable run, or device configuration changed.

**The supplied R16 documents materially strengthen the case for investigating deep sleep:** they explicitly describe super standby, CPU power control, DRAM self-refresh and ARISC activity during standby. We no longer need to rely solely on A33 compatibility and historical forum reports for that architectural direction. However, these are vendor features and configuration interfaces; the inspected material still lacks the complete controller/PHY retention sequence and firmware integration needed to implement reliable GameShell sleep. [R16 user manual, PDF p. 24][r16-manual-24]; [R16 configuration, PDF pp. 11–14][r16-config-11]; [ARISC power checking, PDF p. 59][r16-config-59].

Subsequent source investigation: [report 17](17-vendor-firmware-and-dram-trace.md) recovers A33 self-refresh/clock/PHY operations from vendor source and traces historical firmware interfaces. These operations narrow the programming gap but do not provide a qualified modern whole-system suspend implementation. [Report 19](19-modern-suspend-integration.md) and [the implementation plan](20-base-implementation-plan.md) record the remaining work.

All page numbers below are **one-based PDF page positions**, including covers. Some memory guides print different page numbers in their headers. Links open the relevant starting page where the PDF viewer supports `#page=`. Chinese descriptions are summarized in English; key identifiers retain the spelling used in the source.

## Source scope and revisions

| Inspected document | Revision evidence | Role and limitation |
| --- | --- | --- |
| [R16 user manual][r16-manual] | Cover: v1.0, 30 December 2014; 568 PDF pages | Primary R16 architecture/register reference. This is **not** the remotely located v1.2 manual discussed in report 07. |
| [A33 user manual v1.1][a33-manual] | Cover: v1.1, 22 September 2014; 574 PDF pages | Comparison of memory map, power features and SDRAM chapter. |
| [A33 user manual v1.0][a33-manual-old] | Cover: v1.0, 25 May 2014; 580 PDF pages | Earlier comparison; page locations differ from v1.1. |
| [R16 System Configuration][r16-config] | PDF p. 2: v1.0, 28 February 2015; 62 pages | Vendor configuration fields and examples, not Linux device-tree bindings. |
| [A33 System Configuration V4][a33-config] | PDF p. 2: v4.0, 15 December 2014; 62 pages | Confirms related vendor conventions; includes Android L changes. |
| [R16 Android memory configuration][r16-memory] | PDF p. 2: v1.0, 28 February 2015; 16 pages | Android/Linux 3.4 memory allocation and policy guidance. |
| [A33 memory configuration V3][a33-memory] | PDF p. 2: v3.0, 12 December 2014; 13 pages | Android L revision; records removal of earlier cache/low-memory-killer guidance. |

The findings below use documents whose ZIP entries passed the recorded CRC checks. Neither recovered CRC-failed PDF is used as evidence. See [the extraction inventory](../allwinner/INVENTORY.json) for provenance and integrity results. Text searches selected relevant sections, then critical tables and register pages were rendered for visual checking; this is a targeted power/memory audit, not a claim that every peripheral chapter was fully reviewed.

## 1. Direct R16 evidence for standby and a management processor

The R16 manual's power-management section explicitly lists CPU DVFS, super standby and talking standby. Its watchdog chapter separately refers to resetting **CPUS** or the whole system. The configuration guide describes CPUS UART/RSB interfaces and explicitly names **ARISC** in its super-standby power-checking comments. Together, these are substantial first-party evidence for the vendor's management-processor-based power architecture on its R16 platform. They do not provide a complete AR100 programming reference or demonstrate operation on the owner's board. [R16 manual, PDF pp. 24 and 156][r16-manual-24]; [R16 watchdog, PDF p. 156][r16-manual-156]; [R16 configuration, PDF pp. 58–59][r16-config-58].

| Vendor interface | What the document says | What it establishes for GameShellNeo |
| --- | --- | --- |
| `[pm_para]` / `standby_mode` | Value 1 selects the vendor's super-standby support; another value selects normal standby. | The vendor distinguishes sleep mechanisms. These names must not be equated automatically with Linux `s2idle` and `deep`. |
| `[wakeup_src_para]` / `cpu_en` | Chooses CPU power on/off; the example uses 0. | CPU-off behavior is an intended vendor configuration, not merely screen blanking. |
| `dram_selfresh_en` | The example enables DRAM self-refresh. | Retained-memory sleep is an explicit design lead; register sequencing remains missing. |
| Wake-source entries | Examples identify Wi-Fi/Bluetooth wake GPIOs. | Wake configuration is part of the mechanism. These example pins are not a GameShell wiring specification. |
| `[s_uart0]` and `[s_rsb0]` | Describe CPUS UART and RSB settings. | Firmware/OS ownership of the PMIC bus and diagnostic UART needs a deliberate design. |
| `[s_powchk]` | Describes ARISC checking expected power state and consumption during super standby. | The vendor envisaged monitoring outside ordinary application execution. This is not yet a proven low-battery shutdown implementation. |

Sources: [R16 configuration, PDF p. 11][r16-config-11], [pp. 13–14][r16-config-13], [pp. 58–59][r16-config-58]. These are configuration descriptions and examples, **not commands to apply to a current kernel**. Their consuming SDK code, actual supported modes and board wiring must be established before adapting their behavior.

There is also direct vendor support for the R16/A33 software relationship. The R16 memory guide identifies `sun8iw5p1` as R16; the A33 V3 guide identifies that same platform code as A33. This reinforces the upstream compatibility evidence in report 07. It does not establish that every peripheral, package or board design is interchangeable. [R16 memory guide, PDF p. 12][r16-memory-12]; [A33 memory guide, PDF p. 10][a33-memory-10].

**Effect on report 07:** retain the conclusion that stock modern upstream software does not yet provide the complete examined sleep path. Strengthen its hardware-feasibility assessment: missing R16 management hardware is not an evidenced explanation for the software gap. The next investigation should concentrate on the firmware, clocks, memory sequencing and board power dependencies.

## 2. The manuals expose useful registers, but not the missing retention algorithm

The R16 manual gives the following CPU-visible blocks. The corresponding A33 v1.1 memory-map page lists the same bases, providing concrete comparison points rather than relying on matching product names. [R16 memory map, PDF p. 29][r16-manual-29]; [A33 memory map, PDF p. 29][a33-manual-29].

| Block | Base address in the supplied manuals | Relevance |
| --- | --- | --- |
| DRAM common/controller/PHY | `0x01c62000`, `0x01c63000`, `0x01c65000` | Identifies the hardware to investigate for retention and restoration. |
| R_INTC | `0x01f00c00` | Candidate always-on interrupt-controller boundary already investigated in report 07. |
| R_PRCM | `0x01f01400` | Identifies the power/reset/clock-control block; the inspected manual does not provide a complete PRCM programming sequence. |
| CPUCFG / R_CPUCFG | `0x01f01c00` | CPU reset, status and standby-related controls. |
| R_RSB | `0x01f03400` | PMIC communication path that must recover correctly after firmware activity. |

The CPUCFG chapter documents per-core reset/status registers, WFI/WFE status and a super-standby flag register at offset `0x1a0`. Its event register describes waking cores from **WFE**. These are distinct observations: a WFI status flag or WFE event does not by itself implement powered-off CPU recovery or DRAM retention. The standby flag's protected write procedure identifies a potential state marker for boot/resume code; its retention lifetime and the surrounding firmware contract still need verification. [R16 manual, PDF pp. 90–98, especially p. 96][r16-manual-90]; [standby flag and event details, PDF p. 96][r16-manual-96].

The CCU chapter provides PLL, clock-gating and reset information. In particular, PDF pp. 63–64 describe DDR PLL selection/scaling controls, MBUS reset and DRAM-access clocks for display/video clients. This helps form a register checklist. It **does not establish that it is safe to gate or retune memory while CPUs or DMA clients still access it**, nor does it specify the whole self-refresh/PHY recovery sequence. That ordering remains an implementation requirement to derive from authoritative register information and relevant working code. [R16 CCU overview, PDF p. 32][r16-manual-32]; [DDR/MBUS controls, PDF pp. 63–64][r16-manual-63].

The important documentation gap is now confirmed locally, rather than inferred from a remote table of contents:

- R16 v1.0 has one SDRAM overview page at **PDF p. 281**, followed immediately by NAND at p. 282.
- A33 v1.1 has the equivalent overview at **PDF p. 283**, followed by NAND at p. 284.
- A33 v1.0 places it at **PDF p. 289**, followed by NAND at p. 290.

Those pages describe DDR3/DDR3L, refresh, configurable timing and memory size, but provide no DRAM-controller/PHY register list or suspend/resume algorithm. [R16 SDRAM section][r16-manual-281]; [A33 v1.1 SDRAM section][a33-manual-283]; [A33 v1.0 SDRAM section][a33-manual-old-289]. The configuration guide's self-refresh switch is therefore valuable **intent evidence**, not a replacement for those missing implementation details.

## 3. DRAM configuration, DVFS and sleep must be treated separately

The R16 `[dram_para]` section names clock, memory type, termination, calibration and timing parameters. It describes many `dram_tpr*` and other fields as manufacturer-adjusted internals, without decoding them; its example includes a 552 MHz clock and opaque hexadecimal values. These values must not be adopted as CPI v3.1 settings. Their relevance is to identify which information a known-good board configuration or bootloader can supply. [R16 configuration, PDF pp. 11–13][r16-config-11].

Three mechanisms appear in this material:

| Mechanism | Vendor evidence | Appropriate research use |
| --- | --- | --- |
| CPU voltage/frequency scaling | `[dvfs_table]` defines frequency intervals and associated voltages, including an explicitly named extreme-frequency setting. | Compare against the current upstream operating-point table and actual CPU rail; do not treat example frequencies as validated operating points. |
| DRAM frequency/voltage scaling during operation | `[dram_dvfs_table]` and `[dram_scene_table]` select levels associated with use cases such as home, video and background audio. | Investigate whether modern drivers already provide the mechanism and what transition constraints apply. Android scene policy is not automatically appropriate for the minimal base. |
| DRAM self-refresh during sleep | `[wakeup_src_para]` separately enables self-refresh while configuring CPU power and wake sources. | Establish retention entry/exit and memory integrity independently of runtime frequency scaling. |

Sources: [R16 configuration, PDF pp. 56–57][r16-config-56], [pp. 60–61][r16-config-60], [pp. 13–14][r16-config-13]. A lower memory clock is not equivalent to a retained-memory sleep state. The material supports investigating both, but supplies no measured GameShell power savings for either.

**No standby-power claim should be made from `s_system_power=50`.** The guide presents 50 mW as a configurable maximum used to classify abnormal consumption in the vendor's ARISC check. It is neither a measured platform result nor a promised CPI standby level. Similarly, `s_power_reg` describes an expected regulator-state bitmap whose definitions are deferred to `aw_pm.h`; the document alone does not decode the required supply states. [R16 configuration, PDF p. 59][r16-config-59].

## 4. The “memory configuration” guides address Android allocation policy

These filenames initially look promising for DDR bring-up, but their subject is principally reserved memory, ION/CMA allocation, virtual-address space, compressed swap, low-memory policy and Android process heaps. The R16 guide discusses Linux 3.4 configuration and multimedia memory reservations; it is not the missing DRAM training or retention manual. [R16 memory guide, PDF pp. 3 and 6–12][r16-memory-3]; [memory-management definitions, PDF p. 6][r16-memory-6].

Some historical policies would work against the project's aim if copied without evaluation. The R16 guide describes a framework that periodically drops filesystem caches and shows changing `drop_caches` permissions to permit broad writes. The later A33 Android L revision explicitly removes earlier cache-dropping and low-memory-killer guidance. This is evidence that the archive contains different software generations and changing policies, not one coherent recommended configuration. GameShellNeo should select memory policy from its actual workloads and modern kernel behavior. [R16 guide, PDF pp. 6 and 9][r16-memory-6]; [permission patch, PDF p. 9][r16-memory-9]; [A33 V3 revision history, PDF p. 2][a33-memory].

The useful transferable idea is to size contiguous allocations from real consumers and validate under representative workloads. The vendor examples target GPU/video/camera/Android certification workloads; several of those are outside the initial GameShellNeo scope. They are not evidence that the base needs the same fixed reservation sizes, Android allocators or heap settings. [R16 memory guide, PDF pp. 10–11][r16-memory-10]; [A33 V3 memory guide, PDF pp. 8–9][a33-memory-8].

## 5. Specific source inconsistencies to resolve before implementation

These are visible in the original rendered pages, not merely suspected text-extraction errors.

| Location | Observed inconsistency | Consequence |
| --- | --- | --- |
| R16 configuration, p. 59 | Chinese and English descriptions reverse the assignment of `s_powchk_used` bits 0 and 1 between power-state and consumption exceptions. | Resolve using the consuming source and tests; do not choose a bit from prose alone. |
| R16 configuration, p. 58 | The `[s_rsb0]` example contains `s_uart_*` keys although its table documents `s_rsb_*` keys. | Treat it as a template/copying defect, not a confirmed parser contract. |
| R16 configuration, pp. 13–14 | The table and example differ in DRAM self-refresh/frequency field spelling and presentation. | Find the actual parser and distinguish legacy fields from typographical errors. |
| R16 configuration, p. 60 | DRAM DVFS prose comments show voltage/frequency ranges that disagree with the adjacent numeric example. | Do not infer safe voltages or thresholds from the sample. |
| R16 Lichee guide, p. 5 | A directory illustration names `arisc_sun9iw1p1.bin`, while surrounding R16 bootloader paths use `sun8iw5p1`. | This listing does not identify the correct R16 firmware binary and is not a binary supplied by the archive. |

Sources: [R16 configuration, p. 59][r16-config-59], [p. 58][r16-config-58], [pp. 13–14][r16-config-13], [p. 60][r16-config-60]; [R16 Lichee guide, PDF pp. 4–5][r16-lichee-4]. The inspected A33 V4 guide reproduces several of these examples, so its agreement is not independent validation of their correctness. [A33 configuration, PDF pp. 13–14 and 59–60][a33-config-13]; [A33 power-check examples][a33-config-59].

## 6. What this enables next

The following are **proposed investigations**, not completed implementation:

1. **Recover the narrow implementation references that the PDFs identify.** Obtain the relevant `sun8iw5p1` power-management definitions, `aw_pm.h`, DRAM initialization/retention routines, configuration parsers and firmware interface descriptions. Resolve which pieces have source and which remain binary. Downloading a complete legacy Android build is not inherently necessary to inspect these components.
2. **Record the owner's actual memory configuration.** Identify populated DRAM parts and preserve known-good bootloader configuration/logs. Relate boot timing, geometry and calibration to the physical board before designing retention; vendor example values are insufficient.
3. **Build a documented ownership and sequencing model.** Account for ARM secure-monitor context, SRAM use, ARISC execution, wake masks, CPU/DRAM rails, PLLs, RSB and all memory bus clients. Use modern standard interfaces where appropriate and historical code as evidence for behavior.
4. **Develop retention as a separately testable component if the remaining evidence supports it.** Demonstrate quiescence, self-refresh acknowledgement, retained data and recovery before advertising deep suspend. Preserve a known-working boot path and qualify progressively longer repeated cycles.
5. **Keep awake efficiency work independent.** Qualify CPU DVFS, unused-device power states and wakeup activity while the deeper firmware path is investigated. Evaluate runtime DRAM scaling only with a verified transition mechanism and stability evidence.

The new documents strengthen the rationale for this work but do not close the software gaps already established in [report 07](07-sleep-and-wake-feasibility.md). They provide no measured sub-second resume or week-long standby result for CPI v3.1. The recommended initial kernel and incremental suspend-to-idle qualification therefore remain unchanged; the deeper-sleep investigation now has more direct vendor evidence and a better-defined set of missing implementation references.

## Source links

[r16-manual]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=1>
[r16-manual-24]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=24>
[r16-manual-29]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=29>
[r16-manual-32]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=32>
[r16-manual-63]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=63>
[r16-manual-90]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=90>
[r16-manual-96]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=96>
[r16-manual-156]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=156>
[r16-manual-281]: <../allwinner/extracted/R16/IC/Allwinner_R16_User_Manual_V1.0.pdf#page=281>
[a33-manual]: <../allwinner/A33 user manual release 1.1.pdf#page=1>
[a33-manual-29]: <../allwinner/A33 user manual release 1.1.pdf#page=29>
[a33-manual-283]: <../allwinner/A33 user manual release 1.1.pdf#page=283>
[a33-manual-old]: <../allwinner/Allwinner_A33_user_manual_v1.0_20140525.pdf#page=1>
[a33-manual-old-289]: <../allwinner/Allwinner_A33_user_manual_v1.0_20140525.pdf#page=289>
[r16-config]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=2>
[r16-config-11]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=11>
[r16-config-13]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=13>
[r16-config-56]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=56>
[r16-config-58]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=58>
[r16-config-59]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=59>
[r16-config-60]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=60>
[a33-config]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_System Configuration说明书_V4.pdf#page=2>
[a33-config-13]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_System Configuration说明书_V4.pdf#page=13>
[a33-config-59]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_System Configuration说明书_V4.pdf#page=59>
[r16-memory]: <../allwinner/extracted/R16/Firmware/R16 Android方案内存配置说明.pdf#page=2>
[r16-memory-3]: <../allwinner/extracted/R16/Firmware/R16 Android方案内存配置说明.pdf#page=3>
[r16-memory-6]: <../allwinner/extracted/R16/Firmware/R16 Android方案内存配置说明.pdf#page=6>
[r16-memory-9]: <../allwinner/extracted/R16/Firmware/R16 Android方案内存配置说明.pdf#page=9>
[r16-memory-10]: <../allwinner/extracted/R16/Firmware/R16 Android方案内存配置说明.pdf#page=10>
[r16-memory-12]: <../allwinner/extracted/R16/Firmware/R16 Android方案内存配置说明.pdf#page=12>
[a33-memory]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33 平板方案内存配置说明_V3.pdf#page=2>
[a33-memory-8]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33 平板方案内存配置说明_V3.pdf#page=8>
[a33-memory-10]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33 平板方案内存配置说明_V3.pdf#page=10>
[r16-lichee-4]: <../allwinner/extracted/R16/Firmware/R16_lichee使用手册.pdf#page=4>
