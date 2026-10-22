# Development SD systems (NEO-208)

22 October 2026. The owner requests multiple complete systems on the large
development card, selectable for the next boot, and accepts the initial
reflash. This is for development only; the final release will not include it.
The [commands and operational contract](../development/multiboot/README.md)
describe the opt-in tooling. The initial preparation below was offline;
installation and subsequent board observations are recorded separately.

**Current status:** the physical DEV-card flash is complete. Original r2's
first trial safely entered recovery after the vendor FAT writer created a
duplicate uppercase flag. The `ef1fca6` application fix was deployed over SSH;
diag26's directory boot, actual trial consumption/readback, both SSH routes and
return to fixed recovery on the next boot without confirmation have passed.
The remote bundle import rejected a missing filesystem capability attribute;
NEO-209 is preparing a capable maintenance system and an early destination
check. Import/select/confirmation acceptance remains open. The clock/PM
deployment adapter and matching awake qualification
remain separate, and NEO-192 is unresolved. The corrected r3 image and transfer
are offline-verified FAT-fix artifacts, but still contain the incapable original
kernel; wait for the capable maintenance artifact before another flash. Board observations below
belong to the repaired physical r2 installation.

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
| p1, sectors 32768–294911 | Shared fixed dispatcher, lowercase selection descriptors, versioned kernel/DTB/initramfs bundles |
| p2, sectors 294912–8388607 | Original fixed recovery system with its own kernel and DTB |
| p3, sector 8388608 onward | Complete `systems/<id>/{root,boot,release.json}` and administration tools |

The pinned vendor bootloader is `2018.01-rc1-00118-gd19ddc958a`, SHA
`d7154f264edfed57fe00e2dcbfe30c0c876b3e6a8a6e2ae5bcf7b84d470a208c`.
Its command strings include FAT loading/writing, `iminfo`, `source`, compare and
integer operations. This is capability evidence; the shell model does not
execute that vendor binary. Its upstream v2018.01-rc1 reference source is
`9da7fb4a39149c3061cb148bfbaa76b4b52b9008`, not an assertion that the vendor
fork is byte-for-byte upstream.

In the corrected layout, `next.scr` different from `good.scr` is a trial;
`recover.scr` holds fixed recovery. Original r2 used uppercase entries, whose
replacement defect is recorded below. The dispatcher validates bounded
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
(selected diagnostic.26). At this offline checkpoint the generated image was
hardware-unqualified; its first board trial subsequently failed as recorded
below.

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
logs, both review axes and the remaining qualification limits. At that offline
checkpoint the stage ledger was clear and all owned build sessions had completed.
Canonical main was `a41a0aa` with its original four owner-modified/untracked
paths, and the protected legacy request-resume audit hashed to
`2e8ed588faa129e9f07edc68d9137e8af684774353ed34233bb9b3932c35310a`.
At that checkpoint the feature branch remained open for physical acceptance;
its saved worktree, failed first image and original logs are retained.

## Standards review

Independent review of `a41a0aa...0d1fd62` found zero documented-standard
violations and zero actionable smell findings. The code retains managed
ownership, read-only sources, immutable version names, private artifacts,
identity checks and separate registration/selection. The receipt-collision,
SPL admission and recovery manifest/fstab correlation findings are resolved.
The review distinguishes shell-model/native evidence from the vendor/board
checks still outstanding.

A second independent Standards review of `a41a0aa...ef1fca6` found zero
documented violations and zero actionable smells. Its documentation notes
(lowercase flags, mixed FAT mount and completed installation) are reflected
here and in the operational handoff. The later capability-guard delta received
another independent review with zero actionable findings.

## Spec review

Independent review of the same fixed diff found zero missing requirements,
scope-creep findings or incorrect implementations. The development-only
contract covers independent complete roots, matched boot assets/modules,
preserved recovery, consume/readback, explicit confirmation, loop-free import
and guarded flash selection. Production inputs stay separate, and development
roots cannot reuse PM admission. Physical/vendor/board qualification remains
open. Findings: Standards 0; Spec 0.

The independent Spec review of `a41a0aa...ef1fca6` also found zero source
findings, while retaining import/select/confirm and clock/PM qualification as
open gates. The subsequent real import exposed the target-kernel prerequisite
below; the earlier host review is not evidence that this hardware gate passed.

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
This established the written image and ejection. Board boot and clock/PM
qualification were still pending at that checkpoint; the subsequent card
return and board results follow.

## Original r2 first boot and FAT replacement defect

