# Exact-call userspace clock evidence

12 October 2026 NZDT. NEO-192. This completes the offline reader, fixed workload
and correlation layer following [report 267](267-kernel-clock-provenance-candidate.md).
It does **not** resolve the original clock fault or deploy a diagnostic image.
No GameShell access, runtime change, sleep, reboot or card operation occurred.

## Evidence now retained

[The native reader](../tools/clock-boundary.c) performs exactly one of three
operations for a requested clock: ARM EABI syscall 403/time64, syscall
263/time32, or libc's time64 `clock_gettime`. It keeps the initialized 16-byte
buffer, including padding or bytes untouched by an error, plus return code,
errno, decoded seconds/nanoseconds and the C integer conversion. The time32
ABI writes eight bytes; the remainder stays visible but is not decoded.

Production compilation asserts ARM hard-float EABI, little endian, word sizes,
the two syscall numbers and libc's actual 16-byte timespec layout (64-bit
seconds, 32-bit nanoseconds at offset eight). The builder checks the syscall
table and kernel time32/time64 types against the hash-verified locked archive.
The library exposes its layout for an independent ctypes check before capture.

[The workload](../tools/clock_boundary.py) preallocates 384 observation slots:
32 rounds × three clocks × four routes. Each round reads MONOTONIC,
MONOTONIC_RAW and BOOTTIME through the three native routes and Python's public
clock API. Python independently decodes the native bytes; it does not derive
its comparison integer from the C integer. Python's public API does not expose
its raw timespec, so that route explicitly records `raw: null`. A mismatch on
that route alone cannot separate user-copy from Python conversion.

The native library is loaded through `ctypes.PyDLL` to retain the GIL across
each native call. This avoids introducing a GIL-reacquisition clock wait in
the recorder's owning task. It changes scheduling conditions and does not
reproduce every condition of the original battery service. Neither a clean
instrumented window nor the absence of a reproduced fault clears NEO-192.

## Alignment, failure handling and interpretation

The workload arms a supplied owning-task debugfs descriptor with the kernel's
1,024-call maximum, executes its fixed 384 calls and explicitly stops. Spare
capacity is intentional: an unexpected additional call must appear in the
evidence rather than disappear behind a limit equal to the planned count.
No printing, export, clock-based delay or metadata collection occurs inside
the armed workload. The descriptor must be opened and used by the same task.

The caller receives the original kernel byte stream separately from the
userspace observations and must save both before replay. A failed call or
interruption stops the workload without retrying; stop, export and close are
each attempted. Partial export bytes survive an error. Failed or ambiguous
start commands also attempt cleanup. This cannot guarantee export following
SIGKILL, process loss or a permanently blocked kernel operation; live execution
still needs an independent host deadline and recovery/evidence handling.

Replay first validates the existing kernel tuple arithmetic, then demands
the full fixed call plan, manual stop, correct capture limit, exact ordinals,
clock IDs, syscall ABIs, TID/TGID and namespace. Missing, extra or partial
streams are incomplete; there is no speculative realignment. Recorded CPUs
must lie inside the captured affinity. A changed source generation or source
identity prevents a complete result. The planned deployment wrapper must
independently establish that the numeric source identity refers to the expected
architectural source and that the process has no vDSO clock exports.

The report preserves separate findings for kernel-to-raw disagreement,
raw-to-C-fields disagreement, C conversion, Python conversion and syscall
status. A Python public-API mismatch has its own combined boundary label.
Kernel and userspace regressions remain visible with their signed deltas.
The deliberately injected **−750 ns** regression is retained in both layers.

`complete` means the planned diagnostic evidence is complete, not that clocks
are healthy. An internally consistent backwards value can have complete
evidence. A complete stream can also contain explicit boundary findings;
callers must inspect those findings and the regression lists. These reports
never admit PM tests or classify a silicon defect by themselves.

## Saved commands and validation

```sh
task test:clock-boundary
task check:clock-boundary
task report:clock-boundary KERNEL=<kernel.ndjson> USERS=<users.json>
```

All three commands are offline. The check uses the pinned builder with no
network, no pulls, a read-only container filesystem and a private output mount.
It retains exact input copies, hashes, the ARM shared library, compiler output,
ELF/disassembly and fixture output. The report reads only the two saved files
and publishes their hashes. There is deliberately no live task yet.

The final build receipt is
`.local/diagnostics/20261011T122630.373942Z/build-receipt.json`.
The ARM library SHA-256 is
`485b08959e966ed13fd11e694c0e7a6c372e5aea69e400655770b971eb2c920c`.

- Thirteen Python cases pass, covering each boundary, retained regressions,
  missing/extra calls, ownership and ABI rejection, source changes, errors,
  interruption, partial export and cleanup attempts.
- Native fixtures pass with undefined-behaviour sanitization; the same C
  fixtures pass under ARM emulation, including exact integer overflow limits.
- The host independently decodes **27 buffers emitted by the ARM fixture**:
  three routes × three clocks × success/regression/EFAULT. This checks actual
  C-produced bytes rather than only Python-generated fixtures.
- The production ARM shared library compiles with layout assertions, versioned
  libc time64 imports and eager symbol binding verified. These are build/ABI
  checks, not real clock-syscall or board measurements.
- Full host checks pass: 24 runtime tests, 983 tooling tests (one optional
  skip), both existing C checks and Bash/ShellCheck. The initial sandboxed run
  blocked five existing local-socket fixtures; the unchanged suite passed with
  local socket permission. Both logs are retained separately, and no transport
  investigation was reopened.

## Work remaining before a card swap

Prepare a deployment wrapper that verifies the matching diagnostic image,
kernel configuration/recorder sources, interpreter/libc/library hashes, syscall
route availability, namespace/owner identity and before/after boot and source
context. It must retain original partial results under an independent host
timeout and reject live source/provenance mismatches. Then integrate the
isolated recorder into a separately identified diagnostic image, review the
final composition, build it and verify its artifacts.

Only after those steps should a card swap be requested. The original clock
failure and protected evidence remain intact. NEO-192 stays open, and the
NEO-191/NEO-182 PM gates remain blocked by the unresolved fault.
