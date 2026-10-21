# Clock comparison and preserved inspection provenance

10 October 2026. NEO-192, continuing [report 259](259-clock-path-comparison.md).

The first completed comparison retains **one raw-clock cross-path ordering
discrepancy in 15,000 sequences**: a Python reading is 750 ns below the explicit
kernel reading immediately before it. This is a new lead, not a reproduction
of the original guard's Python MONOTONIC bracket failure. Device state and both
network routes pass the unchanged-state checks; clock reliability remains
unqualified and PM admission remains blocked.

## Preflight failure explained

The approved full offline suite passed: 24 runtime tests and 924 tooling tests,
with one existing optional skip, both compiled C checks and shell lint. The
subsequent device attempt reached the GameShell but failed during its initial
inspection, before submitting any clock measurement.

The existing host wrapper suppressed the remote command's output and raised
only an exit-status exception. Inspection now saves combined remote output to
a private file before parsing it. A failed inspection retains its traceback
without producing a successful snapshot or starting the measurement.

The preserved error is:

```text
ValueError: Kernel checkpoint source/image changed within this boot
```

The checkpoint correctly belongs to the producer used before the uninstalled
battery-guard candidate changed `test-pm-stages.py`. The collector itself has
not changed. This is an inspection-provenance mismatch, not a new device fault
or evidence that the clock comparison failed.

| Identity | SHA-256 |
| --- | --- |
| Existing checkpoint producer | `3b26d041132a32ef5542288b6afc6c33541a911dad1dd97735ab28929f9a61c7` |
| Current producer | `d4fdbe8839d0b136f32b4b5a721f43dd15dfe572d022a943637d3a1c1c865d5a` |
| Unchanged collector | `4ab460c5d691b053adfc42254b0fb1025381fe41a4b8d2eb299e6900d41968d0` |

Original private records in the active worktree:

- `.local/neo192-clock-paths-approved-check.log`: first full passing suite.
- `.local/diagnostics/20261009T224639.656213Z/`: first connected preflight failure;
  ABI receipt only, no measurement.
- `.local/neo192-preserved-kernel-checkpoint.json`: original checkpoint copy.
- `.local/diagnostics/20261009T225008.468858Z/inspection-output.txt`: the
  preserved device traceback from the separate inspection-only command.

## Explicit inspection revision

The clock task can now select the exact committed inspection bundle that owns
the current boot's checkpoint:

```sh
task device:clock-compare INSPECTION_REVISION=be6c719c1b8e1637b69fa3e94a96b370adfb84d2
```

This option is limited to the awake clock comparison. It accepts a full local
ancestor commit, reads all eleven original inspection files from that commit,
and saves their hashes and the exact bundled source alongside the capture.
The bundle supplies hashes of the actual executed bytes. Its collector must
match the current validator exactly; missing files, changed collectors and
unrelated revisions stop before device access. There is no automatic fallback
to an older revision. Without the option, current sources remain the default.

The only remote invocation of the pinned bundle is `--inspect`. The clock
recorder and its host validators remain current. Normal PM commands continue
to use current sources and unchanged admission rules. No checkpoint identity
is rewritten, no retained record is discarded, and no restart count is reset.
The known battery-service fault still blocks PM qualification.

The comparison saves `before-output.txt` and `after-output.txt` even when remote
inspection fails; parsed snapshots have separate JSON files. The standalone
`device:pm-inspect` task similarly saves `inspection-output.txt` on failure.

## Offline validation

Six additional tests cover failed-inspection output retention, exact historical
source bytes and hashes, default current sources, malformed/unrelated commit
rejection, collector mismatch, incomplete bundles and stopping before
measurement after failed preflight. The generated bundle is also executed in
a local Python process to verify the source identities it supplies.

The complete suite after these changes passes **24 runtime tests and 930
tooling tests**, with one existing optional skip. Both C regression checks,
Bash syntax and ShellCheck pass. Log:
`.local/neo192-clock-inspection-check.log`.

## Hardware comparison

The single submitted measurement completed and passed independent host
validation. Private evidence is at
`.local/diagnostics/20261009T225220.923744Z/`, including source receipts,
before/after snapshots, the original `comparison.json` and `summary.json`.
Command output is saved in `.local/neo192-clock-paths-pinned-device.log`.

The device remains on diagnostic.25, kernel `6.18.54-gameshellneo24`, boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`. The measured process verifies ARM EABI5,
32-bit pointers and the expected 16-byte time64 structure before syscall 403.
The active clocksource stays `arch_sys_counter`; affinity remains CPUs 0–3.

| Observation | Result |
| --- | --- |
| Completed sequences | 15,000; each reads MONOTONIC, RAW and BOOTTIME |
| Discrepant sequences | 1, at index 51 |
| Classification | `raw.interleaved` |
| Python-only / kernel-only regressions | None observed |
| Between-sequence regressions | None observed |
| CPU observations, each clock family | CPU 1: 12,800; CPU 2: 2,200 |
| Differing CPU IDs across a family bracket | 0 |
| PM counters before/after | 53 successes, 0 failures |
| Battery-service restarts before/after | 1; original incident retained |
| Services / backlight / USB / charger / governor policy | Unchanged |
| Kernel evidence before/after | Same 1,661 records and original 1,660-record anchor |
| USB and independent Wi-Fi SSH checks | Passed |

CPUs 0 and 3 were allowed but not observed at the recorded bracket starts.
Matching before/after CPU IDs cannot exclude migration away and back between
reads. No affinity change was made to obtain these results.

The discrepant RAW sequence records CPU 1 at both ends. Exact nanosecond values,
in execution order:

| Read | Value (ns) | Difference from preceding read (ns) |
| --- | ---: | ---: |
| Python 1 | 62049005203462 | — |
| Kernel 1 | 62049005516212 | 312750 |
| Python 2 | 62049007661420 | 2145208 |
| Kernel 2 | 62049008553837 | 892417 |
| Python 3 | 62049008553087 | **−750** |

The recorder retains both this sequence and its predecessor. Index 51 is the
first sequence of the second batch, after the first scheduled pause; that
placement does not establish an idle-exit cause. There is no event truncation.
All Python readings in this sequence increase relative to one another, as do
the two explicit kernel readings. The inconsistency is between the two paths.

The host reclassified the raw values and verified complete work, CPU counts,
unchanged metadata/state, kernel continuity and both routes. A successful
capture means the evidence is valid; it does not mean the clocks passed a
reliability qualification. The saved summary explicitly retains
`clock_reliability_qualified: false` and `pm_admission: false`.

## What remains

The original exception involved two ordinary Python MONOTONIC reads, whereas
this observation involves RAW reads across Python and explicit kernel calls.
Do not claim a common cause, identify either path as faulty, or assume Python
used vDSO from this capture alone. Next, trace the installed Python/libc clock
dispatch and the pinned kernel RAW conversion/counter paths, using this exact
event to guide any further bounded measurements.

The candidate guard from report 258 is still uninstalled. NEO-192 remains in
progress; NEO-191 PM qualification and NEO-182 battery sleep remain pending.
No reboot, service restart, incident reset, screen blanking, PM entry,
clocksource/affinity change or charger write occurred in this slice.
