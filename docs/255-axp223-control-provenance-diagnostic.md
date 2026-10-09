# AXP223 charger-control provenance diagnostic

10 October 2026. NEO-188 follows the [NEO-10 source audit](252-charging-voltage-evidence-gap.md).
The isolated candidate compares ordinary charger-control reads with fresh bus
reads through the existing AXP223 regmap. It is outside the active image queue;
no GameShell connection, charger write, image change or hardware test is part
of this work. All seven real-kernel tests and complete ARM driver compilation
pass. Image integration and hardware qualification remain separate gates.

## Question this can answer

The existing inventory and battery target getter can both receive a cached
REG33 value. Their agreement does not independently establish the physical
register value. This diagnostic records normal and bypassed observations of
REG33 and REG34, preserving the method, ordering, time bracket and error for
each read. A successful bypassed read establishes the value returned by the
bus at that instant. It does not establish battery terminal voltage, ADC
accuracy, the unidentified pack's limits or the disputed REG34[2] semantics.

The fixed sequence is normal REG33, bypass REG33, normal REG34, bypass REG34.
These are four separate regmap operations, not one atomic snapshot. Legitimate
writers can run between operations. A mismatch therefore needs investigation
of intervening writes before attributing it to a stale cache. A match does not
calibrate voltage or prove charging through sleep.

## Driver boundary

The [hook patch](../kernel/candidates/axp223-controls/driver.patch) extends the
RSB MFD driver with the adjacent
[diagnostic helper](../kernel/candidates/axp223-controls/axp223-control-diag.h).
The checker composes them into a separate candidate patch. The existing MFD
driver data still points to `struct axp20x_dev`; a containing allocation owns
the diagnostic state without changing what child drivers receive.

The read-only `control_diagnostics` module parameter defaults to false. With
it disabled, no debugfs file is published and the driver's original PM-callback
selection is retained. When requested, only `AXP223_ID` publishes
`axp223-controls-<device-name>/snapshot` under debugfs. The file is mode 0400;
its open handler also rejects write access. Optional diagnostic setup failure
warns without failing the PMIC's otherwise successful probe. Enabling the
parameter installs PM callbacks on the RSB driver; other variants are not
qualified by the AXP223 tests and should not opt in.

One successful open allocates a private record and performs exactly four
register API calls. Once an ordinary cache entry exists, those normally need
only the two bypass bus reads. No retry, cache sync, charger setter, arbitrary
address or writable bypass toggle is exposed. The pinned AXP223 map is direct
and unpaged, so these reads require no register-window write.

Each bypass operation uses Linux 6.18.54's `regmap_read_bypassed()`. Its map lock
covers saving the cache flags, temporarily bypassing the cache, the bus read
and flag restoration. Successful bypass reads do not update the cache. Errors
are preserved as negative errno values with JSON `value: null`; the diagnostic
does not present undefined output or substitute a cached success. All four
observations are attempted even if an individual read fails. Timestamps use
the kernel's monotonic clock and bracket each operation.

The version-1 JSON record labels `variant`, `atomic: false`, register number,
`normal`/`bypass` mode, `start_ns`, `end_ns`, `error` and `value`. Partial reads
copy from that per-open record without issuing further register reads. The
existing charge-inventory schema and its provenance are unchanged.

## PM admission and removal

Bypassed reads deliberately override cache-only mode. That makes driver-owned
system-sleep admission necessary even though the RSB bus already handles
runtime-PM references around its transactions.

- A per-device mutex serializes each complete diagnostic capture with PM
  admission and removal. It does not hold the regmap lock between separate
  register calls or prevent other legitimate register clients from writing.
- The driver's PM `prepare` callback waits for any admitted capture, marks
  preparation active and returns zero. Further captures fail with `-EBUSY`
  before reaching regmap. The gate remains closed through suspend/noirq and
  resume until PM `complete` reopens it, including the prepare-abort path.
- Removal waits for a capture, permanently marks removal active, then removes
  the protected debugfs file before MFD children are removed. New captures
  fail with `-ENODEV`; PM completion cannot override the removal flag.
- Debugfs removal drains protected operations outside the diagnostic mutex.
  A retained file's release frees only its independent record, with no access
  to driver or inode-private storage after devres has freed the device state.

The relevant lock order is device-core lock → diagnostic mutex → regmap lock
→ RSB transaction/runtime-PM handling. Capture does not acquire the device-core
lock, and removal releases the diagnostic mutex before draining debugfs.
Normal disabled operation has no new system-PM callback. This design does not
claim to cover an independently broken parent-bus removal or runtime-PM path.

## Repeatable offline checks

```sh
task test:axp223-controls          # Build/run real Linux UML KUnit
task check:axp223-controls-driver # Also compile the complete ARM RSB MFD object
task check                       # Host tests, C checks and shell lint
```

