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
The earlier 1295-case source checkpoint remains historical. This source
checkpoint preceded the independent reviews and single live operation below.

## Independent review and actual awake operation

Both peer reviews cover fixed source
`98aff1fe86689c916cd930f2b5c5a8bb218088f0...23c4133fa4f86a963152eca86c9b7315a4219264`.
Spec reports zero actionable findings. Standards reports zero documented
violations and zero required fixes, with one optional maintainability note:
three independent sites construct the same deployment-manifest shape. A
future pure helper could centralize that shape while retaining the separate
hash/source comparisons. The note is preserved without changing qualified
inputs. Canonical private reviews are `neo213-23c4133-spec.txt` and
`neo213-23c4133-standards.txt` under `.local/coordination/reviews/`.

The coordinator granted exclusive awake-only lease `device-neo213-01` at
11:19:04 UTC on 22 October. Both frozen-checkout status operations pass:
USB capture `20261022T111952.343801Z`, Wi-Fi `20261022T112004.939587Z`.
The five-second Kiyo baseline `20261022T112022.363230Z` contains ten frames
and stopped successfully. Actual first/last JPEG inspection shows the same
readable tty1 login console; it does not establish physical input or clock
health. All raw images remain private.

Exactly one `dev:clock --apply` ran using the reviewed source and qualified
artifact arguments. Capture
`.local/diagnostics/20261022T112138.366426Z` in the new checkout retains the
originals. The actual staged compact contract hashes to the qualified
`8f4a387bdd33776dbebc9d26ff68d9e51ebdfee7805d62ed52513083c4f1183f`.
The owning unit was
`gameshellneo-clock-boundary-e7611efe551f44e796899071b6734eda.service`,
PID/TID 661. Its original normal exit is code 1/status 0; only after retaining
that evidence did supervision retire it. The final state is inactive,
not-found, MainPID/ControlPID 0. No launch or measurement was repeated.

Current process snapshots before/after match exactly: boot
`cea309a9-bea5-49d7-8d41-e462ddd57e89`, kernel26 and the expected build ID,
source/release/deployment manifests, CID/UUID/PARTUUID and actual p3 directory
inode **131075**. Current Python and mapped libc match the release and saved
ELF ABI evidence, at their exact sizes/hashes. The clocksource remains
`arch_sys_counter`; both same-process vDSO clock exports are absent. The
owner is one task in the initial PID namespace with the expected time
namespace and unchanged CPUs 0–3 allowed affinity. No affinity is changed.

The original 384-call stream is complete, aligned and independently replayed:
128 calls per clock and 96 per route, **zero boundary findings or decreasing
kernel/userspace values in this window**. It contains two writer records,
zero lost writers, and one accepted attempt for every call. Every actual read
and end CPU is **CPU0**. The first-to-last consumed counter span is 285610
ticks, approximately **11.9004 ms** at the recorded 24 MHz timer frequency.
This qualifies the end-to-end evidence path; it supplies neither multi-CPU
coverage nor recurrence/clearance of the intermittent clock fault.

Before/after awake health preserves PM counters 0/0, all service restart
counts 0, empty failed-unit output, taint 0, USB power/configuration, display,
charger, Wi-Fi and governor policy. The complete 282-record protected kernel
checkpoint and its 282-record anchor are unchanged; anchor SHA is
`aef844482f730b1309d9a112a38c9dc0d1339850ef728ad6cfc15faa4384978a`.
These are current-boot observations. They do not overwrite the original
diagnostic.25 restart/clock incident. The independent Wi-Fi proof also passes.

Successful downloaded originals were replayed before removing only the owned
`/tmp/gameshellneo-clock-boundary.jNcWEE3A` stage. A final read-only postflight
proves that stage absent, no active clock/PM diagnostic units, no remaining
process/control PID and no open recorder descriptor in any process. It also
reads NEXT, GOOD and RECOVER, all at the recovery digest
`dce033ba9041858b244d2f15c1f1b3111057d93756f64b07f02c73ec0de1ef84`.
**Flags were measured postflight only**; no fresh before-flag sample exists
for this operation, so unchanged flags across the operation are not claimed.
Diagnostic.27 remains unconfirmed. The coordinator released the device lease
after checking this receipt; no further live operation is authorized by it.

