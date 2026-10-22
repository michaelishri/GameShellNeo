# Finite scheduled clock brackets (NEO-217 / NEO-192)

23 October 2026 NZDT. This is a separate, opt-in diagnostic experiment after
NEO-213's accepted development-directory admission. It preserves the original
reader and capture mode. One independently reviewed and authorized scheduled
GameShell capture completed all 256 calls and 31 pauses without a discrepancy
in that finite sample. The historical MONOTONIC guard fault and separate RAW
−750 ns discrepancy remain unresolved; PM remains unqualified.

## Discriminating observation

The original guard fault has no retained raw readings, so its magnitude cannot
be reconstructed. The later RAW discrepancy was sequence 51, immediately after
a 100 ms batch pause. That timing suggests a useful observation boundary but
does not establish an idle, migration, timer or silicon cause. NEO-213's one
complete recorder capture covered CPU 0 over only 11.9004 ms. A clean sample of
that scope cannot exclude an intermittent fault.

The new experiment requests 32 rounds with exactly these eight calls:

| Position | Clock | Route |
| --- | --- | --- |
| 1 | MONOTONIC | Python |
| 2 | BOOTTIME | Python |
| 3 | MONOTONIC | Python |
| 4 | MONOTONIC_RAW | Python |
| 5 | MONOTONIC_RAW | Explicit ARM time64 syscall 403 |
| 6 | MONOTONIC_RAW | Python |
| 7 | MONOTONIC_RAW | Explicit ARM time64 syscall 403 |
| 8 | MONOTONIC_RAW | Python |

There is one fixed 100 ms relative ARM time64 nanosleep between rounds: 31
pauses, 256 clock calls, 192 Python calls and 64 explicit clock syscalls.
Requested pause time totals 3.1 s; elapsed execution is not assumed to equal
that value. The first three calls reproduce the guard's clock ordering. The
last five bracket native RAW reads with Python values. No Python sleep or
incidental timestamp is added to the declared workload.

If a discrepancy recurs, compare the actual consumed counter and coherent
conversion tuple first, then accepted syscall values, original ABI bytes,
native integer conversion and Python values. Retain read/end CPU and writer
publication records. A result can identify the first differing boundary
without assigning an unproven hardware cause. The pause does not force a CPU
or a particular idle state. No affinity, clocksource, timer/vDSO, PM, installed
runtime, counter or boot-selector policy changes are made.

## Separate pause ABI and evidence

`tools/clock-pause.c` and its separate header build a pause-only ARM hard-float
library. Pinned Linux 6.18.54 defines syscall 407, CLOCK_MONOTONIC 1, flags 0 and
a 16-byte kernel time64 request. Each invocation makes exactly one syscall.
It saves request-before, request-after, remaining bytes, rc, errno and the
invocation count into a preallocated 72-byte observation before returning.
There is no EINTR retry. An error ends the workload and preserves partial
evidence. A pending Python signal may prevent the wrapper from returning;
the C-filled buffer is still exported with `returned:false`.

Both native libraries use PyDLL to retain the GIL, preserving the original
reader's explicit diagnostic limitation. Call slots and pause slots are
allocated before arming. Serialization and file output occur after stop and
export. The recorder retains its existing 1024-call and 2048-writer capacities.
Extra calls, writer loss, truncation, failed pauses and unresolved ownership
remain incomplete evidence. No limit increase or success-based repetition is
used. The original 45 s unit bound and 60 s independent host deadline remain in
force even if the suspect clock stalls a relative pause.

Original kernel bytes and userspace records are stored before postflight or
replay. The host removes only its successful private stage after terminal
unit inspection, unchanged-state checks, both management routes and independent
replay. Failed or ambiguous operations retain their original unit/stage;
observation loss never launches a replacement capture.

## Admission and saved Tasks

The original C reader, `clock_boundary.py`, original 384-call plan and immutable
image source pins stay unchanged. NEO-213's exact ten-header ABI admission and
strict original-image/PM-directory guards are retained. The new scheduled
operation additionally binds its own workload, runner and pause-library
hashes to a separately completed pause receipt and complete five-source ABI
map. It verifies the actual managed operation is terminal and successful,
source/output inventories match, and library imports exist in the verified
saved libc. Newly executed sources are not relabeled as original image inputs.

The existing host supervisor accepts this operation only with its explicit
runner and complete five extra files: two development adapter files plus the
three scheduled artifacts. The old raw and development runners reject a
scheduled contract. The 2 MiB contract bound remains unchanged; compact encoding
retains the full release and original manifests.

