# Internal keypad persistence comparison (NEO-43)

30 September 2026. Owner's CPI v3.1, diagnostic.8,
Linux `6.18.54-gameshellneo8`. This follows the supply/recovery traces in
[report 60](60-diagnostic8-hardware-validation.md).

## Question and experiment

The keypad resumes with no reported USB connection after its supply is cycled.
With USB persistence enabled, `wait_for_connected()` exhausts its nominal
2,000 ms budget before the device is removed and re-enumerated. The traced
keypad USB callback took approximately 3.021 seconds. The experiment compares
persistence on/off/on while retaining the existing supply, runtime-power and
wake policy. It does not attempt actual sleep or retain keypad power.

## Repeatable workflow and restoration

```sh
task device:keypad-compare
# Recovery after an interruption, if needed:
task device:pm-restore
```

The comparison uses three traced `devices` debug cycles, with 20 seconds
between phases and a 30-second minimum recovery window within each cycle.
It reuses the existing image/kernel/firmware, USB power, service, PM-isolation,
memory, configuration and independent USB/Wi-Fi SSH gates. Normal sleep remains
masked. The trace configuration is identical across all three phases.

Before mutation, the helper requires exactly one `4242:e131` keypad, the known
low-speed `rancidbacon.com UsbKeyboard` identity/revision and its internal OHCI
port. Persistence must initially be `1`, runtime policy `on`, and no keypad
wake control present. Only that device's `power/persist` attribute is written.
The saved identity includes its physical path and full USB descriptors, not
the reusable event number.

Each phase records its requested/applied value and restores the original value
with readback. Re-enumeration is handled by rechecking identity and reopening
the new device. A boot-bound ownership record supports independent service
cleanup and manual `device:pm-restore`; failed cleanup keeps the record for a
retry. Trace, persistence and ordinary PM restoration are independently
attempted even if another restoration step fails. Storage devices and global
USB policy are outside the helper's accepted scope.

After the stage returns, the helper polls every 100 ms for a newly opened input
handle that passes `EVIOCGKEY` without a hangup/error. The wait is bounded to ten
seconds. It neither grabs the keypad nor injects or consumes key events. This
measures healthy-handle availability, with polling and inspection overhead;
it does not measure the first delivered physical key press. The original
handle is also checked separately.

The host stops on a failed/incomplete phase, preserves the run ID and private
evidence, and does not resubmit an ambiguous operation. A comparison is marked
passed only after all three phases and restorations pass on the same boot with
the same relevant configuration and keypad identity.

## Verification

Before hardware execution, `task check` passed 13 runtime tests and the 223-test
tool suite (one optional skip), current-limit regressions, the Mac mount-guard checks, Bash syntax and
ShellCheck. New cases exercise re-enumeration, interruption, missing/ambiguous
devices, foreign ownership, wrong boot or descriptors, write/readback failures,
bounded readiness, independent PM restoration after trace/persistence errors,
fixed phase order and refusal to continue after failure or a changed boot.

The initial read-only inspection preserved the prior diagnostic.8 boot and
restored PM controls. Evidence:
`.local/diagnostics/20260930T055837.104486Z/inspection.json` and
`.local/neo43-host-check.log`.

## Initial run and recorder correction

The first attempt, `.local/diagnostics/20260930T060507.891496Z/`, completed the
first baseline and persistence-off phase. Its final baseline overflowed the
128 KiB per-CPU trace buffer: CPU 2 recorded 728 overwritten events while the
other CPUs held little of the trace. The device returned, the new input handle
was healthy, and persistence/tracing/PM settings were restored, but the recorder
correctly failed the phase and left `comparison.json` marked incomplete. That
run is retained and is not counted as a successful comparison.

A separate read-only inspection at
`.local/diagnostics/20260930T060902.641410Z/inspection.json` confirmed the same
boot, PM success count 11, all PM failure counters zero, zero taint and restored
`pm_test=none` / `pm_async=1`. The candidate phase also encountered a transient
SSH protocol-banner failure during collection; its saved retry completed and
both independent SSH routes passed without resubmitting the PM test.

The recorder now reserves **256 KiB per CPU** (1 MiB across this four-core board)
so a serialized callback sequence can fit on a single CPU. It records that size
in the result and also rejects commit overruns or missing CPU statistics. The
complete on/off/on sequence is rerun with this same setting for every phase.
No kernel rebuild, input power policy or timing constant was changed.

