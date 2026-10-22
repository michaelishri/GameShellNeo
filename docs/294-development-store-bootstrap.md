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

The installer and package implementation are undergoing regressions and
independent review. The saved `test:dev-store-install` fixture passes on a new
64 MiB synthetic loop image: the same exclusive descriptor survives the exact
write, full readback and read-only `e2fsck`; mounts are rejected before and after
that check and work after the claim closes. Its original managed result is
retained under `.local/build/dev-store-claim/ae7c22a042304e708f28e5e5e13b3c65`.
Actual old-FAT compatibility and the real remote bootstrap remain pending.
No remote block write is claimed
by this report at this checkpoint. Selector boot, real version import and
confirmation remain NEO-208 gates. Clock and PM admission remain separate.

## Standards

Final independent review pending.

## Spec

Final independent review pending.
