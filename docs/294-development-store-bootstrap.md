# Remote development-store bootstrap (NEO-210)

This opt-in developer operation replaces the inactive ext4 store while the
GameShell runs its original fixed recovery partition. It addresses the initial
bootstrap problem recorded in [report 292](292-development-sd-systems.md): the
old recovery kernel cannot preserve `security.capability` while extracting a
version archive. A complete ext4 image prepared on the Linux build host retains
that metadata without requiring the old kernel to interpret it.

This is development tooling. The owner excludes the version selector from the
final release. Ordinary subsequent version transfers use `dev:bundle` and
`dev:systems` from a capable maintenance kernel. The bootstrap does not register
a system, select a version or reboot the board.

Offline qualification is complete at source `61d46da`. The prepared R4 card,
inactive store package and optional full-card fallback archive are verified.
The real read-only plan and single guarded `--apply` have now completed on the
original fixed recovery boot. Registration, selection, capable-kernel boot and
version import remain separate NEO-208 operations.

## Saved operations

`task dev:store:pack -- --image IMAGE --image-sha256 SHA --receipt RECEIPT
--receipt-sha256 SHA --output NEW_DIRECTORY` prepares a fresh private package
from an explicitly verified regular development-card image. Preparation uses
the locked builder without network access. The copied store retains its complete
root, boot assets, administration and metadata, with an empty registered
catalog. The original source image and receipt remain unchanged.

Stage `install-dev-store.py` and `dev_store.py` as root-owned files under a
private directory on fixed recovery p2. The installer accepts absolute
`--archive`, `--manifest`, `--backup-receipt`, `--boot`, `--store` and `--state`
paths. Its default mode checks admission and the entire compressed and
decompressed archive. Explicit `--apply` takes durable ownership and replaces
only the admitted, cleanly unmounted store partition. `task dev:store:install`
passes the same arguments as data when the checkout is available on recovery.

Admission pins the backup boot, original recovery manifest and kernel, physical
card CID and capacity, all three partition geometries and filesystem identities,
fixed boot assets, lowercase recovery flags, old catalog and retained failure
files. A complete verified unmounted boot/store backup is required. Archive
pins are checked again against an operation-private copy on p2 before any target
write. The live preimage is matched through identity and content pins; its raw
hash may change after a known ext4 remount.

An exclusive kernel block claim spans the exact bounded write, fsync, full raw
readback and read-only filesystem check. Mounting the new store follows those
checks. An unresolved destructive attempt blocks automatic retry even if a new
state directory is supplied. Inspect its original unit, ledger and retained
files before deciding how to recover. The installer never raw-replaces FAT,
changes the partition table or fixed recovery, or consumes a boot flag.

## Qualification status

The original unmounted p1/p3 checkpoint is complete, fully verified compressed
and decompressed, and both filesystems were restored to their original mount
options without reboot. The diagnostic.27 image with ext4 security attributes
has completed its normal image verification and additional capability audit.

The final source is `61d46da890bac06680397eca5e22d976e266e8c5`. The complete
host check passes 24 runtime and 1,217 tooling tests (nine explicit skips), the
native C regression checks and Bash/ShellCheck. The managed root suite passes
139 tests (six explicit BusyBox/namespace skips), including actual mixed
ownership/device nodes, hardlinks, native security-capability and named-user ACL
roundtrips, plus root metadata comparison and rejection controls. These logs
are `.local/build/dev-store-full-check-final.log` and
`.local/build/dev-root-tests.log`. The source/preparation index
`.local/multiboot/card/r4-qualification/completed-source-and-preparation-checks.json`
has SHA-256 `a5497c074c26ad0f2c3514002b6ff75a06bf4d48b614f76e07558bd6b4f90c65`.

The initial saved `test:dev-store-install` fixture is retained under
`.local/build/dev-store-claim/ae7c22a042304e708f28e5e5e13b3c65`. The repeated
fixture after the native ioctl correction passes on a new 64 MiB synthetic
loop image: the same exclusive descriptor survives the exact write, full
readback and read-only `e2fsck`; mounts are rejected before and after that
check and work after the claim closes. Its result is
`.local/build/dev-store-claim/1c1f1f4f09b34fb5b60d160bbbbc84cc/result.json`, SHA-256
`5921ad34638ca30aaa59051b310c7687d89bb5a78d57e4d3fd1fdf7c15b494a2`.
This exercises a disposable native loop, separately from the earlier read-only
ARM ioctl query described below.

