# GameShellNeo: integrating modern ARMv7 suspend firmware

Research date: 27 September 2026. Scope: source inspection and an implementation proposal; no firmware was built, installed or run. Read alongside [historical standby and DRAM evidence](17-vendor-firmware-and-dram-trace.md) and the [PMIC investigation](18-pmic-history-and-suspend-contract.md).

## Finding and recommended direction

**A public ARMv7 U-Boot-to-Crust implementation already exists, including an explicit A33 extension.** We should assess and adapt that work to current U-Boot, then implement the missing A33 DRAM retention and board power contracts in Crust. We do not need to invent a Linux suspend API or begin by porting TF-A to R16. This is a credible engineering route, not evidence that GameShell deep sleep already works.

Samuel Holland's `smaeul/u-boot` development tree contains `psci-scpi.c`: an ARMv7 secure monitor that translates PSCI calls into SCPI messages for Crust. Its A33 variant uses shared memory at `0x00053e00`. OpenWrt also preserves the relevant series, including `0043-sunxi-psci-Delegate-PSCI-to-SCPI.patch` and `0044-sunxi-Enable-SCP-SCPI-on-A33-as-well.patch`. The latter is dated June 2022. These are useful source references; OpenWrt's package builds **RISC-V D1 targets against U-Boot 2023.01**, so carrying the patches does not establish present-day A33 testing. [Author's monitor][monitor], [A33 patch][a33-patch], [OpenWrt package][ow-package]

The remaining substantive gaps are A33 DRAM retention, firmware loading and startup on the chosen board, reliable monitor behavior, regulator mapping and voltage restoration, and shared clock ownership. **CPU power-off idle states require their own wake implementation and must remain disabled initially.**

## Fixed audit points and search limits

| Component | Inspected revision | What this establishes |
|---|---|---|
| Linux | `v6.18` | Existing PSCI system-suspend entry and sunxi wake/RSB mechanisms |
| Upstream U-Boot | `v2026.07`, commit `ece349ade2973e220f524ce59e59711cc919263f` | Current sunxi ARMv7 monitor and image-loader baseline |
| Crust | `499a362645e6ce6ac1fd8ea8d0f25d4df6690688` | Current A23/A33 support, SCPI, clocks, PMIC and missing DRAM backend |
| Samuel Holland's U-Boot | `9d8202dd5cab57fa56880179b4e53c79f9ef24a3` | Existing A33 PSCI/SCPI implementation, dated October 2022 |
| OpenWrt | `44b73b738d18e424d86a34be3fb1d93cf3d718d6` | Preserved patch boundaries and their package context |
| TF-A | `v2.15.0`, commit `da738d5eae93af342fdc4995dd3c05acb4c9d757` | Current Allwinner platform documentation and common SCPI implementation |

This was a bounded inspection of relevant source directories, selected development branches and public patch searches. It found an existing ARMv7 integration; it did not find a ready, qualified GameShell image or a maintained R16 TF-A platform. Fetches and temporary checkouts are under `/tmp/gameshellneo-firmware-research/modern`. Before implementation, refresh maintained release patchlevels without silently changing these audit references.

## How Linux can enter the new implementation

Linux 6.18 already supplies the desired interface. With `CONFIG_SUSPEND`, it queries `PSCI_FEATURES(SYSTEM_SUSPEND)` and installs platform suspend operations when firmware reports support. The entry calls ARM `cpu_suspend()`, which preserves Linux CPU context, and invokes PSCI with the physical `cpu_resume` address. `CPU_SUSPEND`, used by cpuidle, is a separate operation. Adding idle-state DT nodes cannot substitute for a working system-suspend implementation. [Linux PSCI][linux-psci]

Upstream U-Boot's sunxi ARMv7 implementation provides CPU on/off support, but does not override `psci_system_suspend()` or `psci_cpu_suspend()`. Those functions fall through to generic weak stubs returning “not implemented.” The default sunxi PSCI configuration remains 0.1. U-Boot already has secure monitor relocation, per-CPU context storage, assembly entry/exit, cache shutdown and DT fixup machinery that can be retained. The change belongs in a reviewed sunxi monitor backend and its feature advertisement. [Upstream sunxi PSCI][upstream-psci], [generic ARMv7 PSCI][upstream-psci-asm], [monitor configuration][monitor-config], [PSCI DT fixup][psci-dt]

The recovered monitor supplies a concrete starting sequence:

1. Save the non-secure resume address and context ID in retained secure memory.
2. Send SCPI `SET_CSS_POWER_STATE` requesting core, cluster and CPU subsystem off.
3. Execute the ARMv7 cache/coherency shutdown helper and enter WFI.
4. Crust waits until the core is actually in WFI, then handles the CPU subsystem and system state transition.
5. On wake, Crust restores the required hardware before restarting the last active core. The secure monitor restores the required GIC security configuration and returns through the existing ARMv7 entry path to Linux's resume address. [Monitor][monitor], [Crust CSS state machine][crust-css], [A33 CPU control implementation][crust-cpu]

```mermaid
sequenceDiagram
    participant L as Linux 6.18
    participant M as ARMv7 secure monitor
    participant C as Crust on AR100
    participant H as DRAM / PMIC / wake hardware
    L->>L: Quiesce drivers; arm wake IRQs; offline secondary CPUs
    L->>M: PSCI SYSTEM_SUSPEND(cpu_resume)
    M->>C: SCPI CPU subsystem off
    M->>M: Flush caches; WFI
    C->>H: Verified retention and power sequence
    H-->>C: PMIC power-key interrupt
    C->>H: Restore rails, clocks and DRAM
    C->>M: Restart saved lead core
    M->>L: Return to physical cpu_resume
    L->>L: Restore drivers and userspace
```

This diagram is the proposed integration contract, not a measured GameShell trace.

## Adaptation boundaries in U-Boot

The preserved series separates reasonably into FIT support (`0025`), H3 CPU0 workaround (`0037`), AR100 remoteproc (`0038`), SCP image/startup (`0040`), PSCI 1.1 definitions (`0041`), the SCPI monitor (`0043`), and A33 selection/memory addresses (`0044`). Rebase their **purposes**, not the entire 90-patch collection. Current U-Boot already has generic ARM32 FIT descriptions and an optional SCP image entry; A33 still needs suitable configuration and startup. `CONFIG_SUNXI_SCP_BASE` currently defaults to zero for A33. [Patch directory][ow-patches], [current image description][uboot-fit], [current sunxi configuration][uboot-config]

The H3 eGON resume shim works around an H3 Boot ROM CPU0 hotplug defect. The A33 patch explicitly selects the SCP image without selecting that H3 shim. It should not become a presumed R16 requirement merely because it occurs earlier in the series. Validate A33 CPU0 reset/entry behavior directly. [H3 workaround][h3-shim], [A33 patch][a33-patch]

The recovered code needs review and improvement before enabling suspend:

- Its mailbox waits have no timeout, and startup waits for SCP-ready without checking a usable capability set. A missing or crashed SCP must leave ordinary boot/recovery available.
- `psci_features()` advertises suspend unconditionally. Feature visibility must depend on the loaded firmware and the states actually implemented; an SCP magic word proves neither DRAM support nor resume correctness.
- `psci_cpu_suspend()` extracts state nibbles without complete validation. Validate power states, CPU identifiers, entry addresses and the requirement that other CPUs are off for system suspend.
- Audit its shared-memory ordering and multiprocessor locking, payload bounds, asynchronous command lifetime and failure paths. The current simple lock/wait code is evidence of an integration approach, not a production concurrency proof.
- The remoteproc example checks the magic and writes vectors, but does not establish a complete image-boundary contract. Add address/size validation and inspect its reset-status reporting against the framework API.

These are source-review requirements inferred from the inspected implementation, not observed GameShell failures. [Monitor][monitor], [remoteproc reference][remoteproc]

Prefer a small, explicitly supported PSCI feature set over copying the old “full PSCI 1.1” claim. Update the kernel's DT handoff consistently with the monitor's real version and capabilities. Keep a recovery configuration using the existing native monitor while the new backend is experimental.

## Retained SRAM, loading and SCPI contract

Crust's A23/A33 header maps AR100 SRAM addresses to ARM addresses with an offset of `0x40000`. Its current firmware starts at AR100 `0x10000`, corresponding to ARM `0x50000`. The linker includes BSS and a 1 KiB stack in the available region, so checking only `scp.bin` length is insufficient. [A23/A33 memory header][crust-memory], [Crust linker][crust-linker]

| ARM physical region/address | Intended use in the recovered layout |
|---|---|
| `0x40000`–`0x54000` | A23/A33 SRAM A2 address window; end exclusive |
| `0x40100`, `0x40200`, … `0x40e00` | AR100 exception vector instructions |
| `0x44000`–`0x4fc00` | Maximum configured U-Boot ARMv7 secure-monitor region |
| `0x4fc00`–`0x50000` | Gap reserved by the old shared layout; H3 shim logic is not selected for A33 |
| `0x50000`–`0x53c00` | Current Crust code/data/BSS/stack allocation: 15 KiB |
| `0x53c00`–`0x53e00` | Non-secure SCPI pair in the current Crust layout |
| `0x53e00`–`0x53f00` | Secure SCPI response, SCP → ARM |
| `0x53f00`–`0x54000` | Secure SCPI request, ARM → SCP |

The monitor locations follow U-Boot's configured base and maximum size; the SCP base follows the recovered `sun8i.h` layout and agrees with current Crust. Actual link maps, stack bounds, SPL scratch use and image load ranges still need checking. **There is also an ABI detail to resolve:** Crust's ABI document asks consumers to allow three SCPI clients, while the current A23 memory header reserves only two pairs. A third pair would consume another 512 bytes below `0x53c00`; this must not silently overlap firmware. [Monitor configuration][monitor-config], [historical image constants][sun8i-layout], [Crust ABI][crust-abi]

Startup must load the firmware, program AR100 exception vectors, release reset, receive/acknowledge SCP-ready, and establish a compatible feature contract before publishing suspend support. The existing `tools/load.c` demonstrates vector calculation and reset handling, but a userspace `/dev/mem` loader is not the proposed shipping mechanism. [Crust loader reference][crust-loader]

SCPI uses secure mailbox channels 0/1 and shared messages of 256 bytes each. The hardware mailbox clock/reset and channel-direction registers belong to Crust. Other software must not disable or reconfigure them during operation. Linux need not bind a direct SCPI client to obtain system suspend: its interface can remain PSCI through the monitor. [Crust ABI][crust-abi]

## Crust work: more than the DRAM driver

### A33 DRAM retention

Crust already has A23/A33 CPU and clock support, but this platform does not select `HAVE_DRAM_SUSPEND`; the available DRAM backends do not include A33. Without that capability, the system state machine selects `SD_NONE`, retaining clocks needed by DRAM. Merely loading Crust or exposing `deep` in Linux therefore cannot establish the intended low-power state. [Platform selection][crust-platform], [DRAM backend list][crust-dram-make], [system state machine][crust-system]

Implement an A33-specific `dram_suspend()`/`dram_resume()` pair using the register evidence described in report 17. Start with a fixed, verified DDR configuration, self-refresh and clock/PHY retention while keeping DRAM and system supplies powered. Establish master quiescence, saved state, status waits, pad hold, PLL restart and release order. Only enable `HAVE_DRAM_SUSPEND` after the complete pair preserves memory repeatedly. Vendor MDFS code is a useful register-sequence reference, not proof of recovery after arbitrary domain power loss.

Current U-Boot already has an A33 cold-boot DRAM driver. Its register definitions and training logic are useful cross-checks; rerunning complete cold initialization is not the proposed resume operation. Retention must preserve the existing Linux memory contents, using only the controller/PHY restart steps justified for that retained state. [A33 cold-boot DRAM driver][uboot-dram]

### Board supplies and PMIC state

There is a previously hidden integration gap: Crust contains an AXP221 regulator driver selected for AXP223, but `common/regulator_list.c` has no AXP221 mapping. An AXP223-only configuration leaves its CPU, DRAM, PLL and system supply handles null. Consequently the generic call to disable `cpu_supply` does **not** demonstrate that the A33 CPU rail is being switched. Add explicit, verified GameShell rail mappings; do not infer them from an A64 configuration. [Regulator selection][crust-reg-config], [supply handles][crust-supplies], [AXP221 output controls][crust-regulator]

Crust's AXP223 suspend method sets register `0x31` bits 4 and 3; resume sets bit 5. Its system code expects PMIC restoration and only falls back to enabling supplies if the PMIC resume operation fails. The traced regulator driver changes enable bits, with no pre-sleep voltage snapshot/restore mechanism. Resolve the AXP223 restoration and Linux register-cache contract before restoring a DVFS-dependent CPU clock. This is a requirement of this chosen implementation; register `0x31[3]` is not a universal Linux suspend prerequisite. [AXP223 suspend][crust-pmic], [PMIC resume][crust-pmic-common], [system sequence][crust-system]

### Clocks, ownership and cpuidle

Crust switches CPUS/AR100 to its internal oscillator. Linux 6.18's A23/A33 DT still describes AR100 as a fixed 1:1 child of the 24 MHz oscillator. Since RSB derives its divider from the reported parent rate, this mismatch must be addressed before trusting PMIC traffic after firmware startup. Implement an accurate, firmware-compatible clock description/driver or a deliberately constrained temporary clock contract; do not merely tune an unexplained RSB divider. [Crust R clock initialization][crust-r-clock], [Linux A23/A33 DT][linux-dtsi], [Linux RSB][linux-rsb]

Crust's A23 CCU initialization/resume also writes fixed CPU/AXI/APB and AHB1/APB1 source/divider values, and assumes APB2 uses OSC24M. Audit those against Linux's clock configuration. Preserve previous settings or explicitly reconcile the supported configuration; otherwise Linux may retain a software clock model that no longer matches hardware. [A23 CCU][crust-clock]

Finally, A33 core-off cpuidle is a separate gap: the shared A31-style CPU driver provides `css_get_irq_status()` only for H3, and the generic fallback returns zero. `css_poll()` relies on that result to restart powered-off cores on interrupts. System sleep uses `irq_poll()` and `css_resume()` instead. Keep ordinary WFI idle initially and omit deeper DT idle states until per-core IRQ wake is implemented and tested. [CPU control][crust-cpu], [default IRQ status][crust-css-default], [CSS wake logic][crust-css]

## Linux wake and handoff responsibilities

The target wake chain is the AXP223 power-key event → PMIC IRQ → always-on R_INTC → Crust wake polling → restored ARM CPU → Linux interrupt delivery. The mainline A23/A33 DT includes R_INTC at `0x01f00c00` with GIC SPI32. Linux's R_INTC syscore callbacks select wake sources for sleep and restore normal IRQ routing on resume. Board DT and PMIC child wake policy still determine which events reach this chain. [Linux DT][linux-dtsi], [R_INTC driver][linux-irq], [Crust IRQ polling][crust-irq]

Linux 6.18's RSB driver already suspends in the noirq phase and resets/reinitializes the controller on resume, providing the basic handoff required by Crust's ABI. This does not solve the parent-clock mismatch or PMIC register-cache coherence. Wake masks and pending-event acknowledgement must remain coordinated with Linux; Crust's inspected PMIC path does not program a separate AXP223 IRQ mask policy. [Linux RSB][linux-rsb], [Crust ABI][crust-abi], [AXP223 driver][crust-pmic]

Tests must distinguish successful resume from an immediately repeated sleep request. The AXP223 power-key path can deliver the wake press to userspace; the existing AXP288-specific suppression is not general AXP223 handling. This is a driver/policy qualification item, not a reason to add a bespoke power-button interface. [Linux power-key driver][linux-pek]

## Alternatives and implementation gates

| Route | Assessment |
|---|---|
| Current Linux + adapted U-Boot ARMv7 monitor + Crust | Preferred: source exists for the integration boundary; missing A33 behavior can be isolated and maintained |
| TF-A AArch32 + Crust | Architecturally possible, but the inspected Allwinner port implements ARMv8 BL31 targets. A new R16 platform/entry/memory port adds work without removing the A33 DRAM and PMIC tasks |
| Historical vendor kernel and ARISC firmware | Useful evidence and possible later comparison experiment; introduces obsolete kernel interfaces, binary firmware/provenance questions and a much larger maintenance burden |
| Mainline s2idle | Useful early driver/wake milestone; no basis for claiming the week-long target |

TF-A itself supports AArch32, so “TF-A is 64-bit only” would be incorrect. Its current Allwinner documentation and common code, however, provide no ready R16/A33 platform in the inspected scope. Borrow its mature PSCI validation and SCPI design as references when reviewing the U-Boot backend. [TF-A design][tfa-design], [Allwinner targets][tfa-platform], [TF-A SCPI implementation][tfa-scpi]

Proposed gates for later authorized implementation:

1. **Static integration contract:** freeze the memory map, source/license manifest, firmware feature advertisement, rail ownership and accepted clock configuration. Check monitor/Crust linker limits, DT schemas and image metadata. No sleep state should be advertised solely because a blob is present.
2. **Boot and communication:** prove clean boot with absent, invalid and valid SCP firmware; bounded startup failures; correct SCP identification and PMIC communication. Preserve recovery access. No DRAM changes yet.
3. **CPU handoff:** validate secondary CPU on/off, then CPU0 reset/resume entry and GIC/context restoration with conservative power settings. Keep runtime CPU power-off idle disabled.
4. **Memory retention:** exercise the new A33 entry/exit pair with system and DRAM supplies retained. Check retained memory patterns, repeated cycles and distinct diagnostic markers around each irreversible transition.
5. **PMIC power and wake:** add verified CPU rail control and voltage restoration; test power-button wake, battery-only/USB-powered cases, low battery, charger transitions and repeated wake presses. Retain other domains until their savings and restoration are demonstrated.
6. **Full Linux qualification:** stress repeated device suspend/resume, Wi-Fi and USB detach/reconnect, storage integrity, timing and battery drain. Keep failed/deeper states disabled. Only then consider CPU deep idle and additional clock/domain savings.

These are proposed acceptance gates, not tests executed in this research pass. Neither the recovered sources nor the public examples establish sub-second resume or a week of GameShell sleep. Those remain measurable targets. The useful outcome is a bounded patch plan with existing source for the monitor path and clearly separated work for DRAM, clocks, PMIC state and device resume.

## Source availability and attribution

The recovered U-Boot monitor and remoteproc files carry GPL-2.0 SPDX notices. Crust firmware is dual-licensed BSD-3-Clause or GPL-2.0-only, with separately identified third-party/build-tool licenses. Preserve attribution and track which references inform each new implementation. In particular, adapting GPL-licensed vendor implementation does not automatically make the result available under Crust's BSD alternative: record the applicable provenance and licensing before upstream submission. The source and binary provenance questions surrounding historical ARISC material are covered in report 17; availability of a vendor blob is not equivalent to a maintainable open-source replacement. [Monitor][monitor], [remoteproc][remoteproc], [Crust licensing][crust-license]

[monitor]: https://github.com/smaeul/u-boot/blob/9d8202dd5cab57fa56880179b4e53c79f9ef24a3/arch/arm/cpu/armv7/sunxi/psci-scpi.c
[a33-patch]: https://github.com/openwrt/openwrt/blob/44b73b738d18e424d86a34be3fb1d93cf3d718d6/package/boot/uboot-d1/patches/0044-sunxi-Enable-SCP-SCPI-on-A33-as-well.patch
[ow-package]: https://github.com/openwrt/openwrt/blob/44b73b738d18e424d86a34be3fb1d93cf3d718d6/package/boot/uboot-d1/Makefile
[ow-patches]: https://github.com/openwrt/openwrt/tree/44b73b738d18e424d86a34be3fb1d93cf3d718d6/package/boot/uboot-d1/patches
[h3-shim]: https://github.com/openwrt/openwrt/blob/44b73b738d18e424d86a34be3fb1d93cf3d718d6/package/boot/uboot-d1/patches/0037-sunxi-psci-Add-support-for-H3-CPU-0-hotplug.patch
[remoteproc]: https://github.com/smaeul/u-boot/blob/9d8202dd5cab57fa56880179b4e53c79f9ef24a3/drivers/remoteproc/sun6i_ar100_rproc.c
[sun8i-layout]: https://github.com/smaeul/u-boot/blob/9d8202dd5cab57fa56880179b4e53c79f9ef24a3/include/configs/sun8i.h
[upstream-psci]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/cpu/armv7/sunxi/psci.c
[upstream-psci-asm]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/cpu/armv7/psci.S
[monitor-config]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/cpu/armv7/Kconfig
[psci-dt]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/lib/psci-dt.c
[uboot-fit]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/dts/sunxi-u-boot.dtsi
[uboot-config]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/mach-sunxi/Kconfig
[uboot-dram]: https://github.com/u-boot/u-boot/blob/v2026.07/arch/arm/mach-sunxi/dram_sun8i_a33.c
[linux-psci]: https://github.com/torvalds/linux/blob/v6.18/drivers/firmware/psci/psci.c
[linux-dtsi]: https://github.com/torvalds/linux/blob/v6.18/arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi
[linux-rsb]: https://github.com/torvalds/linux/blob/v6.18/drivers/bus/sunxi-rsb.c
[linux-irq]: https://github.com/torvalds/linux/blob/v6.18/drivers/irqchip/irq-sun6i-r.c
[linux-pek]: https://github.com/torvalds/linux/blob/v6.18/drivers/input/misc/axp20x-pek.c
[crust-memory]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/platform/a23/include/platform/memory.h
[crust-linker]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/arch/or1k/scp.ld.S
[crust-abi]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/docs/abi.md
[crust-loader]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/tools/load.c
[crust-platform]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/platform/Kconfig
[crust-dram-make]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/dram/Makefile
[crust-system]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/common/system.c
[crust-css]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/css/css.c
[crust-cpu]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/css/sun6i-a31-css.c
[crust-css-default]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/css/css_default.c
[crust-reg-config]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/regulator/Kconfig
[crust-supplies]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/common/regulator_list.c
[crust-regulator]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/regulator/axp221.c
[crust-pmic]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/pmic/axp223.c
[crust-pmic-common]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/pmic/axp20x.c
[crust-clock]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/clock/sun8i-a23-ccu.c
[crust-r-clock]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/clock/sun8i-r-ccu.c
[crust-irq]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/irq/sun6i-a31-r-intc.c
[crust-license]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/LICENSE.md
[tfa-design]: https://github.com/ARM-software/arm-trusted-firmware/blob/da738d5eae93af342fdc4995dd3c05acb4c9d757/docs/design/firmware-design.rst
[tfa-platform]: https://github.com/ARM-software/arm-trusted-firmware/blob/da738d5eae93af342fdc4995dd3c05acb4c9d757/docs/plat/allwinner.rst
[tfa-scpi]: https://github.com/ARM-software/arm-trusted-firmware/blob/da738d5eae93af342fdc4995dd3c05acb4c9d757/plat/allwinner/common/sunxi_scpi_pm.c
