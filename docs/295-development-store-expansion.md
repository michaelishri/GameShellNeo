# Development-store expansion (NEO-211)

22 October 2026. The owner approved expanding the Samsung DEV card's existing
version store to use all trailing unallocated capacity. This is development
tooling; normal image construction and the final release do not install it.

## Target and preservation contract

The verified physical card contains 64013467648 bytes in 512-byte sectors.
Only partition 3's length changes:

| Field | Before | Target |
| --- | --- | --- |
| Store start sector | 8388608 | 8388608 |
| Store sectors | 8388608 | 116637696 |
| Store bytes | 4294967296 | 59718500352 |
| Store capacity before filesystem overhead | 4 GiB | 55.6171875 GiB |

The disk identifier, partition starts, boot/recovery geometry, filesystem UUIDs,
PARTUUIDs, boot assets and recovery descriptors must remain unchanged. The MBR
readback must differ only in bytes 490–493, partition 3's sector-count field.
The original diagnostic.25 recovery root remains on p2; diagnostic.25 and .27
directory deployments, independent settings and their metadata remain on p3.
No filesystem feature toggles, shrinking, shared settings or new image build
are part of expansion.

## Commands and admission

Use a new source checkout for this tooling and the established frozen hardware
checkout for authentication and transport. Private configuration, keys and
known-host records are never copied into the new checkout.

```sh
task dev:store:grow -- --hardware-checkout <hardware-checkout>
```

The default command reads live identities and reports proposed capacity. It
does not stage a worker, change mounts, register/select a version or write the
card. Apply requires the original fixed recovery p2, its exact current boot,
the admitted Samsung CID/geometry and a fresh fully verified backup.

After entering recovery through the existing warned reboot workflow, mount
boot at `/boot` with `shortname=mixed` and the store at `/mnt/neo-devstore`.
Verify both ordinary catalog releases and all recovery descriptors. Then:

```sh
task dev:store:backup -- --hardware-checkout <hardware-checkout> \
  --boot-id <current-recovery-boot-uuid> --output <new-local-checkpoint-directory>
```

This command changes mounts: it cleanly unmounts boot and store and leaves
them unmounted. It streams the reserved first 16 MiB, complete boot partition
and complete current 4 GiB store directly off-device, recording raw/compressed
lengths and hashes and verifying every decompressed byte. The receipt also
pins the recovery/card identities, MBR, boot flags, catalog and administration
and release/source files. Existing regular settings files in each inactive
root's `etc`, `root`, `home` and `var/lib` are also pinned without following
symlink paths; the worker compares them after growth. It does not stage large
archives on p2.

Failed checkpoint streams retain partial host files, original remote sources,
process identities and receipts. Inspect the original directory with the
backup command's `--status`; no automatic retry or remount is performed.

```sh
task dev:store:grow -- --hardware-checkout <hardware-checkout> \
  --backup-receipt <checkpoint>/backup-receipt.json

task dev:store:grow -- --hardware-checkout <hardware-checkout> \
  --apply --backup-receipt <checkpoint>/backup-receipt.json \
  --output <new-local-growth-operation-directory>

task dev:store:grow -- --hardware-checkout <hardware-checkout> \
  --status <original-local-growth-operation-directory>
```

Apply stages one root-owned worker on p2, records its identity before SSH
submission and starts one retained oneshot unit. It has no automatic restart
or write timeout. Observation is separate and requires the original loaded,
executed, exited unit, matching boot, no queued job, successful exit and matching
completed worker record. A lost connection is inconclusive; inspect that unit
and its original state rather than submitting another operation.

## Offline operation

The worker runs in a private mount namespace with private propagation and
requires boot/store to remain unmounted. It shares checkpoint/bootstrap writer
interlocks and retains an independent growth ledger; an unresolved destructive
attempt blocks later attempts even if another state directory is requested.

It verifies the full old raw regions against the new checkpoint before any
write. Writable filesystem checking then takes its own exclusive claim.

