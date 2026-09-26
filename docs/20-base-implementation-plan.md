# From research to a maintainable GameShellNeo base

Research date: 2026-09-27. Status: proposed implementation plan, following the owner's authorization for the focused firmware and PMIC investigation. No image has been built, no firmware has been run, and no device or network setting has been changed. [The agreed requirements](06-base-requirements.md) remain authoritative.

Subsequent progress: [report 21](21-installed-hardware-baseline.md) records the authorized read-only inspection of the existing installation and preserved boot references. Remote software collection and an authenticated Intel → Mac → USB SSH connection are complete. The owner has confirmed **CPI v3.1** printed on the mainboard. Memory/keypad/battery identification, full backup/recovery and repeated USB reconnection tests remain open. Serial-console setup is deferred and does not block the first-build specification or initial base work. This does not mark checkpoint 0 fully complete.

## Recommendation

**Proceed toward a diagnosable modern Linux base, with deep suspend developed as a separate, staged firmware feature.** Keep the proposed minimal Armbian/Debian userspace and maintained 6.18.y kernel as the starting point. Use ordinary upstream Linux interfaces, assess existing ARMv7 U-Boot/SCPI integration, and develop the missing A33 DRAM support in Crust if the hardware baseline confirms the assumptions. Do not make a proprietary vendor ARISC image the production dependency by default.

The new research materially narrows the problem. We have found relevant vendor DRAM operations and existing monitor integration, so this is no longer an investigation starting only from incomplete manuals. We have **not** found a complete, qualified modern GameShell deep-sleep implementation. The appropriate next step is a bounded engineering experiment with explicit checkpoints, supported by the board's actual configuration. [Vendor source trace](17-vendor-firmware-and-dram-trace.md); [modern integration assessment](19-modern-suspend-integration.md).

There is also a concrete Linux USB current-limit setter defect to address before relying on current-limit writes. It is separate from the English/Chinese AXP223 datasheet disagreement. The driver deliberately supports a 100 mA entry; changing the device's compatible string or table on the strength of the Chinese document would be premature. [PMIC history and contract](18-pmic-history-and-suspend-contract.md).

## What the focused investigation resolved

| Question | Evidence now available | Remaining work |
| --- | --- | --- |
| Is there relevant A33 DRAM sequence source? | The explicit `CONFIG_ARCH_SUN8IW5P1` path in Allwinner's DRAM frequency-change code contains self-refresh, clock/PHY and restoration operations. | Derive a suspend-specific implementation with verified ordering, retained state and bounded failure handling; frequency switching is not whole-system suspend. |
| Can we recover the historical suspend interface? | Vendor and author-maintained trees expose host-side ARISC loading, message/parameter interfaces and historical ARM suspend/resume work. | Separate board assumptions and binary behavior from reusable source; the historical interface is not Crust SCPI. |
| Is a monitor-to-Crust bridge wholly new work? | Public OpenWrt-carried patches implement ARMv7 PSCI delegation to SCPI and explicitly enable A33. | Audit/rebase dependencies against the selected U-Boot, resolve SRAM/load layout and verify the complete resume contract. Presence in a patch stack is not GameShell validation. |
| Do the manuals establish a wrong AXP223 current table? | Linux's AXP223-specific 100 mA support was deliberate, and an English vendor datasheet supports it. The same-revision Chinese table conflicts. | Preserve the existing variant identity. Physical current accuracy remains unverified with the owner's equipment. |
| Is there nevertheless a current-limit software bug? | The inspected setter searches a table ending in `-1`; a positive request can select that unlimited-current code immediately. | Correct selection semantics and test representative tables, bounds and the device-tree clamp before relying on writes. |
| Does PMIC wake have a defined ownership boundary? | Existing Crust AXP223 code uses PMIC output-state capture and software-triggered restoration. Rearming belongs to the implementation that uses this facility. | Coordinate Linux wake masks, firmware RSB ownership, rail restoration and pending IRQ delivery on the actual board. |

Sources and exact revisions are recorded in [17](17-vendor-firmware-and-dram-trace.md), [18](18-pmic-history-and-suspend-contract.md) and [19](19-modern-suspend-integration.md). These findings replace broad source-location questions with implementation and validation tasks.

