# Kernel clock-provenance candidate

10 October 2026. NEO-192, implementing the offline diagnostic slice from
[report 266](266-kernel-counter-timekeeping-audit.md).

The isolated candidate captures the counter value used by a selected clock
syscall, its conversion inputs and the final kernel timespec. It retains a
backwards result instead of fixing, clamping or retrying it. The original
clock incident remains unresolved. No GameShell access, runtime replacement,
clocksource change, sleep, reboot, image integration or card write occurs in
this slice. NEO-191/NEO-182 PM admission remains pending.

## Candidate and scope

[The hook patch](../kernel/candidates/clock-provenance/hooks.patch) targets the
locked Linux 6.18.54 tree and is composed only by the isolated checker with
[the recorder](../kernel/candidates/clock-provenance/neo-clock-diag.c) and
[its header](../kernel/candidates/clock-provenance/neo-clock-diag.h).
It is outside `kernel/patches/` and the image patch queue.
`CONFIG_NEO_CLOCK_DIAG` defaults off. Enabling it adds a root-only debugfs
endpoint, but capture still requires an explicit command from the owning task.
It does not attach to the running battery service.

The scope is ARM EABI clock_gettime64 (403) and clock_gettime32 (263), for
MONOTONIC, MONOTONIC_RAW and BOOTTIME. UML exists solely for kernel testing and
labels the syscall number −1. Real-time, coarse, fast/NMI accessors and direct
vDSO calls are outside this recorder. The intended board currently has no
exported vDSO clock functions; that route condition still needs verification
on any future instrumented image.

The recorder is a diagnostic candidate, not a production timing optimization.
The complete userspace collector that correlates each raw returned timespec
with a Python/native integer is a separate next step. Do not use this kernel
record alone to absolve the user-copy or language-runtime boundary.

## Reader and syscall evidence

A selected syscall reserves one record with an ordinal, TID/TGID, clock ID and
ABI. Only that task's expected clock getter can fill it. Interrupt/NMI callers,
other tasks and unrelated clocks cannot consume its record.

Inside the ordinary sequence-count loop, the hook copies the conversion base
and bound, reads the real counter exactly once, and passes that value and the
frozen base to the original `timekeeping_cycles_to_ns()` implementation. The
function's normal, negative-delta and wide-arithmetic branches are preserved.
The getter's original sequence retry still decides whether the attempt is
accepted. The accepted attempt retains:

- The actual consumed count, mask, anchor, multiplier, shift, fractional base,
  maximum conversion interval and source ID.
- Both timekeeper conversion bases, relevant seconds/offsets, source-change and
  clock-set generations, accepted sequence and attempt count.
- The CPU at the counter read, diagnostic insertion order and syscall-end CPU.
- The post-namespace kernel timespec, namespace identity/offset, copy status,
  acceptance and completion flags.

The source ID is Linux's numeric clocksource identifier. Its generic value
does not distinguish different generic sources by name. The future provenance
collector must verify the expected architectural source and treat any source
change or ambiguous identity separately before attributing a fault.

Rejected attempts replace the scratch tuple and increment the attempt count;
their individual counts are not retained. They never become accepted records.
Attempt-count saturation is explicitly incomplete in replay.

The counter read and its CPU attribution execute inside a short
`preempt_disable_notrace()` interval. This prevents migration between those
two operations; it does not pin the whole syscall or workload. It changes
scheduling conditions, and copying metadata adds latency. A clean capture
therefore cannot exclude a fault suppressed by instrumentation. Record order
is acquisition order of the diagnostic lock, not counter-instruction time or
a substitute clock. Gaps can represent rejected attempts.

The syscall hook saves a valid computed timespec even if its user copy returns
EFAULT. A getter failure retains the error with no claimed valid result. This
separates calculation completion from copy success without changing either
return code.

## Writer context

Core-timekeeper publication records preserve the old published tuple and new
shadow tuple, action flags and odd publication sequence. An accepted reader
of that newly published state has the following even sequence, modulo 32 bits.
Separate records retain the actual counter values consumed by forward-now,
ordinary advancement, resume and source setup. Forward-now and advancement
also retain their actual accepted delta after the kernel's bound check.

The writer lock already prevents CPU migration at these sites. No extra
counter read or timestamp is used by the recorder. Forward/advance/resume
records capture their input context before changing the anchors; the first
two are recorded after delta calculation, and resume before sleep calculation.
SETUP is different: the new source and anchors have already been installed,
while the remaining conversion setup is unfinished. Treat that as a seed
record, not a complete old or new conversion tuple. The later publication
contains the completed transition. Publication action flags describe the
kernel's flags, not a fully decoded human cause such as “NTP correction.”

Replay checks record structure and syscall arithmetic. Automatic reconstruction
of every writer transition, including setup, rate changes and sleep injection,
remains future analysis; saved writer data must not be mistaken for that proof.

## Ownership, limits and export

`/sys/kernel/debug/neo_clock_capture` has mode 0600 and additionally requires
CAP_SYS_ADMIN at open. One open session is allowed globally. Its opener owns
the workload; another task cannot arm or export it. Control is serialized by a
mutex, while IRQ-safe bounded append operations use a raw spinlock. No
append helper allocates memory or adds timestamp, printk or tracing calls.

The development protocol is:

1. The workload task opens the file read/write, then writes `start N\n`, where
   N is 1–1,024 supported clock calls. A session can start only once.
2. It runs the fixed workload. The recorder stops after N calls, or when the
   2,048 writer slots are exhausted. `stop\n` can end a shorter capture.
3. Once stopped and its final call has finished, the owner reads NDJSON from
   the same descriptor, saves it and closes the session. Export before a start
   or while active is rejected. Records are never overwritten within a session.

