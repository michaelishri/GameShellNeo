# Finite scheduled clock brackets (NEO-217 / NEO-192)

23 October 2026 NZDT. This is a separate, opt-in diagnostic experiment after
NEO-213's accepted development-directory admission. It preserves the original
reader and capture mode. No scheduled GameShell capture has been authorized
or performed at this checkpoint. The historical MONOTONIC guard fault and
separate RAW −750 ns discrepancy remain unresolved; PM remains unqualified.

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
fresh; the old successful capture is not admission for another operation.
No live lease exists at this checkpoint.

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

Actual ARM Python/libc workload qualification and final combined host evidence
are being completed separately. The managed workload uses a private regular
sparse partition copy under this checkout's ignored workspace, with the source
image bound read-only. It verifies extracted Python/libc hashes before execution
and uses a fake recorder explicitly labeled ABI/workload-only. Its outputs
must never be described as actual kernel or GameShell evidence.

Original failures are retained: two pre-container source-parser refusals for
comments and the exact `const clockid_t` declaration; synthetic test setup
errors for ELF field spacing and a missing mock OUTPUTS tuple; and original
managed run `fa7e6ae84499412bb919ec6b436f8bde`, which exited 1 without OOM/stop
because the builder lacks Paramiko for host-admission tests. The correction
keeps those host tests in their authorized host context and limits managed
native/ARM tests to the pure clock/pause/replay suite, followed by the actual
extracted ARM workload. No packages, SSH stubs or network access are added to
hide the dependency difference.

Fresh independent review, publication permission and a separate live device
lease remain required. Any complete or clean finite result leaves NEO-192 and
PM acceptance open unless the underlying evidence actually resolves them.
