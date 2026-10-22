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

The initial 36 focused worker tests passed. Managed native qualification
`ed176852b8594772b8f4f023e96ede94` passed authoritatively, with original container
`760bc5361f1d48b48c63caa82078e961` exited successfully and no stop/OOM condition.
Its retained result SHA-256 is
`bef936e61701f14c0a4fdf489bc2dc44d16f80ce3848514774af373714090766`.
That initial worker SHA-256 was
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

The hardware growth, bounded probe and separate capable-system boot
qualification below all pass.

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

### Standards

Independent re-review of `de093ba` clears the original oversized-argument
finding. The source/receipt payload travels through bounded stdin; eight
submission/observation tests pass. No remaining documented-standard or smell
findings. The retained review SHA-256 is
`c985f3dac55da4bb9982daa56a21fb1faa74dbea75c0a67e41926d5ac3d1205a`.

### Spec

Independent re-review of `de093ba` clears the original raw-writer admission
finding. Native child-descriptor rejection occurs before commands or writes.
The surrogate/four-byte method satisfies the stronger MBR-preservation
requirement; no unasked scope or remaining source blocker was found. Review
SHA-256:
`8cdf05098d855c45920504aa0951f2f0dc683df7f4e1590c7cbef1b42cd9cd50`.

Both axes have zero remaining findings. The complete final source check passes
24 runtime and 1283 tooling tests (nine expected skips), both C checks and
Bash/ShellCheck. Its retained log SHA-256 is
`e3d26871ddd7ee976a25f849392483eac6b0c68a885a7a806da8e06e036da8a2`.

### Fresh hardware checkpoint

The complete pre-reboot diag25/27 check passed on capable diag27 boot
`926d517d-1a83-43d6-8702-1a83008025b5`, with all descriptors at recovery and the
exact fping capability intact. Its first 180-second read-only observation timed
out; inspection confirmed that transient verifier had exited. The separately
observed read-only check then completed, retaining the original failure.

Three long speaker cues and verified mixer/amp restoration preceded the one
recovery reboot. Fixed p2 boot
`53dc5db4-41e2-4095-8bdc-cb8d86a8e8db`, original kernel
`6.18.54-gameshellneo24` and recovery manifest matched. Both management routes
and inspected Kiyo console frames passed. The camera stopped after its bounded
capture; no button, audibility or clock/PM qualification is inferred.

Fresh checkpoint `checkpoint-847a6a6ab28a4f6bb969aba55b1b659b` completed with
boot/store cleanly unmounted and both read-only filesystem checks exiting zero.
All three backups were fully decompressed and compared to their exact source
lengths/hashes. They remain under this worktree's ignored
`.local/multiboot/installation/checkpoint-growth-20261022/`; all earlier
checkpoints remain at their original paths.

| Region | Raw bytes | SHA-256 |
| --- | ---: | --- |
| Reserved prefix including MBR | 16777216 | `43ceaaca8755e08f025fa82d94d4c1d27592788e0d75a0c5d35faae2fe838931` |
| Boot | 134217728 | `5da10f714704fb2cca88884c0ccc6cb0f8669a1dda762a7b3af3299996b6a2eb` |
| Store | 4294967296 | `81b48e11e097bbf893ce1e3393b517870394338be124321469f6140e2c7bddc5` |

The verified backup receipt SHA-256 is
`6222fd96ba5679765c5384376337f6c1b83e46c3026dad13463032c7312d0e63`.
Its 3639 file pins include 3609 regular settings files across the two inactive
roots. Read-only planning with that receipt matched the exact live recovery
boot, card, geometry, filesystem identities and original MBR.

One retained unit,
`gameshellneo-store-grow-4f71167346fe466894cb549bbe99adb8`, was submitted from
published source `de093ba`, with worker hash
`48d3281fe7f2217c178f36ff4ea2c4a35a3cb518152932520810dfc2a8172332`.
Its state and logs are on p2 under
`/var/lib/gameshellneo/development-store-growth-4f71167346fe466894cb549bbe99adb8/`.
Host observations stay in `.local/multiboot/growth/hardware-20261022/`.
It has `Restart=no` and `TimeoutStartUSec=infinity`; observations neither restart
nor terminate it. The original unit exited successfully at 10:00:02 UTC; its
10:00:18 observation passed all seven acceptance checks, including completed
worker, matching boot/unit, no remaining process/job and normal successful exit.
Observation SHA-256:
`e102260ffebd405e6571c5ec215cb9b24104618d1b5c5fa8d6fb6c131cc910b3`.

### Growth and probe result

The exact four-byte write at offset 490 was followed by full expected-MBR and
protected-region readback, partition-3-only kernel update, offline resize and
clean read-only filesystem checking. Partition and ext4 size both equal
59718500352 bytes: 116637696 sectors and 14579712 4096-byte filesystem blocks.
Starts, filesystem/PARTUUID identities, features, fixed boot assets, catalog,
both releases and every pinned settings file matched. Final MBR SHA-256:
`7a480c9454d52b6398e21be5517f0fd31c47c2f5e2f868e999c0c081e1a3724c`.
Every byte outside p3's length field is unchanged. Both private read-only mounts
were unmounted before the worker reported completion.