After this correction, the 224-test tool suite (one optional skip), all 13
runtime tests and the existing compiled/lint checks passed. Read-only keypad inspection at
`.local/diagnostics/20260930T061017.740647Z/keypad.json` independently confirmed
`persist=1`, runtime policy `on` and unchanged wake behavior before rerunning.

## Complete hardware comparison

The full rerun passed at
`.local/diagnostics/20260930T061124.693722Z/`. Each phase has its own
`before.json`, `run.json` and `result.json`; `comparison.json` records the
completed sequence. The boot remained
`b749db5f-89ef-4208-9fc6-fe44bd38c873` throughout.

| Phase | Persistence | Debug stage | Healthy handle after stage | Total to healthy handle |
| --- | --- | --- | --- | --- |
| Baseline before | 1 | 9.525 s | 1.717 s | 11.242 s |
| Candidate | 0 | 6.210 s | 3.162 s | 9.372 s |
| Baseline restored | 1 | 9.429 s | 1.703 s | 11.132 s |

All stage durations include the deliberate five-second debug pause. The total
is stage duration plus the observed post-stage healthy-handle delay. Comparing
the candidate with the mean of its surrounding baselines gives:

- Approximately **3.27 seconds shorter** in the driver/debug stage.
- Approximately **1.45 seconds longer** waiting for a new healthy input handle
  after that stage returns.
- Approximately **1.81 seconds earlier** overall healthy-handle availability.

The useful result is roughly **1.8 seconds**, not the entire three-second
driver-stage reduction. Polling and inspection overhead limit timing precision.
These are serialized, instrumented debug tests; they do not establish actual
sleep/resume latency, first button delivery, statistical long-run bounds or an
energy improvement. The initial incomplete batch showed the same direction but
is not included in the accepted comparison.

Both baselines logged `Waited 2000ms for CONNECT`; their keypad USB resume
callbacks took 3.021151 and 3.021350 seconds. The candidate logged no such wait
and its keypad callback returned in approximately 3 microseconds. That is not
a three-microsecond hardware recovery: the disconnect/re-enumeration path
continues afterwards, as the handle-readiness timings demonstrate.
The locked `drivers/usb/core/driver.c:usb_resume()` explicitly maps ENODEV and
ESHUTDOWN to a zero callback result for devices disconnected while suspended;
that callback result alone does not establish input continuity.

Every phase had one keypad disconnect, a dead original input handle and a
healthy newly opened handle with no held keys. Persistence/tracing/PM control
restoration and fresh USB/Wi-Fi SSH passed every time. Each trace contained
3,742 events with zero overruns, commit overruns or dropped events at the same
256 KiB per-CPU setting. There were zero unsupported-ULPI warnings and one
firmware load for the entire boot.

| Phase | Run ID |
| --- | --- |
| Baseline before | `a28bcf11548040f6a177683a8a20f0e2` |
| Candidate | `513edd5f3f174a01aca3c23455e9e576` |
| Baseline restored | `85d8db56c81745f28d3fe2ac78c5f370` |

Final independent inspections are
`.local/diagnostics/20260930T061559.362328Z/inspection.json` and
`.local/diagnostics/20260930T061559.326273Z/keypad.json`. They confirm PM success
count 14, all failure counters zero, all seven services active without restarts,
zero taint, `pm_test=none`, `pm_async=1`, and keypad `persist=1` / `control=on`
with unchanged wake behavior. The original policy is restored and no boot
setting was changed. This batch did not request a new physical button or visual
test; software backlight/input state returned normally under the existing gates.

## Decision

Persistence-off is a useful candidate for a sleep policy that deliberately
powers the keypad down: it avoids an exhausted wait and improves measured
recovery. Both tested policies lose the original input handle, so applications
still need to reopen the keypad. Keep this as a measured
candidate rather than silently changing the running default or claiming
seamless resume.

The next comparison should isolate temporary keypad supply retention to learn
whether the original input handle can survive and whether the startup delay
can be removed. That requires a separately identified boot/DT configuration and
recovery path, with energy measurement before selecting retention for normal
sleep. The recorded persistence-off behavior provides the faster power-off
baseline. Held/released-key behavior, actual input-event delivery, real sleep,
final wake latency and energy remain separate qualifications.
