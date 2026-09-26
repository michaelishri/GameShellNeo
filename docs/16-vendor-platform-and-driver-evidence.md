# Vendor platform guides: useful evidence for modern driver work

Research date: **27 September 2026**. This report examines the newly supplied Allwinner development documents in `GameShellNeo/allwinner`. It supplements [the modern driver audit](08-driver-and-board-support.md); it does not replace the selected upstream-first approach with the historical SDK. Citations use **one-based physical PDF pages**, which sometimes differ from printed page numbers. Chinese passages are paraphrased in English.

## What this collection supplies

The extracted ZIP contents comprise 91 files: 73 PDFs and 18 CAD/archive/metadata files. There are no standalone kernel source trees, C driver files, bootloader executables or firmware images among those extracted entries. Nested RAR member inventories describe CAD files already represented in the expanded directories; this is not an independent decompression test. The [inventory](../allwinner/INVENTORY.json) records file hashes and ZIP integrity results. A filename ending in `.bin` inside a PDF is a source-location lead, not an included binary.

The R16 Android and Tina download guides describe a vendor-account/public-key approval process before accessing separate software repositories. They establish how customers obtained code in 2015, not present access rights or availability. No SDK commands were executed and no historical SDK download hosts were contacted. [R16 SDK download guide, PDF pp. 1–4][sdk-download]; [Tina download guide, PDF pp. 1–4][tina-download].

Two archive members failed ZIP CRC verification. This report does not rely on the recovered A33 IIC guide or the unreadable R16 Ubuntu installation manual; it uses the valid R16 IIC counterpart. Integrity and completeness are separate from whether a PDF viewer happens to open a file. [Inventory](../allwinner/INVENTORY.json).

## The historical SDK is a map, not the new base

The R16 Tina quickstart specifies `linux-3.4`, `sun8iw5p1`, `brandy/u-boot-2011.09`, and Android-style `bionic`, `frameworks`, `lunch` and BSP extraction. Its configuration menu separates Android, DragonBoard, Linux and Tina targets. The A33 quickstart similarly separates Android userspace from a `lichee` tree. Thus the name *Tina* in this package does not establish a current, maintained distribution candidate. [R16 Tina quickstart, PDF pp. 4–6][tina-start]; [A33 quickstart v3, PDF pp. 4–6][a33-start].

The Lichee guide identifies potentially useful future source locations: `brandy/basic_loader` for boot0, `brandy/u-boot-2011.09`, `linux-3.4`, and board configurations under `tools/pack/chips/sun8iw5p1/configs`. Its Linux root filesystem is generated through Buildroot. These explain the vendor implementation boundaries and would help locate a missing behavior if authentic SDK source becomes available. They are not paths present in this document collection. [R16 Lichee guide, PDF pp. 4–8][lichee].

Some content is generic or copied across platforms. The R16 Lichee tree example lists `arisc_sun9iw1p1.bin`; that different platform identifier cannot be treated as a supplied or suitable R16 firmware. The Android porting guide cites a `linux-3.3` keyboard path despite the quickstart's Linux 3.4 baseline. Resolve such discrepancies against actual source and hardware before implementing anything. [Lichee, PDF p. 5][lichee]; [R16 Android porting, PDF p. 14][porting].

## Configuration should become explicit hardware relationships

The vendor `sys_config.fex` model groups boot clocks, supplies, pins, display timing, USB roles, radio power and DVFS into one configuration. That helps enumerate the responsibilities a modern board description must cover; it does not make the FEX examples GameShell wiring specifications. For example, the MMC example uses PB4 card detect, whereas the existing CPI3 DT uses PB3. [R16 System Configuration, PDF pp. 6–7 and 33][sysconfig]; [CPI3 DT](../../GameShell/Code/Kernel/v0.6/515_dts.patch).

The pinctrl guide distinguishes mux selection, bias, drive strength and output state, and explains that the vendor framework matches pin mappings to device names. **Design implication:** document these dimensions for every GameShell pin in its default and sleep states; represent ownership and dependencies through current DT/pinctrl/GPIO interfaces. Merely translating register numbers or copying vendor device names would lose that context. [R16 pinctrl guide, PDF pp. 5 and 8–11][pinctrl].

The U-Boot configuration-editing guide explicitly excludes parameters already consumed by boot0, including DRAM settings. **Design implication:** each tunable needs an owning boot stage. A Linux DT correction cannot retroactively fix early DRAM training, and a U-Boot environment setting is not automatically a runtime power policy. [U-Boot system-configuration guide, PDF pp. 4 and 8][uboot-config].

## Display and backlight: more precise validation questions

