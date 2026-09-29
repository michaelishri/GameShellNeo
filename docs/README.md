# GameShellNeo research

**The refreshed diagnostic image has booted on the owner's CPI v3.1:** [report 27](27-diagnostic-integration-refresh.md) records the NEO-7 integration fixes, passing live ACL/BPF/service checks and the owner's accepted AU access-point announcement. [Report 26](26-first-card-and-boot-validation.md) preserves the initial boot and USB correction. [The build validation report](25-first-build-validation.md) records the original artifact and offline checks. [The approved specification](23-first-build-spec.md) freezes the milestone, and [the build workflow](24-building-and-testing.md) describes its stages. NEO-5 repeated hardware qualification remains open in Kaneo. Historical research statements below describe their inspection dates.

Research date: **2026-09-27**. Scope: the supplied repositories, original hardware and software, and primary online sources for subsequent development. This is the research baseline for further guidance; it does not select a new operating system or launcher.

Subsequent discussion established [the initial base-image requirements](06-base-requirements.md), including a provisional minimal Armbian/Debian base and deferred features. Reports 01–05 remain the research record; document 06 records the owner's decisions. [Follow-up activities](../FOLLOW-UP.md) track remaining checks.

**Start with [the implementation plan](20-base-implementation-plan.md)** for the research conclusions and proposed sequence. The focused source investigation in reports 17–19 found relevant A33 DRAM operations, an existing ARMv7 PSCI/SCPI patch stack, and a concrete Linux USB current-limit setter defect. Deep suspend and sleeping-battery protection remain implementation and hardware-validation work. No image had been built or tested at the end of that research phase.