The first board boot was `7cc3ad19-876c-4042-92ef-f86cc66c5559`, running fixed
recovery kernel `6.18.54-gameshellneo24` rather than the requested diag26.
Trial readback rejected the failed flag replacement and entered recovery.
Ordinary startup fsck found duplicate `NEXT.SCR` entries: the original 2653-byte
trial and a new 2266-byte recovery descriptor. It renamed the second entry
`FSCK0000.000`. This is a failed original trial, not a passing diag26 boot.

The original journal, script hashes and complete 128 MiB FAT snapshot remain
under the hardware checkout's `.local/diagnostics/`. Snapshot
`20261022T034222.060160Z/post-boot-fat.img` hashes to
`c55b684afb6c4baf96d0354b95539114bfeacb549edd1b1c7bf616c3fd5a7d51`.
Private `.local/multiboot/installation/first-boot-recovery.json`, SHA
`928e7e70a014e910001d07ba22e840d31f2f8cf06244624213ae63b0b1aec277`, pins the
original failure evidence. No PM/clock fault was cleared or confirmation made.

## Legacy FAT fixture and SSH repair

Published fix `ef1fca6` uses lowercase flag paths and admits only unique
lowercase directory entries on vfat mounted with `shortname=mixed`. Admission
rejects case-fold aliases and the alternate `msdos` driver, and is repeated
under the selection lock before writes and after flag replacement. The old
writer lowercases its request before a case-sensitive comparison against the
directory name; the uppercase Linux-created entry did not match.

The native fixture compiles unchanged pinned upstream v2018.01-rc1 FAT code
with POSIX block-I/O shims. Eight operations reproduce the uppercase duplicate
and exercise repeated writer/Linux atomic replacements with both lowercase
short entries (NTRes `0x18`) and lowercase LFNs (NTRes `0`). Linux's mixed
policy creates the latter. Atomic replacement of an existing uppercase entry
retains its incompatible presentation; migration must first move it to a
distinct basename before publishing a fresh lowercase entry. The fixture's
distinct-backup migration passes. This fixture does not execute the exact
vendor binary, controller or hush shell; the board trial below supplies the
separate live evidence.

Fixture result `.local/build/dev-fat-writer/9c8eaf14d335422887a0c2ad5244390c/result.json`
has SHA `4c862f03bafcac3adf1a3d3464545e3f44fe596f8a596a1f58fc884a10755b88`.
Managed run `db304206d64f4c6aa8853185c762554f` exited 0 without OOM or stop.
The fix's full check passes 24 runtime and 1160 tooling tests, five explicit
skips, compiled C checks and ShellCheck. The earlier 1150-test checkpoint above
remains its original result.

One recorded SSH repair ran as transient unit
`gameshellneo-case-repair-35f53c03cdbf477d932fc323fead876b` and completed with
exit 0 on the original recovery boot. It checked pinned source/card identities,
held the selection lock and validated the original full catalog. Originals of
four admin source files, boot files, flags and the FSCK artifact were saved
under the store's `admin/case-repair-35f53c03cdbf477d932fc323fead876b/`.
The temporary recovery anchor boots validated recovery and halts if it returns,
preventing vendor outer-search fallthrough during repair. Uppercase flags were
moved to distinct `OLD*.BAK` names, fresh lowercase flags were created, and new
admin/catalog validation completed before publishing the final dispatcher.
Durable phase/result records remain; the repair itself did not reboot or change
the selected/confirmed systems.

Repair script SHA is
`cdd8ec60aa1108e57391bff4b37821e78499d884c45a0e30f40d2f43ab4da854`;
manifest SHA is
`ea41336215097e586f43536100ac6ad5fdd0d9bb7b020ea535cdcfd06ab73e41`.
Unmounted read-only FAT fsck returned 0. The repaired snapshot SHA is
`e6e99475b9e8c787932e0080674fb2e31291f227f7f871a50d36b4a00363ced6`;
its raw audit finds one lowercase `next.scr` LFN with NTRes `0`.

## Actual diag26 trial and unconfirmed-boot rollback

The separately warned trial reboot used audio run
`e4e9a190e1ec4a109b8dc23c6f3e89dc`, capture
`20261022T040319.872438Z`: three long cues and mixer restoration passed.
Kiyo capture `20261022T040257.558992Z` retained 398 frames and stopped cleanly.
Inspected first/restart/startup/final frames show the previous console, restart,
new startup and readable login; U-Boot text was not readable in those frames.