The LCD configuration separates framebuffer format, panel timing, signal polarity/phase, RGB666 dithering, gamma, backlight enable and panel power. This supports the earlier decision to treat scanout, panel control and backlight as distinct responsibilities within a coordinated lifecycle. It also reinforces that an eight-bit framebuffer channel does not establish eight physical color wires. [System Configuration, PDF pp. 25–28][sysconfig-display].

The hardware checklist says PD has its own supply domain and requires the panel's I/O voltage to match it; it also calls for a pull-down on the backlight enable input. These are useful checks for off-state behavior and unwanted illumination during boot or suspend. They describe the reference design, not proof that CPI3 follows it. The supplied guides do not identify GameShell's KD027 controller or provide its exact initialization/shutdown protocol; that remains an independent gap. [R16 schematic checklist, PDF p. 7][checklist-display]; [original display investigation](08-driver-and-board-support.md).

Boot-stage display code is specifically located under `u-boot-2011.09/drivers/video_sunxi/sunxi_v2`. If later source inspection reveals a reset or initialization sequence absent from Linux, this is a useful lead for explaining warm-boot-only success. Linux should still own a complete tested panel lifecycle. [R16 Tina quickstart, PDF p. 6][tina-start].

## Radio support: shared supplies are real, examples are not universal

The system-configuration guide describes up to three radio supplies with voltage fields, a power switch, chip enable and an optional system 32 kHz clock. The older Wi-Fi guide separates the network driver from power/GPIO helpers such as `arch/arm/mach-sunxi/rf/wifi_pm.c` and `wifi_pm_ap6xxx.c`; firmware and NVRAM installation are additional responsibilities. **Design implication:** preserve that separation using current regulator, clock, reset/power-sequence and `brcmfmac` interfaces, and investigate any missing shared-resource support before inventing a new network driver. [System Configuration, PDF p. 41][sysconfig-radio]; [R16 Wi-Fi guide, PDF pp. 6–7 and 12–13][wifi-guide].

A particularly relevant trap: the Wi-Fi guide's DLDO1/DLDO2/DLDO4 example is explicitly for **RTL8723BS**. It demonstrates a three-supply integration, but cannot establish AP6212's supply topology or justify the historical CPI3 always-on declarations. The Broadcom examples separately require module-specific supply/control handling and a powered, interrupt-capable host-wake pin if wireless wake is wanted. Our agreed power-button-only wake policy removes the wireless-wake requirement; it does not remove the need to restore the module correctly. [Wi-Fi guide, PDF pp. 12, 18 and 31–32][wifi-guide].

The one-page R16 and A33T support tables were visually inspected. Neither lists AP6212. R16 marks AP6210 as sample-tested; the A33T table marks it as supported from its datasheet. Those categories are different evidence, and absence from an old list does not mean an unlisted module cannot work. Neither table validates GameShell's actual AP6212 revision, firmware or calibration. [R16 wireless list, PDF p. 1][r16-radio-list]; [A33T wireless list, PDF p. 1][a33-radio-list].

The hardware checklist adds electrical checks for module/SoC I/O voltage agreement, UART/SDIO pull-ups, reset/power/wake routing and antenna matching. Use these to review the actual CPI schematic and board; do not substitute the tablet reference design for it. [R16 schematic checklist, PDF p. 9][checklist-radio].

## I²C, USB and input: useful boundaries

| Evidence | Consequence for GameShellNeo |
| --- | --- |
| R16 IIC troubleshooting distinguishes a bus stuck low from an address receiving no acknowledgement; an unpowered peripheral can hold a bus low. [PDF p. 19][iic] | When gating peripheral supplies, inspect bus bias and powered/unpowered signal relationships. An I²C timeout after resume need not be fixed by adding arbitrary delays. |
| The hardware checklist puts PL in the always-powered VCC-RTC domain and reserves PL0/PL1 for PMIC communication. [PDF p. 4][checklist-pmic] | Preserve the PMIC bus and wake path when creating sleep pin states. The generic IIC guide does not override GameShell's identified RSB PMIC connection. |
| USB configuration distinguishes device/host/OTG roles, ID/VBUS detection and host initial state. [System Configuration, PDF pp. 36–38][sysconfig-usb] | Audit external USB gadget and internal keypad-host power separately. The guide supplies no macOS Ethernet compatibility proof; that remains a configfs/ECM/NCM device test. |
| The “input driver adaptation” guide scans I²C touchscreen/sensor addresses and IDs, then records a module for loading. [PDF pp. 4–5][input] | It is not a replacement for GameShell's USB HID keypad driver. Avoid importing tablet autodetection into a single known-board image. |
| The Android porting guide describes an ADC resistor-ladder keyboard that cannot distinguish combinations. [PDF pp. 14–15][porting] | This limitation belongs to that reference input design. It must not be attributed to GameShell's separate USB keypad MCU. |