The first [read-only inspection of the owner's running GameShell](21-installed-hardware-baseline.md) now records the installed kernel/bootloader, memory, power settings, battery telemetry, preserved boot artifacts and development-access status. SSH works directly over Wi-Fi and through the Mac over both Wi-Fi and USB Ethernet. The owner has confirmed CPI v3.1 printed on the mainboard. [Serial-console preparation](22-serial-cable-and-console-preparation.md) records the recovered cable documentation and pending harness identification.

The earlier research phase is complete in reports 07–12. [The feasibility summary and validation plan](11-feasibility-summary-and-validation-plan.md) recommends a modern LTS development baseline and records the broader acceptance tests. Report 12 assesses the additional R16/A33 sources supplied during the investigation. These recommendations do not change the agreed goals.

The subsequently supplied local Allwinner collection is assessed in **[report 13](13-allwinner-document-findings.md)**, with detailed sleep/memory, PMIC and platform findings in reports 14–16. It adds direct R16 vendor evidence for super standby and useful implementation clues, while leaving the complete modern retention/resume path unimplemented. The [document catalogue](../allwinner/README.md) records all 77 PDFs and two ZIP integrity exceptions.

## Reports

| Report | Contents |
| --- | --- |
| [49 — Connected firmware validation](49-connected-firmware-validation.md) | Candidate association, four software reconnections and independently verified original-firmware recovery |
| [50 — Direct USB diagnostic notes](50-usb-diagnostic-implementation-notes.md) | Source-reviewed boundaries for direct poll counts and bounded read-error tests; implementation pending |
| [48 — A0 firmware trials](48-a0-firmware-trials.md) | Reversible upstream A0 scan comparison, runtime identity correction and network visibility limits |
| [47 — Wi-Fi firmware options](47-wifi-firmware-options.md) | Exact A0 silicon compatibility, candidate binary versions and primary-source provenance |
| [46 — Wi-Fi transition and scan recovery](46-wifi-transition-and-scan-recovery.md) | Guarded .env network changes, automatic rollback and firmware/host scan isolation |
| [45 — USB polling idle comparison](45-usb-polling-idle-comparison.md) | Repeatable experimental/stock/experimental protocol; measurements pending network recovery |
| [44 — Diagnostic.5 initial validation](44-diagnostic5-hardware-validation.md) | Stock/experimental startup and 20 cable cycles, repeatable rapid-test support, hotspot recovery and remaining power/instrumentation limits |
| [43 — macOS card mount guard](43-macos-card-mount-guard.md) | Failed-readback diagnosis, read-only sector comparison, temporary target-specific mount veto and verified recovery |
| [42 — Remote network preparation](42-remote-network-preparation.md) | Mac tailnet transport, Wi-Fi SSH through the Mac, private provisioning refresh and pre-existing Wi-Fi crash evidence |
| [41 — USB polling experiment](41-usb-polling-experiment.md) | Diagnostic.5 opt-in driver, actual-source/compiled-DTB tests, next-boot selection and pending hardware qualification |
| [40 — Diagnostic.4 validation](40-diagnostic4-hardware-validation.md) | Verified build/flash, labeled backlight, load/recovery, four USB reconnects and four cold starts; exact repeatable tasks and qualification limits |
| [39 — Clock rate constraints](39-clock-rate-constraint-optimization.md) | Once-per-search NM/NKM limits, native/ARM32 equivalence, lookup counts and isolated ARM object builds |
| [38 — USB work lifetime](38-usb-work-lifetime.md) | Managed-resource ordering correction, actual-source probe/IRQ/poll regressions and isolated ARM driver build |
| [37 — Driver optimization audit](37-driver-optimization-audit.md) | Clock constraint walks, redundant backlight requests, RSB autosuspend interaction and display/USB lifecycle findings |
| [36 — USB polling policy](36-usb-polling-policy.md) | Host/peripheral timing distinction, experimental absent-state fallback, activation checks, workqueue races and validation requirements |
| [35 — USB detection capture](35-usb-detection-capture.md) | Shared IRQ/uevent/controller recorder, read-only PMIC configuration, test coverage and instrumented cable cycles |
| [34 — USB status polling investigation](34-usb-status-polling-investigation.md) | AXP223 polling rationale, USB detection deadlines, board wiring, live attached state and requirements for reducing unnecessary work |
| [33 — NKMP clock-search optimization](33-nkmp-clock-search-optimization.md) | Exact-match exit, native/ARM32 equivalence, verified diagnostic.3 installation, 92% lower recorded governor CPU time and power measurement limits |
| [32 — Governor-rate comparison and function attribution](32-governor-rate-comparison.md) | Live original/slower/original comparison, restoration, modest estimated power savings, directly sampled NKMP cost and reusable perf workflow |
| [31 — Awake-power profile](31-awake-power-profile.md) | CPU/interrupt/radio captures, substantial governor-worker activity, instrumentation limits and prioritized follow-ups |
| [30 — BL-5C battery identification](30-bl5c-battery-identification.md) | Owner-supplied replacement-pack listing, primary-source charging examples and unresolved exact-pack limits |
| [29 — Hardware qualification](29-hardware-qualification.md) | Ten cold starts and USB reconnections, keypad/backlight and load results, power transitions, Lightkey issue and charging-voltage discrepancy |
| [28 — Original-card recovery backup](28-original-card-recovery-backup.md) | Read-only whole-card recovery workflow, private copies, integrity checks and recovery limits |
| [27 — Diagnostic integration refresh](27-diagnostic-integration-refresh.md) | New Zealand provisioning, regulatory database load/signature fixes, kernel/userspace corrections, remaining warning classification and post-flash checks |
| [23 — First-build specification](23-first-build-spec.md) | Approved diagnostic scope, immutable inputs, boot/storage/access contract and acceptance gates |
| [24 — Building and testing](24-building-and-testing.md) | Private provisioning, pinned build stages, offline checks and first hardware session |
| [25 — First-build validation](25-first-build-validation.md) | Completed diagnostic image, exact hash, build evidence and remaining hardware qualification |
| [26 — First card and boot validation](26-first-card-and-boot-validation.md) | Owner-confirmed spare, private transfer, flashing procedure and physical test results as they become available |
| [01 — Repository map](01-repository-map.md) | Exact local snapshots, directory map, build assets, missing pieces and evidence boundaries |
| [02 — Hardware](02-hardware.md) | Board architecture, schematics, display/graphics, power, input, audio, connectivity and revision discrepancies |
| [03 — Original software](03-original-software.md) | Boot and desktop environment, Python and Go launchers, games, integration, update mechanisms and reuse constraints |
| [04 — Release history and ecosystem](04-release-history-and-ecosystem.md) | Official and community images, later development, upstream support and remaining gaps |
| [05 — Python launcher](05-python-launcher.md) | Follow-up assessment of the newly cloned `launcher` repository, historical differences, session integration and reuse boundaries |
| [06 — Initial base requirements](06-base-requirements.md) | Agreed scope, power policies, development setup, aspirational targets and remaining feasibility work |
| [07 — Sleep and wake feasibility](07-sleep-and-wake-feasibility.md) | Linux, U-Boot and Crust suspend paths, DRAM-retention gaps, PMIC wake and qualification steps |
| [08 — Driver and board support](08-driver-and-board-support.md) | Legacy patch audit, upstream comparison, display/backlight, CPU power management, wireless and USB integration |
| [09 — Battery and power policy](09-battery-and-power-policy.md) | Percentage and charging support, calibration limits, asleep protection, idle policy and software-only measurement |
| [10 — Boot and update architecture](10-boot-and-update-architecture.md) | Armbian/Debian inputs, cold-boot measurement, SD layout constraints and future OTA design |
| [11 — Feasibility summary and validation plan](11-feasibility-summary-and-validation-plan.md) | Recommended baseline, major findings, proposed acceptance tests and the next decision |
| [12 — R16/A33 source guide](12-r16-a33-source-guide.md) | Upstream evidence connecting R16 and A33, supplied links, vendor manuals, archive access limits and a hardware error in the audio tutorial |
| [13 — Local Allwinner document findings](13-allwinner-document-findings.md) | Collection inventory, integrity checks, main conclusions, electrical references and remaining gaps |
| [14 — Vendor suspend and memory evidence](14-vendor-suspend-and-memory-evidence.md) | R16 super standby, ARISC, CPU/DRAM controls, register references and missing retention implementation |
| [15 — Vendor PMIC and power evidence](15-vendor-pmic-and-power-evidence.md) | Wake rearming, battery alarms/calibration, voltage restoration and register discrepancies |
| [16 — Vendor platform and driver evidence](16-vendor-platform-and-driver-evidence.md) | Historical SDK boundaries, pin/supply ownership, display, radios, input and modern integration implications |
| [17 — Vendor firmware and DRAM trace](17-vendor-firmware-and-dram-trace.md) | Actual A33 source paths, historical ARM/ARISC interfaces, DRAM operations, binary boundaries and misleading inactive code |
| [18 — PMIC history and suspend contract](18-pmic-history-and-suspend-contract.md) | AXP223 current-table history, conflicting vendor documents, setter defect and Linux/firmware ownership |
| [19 — Modern suspend integration](19-modern-suspend-integration.md) | Existing ARMv7 PSCI/SCPI patches, Crust gaps, SRAM/clock/regulator contracts and staged firmware tests |
| [20 — Base implementation plan](20-base-implementation-plan.md) | Recommended architecture, concrete change sets, dependencies, hardware baseline and implementation checkpoints |
| [21 — Installed hardware baseline](21-installed-hardware-baseline.md) | First direct device inspection, working SSH paths, USB diagnosis, installed power configuration and preserved boot references |
| [22 — Serial cable and console preparation](22-serial-cable-and-console-preparation.md) | Recovered Banggood listing and cable guide, limits of the PL2303GT datasheet, and physical console connection prerequisites |

## Findings that change the starting picture

**January 4, 2020 is the date still advertised for v0.5, but it is not the end of the published image history.** The research found a January 2023 v0.6 gamma announcement and later community work. A published experimental image, a current download listing and an actively supported release are different things. The release-history report records the evidence and limitations. [Official v0.5 listing](../../GameShell/README.md); [v0.6 gamma announcement](https://forum.clockworkpi.com/t/gameshell-os-image-v0-6-gamma/9419/1); [release investigation](04-release-history-and-ecosystem.md).

**The workspace contains substantial revival material, but no complete OS build in the three inspected repositories.** There are schematics, firmware, historical kernels and bootloaders, Linux 5.15 patches, and launcher source. The Go build scripts produce application binaries; they do not assemble a bootable SD image. Later external build projects deserve separate consideration. [Repository inventory](01-repository-map.md); [build script](../../LauncherGoDev/build.sh); [kernel build notes](../../GameShell/Code/Kernel/v0.6/README.md).

**The original user experience and the current Go tree must be understood separately.** The Go project began in 2018, so it would also be misleading to describe Go as wholly new after 2020. The software report distinguishes historical Python source, Go evolution, image documentation and what remains unverified on an actual disk image. [Software analysis](03-original-software.md).

**Hardware revision identification matters.** Published schematics, the product page and firmware artifacts contain differences, including the keypad microcontroller identification. The reports preserve those disagreements. The owner's mainboard is now identified as CPI v3.1; keypad and memory-package markings remain outstanding. Code enabling a device is not proof that a new image supports it reliably. [Hardware analysis](02-hardware.md); [installed baseline](21-installed-hardware-baseline.md).

## Questions left open for the next phase

These are research gaps, not requests to choose an implementation now:

- Which keypad and memory packages are fitted? The CPI v3.1 mainboard marking and installed OS/boot artifacts are now recorded in report 21.
- What exact packages, services and local modifications are present in the image to be used as the historical baseline?
- Which later build recipe can still be reproduced from pinned sources and obtainable dependencies?
- Which hardware functions work together on that build: accelerated rendering, LCD, HDMI where fitted, audio, wireless, USB networking, battery reporting and shutdown?
- Which parts of the existing interface and game-launch conventions should GameShellNeo retain?

The follow-up Python assessment includes the newly supplied local clone; the original historical analysis remains explicitly dated. Subsequent device inspection is recorded separately in report 21. During that inspection, no device was flashed, no original source checkout was changed, and no full multi-gigabyte OS image was downloaded or mounted. The device's boot region and boot partition were copied read-only for local reference. The later GameShellNeo build and offline image inspection are recorded in report 25; the original physical card remains untouched.
