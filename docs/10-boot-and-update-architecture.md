# Boot time, image construction and future OTA updates

Research date: 2026-09-27. This report evaluates architecture against the [agreed requirements](06-base-requirements.md). Recommendations are proposals, not implementations. No kernel, bootloader or image was built; no device or card was modified.

## Recommendation

Use a pinned Armbian build framework to assemble minimal Debian armhf userspace and explicitly selected board support. Keep the bootloader, kernel, firmware, device tree and userspace manifest versioned together. Retain full U-Boot and diagnostic access during initial bring-up. Measure cold boot before choosing optimizations. For later OTA, evaluate signed A/B system images with RAUC as the first candidate, while keeping the bootloader outside routine updates initially.

This combination is an engineering recommendation based on the integration findings below, not a claim that an existing Armbian image already meets GameShellNeo's requirements. The [driver audit](08-driver-and-board-support.md) and [sleep investigation](07-sleep-and-wake-feasibility.md) determine what the image must carry.

## A modern userspace is available, but board defaults need auditing

Debian 13 supports ARMv7 hard-float (`armhf`), ships the Linux 6.12 family and systemd 257, and changes the time-related ABI of many armhf libraries. That supports a current Debian userspace for this hardware, but old third-party binaries require rebuilding or compatibility assessment. Debian architecture support is not GameShell board qualification. [Debian 13 release notes](https://www.debian.org/releases/trixie/release-notes/whats-new.en.html).

The inspected Armbian framework commit is `488dc40c493ba7633e379dbcf5606d7d58ee4575`. Its sunxi family selects armhf and U-Boot v2026.07; its `legacy`, `current` and `edge` branches select kernel families 6.12, 6.18 and 7.2 respectively. These labels move over time. The sun8i file also supplies default CPU limits of 480–1400 MHz and an H3 overlay prefix. Those defaults are not a qualified R16/GameShell policy. [Pinned sunxi family](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/include/sunxi_common.inc), [sun8i configuration](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/sun8i.conf).

Armbian supports project-supplied configuration and patches through `userpatches`, including replacing or disabling framework patches. Consequently, a GameShellNeo repository can own its board definition and patch policy without treating all of a large fork as project code. The inherited patch series still needs recording and review. [Armbian configuration documentation](https://docs.armbian.com/build-framework/user-configurations/).

For each future experimental image, preserve these inputs:

- Framework commit and container/build-host definition.
- U-Boot and Linux commits, complete applied patch lists, configurations and device-tree sources.
- Firmware names, versions, checksums and source/provenance.
- Userspace package versions, repositories and image customization inputs.
- Output checksums and a hardware-test result linked to that exact image.

These are proposed traceability requirements. Pinning source is necessary for comparison; it does not itself guarantee byte-identical outputs when package repositories, timestamps or generated files vary. A successful fresh rebuild is a separate acceptance result.

## Define the five-second target before optimizing

The owner's target is less than five seconds from power-on to a usable system. The project currently has no launcher, so the proposed initial ready event is a visible local test screen/console with confirmed input handling and the power-policy service operational. This is a temporary test endpoint, not a launcher design. Record USB SSH readiness and Wi-Fi association separately; network conditions should not redefine the local boot metric.

The path to measure is:

```text
Power-button event / power applied
  → Boot ROM → SPL and DRAM initialization → U-Boot
  → kernel initialization → root filesystem / optional initramfs
  → essential services → local usable-ready marker
```

The ROM/SPL chain and firmware placement are documented by U-Boot's Allwinner support. U-Boot also has bootstage reporting and data export hooks. Linux/systemd timing covers later portions, but systemd's documentation cautions that service-start timings do not establish complete initialization or disk quiescence. Therefore `systemd-analyze time` alone is not proof of a five-second cold boot. [U-Boot sunxi boot description](https://github.com/u-boot/u-boot/blob/ece349ade2973e220f524ce59e59711cc919263f/doc/board/allwinner/sunxi.rst), [bootstage command](https://github.com/u-boot/u-boot/blob/ece349ade2973e220f524ce59e59711cc919263f/cmd/bootstage.c), [systemd timing documentation](https://github.com/systemd/systemd/blob/v257/man/systemd-analyze.xml).

With the available equipment, timestamped serial logs plus a recorded view of the button and screen can provide a useful baseline. Record frame rate/timestamp resolution and where observation begins. Serial output itself affects timing; retain verbose diagnostic and quieter measurement configurations and compare them. Report first boot separately from repeated normal boots, since provisioning and filesystem growth are different workloads.

### Optimization order

The following is a proposed sequence, not a measured ranking of current bottlenecks:

1. **Remove deliberate waits and unnecessary boot searches.** The inspected Armbian family specifies a one-second boot delay. U-Boot permits bootflow scanning to be restricted to a selected device. Preserve an intentional recovery entry path while narrowing the normal boot path. [Armbian family source above](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/include/sunxi_common.inc), [U-Boot bootflow](https://docs.u-boot.org/en/latest/usage/cmd/bootflow.html).
2. **Resolve driver delays and failed probes.** Investigate essential regulator, display, storage and firmware initialization. Avoid masking a dependency problem with a fixed sleep. The driver audit identifies the legacy Wi-Fi delay as a candidate for investigation rather than automatic retention. [Driver audit](08-driver-and-board-support.md).
3. **Keep the critical userspace path small.** Network connectivity, optional update checks and later application services should not block local readiness. Keep charging and power policy available early. Dependencies, not merely the number of installed packages, determine the critical path.
4. **Assess kernel size, compression and initramfs needs with measurements.** A direct root mount may simplify a fixed development image; production recovery or verified-root arrangements may justify an initramfs. Do not make its removal an unconditional rule before the update architecture is chosen.
5. **Consider SPL-to-kernel boot only if measurement justifies it.** U-Boot Falcon Mode can bypass full U-Boot but needs board integration. Slot selection, recovery and verified boot must still work in whichever code executes. No working GameShell Falcon configuration was established here. [Falcon Mode documentation](https://docs.u-boot.org/en/latest/develop/falcon.html).

A five-second guarantee cannot be made from source inspection. SD-card behavior, DRAM initialization, driver waits and actual required services remain unmeasured. A fast cold boot also does not satisfy the separate requirement to resume the previous running state.

## A concrete storage constraint: do not copy a generic GPT layout

The legacy GameShell instructions place U-Boot/SPL at **8 KiB** on the card. Current U-Boot documentation warns that this placement overlaps a normal GPT partition-entry area; its alternative 128 KiB ROM boot location is documented for newer Allwinner generations, not established for this R16 board. The inspected Armbian sunxi writer also clears nearly the first MiB before writing at 8 KiB. [Local flashing note](../../GameShell/Code/Kernel/v0.4/how_to_flash_u-boot.md), [U-Boot sunxi documentation](https://github.com/u-boot/u-boot/blob/ece349ade2973e220f524ce59e59711cc919263f/doc/board/allwinner/sunxi.rst), [Armbian writer](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/include/sunxi_common.inc).

**Recommendation:** begin storage design from an explicit byte/sector map compatible with the verified boot ROM. An MBR layout with a reserved firmware area is a reasonable candidate. Do not select offsets from another board or execute the framework's low-level writer against a production A/B layout without auditing every range. Bootloader/environment overlap can defeat otherwise correct update logic.

An eventual logical layout could be:

```text
partition metadata + reserved SPL/U-Boot and boot-state areas
system A: kernel + DTB + optional initramfs + matching root filesystem
system B: kernel + DTB + optional initramfs + matching root filesystem
persistent data/settings
```

This diagram specifies ownership, not partition numbers or sizes. Whether kernel assets reside inside each root partition or in associated boot partitions is still open. Prefer one coherent kernel/DTB/modules set per slot. Avoid a single mutable shared kernel that makes both supposedly independent root filesystems unbootable after one bad update.

## OTA candidate and the pieces we still own

RAUC supports signed bundles, target compatibility checks and installation into configured slots. U-Boot integration requires slot-selection scripting and persistent boot state; marking a boot successful belongs to system integration. RAUC is an update engine, not a complete product UI or update service. [RAUC basics](https://rauc.readthedocs.io/en/latest/basic.html), [RAUC integration](https://rauc.readthedocs.io/en/latest/integration.html). Versioned source inspected: [RAUC v1.15.2](https://github.com/rauc/rauc/tree/v1.15.2).

The upstream U-Boot example uses `BOOT_ORDER` and remaining-attempt variables, and explicitly expects adaptation. It demonstrates why copying an example would be inadequate: its example storage is NAND plus eMMC, whereas this project boots from microSD. U-Boot's generic `bootcount` feature is another mechanism, not automatically the same policy as RAUC's slot attempt counters. Choose one coherent design and test its persistent state. [RAUC boot script](https://github.com/rauc/rauc/blob/v1.15.2/contrib/uboot.sh), [U-Boot boot-count interface](https://github.com/u-boot/u-boot/blob/ece349ade2973e220f524ce59e59711cc919263f/doc/api/bootcount.rst).

Proposed product behavior:

1. Download a release description and authenticated bundle; check board compatibility, available space and power conditions.
2. Write and verify the inactive system slot while the current slot stays usable.
3. Select the new slot for a bounded trial boot.
4. Mark it good only after essential local health checks pass. An unavailable Wi-Fi access point should not invalidate an otherwise healthy system.
5. Fall back after failed boots. Keep persistent settings and user data compatible with the previous slot, or explicitly define migration/recovery behavior.

This is a GameShellNeo proposal. It needs implementation of release hosting/discovery, signing-key handling, an install policy, health checks, persistent boot state, reset/watchdog behavior and user-facing update status later. Merely installing RAUC does not supply those choices.

A signature on an update bundle establishes authenticity under the configured trust keys; it is separate from a hardware-rooted verified-boot chain. U-Boot's verified-boot documentation describes the latter chain. No immutable trust anchor has been established for this device, and OTA authenticity should not be advertised as complete resistance to physical card modification. [U-Boot verified boot](https://docs.u-boot.org/en/latest/usage/fit/verified-boot.html).

Likewise, two root slots on one SD card protect against some interrupted or bad updates, not against card failure or arbitrary shared-data corruption. Routine SPL/U-Boot updates should initially remain excluded from OTA because losing the common first boot stage bypasses root-slot fallback. The spare-card reflash path remains a practical recovery route while those guarantees are developed.

For comparison, SWUpdate offers flexible handlers and scripting, while Mender documents Debian-family image integration. Both merit evaluation if RAUC's constraints prove awkward, but no GameShell-specific integration of any of these projects was verified. A full framework bake-off would be premature before the boot/storage contract exists. [SWUpdate overview](https://sbabic.github.io/swupdate/overview.html), [Mender Debian-family integration](https://docs.mender.io/operating-system-updates-debian-family).

## Tests to require later

These are proposed tests, not completed results:

| Test | Evidence to collect |
| --- | --- |
| Repeated normal cold boots | End-to-end median, spread and worst observed time; stage timestamps and image identity |
| No access point / failed DNS | Local readiness remains independent; networking reports its own condition |
| Valid signed update | Inactive-slot write, verified trial boot and explicit mark-good transition |
| Wrong board / damaged or untrusted bundle | Rejection before activating the candidate slot |
| Interrupted download or inactive-slot installation | Previous system remains bootable; status is understandable and retryable |
| New kernel cannot boot / userspace fails / system hangs | Bounded retry and recovery; a hang needs a functioning reset/watchdog path to reach another boot attempt |
| Rollback after settings changes | Old system can use persistent state or offers a defined recovery route |
| Corrupted boot state | Tested fallback rules; redundant metadata does not become an untested assumption |

Controlled interruption tests belong on a disposable development card after the recovery path is established. No destructive tests are part of this research.
