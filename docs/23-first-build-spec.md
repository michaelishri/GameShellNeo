# First diagnostic build specification

Approved 27 September 2026; implementation authorized subsequently. Tracked as
NEO-1 through NEO-5 in Kaneo. This is a build contract, not a hardware success
report. [Requirements](06-base-requirements.md) describe the eventual base;
this milestone deliberately precedes sleep qualification.

## Accepted decisions

- Support only the owner's physically confirmed CPI v3.1.
- Build a diagnostic base first, with system sleep and hibernation disabled.
- Retain the exact proven SPL/U-Boot while replacing Linux and userspace.
- A short power-button press requests orderly shutdown. It will request sleep
  in the later qualified power-policy milestone.
- Privately provision the existing Wi-Fi configuration for fallback access.
- Preserve the original card and use a spare for experiments. Serial is
  deferred; revisit it when missing early-boot or resume evidence blocks work.
- Display/backlight, keypad, power button, Wi-Fi/USB SSH, battery telemetry and
  awake critical-battery shutdown are in scope. Launcher, audio, GPU, HDMI,
  Bluetooth, OTA and deep sleep are out of this diagnostic milestone.

## Frozen construction inputs

[sources.lock.json](../build/sources.lock.json) is the machine-readable authority.

| Input | Pin |
| --- | --- |
| Armbian | `488dc40c493ba7633e379dbcf5606d7d58ee4575` |
| Linux | `v6.18.54`, commit `1b357ecb321392158d507b04672ffee57bfa071d` |
| Kernel configuration | Exact upstream `sunxi_defconfig` plus project fragment |
| Userspace | Debian 13/Trixie `armhf`, minimal, no desktop |
| Debian snapshot | `20260926T202543Z` |
| Security snapshot | `20260926T174359Z` |
| Builder | Official Armbian amd64 container pinned by manifest digest in the lock |
| Compiler | Container's `arm-linux-gnueabihf-gcc`; record version and package inventory |
| Bootloader | Captured `2018.01-rc1-00118-gd19ddc958a`, 548,864 bytes, hash in the lock |

Use the Intel host, one compile/compression job, `KERNEL_BTF=no`, no tmpfs build
tree, and disk-backed scratch. Docker access works; approximately 3.3 GiB RAM
is below Armbian's recommended 8 GiB, so memory feasibility must be measured.
The Mac remains the management jump host.

Fetch source at exact revisions; verify Debian signatures as well as locked
metadata hashes. Limit expiry overrides to dated snapshot sources. Record all
applied patches and final kernel configuration. Use a unique project kernel
patch directory and `EXTRAWIFI=no`, avoiding broad inherited sunxi patches.
The custom configuration hook must neutralize Armbian's queued option changes
before merging the fragment; assert final required and forbidden options.

The output bundle contains the private image, SHA-256 checksums, source/patch
and package manifests, resolved configuration, compiler inventory and logs.
Reproducibility means frozen inputs and a repeatable process initially, not a
claim of byte-identical filesystem images or personalized credentials.

## Boot and storage

| Region | Layout |
| --- | --- |
| Table | MBR, 512-byte sectors, fixed 4 GiB image |
| Reserved prefix | First 16 MiB |
| SPL/U-Boot | Byte 8,192; copy only the locked binary, not the old MBR |
| Boot | FAT16, type `0x0e`, bootable, start sector 32,768, length 262,144 |
| Root | ext4, type `0x83`, start sector 294,912, length 8,093,696 |

Set `BOOTCONFIG=none` and inject the verified binary using the final-image hook
before fingerprinting/compression. Verify the inserted bytes and boundaries.
Disable automatic root expansion. Preserve normal ordered ext4 journaling and
five-second commits, overriding Armbian's writeback/120-second defaults.

Boot script loads `uImage` at `0x48000000` and the CPI3 DTB at `0x49000000`, with
overlap checks. Wrap `zImage` with the known `0x40008000` load/entry address.
Use root PARTUUID and `rootwait`, preserving the existing bootloader's memory,
framebuffer and PSCI handoff. Boot without an initramfs; build root-storage
dependencies into Linux. Framework-generated unused ramdisks can be removed
from the final image. Keep UART console support for future use.

## Hardware implementation

Derive a fresh board DTS from the schematic and captured DT, retaining existing
compatible strings. Use standard sun4i DRM, USB HID, AXP power-key, brcmfmac,
power-supply, regulator and USB gadget interfaces. No legacy private `/proc`
APIs or whole historical patch queues.

- One DRM panel driver owns initialization and blanking. Use `spi-gpio` mode 3,
  MSB-first, two-byte command/data transfers, and the established sequence.
  Keep the known reset level; arbitrary reset pulses and unqualified panel
  rail cycling are excluded.
