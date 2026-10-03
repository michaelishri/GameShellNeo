# Shared kernel sources for driver checks

4 October 2026, Pacific/Auckland. NEO-104.

Driver configuration matrices previously extracted a complete patched kernel
for every configuration. The three recent MUSB candidates each retained six
copies of essentially the same 1.5 GB of source content. This work shares source
within each suite while preserving separate outputs and historical evidence.
It changes host build/storage tooling only, with no device, image or driver patch
change. Diagnostic.18 remains the staged hardware candidate.

## Source and output identity

`tools/kernel_sources.py` keys the shared source by the Linux tag, archive and
upstream configuration-seed hashes, and complete patch manifest (including the
generated overlay patch). The cache is local to a suite under
`.local/build/<suite>/.sources/source-<SHA256>/source`. Different patch queues
remain distinct. Compiler, image-version and configuration changes can reuse
source; the existing configuration-specific scratch identity and output paths
remain separate.

A new cache is extracted from the checksum-verified archive and receives the
complete patch queue through `kernel-inputs.py`. The resulting patch manifest
must match the expected manifest. Every path, file content, owner executable bit,
and symlink target contributes to the tree fingerprint. Directories are included,
source symlinks are recorded without following them, and special files reject
verification. Timestamps, ownership and group/other permission bits are omitted
so differing umasks do not invent source changes. This fingerprint includes the
`.orig` files left by successful patch application. Reuse verifies the tree
against its recorded identity; a patch stamp alone is insufficient.

`tools/kernel_checks.py` mounts the cache read-only at `/kernel-source` in the
pinned builder, uses a separate `O=` output for each configuration, and runs
`merge_config.sh` from that output directory. The last detail matters because the
merge script creates temporary files in its current directory. New scratch trees
receive relative source links. Existing real source directories are checked and
left for explicit compaction. Builds reject an incomplete source migration.

The helper also retains the compile-only configuration support used by the CPU
and MUSB candidate matrices: explicit overrides, distinct configuration identity,
ARM/kernel object paths, and disabled hidden Kconfig symbols interpreted as `n`.
Those checks do not relax the normal board configuration validation.

## Explicit migration and recovery

The README documents two repeatable tasks:

```sh
task build:compact-driver-sources SUITE=musb-sleep-tests
task build:compact-driver-sources SUITE=musb-sleep-tests APPLY=1
task check:kernel-source-reuse
```

`TARGET=/absolute/path/to/worktree` can select a different worktree of this Git
repository. Source compaction supports the MUSB sleep and CPU-idle suites plus
the five existing Wi-Fi suites. Preview may materialize the shared source and
therefore needs about 1.7 GiB of headroom, but leaves legacy copies intact.

Compaction holds the same suite lock as its compiler tests and a separate source
lock. It accepts only known scratch layouts referenced by completed evidence.
It verifies every referenced object and configuration hash and compares every
selected source against the independently extracted and patched reference before
replacing any source. Unreferenced scratch, recovery images, full kernel builds,
downloads, device captures and provisioning are outside the deletion scope.

Each replacement durably records its source identity, renames the verified old
source to a retired directory, publishes the shared-source link, and deletes the
retired copy. A repeated invocation can complete an interrupted process: before
link publication the retired source must still be complete; after publication,
any remaining retired entries must match the reference. Unexpected entries,
symlink escapes, changed outputs, missing evidence, active locks or an altered
migration record stop the operation. The task preserves original evidence and
outputs and writes an incremental audit containing their hashes and disk-space
observations. Existing Wi-Fi scratch pruning recognizes verified-layout cache
links and removes only the superseded scratch/link, retaining shared caches.
There is no automatic cache eviction.

## Validation

The host regression suite passes 13 runtime tests and 483 tooling tests, with
only the existing optional user-systemd test and unavailable prepared-Armbian
fixture skipped. Both small C checks and Bash/ShellCheck pass. The new source
suite covers 20 scenarios, including identity changes, archive/patch mismatch,
changed source/configuration/object data, permissions, links, busy locks, missing
evidence, partial deletion, journal recovery and idempotence. Eight pruning
tests include retaining the shared cache when an obsolete linked scratch is
removed.

