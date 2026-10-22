# Development-directory clock provenance (NEO-213 / NEO-192)

23 October 2026 NZDT. The capable diagnostic.27 system is installed as a
directory on the development card. It contains the bounded kernel recorder,
but the original raw-image capture contract intentionally cannot identify
this changed deployment as its original flashed image. NEO-213 adds an
explicit, opt-in awake diagnostic adapter. NEO-192's original MONOTONIC fault
and the saved RAW −750 ns discrepancy remain unresolved.

## Separate identities

The adapter keeps three independent provenance chains:

1. The original diagnostic.27 raw image, image manifest, canonical kernel
   queue, resolved configuration, all completed kernel artifacts and ELF
   build ID. The full 4 GiB image is hashed again before any SSH import.
2. The unchanged original ARM reader build, its source/output hashes, actual
   native/ARM fixture outputs, exact ABI header hashes and verified copied
   Python/libc ELF evidence. Its original Linux lock is retained. It used
   `-gameshellneo25`; diagnostic.27 uses `-gameshellneo26`. Only this version
   suffix may differ, after all other Linux lock fields, pinned builder,
   actual ABI headers and executed reader sources match. The reader is not
   relabeled as a newly built image.
3. The new adapter's actually executed source hashes. These files are staged
   privately and are not claimed to have been included in diagnostic.27's
   original image. The original recorder, C reader, workload and replay
   implementation remain unchanged.

The exact original image-manifest bytes are preserved; decoding/reformatting
them would change the source hash. The deployed manifest must instead match
the existing explicit development transformation exactly, including its
source raw-image hash, original manifest/fstab hashes, slot and p3 PARTUUID.
The exact canonical release bytes and catalog digest bind that transformation
to the installed release. A copied label alone cannot admit a capture.

The saved runtime inventory is historical offline ABI evidence. The running
Python executable and actually mapped libc are independently read and hashed
again in the current owning process before and after capture. Their exact
paths, sizes, contents and release-manifest hashes must match. Historical
boot counters are never reused as fresh health admission.

## Actual root and capture ownership

Before opening the recorder, the adapter requires the complete ext4 p3 store
at `/run/gameshellneo-store`, its exact device number, card CID, filesystem
UUID and PARTUUID. Store subdirectory aliases, loop devices, overlays,
symlinks and changed identities fail closed. The running `/` must have the
exact device and inode of `systems/<slot>/root`, and its kernel mount FSROOT
must identify that directory. Unique command-line values and the independent
early-userspace/root markers must agree. The installed battery guard retains
its exact release hash; no live source replacement is performed.

The original raw-image `device:clock-boundary` behavior remains strict. Its
image-manifest comparison still rejects a development-directory manifest.
The PM validator's explicit directory rejection is unchanged. The new runner
requires both adapter files and the explicit development contract; the
default host path cannot select it accidentally.

Hardware transport, credentials, host-key records and the PM-operation lock
belong to the frozen `musb-restart-integration` checkout. The adapter loads
that context only after local checks pass and does not copy private config.
Before/after inspection uses that checkout's exact preserved inspection
bundle so an existing protected kernel checkpoint is never rewritten to fit
new source. Both USB operation and independent Wi-Fi proof are required.

One uniquely named transient unit uses the existing 45-second device limit,
60-second independent host deadline and explicit termination verification.
Lost launch acknowledgement never causes a second launch. The original
384-call plan, absent same-process vDSO clock exports, single owning task,
initial PID namespace, exact kernel build ID/config and recorder-exclusive
descriptor are retained. No PM, reboot, service restart, counter reset,
affinity/clocksource change, display blanking or selector confirmation occurs.

Original kernel bytes and userspace results are saved before postflight or
analysis. Failed or partial work retains its original stage, unit state and
files. Complete downloaded results are replayed independently before removing
only that successful private stage. A timeout is not proof of termination.
All summaries retain `pm_admission: false` and
`clock_reliability_qualified: false` even when a short capture is clean.

## Saved commands

```sh
task test:development-clock
task check:development-clock-reader -- --reader-build <original-reader-directory>

# Default is a local, read-only artifact/provenance plan; no device connection:
task dev:clock -- \
  --image-checkout <diagnostic27-source-checkout> \
  --reader-build <original-reader-directory> \
  --runtime-capture <verified-runtime-ELF-directory> \
  --release-manifest <exact-release.json> \
  --boot-id <current-boot-uuid> --card-cid <expected-CID> \
  --store-uuid <expected-filesystem-UUID>
```

Actual execution additionally requires `--apply --hardware-checkout
<frozen-hardware-checkout>` and the coordinator's exclusive device lease.
Resolve all artifact paths first. No ordinary image build or card movement
is needed for this adapter. Physical input/default confirmation and PM
qualification remain separate gates.

## Offline qualification checkpoint

The first real local plan passes against these preserved artifacts:

| Identity | Value |
| --- | --- |
| Original diagnostic.27 raw image | `f51b91fe7cfcfb24747e137a0c2bac46e9a0d12e0dc995500fad5dd9200f8617` |
| Original source manifest | `c14bb9f43d9de58ee5268482389754338110ec84aea6f364e298ca4dd6b9d4f1` |
| Release manifest | `ec5041df2e0321217273576b8a9b11f14b6e6d1096dce6c3b9c493eaa625cc9f` |
| Deployed manifest | `4ab997d27be010a53e9bf27d45e7f89f819e566016b03293666e0e3c82fe44b7` |
| Kernel GNU build ID | `a545d309c5f43e3e047cc124322e75e125aef3f5` |
| Original reader build receipt | `e2d0c4479e55e12b7558c4a7f2fb5e1138fbcb6245f625ad01fcc129f27ae184` |
| Original ARM reader library | `41f2dbb4b4b88e1014a1693277a64a95df39b81823ee515e70b2ce5845e680c1` |

The source artifact checkout is `ext4-security-attributes`. The reader is
`musb-restart-integration/.local/diagnostics/20261011T130856.669104Z`;
the copied runtime ABI inventory is `20261009T230039.014366Z` in that checkout.
The release bytes were recovered from the fresh expansion checkpoint and
verified against its independently recorded exact digest above.

Fourteen focused adapter tests pass, including changed card/UUID, wrong actual
directory inode or mount FSROOT, aliases, duplicate boot arguments, altered
catalog/source/deployment/marker/guard/runtime, missing staged dependencies,
legacy raw-manifest refusal, failure before any transport import and the exact
large-contract upload/download verification path. The
existing clock-focused suite passes 120 cases at its earlier checkpoint.
The unchanged original reader also passes fresh managed native and ARM/QEMU
execution and independent replay of all 27 actual ARM byte buffers.

The initial managed replay is
`.local/build/development-clock-reader/6a66d54a35de497b972abeec63f38499/qualification.json`,
managed run `2d1bb02115d34d1dbfa4f5b068825f21`. The initial YAML invocation
failed to parse unquoted CLI template braces before starting a container;
quoting is corrected and its original result is retained. Inspection also
caught exact-manifest formatting and an unstaged module dependency before any
live execution; the standalone staged-module test now covers the latter.

The final input-pinned native/ARM replay is
`.local/build/development-clock-reader/5d861ddb57f244b6a728a4c90c6bcd1e/qualification.json`,
SHA `2ba26eac2733650c8a5e180a51cafbc007c0d64aa6266d2a7fa0feb6caaf91a1`,
managed run `54271a9702474ce5bbe2b82bd2425d7a`. All original reader outputs,
ABI/library fixtures and qualification sources retain their before/after
hashes. This establishes the unchanged reader's native/ARM behavior; the
new host wrapper has its own source/tests and is not attributed to that old
reader receipt.

The real contract exposed a prelaunch size boundary: indented encoding is
2121759 bytes, above the existing 2 MiB limit. The final host writes bounded
compact JSON, retaining every original field in 1949039 bytes. The exact
planned payload SHA is
`8f4a387bdd33776dbebc9d26ff68d9e51ebdfee7805d62ed52513083c4f1183f`.
Its private `final-payload-qualification.json` records both lengths, equality
after decoding and the actual host source hash. A 23000-entry staging fixture
executes the actual local-write/upload/download verification path; oversized
inputs are refused before SSH. The initial test fixtures underestimated the
entry count needed to cross the bound; their failures remain separate from
the corrected successful fixture. The 2 MiB production limit is unchanged.
Passing a development contract to the default raw runner is also refused.

Final `task check` passes **24 runtime and 1297 tooling tests**, nine expected
skips, both compiled C checks and Bash/ShellCheck. Log
`.local/build/development-clock-host-check-final.log` has SHA
`7eae5c49d7a94d027b66089a3699d14727837ced2c65bc151a960a9218c4790d`.
The earlier 1295-case source checkpoint remains historical. Independent
Standards/Spec reviews and live execution remain pending at this checkpoint.
No Mac or GameShell operation has occurred for NEO-213 yet.

## Interpretation and next causal work

The original guard failure lacks raw readings; its magnitude cannot be
reconstructed. Report260's RAW discrepancy is a distinct event, not an
attributed recurrence. The recorder must retain consumed counts, accepted
conversion tuples, actual read CPU, writer records, syscall results and
userspace values before any conclusion about their failing boundary.

A complete short capture supplies an actual end-to-end recorder qualification
and current provenance. It cannot exclude a rare fault or distinguish a
silicon/idle/migration cause without a recurrence. Analysis must first compare
kernel-to-ABI conversion and tuple arithmetic, then examine any decreasing
consumed counts against writer transitions and per-read CPU attribution.
If no recurrence occurs, design and independently qualify a focused bounded
next observation from those source boundaries; do not repeat until clean,
switch clocks, relax validators or declare NEO-192/191 cleared.
