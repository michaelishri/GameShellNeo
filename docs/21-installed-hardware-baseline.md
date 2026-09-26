# First inspection of the owner's running GameShell

Inspection date: **27 September 2026, Pacific/Auckland**. This is the first direct, read-only observation of the owner's installation. It supplements the source research in reports 01–20. Credentials were read from the local `.env`; they are not included in this report or the diagnostic captures. No firmware, kernel, packages or device configuration were changed, and no reboot, suspend or battery-discharge test was requested.

## Access established

The Intel development host can log into the GameShell directly over its existing Wi-Fi connection. The Mac initially refused TCP port 22; after Remote Login became available and the owner supplied its credentials, SSH login to the Mac succeeded. The Mac itself reports **macOS 26.5.1, build 25F80, arm64**, confirming the earlier owner-provided version.

An initial SSH forwarding test succeeded through the Mac to the GameShell's **Wi-Fi address**. After the owner connected another cable and reported the Mac's accessory-approval screen appearing, a separate SSH test succeeded through the Mac to the GameShell's **USB address**. The intended development access path is now verified.

| Path | Observed result |
| --- | --- |
| Intel → GameShell Wi-Fi (`192.168.1.116`) | SSH login and read-only collection succeeded |
| Intel → Mac (`192.168.1.152`) | SSH login succeeded using the owner-supplied credentials |
| Intel → Mac SSH forwarding → GameShell Wi-Fi | A second SSH session returned the expected GameShell kernel version |
| Intel → Mac SSH forwarding → GameShell USB (`192.168.10.1`) | SSH login succeeded; session endpoints and routing confirm USB, and the host key matches the known GameShell |

The developer-created SSH key under `.local/ssh` was not needed for password authentication; its public-key installation was not assumed to have occurred. `.env`, `.env.*` and `.local/` are excluded from version control. Raw diagnostic captures and reference binaries are kept in the private local directory `GameShellNeo/.local/hardware-baseline/2026-09-27/`.

## Observed system and hardware

| Item | Direct observation | What it establishes |
| --- | --- | --- |
| Operating system | Debian GNU/Linux 9, Stretch | The actual installed userspace is older than the later images discussed in the research |
| Physical board revision | Owner reports **CPI v3.1** printed on the mainboard | Confirms the sole initial hardware target; this is an owner observation, not a software inference |
| Kernel | `4.14.2-clockworkpi-cpi3-g638f2a7`, built 10 December 2018 | Exact running kernel identity |
| Device-tree model | `Clockwork CPI3` | Software's board identity; not proof of the physical PCB revision |
| Compatible strings | `clockwork,clockworkpi-cpi3`, `allwinner,sun8i-a33` | Confirms the installed A33-family board description |
| CPU | Four ARMv7 Cortex-A7-class cores; CPU part `0xc07` | Four cores are visible to Linux |
| Memory | Approximately 1 GiB installed; `MemTotal: 1030056 kB` | Establishes the memory visible to Linux; memory-package markings remain outstanding |
| PMIC | Boot log identifies AXP223 over RSB at 3 MHz | Confirms the PMIC driver identification used in the research |
| Storage | 15,931,539,456-byte microSD, reported as `SC16G` | Current working card is nominally 16 GB; this does not identify the spare card |
| Display | Connected/enabled DRM output with `320x240` mode | Driver reports an active local display; no visual or electrical test was performed |
| Backlight | Raw backlight device, maximum 9, current brightness 1 | Existing brightness interface is exposed; no brightness value was changed |
| Keypad | USB HID device `4242:e131`, named `rancidbacon.com UsbKeyboard` | Keypad enumerates; physical MCU identity and key behavior remain unverified |
| Power key | `axp20x-pek`, event device present | Existing PMIC input path enumerates; no button test was performed |

The running DT's memory region begins at `0x40000000` and has size `0x3ffb5000`, 300 KiB below a full 1 GiB. Linux then accounts for its own reservations, including a logged 64 MiB CMA region. These are observed reservations, not evidence of a smaller physical memory package or a decoded DRAM timing configuration.

## Power-management baseline

The kernel exposes `/sys/power/state` as `freeze mem`, but `/sys/power/mem_sleep` contains only **`[s2idle]`**. Therefore the presence of `mem` is not evidence of a platform deep-suspend implementation in this installation. No sleep state was entered.