```sh
task test:scheduled-clock
task check:scheduled-clock-pause -- --linux-archive <locked-linux-archive>
task check:scheduled-clock-workload -- \
  --image-checkout <diag27-checkout> --reader-build <original-reader> \
  --runtime-capture <verified-ELF-inventory> --release-manifest <release.json> \
  --pause-build <qualified-pause-build> \
  --boot-id <expected-boot> --card-cid <expected-card> --store-uuid <expected-UUID>

# Local read-only plan, with no Mac/GameShell contact:
task dev:clock:scheduled -- <same-explicit-artifact-and-identity-arguments>

task report:clock-scheduled -- --kernel <saved-NDJSON> --users <saved-JSON>
```

Live use additionally requires `--apply --hardware-checkout <frozen-checkout>`,
fresh independent Standards and Spec acceptance, and a separate exclusive
coordinator device lease. Current boot/root/runtime and health must be measured
fresh; an old successful capture is not admission for another operation. The
single capture below used reviewed source `6524aea`; its lease is now released.

## Offline qualification and retained limits

The branch initially used frozen `d0056fd`, then adopted independently accepted
published NEO-213 at `5505fd90e9cd98038fef785bfe6ba19e6548a739`. Uncommitted new
files and the original qualification attempts were preserved during adoption.
The original reader's image/source/ABI identity remains separate from the new
pause library and workload.

The refreshed pause build is
`7ae7c98b58ce415791ba0db4f1902391`, receipt SHA
`cba7ee935c122fd71f283c29a74f38edf61cdfe6203326f5a10f2995edfaab76`.
Managed run `6565b144d86d4cafbed4e4b8dd08fdcd` exited 0 without OOM or stop.
It executes four native UBSan and four ARM buffer fixtures: success, EINTR,
EFAULT and changed-request evidence. The actual ARM shared-library probe makes
one successful 100 ms pause and one declared SIGALRM/EINTR call, preserving the
remaining raw timespec and verifying no retry. It hashes all ten build/helper
inputs before/after and verifies the ARM ELF, hard-float ABI and five locked
Linux sources. The earlier seven-input receipt remains historical.

The real read-only scheduled plan passes against the complete original image,
reader, runtime evidence and release, plus that new pause receipt. Focused
tests cover exact ordering and capacities, separate MONOTONIC/RAW −750ns
fixtures, conversion boundaries, partial and extra records, signal/errno
preservation, strict old-entry refusal, bounded full staging, complete receipt
maps, source/output corruption, failed managed ownership, unsupported imports,
failed postflight and cleanup, timeout and no relaunch.

Actual ARM Python/libc qualification passes in
`3be43f3e4fab4242ad24f022894a1b84`, receipt SHA
`8bff42588612c9909938bfd69239532ef911c5f5d624aee16ab97ff4534a9018`.
Original managed run `d66ac2c10ed14a1792fd6d562112cb1a` exited 0 without
OOM/stop. Fifteen pure clock/pause/replay tests pass on native Python and the
actual extracted ARM Python. The ARM workload then executes all 256 clock
calls and 31 pauses using the unchanged original reader and the new pause
library, whose SHA is
`e59c4dda6ef2ed4db4d193c3643ee89a4958873fc17999ee5a950671cf37f639`.

The managed workload uses a private regular sparse partition copy under this
checkout's ignored workspace, with the source image bound read-only. It verifies
extracted Python/libc hashes before execution and again afterward. The actual
files match the verified original inventory: Python SHA
`c5b8ff962e01a7e6fa49090d2f646e3c85a7e5806907e4e64dd7d619c7c388a7`
and libc SHA
`f7854d98c852da9c89d2cbdbeb980c5d1258ba6d624486f76b24c7741a9649b7`.
It uses a fake recorder explicitly labeled ABI/workload-only. These outputs
supply no genuine kernel or GameShell evidence.

Original failures are retained: two pre-container source-parser refusals for
comments and the exact `const clockid_t` declaration; synthetic test setup
errors for ELF field spacing and a missing mock OUTPUTS tuple; and original
managed run `fa7e6ae84499412bb919ec6b436f8bde`, which exited 1 without OOM/stop
because the builder lacks Paramiko for host-admission tests. The correction
keeps those host tests in their authorized host context and limits managed
native/ARM tests to the pure clock/pause/replay suite, followed by the actual
extracted ARM workload. No packages, SSH stubs or network access are added to
hide the dependency difference.