New boot `6d4ee9eb-1dcd-4adc-af47-1e340e88d123` runs
`6.18.54-gameshellneo25`. The early-userspace/root markers identify diag26,
and `/` has the exact device/inode of `systems/diag26/root` in store
`b9dab681-03`. All three flags now contain recovery: NEXT was consumed and
read back before the actual directory-system handoff. A subsequent unmounted,
read-only FAT check returned 0 without duplicate entries. Independent USB
`20261022T040426.795339Z` and Wi-Fi `20261022T040424.206877Z` checks agree on
the boot, with no failed services/restarts and taint 0. Strong identity is saved
in hardware capture `20261022T040531.284745Z/development-boot.json`.
Private `.local/multiboot/installation/trial-qualification.json` has SHA
`ed690c45ae4255f8cd3071e3865df69d5d8c4c0f3ed3e23a54fbdabc261a5241`.
Registered input devices are observed; physical button response is not claimed.

No flag selection or confirmation followed. A second warned reboot, audio run
`d6507d9003df4b0ea4470afe3e4bdea4` at `20261022T040653.973017Z`, passed the
warning/restoration gates. Kiyo capture `20261022T040638.910571Z` retained 171
frames and stopped; inspected first/final frames show a readable login.
The next boot, `9caf10b6-a94f-4c9b-8ca9-e8e6c1580cab`, runs recovery kernel
`6.18.54-gameshellneo24` from `/dev/mmcblk0p2`, without a development runtime
marker. Flags remain recovery. Both USB `20261022T040806.617807Z` and Wi-Fi
`20261022T040806.262184Z` basic access/service checks pass. This establishes
automatic selection of fixed recovery after the unconfirmed trial on the next
separately initiated boot; it does not supply a reset for a hung kernel.

Private `.local/multiboot/installation/bundle-upload-preparation.json`, SHA
`228909a42cc50ec1053aa6da318189456bd2267c339b671eef073f8fb527078d`, pins that
rollback identity and a private incoming directory. Upload of the previously
qualified 678348800-byte diag25 bundle completed with SHA
`d1b40e7c333e652904c60c9d7df7fb4412f7411b8ca5568a8bda34b8069adaa4`.
The first device import did not pass; its terminal failure follows below.
Camera, SSH and selector observations establish neither PM/clock qualification
nor timing or energy targets.

## Target capability failure and early rejection (NEO-209)

Recorded unit `gameshellneo-bundle-import-8c5876d51cac48de8e6a5d530f8a32ce`
ran from 04:14:15 to 04:21:59 UTC and exited 1. GNU tar reported unsupported
`security.capability` on `diag25/root/usr/bin/fping`; the unchanged metadata
verification then rejected its missing xattr. The original private archive,
extracted staging tree, operation log, service journal and failed unit remain.
Nothing was registered as diag25. Postflight confirms the same recovery boot,
original diag26 catalog and all three recovery flag hashes; the only failed
unit is this recorded import job, which has not been cleared.

Both original generated kernels disable `CONFIG_EXT4_FS_SECURITY`. A separate
private regular-file probe on the actual store returned errno 95 for the exact
20-byte capability value while a `user.*` xattr roundtrip passed. The minimal
kernel prerequisite is `CONFIG_EXT4_FS_SECURITY=y`; the separate LSM framework
`CONFIG_SECURITY` is unnecessary. NEO-209 prepares a newly identified
diagnostic.27 / kernel26 maintenance system, preserving the original images
and patch queue. The incapable running kernel cannot bootstrap that system's
full-metadata TAR itself, so its initial installation needs offline card
preparation and the guarded DEV-card workflow.

Commit `c361728` probes every distinct required capability value on a private
regular-file descriptor after verified snapshot/hash and safe TAR admission,
before extraction. Unsupported or changed values reject with maintenance-boot
guidance. It removes only the probe and retains the failed snapshot/log; all
existing metadata checks remain. Capability-free bundles need no probe.

The full host check passes 24 runtime and 1166 tooling tests, six explicit
skips, compiled C checks and ShellCheck. The managed root builder passes 94
tests with six explicit BusyBox/namespace skips, including actual capability,
hardlink and original-metadata preservation. Its initial attempt retained a
missing-Paramiko dependency failure: the root runner now excludes only the
host SSH transfer suite, which still runs in the mandatory full host check.
These native results do not qualify the new ARM maintenance kernel or complete
the on-device import/confirmation gate.