The separately reviewed normal-remount helper then checked the original
completed unit/state and exact boot/card/MBR/filesystem identities. It compared
the exact current catalog and all recovery flags against the pins; it relies
on the completed grower's full content proof instead of repeating another
`Card.status()` sweep. Its uniquely named 1048576-byte probe was written,
synced, read back exactly and deleted, followed by a directory sync.
Probe receipt SHA-256:
`261bcc33251d4bac2cfc7996fb558e009d69c69ec1613a71c0283fb9f498dd44`.

At that probe, `statvfs` reported 58687197184 filesystem bytes and 54267879424
available bytes, approximately 54.66 GiB total and 50.54 GiB available after
overhead, reserves and existing data. No image was rebuilt, card removed,
partition shrunk or old MBR restored.

### Return to diagnostic.27

Normal selection remained a separate operation. Unit
`gameshellneo-card-command-ea8b8962e2904292885202deae1d971d` completed successfully
at 10:03:44 UTC, selecting only NEXT=diag27 while retaining GOOD/RECOVER=recovery.
Its accepted observation SHA-256 is
`35bfce3f97ef4597c055523022a5a1d15a037a704e5161a692ee64936a72548d`.
The first camera sequence finished before the reboot was submitted and remains
separate evidence. A new 120-second Kiyo sequence reported readiness before
the warned reboot. Audio run `dd0c460ae472440f92c140897299c5c1` completed three
bounded cues and verified mixer/amplifier restoration before queuing one reboot.

The new boot is `cea309a9-bea5-49d7-8d41-e462ddd57e89`, kernel
`6.18.54-gameshellneo26`. Qualification compared the actual `/` device/inode
to `systems/diag27/root` (inode 131075), command-line/early-userspace markers,
source image, release and deployment manifests. The exact fping capability
`0100000200200000000000000000000000000000` and actual-store capability roundtrip
pass. The unmounted FAT check exited zero; NEXT, GOOD and RECOVER all match the
recovery descriptor after trial consumption. No failed units were present.
Qualification receipt SHA-256:
`9b6b756562b637ed298d88b83c15893ef94723b7ecd63f9738b3ff9a49d7311e`.

The initial USB status and qualification connection attempts were too early
and reported no route to host before running any remote qualification code.
Their original evidence is retained. Later USB and Wi-Fi status checks both
pass on the same new boot; no second reboot was submitted. Their retained log
SHA-256 values are respectively
`db10aff3480d73404db06dd18772a1f8a41466c6ba3d524dd644fe967e01445b` and
`6b8f6202e50ec48e09bd0e61c5897236f215e814a406c0bfb46a3c65c06ceb7c`.

Actual first/last JPEGs in hardware capture `20261022T100849.545376Z` show
readable recovery messages before reboot and the returned Trixie login console.
All 118 frames were retained and the camera stopped successfully. The private
visual-observation receipt SHA-256 is
`c699020c717443244ba381cb9e997695703862ad1b0fc358ffb892504608d99e`.
This establishes readable display return; button response, audibility and
clock/PM qualification were not inferred from video.

The final read-only `dev:store:grow` plan on this directory boot reports
59718500352 bytes for both current and proposed p3, 116637696 sectors and
`growth_required=false`, with all original starts/UUIDs/PARTUUIDs intact.
Receipt SHA-256:
`c486eaedea404ac1a21826b46073758204c1bd5cfa1063304e15f06986dd9e15`.

An additional read-only ARM32-native ioctl and ext4-superblock check on that
same boot confirms the partition and filesystem both have 59718500352 bytes,
14579712 blocks of 4096 bytes. `statvfs` then reports 54267826176 available
bytes, approximately 50.54 GiB. Receipt SHA-256:
`f175ec8645b032b719254edd89078fbfb195e105bdbef0c50a0a12f4ec878041`.
The first standalone read observer used a host-width ioctl request and returned
EINVAL on ARM32; its original source/output remain alongside the corrected
native-width read. The production worker already uses the correct native ioctl.

Diagnostic.27 remains unconfirmed with recovery as the default. NEO-208's
physical-input/default-confirmation and NEO-192 clock/provenance/awake gates
remain open.

The private completion receipt
`.local/multiboot/growth/qualification/development-store-expansion-complete.json`
cross-links source/reviews, qualification, checkpoint, the original successful
grow operation, probe, separate selector/reboot and final boot/access/camera/
capacity evidence. All eleven completion checks pass; its SHA-256 is
`15f9036b37df0508767d41ae083683655b97ea38f844df7b5a1fea03fb35cb0f`.
Raw backups, operation logs and images remain private in their original ignored
worktrees; branch cleanup must retain them.

Reports [292](292-development-sd-systems.md)–
[294](294-development-store-bootstrap.md) retain their original build,
installation and 4 GiB bootstrap checkpoints. Those older raw/geometry receipts
are historical after expansion; their strict guards must not be relaxed to
reuse them against a differently sized store.