One source trap matters: a mirrored R16 U-Boot tree contains attractively named standby/DRAM files, but the caller is disabled and register definitions differ from the explicit A33 implementation. It is not a validated retention recipe. File names, adjacent chip support and reference-tablet configuration remain insufficient evidence for GameShell register writes. [Detailed comparison](17-vendor-firmware-and-dram-trace.md).

## Component boundaries

The proposed division keeps product policy out of firmware and keeps board wiring out of generic drivers.

| Component | Owns | Concrete deliverable |
| --- | --- | --- |
| Board description and build configuration | Actual supplies, pins, interrupts, clocks, memory configuration, enabled devices and kernel selection | One board target, a pinned source/configuration manifest, and a documented patch ledger |
| Linux device drivers | Normal peripheral operation, device suspend/resume, wake configuration, battery telemetry and alarm delivery | Focused display/backlight integration, current-limit fix, battery IRQ/wake extension, verified CPU/regulator and radio lifecycle |
| ARM secure monitor in U-Boot | PSCI entry, CPU context/power coordination, SCPI handoff and return to Linux's resume address | Reviewed ARMv7 integration with explicit feature discovery, SRAM placement and failure behavior |
| Crust on AR100 | Always-on coordination, A33 DRAM retention, clock transitions, PMIC access while Linux is suspended and ordered restoration | A33 DRAM backend, GameShell configuration and a documented PMIC/clock contract |
| Userspace power policy | Two-minute default, user configuration, SSH/USB automatic-sleep exemptions, explicit button sleep and critical-battery shutdown policy | A small launcher-independent service using standard system interfaces |
| Test/recovery support | Reproducibility, logs, known-good boot, memory checks and observed timing/endurance | Spare-card recovery procedure and versioned result bundles |

The monitor and Crust must agree on protocol, memory ownership and power-state meanings; the historical Allwinner mailbox structures cannot simply be substituted for SCPI. Likewise, Linux and firmware must never access the PMIC bus concurrently during ownership transfer. [Firmware/interface trace](17-vendor-firmware-and-dram-trace.md); [integration design](19-modern-suspend-integration.md); [PMIC contract](18-pmic-history-and-suspend-contract.md).

## Proposed change sets

Keep these independently reviewable. An entry here describes future work, not an existing patch or a promise that it will be small.

| ID | Change set | Approach and acceptance boundary |
| --- | --- | --- |
| B1 | Reproducible board baseline | Pin Armbian inputs, Linux, U-Boot, toolchains and firmware assets; inspect inherited family patches, overlays and frequency defaults. Retain normal console/recovery facilities. |
| L1 | Required board and device integration | Derive a fresh board description from schematic/source evidence. Adapt standard panel/backlight interfaces and assess the OCP8178 submission. Qualify keypad, Wi-Fi, USB gadget and battery reporting. |
| L2 | AXP USB current-limit selection | Fix the demonstrated setter behavior without reclassifying AXP223 as AXP221. Test finite entries, table ordering, sentinels, too-small requests and board maximums. Treat requested, encoded and physically measured current as separate quantities. |
| L3 | Awake efficiency | Restore appropriate CPU idle/DVFS support and correct regulator linkage; verify unused hardware states. Investigate USB polling only after preserving its input-detection timing requirements. Measure each change. |
| P1 | Power policy and ordinary suspend | Implement the agreed policy separately from a launcher. Prove peripheral recovery using the available shallow state before relying on firmware-controlled DRAM retention. |
| F1 | ARMv7 monitor and SCP loading | Assess/rebase the existing PSCI/SCPI work and its loader/FIT prerequisites; document reserved SRAM, firmware discovery and runtime feature advertisement. |
| F2 | A33 Crust retention | Implement a deliberately scoped DRAM backend from corroborated A33 behavior, reconcile clock/RSB restoration and bind the actual board supplies. Existing AXP223 regulator support does not populate the generic supply handles. This is the largest unproven engineering item. |
| L4/F3 | Critical-battery wake and PMIC handoff | Route battery alarm resources through the MFD/driver and establish wake delivery, retained reason and restoration ordering. Coordinate both sides of the firmware boundary. |

Every patch should state its source evidence, affected versions, rationale, functional test, known limitations and removal/upstreaming condition. Preserve applicable license notices and attribution for any adapted code. Availability in a public repository does not establish unrestricted redistribution of a firmware blob. [Source/license boundaries](17-vendor-firmware-and-dram-trace.md).