Private failure receipt `.local/multiboot/installation/bundle-import-failure.json`
has SHA `e783c52c116f1c86f59304db1685a9f95a4fb0856070b40b47fa4929dd49398b`;
postflight SHA is
`f8ebe2bc8fb7e7e7262bd02c2cf69cf95b74c3b0bacb56ec3c2a3839ed3817db`.
The separate destination probe receipt SHA is
`01e372cf1e9f292df5468c2ba315c883fcf7d50f888fb7b377a061a56eb22afe`.

The exact `c361728` guard was then loaded from a private source copy on the
actual recovery kernel, without replacing its installed administration tree.
It hash-checked and parsed the preserved original failed bundle, rejected the
required capability with errno 95, cleaned its probe and performed no
extraction or publication. Original failure-log bytes, catalog and flag hashes
remained unchanged. Receipt
`.local/multiboot/installation/board-capability-guard-result.json` has SHA
`bf0ab8c8e3a667eae5f92771d2618b96e37d3772f8b71542190ef886f41f8659`.
This is the expected rejection case on an incapable target, not a successful
on-device import.

## Corrected r3 artifact, offline only

Saved `dev:card` and `dev:pack` Tasks built a separate r3 from clean `ef1fca6`,
using the same two pinned raw source images and authenticated ARM loader.
Retain r3 as the FAT-fix candidate and original r2 with its failed trial evidence.
Neither contains the capable maintenance kernel; do not spend another card
swap flashing r3 while NEO-209's bootstrap artifact is being prepared.
Managed assembly `97b7fb8352a3442f920894ebcbbd74a2` and independent read-only
audit `fccd4f33a8574091b0c51acd0de5c970` both exited 0 without OOM/stop.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `.local/multiboot/card/GameShellNeo-development-r3.img` | 8589934592 | `eeda974bf8c13ef92d1b90043597dba1a190c03146429d25b44686ff7680ee8d` |
| `.local/multiboot/transfer-r3/GameShellNeo-development-r3.img.gz` | 561055497 | `2c5ad62c500e4b7d8d6cae42ca46369c2877ecf05f7e05ff14158008170656ce` |

The image receipt SHA is
`b945da05c24aac4aa135c22dd648ac8ee3efac7ac701cfee416a43bc3c4dcb4b`;
the separate transfer manifest SHA is
`5bc83f2e700e98e3fc05134ff3cb87878ec240cf22e59424914bc91f171735b7`.
The audit mounted FAT read-only with `shortname=mixed`; raw FAT checks verify
one lowercase LFN with NTRes `0` per flag. Copied admin/loader pins and all three
filesystems pass. Full
compressed/decompressed transfer verification and the 2168-second guard
admission pass on Linux. Independent byte comparisons verify the original p2,
reserved bootloader prefix and exact MBR partition append. Nine source/r2
artifacts retained their original bytes/mtime, and all 816 frozen tracked inputs
were unchanged through qualification. No card, Mac, configuration or network
was accessed for r3.

The consolidated index is
`.local/multiboot/card/r3-qualification/qualification.json`, SHA
`9e4ea3c0fc1421204b5e98c2383bc9699dce7b204f925508a712479645c024a1`.
It pins authoritative managed receipts, original logs, source-only verification
and preservation evidence. At completion all owned sessions had ended and the
ledger/lock were clear. R3 has not been flashed or board-qualified; the board
observations above belong to the physical r2 card after repair.

## Remaining acceptance

NEO-208 stays open for the capable maintenance-system bootstrap, completed
on-device bundle import, the subsequent
version's matched boot/management observations and explicit confirmation.
Actual diag26 trial consumption/readback, directory-root handoff and
unconfirmed-boot return to fixed recovery have the bounded board evidence above.
Physical input response, broader reliability and reset/power-loss behavior
remain unqualified. Use the existing long speaker warning for any later board
reboot. Clock/PM provenance admission and matching awake qualification remain
separate work; preserve NEO-192's original failures and do not use frozen older
PM runners to bypass development-deployment rejection. The selector alone does
not establish power-cut safety or a reset for a complete kernel hang.

Primary references: [Linux 6.18 initramfs handoff](https://docs.kernel.org/6.18/filesystems/ramfs-rootfs-initramfs.html),
[U-Boot legacy bootm arguments](https://docs.u-boot-project.org/en/latest/usage/cmd/bootm.html),
[v2018.01-rc1 source command](https://github.com/u-boot/u-boot/blob/9da7fb4a39149c3061cb148bfbaa76b4b52b9008/cmd/source.c),
[v2018.01-rc1 FAT writer](https://github.com/u-boot/u-boot/blob/9da7fb4a39149c3061cb148bfbaa76b4b52b9008/fs/fat/fat_write.c).
