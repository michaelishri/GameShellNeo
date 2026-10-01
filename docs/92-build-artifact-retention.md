# Build-artifact retention (NEO-72)

1 October 2026. The owner authorized pruning old diagnostic images, archived
kernels and abandoned `CleanupAtFrozenRetentionCap` test fixtures. The policy
keeps three recent raw images and three full kernel snapshots, with smaller
compressed images and provenance retained for recovery.

## Why raw images need special handling

Each image has a logical size of 4 GiB but occupies only about 0.7 GiB because
it is sparse. Before diagnostic.13 there were fifteen raw images, including
multiple diagnostic.1 and diagnostic.5 builds. Disk savings are measured from
allocated blocks, not apparent image sizes.

Six modern checkpoints and one older manual recovery record reference older
images. The modern resolver
required the raw file even though Mac staging uses only the gzip archive. The
resolver now verifies the complete streamed expansion against the checkpoint's
original size and SHA-256 when its raw copy has been pruned. It still verifies
the compressed hash and all checkpoint metadata; a present but corrupted raw
image is rejected. Expansion is bounded by the recorded size and does not
create another raw image.

The compact gzip archives contain private provisioning and remain ignored.
They are retained here, not published or transferred as part of cleanup.

## Repeating project cleanup

Wait for the full build/pack/staging workflow to finish, then preview:

```sh
task build:prune-retained KEEP=3
```

Apply the reviewed selection with:

```sh
task build:prune-retained KEEP=3 APPLY=1
```

The task:

- Holds the existing build-stage lock and refuses a busy stage. Do not interleave
  it between stages of an ongoing multi-stage workflow.
- Keeps the latest diagnostic versions, using file modification time to order
  repeated builds of one version. The current verified image is always retained,
  even if that means keeping an extra raw image. `KEEP` must be at least two.
- Keeps the newest timestamped full kernel snapshots. Before removing older
  source/output/module trees, copies and checksum-verifies their artifact tar,
  available completed record, configuration, release and patch stamp under
  `.local/retention/kernel-metadata/`.
- Resolves every named recovery checkpoint and verifies each old raw image's
  complete gzip expansion before deleting any image or snapshot. Missing or
  mismatched archives stop the operation. Compact provenance is also saved
  before any deletion starts.
- Refuses unexpected image/snapshot names and layouts, symlinked deletion roots
  and symlinked artifact/provenance files. It does not touch active kernel
  source/output, credentials, original-card backups, downloads or test captures.
- Updates `SHA256SUMS` to list retained artifacts; archived raw hashes remain
  in the retention record.
- Saves a private incremental `.local/retention/prune-*.json` containing the
  candidate allocation, retained paths, verified raw/compressed hashes, copied
  metadata hashes, deletions and filesystem free-space observations.

All compressed images remain available. Named checkpoint recovery still uses
`task mac:stage-recovery NAME=...`; its local verification now also works after
raw pruning. For an older image without a named checkpoint, retention records
preserve raw/gzip hashes, but do not manufacture hardware qualification or a
complete named checkpoint.

Cleanup is explicit rather than automatic after every build. This leaves time
to retain a candidate or inspect a regression before applying the policy.

## Preserving the older diagnostic.6 record

The first application stopped before deletion because
`.local/recovery/diagnostic6-before-pm/` predates the saved checkpoint schema.
Its six original files lacked the image manifest and metadata checksum list.
The guard was kept strict; this record was not silently skipped.

The archived metadata tar at
`.local/previous-kernels/20260929T115303Z-21939/artifact-metadata.tar` contained
the matching diagnostic.6 image manifest, configuration, compiler, packages
and patches. Its verification and completed-kernel records matched the manual
checkpoint; its source lock and resolved configuration also matched exactly
(as JSON objects and bytes respectively). Every recovered patch matched the
completed-kernel checksum.

Missing checkpoint files were added from that archive, with the original six
files unchanged. The resulting checkpoint passed normal raw/gzip/metadata
verification. Its metadata checksum list covers the original and added files.
Evidence: `.local/retention/legacy-diagnostic6-upgrade.json` and
`.local/neo72-legacy-upgrade.log`. The failed attempt is retained in
`.local/neo72-retention-legacy-stop.log` and
`.local/retention/prune-20261001T102216.678505Z.json`, with no deleted paths.
The archive's compact copy is retained under `kernel-metadata/` after cleanup.

All seven checkpoints can therefore use the standard recovery selector after
raw-image pruning, without reconstructing or inventing missing provenance.

## Abandoned external test fixtures

The exact matched pattern was
`TestPrivateV4CommittedOldOnlyCleanupAtFrozenRetentionCap[0-9]+` under
`/home/mishri/workspace/temp`. Eighteen directories contained 1,724,242 entries
and occupied 7,338,274,816 allocated bytes (6.83 GiB). Their latest descendant
modification was 1 September 2026, 16:01:18 UTC.

The originating Go test creates these through `t.TempDir()`. A privileged
read-only `/proc` check found no matching command, working-directory, open-file
or mapped-file references and no active Go/test process; every process was
inspectable. The running build container had no fixture mount. A fresh audit
immediately before deletion again passed the age and activity checks. All
eighteen matching directories were removed; unrelated temporary data remains.

This was a narrowly scoped external cleanup, not a general workspace deletion
task. Private audit/application evidence is in
`.local/neo72-fixture-audit.json` and `.local/neo72-fixture-cleanup.jsonl`.

## Validation and application results

Nine retention regressions cover preview/application, current-image protection,
busy locking, archive/checkpoint failure, metadata conflicts, unexpected layouts,
symlinks and invalid retention. Three additional recovery regressions cover
compressed-only recovery, missing artifacts and invalid/rehashed archive
expansion. `task check` passed 13 runtime tests, 295 tool tests (one optional
skip), compiled helpers and Bash/ShellCheck. Evidence: `.local/neo72-check.log`.

The application ran only after diagnostic.13 finished building, passed offline
verification and was checksum-verified on the Mac. It completed successfully:

| Group | Removed | Allocated space recovered, approximately |
| --- | --- | --- |
| Older raw diagnostic images | 13 | 9.24 GiB |
| Older full kernel snapshots | 9 | 17.51 GiB |
| Abandoned external test fixtures | 18 | 6.83 GiB |
| Total | | 33.6 GiB |

Compact copied kernel provenance and incremental records use a small amount of
space; the measured project-cleanup free-space increase was 26.74 GiB. The
filesystem reported about 64.3 GiB free afterward. The table uses allocated
blocks rather than the sparse images' apparent sizes.

The retained raw images are diagnostic.11, .12 and .13. All sixteen gzip images
remain. The three full kernel snapshots retained are:

- `20260930T110952Z-287797` (diagnostic.10).
- `20261001T005804Z-475387` (diagnostic.11).
- `20261001T092732Z-596127` (diagnostic.12).

The active diagnostic.13 kernel source/output/modules remain in their normal
working locations. Nine retired snapshot metadata bundles are retained under
`.local/retention/kernel-metadata/`.

Application evidence:
`.local/retention/prune-20261001T102551.105770Z.json` and
`.local/neo72-retention-apply.log`. Post-cleanup recovery/catalog verification
is recorded in `.local/neo72-post-cleanup.json` and its matching log.


Post-cleanup checks passed for all seven named checkpoints, including five
using only compressed images. Exactly three raw images and three full kernel
snapshots remain, sixteen gzip images are retained, and the artifact checksum
catalog has no missing files. No card or GameShell operation was needed by
this cleanup task.
