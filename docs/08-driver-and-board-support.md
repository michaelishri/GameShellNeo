# Driver and board support for the initial GameShellNeo base

Research date: **27 September 2026**. This is a source audit and engineering proposal, not a tested port. It follows [the agreed requirements](06-base-requirements.md): the owner's presumed CPI v3.1 board, minimal Armbian/Debian, standard Linux interfaces, no launcher, and permission to replace historical implementations when that improves the result. Board markings remain to be confirmed.

The subsequently supplied vendor guides are assessed in [report 16](16-vendor-platform-and-driver-evidence.md). They add supply/pin and boot-stage ownership checks; reference tablet configurations and their example operating points are not qualified CPI settings.

The local reference is `clockworkpi/GameShell` commit `523cf591e2f955d001d257d7c850406f9fd917eb`. All seven `Code/Kernel/v0.6` patches were read. Selected upstream files were compared at Linux **v6.12** and **v6.18**; these are immutable source-comparison points, not the patch releases to deploy. No kernel, DTB or image was built, and no hardware or original source checkout was modified. This report complements the sleep and battery investigations rather than declaring those problems solved.

## Recommendation

Use the maintained **6.18.y LTS line as the first integration candidate**, with **6.12.y as a diagnostic fallback**. On the research date kernel.org lists 6.18.54 and 6.12.111; both have projected maintenance through December 2028. The selected patch release must be refreshed and pinned when building starts. Current Armbian sunxi configuration already selects 6.18 for `current` and 6.12 for `legacy`, making this a practical integration choice. Nothing inspected establishes that either version is qualified for GameShell. [Current kernel versions](https://www.kernel.org/); [maintenance schedule][releases]; [Armbian family configuration][armbian-family].

The core work is **a correct board description, panel lifecycle, backlight behavior, power sequencing and validation**. The evidence does not justify replacing the general Allwinner display engine, Broadcom Wi-Fi stack, USB gadget stack or USB HID stack. New code is most credible where the board's hardware has no suitable integrated driver, or a reproducible limitation requires a focused extension. [A33 source][a33-618]; [display reference][display]; [Broadcom SDIO source][brcm-sdio]; [USB gadget documentation][configfs]; [keypad firmware][keypad].

A useful new lead is an **August 2026 OCP8178 submission** by Wim de With, written independently for ClockworkPi uConsole hardware. Its v4 series includes a standard backlight driver and reviewed DT binding. It is a candidate for assessment/backporting; it is not evidence that GameShell already has upstream backlight support or tested suspend behavior. [Author's v4 cover letter][ocp-cover]; [driver submission][ocp-driver]; [binding submission][ocp-binding].

## What was and was not checked upstream

| Check | Result and boundary |
| --- | --- |
| Linux v6.12 and v6.18 `arch/arm/boot/dts/allwinner` directories | Neither contains a GameShell/Clockwork CPI3-named board DTS. A33 and R16 SoC/other-board descriptions are present. This is a directory inventory, not a search of every external patch or renamed compatible. [v6.12 directory][dts-612]; [v6.18 directory][dts-618] |
| Linux panel and backlight Makefiles, plus `panel-simple.c`, at v6.12 and v6.18 | No legacy `kd027-lcd`, `clockwork,cpi3-lcd` or OCP8178 implementation was found in these locations. Other Startek panels exist; a shared manufacturer does not establish compatible hardware. [Panel sources][panel-simple]; [panel Makefile][panel-make]; [backlight Makefile][bl-make] |
| OCP8178 in later Linux tags | No OCP8178 filename in the inspected backlight directories at v7.2 or v7.3-rc4. That distinguishes the v4 submission from a merged driver in those releases; it does not establish the state of every maintainer tree. [v7.2 directory][bl-72]; [v7.3-rc4 directory][bl-73] |
| U-Boot v2026.07 | An untruncated recursive tree listing contained no GameShell/CPI3-named path; the ClockworkPi D1 board found there is a different product. The `configs` contents API alone returns only 1,000 entries and was not used as proof of absence. [Complete tree query][uboot-tree] |
| Community Armbian fork | The pinned 2023 fork contains CPI3 DTS/display/power/audio patches for 6.1/6.6 and a U-Boot patch. The board file also adds desktop and launcher policy, which is outside this milestone. Its existence establishes prior integration work, not reproducibility or reliability on a new kernel. [Fork tree][community-tree]; [board file][community-board] |

The v6.12/v6.18 A33 DTS and AXP power-key driver are byte-identical in the inspected snapshots. Wi-Fi integration has evolved: v6.18's `brcmf_of_probe()` can request an optional 32.768 kHz `lpo` clock, and `mmc-pwrseq-simple` has shared-reset support absent from the earlier inspected version. These are reasons to use matching bindings and source when designing the new DT, not reasons to invent a clock/reset connection absent from the schematic. [A33 v6.12][a33-612]; [A33 v6.18][a33-618]; [PEK v6.12][pek-612]; [PEK v6.18][pek]; [Wi-Fi OF source][brcm-of]; [power-sequence source][pwrseq].

## Disposition of every v0.6 patch

The vendor instructions target Linux 5.15.y commit `5827ddaf4534c52d31dd464679a186b41810ef76`. These patches are a hardware notebook and historical integration record, not a patch queue to apply wholesale. [Vendor build instructions][vendor-readme].

| Patch | What it changes | Proposed disposition |
| --- | --- | --- |
| `515_dts.patch` | Adds LCD and HDMI board variants, peripheral pin assignments, PMIC and regulator setup, Wi-Fi power sequencing, USB roles and private panel/backlight/rfkill nodes. | **Rewrite the board description** against current schemas, retaining verified electrical facts. Initially add only the LCD variant. Audit supply consumers, CPU supply ownership, device dependencies and suspend states individually. Do not copy blanket `always-on` constraints or remove them indiscriminately. [Source][dts] |
| `515_defconfig.patch` | Adds a complete generated kernel configuration, including platform drivers and legacy interfaces. It selects only the performance CPU-frequency governor and disables `CONFIG_CPU_IDLE`. | **Replace with a small configuration fragment** over an appropriate ARM/sunxi baseline. Enable required diagnostics and power-management functionality; select an adaptive governor and evaluate actual idle-state support. Configuration does not create a missing platform sleep implementation. [Source][defconfig] |
| `515_display.patch` | Adds fixed LCD/HDMI modes to `panel-simple`, a separate GPIO KD027 control driver, an OCP8178 backlight driver, private `/proc` endpoints, cursor suppression and logo-position changes. | **Split by responsibility.** Integrate LCD initialization and power sequencing into a DRM panel driver; assess the newer OCP8178 proposal; drop private `/proc` interfaces and framebuffer cosmetic changes. HDMI functionality remains deferred. [Source][display] |
| `515_power.patch` | Replaces AXP22x power-key edge IRQ resources with short/long IRQ resources; synthesizes a key press/release after a 100 ms sleep; adds writable LED `/proc` nodes; expands the analog-codec PRCM resource from 4 to 16 bytes. | **Start with unmodified upstream power-key and LED drivers.** Implement short-press policy in userspace. The PRCM change supports the historical audio work and is not a battery/suspend fix; defer with audio unless a separately demonstrated issue requires it. [Source][power] |
| `515_wifi.patch` | Adds `/proc/driver/brcmf_fw` and an unconditional 1,000 ms delay at the start of Broadcom SDIO probe. | **Drop both initially.** Record firmware identity through normal diagnostics. If a timing problem reproduces, fix the relevant reset/supply sequence or narrowly scoped driver issue instead of reinstating an unexplained delay for every SDIO Broadcom device. [Source][wifi] |
| `515_sound.patch` | Adds analog register access/jack-detection logic and amplifier control, renames a mixer control, changes digital AIF programming and introduces a 450 ms initialization delay. | **Defer playback integration.** Keep the amplifier inactive and establish rail ownership in the base. Revisit functional audio against current ASoC support, preserving evidence for pop/noise and routing problems without making this patch mandatory. [Source][sound] |
| `515_logo.patch` | Replaces the kernel logo image. | **Drop from the hardware patch set.** Branding is later presentation work and provides no required driver functionality. [Source][logo] |

The private LCD, backlight and LED write handlers copy caller-provided lengths into 64-byte static buffers without bounds checks, then write a terminator at the supplied index. They also rely on global device state. These are concrete reasons to discard the interfaces, beyond the maintenance cost of carrying launcher-specific APIs in generic drivers. This source finding does not assert that the owner's running image exposes those exact handlers. [Display patch][display]; [power patch][power].

## Initial subsystem matrix

| Subsystem | Existing foundation | GameShellNeo work and acceptance evidence |
| --- | --- | --- |
| CPU, clocks, pinctrl and thermal sensing | A33-family upstream description and drivers. | Correct regulator linkage and configuration; verify clocks, voltage transitions, temperature reporting and load stability. [A33][a33-618] |
| microSD | Standard Allwinner MMC with board supplies and PB3 card-detect in the reference DT. | Confirm card identification, boot/root storage and error-free load/resume. SDIO Wi-Fi is a separate MMC controller. [Board DT][dts] |
| LCD scanout | Upstream sun4i DRM with A33 display-engine and TCON compatibles. | Correct panel/control integration and RGB timing; test modesetting and blank/unblank without Lima rendering. [A33][a33-618]; [display reference][display] |
| Backlight | Hardware-specific OCP8178 protocol; newer upstream submission available. | Implement brightness, actual off, shutdown and restart after power loss; quantify latency and validate all levels. [Legacy implementation][display]; [v4 submission][ocp-driver] |
| Game controls | Keypad firmware exposes a USB HID keyboard. | Standard host/HID/input support; confirm all buttons, combinations, key release and resume. No initial MCU firmware rewrite. [Firmware][keypad]; [USB descriptor][usb-keyboard] |
| Power button | Upstream AXP20x PEK input driver with wake IRQ handling. | Verify short press, hold/release and wake behavior; prevent the wake press from immediately triggering another sleep. [PEK][pek] |
| Wi-Fi | Mainline `brcmfmac` SDIO support for relevant BCM43430 chip revisions. | Identify real chip/firmware/NVRAM; correct supplies/reset; validate awake power saving and disconnect/reprobe/reconnect. [SDIO mapping][brcm-sdio]; [SDIO power management][brcm-pm] |
| USB management | A33 MUSB device controller plus standard gadget functions. | Board VBUS/role setup, ECM or NCM gadget configuration, stable addressing and macOS enumeration/resume tests. [A33][a33-618]; [configfs][configfs] |
| Battery and charging | AXP223 includes AXP22x battery/USB power-supply nodes. | Enable and validate telemetry and charging policy; use the separate battery investigation for percentage accuracy and low-battery protection. A DT node alone proves neither. [AXP223][axp223]; [AXP22x][axp22x] |
| Deferred peripherals | HDMI bridge, Mali GPU, codec/amplifier, Bluetooth remain physically present. | Establish harmless initial states and inspect clocks/rails. Disabled functionality is not evidence of zero consumption. [Hardware report](02-hardware.md); [reference DT][dts] |

### LCD: one lifecycle owner

The old implementation has three independent pieces: a mode-only `panel-simple` entry, a GPIO control platform driver, and a backlight driver. Its panel node lacks a backlight phandle. The control driver requests reset high, sends four initialization register/value pairs at probe, and sends `0x2b/0x00` or `0x2b/0x01` during system suspend/resume. It does not establish a complete cold-power-up sequence or integrate those operations with DRM blanking. Its existence cannot prove the display recovers after its supply is actually removed. [Display patch][display]; [DT patch][dts].

**Proposed design:** identify the controller/panel variant, then extend a suitable existing DRM panel driver or add a small panel driver that owns prepare/enable/disable/unprepare, reset, power and control transactions. Connect the backlight through the panel's standard DT relationship. Standard panel bindings already describe power-supply, backlight and timing; the remaining problem is this panel's control protocol and lifecycle. [Upstream panel binding][panel-dpi]; [DRM panel source example][panel-example].

The legacy PC0/PC2/PC3 control pins and 16-bit command/data transfers are useful evidence when evaluating a standard SPI controller or `spi-gpio` transport. Neither transport is selected here: verify pin multiplexing, SPI mode, chip-select behavior and timing before choosing. Retain panel identity and necessary electrical timing in code/bindings instead of making unvalidated register bytecode a general-purpose user-facing API. The physical drawing describes RGB666 while the old mode-only driver advertises eight bits per component; reconcile this with bus format and actual panel identity rather than copying that metadata. [Hardware analysis](02-hardware.md); [reference display code][display]; [reference DT][dts].

Useful early tests are solid colors, gradients, checkerboards, fast blank/unblank and repeated resume from a genuinely unpowered panel state. A working console after warm boot is insufficient: bootloader state can hide missing initialization. These are proposed tests, not completed measurements.

### Backlight: minimum brightness and power-off must be distinct

The old OCP8178 implementation maps ten software values to controller commands `0,1,4,8,12,16,20,24,28,31`. Even at blank/suspend it sends command zero and leaves CTRL high. It enters one-wire mode only at probe, with about 4.7 ms of programmed delay while local interrupts are disabled. This makes actual off-state semantics and recovery after controller power loss priority checks; code zero must not be assumed equivalent to shutting down the converter. [Legacy backlight source][display].

Wim de With's v4 proposal, dated 26 August 2026, uses `ocs,ocp8178`, `ctrl-gpios`, per-device state, standard backlight helpers and a 0–31 range. It rejects sleep-capable GPIOs and limits interrupt masking to short serial writes. It carries review trailers. However, its update path also sends a brightness value, and protocol initialization occurs at probe. Assess true off and reinitialization after power removal before adopting it for this power-focused product. Prefer an upstream-compatible extension over another independent fork if those behaviors need work. [v4 driver][ocp-driver]; [v4 binding][ocp-binding].

The manufacturer's current product page describes one-wire and PWM control, but its linked three-page v1.9 datasheet is an abbreviated document emphasizing PWM. It does not provide enough information to settle all one-wire shutdown/brightness semantics. Obtain a complete, applicable controller datasheet or validated hardware evidence; do not infer them solely from either implementation. [Manufacturer page][ocp-product]; [manufacturer PDF][ocp-datasheet].

### CPU efficiency: fix ownership before optimizing frequencies

The old DT names DCDC3 `vdd-cpu`, fixes it to 1.2 V and does not assign a `cpu-supply` consumer link. Coupled with a performance-only governor configuration, this is a poor policy baseline for an efficiency project. This observation concerns checked-in configuration, not a measurement of the installed OS. [DT][dts]; [defconfig][defconfig].

The inspected upstream A33 operating-point table spans 120–1,008 MHz, using 1.04, 1.10 and 1.20 V. **Propose validating those upstream operating points first**, with the board's real CPU supply linked correctly and regulator constraints permitting the required range after the schematic and board are confirmed. Do not introduce the marketed 1.2 GHz frequency, arbitrary undervolting or community DRAM timings as presumed-safe optimizations. A frequency governor cannot save voltage through a supply it does not control. [A33 operating points][a33-618]; [hardware report](02-hardware.md).

Enable and inspect suitable CPU idle support, but distinguish clock-frequency policy, shallow CPU idle and whole-system suspend. `CONFIG_CPU_IDLE=y` alone is not evidence that a deep idle state exists. Retain thermal protection and measure energy for equal completed work; the slowest frequency need not minimize total energy. These are engineering criteria, not performance claims.

Current Armbian's generic `sun8i` family defaults include `CPUMIN=480000`, `CPUMAX=1400000` and an H3 overlay prefix if not overridden. The CPI3 board definition must override these deliberately. These defaults do not prove the kernel will actually run at 1.4 GHz, but they should not become GameShell policy accidentally. [Pinned `sun8i.conf`][armbian-sun8i].

### Wi-Fi: standard driver, explicit firmware and power lifecycle

The source maps BCM43430 chip revisions to distinct firmware stems, including `brcmfmac43430a0-sdio`, `brcmfmac43430-sdio` and `brcmfmac43430b0-sdio`. Broadcom's DT integration derives the board type from the root compatible unless overridden; that affects firmware/NVRAM filenames. A new GameShellNeo compatible therefore needs an explicit firmware naming decision, not a hopeful copy of another board's file. [Firmware mapping][brcm-sdio]; [OF implementation][brcm-of]; [binding][brcm-binding].

The local source trees contain Bluetooth helpers/blobs but did not supply a reproducible, identified Wi-Fi NVRAM installation in the filename/content checks performed. Upstream linux-firmware has an AP6212-named NVRAM file, but that is a candidate to compare with the working installation, not proof that it matches this unit's module revision and antenna design. Capture the original chip/revision logs, actual requested filenames, binary versions, NVRAM contents/hashes and redistribution terms before selecting assets. Do not reuse an unrelated Raspberry Pi calibration simply because the chip family matches. [Local Bluetooth directory][bluetooth]; [pinned firmware directory][firmware-dir]; [firmware request implementation][brcm-fw].

The 1-second vendor probe delay is not a protocol feature. Mainline `mmc-pwrseq-simple` already expresses reset handling, optional external clock, a post-power-on delay and power-off delay. If needed, describe a measured module sequencing requirement at that boundary rather than delaying every Broadcom probe. Check the shared rail topology first: the reference DT marks multiple Wi-Fi rails always-on and uses ALDO1 as MMC1's supply; it does not fully model individual radio supplies. A multi-supply or shared-resource extension may be justified, but a new Wi-Fi network driver is not the default solution. [Power-sequence binding][pwrseq-binding]; [implementation][pwrseq]; [board DT][dts].

**Removing `keep-power-in-suspend` is insufficient.** In v6.18, `brcmfmac`'s SDIO suspend path chooses removal/reprobe only when the host advertises `MMC_CAP_POWER_OFF_CARD` and wake-on-WLAN is disabled. Otherwise it tries to keep power. The board must first have a credible power-off/reset sequence, then use the matching `cap-power-off-card` policy and verify that the selected path actually runs. Wi-Fi link reconnection should be measured separately from display/input resume. [SDIO suspend/resume implementation][brcm-pm].

### Keypad and power button

Keep the existing keypad firmware for the first milestone. It presents ordinary keyboard reports, so the job is USB host/HID/input integration and reliable suspend/resume, not a new GameShell-specific kernel input protocol. Because game-button wake is not required, USB wake can be disabled for this device after confirming the power-button path; verify enumeration and held-key/release state after wake. Turning off host VBUS can save additional power only if the board actually removes power from the keypad MCU—this requires checking its wiring and observing behavior. [Firmware][keypad]; [HID report definition][usb-keyboard]; [board USB setup][dts].

Use upstream AXP power-key edge events. The old short/long interrupt remapping and synthetic press/release cannot be treated as the owner's requested short-press sleep policy. Upstream exposes wake-enabled PEK interrupts, but its explicit wake-key suppression in `resume_noirq` is restricted to AXP288. GameShell's AXP223 wake press may therefore need policy-level handling to avoid an immediate second sleep; test event ordering instead of assuming suppression is generic. [Legacy power patch][power]; [upstream PEK][pek]; [upstream IRQ resources][axp-mfd].

### USB networking with the M2 Mac

Use **standard composite gadget configuration**, initially testing a single CDC-ECM function; retain CDC-NCM as an alternative to compare on the actual Mac. Linux already provides the functions and userspace configfs assembly. The historical USB Ethernet patch is primarily configuration enabling `g_ether`/ECM/RNDIS, not a missing GameShell networking driver. [Configfs documentation][configfs]; [historical USB patch][usb-patch]; [upstream ECM implementation][ecm].

Apple publishes an ECM driver implementation, establishing the protocol's history on macOS. It does **not** certify the user's Tahoe 26.5.1 installation or this gadget's descriptors. Qualification needs actual enumeration, addressing, SSH through the Mac, cable removal/reconnection, deliberate GameShell sleep while attached and resume/re-enumeration. Keep serial diagnostics available because gadget networking starts too late to diagnose many boot failures. [Apple's source][apple-cdc]; [agreed development setup](06-base-requirements.md).

Specify a stable per-device serial number and locally administered MAC addresses, one USB subnet that does not overlap the LAN, and one owner for address assignment. An SSH jump host is sufficient for Intel-to-GameShell access; routed Internet access is a separate host configuration. USB gadget configuration and networking policy should be versioned userspace assets, not modifications to the USB kernel stack. This is a proposed integration design based on the available standard interfaces. [Configfs ABI and workflow][configfs].

## Bootloader and device-tree gaps

The 2023 community U-Boot patch supplies a sixteen-line configuration with A33 selection, DRAM clock 600 MHz, ZQ value 15291, ODT, PB3 card-detect, a second MMC slot setting, PL4 USB ID, a fixed LCD mode and zero boot delay. It supplies evidence of a previous configuration, not validation of those settings on the owner's board or modern U-Boot. Inventory the running U-Boot banner, DRAM size and boot behavior before proposing the replacement. [Community U-Boot patch][community-uboot].

The new board definition needs a checked relationship between SPL initialization, U-Boot's DT/configuration and the Linux DT. Linux must initialize the peripherals it owns independently enough that a different bootloader display state does not determine correctness. U-Boot display initialization is optional for early feedback, whereas a correct Linux panel lifecycle remains necessary. Storage layout and cold-boot/OTA design are separate decisions; preserving a recovery route is part of qualifying the bootloader, not a reason to reuse an unexplained binary.

Proposed DT review before the first image:

1. Confirm board and module identity against the physical markings; reconcile the older schematic with CPI v3.1.
2. Add one appropriately named board compatible/DTS and relevant schema entry; select current vendor prefixes rather than preserving bare names such as `kd027-lcd` or `rfkill_gpio`.
3. Trace every rail to its consumers, its bootloader state and its shutdown/suspend requirement. Separate necessary always-on supplies from missing consumer descriptions.
4. Describe the panel/backlight dependency and verify RGB pinctrl, control-bus ownership, reset polarity, bus format and timing.
5. Describe microSD, SDIO Wi-Fi, USB host for the keypad, external gadget/OTG behavior, PMIC IRQ and UART console correctly.
6. Keep Bluetooth held inactive, speaker amplifier muted and deferred display/GPU functionality inactive without switching off rails shared with active devices.
7. Once implementation is authorized, run schema and DT checks against the pinned kernel, then inspect the resulting tree and boot logs. Compilation/schema success still requires electrical and functional tests.

These are proposed checks. No DT validation was executed because no replacement tree has been authored. The existing DTS is the source of the board wiring claims above; the modern bindings are the validation target, not evidence that those checks have already passed. [Reference DT][dts]; [Linux DT validation documentation][dt-check]; [vendor-prefix schema][vendor-prefix].

## Proposed downstream boundaries and removal conditions

| Change boundary | Initial expectation | Removal or acceptance condition |
| --- | --- | --- |
| Board DTS and bindings | Required new board integration. | Accepted upstream with correct board identity and qualified behavior. |
| LCD panel integration | Likely a small new driver or extension after controller identification. | Upstream panel support supplies the same validated lifecycle and timing. |
| OCP8178 backlight | Evaluate/backport v4 or its eventual upstream successor; extend power-off/recovery if evidence requires. | Mainline driver covers the required behavior on GameShell. |
| Radio/shared supply sequencing | Potential DT work or focused framework extension; size not yet known. | Standard supply/power-sequence support describes all necessary dependencies. |
| SoC suspend/firmware | Separate feasibility dependency; no patch-count promise. | Selected upstream/firmware path demonstrably enters and leaves the desired state. |
| Config, firmware manifest and policy | Required image assets, kept outside generic kernel drivers. | Remain versioned configuration even after all hardware support is upstream. |
| Legacy `/proc`, framebuffer cosmetics, logo, audio/HDMI tweaks | Excluded from the initial hardware queue. | Reintroduce only a newly justified requirement, using standard interfaces where available. |

This is an estimated division of responsibilities, **not a complete proven minimum patch set**. Display identity, shared supplies and platform suspend can change its size. Each actual change should record the observed problem, owning hardware/interface, upstream status, test that demonstrates the need, power/resume consequences and condition for deletion.

## Evidence needed before calling the base solid

The first image should establish a diagnostic baseline, followed by subsystem qualification. Proposed evidence includes boot logs and hardware IDs; console/display output through repeated blanking and resume; every keypad key and release; real backlight off/recovery; Wi-Fi scans/transfers and power-cycle recovery; USB enumeration/SSH through the named Mac; battery/external-power reporting; regulator/clock ownership; and repeated shutdown/reboot/sleep tests. Capture failures with serial where possible and keep the original card unchanged.

For efficiency, record the kernel/config/DT/firmware versions, brightness, radios, workload, USB-power state and logging overhead with each battery test. A source cleanup, a smaller root filesystem, an adaptive governor or a newly written driver is not itself a measured power improvement. The investigation supports a credible path to a small maintained hardware layer, while reliable deep sleep, week-long standby, fast wake and a sub-five-second cold boot remain qualification goals.

## Sources

Local links point to the supplied checkout; its commit is pinned at the top. Online code links use fixed tags or commits. Mailing-list submissions below are the author's own patch text mirrored by Patchew, not a secondary description.

[vendor-readme]: ../../GameShell/Code/Kernel/v0.6/README.md
[dts]: ../../GameShell/Code/Kernel/v0.6/515_dts.patch
[defconfig]: ../../GameShell/Code/Kernel/v0.6/515_defconfig.patch
[display]: ../../GameShell/Code/Kernel/v0.6/515_display.patch
[power]: ../../GameShell/Code/Kernel/v0.6/515_power.patch
[wifi]: ../../GameShell/Code/Kernel/v0.6/515_wifi.patch
[sound]: ../../GameShell/Code/Kernel/v0.6/515_sound.patch
[logo]: ../../GameShell/Code/Kernel/v0.6/515_logo.patch
[keypad]: ../../GameShell/Code/Keypad/clockworkpi_keypad.ino
[usb-keyboard]: ../../GameShell/Code/Keypad/UsbKeyboard/UsbKeyboard.h
[bluetooth]: ../../GameShell/Code/bluetooth
[usb-patch]: ../../GameShell/Code/USB-Ethernet/usb_ethernet.patch
[releases]: https://www.kernel.org/category/releases.html
[armbian-family]: https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/include/sunxi_common.inc
[armbian-sun8i]: https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/sun8i.conf
[a33-612]: https://github.com/torvalds/linux/blob/v6.12/arch/arm/boot/dts/allwinner/sun8i-a33.dtsi
[a33-618]: https://github.com/torvalds/linux/blob/v6.18/arch/arm/boot/dts/allwinner/sun8i-a33.dtsi
[dts-612]: https://github.com/torvalds/linux/tree/v6.12/arch/arm/boot/dts/allwinner
[dts-618]: https://github.com/torvalds/linux/tree/v6.18/arch/arm/boot/dts/allwinner
[panel-simple]: https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/panel/panel-simple.c
[panel-make]: https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/panel/Makefile
[bl-make]: https://github.com/torvalds/linux/blob/v6.18/drivers/video/backlight/Makefile
[bl-72]: https://github.com/torvalds/linux/tree/v7.2/drivers/video/backlight
[bl-73]: https://github.com/torvalds/linux/tree/v7.3-rc4/drivers/video/backlight
[uboot-tree]: https://api.github.com/repos/u-boot/u-boot/git/trees/v2026.07?recursive=1
[community-tree]: https://github.com/uberlinuxguy/armbian-build/tree/dd92a1abff08ad41fe23526285569b63271a5226
[community-board]: https://github.com/uberlinuxguy/armbian-build/blob/dd92a1abff08ad41fe23526285569b63271a5226/config/boards/clockworkpi-gameshell.csc
[community-uboot]: https://github.com/uberlinuxguy/armbian-build/blob/dd92a1abff08ad41fe23526285569b63271a5226/patch/u-boot/u-boot-sunxi/board_clockworkpi-gameshell/cpi-u-boot.patch
[pek-612]: https://github.com/torvalds/linux/blob/v6.12/drivers/input/misc/axp20x-pek.c
[pek]: https://github.com/torvalds/linux/blob/v6.18/drivers/input/misc/axp20x-pek.c
[axp-mfd]: https://github.com/torvalds/linux/blob/v6.18/drivers/mfd/axp20x.c
[axp223]: https://github.com/torvalds/linux/blob/v6.12/arch/arm/boot/dts/allwinner/axp223.dtsi
[axp22x]: https://github.com/torvalds/linux/blob/v6.12/arch/arm/boot/dts/allwinner/axp22x.dtsi
[brcm-sdio]: https://github.com/torvalds/linux/blob/v6.18/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c
[brcm-of]: https://github.com/torvalds/linux/blob/v6.18/drivers/net/wireless/broadcom/brcm80211/brcmfmac/of.c
[brcm-pm]: https://github.com/torvalds/linux/blob/v6.18/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c
[brcm-fw]: https://github.com/torvalds/linux/blob/v6.18/drivers/net/wireless/broadcom/brcm80211/brcmfmac/firmware.c
[brcm-binding]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/net/wireless/brcm,bcm4329-fmac.yaml
[pwrseq]: https://github.com/torvalds/linux/blob/v6.18/drivers/mmc/core/pwrseq_simple.c
[pwrseq-binding]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/mmc/mmc-pwrseq-simple.yaml
[firmware-dir]: https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware.git/+/refs/tags/20250211/brcm/
[panel-dpi]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/display/panel/panel-dpi.yaml
[panel-example]: https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/panel/panel-ilitek-ili9322.c
[ocp-cover]: https://patchew.org/linux/20260826-ocp8178-backlight-v4-0-47d7acce882e@dewith.io/
[ocp-driver]: https://patchew.org/linux/20260826-ocp8178-backlight-v4-0-47d7acce882e@dewith.io/20260826-ocp8178-backlight-v4-2-47d7acce882e@dewith.io/
[ocp-binding]: https://patchew.org/linux/20260826-ocp8178-backlight-v4-0-47d7acce882e@dewith.io/20260826-ocp8178-backlight-v4-1-47d7acce882e@dewith.io/
[ocp-product]: https://www.orient-chip.com/en/products/power-managements/led-drivers/backlight-led-drivers/22
[ocp-datasheet]: https://www.orient-chip.com/Public/Uploads/uploadfile/files/20231016/OCP8178DatasheetV1.9.pdf
[configfs]: https://docs.kernel.org/usb/gadget_configfs.html
[ecm]: https://github.com/torvalds/linux/blob/v6.12/drivers/usb/gadget/function/f_ecm.c
[apple-cdc]: https://github.com/apple-oss-distributions/AppleUSBCDCDriver/tree/main/AppleUSBCDCECM
[dt-check]: https://docs.kernel.org/devicetree/bindings/writing-schema.html
[vendor-prefix]: https://github.com/torvalds/linux/blob/v6.18/Documentation/devicetree/bindings/vendor-prefixes.yaml
