# Vendor firmware and A33/R16 DRAM implementation trace

Research date: 27 September 2026. Scope: recover the implementation behind the historical A33 suspend work, identify the firmware boundary, and find usable register-level references for GameShellNeo's retained-memory sleep. This follows [the supplied-manual investigation](14-vendor-suspend-and-memory-evidence.md) and complements [the modern firmware investigation](19-modern-suspend-integration.md). All inspection was read-only, using temporary source checkouts. No kernel, firmware or image was built; no downloaded executable or firmware was run.

**There is a credible source-based route to an A33 DRAM suspend implementation, but the historical full super-standby algorithm is not available as plaintext source in the inspected packages.** The most useful readable reference is Allwinner's explicitly selected `CONFIG_ARCH_SUN8IW5P1` memory-frequency transition routine. It contains the self-refresh, pad-hold, DDR-clock and PHY restart sequence missing from the manuals. The historical Linux port establishes the ARM/ARISC handoff and reset-resume contract; its actual DRAM and power sequencing remains inside an ARISC image. These are complementary references, not a complete modern implementation. [A33 MDFS routine][mdfs]; [historical ARM suspend][micile-pm]; [firmware loader][vendor-loader].

## 1. Recovered sources and provenance

| Source inspected | Pinned revision | What it actually provides |
| --- | --- | --- |
| Allwinner's `allwinner-zh/linux-3.4-sunxi` | `6964d467510849e3e262518cb87bff7ef92e01f5` | A33 DRAM frequency-transition C source, ARISC loader/host interfaces, `aw_pm.h`, and firmware encoded as a C byte array. This checkout does not contain the ARM `mach-sunxi/pm` tree. |
| Lawrence Yu's `micile/linux-sunxi`, `arisc_standby_cleanup` | `2f961cb880c19ac9a9a1c39fe24913f308205426` | Author-maintained ARM suspend/resume port and ARISC package. Its Makefile identifies **Linux 4.8-rc5**, and the commit is dated 26 March 2017. |
| Lawrence Yu's `micile/u-boot`, `MICILE_A33` | `b1763ec905e5ec3e0f66e6f07da24ba85dfb79bc` | Private secure-register SMC interface needed by that ARM resume implementation. |
| Samuel Holland's `smaeul/sunxi-blobs` | `7cda4903df7b46eba9514094904e57cbe0272520` | Firmware bytes, provenance, analysis annotations and largely unnamed function boundaries for several A33 ARISC versions. It is an analysis collection, not ARISC source code. |
| Upstream U-Boot | `v2026.07`, commit `ece349ade2973e220f524ce59e59711cc919263f` | Independent current A33 controller register layout to cross-check the legacy sequence. |
| `mistydemeo/super_nes_classic_edition_oss` mirror | `730dff9833a887ed43787f1c1b1cbbecb4c6e3e3` | Additional R16-labelled vendor files, including an **inactive and register-incompatible** standby implementation. This mirror was not independently matched against Nintendo's original downloadable archive during this research. |