## Frequency, audio and performance claims

The DVFS chapter labels an “extremity” overclock setting separately from normal bounds. Its example includes 1.536 GHz at 1.5 V and 1.2 GHz at 1.32 V. These are **example vendor settings, not qualified CPI3 operating points**. Retain the modern upstream OPP baseline and verify regulator ownership and stability before considering frequency/voltage changes. [System Configuration, PDF pp. 56–57][sysconfig-dvfs]; [modern CPU assessment](08-driver-and-board-support.md).

The A33 audio parameter guide distinguishes analog and digital gains, headphone circuitry, speaker-amplifier control and auxiliary audio interfaces. That supports explicitly holding the amplifier inactive while playback is deferred; neither a zero volume nor omission of an audio application establishes power removal. Its reference gain values are not calibration for GameShell's speakers or amplifier. [A33 audio parameters, PDF pp. 2–3][audio].

The Android 4.4-to-L comparison identifies CMA, ART-related memory pressure and first-boot processing, including much longer first starts than later boots. Those are observations about the vendor Android software stack, not an R16 minimum boot-time limit or evidence against GameShellNeo's target. They strengthen the requirement to measure first provisioning, ordinary cold boot, visible readiness and network readiness separately. [A33 release differences, PDF pp. 5–7][release-diffs].

## Resulting research priorities

1. Reconcile actual CPI3 rails, I/O domains and wake pins with the reference-design constraints before changing power states.
2. Identify the exact LCD controller and finish the panel/backlight off-and-recovery specification.
3. Identify the installed radio revision, firmware/NVRAM and real supply/clock dependencies; qualify reset and power removal independently of association.
4. Keep a source-lead list for boot0, boot-stage display and vendor power helpers if authentic SDK source later becomes available. The documents already provide useful leads; obtaining the obsolete stack is not a prerequisite for every modern driver task.

The new material improves our questions and electrical cross-checks. It supplies neither a complete SDK nor a tested modern GameShell port. The existing recommendation—small, evidence-backed additions to maintained Linux with measured behavior—continues to fit the evidence.

[sdk-download]: <../allwinner/extracted/R16/代码下载编译环境搭建/R16 SDK下载说明v1.0.pdf#page=1>
[tina-download]: <../allwinner/extracted/R16/代码下载编译环境搭建/R16 tina SDK下载说明v1.0.pdf#page=1>
[tina-start]: <../allwinner/extracted/R16/代码下载编译环境搭建/R16_Tina SDK Quick Start Guide.pdf#page=4>
[a33-start]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33_Tablet SDK Quick Start Guide_V3.pdf#page=4>
[lichee]: <../allwinner/extracted/R16/Firmware/R16_lichee使用手册.pdf#page=4>
[porting]: <../allwinner/extracted/R16/Firmware/R16_Android快速移植指南.pdf#page=14>
[sysconfig]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=6>
[pinctrl]: <../allwinner/extracted/R16/Firmware/R16_pinctrl接口使用说明书.pdf#page=5>
[uboot-config]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/uboot阶段修改系统配置使用文档.pdf#page=4>
[sysconfig-display]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=25>
[sysconfig-radio]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=41>
[sysconfig-usb]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=36>
[sysconfig-dvfs]: <../allwinner/extracted/R16/Firmware/R16_System Configuration说明书.pdf#page=56>
[wifi-guide]: <../allwinner/extracted/R16/Firmware/R16 WiFi移植说明书.pdf#page=6>
[r16-radio-list]: <../allwinner/extracted/R16/Hardware/R16支持列表/R16_WiFi&BT&GPS支持列表-V1.00.pdf#page=1>
[a33-radio-list]: <../allwinner/extracted/Allwinner A33 Development Materials/Hardware/A33支持器件列表/A33T WiFi&BT&GPS支持列表.pdf#page=1>
[checklist-display]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(原理图部分)_V1_0.pdf#page=7>
[checklist-radio]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(原理图部分)_V1_0.pdf#page=9>
[checklist-pmic]: <../allwinner/extracted/R16/Hardware/硬件设计Check list/R16 checklist(原理图部分)_V1_0.pdf#page=4>
[iic]: <../allwinner/extracted/R16/Firmware/R16_IIC驱动开发说明书.pdf#page=19>
[input]: <../allwinner/extracted/R16/Firmware/R16 input驱动自适应使用书.pdf#page=4>
[audio]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33 audio参数配置说明书.pdf#page=2>
[release-diffs]: <../allwinner/extracted/Allwinner A33 Development Materials/Firmware/A33 5 1对比4 4差异说明.pdf#page=5>
