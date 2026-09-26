# First diagnostic build validation

Date: 27 September 2026. Target: the owner's CPI v3.1 only.

This report separates host validation from hardware qualification. No new image
has been booted on the GameShell, and no physical card has been overwritten.
The original installation remains the recovery system.

## Kernel gate — passed

- Linux `6.18.54-gameshellneo1`, compiled with GCC 14.2.0 in the digest-pinned
  Armbian amd64 builder, one compile job and disk-backed scratch.
- Full kernel, modules and project DTB compiled successfully. Final `zImage`:
  **5,513,296 bytes**; CPI3 DTB: **23,684 bytes**.
- **125** resolved Kconfig assertions passed. Suspend/hibernate and deferred
  features are disabled; root-storage drivers, display/input and thermal
  sensing are built in. USB gadget and Wi-Fi modules are installed separately.
- The completed-stage manifest covers **13** kernel/module files and binds
  them to the fragment and exported project patch hashes.
- The patch queue applied cleanly to files extracted from the locked Linux
  archive. The actual AXP selector helper passed compiled regression cases for
  AXP192, AXP20x/223, AXP221 and AXP813 tables, invalid/sentinel values, table
  ordering, clamping and integer bounds.
- Bundled **dtschema 2026.9** checked the modified bindings and project DTB with
  no diagnostics. The additional sunxi binding permits standard GPIO hogs that
  the existing GPIO implementation already supports.

The integration audit identified A33's older-named `SUN4I_GPADC` temperature
driver as a required option; `SUN8I_THERMAL` alone would not bind this device.
The corrected kernel was rebuilt and recorded. This establishes that the
driver is included, not that its measurements are calibrated on this board.

## Runtime gate — passed offline

Five host tests pass for consecutive low-battery samples, invalid/absent
telemetry, charging/recovery/gap resets, private identity persistence, encoded
Wi-Fi configuration, restrictive key permissions and conflicting profiles.
ShellCheck 0.11.0 passes the build and runtime shell scripts.

The runtime installer successfully checked the ARM target's SSH (`sshd -t`)
and sudo (`visudo -c`) configuration under emulation. `systemd-analyze verify`
accepted all three project units. This validates configuration and executable
availability, not service behavior on the board.

## Image gate — passed offline

The completed private bundle is in `.local/artifacts/`, including the image,
`verification.json`, `SHA256SUMS`, kernel configuration, source/patch manifests,
the target's **303 package records**, builder package inventories and logs.

| Property | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.1-cpi31-750fb8829d41.img` |
| Size | 4,294,967,296 bytes (4 GiB) |
| SHA-256 | `750fb8829d41af96ed58db1b5e5cf6a9051799436bb69740c973afd9656e33ad` |
| Partition layout | Exact locked MBR entries, offsets, sizes and boot flag |
| Bootloader | Byte-for-byte hash readback at the 8 KiB offset |
| Filesystems | FAT16 and ext4 checks passed without modifying the image |
| Boot payload | Legacy U-Boot header/data CRCs, kernel load/entry addresses, script and root PARTUUID passed |
| Installed drivers | Kernel, DTB and module hashes match the completed kernel stage |
| Radio | Firmware and board-specific NVRAM hashes match the locked private inputs |
| Access and service policy | Provisioned identity, private file modes, enabled project units and disabled sleep checked |

The image contains the owner's Wi-Fi access and a device SSH private host key.
It stays under ignored `.local/`; only source and reports are pushed to GitHub.
The image filename and hash identify this particular personalized build, not
a promise of bit-for-bit reproducibility across new identities or timestamps.

The builder uses Debian 13 armhf from signed, hash-checked dated snapshots.
Armbian assembles a separately verified kernel stage. Debian's own base-files
and OS identity are retained; GameShellNeo identity is `/etc/gameshellneo/image.json`.
Locally built rootfs cache reuse requires matching content and construction
inputs; remote rootfs artifacts are disabled.

Host integration fixes include explicit ARM emulation registration for the
builder's modern binfmt packaging and creation of image loop-partition device
nodes inside Docker's separate `/dev`. Offline SSH validation uses a temporary
`/dev/null` node, removed afterward, and explicit root ownership and mode 0755
for `/run/sshd`, independent of Armbian's build umask. The final image contains
no builder QEMU executable. These are builder requirements, not device runtime
services.

## Hardware gate — not started

NEO-5 still requires identification of a spare card and reader, a verified
offline backup of the original, and the first physical boot. Serial remains
deferred; revisit it if early boot fails before either network path is usable.

Unqualified behavior includes display/backlight transitions, every keypad
event, USB enumeration/reconnection, Wi-Fi/firmware compatibility, CPU DVFS and
temperature behavior, charging/percentage accuracy, shutdown and endurance.
No cold-boot, sleep/resume latency or battery-life result is claimed.

The first image intentionally retains the upstream AXP223 driver's 50 ms
offline USB-power polling. Measure and improve it in the efficiency phase;
do not mistake a successful image build for the eventual power target. Sleep,
asleep battery protection, OTA and the launcher remain outside this milestone.
