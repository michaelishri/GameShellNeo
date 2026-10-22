# Development SD systems (NEO-208)

22 October 2026. The owner requests multiple complete systems on the large
development card, selectable for the next boot, and accepts the initial
reflash. This is for development only; the final release will not include it.
The [commands and operational contract](../development/multiboot/README.md)
describe the opt-in tooling. No device/card write or reboot is part of the
offline preparation recorded here.

## Layout and boot contract

The existing 4 GiB diagnostic.25 image supplies the reserved SPL/U-Boot prefix,
MBR disk identity, original FAT boot filesystem and unchanged recovery root.
The builder appends only partition 3, an ext4 store, at sector 8388608 and
extends a new regular `.img` file (default 8 GiB). It validates the exact
bootloader SHA, original geometry, all filesystem checks, reserved prefix and
every byte of the recovery root. Source images are mounted read-only.

| Region | Development use |
| --- | --- |
| Reserved first 16 MiB | Existing R16 SPL/U-Boot at 8192 bytes; no environment update |
| p1, sectors 32768–294911 | Shared fixed dispatcher, 8.3 selection descriptors, versioned kernel/DTB/initramfs bundles |
| p2, sectors 294912–8388607 | Original fixed recovery system with its own kernel and DTB |
| p3, sector 8388608 onward | Complete `systems/<id>/{root,boot,release.json}` and administration tools |

The pinned vendor bootloader is `2018.01-rc1-00118-gd19ddc958a`, SHA
`d7154f264edfed57fe00e2dcbfe30c0c876b3e6a8a6e2ae5bcf7b84d470a208c`.
Its command strings include FAT loading/writing, `iminfo`, `source`, compare and
integer operations. This is capability evidence; the shell model does not
execute that vendor binary. Its upstream v2018.01-rc1 reference source is
`9da7fb4a39149c3061cb148bfbaa76b4b52b9008`, not an assertion that the vendor
fork is byte-for-byte upstream.

`NEXT.SCR` different from `GOOD.SCR` is a trial. The dispatcher validates bounded
legacy ARM script images and CRCs, retains NEXT in RAM, writes GOOD back to NEXT,
reads it back and compares exact length/bytes before sourcing the trial.
Unchanged confirmed descriptors incur no write. A returning or invalid path
enters fixed recovery and cannot resume the vendor's outer USB/PXE/DHCP search.
The vendor's executing main script buffer at `0x43100000` is preserved;
NEXT/readback/GOOD/recovery occupy separate windows. Kernel, DTB and initramfs
loads are bounded to nonoverlapping RAM staging windows at
`0x48000000`, `0x49000000` and `0x4a000000`.

Recovery fallback requires another boot after an unconfirmed kernel hang;
the flag supplies no reset by itself. No qualified bootcount/watchdog is
assumed. The old FAT implementation can reallocate a file's cluster chain, so
readback is not power-cut atomicity. All versions still share the card, FAT and
first boot stage. Retain the original recovery/checkpoint and physical reflash
path.

## Root handoff and import

The existing board kernel supports external initrd/gzip, ext4 and MMC. Its
loop device driver is disabled. A minimal external initramfs mounts virtual
filesystems, resolves the unique store PARTUUID through sysfs within ten
seconds, validates the selected real directory and exact marker/kernel, binds
the root, moves mounts and executes `switch_root`. Debian's absolute and
usrmerge init symlinks are resolved inside the selected root. Missing or
ambiguous devices and damaged roots stop before handoff.

Raw images are extracted on the build host. Read-only admission validates
original board identity, source lock/kernel release, ARM zImage, module
vermagic, DTB and optional keypad baseline hashes. Root import preserves
ownership, modes, timestamps, xattrs, ACLs, hardlinks, symlink text and device
nodes without following symlinks. Sockets and nested filesystems reject.
Original image/fstab bytes remain as provenance. Only copied identity/fstab
and the development marker change. Old USB experiment boot-policy identities
are explicitly unsupported; standard policy and the validated suspend flag are
preserved.

The host prepares a complete-version pax TAR for loop-free transfer. Device
import checks its SHA, paths and link topology before private extraction and
target store identity before publication, then registers its boot bundle. The current
selection is unchanged until explicit `select`. Existing system names cannot
be replaced. Root/boot/module inputs remain paired, and each version has its
own settings and private identities. `confirm` requires the actual running root
inode, early-userspace record and exact kernel, not merely a version argument.

The copied manifest says `development-directory`, records original image and
manifest hashes, and names p3. It must not pass an existing pristine-image
admission check by changing labels or dropping checks. The clock/PM provenance
adapter and subsequent awake qualification remain separate software/hardware
work; NEO-192 is unresolved. Recovery diagnostic.25 is management-bootable with
the existing recorded clock fault; its preservation is not a PM health claim.

