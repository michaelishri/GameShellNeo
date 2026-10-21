# Historical driver-source compaction

7 October 2026. NEO-127. Host build-storage maintenance for NEO-125; no device,
charging or kernel behavior is changed by this work.

## Reason and contract

Diagnostic.21 completed its kernel, source regressions and device-tree checks,
then Armbian rejected image assembly because less than 10 GiB was available.
The original failed build log is retained. The threshold is unchanged.

The existing retention task, run in the main worktree with `KEEP=2 APPLY=1`,
verified recovery archives/checkpoints before removing the older diagnostic.17
raw image and one superseded full kernel snapshot. Its audit is
`.local/retention/prune-20261007T021236.347627Z.json`. This recovered about
2.7 GiB and left about 8.7 GiB available. Two newest retained raw images and
snapshots remain there; the active integration worktree separately retains
diagnostic.20 and its matching kernel/recovery checkpoint. No matching old
frozen-retention test fixtures remained to remove from `workspace/temp`.

Historical driver checks still held full Linux source copies. The checkout's
newer patch queue cannot authorize replacement of these older trees. The saved
compaction task now accepts explicit `RECORDED_PATCHES=1`, reconstructing from
the suite's recorded export instead. It validates manifest shape, ordered
unique patch names, exact export contents, regular files and every SHA-256.
It uses the current trusted patch applicator with fuzz disabled; the export
contains data, not executable helper code.

The locked Linux archive, complete source inventory, executable bits and link
targets must still match. All selected trees are checked before replacement.
Suite/cache locks, resumable migration records, preserved object/configuration
hashes and final evidence rechecks remain mandatory. Unreferenced compiler
trees, recovery images and unrelated temporary files are left alone.

## Reproduction

From the integration worktree, preview before applying to the main worktree:

```sh
task build:compact-driver-sources SUITE=musb-sleep-tests TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo RECORDED_PATCHES=1
task build:compact-driver-sources SUITE=musb-sleep-tests TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo RECORDED_PATCHES=1 APPLY=1
task build:compact-driver-sources SUITE=brcmfmac-pm-tests TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo RECORDED_PATCHES=1
task build:compact-driver-sources SUITE=brcmfmac-pm-tests TARGET=/home/mishri/workspace/clockworkpi/GameShellNeo RECORDED_PATCHES=1 APPLY=1
```

Preview needs room to extract one shared source, about 1.7 GiB here. MUSB's
current evidence selects only one of its two compiler directories; its
conversion alone therefore provides no material net saving. The superseded,
unreferenced directory is preserved. The Wi-Fi suite's normal/debug evidence
selects two copies, allowing consolidation to one verified shared source.

## Validation

The 24 focused source-reuse tests pass. New coverage reconstructs a historical
patch queue, preserves object/evidence hashes, checks repeat application and
rejects corrupt bytes, symlinks, escaping/duplicate names, extra files and
changed source contents before replacement. Full `task check` passes 13 runtime
and 626 tooling tests (one optional user-systemd skip), C helper checks, Bash
syntax and ShellCheck. Logs are `.local/neo127-focused.log` and
`.local/neo127-check.log` in the integration worktree.

Both applications completed and passed the final object/configuration/evidence
rechecks. Audit records in the main worktree:

- `.local/build/musb-sleep-tests/compact-20261007T022357.166571Z.json`
  records the one evidence-backed source conversion; the unreferenced directory
  remains intact.
- `.local/build/brcmfmac-pm-tests/compact-20261007T022642.384030Z.json`
  records both normal/debug source conversions into one shared source.

The Wi-Fi application recovered about 3.3 GiB from the two copies after its
shared source had been prepared. Including that preparation, its net saving
is about 1.7 GiB. Final available space exceeds 10 GiB. Per-command free-space
values also reflect the overlapping preparation of the other suite; these
are host filesystem observations, not exact attribution of every byte.
Image assembly can now reuse the completed kernel through `task build:image`;
compilation is not repeated for this host tooling change.