Native qualification exposed a necessary correction to the proposed direct
`sfdisk` write. Its DOS partition implementation recalculates legacy CHS fields
when changing a partition's length; the installed utility is version 2.41.5.
The card's p3 contains sentinel CHS values. Writing its result directly would
violate the requirement to preserve every other MBR byte. The disposable-loop
guard caught and retained that failure. See
[util-linux's DOS implementation](https://github.com/util-linux/util-linux/blob/v2.41/libfdisk/src/dos.c),
particularly `dos_set_partition`, `set_partition` and `dos_partition_sync_chs`.

Instead, `sfdisk -N 3` receives the exact sector count on a private sparse
surrogate containing the original MBR and exact parent capacity. Signature
wiping, automatic rereading and kernel notification remain disabled. The
generated layout must preserve starts, types, other entries and boot data;
only p3's length and the utility's CHS recalculation are allowed there.
The actual card receives exactly its four-byte length field under exclusive
p3 ownership and a nonblocking parent lock. No temporary CHS rewrite or repair
occurs. Complete exact MBR and protected boot/prefix readback must pass before
`partx --update --nr 3`. Kernel and on-disk geometry must agree before offline
`resize2fs` runs. The command interfaces are documented by
[sfdisk](https://man7.org/linux/man-pages/man8/sfdisk.8.html) and
[resize2fs](https://man7.org/linux/man-pages/man8/resize2fs.8.html).

Do not hold a wrapper's exclusive p3 descriptor while e2fsprogs opens its own
exclusive claim. A stable private mount view forces the offline path; a mount
race from another namespace must cause an exclusive-open failure. The worker
never forces a resize past failed checks, enables an online-resize fallback or
changes features.

After growth, read-only filesystem checking and superblock size/UUID/features
must pass. Private read-only mounts verify the unchanged catalog, boot flags,
source pins and both releases' immutable files, then are unmounted again.
The worker never selects a version or reboots. No automatic partition rollback,
shrink or restore is attempted after a failure.

## Qualification and hardware result

The 36 focused worker tests pass. Managed native qualification
`ed176852b8594772b8f4f023e96ede94` passed authoritatively, with original container
`760bc5361f1d48b48c63caa82078e961` exited successfully and no stop/OOM condition.
Its retained result SHA-256 is
`bef936e61701f14c0a4fdf489bc2dc44d16f80ce3848514774af373714090766`.
The frozen worker SHA-256 is
`f3f78f8ae96cd80063b087838cd78bf69269c8d6306daf5c9dab89d7876fca48`.

The actual disposable p3 grew from 64 MiB to 288 MiB while p2 stayed mounted.
All 75 captured metadata entries, contents, inodes, ownership, modes, hardlinks,
symlinks, user attributes, exact file capabilities, POSIX ACLs, FIFO and character
device survived. Boot, mounted recovery and reserved-prefix bytes were
unchanged, both registered roots verified and a 262144-byte write/read/delete
probe passed. A real mount in another namespace during handoff remained
invisible to the worker; `resize2fs` rejected its exclusive open. That operation
stayed incomplete without retry or rollback. Geometry-failure, interrupted
observation and duplicate-writer cases are also covered.

Actual `sfdisk` planning on a 64013467648-byte sparse file used the captured live
MBR SHA-256
`79fc38e3713407f8cbf0393cd9b28a4c347f13868f2ea474a6a35881768f6417`.
It produced the exact 116637696-sector target and reproduced the CHS changes;
the validated physical candidate changes only the length field.

Earlier fixture failures remain retained: initial Docker access, namespace-PID1
admission, invisible host-swap paths, optional `--lock` argument syntax and the
strict CHS mismatch. Each failed operation was inspected before a separate
corrected fixture; none touched physical media. The first broad host check
also retains its sandbox socket failures; qualification must use an environment
that permits the existing local socket fixtures.

Physical expansion has not yet occurred. Independent reviews and final hardware
receipts must be recorded here after authoritative completion.

Independent reviews of candidate `fdb7a71` found two concrete issues before
hardware work. The Standards review identified a large source/receipt payload
passed as one SSH argument, exceeding Linux's per-string limit for normal
settings receipts and exposing source in command auditing. Submission now
passes compressed literal JSON through the established bounded stdin source
interface; large-payload roundtrip and transport-bound rejection tests pass.
The Spec review identified ordinary writable raw device handles not covered by
mount claims or advisory locks. Admission now scans process descriptors for
the actual parent/partition device numbers, rejects writable aliases and fails
closed on unreadable or malformed descriptor flags.

Follow-up native run `dee61a5209f844838f35bb32a55d7ee4` passed on worker SHA-256
`48d3281fe7f2217c178f36ff4ea2c4a35a3cb518152932520810dfc2a8172332`.
Independent children holding ordinary writable p3 and parent descriptors were
identified and rejected before any utility or write; both children exited
before the real disposable growth. All earlier preservation/race/full-capacity
cases still pass. The focused worker suite now has 42 passing tests, alongside
16 checkpoint/transport and eight host-observation/submission tests.

After successful expansion, separately mount the filesystems, select diag27
normally and use the established long speaker warning before reboot. Verify
the actual directory root, exact capability value, both routes, inspected Kiyo
console, capacity and bounded write/read/delete behavior. Leave diag27
unconfirmed with recovery as the default. NEO-208's physical-input/default
confirmation and NEO-192 clock/provenance/awake gates remain open.

Reports [292](292-development-sd-systems.md)–
[294](294-development-store-bootstrap.md) retain their original build,
installation and 4 GiB bootstrap checkpoints. Those older raw/geometry receipts
are historical after expansion; their strict guards must not be relaxed to
reuse them against a differently sized store.