A new whole driver is justified only where the existing model cannot express the required behavior or testing reveals a broader structural fault. The evidence presently favors targeted extensions for power supply, panel/backlight and firmware support. There is no evidence that replacing all AXP or wireless support would be necessary or more efficient. [Driver audit](08-driver-and-board-support.md); [battery assessment](09-battery-and-power-policy.md).

## Execution order and checkpoints

### 0. Establish a recovery and evidence baseline

Preserve the working card and collect read-only information from the original installation. Record the board/keypad markings, battery, fitted memory and known-good bootloader settings, radio firmware/NVRAM names and hashes, battery telemetry, available sleep states and boot logs. Verify the Intel → Mac → USB Ethernet → GameShell management path separately from Internet sharing. Serial-adapter and harness qualification can resume later; verify UART compatibility and connector orientation before wiring.

**Checkpoint for initial image testing:** the actual board is identified, the original installation is preserved, existing network access is verified, and the spare card has a repeatable recovery procedure. Serial capture is not required for this checkpoint. Host-side source and patch preparation need not wait for the remaining physical checks. [Baseline checklist](11-feasibility-summary-and-validation-plan.md); [deferred activities](../FOLLOW-UP.md).

**Working without serial:** use USB or Wi-Fi SSH for logs and tests once the new kernel and userspace start. Keep UART console support configured for future use, but do not require an attached cable. If neither network path starts, available display output or logs saved to the development card may help; neither guarantees evidence from an early crash. Recover with the original card or reflash the spare, and revisit serial access when missing diagnostics prevent progress. USB and Wi-Fi both depend on functioning Linux drivers and cannot replace an early-boot console.

### 1. Freeze and prepare the minimal bootable base

Prepare the board target and patch ledger, pin exact versions, address the current-limit setter, and build the in-scope hardware support. Include diagnostic tools and a simple local readiness marker; no launcher is needed. Record USB power declarations and charging behavior rather than assuming the Mac permits the largest PMIC limit.

**Checkpoint:** repeated cold boot, logs accessible over SSH, display/backlight, keypad, battery reporting, orderly shutdown, Wi-Fi SSH and USB SSH work on the spare card. The proposed initial boot gate is ten consecutive successful starts. Serial capture remains a deferred diagnostic capability. Charge configuration and current-limit readback are documented; readback alone does not prove electrical current accuracy. Do not include speculative undervolting, overclocking or DRAM frequency tuning in this baseline.

### 2. Qualify ordinary power management

Measure awake idle; correct CPU power-management configuration and peripheral lifecycle. Implement and exercise configurable inactivity sleep, SSH and USB exemptions, and deliberate button sleep. Start with the available shallow suspend state and record exactly which state was entered. Restore Wi-Fi only if it was enabled before sleep; count local interaction recovery separately from network reconnection.

**Checkpoint:** twenty consecutive short cycles preserve application state and recover the in-scope peripherals, including USB and radio transitions. Qualify the wake-button event so it does not immediately request another sleep. These tests establish device/policy behavior; they do not satisfy the final standby requirement.

### 3. Bring up the firmware interface incrementally

Reassess diagnostics and recovery before firmware-controlled power transitions. Serial is the preferred way to observe progress when Linux networking is unavailable; any alternative must demonstrate useful failure evidence rather than merely assume logs survive. Deferring the cable now does not establish that deep-sleep failures will be diagnosable without it.

Integrate reviewed monitor/SCP loading and verify firmware identity, memory reservations and SCPI communication before permitting a destructive power transition. Establish one clock/RSB contract that both Linux and Crust implement. Keep public deep-suspend claims and defaults disabled until their implementation is complete; successful mailbox communication alone is insufficient.

The old monitor patch advertises suspend operations and waits indefinitely for SCP responses, so validation, bounded waits and correct feature discovery need explicit attention. Crust's A33 core-off CPU-idle interrupt handling also needs separate work: retain ordinary WFI initially and do not introduce unqualified deep CPU-idle states just because system-suspend integration is being added. Reconcile Crust's fixed resume divider values with Linux's clock state rather than assuming clocks were restored unchanged. [Source-level gaps](19-modern-suspend-integration.md).