## Combined source and review checkpoint

After all original writers were terminal, the branch adopted accepted published
main `49b1c237ea3cd822195362f9462285fc1ee9a75c`. The sole source-merge conflict
was the report index; both exact entries are retained in order 302, 298. Every
clock/pause source and actual pause-build admission input remains unchanged.
The broad qualification snapshot has one context difference,
`tools/kernel_candidates.py`, which registers the accepted isolated USB
candidate. The entire old snapshot is not claimed byte-identical.

The selected 33 production patch names and hashes exactly match the completed
original image. Their canonical map SHA is
`d88de734919a86545b006d5298c79576938003c57436c4c0ccf4dbccce70e081`.
The original reader lock keeps its historical `-gameshellneo25` suffix;
image/pause inputs retain `-gameshellneo26`. The exact ABI sources and all
other Linux fields remain separately verified; neither receipt is relabeled.

The real read-only plan passes again on the combined source, including every
required receipt/source check. Its exact executed serialization is 1950028
bytes, SHA
`01d0e05379c43985e4cca4344c9e8310b65c9b90f48b2d12f88ddcffa1c27eac`,
within the unchanged 2 MiB limit. Full combined `task check` passes 24 runtime
and 1331 tooling tests, nine expected skips, C checks and shell lint. All 30
focused host tests pass. Combined log SHA is
`bfd36aec8b47f7e91cb41178c9e4dde2e2e17fc0f9d483050e098396ffae82ad`.

The actual saved replay Task independently retains synthetic MONOTONIC and
RAW −750 ns events as complete diagnostic evidence, while a synthetic
2048-writer-loss stream is incomplete. These are explicitly named synthetic
fixtures, not claims of new hardware failures. Source image, original reader,
actual extracted runtime, ABI/helper inputs, original failed jobs and exact
records remain preserved. No current owned container remains active.

Private `.local/scheduled-clock/evidence-index.json`, SHA
`71915f1eccecb986f9bc258103adb6ac708b39cc8e7c3d88993fd78276adca33`,
links 98 source/artifact files and the final proof, SHA
`d0df6e443f2a0e9e51d6cbcb60e59a30a27249301c3f9bde6e78cd1a48276ba1`.
The original source image was rehashed unchanged. The proof distinguishes
actual clock/ABI inputs from generic registry context and historical
reader/image lock identities.

## One authorized GameShell capture

Entirely fresh Standards and Spec reviewers accepted frozen
`6524aea6e2a6226e54fabf336cf63eaf64f0fada` with zero required or optional
findings. Their retained report SHAs are respectively
`be6767624c35d0d27824e993979adf4a126110eda0082f328230411d1f9dc597`
and `c73a83c46408dc97481b1eee37cbe19ee5030d636691574cfcfbd89fd655aaf9`.
The original checkout and its 98-artifact index remain unchanged.

Exclusive lease `device-neo217-01` authorized exactly one scheduled operation.
Original host session 60631 / Task PID 997556 started at 13:13:45 UTC on
22 October and exited 0 at 13:14:51. Original private capture
`.local/diagnostics/20261022T131425.941685Z/` contains the exact records,
runtime/source snapshots, health inspections, unit states and replay.

| Observation | Retained result |
| --- | --- |
| Clock calls / pauses | 256 / 31; exact declared order and relative requests |
| Kernel stop / writer records | Manual stop; 458 writers; zero loss |
| Read CPUs 0 / 1 / 2 / 3 | 120 / 24 / 8 / 104 calls |
| First-to-last RAW interval | 3,157,333,209 ns |
| Boundary / kernel / userspace findings | Zero in this sample |
| Actual contract | 1,950,028 bytes; SHA `01d0e05379c43985e4cca4344c9e8310b65c9b90f48b2d12f88ddcffa1c27eac` |
| Kernel records | SHA `0285ba8b8778cac662f34d4b583c3ea3bd67b0db44c265127b2af56a4665ce00` |
| Userspace records | SHA `ba6acd12e6081a525c621bbc134114cba9e86f22c2072b97027a1738672ff7cc` |

The independent saved `report:clock-scheduled` Task exited 0 and exactly
reproduced the original analysis. Its records retain the actual consumed
counter, coherent conversion tuple, writer publications and userspace values.
No recurrence occurred to localize either historical fault. Coverage of four
CPUs here is a finite observation, not migration, accuracy or reliability
qualification. A pause does not establish a particular CPU idle state.

