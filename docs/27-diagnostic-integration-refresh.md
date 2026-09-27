# Diagnostic image integration refresh — NEO-7

Date: 27 September 2026. Target: the owner's CPI v3.1. This work produces
`0.1.0-diagnostic.2` with Linux `6.18.54-gameshellneo2`. The development card
passed full-image readback and its first boot. Integration checks passed on the
owner's explicitly accepted AU-advertising access point; NZ-only operation and
broader hardware reliability remain follow-ups.

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
  The live control/deny/allow-exception tests below verify enforcement on the board.
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
| networkd warns that `usb0` may be unpredictable | The existing network file matches the kernel-assigned gadget name. The warning appeared in the previous baseline too. The first refreshed boot creates `usb0` and establishes high-speed ECM automatically; repeat reconnect testing remains under NEO-5. |
| MMC cannot read a write-protect switch | The removable microSD path has no described switch; the driver assumes writable media. No write-protect hardware should be invented. |
| `rdinit=/init` not found | This image intentionally boots without an initramfs and proceeds to `/sbin/init` on root. The captured log shows that handoff succeeding. |
| Board-specific Broadcom filename / CLM fallback | Preserve the working locked generic firmware and board NVRAM. Missing optional names are not a reason to substitute an unqualified binary. The live country events and channel limits are recorded below; independent firmware-country qualification remains a follow-up. |

Sources for that classification are the pinned Linux tree:
`arch/arm/kernel/topology.c`, `drivers/of/device.c`, `drivers/mfd/mfd-core.c`,
`drivers/pinctrl/sunxi/`, `drivers/usb/musb/sunxi.c`,
`drivers/usb/phy/phy-generic.c`, and the AXP power/ADC drivers. The local
Clockwork mainboard schematic's power tree and CPU page were inspected; the
drawing is evidence of the reference design, not a physical measurement of the
owner's board.

## Build and flash validation

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
| Hardware qualification | First boot and integration comparison passed for the accepted test setup; broader NEO-5 acceptance remains open |

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

The owner then returned the DEV card to the GameShell, connected USB to the
Mac, powered it on and reported the login screen. The following results are
from that single boot.

## First refreshed boot and integration results

| Check | Observed result |
| --- | --- |
| Image and kernel | `0.1.0-diagnostic.2`, `6.18.54-gameshellneo2`, CPI v3.1 identity |
| USB access | Authenticated SSH through the Mac; ECM configured at high speed, with no live USB correction needed |
| Wi-Fi access | Direct authenticated SSH works; one interface-specific wpa_supplicant process, global and D-Bus services masked |
| Required services | All six active, zero restarts, no failed systemd units |
| Kernel | Four cores, about 1000 MiB visible RAM, zero taint |
| Display/input | Owner sees login console; framebuffer 320×240, backlight active, USB keypad enumerated as `4242:e131`; button functionality was not exercised |
| Journal ACL | Actual `user-1000.journal` has a named-user read ACL and read mask for UID 1000; the previous unsupported-ACL error is absent |
| BPF enforcement | Temporary IPv4 loopback control connects; `IPAddressDeny=any` blocks the same listener (connect errno 11); `IPAddressAllow=localhost` permits it again |
| Unprivileged BPF | Disabled (`kernel.unprivileged_bpf_disabled=2`) |
| Hostname and obsolete rules | Hostname remains `gameshellneo`; previous DHCP Access Denied, ALSA-rule and missing-SysRq warnings are absent |
| Regulatory database | Upstream alternatives selected, cfg80211 loaded as a module, no database load/signature errors; NZ and subsequent AP country events are observed |
| Telemetry | Battery reports 100%, Charging; USB input-limit readback 900000 µA. These are software readings, not battery-health or electrical-current measurements |

### Country announcement from the access point

The saved configuration is `country=NZ`. The boot journal records:

```text
01:50:42 CTRL-EVENT-REGDOM-CHANGE init=USER type=COUNTRY alpha2=NZ
01:50:44 CTRL-EVENT-REGDOM-CHANGE init=COUNTRY_IE type=COUNTRY alpha2=AU
```

The associated access point's cached beacon advertises `Country: AU`, explaining
the resulting global AU domain. The owner confirmed having moved from Australia
and explicitly requested leaving the AU setup as it is. Neither the AP nor the
device's saved NZ provisioning was changed during validation. The Linux
[regulatory processing documentation][country-ie] describes country information
elements as regulatory hints on association; the journal/beacon evidence above
establishes what happened on this boot.

`iw reg get` also reports the driver's custom `phy#0` domain as `99`; this is not
proof of a firmware ISO country code. The actual wiphy exposes 2.4 GHz channels
1–13 with reported maximum 20 dBm, with channel 14 disabled. No 5 GHz hardware
capability is inferred from the generic custom-domain rules. NZ-only operation,
firmware-country readback/mapping and eventual launcher region policy remain
in `FOLLOW-UP.md`; this boot is not marked as NZ radio qualification.

### Boot timing and scope

| Measurement | Previous image | Refreshed image |
| --- | --- | --- |
| Kernel | 2.456 s | 2.457 s |
| Userspace completion | 19.783 s | 19.752 s |
| systemd total | 22.239 s | 22.209 s |
| Local readiness marker | about 17.166 s | 17.177 s |

These are single-boot observations, exclude the legacy bootloader, and show no
meaningful speed improvement. This is the first cold start of the refreshed
candidate; the prior image's boot does not complete its repeatability sequence.
Remaining driver warnings match the classified baseline above. No new failed
device/service was identified.

### Repeatable validation and evidence

The new host-side task uploads a temporary checker, runs its privileged checks,
then removes it. BPF probes use a local-only listener and disposable systemd
services; their filters affect only the probe cgroups. This does not change
production services, Wi-Fi configuration or the installed image.

```sh
task device:status ROUTE=usb
task device:logs ROUTE=usb
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
```

The last command passed all six groups: identity, services, database/policy,
journal ACL, BPF enforcement and country. Omitting `ACTIVE_COUNTRY=AU` was also
tested: it correctly returned a failure for expected NZ versus observed AU,
preserved the evidence and removed the temporary helper. The explicit override
records the accepted test condition; it does not suppress country checking.
The existing 25 Python regressions, C selector cases and shell lint still pass.

Private evidence:

- Status: `.local/diagnostics/20260927T015114.768930Z/status.txt`.
- Boot archive: `.local/diagnostics/20260927T015114.768271Z/device.tar.gz`.
- Detailed review: `.local/diagnostics/neo7-first-boot-review.txt`,
  `neo7-radio-investigation.txt` and `neo7-integration-details.txt`.
- Passing integration run: `.local/diagnostics/20260927T020246.670661Z/integration.json`.
- Expected country-mismatch failure: `.local/diagnostics/20260927T015800.449067Z/integration.json`.

NEO-7's implementation and boot comparison are complete for this accepted setup.
NEO-5 remains open for repeated cold starts/reconnections, actual control/display
tests and power/stability qualification. Its original-card backup is verified
on both hosts in [report 28](28-original-card-recovery-backup.md). Sleep,
battery-life qualification and the boot-speed target remain later milestones.

[regdb-files]: https://packages.debian.org/trixie/all/wireless-regdb/filelist
[regulatory]: https://kernel.org/doc/html/v6.7/networking/regulatory.html
[networkd]: https://raw.githubusercontent.com/systemd/systemd/v257/man/systemd.network.xml
[sysctl]: https://raw.githubusercontent.com/systemd/systemd/v257/man/sysctl.d.xml
[country-ie]: https://wireless.docs.kernel.org/en/latest/en/developers/regulatory/processing_rules.html