The CPU uses `cpufreq-dt` with the **`performance` governor**, a current and maximum frequency of **1,008,000 kHz**, and advertised frequencies from 120,000 to 1,008,000 kHz. No CPU0 cpuidle state directory or current idle-driver result was exposed by the queried paths. That observation does not by itself recover the kernel's build-time configuration.

The running DT names DCDC3 `vdd-cpu`, fixes its bounds to **1.2 V**, and supplies no `cpu-supply` property on CPU0. DCDC5 is described as the always-on **1.5 V** DRAM rail. Several radio, audio and other supplies are also described as always-on. This confirms that the previously identified configuration issues are present in the owner's installed DT, rather than merely in repository examples. DT constraints are not independent voltage measurements. [Earlier source audit](08-driver-and-board-support.md).

Two ordinary charging snapshots were collected while Wi-Fi/SSH was active and USB supplied power:

| Property | Initial snapshot | Later snapshot |
| --- | --- | --- |
| Battery presence | Present | Present |
| Status | Charging | Charging |
| Reported capacity | 44% | 60% |
| Battery voltage | 4.111 V | 4.137 V |
| Reported battery current | +278 mA | +295 mA |
| USB supply | Present and online | Present and online |
| Reported USB `current_max` | 900 mA | 900 mA |

The initial battery readout also reported `health=Good`, `constant_charge_current_max=1200000` µA and `voltage_min_design=2900000` µV. These are reported status/configuration values, not pack specifications, measured USB current, usable capacity, or proof of safe charging limits for the replacement cell. The exact capture times are retained in the local evidence where available. Collection activity and charging varied; this was **not an endurance, calibration or charge-rate benchmark**.

The modern setter defect in [report 18](18-pmic-history-and-suspend-contract.md) was traced in much newer Linux code. This observation of an old kernel's read-only `current_max` property does not establish that the same setter regression exists here. No current-limit or charge-current write was made.

## USB networking: initial failure and successful connection

**Current result:** USB Ethernet and SSH through the Mac work. The initial diagnosis below records the earlier failure; the successful repeat test follows it.

The installed image already has useful USB-network configuration:

- `g_ether` is bound to the MUSB gadget controller.
- `usb0` is administratively up and configured as `192.168.10.1/24`.
- The existing DHCP server configuration serves `192.168.10.10`–`192.168.10.250` on `usb0`; the service is active and listening on UDP port 67. SSH is active and listening on TCP port 22.

However, the actual data path did not enumerate:

- UDC state: `not attached`; current speed: `UNKNOWN`; `usb0` carrier: `0`.
- MUSB role state: `b_idle`; VBUS reported on.
- PHY extcon reports `USB=1`, `USB-HOST=0`, consistent with peripheral-side power detection.
- The Mac's IOUSB registry showed its two host controllers without attached USB-device children, and no new GameShell Ethernet interface.
- The Mac routed attempts to `192.168.10.1` through its ordinary Wi-Fi default route, with no successful connection.

The owner tried another cable; the immediate repeat inspection still showed no enumeration. Neither cable's data capability was confirmed, and the owner identified a USB-A-to-C adapter in the path. A read-only Mac console-state query initially returned `IOConsoleLocked=true`. The owner subsequently unlocked the Mac and reconnected; no accessory prompt appeared. A repeat query confirmed `IOConsoleLocked=false`, but both ends still showed no USB enumeration. Unlocking therefore did **not** resolve this connection. Apple documents that charging can continue without granting USB data access, but the lock state is not established as the cause here. [Apple USB accessory guidance](https://support.apple.com/en-gb/102282).

The owner subsequently confirmed that a USB flash drive works through the adapter. This makes a general Mac-port/adapter failure less likely, while neither GameShell cable's data capability has been independently established. A further read-only configuration audit found:

| Check | Observation | Interpretation |
| --- | --- | --- |
| Controller and PHY device-tree nodes | Enabled; A33-compatible MUSB/PHY; `dr_mode=otg` | The board description enables the required hardware |
| MUSB runtime power management | Active; no recorded runtime-suspended time | The controller is not runtime-suspended |
| MUSB `POWER`, at `0x01c19040` | `0xe0` | Software connection (`SOFTCONN`) and high-speed enable bits are set; suspend bit is clear |
| MUSB `DEVCTL`, at `0x01c19041` | `0x99` | B-device/peripheral state, VBUS-valid indication and session bit; host-mode bit clear |
| MUSB interrupt enable, at `0x01c19050` | `0xf7` | USB reset interrupt is enabled |
| PHY `ISCR`, at `0x01c19400` | `0x0f03f000` | D+/D− and ID pull-up controls are enabled; ID/VBUS inputs are forced high by the driver's detection mechanism |
| MUSB interrupt count | Zero on all CPUs since this boot | No USB controller interrupt was recorded despite the earlier reconnects |
| USB device address | Zero; UDC still `not attached` | No completed host enumeration was observed |

