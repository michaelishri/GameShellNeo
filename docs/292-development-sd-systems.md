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

The 8 GiB card assembly completed through managed run
`9b500a28549a4e3ab426b792fd5ec89c`. Artifact
`.local/multiboot/card/GameShellNeo-development-r2.img` has SHA
`630be26098ae5736ff8718a2e2a4608564213a915f8222d87a5bed0200416463`;
its `.json` receipt SHA is
`0505f4c7b250b7c7aaf229522545d3862285978c606397a28c85a8732636cf0f`.
All three filesystems pass, and the reserved bootloader prefix and full p2 are
byte-identical. The store is `b9dab681-03`, recovery `b9dab681-02` with kernel
`6.18.54-gameshellneo24`. The initial NEXT selects `diag26` with matched
`6.18.54-gameshellneo25`; GOOD retains recovery. The source raw hashes are
`c88d158d446b6ed14617b815ec17bfd2b3e90fee858ddd30e008ed74640aeb77`
(recovery diagnostic.25) and
`a4ba84485e9de96d9b92ce0eb6f5ce1958163188c02a315d7f46d1da161c9df8`
(selected diagnostic.26). The generated image remains hardware-unqualified.

The complete `task check` passed: 24 runtime and 1150 tooling tests, five
explicit skips, both compiled selector/mount-guard checks and shell lint.
Root-only and native-handoff skips have the separate evidence above; the two
pre-existing environment-dependent skips remain explicit. Host log SHA is
`d5c19f38822a474135d4faca9479a27df2bdc79ae571650e59c37ccbb00cf674`.
There is no diff to `build/sources.lock.json`, `kernel/patches/` or `runtime/`.

The host prepared `.local/multiboot/bundles/diag25.tar`, 678348800 bytes, SHA
`d1b40e7c333e652904c60c9d7df7fb4412f7411b8ca5568a8bda34b8069adaa4`,
for store `b9dab681-03`. `task check:dev-card` then completed the full import on
a disposable copy, managed run `6190841ff16c4d268d51953ce8923102` (exit 0, no
OOM/stop). The two roots retain their respective kernels. Import left
NEXT=diag26/GOOD=recovery unchanged; selection changed NEXT to diag25; recovery
selection restored NEXT=recovery. The actual copied administration CLI and its
retained loader/source receipt passed. All three copied filesystems pass after
the operations, and the original prepared image still hashes to `630be260...`.
Result `.local/multiboot/card/import-qualification.json` and its managed log
both hash to
`648507319a128538a77ef5dc4e41e031aebe6f84e04846e72bcf67bb6ca4c9ed`.

`task dev:pack` created the fresh private transfer directory
`.local/multiboot/transfer-r2`. Its gzip image is 561002958 bytes, SHA
`6196379abcf4126d4575c44511f1d5451e805dfabe71f81bae2924014f902e19`;
`transfer.json` SHA is
`45978796b8cc5fea684cf9f5cb2c538901ac8985f682fbed018bd0c9480cd116`.
The actual flash helper's source-verification API checked the complete
compressed and decompressed checksums and development receipt on Linux, and
admitted the explicit 2168-second guard. This accesses no card and does not
qualify macOS Disk Arbitration runtime behavior. Verification result SHA is
`e28d3059e7c918743ec0616aac832e76290926db41c900a3d270598bd52c264f`.
Production transfer directories and recovery checkpoints were not selected.

The consolidated private evidence is `.local/multiboot/qualification.json`, SHA
`3d397f58f3a4e984aa310a5170c16eadbe8d7428586c97146828e74d1cb4af39`.
It pins code checkpoint `0d1fd621e48e674f455964daa80e90e119d9f148`, receipts,
logs, both review axes and the remaining qualification limits. The stage
ledger is clear; all owned build sessions completed. Canonical main remains
`a41a0aa` with its original four owner-modified/untracked paths, and the
protected legacy request-resume audit still hashes to
`2e8ed588faa129e9f07edc68d9137e8af684774353ed34233bb9b3932c35310a`.
This feature branch remains open for the physical acceptance below; its saved
worktree, failed first image and original logs are retained.

## Standards review

Independent review of `a41a0aa...0d1fd62` found zero documented-standard
violations and zero actionable smell findings. The code retains managed
ownership, read-only sources, immutable version names, private artifacts,
identity checks and separate registration/selection. The receipt-collision,
SPL admission and recovery manifest/fstab correlation findings are resolved.
The review distinguishes shell-model/native evidence from the vendor/board
checks still outstanding.

## Spec review

