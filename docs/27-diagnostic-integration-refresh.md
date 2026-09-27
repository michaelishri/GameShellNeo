# Diagnostic image integration refresh — NEO-7

Date: 27 September 2026. Target: the owner's CPI v3.1. This work produces
`0.1.0-diagnostic.2` with Linux `6.18.54-gameshellneo2`. The development card
is now flashed with a matching full-image readback; its first boot and physical
integration checks remain pending.

## Baseline and implemented corrections

The original diagnostic card remained running during development. A fresh
status capture showed the six required services active/successful, zero
restarts, no failed units, and zero kernel taint. USB SSH through the Mac and
Wi-Fi SSH worked. These are observations of the original boot, not additional
cold-boot or reconnect tests. Private captures are in `.local/diagnostics/`,
including `20260927T000415.959213Z`, `20260927T000415.591989Z` and `neo7-*.txt`.

### Wi-Fi country, database availability and signing key

The owner explicitly confirmed **New Zealand (`NZ`)**, and requested a future
launcher region selector. The current image gets its country from
`GAMESHELL_WIFI_COUNTRY` in the ignored `.env`. Provisioning requires an explicit
two-letter uppercase value, writes `country=` into the private wpa_supplicant
configuration, and preserves the existing machine and SSH identity when the
country changes. Launcher configuration is recorded in `FOLLOW-UP.md` and is
not implemented here.

The initial report described `regulatory.db` as absent. Further inspection
corrected that diagnosis: `wireless-regdb 2026.05.30-1~deb13u1` was installed,
but built-in cfg80211 attempted to load the file before the root filesystem
was mounted. The boot log places that failure before `VFS: Mounted root`.
The database's selected alternative also used Debian's signature, while the
custom upstream kernel embeds the upstream maintainer keys.

The refresh builds cfg80211 as a module, so its database request happens after
root is available, and explicitly selects the package's upstream-signed
database/signature pair with `update-alternatives`. Signature verification
remains enabled in the kernel. Offline image checks now verify the selected
links and cryptographic signature using only certificates shipped in the
locked Linux source; embedded signer certificates are not accepted as trust
anchors. A check against files copied read-only from the running board accepted
the upstream signature and rejected the Debian-only signer.

The package's installed `README.Debian` explicitly prescribes the upstream
alternative for custom upstream kernels. Its [package file list][regdb-files]
includes both variants. The [kernel regulatory documentation][regulatory]
describes firmware-file loading; the exact load order is established by the
captured boot log and locked `net/wireless/reg.c`, including
`regulatory_init_db()` and its built-in late initcall.

### Kernel and userspace policy

- Enable ext4 POSIX ACLs so journald can apply its per-user journal permissions.
- Enable the BPF syscall, cgroup BPF and ARM BPF JIT needed by systemd's shipped
  IP-address isolation policies. Unprivileged BPF remains disabled by default.
  Runtime attachment and effective isolation still need validation on the board.