The register inspection used read-only mappings and made no register writes. Offsets and bit meanings were checked against Linux **v4.14.2**, the installed kernel's upstream base: [sunxi register mapping](https://github.com/gregkh/linux/blob/v4.14.2/drivers/usb/musb/sunxi.c), [MUSB bit definitions](https://github.com/gregkh/linux/blob/v4.14.2/drivers/usb/musb/musb_regs.h), [gadget connection handling](https://github.com/gregkh/linux/blob/v4.14.2/drivers/usb/musb/musb_gadget.c), and [PHY detection/pull-up handling](https://github.com/gregkh/linux/blob/v4.14.2/drivers/phy/allwinner/phy-sun4i-usb.c). The forced PHY inputs are software state, not independent electrical measurements. PMIC USB-presence telemetry separately reports power present.

An empty configfs gadget directory is expected here: the image uses the legacy built-in `g_ether` driver. ClockworkPi's checked-in [USB patch](../../GameShell/Code/USB-Ethernet/usb_ethernet.patch) enables both ECM and RNDIS; it does not establish a RNDIS-only setup. The DHCP service logs a deprecated `INTERFACES` setting but automatically migrates it and starts successfully. Neither detail explains the missing USB enumeration.

**Initial conclusion:** no missing USB-network enable setting was found. The failure preceded IP addressing, DHCP and SSH. Those checks alone could not exclude a controller/PHY driver fault or identify a cable/connector fault. No gadget reset, role change or persistent configuration change was made.

Private captures of the initial audit include `usb-configuration-audit.json`, `usb-control-registers.json`, `usb-phy-control.json`, `usb-network-services.json` and `mac-usb-config-audit.json` in the baseline directory.

The Mac's `system_profiler SPUSBDataType` returned no output, so that result alone was not treated as proof. The diagnosis also uses `ioreg`, interface state, routing and the GameShell controller's own state. Internet Sharing was not enabled or changed.

### Successful repeat test, 27 September 2026 at approximately 08:10 NZDT

Following another cable change and the owner-reported accessory-approval screen, the repeat inspection found:

- The Mac enumerates `RNDIS/Ethernet Gadget` and has an active `en7` interface at `192.168.10.21/24`. Its route to `192.168.10.1` uses `en7`.
- The GameShell UDC is `configured` at `high-speed`; `usb0` has carrier `1` and address `192.168.10.1/24`.
- Despite the generic product name, the GameShell log explicitly identifies the selected configuration as **CDC Ethernet (ECM)**.
- An authenticated SSH connection from the Intel host, forwarded through the Mac to `192.168.10.1:22`, succeeded. The SSH host key matched the key already observed over GameShell Wi-Fi.
- Inside that session, `SSH_CONNECTION` identified the Mac's USB address `192.168.10.21` and the GameShell's USB address `192.168.10.1`; the return route used `usb0`. The hostname and kernel matched the expected device.

No GameShell or Mac network configuration change was required during this test. The working connection establishes that the installed gadget configuration and macOS can interoperate. Cable replacement and accessory approval were not tested independently, and device uptime also indicates a new boot since the earlier audit, so the evidence does not isolate a single cause of the original failure. Repeated reconnect and sleep/resume reliability remain untested.

The successful captures are `mac-usb-new-cable.json`, `gameshell-usb-new-cable.json` and `usb-jump-host-success.json`. USB addresses/interface names are observations from this connection, not permanent assignments for every host or boot. Serial-console qualification and a recoverable development card remain important before bootloader or deep-sleep experiments.

## Serial adapter identification

The owner reports an unmarked adapter with four separate black, green, red and white leads. After connecting only its USB end to the Mac, the following appeared:

| Property | Observation |
| --- | --- |
| Manufacturer string | `Prolific Technology Inc.` |
| Product string | `USB-Serial Controller` |
| USB VID:PID | `067b:2303` |
| Device revision descriptor | `0x0300` |
| macOS serial callout device | `/dev/cu.usbserial-110` |

This identifies an interface in the PL2303 family; [Prolific's driver documentation](https://www.prolific.com.tw/portfolio-item/pl2303gs/) lists `067b:2303` among its supported IDs. It does not establish the exact cable model, chip authenticity/revision, lead assignments or signal voltage. macOS has created a serial device, but transmitting/receiving has not been tested. The adapter's loose leads remain disconnected from the GameShell. Electrical compatibility and the board connector's orientation still need verification before wiring.

The owner subsequently supplied a wire mapping: red = +5 V, black = GND, white = RXD, green = TXD. This is recorded as owner-supplied information; its source and applicability to the exact cable are not yet confirmed. A 5 V power lead does not establish the UART signal voltage. The serial adapter's power lead is unnecessary when the GameShell has its own power supply.

The owner then supplied `http://www.prolific.com.tw/US/ShowProduct.aspx?p_id=229&pcid=41` as the product reference. The URL returned HTTP 404 during this investigation. Prolific's own [PL2303HXD datasheet, page 8](https://web.mit.edu/6.111/volume2/www/f2019/handouts/pl2303v1_4_4.pdf) identifies that exact URL as its historical **Mac driver download**. It therefore does not identify the purchased cable's electrical implementation. That datasheet also describes a separate serial-I/O supply and multiple signal-voltage options; this is an example of why a chipset-family match is insufficient, not proof that the inspected adapter contains the HXD revision. The next outstanding check is the cable's actual signal voltage through suitable measurement or cable-specific documentation. No driver installation is required merely to make a serial port appear: macOS already exposes one.

**Subsequent evidence resolves the missing product-documentation lead:** the owner supplied the actual Banggood product 1055396 listing. Its original page and linked Raspberry Pi wiring guide have been recovered from archives, supporting intended use with a 3.3 V UART. The owner also reports successful use of this cable on an Orange Pi Zero. [Report 22](22-serial-cable-and-console-preparation.md) records the source chain, the distinction from the supplied PL2303GT datasheet, and the limits of this documentary qualification. This supersedes the earlier suggestion to assume a replacement adapter was needed. The owner has no multimeter; actual output voltage remains unmeasured.

The remaining serial issue is the physical connection: the owner notes that the GameShell connector is smaller than the adapter's individual sockets and is unsure whether the original expansion harness is available. Identify that harness and its orientation before connecting any leads. No purchase or GameShell serial connection has been made. Serial setup is now deferred; source preparation, the first-build specification and initial base work can proceed without it under [the updated implementation plan](20-base-implementation-plan.md).

The private captures are `mac-serial-adapter-baseline.json` and `mac-serial-adapter-connected.json`. The latter USB tree contains the serial adapter but no GameShell USB gadget; it does not retest simultaneous USB Ethernet and serial operation. Device node names can change with the USB port used.

## Boot artifacts preserved locally

The card uses a DOS/MBR partition table with 512-byte sectors:

| Region | Start sector | Sector count | Observed use |
| --- | ---: | ---: | --- |
| Before first partition | 0 | 8,192 | MBR and bootloader area; copied in full as 4 MiB |
| Partition 1 | 8,192 | 85,623 | FAT16 boot filesystem; 43,838,976 bytes |
| Partition 2 | 94,208 | 31,022,080 | Mounted ext4 root filesystem |

Both partition entries use MBR type `0x83`, even though the first filesystem is FAT16. Preserve the observed map; it should not be treated as a new image layout recommendation. The SPL `eGON.BT0` signature is present at the expected **8 KiB offset**, with a declared SPL image length of **24,576 bytes**. Bootloader strings identify **U-Boot 2018.01-rc1-00118-gd19ddc958a**, dated 10 December 2018. A serial boot log is still needed to observe its actual startup and memory-training output.

The boot partition was **not mounted or written on the GameShell**. Its bytes were copied read-only and FAT16 directories were inspected locally. It contains:

- `boot.scr`
- `uImage`
- `sun8i-r16-clockworkpi-cpi3.dtb`
- `sun8i-r16-clockworkpi-cpi3-hdmi.dtb`

The script loads `uImage` at `0x48000000`, the non-HDMI DTB at `0x49000000`, and boots without an initramfs. Its arguments include serial output, `earlyprintk` and `no_console_suspend`. `/boot` in the running root filesystem is empty because the actual boot partition is not mounted there; this is not evidence that boot files are missing.

| Saved reference | SHA-256 |
| --- | --- |
| First 4 MiB of card | `612bb05276a1d0b5242dddcef9f5937b3623195acb4af290f67872e98f972f0e` |
| Entire boot partition | `bde8eff0bf62801fc2d19e7819d1758500f72d9d7077e724d8c860067719612b` |
| Running DTB | `2e2f56e1b80186e9efe5af617a4d321796c5e93bc8677a01a0fd759cb0b4bb38` |
| Boot `uImage` | `6070cab0a0aa9b506735f2a20abdabc1288bd38ee54805de1e94369061e5ff27` |
| Boot non-HDMI DTB | `8e634037b780b2f969c0e0e24a40e6f9dd014f4da32b39dfc5aac913a28ce9a1` |

The local manifest records sizes, hashes and source commands. These files are **not a full-card backup**: the root filesystem, settings and user data have not been backed up. Do not use this capture alone as assurance that reflashing the original card is recoverable.

**Repository identity confirmed:** the copied `uImage` and both boot DTBs match the files under [the local `Code/Kernel/v0.2` directory](../../GameShell/Code/Kernel/v0.2) byte-for-byte by SHA-256. That directory's 548,864-byte `u-boot-sunxi-with-spl.bin` also exactly matches the card bytes starting at offset 8,192. This ties the installed boot artifacts to a specific local reference set; it does not identify the complete root filesystem as an unmodified v0.2 OS release or recover every build option.

`/proc/config.gz` was unavailable. A read-only local inspection of the compressed kernel found no embedded `IKCFG_ST` configuration marker. The matching kernel and bootloader build configurations, exact DDR parameters and fitted memory-part identification therefore remain follow-ups.

## Radio and startup observations

The live SDIO device reports vendor/device ID **`02d0:a9a6`** and uses `brcmfmac`. The kernel explicitly requests **`brcm/brcmfmac43430a0-sdio.bin`** for chip 43430 revision 0 and reports firmware `7.46.57.4.ap.r4`, dated 8 October 2016. This identifies the selected firmware family; it does not independently read the radio module's physical marking.

Both 43430 and 43430a0 firmware/NVRAM pairs and two Bluetooth HCD files were copied into the private reference directory, with exact source paths and hashes in `radio-manifest.json`. The selected 43430a0 binary hashes to `bb2bd00ede1fe04c74d3684e76ef58d9f2acd54d6759894b934bbefb159668e9`; its companion text file hashes to `5f977a2a3916ef795ceb184cf928231d587249606d1750dacecb5f16ed941ae6`. The text file's presence is confirmed, while the log did not explicitly name the selected NVRAM file. No adjacent license file was found by the bounded firmware-directory search; redistribution terms still require provenance work.

`systemd-analyze time` reports **2.711 s kernel + 9.400 s userspace = 12.111 s** for the current boot. This excludes unmeasured pre-kernel startup and does not identify the moment the display or launcher became usable. It is a useful software startup observation, **not a measured power-button-to-ready cold-boot time**.

Twenty-five services were running, including Wicd, Bluetooth, Samba, two AirPlay-related services, ModemManager, snapd and the USB DHCP server. MPD was failed. The boot log also reports a panel dummy-supply fallback and an unavailable `autofs4` module. Earlier deferred probes eventually resolve; their presence alone is not a permanent device failure. These observations provide inputs for a minimal new image; no service was stopped or removed.

## What this enables next

The remote software baseline, original boot-reference capture and intended Intel → Mac → USB SSH access test are complete. The owner has confirmed the physical mainboard marking as CPI v3.1. We can now prepare the first-build specification against observed hardware/software rather than assumptions. Memory/keypad/battery identification and repeated USB reconnection remain open checks. Recovery preparation is still needed before testing a new image on the spare card; serial setup is deferred and is not a prerequisite for the first-build specification or initial base tests.

Detailed outstanding activities are recorded in [FOLLOW-UP.md](../FOLLOW-UP.md). The staged implementation remains [report 20](20-base-implementation-plan.md). Hardware retention, sleep reliability, voltage behavior, current-limit enforcement, usable battery capacity and endurance are all still untested.