Independent review of the same fixed diff found zero missing requirements,
scope-creep findings or incorrect implementations. The development-only
contract covers independent complete roots, matched boot assets/modules,
preserved recovery, consume/readback, explicit confirmation, loop-free import
and guarded flash selection. Production inputs stay separate, and development
roots cannot reuse PM admission. Physical/vendor/board qualification remains
open. Findings: Standards 0; Spec 0.

## Installation preparation, 22 October

The owner freshly confirmed readiness for shutdown/card movement and an ordinary
unmetered connection. Host commit `1c45a30` adds `device:poweroff` using the
existing three-cue, mixer-restoration, same-boot and single-submission gates.
All 33 focused audio/timing regressions pass; independent review found no
actionable defect. The established hardware checkout supplied its existing
private identity and unchanged speaker helper in place; its frozen files were
not edited.

Audio run `21e6e6e50c7f41588f11e1f16b268cf0` completed three level-5, 1000 ms cues
and restored the mixer on boot `2ed25c8e-2e83-4c31-bc31-0b87f38bbbde`. One unique
poweroff timer was accepted. Its original evidence is retained under the
hardware checkout's `.local/diagnostics/20261022T032658.168453Z/`; transport
acceptance alone does not establish physical power-off or human audibility.

The 561,002,958-byte development-r2 archive is staged in the Mac's separate,
receipt-addressed development directory. Compressed and complete 8 GiB
decompressed checksum verification passed. This source-only operation wrote
no card. Private `.local/multiboot/installation/preparation.json`, SHA
`be3ee93819befc5ebeb2f606471cf68b582d07c68b4ac52595d003a16fe3540b`, pins these
observations and the original warning-result hashes. Physical spare identity,
installation and board qualification are separate from this source check.

## DEV-card write and readback

After shutdown the owner confirmed the Samsung DEV spare was in the Mac's
reader. Fresh `mac:status` and `mac:inspect` found one external physical USB
card, temporarily `disk16`, with 64,013,467,648 bytes, 512-byte sectors and
boot-volume UUID `F3C30F83-85C0-3268-ACEE-68029A2BA536`. The original card is
the separately retained 15,931,539,456-byte card. Fresh complete SHA-256 checks
passed for its 6,515,307,882-byte backup archive and the diagnostic.25 recovery
raw image. The original backup, both diagnostic source images and recovery
checkpoints remain preserved.

`mac:preflight` passed full source hashes and the freshly recorded target.
An initial flash setup timed out before destructive submission: no feature
flash capture had been created, no mount-guard source had been uploaded, no
writer/guard was running on the Mac, and the original two-partition layout
remained visible. This failed setup is retained in private
`.local/multiboot/installation/flash-setup-timeout.json`. A fresh non-writing
preflight passed before a separately recorded write was submitted.

The completed `mac:flash` verified the real Mac mount veto, wrote the full
8,589,934,592-byte image, read every written byte back and ejected the card.
Readback SHA-256 is
`630be26098ae5736ff8718a2e2a4608564213a915f8222d87a5bed0200416463`, exactly
matching the prepared image; the bounded guard was 2168 seconds. Evidence is
`.local/diagnostics/20261022T033251.466149Z/`; `flash-result.json` hashes to
`3073c323755103f25a871eaaa34f94c6f5cb98ff5fc3f163eb8eab16264b378f`.
Private `.local/multiboot/installation/flash-qualified.json`, SHA
`f98be57edeb0ef672a15987094388d4174f296486aa9ec4c0a6a042e2e8477fe`, links the
identity/admission records, original setup failure, flash log and result.
This establishes the written image and ejection, not a board boot or clock/PM
qualification. The owner must return the card and power on the GameShell.

## Remaining acceptance

NEO-208 stays open pending actual vendor U-Boot trial consumption/readback,
board directory-root handoff,
both management routes, explicit confirmation, subsequent bundle import and
fixed-recovery/reset behavior. The owner moves the card. Use the existing long
speaker warning for any later board reboot. Do not run clock/PM captures until
the explicit deployment adapter and matching admission are ready, and do not
claim power-cut or total-hang recovery from the selector alone.

Primary references: [Linux 6.18 initramfs handoff](https://docs.kernel.org/6.18/filesystems/ramfs-rootfs-initramfs.html),
[U-Boot legacy bootm arguments](https://docs.u-boot-project.org/en/latest/usage/cmd/bootm.html),
[v2018.01-rc1 source command](https://github.com/u-boot/u-boot/blob/9da7fb4a39149c3061cb148bfbaa76b4b52b9008/cmd/source.c),
[v2018.01-rc1 FAT writer](https://github.com/u-boot/u-boot/blob/9da7fb4a39149c3061cb148bfbaa76b4b52b9008/fs/fat/fat_write.c).