Fresh admission measured boot `cea309a9-bea5-49d7-8d41-e462ddd57e89`,
kernel `6.18.54-gameshellneo26`, build ID
`a545d309c5f43e3e047cc124322e75e125aef3f5`, and the actual diag27 directory
root `/systems/diag27/root`, inode 131075 / device 179:3. The card CID,
store PARTUUID/UUID, release/deployment hashes and actual Python/libc match
the explicit contract. Before/after snapshots are identical. Both same-process
vDSO clock exports remain absent. Services remain active with restart counts
zero, PM success/failure remains 0/0, and the protected 282-record kernel
checkpoint remains unchanged at SHA
`aef844482f730b1309d9a112a38c9dc0d1339850ef728ad6cfc15faa4384978a`.
USB and independent Wi-Fi checks pass. This new boot's clean counters do not
erase the historical failed boot or permit PM.

The exact Razer Kiyo 5 s / 2 fps session
`20261022T131121.217516Z` produced 10 frames and stopped. Actual first and last
JPEGs show the readable tty1 login console. They do not qualify physical input,
responsiveness, latency or power. A local wrapper initially expected the Task's
displayed `frame_count` field in the raw result; the original raw schema uses
`frames`. That KeyError happened before transport loading. It is retained;
the same actual camera result was inspected without another camera capture.

The separately granted read-only v2 helper, SHA
`a174dcc4c5a1905f2777c782947d1b21ee54b886b59a758d0ebe860d969df2a7`,
ran fresh before and after the operation. It verifies the existing whole-root
vfat p1 mount at device 179:1, the actual block device and pinned PARTUUID,
then all three flag hashes. NEXT, GOOD and RECOVER all remain recovery; diag27
is unconfirmed. Unlike NEO-213's historical postflight-only flag observation,
this operation has a real pre/post comparison. No historical receipt is
retroactively upgraded.

The original unit is
`gameshellneo-clock-boundary-3ff9ba9012e94313859cc8d0d2f15080.service`,
original device PID 923. Retained states show successful exit status 0 followed
by inactive/not-found with MainPID and ControlPID zero. The owned stage
`/tmp/gameshellneo-clock-boundary.EVU7EtYL` is absent; no recorder descriptors
or active diagnostic units remain. The host removed that successful private
stage only after independent replay and postflight. No second capture, PM,
reboot, counter reset, clocksource/affinity change, installed replacement or
boot-selector write occurred.

Postflight receipt SHA
`38b540462ea4af11e98892cda76535b6673336fa7f2afba2bc56ee58fd981df1`
links 45 original files. The coordinator independently streamed every linked
hash and checked state/ownership before accepting and releasing the lease.
All original host sessions are terminal. An additional local index audit used
an inappropriate whole-file read of the image and lost its observer result;
its explicit inconclusive note remains retained. It is not a passing hash
check and was not repeated. The actual capture's normal admission and the
independent reviews remain separate evidence.

The separate final checkout's stable `live-evidence-collation-v2.json`, SHA
`556752e4eafe3b88d80cfbfe9ca9d7a66535e3bee9e3717f5d03af404e241f06`,
collects 153 expected artifact hashes: the preserved 98-file offline index,
the 45 accepted postflight files, and the index/receipt/helper/proposal/review
sources. The original offline hashes are carried from both accepted fresh
reviews, rather than claimed as a successful result of the lost extra audit.
The 45 small postflight files were streamed again during collation. The
original helper, proposal and first collation draft remain retained.

## Final accepted context and remaining gates

Final documentation is prepared in a separate checkout. It adopts accepted
published main `02c633a0349ad986fe384cc0f94e26663baa3df3`, retaining NEO-215's
isolated MPFS work, through merge `45ed6cd`. The sole merge conflict was the
report index; exact report entries 302, 300 and 298 remain in that order.
The physical capture executed frozen `6524aea`, before this context adoption;
it is not relabeled as execution of the final merge.

The clock, pause, ABI and reader sources remain byte-identical to the executed
source. The shared Taskfile additionally contains accepted MPFS Tasks; its
clock sections remain identical. Generic qualification snapshots therefore
have explicit context differences rather than whole-tree equality. The final
private proof records every actual admission input separately and preserves
the unchanged 33 production patches and immutable image/runtime identities.

Final independent review and publication remain required. NEO-217's finite
experiment does not close NEO-192 or admit dependent PM. Any later experiment
needs its own explicit scope, fresh evidence and exclusive device grant.