## Evidence

The authenticated loader uses Debian snapshot `20260926T202543Z`,
busybox-static `1:1.37.0-6+b9` armhf, package SHA
`8b35210e08d559ecc0ddb660dd96f6f9694f69eb27f1dc608f5eeda56d94509e`,
static ARM ELF SHA
`0a58280553462be5d8064f510a8abceef2610fb549d82f52027bcfc9cbdf9d1d`.
Signed InRelease, package-index and package hashes are pinned in the separate
development dependency lock. `verify_u_initrd` checks header/payload CRC,
bounded gzip/newc, complete entries/modes, actual static ARM ELF, dependency
pins and source receipt. A native x86 fixture cannot satisfy ARM admission.

The final ARM uInitrd SHA is
`55751e885199c397fe1d19e741586f81cdf82a92b3d2b1da36ee0f841681dcb4`;
its sidecar SHA is
`c9ea85eeb2abf12b26890da327d6b6a8c3d164ba8f04171c29751e8a14ee3061`.
The saved builder mode runs the required applets under `qemu-arm-static`.

An isolated actual native-kernel fixture selected a real ext4 loop partition
by sysfs PARTUUID, moved mounts and started an absolute usrmerge `/sbin/init`
as PID 1. The unchanged `/init` also rejected a bad marker, symlinked root,
init-link loop and missing store (9.26 seconds). Test-only mount shims provide
namespace-local command line and console after real mounts. This is native
handoff evidence, not a CPI kernel/DTB or vendor bootloader execution claim.
The final result is `.local/build/dev-initramfs-handoff/8b2abcaf840440d1ad72d6abe54cb501/fixture/result.json`,
SHA `86dafe193e6fa9cb40a712e3f3bd53b584db16c282a3c85cf96eb6feda1c83d8`;
managed run `07c4f25df76b442fa70ff7afabb1ee46` exited 0, no OOM/stop.
The original failed mount-syntax attempt is retained; it led to the supported
BusyBox `--make-rprivate` fix and rerun.

`task test:dev-root` ran 81 tests in the pinned offline container: 75 passed,
six skipped host-BusyBox/native-namespace cases already exercised separately.
The real-root cases preserved mixed uid/gid, device nodes and a named-user
POSIX ACL, as well as hardlinks, xattrs and nanosecond timestamps. The initial
complete-image attempt safely failed when Docker lacked a device node for its
second kernel-allocated loop. Its log/artifact remain; the allocator now checks
the free loop's sysfs identity, materializes its container-local node, attaches
explicitly, and releases it through the context manager.

The generic PM admission regression accepts the ordinary healthy fixture and
rejects an otherwise identical development manifest or `neo.dev` command
line. Its 20 focused checks pass. Older frozen hardware-access worktrees retain
their historical tools; do not use their older PM runners to bypass this guard.

The guarded-transfer adapter passes 60 focused tests, including native C
duration/expiry checks. A fresh private transfer directory and explicit
development receipt avoid changing production archives/checkpoints. An 8 GiB
development image receives a 2168-second mount-veto budget for write/readback
at 8 MiB/s plus 120 seconds, capped at 3600; production retains 900 seconds.
No target/guard/readback/eject check is removed. The new source can reuse the
established hardware checkout's credentials and known-host records in place;
remote development files get a receipt-addressed directory. Local admission
rejects tampering before SSH. Validation is
`.local/build/dev-transfer-validation.json`, SHA
`1c3be827f08a3a862a1810e90731064b56bb46340e29f3e09b82f6f20772fd47`.
No real configuration, network, Mac or device operation was used by these tests.

Card assembly, whole-version transfer qualification, full host regression and
independent final review results are recorded below once complete.

## Remaining acceptance

NEO-208 stays open pending the fresh DEV-spare identity/installation/readback,
actual vendor U-Boot trial consumption/readback, board directory-root handoff,
both management routes, explicit confirmation, subsequent bundle import and
fixed-recovery/reset behavior. The owner moves the card. Use the existing long
speaker warning for any later board reboot. Do not run clock/PM captures until
the explicit deployment adapter and matching admission are ready, and do not
claim power-cut or total-hang recovery from the selector alone.

Primary references: [Linux 6.18 initramfs handoff](https://docs.kernel.org/6.18/filesystems/ramfs-rootfs-initramfs.html),
[U-Boot legacy bootm arguments](https://docs.u-boot-project.org/en/latest/usage/cmd/bootm.html),
[v2018.01-rc1 source command](https://github.com/u-boot/u-boot/blob/9da7fb4a39149c3061cb148bfbaa76b4b52b9008/cmd/source.c),
[v2018.01-rc1 FAT writer](https://github.com/u-boot/u-boot/blob/9da7fb4a39149c3061cb148bfbaa76b4b52b9008/fs/fat/fat_write.c).