The repeatable ARM check first requests the ordinary board configuration, then a
compile-only configuration with suspend, hibernation, PM sleep and PM disabled.
It compares source identities, verifies different configuration hashes and
unchanged source contents, deletes the board object and requires identical
regenerated evidence. An initial incomplete request disabling only PM was
correctly rejected because Kconfig's remaining sleep selections kept PM enabled;
that failed run remains in the rotated log. It is not counted as qualification.

Both ARM configurations passed, with one source cache, distinct `.config`
hashes and ARM ELF32 objects. The board configuration passed all 164 project
assertions. Regenerating its deleted `musb_core.o` produced the same SHA-256:
`1cfeb7cafdaf4a7ad0e841cbc19dce4504065b69214b3994f2bb92a78a799d41`.
The no-PM object SHA-256 is
`f7377f54bb3bc99676f304c66d25e7292714e673c70565b00cc4294bed13f30f`.

Private repeatable evidence in the maintenance worktree:
`.local/build/kernel-source-reuse-tests/compile-evidence.json`, SHA-256
`895a6fa33bc493baf47e61bf5b43c2cd8ee1c1e13a943f79d35a8ac4f3ad24a3`.
The shared tree fingerprint is
`56aecbd9d3e1372f861595d18c00de679eb73d6447b1fce5d23d9df6e4900560`.
The 85 source symlinks resolve within this verified source tree. Compiler output
is retained in `.local/build/kernel-source-reuse.log`; the ordinary board and
no-PM output directories remain separate.

The three recent MUSB worktrees now retain one source each instead of six:

| Candidate worktree | Source copies | Net source allocation saved | Observed free-space increase during apply |
| --- | ---: | ---: | ---: |
| `musb-wake-irq-policy` | 6 → 1 | 8.30 GiB | 9.95 GiB |
| `musb-startup-pm` | 6 → 1 | 8.30 GiB | 8.30 GiB |
| `musb-callback-lifetime` | 6 → 1 | 8.30 GiB | 8.29 GiB |

That removes 15 redundant full source copies, approximately 24.89 GiB of
allocated source storage. The wake-policy cache was created by its preview, so
its apply-only free-space increase includes all six old copies; the other two
apply runs include creation of their replacement cache. Filesystem free-space
observations also include ordinary concurrent host activity. Free space after
cleanup and retaining the independent ARM validation cache is approximately
28.9 GiB, compared with about 5.7 GiB before this work.

All 18 configurations retained their object/configuration hashes. Original
matrix and other evidence files also retained their hashes. A final independent
read checked the preserved hashes, 18 source links, three source caches and
absence of unfinished migration records. Candidate tracked files are unchanged;
the old branches retain their historical compiler helpers. Bring the new helper
and `kernel_sources.py` forward together when extending those branches, as the
README explains.

Private compaction audits, relative to the main repository's `.local/worktrees/`:

- `musb-wake-irq-policy/.local/build/musb-sleep-tests/compact-20261003T152509.077196Z.json`
  SHA-256 `6154d51c0e61ba176afec16cc80d82cb312418955c46b08dde836204dd2bf56d`.
- `musb-startup-pm/.local/build/musb-sleep-tests/compact-20261003T153554.964053Z.json`
  SHA-256 `7c21d3ffa40e9bda1982f218b4f949e1b483af2b5d292fc6bbde1751562d5fc7`.
- `musb-callback-lifetime/.local/build/musb-sleep-tests/compact-20261003T153959.172765Z.json`
  SHA-256 `a0591297d1a89e5038e86a303f0f136e20653726a4d4287699710226034a5023`.

## Limits

Sharing saves host storage and avoids repeated extraction/patching. Full source
fingerprinting still costs disk reads and CPU time. No build-speed percentage is
claimed; incremental checks can spend more time verifying source than the old
patch-stamp-only reuse. Cooperative locks exclude the repository's build tasks,
not arbitrary external file writers. Process-interruption recovery is tested; abrupt host
power loss and filesystem corruption are not fault-injected. The locked archive
and patch queue remain available for regeneration. This work makes no claim
about GameShell power use, USB recovery, sleep reliability or latency.