Sources: [Allwinner tree][vendor-tree], [author's Linux revision][micile-revision], [author's kernel version][micile-version], [author's U-Boot revision][micile-uboot], [firmware analysis collection][blobs], [current A33 header][modern-header], [Nintendo mirror][nintendo-tree].

The [2017 announcement][announcement] and [versioned A33 suspend instructions][wiki] describe a later 4.11/4.12 port relying on vendor AR100 firmware. Their original `micile.com/patches` download URLs failed in this audit: HTTP returned 404 and HTTPS failed TLS negotiation. The recovered March branch belongs to the author and contains the relevant mechanism, but **has not been established as byte-for-byte equivalent to those later patches**. The author's August `MICILE_MAINLINE` head, `6f7dafde1b1e695c65ba4c36de187fd397364d6c`, lacks this PM tree, so selecting the newest branch name would miss the implementation. [Historical instructions][wiki]; [March source][micile-revision]; [August source][micile-later].

## 2. Where the historical suspend operation really happens

The recovered code has three distinct components:

```text
Linux ARM suspend code
  saves application/secure context and prepares resume metadata
    -> ARISC mailbox: super-standby request
    -> ARM leaves cache coherency and executes WFI

ARISC firmware image
  owns the unexposed DRAM/power transition and wake processing
    -> restores enough hardware for ARM reset-resume

ARM SRAM resume trampoline
  rebuilds secure/nonsecure execution context
    -> returns to saved Linux continuation
    -> Linux notifies ARISC that CPUX is ready
```

The middle stage is an implementation boundary, not a claim to have recovered its instruction-by-instruction behavior. The following source trace establishes why it is required. [ARM PM implementation][micile-pm]; [ARISC standby interface][micile-standby]; [ARM trampoline][resume-asm].

1. **Select the vendor operation.** `aw_pm_valid()` interprets `standby` and `mem` through `standby_mode`; for `SUN8IW5P1`, a selected normal standby is then changed to super standby. Consequently, the historical command's name cannot identify the modern Linux sleep depth. `aw_pm_enter()` calls `aw_super_standby()`. [Selection and entry][micile-pm].
2. **Save ARM and device context.** `aw_super_standby()` records its continuation and runtime registers. `aw_early_suspend()` saves clocks, GPIO, timers, SRAM-controller and display-related state, and both normal and secure MMU state. It places the parameter block in reserved DRAM and flushes it before handing off. The secure MMU registers and monitor-vector address come from `psci_ops.get_mmu_sec_reg()`. [Context preparation][micile-pm].
3. **Pass a real resume contract.** `super_standby_para_info` carries the wake-event mask, physical source/length of `resume1`, SRAM entry address, timeout, wake GPIO bitmaps and optional extended-standby structure. `pm_config.h` selects A33 and `ENTER_SUPER_STANDBY`, with the ARM resume entry at physical address zero. This is not merely a request to gate the CPU clock. [Parameters][aw-pm]; [configuration][micile-config]; [handoff][micile-pm].
4. **Send the request and stop the ARM CPU.** `arisc_standby_super()` creates an asynchronous `ARISC_SSTANDBY_ENTER_REQ` or `ARISC_ESSTANDBY_ENTER_REQ`. The caller then enters `aw_suspend_cpu_die()`: disable data cache, clean/invalidate cache, clear exclusives, leave SMP coherency, execute barriers and `WFI`. There is no A33 DRAM self-refresh routine called from this ARM super-standby path. [Request implementation][micile-standby]; [CPU stop][micile-pm].
5. **Resume requires usable DRAM before the Linux continuation.** `resume1.S` starts with MMU/cache disabled, sets a SRAM stack, installs a temporary monitor vector and enters a secure monitor handler. That handler reads the saved parameter block from DRAM, restores normal then secure MMU state, restores the original monitor vector and returns to nonsecure execution. The remaining trampoline restores clocks and jumps to the saved Linux continuation. Therefore DRAM restoration is a prerequisite of this trampoline, not something the trampoline itself supplies. [Assembly][resume-asm]; [resume C][resume-c].
6. **Complete the two-processor handshake.** Linux restores its saved state, then `arisc_cpux_ready_notify()` resumes mailbox/spinlock handling, sends `ARISC_SSTANDBY_RESTORE_NOTIFY`, and retrieves the wake-event bitmap and optional DRAM-CRC result. [ARM return path][micile-pm]; [restore notification][micile-standby].

The paired U-Boot modification exposes selected secure CP15 registers through a private `ARM_PSCI_FN_GET_MMU_SEC_REG` call. It is not an implementation of standardized `SYSTEM_SUSPEND`. Reusing this architecture would couple the Linux port to a private secure-monitor ABI. The modern PSCI/SCPI bridge examined separately is the more appropriate direction for GameShellNeo. [Private function ID][micile-psci-header]; [register accessor][micile-psci]; [modern investigation](19-modern-suspend-integration.md).

The recovered port also retains debug-register writes, tablet-specific R_UART pin setup and comments indicating that a `printk` changes whether it hangs. Its standby Makefile contains specialized compiler flags and an external checksum executable. These are explicit reasons to extract requirements and ordering from the code rather than treat the branch as a maintainable patch set. [Resume setup][resume-c]; [PM implementation][micile-pm]; [standby build description][micile-makefile].

## 3. ARISC firmware, configuration and mailbox boundary

The official vendor loader chooses `arisc_bsp_sun8iw5p1_table.c` for A33. This file is a **104,908-byte machine-code/data image expressed as C hexadecimal bytes**, not readable firmware implementation. For this platform `sunxi_arisc_probe()` copies the first `0x13000` bytes into SRAM A2, sets up parameters and shared messages, releases ARISC reset, waits for startup, then sends DVFS, PMIC, DRAM and standby-power configuration. The nonsecure path directly writes SRAM and reset registers; a separate secure path delegates loading through a firmware operation. [Build selection][arisc-makefile]; [image][arisc-image]; [loader][vendor-loader].

The interface is sufficiently visible to document:

| Item | Observed host-side contract |
| --- | --- |
| Shared message | 64-byte structure: state/attributes/type/result, host bookkeeping fields, and eleven 32-bit parameter words. |
| Mailbox payload | A mapped address of that shared message; synchronous and asynchronous queues are distinct. Allocation and shared-state handling also involve hardware spinlocks. |
| A33 shared pool | SRAM offsets `0x13000`–`0x14000`; these are the vendor layout, **not** the modern Crust SCPI buffers. |
| Super-standby command | `0x10`; extended super standby `0x16`; CPUX-restored notification `0x11`. |
| DRAM configuration | `ARISC_SET_DRAM_PARAS`, command `0x63`; the host sends the 24-word DRAM parameter structure one indexed word at a time. |
| Wake configuration | `aw_pm.h` defines low battery, power-key edges/short/long events, charger, alarm and GPIO bits. Presence in this ABI does not establish working modern wake delivery. |

Sources: [message format and IDs][messages], [queue/address handling][msgbox], [message allocation][message-manager], [SRAM/queue configuration][arisc-config], [DRAM parameter transfer][dram-config], [wake definitions][aw-pm].

This resolves part of the manuals' `aw_pm.h` reference: the source describes the A33 PMIC output-state bitmap and the fields used for expected power state and consumption threshold. The parser copies `s_powchk_used`, `s_power_reg` and `s_system_power` into the firmware request. It does **not** resolve the manuals' contradictory enable-bit descriptions through executable host logic: the enable word is forwarded rather than interpreted here. The firmware remains the authority for that behavior. [Structure][aw-pm]; [parser][standby-interface]; [manual discrepancy](14-vendor-suspend-and-memory-evidence.md).

Two distinctions prevent overclaiming firmware availability:

- The recovered author's `arisc_sun8iw5p1.code` is a bzip2-compressed tar package. Inspection of its members found a 104,824-byte `.bin` and a 603,395-byte `.tar.bz2.aes` member. The Makefile extracts the binary and preserves the encrypted member; no plaintext ARISC implementation was recovered. The binary SHA-256 is `bfc444345121a2225aaafa295cf91394e3b7bbd4978733c2b27349f3e26136af`. [Package][micile-package]; [extraction recipe][micile-binary-makefile].
- The official C-array bytes hash to `bd7bba19cfc99aec764af421679e098f91fbc06771ec32d7a6833a68bcf73ed8`. Read-only decoding confirmed that these exactly match `sunxi-blobs/sun8iw5p1/arisc_v0.1.33/blob.hex`. Thus they are a useful pinned analysis target, but **a different image from the author's recovered package**. The collection records multiple A33 firmware versions; interchangeability with the same host ABI, PMIC and board parameters is unproven. [Vendor image][arisc-image]; [matching bytes and provenance][blob133]; [analysis collection][blobs].

The `sunxi-blobs` A33 annotations identify a DRAM-standby version string and many function boundaries, but the inspected symbol files largely retain anonymous `func_...` names. They do not provide an already explained complete DRAM suspend algorithm. No blob disassembly was generated in this task. [Annotations][blob-comments]; [symbols][blob-symbols].

## 4. Exact readable A33 self-refresh and restart sequence

The strongest implementation reference is `drivers/devfreq/dramfreq/sunxi-mdfs.c`, specifically the `CONFIG_ARCH_SUN8IW5P1` `mdfs_start()` at lines 850–1080. It carries an explicit GPL-2.0-or-later header. This is a **memory frequency transition**, including entry and exit from self-refresh; it is not the hidden ARISC super-standby routine. Its caller selects different MDFS paths according to configuration and operating mode, so finding the function does not establish that every vendor image runs it. [A33 function][mdfs]; [driver path selection][ddrfreq].

The register header uses kernel virtual addresses. The physical offsets below correspond to its A33 bases and agree with the current U-Boot A33 controller structure; they are evidence for a future implementation, not commands to issue from Linux userspace. [Vendor A33 header][mdfs-header]; [upstream A33 header][modern-header].

| Step | Actual A33 function behavior |
| --- | --- |
| Prepare timing | Read the selected DDR PLL. Choose refresh timing from `dram_tpr2`, with a separate low-frequency case. |
| Stop memory masters | Write zero to `MC_MAER`, common block `0x01c62000 + 0x94`. |
| Request self-refresh | Set bits 0 and 8 in `PWRCTL`, controller `0x01c63000 + 0x04`; delay 100 µs, write refresh timing, then wait for `STATR[2:0] == 3` at controller `+0x18`. |
| Hold pads | Set bits 0–1 in PRCM `+0x110`; delay 10 µs. |
| Stop DDR clocks | Clear `MC_CLKEN` at controller `+0x0c`, then disable both DDR PLLs' enable/modulation bits; delay 100 µs. |
| Re-establish clocking | Program the selected DDR PLL and update the DRAM divider. The normal and ≤192 MHz branches use different divider, controller-clock and PHY-PLL handling. The normal branch restores supplied PLL parameters; the low-frequency branch uses dedicated constants. |
| Restart PHY | Write `PIR = 0x40000071` in the normal branch or `0x40020061` in the low-frequency branch. Wait for `PGSR0` bit 0 at controller `+0x10`. |
| Release pads | Clear PRCM `+0x110` bits 0–1; delay 10 µs. |
| Exit self-refresh | Write zero to `PWRCTL`; wait for `STATR[2:0] == 1`. The nearby comment incorrectly repeats “enter”; the tested value and following operations establish the exit step. |
| Restore access policy | Adjust controller/DRAM ODT by frequency/rank, optionally enable automatic self-refresh in the low-frequency case, then write `0xffff` to `MC_MAER`. |

All operations in this table come from the [A33-specific function][mdfs], with addresses from its [associated header][mdfs-header]. They describe the audited code's behavior; undocumented bit meanings and constants still need an implementation review.

The surrounding code matters. `mdfs_main()` uses SRAM code/data, changes the stack, preloads relevant translations and copies parameters into SRAM before issuing barriers and entering `mdfs_start()`. The driver copies SRAM text, pauses other CPUs and disables local interrupts around the selected transition. Executing this sequence while ordinary CPU/DMA users can still access DRAM would violate those original preconditions. [SRAM wrapper][mdfs]; [quiescing caller][ddrfreq].

The useful new conclusion is narrow but substantial: **readable vendor code exists for an A33 self-refresh cycle intended to stop and restart DDR clocks and PHY operation while preserving memory.** It supplies concrete registers, ordering, status tests and branch conditions. What it does not supply is a full context-loss restore after arbitrary system/controller power removal, an ARISC wake-state machine, or proof of long-duration retention on GameShell. It also uses unbounded polling and largely fixed writes rather than robust timeout/error recovery and restoration of every prior setting. Those limitations must inform a new implementation. [A33 function and caller][mdfs]; [historical firmware boundary][micile-pm].

A first GameShell-specific implementation should therefore use the known-good DDR operating point, retain the DRAM rail and controller/system power, explicitly save settings that the reference overwrites, and validate a complete entry/exit pair before adding further clock or rail reductions. The ≤192 MHz branch is evidence to investigate later, not a recommended GameShell operating point. This is a proposed staging strategy derived from the source's prerequisites and gaps; it is not a measured configuration.

## 5. A source-provenance trap: the R16/Nintendo standby directory

The Nintendo mirror contains `board/sunxi/sun8iw5/standby/dram/mctl_sys.c` with functions named `mctl_self_refresh_entry()` and `mctl_self_refresh_exit()`. Its path looks promising, but it should **not** be used as the A33 implementation basis:

- `standby.c` places its real `boot_early_standby_mode()` body and the call sites inside `#if 0`; the active early-standby path returns zero.
- Its DRAM header puts `PWRCTL` at controller `+0x30` and status at `+0x04`, with separate PHY registers. The explicit A33 MDFS branch and current A33 U-Boot header instead put these at `+0x04` and `+0x18`. This is a material register mismatch, not a naming difference.
- Clock/PLL power-down operations in `dram_power_save_process()` are commented out; a deeper sequence is separately disabled. Current numbers in comments lack a verified board/method and are not GameShell measurements.

These are observations from the [mirrored source][nintendo-mctl], [header][nintendo-regs], [inactive caller][nintendo-standby], and [current A33 definitions][modern-header]. They are consistent with inherited inactive code, but its original platform provenance was not established. The mirror's cold-boot DRAM Makefile also selects prebuilt `libdram-riot` or `libdram-pad`; presence of a public source bundle does not make every relevant firmware routine source-available. [DRAM library selection][nintendo-dram-makefile].

## 6. Reuse boundaries and the concrete implementation direction

| Material | Source/license evidence | Recommended role |
| --- | --- | --- |
| Vendor A33 MDFS C and current A33 U-Boot header | Explicit GPL-2.0-or-later notices | Primary register/order references; evaluate compatible reuse or write a documented implementation under an appropriate license. |
| ARISC host loader/mailbox/DRAM interfaces | Explicit GPL notices in inspected implementation files | Document old firmware behavior and its inputs; avoid importing the vendor host subsystem into modern Linux. |
| Historical ARM PM/resume tree | Mixed file-level notices, including “All Rights Reserved” headers within a GPL kernel tree | Study context and handoff requirements; do not assume every file has separately clarified provenance merely because the repository has `COPYING`. |
| ARISC images, C-array image and encrypted archive | Bytes available; no complete plaintext corresponding firmware source or separate redistribution grant established by this inspection | Analysis references. Do not describe them as open firmware or select them for redistributable images on this evidence alone. |
| `sunxi-blobs` tools and collection | Its license applies to files containing the stated copyright notice and expressly excludes other owners' files | Useful provenance/analysis tooling; its permissive license does not license Allwinner firmware. |

Sources: [MDFS header][mdfs], [modern header][modern-header], [host interface][messages], [historical PM header][micile-pm], [resume header][resume-asm], [image][arisc-image], [package][micile-package], [collection license][blob-license]. This table records observed notices and unresolved provenance; it is not a general legal determination.

Crust's existing DRAM files use `BSD-3-Clause OR GPL-2.0-only`; the vendor MDFS file grants GPL-2.0-or-later terms. Using legacy code as a guide does not automatically grant a BSD license to copied or translated code. A literal adaptation must retain appropriate attribution and have its licensing compatibility reviewed; a newly written implementation based on corroborated hardware behavior needs its own documented provenance. Do not apply Crust's dual-license header automatically to vendor-derived implementation. [Crust DRAM notice][crust-dram-license]; [vendor MDFS notice][mdfs].

The resulting direction is specific:

1. **Use the modern ARMv7 PSCI-to-SCPI bridge and an open ARISC firmware base**, as evaluated in report 19. The recovered private secure-register interface is historical evidence, not the preferred integration contract.
2. **Implement an A33-specific DRAM entry/exit pair**, guided by the explicit vendor MDFS branch and modern A33 register definitions. Keep the initial state conservative and make overwritten clock, refresh, ODT and access-mask settings explicit. Controller status, PHY completion, timeouts and failure checkpoints belong in the design before hardware execution.
3. **Keep the firmware wake/rail policy separate from that DRAM primitive.** Power-key/low-battery wake, RSB ownership, CPU power transitions and SRAM allocation must be reconciled with the modern code, not inferred from old mailbox command names. See [report 19](19-modern-suspend-integration.md).
4. **Require retained-data and reset-resume evidence before declaring deep sleep available.** The first future hardware milestones are a repeatable self-refresh round trip at the existing DDR settings, deterministic CPU-off wake to the intended resume entry, and repeated full Linux suspend/resume with memory checks and recorded wake causes. Longer battery tests follow those correctness checks; none of the recovered firmware versions or timing constants establishes week-long standby or subsecond user-visible resume.

The unresolved technical obstacle is now much better bounded: not “find any A33 sleep information,” but **translate and validate the known A33 retention sequence inside a modern firmware lifecycle, with a complete ARM resume contract and board-specific rail/wake ownership**. Full proprietary ARISC algorithm recovery is not a prerequisite for that staged approach. It would become relevant if the readable sequence and documented hardware fail to explain a required transition. No legacy blob, private SMC or inactive Nintendo routine is necessary to adopt merely because it was found.

[announcement]: https://groups.google.com/g/linux-sunxi/c/UP6M35hkGMU
[wiki]: https://linux-sunxi.org/index.php?title=A33_Suspend&oldid=19979
[vendor-tree]: https://github.com/allwinner-zh/linux-3.4-sunxi/tree/6964d467510849e3e262518cb87bff7ef92e01f5
[vendor-loader]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/arisc.c
[arisc-makefile]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/Makefile
[arisc-image]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/arisc_bsp_sun8iw5p1_table.c
[aw-pm]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/include/linux/power/aw_pm.h
[standby-interface]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/interfaces/arisc_standby.c
[messages]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/include/arisc_messages.h
[msgbox]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/hwmsgbox/hwmsgbox.c
[message-manager]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/message_manager/message_manager.c
[arisc-config]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/include/arisc_cfgs.h
[dram-config]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/arisc/arisc_dram.c
[mdfs]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/devfreq/dramfreq/sunxi-mdfs.c
[mdfs-header]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/devfreq/dramfreq/sunxi-mdfs.h
[ddrfreq]: https://github.com/allwinner-zh/linux-3.4-sunxi/blob/6964d467510849e3e262518cb87bff7ef92e01f5/drivers/devfreq/dramfreq/sunxi-ddrfreq.c
[modern-header]: https://github.com/u-boot/u-boot/blob/ece349ade2973e220f524ce59e59711cc919263f/arch/arm/include/asm/arch-sunxi/dram_sun8i_a33.h
[micile-revision]: https://github.com/micile/linux-sunxi/commit/2f961cb880c19ac9a9a1c39fe24913f308205426
[micile-version]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/Makefile
[micile-later]: https://github.com/micile/linux-sunxi/tree/6f7dafde1b1e695c65ba4c36de187fd397364d6c
[micile-pm]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/arch/arm/mach-sunxi/pm/pm.c
[micile-config]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/arch/arm/mach-sunxi/pm/pm_config.h
[micile-makefile]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/arch/arm/mach-sunxi/pm/standby/Makefile
[resume-asm]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/arch/arm/mach-sunxi/pm/standby/super/resume/resume1.S
[resume-c]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/arch/arm/mach-sunxi/pm/standby/super/resume/resume1_c_part.c
[micile-package]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/drivers/arisc/binary/arisc_sun8iw5p1.code
[micile-binary-makefile]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/drivers/arisc/binary/Makefile
[micile-uboot]: https://github.com/micile/u-boot/commit/b1763ec905e5ec3e0f66e6f07da24ba85dfb79bc
[micile-psci]: https://github.com/micile/u-boot/blob/b1763ec905e5ec3e0f66e6f07da24ba85dfb79bc/arch/arm/cpu/armv7/sunxi/psci.c
[micile-psci-header]: https://github.com/micile/u-boot/blob/b1763ec905e5ec3e0f66e6f07da24ba85dfb79bc/arch/arm/include/asm/psci.h
[blobs]: https://github.com/smaeul/sunxi-blobs/tree/7cda4903df7b46eba9514094904e57cbe0272520
[blob133]: https://github.com/smaeul/sunxi-blobs/tree/7cda4903df7b46eba9514094904e57cbe0272520/sun8iw5p1/arisc_v0.1.33
[blob-comments]: https://github.com/smaeul/sunxi-blobs/blob/7cda4903df7b46eba9514094904e57cbe0272520/sun8iw5p1/arisc_v0.1.33/comments
[blob-symbols]: https://github.com/smaeul/sunxi-blobs/blob/7cda4903df7b46eba9514094904e57cbe0272520/sun8iw5p1/arisc_v0.1.33/symbols
[blob-license]: https://github.com/smaeul/sunxi-blobs/blob/7cda4903df7b46eba9514094904e57cbe0272520/LICENSE
[nintendo-tree]: https://github.com/mistydemeo/super_nes_classic_edition_oss/tree/730dff9833a887ed43787f1c1b1cbbecb4c6e3e3
[nintendo-mctl]: https://github.com/mistydemeo/super_nes_classic_edition_oss/blob/730dff9833a887ed43787f1c1b1cbbecb4c6e3e3/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/board/sunxi/sun8iw5/standby/dram/mctl_sys.c
[nintendo-regs]: https://github.com/mistydemeo/super_nes_classic_edition_oss/blob/730dff9833a887ed43787f1c1b1cbbecb4c6e3e3/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/board/sunxi/sun8iw5/standby/dram/mctl_reg.h
[nintendo-standby]: https://github.com/mistydemeo/super_nes_classic_edition_oss/blob/730dff9833a887ed43787f1c1b1cbbecb4c6e3e3/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/board/sunxi/sun8iw5/standby/standby.c
[nintendo-dram-makefile]: https://github.com/mistydemeo/super_nes_classic_edition_oss/blob/730dff9833a887ed43787f1c1b1cbbecb4c6e3e3/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/r16-uboot-371a64b6922f4b4a63be022768e251d0c1a6fa87/arch/arm/cpu/armv7/sun8iw5/dram/Makefile

[crust-dram-license]: https://github.com/crust-firmware/crust/blob/499a362645e6ce6ac1fd8ea8d0f25d4df6690688/drivers/dram/dram.c
[micile-standby]: https://github.com/micile/linux-sunxi/blob/2f961cb880c19ac9a9a1c39fe24913f308205426/drivers/arisc/interfaces/arisc_standby.c
