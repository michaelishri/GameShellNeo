# Installed clock-runtime inventory

**Subsequent finding:** [report 263](263-native-clock-vdso-availability.md)
verifies that this boot's mapped vDSO has no resolvable clock exports. The
kernel removes their names because of the timer DT flag. The static libc
dispatch described here remains accurate, but its vDSO candidates are not
available clock routes on this boot; the expected installed path is the syscall
fallback. The original fault remains unresolved.

10 October 2026. NEO-192. This continues the saved discrepancy in
[report 260](260-clock-comparison-provenance.md) and complements the kernel
source analysis in [report 261](261-arm-clock-path-source-analysis.md).

The installed Python imports **`__clock_gettime64@GLIBC_2.34`**, and its build
configuration has an eight-byte `time_t` on 32-bit ARM. The captured libc has
the expected indirect-call-first implementation and explicit syscall 403
fallback. This establishes the installed binary boundary and narrows the next
measurement; it does not prove which branch served the original RAW reading.

## Reproducible collection and offline inspection

```sh
task device:clock-runtime INSPECTION_REVISION=be6c719c1b8e1637b69fa3e94a96b370adfb84d2
task report:clock-runtime CAPTURE=20261009T230039.014366Z
```

Use the timestamp printed by a new inventory for later reports. The inspection
revision is the explicit original producer for this boot's protected kernel
checkpoint, as explained in report 260; it is not a general fallback for PM
tests. Current inspection sources remain the default when the option is absent.

The device task uses the existing USB SSH route, keeps the device awake, and
runs the inventory as the ordinary user. It reads its own executable/mappings,
Python build configuration, package identities, timer DT properties and hashes
of the Python/libc files. It performs no tracing, clock sampling loop, runtime
installation, clocksource/affinity change, service restart, PM operation or
charger write. Loader environment variables are recorded only as present or
absent; their contents are not collected.

An inventory timeout, parse error or incomplete identity stops validation;
original remote output and a postflight inspection are retained. Before/after
PM, service and kernel evidence checks use the existing validators. No PM test
may already be running. The known battery-service restart is observed, not
cleared or accepted for sleep qualification.

The host copies only the two identified binaries, with a 32 MiB limit each,
and checks their exact size and SHA-256 before inspecting them. Host `readelf`
records ELF headers, notes, dependencies, symbols and relocations. The optional
offline report uses the pinned builder's ARM `objdump`, with no network,
dropped capabilities, a read-only filesystem and a read-only capture mount.
Each report attempt has a fresh private directory, preserving earlier output.
Neither copied binary is executed by the report.

Private records:

- Runtime capture: `.local/diagnostics/20261009T230039.014366Z/`.
- Offline disassembly: `.local/diagnostics/20261009T230252.066873Z/`.
- Logs: `.local/neo192-clock-runtime-device.log` and
  `.local/neo192-clock-disassembly.log`.

## Installed identity

| Item | Observed result |
| --- | --- |
| Boot | `2170b296-d964-4d16-bdb1-c135b0e7b812`, unchanged |
| Kernel | `6.18.54-gameshellneo24` |
| Python package | `python3.13-minimal` `3.13.5-2+deb13u5`, armhf |
| libc package | `libc6:armhf` `2.41-12+deb13u4` |
| `time` module | Built into the Python executable |
| `time_t` / `long` / pointer sizes | 8 / 4 / 4 bytes |
| Python monotonic implementation string | `clock_gettime(CLOCK_MONOTONIC)` |
| ELF format | ELF32, little-endian ARM, EABI5 hard-float |
| vDSO mapping | Present; per-call execution remains unproven |
| `LD_PRELOAD`, `LD_AUDIT`, `LD_LIBRARY_PATH` | Absent in this inventory process |
| Timer DT | Node present, `arm,cpu-registers-not-fw-configured` present, frequency 24,000,000 Hz |

The Python-reported 1 ns clock resolution describes the API; it does not mean
the 24 MHz hardware has 1 ns counter ticks or establish accuracy. Similarly,
an inventory process's loader environment does not retrospectively measure
the environment or exact branch of the earlier comparator/guard process.

| Binary | Size | SHA-256 |
| --- | ---: | --- |
| `/usr/bin/python3.13` | 4,759,168 bytes | `c5b8ff962e01a7e6fa49090d2f646e3c85a7e5806907e4e64dd7d619c7c388a7` |
| `/usr/lib/arm-linux-gnueabihf/libc.so.6` | 1,188,080 bytes | `f7854d98c852da9c89d2cbdbeb980c5d1258ba6d624486f76b24c7741a9649b7` |

The copied files match the before/after device hashes. GNU build IDs are
`1baa0f61113b13bf9d0c404ccd9698e73b14b2d6` for Python and
`8480e4cfa4b1327bfb61f60ecf0764f30944a3a8` for libc.

## Python to libc