The locked Linux archive and pinned builder image must already be cached.
Both new-task containers use `--network none --pull never`; no downloads or
device connection are part of these tasks. The optional offline switch in the
shared ARM compiler helper leaves existing callers' behavior unchanged.

The [checker](../tools/check-axp223-controls.py) verifies the archive and creates
separate source manifests from the complete active patch queue plus this
candidate. Other isolated candidates are not implicitly included. The test
queue adds only the KUnit harness and its Kconfig/Makefile entries; its helper
bytes must match the production candidate. The ARM step compiles all of
`drivers/mfd/axp20x-rsb.o` against the production candidate source and project
configuration.

The [KUnit suite](../kernel/tests/axp223-control-kunit.c) uses real regmap/Maple,
kernel mutexes and threads, debugfs, device unbinding/devres and PM-core
prepare/complete. Only the register bus and platform device are synthetic.
Seven named cases cover:

| Case | Intended checks |
| --- | --- |
| Ordered snapshot | Different cached/backing values; method, address, order, timestamps and exact bus-read count |
| Errors and cache state | Three supported cache modes × success/failure at each register; unchanged cache and restored flags, no cached fallback |
| Admission | Default-off and unsupported variants; PM-prepared and removing states; no bus access on rejection |
| Concurrent map client | An ordinary read waits while a bypass read owns the real regmap lock and subsequently receives the unchanged cache value |
| PM core | Real `dpm_prepare()` waits for an admitted read; captures and debugfs opens reject while prepared; `dpm_complete()` reopens admission |
| Driver removal | Unbind waits for a protected open; devres releases driver state; retained-file release is safe; new opens fail |
| File contract | Write opens reject without I/O; read opens retain explicit provenance and null values for errors |

Every fixture checks zero bus writes. KASAN, lockdep and atomic-sleep debugging
are requested and their resolved configurations checked. Thread fixtures park
until joined, and file releases run synchronously so lifetime assertions are
not deferred beyond their test. The single-CPU UML interleavings are controlled
examples, not exhaustive SMP qualification. The PM case tests preparation and
completion without entering actual sleep. File tests inspect the captured
record rather than exercising userspace partial-read copy faults.

Acceptance requires exactly those seven passing cases, with no skipped cases,
kernel warnings, lock reports or sanitizer failures. Linux/configuration/log/
result hashes and input/source manifests are retained together. Inputs and the
active queue must still match at the end. The compile receipt is only written
after both KUnit and ARM compilation pass; failed logs are retained separately.

## Validation status and remaining work

| Check | Result |
| --- | --- |
| Linux UML KUnit | All seven cases passed; zero failures or skipped cases |
| Kernel diagnostics | KASAN, lockdep and atomic-sleep checks enabled; no kernel WARN/BUG, sanitizer or lock reports |
| Complete ARM RSB MFD driver | Compiled successfully with the project configuration; output is an ARM ELF32 object |
| Host `task check` | 16 runtime and 898 tooling tests passed (one existing optional skip), plus both C checks and shell lint |
| Compiler output | No compiler warnings or errors in the accepted task log |

The successful task log is `.local/build/axp223-controls-driver.log`. The UML
build took about 559 seconds; the seven tests ran in about 0.43 seconds. These
are development-host timings, not device latency or energy measurements.
The accepted receipt is `.local/build/axp223-controls-tests/compile-evidence.json`,
with SHA-256:
`280d66fa06e77c99ee4fff2e48bf2ae785972da04903c05bc5d3211a2b6f2109`.
Its `artifact_dir` retains the tested Linux executable, configuration, complete
boot/test log, JSON results and a copy of the receipt. The ARM output and its
configuration/object hashes are recorded alongside their source identity.

Initial Docker launches were prevented by automatic approval-review timeouts;
the sandboxed attempt stopped at Docker-socket permissions after preparing the
source trees. Those attempts did not execute a kernel test or ARM compilation.
The owner explicitly approved retrying the offline Docker task. The later
launch with explicit offline/no-pull settings completed successfully. The
archived stage log and `.local/neo188-candidate.log` preserve the socket-denied
attempt; approval timeouts happened before a process started.

The first sandboxed host suite passed its 16 runtime tests but stopped with
five local socket-fixture errors among 897 tooling tests (one optional skip).
That is a failed host run, not evidence of a completed check. Its log remains
`.local/neo188-check.log`. The final successful 898-test run, including the new
offline-container command regression, is `.local/neo188-check-final.log`.

NEO-188 is ready for review of the isolated candidate. Image integration needs
its own identity, reviewed opt-in and
collector/provenance contract, followed by awake reads and attended PM tests
on CPI v3.1. Keep the current image and inventory unchanged until then. Remove
this optional diagnostic if an equivalent maintained upstream interface is
adopted or the investigation no longer needs it.

NEO-10 still needs the independent voltage/pack/documentation evidence from
report 252. This work does not justify charger changes, an ADC offset, a claim
of energy savings or treating a synthetic test as physical RSB qualification.