The writer-cap event records one lost event and freezes further admission.
An already admitted call can still finish. The report labels this capture
incomplete; later unrecorded work after the stop is outside the capture, not
silently included in its coverage. Closing from another thread waits for an
in-flight call before releasing the task reference. This is a drain, not a
wall-time timeout: an indefinitely blocked original syscall could also block
that drain. An external collector must account for this when live testing is
designed. There is no automatic repeat-until-clean behavior.

Storage is fixed in the diagnostic-enabled kernel. Disabled builds omit the
recorder object, and the disabled publication macro does not evaluate its
sequence-count argument. The candidate has no persistent service or boot-time
arming. The ARM objects reserve 1,122,304 bytes for the two record arrays when
enabled, excluding the small control state and export buffer. No disabled-state
energy or timing claim is made from compilation.

## Repeatable offline checks

```sh
task test:clock-provenance
# Also compile actual ARM timekeeping/syscall objects with the option off/on:
task check:clock-provenance
# Replay a saved kernel stream; this never contacts a device:
task report:clock-provenance FILE=<saved-records.ndjson>
task check
```

The checker uses the existing pinned builder with `--network none` and
`--pull never`, verifies the downloaded kernel archive and source manifest,
and retains source/configuration/input hashes and kernel results under
`.local/build/clock-provenance-tests/`. It does not change the active queue.
The candidate and the test-only inclusion are separately identified in its
patch manifests. ARM builds compile the three relevant objects with diagnostics
enabled and the two original objects with it disabled; they are not a complete
bootable image or a board qualification.
The host's `nm` also verifies seven enabled hook references against their
definitions and no diagnostic references in the disabled objects.

[Kernel tests](../kernel/tests/neo-clock-diag-test.c) exercise:

- An injected 750 ns backwards count above the anchor for all three clocks,
  exactly one counter read per attempt, CPU attribution and call limits.
- A rejected sequence followed by an accepted attempt, negative-delta and
  128-bit intermediate conversion, and EFAULT with its retained kernel result.
- Writer inputs/publication tuples, a full buffer without overwrite, and
  completion of a call already admitted when the writer limit is reached.
- Exclusive ownership, unstarted/live export refusal, unsupported clocks,
  one-start semantics and the actual NDJSON serializer.
- Foreign-task exclusion and stop/drain behavior with real kernel threads.

The test counter is scripted. Retry testing uses a real sequence counter and
the actual read/conversion hook, not concurrent mutation of the live kernel's
timekeeper. The tests do not exercise a real ARM register, actual user-copy
faults, concurrent ARM migration or a complete userspace debugfs workload.
The host independently replays the real serializer fixture and rejects
missing/duplicated/failing kernel cases or warnings. UML runs with KASAN,
lockdep and atomic-sleep checking. Its configuration does not support time
namespaces; the producer explicitly exports zero offset/identity when that
feature is absent, while host fixtures cover nonzero offsets.

The host replay preserves regressions and compares exact integer arithmetic.
A coherent unchanged tuple plus decreasing consumed cycles can identify a
counter-observation regression, without identifying a silicon or idle defect.
Changed tuples require transition analysis. A reconstruction mismatch is an
error, not a hardware attribution. The report's `complete` field concerns
record completeness only; neither that field nor a clean capture admits PM.

## Validation outcome and next work

The final `task check:clock-provenance` passed. Its receipt is
`.local/build/clock-provenance-tests/compile-evidence.json`. All current input
hashes and retained UML artifact hashes were rechecked against that receipt.

- All five KUnit cases passed with no kernel warnings, KASAN findings, lockdep
  reports or atomic-sleep diagnostics. The actual kernel serializer's fixture
  replayed independently on the host.
- Both ARM configurations compiled, with 177 project configuration assertions
  plus the requested diagnostic-option checks. All seven enabled hook symbols
  resolve; disabled objects have no references to those hooks.
- Full host checks passed: 24 runtime tests and 967 tooling tests, with one
  optional skip, both existing C checks and Bash/ShellCheck. Nine tooling cases
  cover replay, malformed/incomplete evidence, kernel-result acceptance and
  the ARM symbol-validation rules.
- The composed candidate passes the kernel style checker with zero errors
  and warnings (`--no-tree --no-signoff`).

The retained kernel run is under
`.local/build/clock-provenance-tests/uml-5e30cdc71d8a3c9c/accepted-runs/ebd5b61e1f794dfabede26ca4b6633de/`.
Its serializer fixture SHA-256 is
`f2e14e63120d2c20d18cdce794b30ec010e147b14f1b1f4e6c1b928faf78e518`.
The candidate source-tree digest is
`6e17eb1c7a9cca41fc39329f9f5c0cb2505df159093a37f215bab9fd8eb42dc0`;
including the test-only file gives
`aaa548568878077fe256950ac42d9dcba7989f4660be14b98c9fb37a87f241c6`.
These are source-inventory digests, not image hashes.

Earlier runs remain separate: UML rejected an unsupported time-namespace
configuration; a later test passed its assertions but was rejected for a
sequence-writer preemption warning in the fixture. The fixture now obeys the
writer contract. The input-hash guard also rejected a run while host validators
were being edited. The accepted run uses the final unchanged inputs; neither
warnings nor provenance checks were waived.

The next step after offline checks is review of the kernel hooks and a bounded
userspace collector that retains per-call raw ABI bytes and integer results,
verifies boot/configuration/binary provenance and joins them to kernel call
ordinals. No live deployment follows merely from these offline passes. Keep
the original diagnostic.25 boot, PM53/0, battery NRestarts=1 and protected
kernel checkpoint intact; no cause or repair of the original fault is claimed.