All paths below are rooted in the preserved
`GameShellNeo/.local/worktrees/multiboot-boot-selection` checkout. R4 retains
the original diagnostic.25 fixed recovery partition and reserved bootloader
prefix byte for byte, with capable diagnostic.27/kernel
`6.18.54-gameshellneo26` as its directory system. The package copies only its
4 GiB store region, empties the registered catalog, and verifies the complete
inactive release and administration without modifying the source card. It
passes read-only ext4 checking and full compressed/decompressed verification.

| Prepared artifact | SHA-256 |
| --- | --- |
| `.local/multiboot/card/GameShellNeo-development-r4.img` (8,589,934,592 bytes) | `6ec95305c25360264d3a4fe9ebcfbd30f875740ff561a4f6a0918c42d2f5d863` |
| `.local/multiboot/card/GameShellNeo-development-r4.json` | `463cc0b6a3d9a6b38197442ff4cd893ddbcef44a21616ab88a39c40dd1067d92` |
| `.local/multiboot/store-r4/store.ext4` (4,294,967,296 bytes) | `0b20c5aaad0cf0c68ba6dc39bfd3c936baa704cf588fa404d701d3cc7e99294e` |
| `.local/multiboot/store-r4/store.ext4.gz` (277,537,675 bytes) | `a9b57fed51dce7bfb963ac6902cbd2b180f061539f6a69116e3f7370c1ec0afc` |
| `.local/multiboot/store-r4/store.json` | `13ba3b96e1001312a5823c362f3b765fb4193fd15278a0512e6176ab06a2412d` |

The native saved `check:dev-store` fixture uses disposable copies of the actual
original FAT checkpoint and the new inactive store. It verifies recovery status
with an empty catalog, ordinary `Card.register('diag27')` without changing boot
selection, copied administration and authenticated ARM loader admission,
ordinary trial selection with GOOD/fixed recovery retained, and restoration of
NEXT to recovery. Both FAT and ext4 checks pass after unmounting. It compares all
23,496 root metadata entries before and after administration: 18,437 regular
files, 2,127 directories, 2,932 symlinks, four hardlink groups and one extended
attribute remain equal. The metadata digest is
`547990055c9a34d3054d4d1a5c516ea453efaefe14421c6b1a39c26bb824ab10`.
The actual `usr/bin/fping` capability is
`0100000200200000000000000000000000000000`, exactly matching the independent
diagnostic.27 image audit in [report 293](293-ext4-security-attributes.md).
This is an on-disk attribute comparison on the native build host; it does not
establish that the new kernel has booted or used the attribute on the board.

The original fixture is retained under
`.local/build/dev-store-compatibility/b6a14ddd188640878b15b3f75e6af829`.
Its published receipt is
`.local/multiboot/card/r4-qualification/store-compatibility.json`, SHA-256
`e6f71da011d0e19b16e174be4b563c732fdd0afc5a6b55de852a05c3934cdbe0`;
the original managed result SHA-256 is
`e95624008eeabbac3f13d47591fb40aec8aa947dfd416530981ae69c35a6525f`.

| Completed managed stage | Run |
| --- | --- |
| Root metadata/import regressions | `3e1a8e8fc3204dc6be5a7dd915785c8e` |
| Corrected exclusive-claim fixture | `ffa6d72236044fefb200b3f18a3ca9a3` |
| R4 regular card assembly | `2ab18a8620834668986bc6389ebbe207` |
| Inactive store packaging | `99e5facccb804ead9a2621f0e7698272` |
| Actual old-FAT/store compatibility | `976e44bd01d844eaab760ee077f8d699` |

Each original managed result records exit 0, no OOM and no stop request. The
offline qualification index at
`.local/multiboot/card/r4-qualification/qualification.json`, SHA-256
`f8007b11441890272225a4703890970e34fea0bc568ed2161b1b16fce888cb38`,
pins these results, the original boot checkpoint, backup attestation, source
reviews and 828 unchanged source inputs. Original failed imports, earlier
findings and retained jobs are preserved.

The optional full physical-flash fallback is separately prepared through
`dev:pack` in the fresh private `.local/multiboot/transfer-r4` directory. Its
`GameShellNeo-development-r4.img.gz` is 561,024,418 bytes, SHA-256
`8ec80565c634866ecf3ed7a6d2c0f91881bfd468e50f11e311d8bea59c1553dd`.
The transfer manifest SHA-256 is
`0231c74995a6fc083967ce66249082ff9c81de9dd5296d934def07bcc46c4e2a`;
the copied development receipt retains the R4 receipt hash above. Linux
source-only verification passes local staging admission, full compressed and
decompressed hashes and the explicit 2,168-second bounded guard policy. Its
receipt is
`.local/multiboot/card/r4-qualification/fallback-source-verification.json`, SHA-256
`9b67ab8bf12d53b3ff58b8721bd6a868b95258d3bf0159cad9743ff65f579f69`.
At the completed fallback-preparation checkpoint, all 828 source files and both
original R4 image/receipt bytes and modification times were verified unchanged.
This report was updated afterward to record the results. No Mac transfer,
physical-card operation or flash is claimed by the fallback preparation.