**Checkpoint:** ordinary boot and SMP operation remain reliable, firmware memory regions do not overlap live data, protocol behavior is known, and the selected monitor exposes only operations supported by the selected firmware. Define how a failed request returns before commitment, and how diagnostics/recovery work after a failure beyond the reversible point. Do not assume an arbitrary DRAM-off failure can return safely to Linux. [Detailed staged integration](19-modern-suspend-integration.md).

### 4. Prove retained memory before reducing more power

Implement the A33 DRAM operations using the explicit A33 source path and modern register definitions as references. Establish where every instruction, stack, saved value and mailbox lives while DRAM is unavailable. Quiesce other CPUs and DMA clients; verify controller entry/exit conditions and ordering. Begin with the least aggressive supported transition; add clock and rail reductions only after memory preservation is repeatable.

**Checkpoint:** a process with a known memory pattern survives repeated entry/resume, with no checksum mismatch, unexplained reset or storage error. Record firmware progress markers and wake reasons. Test peripheral recovery again after each additional power reduction. A single successful wake is evidence for the next experiment, not proof of reliability or an endurance result.

### 5. Complete battery protection and qualify useful deep sleep

Implement the battery alarm/wake path and qualify it through the selected sleep state. Confirm PMIC state capture/rearming, software restoration where used, voltage/clock order, pending-event handling and Linux driver state. Test a pending event at entry, an alarm during sleep, power-key wake and power-source changes. Validate policy logic with controlled inputs before supervised battery discharge tests.

**Checkpoint:** reliable wake-to-orderly-shutdown occurs with sufficient reserve, and repeated suspend cycles restore operation across the agreed conditions. Only then extend unplugged sleep intervals toward the week-long target. Twenty short cycles can progress to a proposed 100-cycle soak; neither establishes week-long endurance. [PMIC ownership/test contract](18-pmic-history-and-suspend-contract.md); [battery measurement limits](09-battery-and-power-policy.md).

### 6. Optimize startup and design production updates

Once the base is stable, measure cold boot and local resume with explicit start/ready endpoints. Separate first output, usable local interaction and network availability. Retain the under-five-second cold-boot and under-one-second local-resume aspirations without assigning unmeasured stage budgets.

Design the production card map and signed update/rollback path before committing to production storage. The existing 8 KiB SPL placement needs explicit treatment before adopting GPT or A/B layouts. Early experiments can continue to use the spare-card reflash procedure; OTA does not need to block driver/firmware qualification. [Boot and update design](10-boot-and-update-architecture.md).

## How to judge progress and when to change direction

- **Driver/policy success, high standby drain:** preserve the useful modern base, then attribute the remaining consumption to the actual sleep state and powered hardware. Changing distributions alone does not supply missing DRAM retention.
- **SCPI works, DRAM retention fails:** focus on register sequencing, retained execution state, memory configuration and clocks. Do not compensate with copied tablet FEX values or globally disabling normal clock management.
- **Memory survives, peripherals fail:** isolate the specific driver's suspend/resume contract. Memory success does not justify accepting a blind LCD, broken storage or missing wake input.
- **Short sleep works, battery protection does not:** retain short supervised testing; the week-long unattended-use requirement is still incomplete.
- **Public-source route proves infeasible on this board:** document the specific technical blocker before reconsidering a vendor binary experiment. Any such experiment needs a known compatible ABI, board assumptions and a redistribution assessment; it must not silently become the production architecture.

Relative uncertainty is now clearer: the current-limit correction is a narrow software task; board/display/power-policy integration is ordinary driver and system work with hardware testing; A33 retention and its secure-monitor/clock/PMIC integration remain substantial firmware work. A calendar estimate would be premature before the first hardware baseline and retained-memory experiment.

## Immediate next step

The focused research is complete. The next useful activity is **hardware-baseline preparation and a pinned first-build specification**, followed by the minimal diagnostic image when implementation begins. In parallel, the demonstrated current-limit bug can be turned into a focused patch with meaningful regression coverage. Another broad distribution or SDK survey is unlikely to remove the remaining uncertainty as effectively as these steps.

All device-dependent checks, source tasks and implementation checkpoints are recorded in [FOLLOW-UP.md](../FOLLOW-UP.md). The new source trace, modern integration assessment and PMIC contract make those tasks concrete without claiming that deep sleep, battery endurance or startup targets have already been achieved.