- Set `UseHostname=no` for DHCPv4 and DHCPv6, retaining the fixed `gameshellneo`
  hostname without trying to change it through hostnamed. This setting's
  semantics are documented in [systemd's versioned network manual][networkd].
- Retain `wpa_supplicant@wlan0`; disable and mask the unused global service and
  its D-Bus alias. The baseline had two processes, one interface-specific and
  one global. Provisioning continues to use the interface's control socket.
- Exclude `alsa-utils` from this audio-disabled image. The installed package's
  restore rules had references to an absent label; audio packages and rules
  must be revisited when audio support is implemented.
- Override the distro SysRq keyboard setting with a failure-tolerant zero
  setting because this diagnostic kernel does not provide SysRq. Other distro
  sysctls are preserved. The [sysctl.d format][sysctl] defines the leading `-`.
- Extend diagnostic collection with warning-level journal messages, effective
  Wi-Fi regulatory state, and required/global Wi-Fi service states.

No charger programming, firmware blobs, voltage limits, bootloader, device-tree
power wiring, suspend support or partition layout is changed by this refresh.

## Remaining driver messages: classification

These messages remain visible. They are not counted as resolved merely because
the first boot worked.

| Message | Source-level explanation and disposition |
| --- | --- |
| CPU nodes lack `clock-frequency` | ARM topology's legacy capacity calculation reads this property after no explicit capacity value is found. The four homogeneous Cortex-A7 cores retain their default equal capacity; operating frequencies come from cpufreq/OPPs. Do not invent a fixed frequency to hide the message. Explicit capacity description can be considered separately. |
| `vcc-pl` and `vcc-pf` use dummy regulators | The board description lacks these bank-supply links. The schematic power tree identifies PL with the RTC rail, while the live regulator report confirms dummy consumers. The PF bank supply needs corroboration independently of the SD card's supply. Model the PMIC/RSB/pinctrl dependency sequence before adding links, especially because the PMIC bus itself uses PL pins. This remains a power-model follow-up. |
| AXP ADC/battery/AC/USB child devices lack a DMA mask | Generic OF DMA configuration warns and supplies a fallback mask for the MFD-created platform children. These PMIC paths perform register/RSB and IIO operations; no failed DMA transaction is evidenced. Retain the message and consider an upstream bus/MFD fix rather than inventing DMA hardware in the board description. |
| Generic USB PHY cannot use a dummy exclusive VBUS supply | sunxi MUSB registers a generic legacy transceiver. `phy-generic.c` explicitly accepts an absent optional VBUS-draw regulator and continues with a null handle. The separate sun4i generic PHY supplies the actual PHY path. High-speed ECM works; do not add an output VBUS regulator to the external peripheral port. |
| Static GPIO base deprecated | Existing upstream sunxi pinctrl allocation. A migration is separate from board functionality and does not justify another local patch just to remove a diagnostic. |
| MMC cannot read a write-protect switch | The removable microSD path has no described switch; the driver assumes writable media. No write-protect hardware should be invented. |
| `rdinit=/init` not found | This image intentionally boots without an initramfs and proceeds to `/sbin/init` on root. The captured log shows that handoff succeeding. |
| Board-specific Broadcom filename / CLM fallback | Preserve the working locked generic firmware and board NVRAM. Missing optional names are not a reason to substitute an unqualified binary. Country application and effective limits still require a physical check. |

Sources for that classification are the pinned Linux tree:
`arch/arm/kernel/topology.c`, `drivers/of/device.c`, `drivers/mfd/mfd-core.c`,
`drivers/pinctrl/sunxi/`, `drivers/usb/musb/sunxi.c`,
`drivers/usb/phy/phy-generic.c`, and the AXP power/ADC drivers. The local
Clockwork mainboard schematic's power tree and CPU page were inspected; the
drawing is evidence of the reference design, not a physical measurement of the
owner's board.

## Validation and next physical session

Host regressions and lint pass, including explicit-country validation, rejection
of injected configuration text, and identity preservation across country
changes. The refreshed kernel compiled successfully; all 132 requested Kconfig
assertions and the 15-file kernel artifact inventory passed. Its zImage SHA-256
is `a1570f9d64260d70a5f9236252cd630673e2c6b5de74a90ee438e2fb7b52bf23`.
The DTB remains byte-for-byte identical to the first build:
`8280b127316f641aab60a1d341832adfc4fbc7cec3ae65a559bbd33224b40cd4`.

Device-tree bindings and the compiled board DTB validated without diagnostics.
The fresh Debian bootstrap and image assembly completed successfully through
`task build:image`; the offline contents/filesystem checks passed. The resulting
private artifact is:

| Property | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.2-cpi31-d3458c373a42.img` |
| Size | 4,294,967,296 bytes (4 GiB) |
| SHA-256 | `d3458c373a4281f12e424b8e3448da2f55c21309d34f2fa70b4a90b4b5eb21d8` |
| Compressed transfer bytes | 264,295,865 |
| Compressed SHA-256 | `0a4f1317e749b107a511baec5e91b93545e078aebbd714667e47ef703cf1a2a2` |
| Kernel | `6.18.54-gameshellneo2` |
| Hardware qualification | Pending; DEV-card flash/readback passed, first boot remains pending |

Checks covered the partition boundaries and bootloader readback, FAT16/ext4
integrity, U-Boot image CRCs/addresses, kernel/DTB/module/radio hashes, private
identity permissions, exact provisioned country/Wi-Fi configuration, the
upstream regdb alternative and signature, interface/global Wi-Fi unit policy,
and absence of the unused ALSA restore rules. The installed regulatory package
remains `2026.05.30-1~deb13u1`; `alsa-utils` is absent. The full host suite passed
25 Python regressions, C current-selector tests, Bash syntax and ShellCheck.

Private artifacts, package inventory and verification records are under
`.local/artifacts/`; build logs are under `.local/build/`. `task mac:stage`
completed: the Mac independently verified both compressed and decompressed
image sizes/hashes. The private image and `transfer.json` are staged under
`~/.local/share/GameShellNeo/`. No card was written by that task. These checks
do not establish physical behavior.

### Verified DEV-card flash

After the owner moved the DEV card into the Mac reader, `task mac:status` and
`task mac:inspect DISK=disk16` freshly identified the 64,013,467,648-byte
external physical USB card with its existing `armbi_boot` FAT16 volume and
diagnostic Linux partition. The separate original card had already been backed
up and ejected. The temporary `disk16` identifier must be rechecked for any
future write.

`task mac:preflight` passed the source checksums and recorded-card identity.
`task mac:flash DISK=disk16` then unmounted and revalidated the target, wrote
all 4,294,967,296 image bytes, flushed them, and read back the full image range.
The readback SHA-256 exactly matched
`d3458c373a4281f12e424b8e3448da2f55c21309d34f2fa70b4a90b4b5eb21d8`.
The Mac successfully ejected the card. Private evidence is under
`.local/diagnostics/20260927T014027.581733Z/`: `flash.log`, `flash-result.json`,
`target-before-flash.json` and `transfer.json`.

This verifies the written image bytes, not a boot or the behavior of the new
kernel and services. The next owner action is to return the DEV card to the
powered-off GameShell, reconnect USB to the Mac, and boot it.

After booting the candidate, compare against the saved baseline:

1. Confirm image identity, `6.18.54-gameshellneo2`, display, USB and Wi-Fi SSH.
2. Check that cfg80211 loads its signed database and the requested global
   country is `NZ`; inspect the radio's own effective regulatory restrictions
   separately. Successful SSH alone does not establish correct country behavior.
3. Check journald ACL creation after a user login, and systemd BPF policy support.
4. Verify only the interface Wi-Fi daemon runs, DHCP preserves the hostname,
   and the obsolete ALSA/SysRq messages have disappeared.
5. Capture warnings and boot timing; retain the classified driver messages in
   the report and investigate any new failure.

NEO-7 remains open for that comparison. NEO-5's original-card backup is now
complete and verified on both hosts; [report 28](28-original-card-recovery-backup.md)
records that result. NEO-5 still covers repeated cold starts/reconnections,
control/display checks and power/stability qualification. Sleep and the
battery-life/boot-speed targets remain later milestones.

[regdb-files]: https://packages.debian.org/trixie/all/wireless-regdb/filelist
[regulatory]: https://kernel.org/doc/html/v6.7/networking/regulatory.html
[networkd]: https://raw.githubusercontent.com/systemd/systemd/v257/man/systemd.network.xml
[sysctl]: https://raw.githubusercontent.com/systemd/systemd/v257/man/sysctl.d.xml