The actual device plan and guarded store replacement pass as recorded below.
Capable-kernel boot and attribute checks, real version import and confirmation
remain NEO-208 gates. Clock and PM admission, including NEO-192, remain separate;
these checks do not qualify board timing or energy.

## Actual remote bootstrap

The package and pinned installer were uploaded through the existing USB SSH
route and copied into a unique root-private directory on fixed recovery p2.
The original recovery boot remained `9caf10b6-a94f-4c9b-8ca9-e8e6c1580cab`,
kernel `6.18.54-gameshellneo24`, throughout the operation. The read-only plan
passed complete live card/root/backup admission and compressed/raw checksums
before the separately submitted apply unit.

The recorded apply unit is
`gameshellneo-dev-store-apply-490f3a7a7b794637be4eef87a6ee3834`. It retained the
exact original 678,348,800-byte diag25 TAR on p2, verified its private package
copy, repeated live admission, cleanly unmounted only p3, and took the exclusive
block claim. All 4,294,967,296 written and read-back bytes match raw SHA-256
`0b20c5aaad0cf0c68ba6dc39bfd3c936baa704cf588fa404d701d3cc7e99294e`.
Read-only `e2fsck` through the same held descriptor exited 0. The copied
administration verified the complete inactive diag27 release and its immutable
files after the new store mounted as `rw,noatime`.

Authoritative completion requires the original unit to remain loaded with a
recorded execution, no queued job or main process, successful exit status and
the original passing worker result. These checks passed: the retained unit was
`active/exited`, `MainPID=0`, `ExecMainPID=1623`, `ExecMainStatus=0` and
`Result=success`. The terminal installer state is `complete`, with
`completed=true`, `registered=false`, `boot_selection_changed=false` and
`reboot_performed=false`. The terminal observation receipt
`.local/multiboot/installation/store-bootstrap/apply-result.json` has SHA-256
`05ba6336f9847a6a8c5e24db90f5a6caceb81579fcf546c69007d80f91de6062`.

Independent postflight confirms original recovery manifest identity, an empty
new catalog, store UUID `905c31f6-8d2a-486c-8c57-ca1fd23ecd36` and all three
unchanged recovery flag hashes. The original failed import unit was still
failed and had not been reset. Its original store contents remain in the fully
verified host checkpoint. Postflight evidence
`.local/multiboot/installation/store-bootstrap/completion-evidence.json` has
SHA-256 `551911ff9b5d043525f0aa8ac8dbbd0c23f6b2f91ff5fa31731d26a896bea95e`.
Two SSH observation channel timeouts are preserved separately; the original
apply was never resubmitted or stopped, and later observations established its
terminal success. The installer did not replace FAT, the partition table,
bootloader or the fixed recovery system; its private staging and evidence are
ordinary files on recovery p2.

## Standards

The initial independent review of `8ae9274` found one hard issue and no
actionable smells: a fixed x86 block-size ioctl request did not match native
32-bit ARM. A read-only board query reproduced its errno 22 rejection and
verified the native request returns the exact 4 GiB store size. The correction
derives the request from native `size_t` width and checks both encodings.
The original finding and read-only query are retained. Final Standards review
of `61d46da` reports zero hard findings and zero actionable smells; the corrected
native fixture above passes. The final source-review receipt is
`.local/multiboot/installation/dev210-final-source-reviews.json`, SHA-256
`5bd4447df58a6884b753d5de1200903861ba9b87d104d941a9b1d51b57d567b5`.

## Spec

The initial independent review found two partial requirements: original-failure
file pins were optional, and the compatibility fixture lacked root metadata
comparison around administration operations. The correction requires archive
and log pins from one retained failure operation, cross-checked against live
store-file pins; additional retained evidence files must share that operation
directory and match their mandatory store-file pins. The independent host
failure-result digest remains separate. The fixture now compares the complete
root's ownership, modes, links and extended attributes before and after
administration, and the actual artifact run passes that comparison. Final Spec
review of `61d46da` reports zero remaining missing/partial requirements,
incorrect behavior or scope creep. The initial findings remain recorded;
offline completion does not close the actual device gates above.
