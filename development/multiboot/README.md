# Development SD-card systems

NEO-208 prepares multiple diagnostic systems on one card for driver development.
This is opt-in tooling. Normal image construction does not install the loader,
selector, catalog or administration scripts. The final release will not carry
this development arrangement. See [report 292](../../docs/292-development-sd-systems.md)
for evidence and outstanding board qualification.

## Storage and selection

The development image retains the verified MBR/SPL/U-Boot prefix, original FAT
boot partition and byte-identical recovery root partition. A third ext4
partition stores `systems/<version>/{root,boot,release.json}`. Each version has
its own complete root, settings, kernel modules, kernel, DTB and external
initramfs. Private identities stay on ext4. Games, saves and settings are not
shared between versions.

The fixed FAT `boot.scr` reads `next.scr` and `good.scr`. A different NEXT is a
one-shot trial: before executing it, the loader rewrites NEXT from GOOD and
checks the actual readback. A successful trial must be explicitly confirmed
from that running root. Normal confirmed boots do not rewrite the flag.
A missing, damaged or returning descriptor enters the fixed recovery system.
Recovery uses its own old kernel, DTB and unchanged root partition.

The three flag entries (`next.scr`, `good.scr`, `recover.scr`) must have unique
lowercase names. Mount the boot partition as `vfat` with `shortname=mixed`;
the administration tool rejects incompatible mounts and case aliases. The
2018 writer downcases its lookup but compares directory names case-sensitively,
so an uppercase-only entry can produce a duplicate instead of a replacement.
An older development card needs a verified migration or a corrected reflash.
Migration must move each old entry to a distinct backup name before creating
its fresh lowercase replacement; atomic replacement alone can retain the old
uppercase directory entry. Report 292 records the original failure, actual
writer regression fixture, reviewed migration and board qualification.

A reset after an unconfirmed trial returns to the confirmed system. A complete
hang still needs a reset or separately qualified watchdog. FAT writes are not
power-cut atomic, and sharing a card and boot filesystem leaves common failure
modes. No product OTA, signed-update service or automatic health policy is
provided here.

## Prepare an image

Use `task dev:busybox -- --help`, `task dev:initramfs -- --help` and
`task dev:card -- --help` for current options. Arguments after `--` are parsed
as data; Task does not evaluate them as shell code. BusyBox is authenticated
against signed Debian snapshot metadata and the development dependency lock.
The initramfs builder verifies the static ARM ELF and needed applets through
the builder's ARM emulator. Card assembly verifies its archive and source-pin
receipt; an x86 test loader cannot be installed as the ARM loader.
Use `--builder` with `dev:initramfs` for the pinned offline ARM builder.

The card command requires explicit recovery/system raw image paths and SHA-256
pins, a verified ARM `uInitrd` with its `.json` sidecar, a fresh `.img` output
under this checkout's ignored `.local`, and a fresh lowercase version name.
Without `--build` it reports the proposed layout. With `--build` it operates
only on regular image files in the locked, network-disabled builder, checks all
three filesystems and compares every recovery-root byte. Choose `--bytes` for
the desired MiB-aligned image size (default 8 GiB, minimum 6 GiB); the physical
card must be at least that large. It does not resize a physical card.

Before installation, use the established fresh DEV-spare identity, original-card
preservation, backup/checkpoint, guarded write, full readback and ejection
procedure. A new partition layout needs the initial reflash already agreed by
the owner. No source image or device is modified by preparation.

`task dev:pack -- --image <development.img> --receipt <development.json>
--output <fresh-private-transfer-directory>` validates the completed development
receipt and creates a separate gzip transfer. Existing output directories are
rejected, including production transfers and recovery checkpoints. For the
8 GiB image, the guarded write/readback/eject budget is 2168 seconds; the
ordinary image's 900-second default is unchanged and the development bound is
3600 seconds. Oversized images whose conservative budget exceeds that bound
reject.

Use the **new checkout's** Mac Tasks with both environment values set:
`NEO_HARDWARE_CHECKOUT=<established-hardware-checkout>` and
`NEO_DEVELOPMENT_TRANSFER=<fresh-private-transfer-directory>`. The new helper
reuses existing credentials/keys/known-host records in place and stages into a
receipt-addressed development directory. `mac:stage` skips production packing
only with that explicit development selection; `mac:inspect`, `mac:preflight`
and `mac:flash` retain target identity, mount veto, full readback and ejection.
All actions must use the same explicit selection. Before transferring the large
archive, establish that the current connection is ordinary Wi-Fi rather than
assuming an old hotspot/network answer is still valid.