- Adapt the OCP8178 v4 proposal with explicit CTRL-low shutdown, one-wire
  reinitialization after off, per-device state, and standard backlight controls.
- Link CPU power to the actual regulator; use upstream 120–1,008 MHz operating
  points and `schedutil`, ordinary idle and thermal protection. No overclocking,
  speculative undervolting, DRAM tuning or new firmware power states.
- Use captured BCM43430a0 firmware/NVRAM as private inputs with checked hashes
  and explicit board-specific NVRAM naming. Preserve shared radio supplies.
- Keep the external port in peripheral mode and the keypad host controller
  enabled. Keep deferred peripherals inactive without dropping shared rails.
- Correct the AXP current-limit setter: select the greatest positive supported
  value no greater than the request/clamp, regardless of table ordering; reject
  invalid/below-minimum requests before any register writes. Test real helper
  code across variant tables, sentinels and bounds.

Preserve inherited charger/gauge settings; do not add automatic current tuning.
Configured current is not measured USB current. An awake guard shuts down at
the provisional 10% threshold after three consecutive valid discharging samples
ten seconds apart. Invalid telemetry reports degraded monitoring; it must not
be interpreted as a full battery or a valid low reading. Pack calibration and
asleep protection remain unqualified. Deliberate endurance testing requires
valid telemetry and supervision until battery margins are established.

## Runtime and access

Use direct systemd-networkd/resolved plus wpa_supplicant configuration. USB CDC
ECM provides `192.168.10.1/24`; serve DHCP only on USB, advertising neither router
nor DNS. Wi-Fi uses DHCP and private provisioning. Neither network readiness
nor Internet availability may delay local diagnostic readiness.

Use hostname `gameshellneo`, account `cpi`, public-key SSH and development sudo.
Install the existing development public key, a distinct per-device SSH host
identity and an independently recorded fingerprint. Never copy old host keys
or embed `.env`. Keep credentials and personal firmware under ignored `.local/`,
out of logs and tracked inputs. Personalized images are private.

Provide a local diagnostic readiness marker, bounded persistent journals and
a collection command for image identity, device status, power readings and
kernel logs. Logind handles short-press shutdown. No automatic sleep or suspend
firmware is enabled. Standard Linux device interfaces are the public contract;
there is no launcher API in this milestone.

## Acceptance and recovery

Host gates: checked sources, clean patch application, configuration assertions,
targeted DT validation, driver/policy regression tests, compiled kernel/DTB,
exact image layout/bootloader bytes, filesystem checks and artifact manifests.

Hardware gate NEO-5 requires an offline verified backup of the original card,
an identified spare (assume at least 8 GB) and a compatible reader. Never guess
a physical disk target. Preserve the original as the recovery card.

- Ten consecutive cold starts, four CPUs and expected memory; working local
  display/input, Wi-Fi SSH and USB SSH.
- Ten USB reconnections; no-access-point boot remains locally usable.
- All buttons and release events, backlight levels and repeated off/on.
- CPU/memory/storage load without faults, frequency transitions and shutdown.
- Simulated critical/invalid telemetry, actual charging/unplugging transitions
  and supervised battery operation.
- Separate local/network readiness timings and repeatable unplugged awake-idle
  readings, with uncertainty and exact test conditions recorded.

No cold-boot, standby or resume numerical target gates this diagnostic image.
Failures before networking may require serial; recover with the original card
or reflash only the spare before reassessing diagnostics.

## Source references

- [Pinned Armbian family](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/config/sources/families/include/sunxi_common.inc), [configuration hooks](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/lib/functions/compilation/kernel-config.sh), [image hooks](https://github.com/armbian/build/blob/488dc40c493ba7633e379dbcf5606d7d58ee4575/lib/functions/image/rootfs-to-image.sh).
- [Linux release](https://github.com/gregkh/linux/tree/1b357ecb321392158d507b04672ffee57bfa071d), [kernel checksums](https://cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc).
- [Debian snapshot](https://snapshot.debian.org/archive/debian/20260926T202543Z/dists/trixie/InRelease), [security snapshot](https://snapshot.debian.org/archive/debian-security/20260926T174359Z/dists/trixie-security/InRelease).
- [OCP8178 v4 submission](https://lkml.iu.edu/2608.3/04616.html), [full OCP8178 datasheet mirror](https://en.visvie.com/static/upload/file/20220902/1662097252339999.pdf): 16 pages, SHA-256 `d7a4b4ac3317cec166a682799eb91e98ee25e583faf8068e317fb2471155aec2`; specifies >2.5 ms CTRL-low shutdown and re-entry to one-wire after shutdown. Exact hardware behavior still needs testing.
- [Installed baseline](21-installed-hardware-baseline.md), [driver audit](08-driver-and-board-support.md), [PMIC setter analysis](18-pmic-history-and-suspend-contract.md).