| Retained live artifact | SHA-256 |
| --- | --- |
| `kernel.ndjson` | `aa40f8c551edecfd433a4d7acb060e19657cf669767c13b3c796e6b92da3dc62` |
| `users.json` | `00bafb80e0e9460f2e34ccc4f5c18df160b7d2858978bf5d080b8bf1badd0530` |
| `analysis.json` | `58093d96c3e7624f95e56d1f48bf75c74fed2386fa34fef54f02074a41f2ae4c` |
| `host-summary.json` | `2e566466da36c14d8cc52188aee63b772db272d286acff65998ff263c06f16e3` |
| `unit.json` | `485dab1183ae796b6804b52f0dbcb35bec3550ef9164d129ac5ab04b49ef88fe` |
| `read-only-postflight.json` | `9a15e170f0b0772b3a4d12b9455984b8a753b650c4f8b9d1a08c4ffc2c0cb37c` |
| Separate offline replay | `5f52ee1bdcc60abd2ba90e43061870e3ed0f8fe4357c5d4b4719a4fad04cdd16` |

No PM, reboot, blanking, confirmation, service/runtime replacement, counter
reset, clocksource/affinity policy or charger change occurred. NEO-192 and
all dependent PM gates remain open. NEO-213's source and actual-capture
milestone is ready for independent final evidence and combined-tree review,
then serialized publication/integration and closure.

The frozen `d0056fd` checkpoint incorporates independently accepted published main
`5a2f362a39e49415b6a73e732219007ab8f4eb00`. The only merge conflict was the
report index; its resolution retains the exact report297 and296 entries in
that order. All six clock source/test files and clock Task sections remain
byte-identical to reviewed source `23c4133`; all Wi-Fi source/tests and report297
match accepted main. The production source lock, kernel queue and fragment
are unchanged. Combined `task check` passes 24 runtime/1297 tooling tests,
nine expected skips, C checks and shell lint; its log SHA is
`8c629d89a941f66f8524a5f4b17dd68fa8d02a7cbadbc7664734e9ce2f2cbb13`.
Private `.local/development-clock/final-evidence-index.json`, SHA
`d9e73cd70b1574ed646ea3abff025556293f75de90bf27e2c62727a971ee8c70`,
links source-unchanged proof, independent source reviews, both completed host
checks, managed reader evidence, exact live originals, separately rerun replay,
camera/status receipts and the terminal ownership/flag postflight.

## Fresh review correction: complete ABI provenance

The additional fresh Standards review of `d0056fd` has zero required findings
and one optional note about repeated result/replay/cleanup flow. The additional
fresh Spec review found one required P2: the original archive comparison took
its required header names from the receipt itself. An empty or matching partial
map could therefore pass. Both original review reports and the frozen source
remain preserved; optional refactoring is deferred.

The correction fixes the expected set at all ten headers from the original
reader's time32/time64, syscall, clocksource and ELF provenance. Empty, partial,
extra or malformed maps and malformed digests fail before opening the archive;
the complete map must then match the actual locked archive contents. Four new
tests cover these cases, including each single missing header, changed contents
and a missing archive member. All **18 focused tests** pass. Full `task check`
passes **24 runtime and 1301 tooling tests**, nine expected skips, C checks and
Bash/ShellCheck. The isolated fix checkout's
`.local/build/development-clock-abi-check.log` has SHA
`c71d29a6bf6ade8fcf649ca76832e86b470024d8cddce9b9b1674df3dba36723`.

The actual original receipt already contains all ten correct headers. A fresh
read-only `dev:clock` plan verifies it against the complete original image,
kernel artifacts and locked archive. Its contract equals the earlier valid
contract except for the explicitly changed `development_clock.py` source hash.
The original reader inputs and binaries remain unchanged. An offline replay of
the exact pre-fix comparison also reproduces its acceptance of empty and partial
maps; the fixed validator rejects both.

The hardware capture above executed reviewed source `23c4133` in the preserved
`d0056fd` lineage. Its original adapter hash and all original receipts remain
unchanged. The corrected admission code has been verified **offline only**;
no new hardware capture was requested or performed. The complete original
receipt preserves the validity and stated limits of the historical capture.

The separate fix checkout retains
`.local/development-clock-abi/evidence-index.json`, SHA
`5930fa63e0bafd2938b81d704c60e3d860d1c1b2a8d4b598ea318637f3646783`,
linking 40 artifacts, including all 29 rehashed original evidence files, both
fresh reviews, the actual reader receipt, rejection reproduction, real local
plan and completed host checks. Fresh independent reviews of the corrected tip
and separate serialized publication remain required. NEO-192 and PM gates
remain open.

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