## Import and switch over SSH

The image places the administration tree at `<store>/admin`. When running a
directory system, the complete store is mounted at
`/run/gameshellneo-store`; the boot filesystem must also be mounted read/write
as `vfat` with `shortname=mixed` at an explicit path, such as `/mnt/devboot`.
In recovery, mount the store
separately using its recorded PARTUUID. Check `DEVBOOT.JSON` on both mounts.

These commands run **on the GameShell** as root through the established pinned
SSH connection. Substitute the actual mounted boot/store paths. The examples
use a newly uploaded, complete version bundle and its independently known
SHA-256. Prepare that bundle on the build machine:

```sh
task dev:bundle -- --image <raw-image> --sha256 <raw-image-sha256> \
  --system diag27 --store-partuuid <card-store-partuuid> \
  --initramfs .local/multiboot/uInitrd --output .local/multiboot/diag27.tar
```

It uses host loop mounts and retains the image's complete metadata.
The GameShell kernel has loop devices disabled;
its bundle import needs only Python, GNU tar and the mounted store.
The running kernel/filesystem must also support every required xattr, including
`CONFIG_EXT4_FS_SECURITY=y` for Debian file capabilities. The importer probes
the exact required capability values before extraction. The original
diagnostic.25/26 kernels lack this option; first bootstrap a capable maintenance
system from an offline-prepared complete filesystem. NEO-210's opt-in
`dev:store:pack` / `dev:store:install` path has passed the real inactive-store
replacement from fixed recovery, with a complete verified backup; see
[report 294](../../docs/294-development-store-bootstrap.md). A regular complete
card image remains the physical-flash fallback. Older kernels can then be imported
and tested from that capable system. Keep a capable maintenance version
available for later full-metadata imports.

The installed prototype uses a 4 GiB store on the 64 GB DEV spare; the remaining
card capacity is unallocated. Ordinary imports do not resize partitions. The
opt-in `dev:store:backup` / `dev:store:grow` workflow is being qualified to use
that space from fixed recovery, with a fresh full off-device checkpoint; see
[report 295](../../docs/295-development-store-expansion.md). Its default growth
command is read-only; `--apply` is a separate owned offline operation and
`--status` observes the original job without resubmitting it. The
bootstrap leaves an empty catalog and recovery selected; register its verified
inactive release with the normal `register` command, then select a trial
separately. Its real diag27 trial preserves the exact capability value and
returns NEXT to the confirmed recovery descriptor. A subsequent complete
diag25 import, directory-root trial and next-boot return to fixed recovery also
pass. Confirmation still requires
the checks below; registered input-device names alone do not prove button
response.

```sh
python3 /run/gameshellneo-store/admin/tools/dev-systems.py \
  --boot /mnt/devboot --store /run/gameshellneo-store status

python3 /run/gameshellneo-store/admin/tools/dev-systems.py \
  --boot /mnt/devboot --store /run/gameshellneo-store \
  import-bundle diag27 --bundle /run/gameshellneo-store/incoming/diag27.tar \
  --sha256 <verified-bundle-sha256>

python3 /run/gameshellneo-store/admin/tools/dev-systems.py \
  --boot /mnt/devboot --store /run/gameshellneo-store select diag27
```

Host preparation verifies the image, root/modules/kernel match and boot assets.
Device import verifies the whole bundle and safe archive paths, preserves
ownership/modes/links/xattrs, and publishes a fresh version without selecting
it. Failed imports leave the prior selected system alone. A complete imported
directory whose registration was interrupted can be registered with
`register diag27`. Existing version names cannot be replaced. The upload needs
room for the upload, a private verified archive snapshot and extracted version;
remove an upload only after
checking its successful import and retained provenance.

Selection never reboots. Use the existing warned `task device:reboot` from the
hardware-access checkout for an authorized selector test. Clock/PM captures
still need their separate deployment and clock admission.
After observing the correct boot and checking display, inputs and both required
management routes, `confirm diag27` sets the default. It verifies the running
root inode, early-userspace marker and exact kernel. `recovery` queues the fixed
recovery system without replacing the confirmed default. `status` validates the
catalog and reports next and confirmed versions.

Original image manifests/fstab are retained beside each imported release. The
copied image manifest explicitly records a `development-directory` deployment
and the store PARTUUID, and root/boot fstab entries are removed from the copied
root. Strict clock/PM tools must continue to reject this different deployment
until their separate provenance adapter and matching qualification are ready.
Importing or confirming a version does not resolve NEO-192 or qualify sleep.