The executable's saved relocation table contains an `R_ARM_JUMP_SLOT` entry
at ELF address `0x004603fc` for `__clock_gettime64@GLIBC_2.34`, and the dynamic
symbol is undefined in Python. The captured libc exports that versioned
function. These are ELF-relative addresses, not live process addresses.

The upstream CPython 3.13.5 `clock_gettime_ns` implementation calls
`clock_gettime`, converts the returned timespec to an integer nanosecond value,
and returns a Python integer. Its monotonic API uses the MONOTONIC clock on
this platform. The conversion multiplies integer seconds by one billion and
adds nanoseconds with overflow checks; the integer APIs do not perform a
float-seconds round trip.
([CPython time module](https://github.com/python/cpython/blob/v3.13.5/Modules/timemodule.c#L231),
[conversion and monotonic implementation](https://github.com/python/cpython/blob/v3.13.5/Python/pytime.c#L466).)

The live import and configuration show that the compiled API boundary is the
64-bit libc function, despite the source spelling `clock_gettime`. This removes
the assumption that the earlier test compared Python's legacy time32 ABI with
an unrelated kernel time64 implementation. It does not by itself prove that
Python's complete implementation is fault-free. Debian-specific source patches
were not exhaustively audited or reproduced in this slice; upstream source is
a reference, while the hashes/imports/disassembly describe the installed files.

## libc dispatch

Upstream glibc 2.41 first tries the resolved time64 vDSO function when present,
then the legacy vDSO entry if needed, and otherwise uses the time64 syscall. A
nonzero return from the selected vDSO is reported as an error; it is not silently
replaced by a fresh successful reading. ARM's time64 vDSO support was added
explicitly for `__vdso_clock_gettime64`.
([glibc clock implementation](https://github.com/bminor/glibc/blob/glibc-2.41/sysdeps/unix/sysv/linux/clock_gettime.c#L26),
[upstream ARM support commit](https://sourceware.org/pipermail/glibc-cvs/2020q1/068456.html).)

The **installed** libc disassembly supports that structure:

| ELF code offset | Observed instruction behavior |
| --- | --- |
| `0x8a48c`–`0x8a492` | Load first function pointer, test for null, indirect call if present |
| `0x8a4b2`–`0x8a4be` | Load/test second pointer and call with temporary timespec storage |
| `0x8a4cc` | Load syscall number 403 before the syscall helper |
| `0x8a4e2` | Load legacy syscall number 263 on the ENOSYS fallback branch |

The first and second pointers are identified as the vDSO candidates by matching
this structure to the source, not by reading their live values. The static
code and vDSO mapping support availability and expected dispatch. They cannot
retrospectively prove the branch taken at comparator sequence 51. There is no
new per-call trace in this slice.

## Relation to the kernel findings

The preserved boot log reports physical timer access. Pinned ARM32 vDSO code
reads the virtual counter. Both normal RAW conversions use the same fixed-point
formula and shared timekeeper parameters; ordinary rounding is not a sufficient
explanation for the −750 ns ordering discrepancy. Report 261 also finds that
the observed HYP boot path initializes the virtual offset to zero on primary
and secondary CPUs. This weakens an uninitialized-offset hypothesis without
providing a current register readback.

Physical and virtual routes are therefore a useful comparison boundary, not
an identified defect. A fixed offset could be hidden by most call spacing;
an intermittent counter read or update-related issue is also still unresolved.
The earlier event differs from the guard's original Python MONOTONIC bracket
failure, so neither a common cause nor an Allwinner A64 erratum is established.

## Validation and next step

The inventory and copied-binary checks passed. Both SSH routes work; PM remains
53 successes/0 failures, the battery-service restart count remains 1, and no
new kernel fault or control-state change appears in the inventory snapshots.
The uninstalled guard candidate and original incident remain intact.

Five focused tests cover ambiguous/deleted mappings, wrong binary identities,
bounded transfer corruption/truncation, changed boot/loader state, preservation
of failed remote output with postflight collection, and rejection of invalid
offline inputs before starting Docker. The final full suite passes **24 runtime
tests and 935 tooling tests**, with one existing optional skip, both C checks,
Bash syntax and ShellCheck. Log: `.local/neo192-clock-runtime-final-check.log`.

The next useful diagnostic should reduce Python/ctypes spacing with a small
native ARM harness, distinguish the normal libc route from an explicitly
identified vDSO route and kernel syscall route, and retain exact raw readings
and CPU context. Its libc timespec and kernel time64 layouts must be verified
separately: their equal overall size alone does not establish identical member
types or padding. Keep fixed work bounds, original anomaly evidence, unchanged
device-state checks and no success-based retry loop.

Do not switch clocksource, force CPU placement, add counter rereads/clamping,
or patch a timer driver merely to remove the symptom. First identify which
boundary fails and a measurement that can demonstrate a correction. No new
image or physical test is needed to design and verify that next recorder.
NEO-192 stays in progress; NEO-191 and NEO-182 remain pending.
