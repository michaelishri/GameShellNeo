# Diagnostic.16 hardware qualification (NEO-88)

3 October 2026, Pacific/Auckland. Diagnostic.16 has been written to the owner's
Samsung DEV card, verified by full readback and safely ejected. The owner
confirmed first boot; integration, journal and awake prerequisites passed.
One freezer, one driver and five late/noirq cycles passed the automated checks.
The owner confirmed normal display after the driver, first late/noirq and
four-repeat batch. Final health, settings and idle audio matched the baseline.
The earlier suspended-transmit warning did not recur in this bounded comparison;
actual sleep remains untested and disabled for normal use.

[Report 111](111-diagnostic16-preparation.md) records the complete build,
offline checks, retained diagnostic.15 recovery and staged archive. The source
changes are [transmit suspend ownership](109-wifi-transmit-suspend-ownership.md)
and [band capability query errors](110-wifi-band-query-errors.md).

## Pre-flash state

The owner returned for testing. The Mac and diagnostic.15 GameShell were
reachable using the saved tasks. USB access showed
`6.18.54-gameshellneo15`, active inspected services with no restarts, no failed
units and kernel taint zero. The battery monitor reported 100%, Charging and
4.1866 V; this is a software reading, not a capacity or voltage calibration.
No charging setting was changed.

The initial read-only status capture is
`.local/diagnostics/20261002T181643.200822Z/`; host transcripts are
`.local/neo88-mac-status.log` and `.local/neo88-device-before-flash.log`.

## Card installation

After shutdown/card-move instructions, the owner confirmed completion. Fresh
Mac inspection found one external physical USB card at `disk16`, capacity
`64013467648` bytes, with the existing `armbi_boot` and Linux partitions,
matching the intended 64 GB DEV card. The saved sequence was:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

The disk identifier is this session's observation; always identify the physical
DEV card afresh before another write. Preflight verified the compressed and
decompressed image hashes and recorded target identity. The flash repeated
those checks, activated the mount guard, unmounted the volume and verified
that macOS could not remount it during the operation.

All `4294967296` image bytes were written and read back with SHA-256
`de531424ec88e55cbc991e757e295e49658a8991fb0058c5380bc969814d90c7`,
matching `GameShellNeo-0.1.0-diagnostic.16-cpi31-de531424ec88.img`.
The card was safely ejected. The flash result records `readback: passed`,
`mount_guard_verified: true` and `hardware_boot_tested: false`.

Flash evidence is
`.local/diagnostics/20261002T182154.163870Z/flash-result.json` and `flash.log`.
Host transcripts are `.local/neo88-mac-card-status.log`,
`.local/neo88-mac-inspect.log`, `.local/neo88-mac-preflight.log` and
`.local/neo88-mac-flash.log`.

## Startup and awake prerequisites

The owner confirmed the normal login screen after reinsertion. USB and
independent Wi-Fi SSH reached the same boot,
`edb5b83b-8de9-425b-91fe-afb8e66ee39f`, running
`6.18.54-gameshellneo16` / `0.1.0-diagnostic.16`. The complete installed image
manifest matches the verified build, including both new patch hashes in
report 111. The firmware and board-specific NVRAM hashes match the locked inputs.

All six integration groups passed: image identity, service state, database and
policy, journal ACL, BPF enforcement and country policy. Inspected services were
active with zero restarts; there were no failed units and kernel taint was zero.
Provisioning remains NZ, the owner's accepted AP announcement sets global AU,
and the phy label is 99. Firmware-country readback remains unqualified.

The raw startup log identifies the expected BCM43430/0 firmware `7.13.53.9`.
It contains no country/control timeout, capability-query error or rejected
transmit warning. Existing board-specific binary/CLM/txcap fallback messages
remain visible; the pinned generic binary loaded and Wi-Fi associated.

Normal sleep targets are masked; the only advertised memory-sleep mode is
s2idle. `pm_test` is none, async is 1 and the debug delay is five seconds.
The idle audio baseline was saved without playback. Post-boot battery monitoring
reported valid samples, 100%, Charging and 4.1899 V; no policy was changed.

Ordinary journal rotation passed with no journald restart, history loss or
displaced-file change. Awake power-key ownership verified the inhibitor and
exclusive input ownership, saw no key events and returned ownership normally.
The ten-second awake RTC test delivered one `RTC_IRQF | RTC_AF` notification
after **10.240 seconds**, then restored the original disabled logical alarm.
RTC run ID: `11f5ff69f67444df9bd54ca073228117`. These are awake prerequisites,
not gesture, sleep or wake qualification.

Saved tasks were `device:pm-inspect`, `device:journal-inspect`,
`device:audio-inspect`, `device:check ROUTE=usb ACTIVE_COUNTRY=AU`,
`device:journal-rotation`, `device:power-key-smoke`, `device:rtc-smoke` and
`device:status ROUTE=usb`. Explicit read-only `device:exec` commands saved the
installed manifest, raw kernel log, Wi-Fi boot identity, radio hashes and sleep
target states. The host transcripts use `.local/neo88-*.log`.

| Evidence | Capture under `.local/diagnostics/` |
| --- | --- |
| Initial PM inspection | `20261002T182643.636604Z` |
| Initial journal | `20261002T182722.679351Z` |
| Integration | `20261002T182804.412695Z` |
| Audio inspection | `20261002T182848.087563Z` |
| Journal rotation | `20261002T182944.105306Z` |
| Awake power-key ownership | `20261002T183004.037801Z` |
| Awake RTC delivery | `20261002T183039.167443Z` |
| Post-boot status | `20261002T183138.890944Z` |

Two collection mistakes are retained in the host logs. An initial audio
inspection met the host PM lock held by journal inspection and stopped before
device access; the subsequent sequential inspection passed. An explicit NVRAM
hash command initially used the absent generic filename; checking the actual
board-specific filename from `tools/image.py` passed. Neither was a device
failure or a retried PM submission.

## Attended PM qualification

The owner explicitly confirmed readiness to watch a freezer check followed by
one driver cycle, with USB connected and controls untouched. The freezer stage
passed with both SSH routes verified on the same boot. Run ID:
`32d90875783d4230bf7d5e7c26dc46d5`; evidence:
`.local/diagnostics/20261002T183313.191668Z/cycle-1/` and
`.local/neo88-freezer.log`.

The traced driver cycle also passed, run ID
`a3299cd414844d64a4fe546fce9f9691`. Evidence is
`.local/diagnostics/20261002T183428.008945Z/cycle-1/`,
`.local/neo88-devices.log` and `.local/neo88-kernel-after-devices.log`.
The debug stage took **7.893 seconds**, including the five-second debug wait;
this is not a real-sleep resume-latency measurement.

Both SSH routes recovered on the same boot. PM counters advanced from one to
two successes, with all failure counters remaining zero. Process memory and
settings restoration passed, power-key ownership was returned, and Wi-Fi
logging/tracing was restored without trace loss. The Wi-Fi trace recorded two
EAPOL transmissions and two receptions. The original keypad handle remained
healthy, with unchanged USB device number and input path, no keypad disconnect
or supply-disable event, and complete restored tracing. No physical button
input has been tested in this slice.

The raw kernel log contains the expected debug hold and keypad reset-resume,
with no new country/control timeout, band-query failure, unsupported-register
warning or suspended-transmit rejection. The collector encountered a temporary
route/channel failure and an SSH session/banner failure during recovery, then
retrieved this same run successfully. Both failed connection attempts remain
in the capture; no PM submission was retried. Access latency is unqualified.

The owner confirmed normal dim-console return and readiness for one late/noirq
cycle. The saved `task device:pm-platform` then passed, run ID
`6c7055a5751849e2b15a4e7e11ee5cfc`. Evidence is
`.local/diagnostics/20261002T185305.665142Z/cycle-1/`,
`.local/neo88-platform-first.log` and
`.local/neo88-kernel-after-platform-first.log`.

The stage took **7.966 seconds**, including the five-second debug wait. Both SSH
routes recovered on the same boot, and PM successes advanced from two to three
with every failure counter still zero. Process memory, settings and power-key
ownership restoration passed. The original keypad handle, USB device number
and input path survived, with no disconnect or supply-disable event. Wi-Fi
tracing was restored without loss and recorded two EAPOL transmissions and two
receptions. A temporary SSH channel-open timeout recovered while collecting
this same run; there was no repeated PM submission.

Trace validation found all four ordered late/noirq phase pairs and **1,903
device callback returns with zero errors**. RSB noirq resume finished at ftrace
time `1676.189547`, before PEK noirq resume began at `1676.189607`. The trace
contains no actual-sleep entry. The raw kernel log shows the expected RSB
restore and keypad reset-resume, without a new country/control timeout,
band-query failure, unsupported-register warning or suspended-transmit
rejection. These observations establish this debug cycle's recovery, not actual
sleep/wake reliability or resume latency.

The owner confirmed normal dim-console return and gave fresh readiness for
four further late/noirq cycles, reviewed individually.

## Four-repeat comparison and final state

Each repeat used one invocation of `task device:pm-platform`. The completed
result, callback trace, keypad retention, both independent SSH proofs and raw
kernel delta were reviewed before starting the next. The owner subsequently
confirmed that all four display returns and final brightness looked normal.

| Repeat | Run ID | Private capture | Stage including 5 s debug hold |
| --- | --- | --- | --- |
| 1 | `a49b1e28cb14466886178487637e095a` | `20261002T190057.578761Z` | 8.047 s |
| 2 | `f24898a5b5834de295df4078f7e4b1b8` | `20261002T190253.625880Z` | 7.867 s |
| 3 | `135c6d74d0d84d028f22acad8a697875` | `20261002T190445.281634Z` | 7.893 s |
| 4 | `6fb0f67235f2420fab8d266e257c36b4` | `20261002T190648.133179Z` | 7.907 s |

Captures are under `.local/diagnostics/<capture>/cycle-1/`. Host transcripts
are `.local/neo88-platform-repeat{1,2,3,4}.log`; corresponding raw kernel logs
are `.local/neo88-kernel-after-platform-repeat{1,2,3,4}.log`. Each capture
includes the original result and a local review summary produced using the
existing retention and platform validators.

Every repeat preserved process memory, the original keypad handle, USB number
and input path, with no disconnect or keypad-supply-disable event. Power-key
ownership returned normally. All four late/noirq phase pairs were present in
each trace, with 1,903 callback returns per cycle and no callback errors, trace
loss or actual-sleep entry. RSB noirq completion preceded PEK noirq entry in
each. Wi-Fi tracing was restored and recorded two EAPOL transmissions and two
receptions per repeat. Both SSH routes recovered on the original boot.

All five late/noirq raw-log intervals were free of the earlier suspended-transmit
rejection and tracked country/control, band-query and unsupported-register
errors. The complete raw kernel history was preserved across collection. The
first three repeats recorded transient no-route/channel collection errors;
repeat four recorded a channel-open timeout. Each original run was recovered
without repeating its PM submission. These access interruptions remain recorded;
the checks do not qualify network recovery latency.

Final saved checks were:

```sh
task device:pm-inspect
task device:audio-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:exec ROUTE=usb -- sudo -n dmesg --time-format=raw
```

PM successes reached **7** with every failure counter zero. The final snapshot
passed the existing PM admission validator and matched the initial identity,
kernel/configuration, normal sleep masks and PM controls, USB experiments,
retained supplies, services, taint, Wi-Fi configuration/power save, charging
and CPU policy, input/backlight and radio hashes. Battery monitoring remained
valid; no charging setting changed. The entire final idle audio inspection
matched its initial capture, including closed PCM devices and both amplifiers
off. All six integration groups passed, with the accepted NZ provisioning / AU
AP announcement / phy 99 policy unchanged.

Final captures: PM `20261002T190857.680765Z`, audio
`20261002T190915.512072Z`, integration `20261002T190953.454185Z`.
Host transcripts are `.local/neo88-{pm,audio,integration}-final.log`; the final
raw kernel log is `.local/neo88-kernel-final.log`. Comparison evidence is
`.local/neo88-final-baseline-comparison.json`. No new kernel entry appeared
between the last repeat's raw capture and the final check.

## Conclusion and remaining limits

Diagnostic.15 logged one `xmit rejected state=0` warning in five late/noirq
cycles. Diagnostic.16 completed the same one-driver/five-late-noirq comparison
without that warning, country/control timeouts or band-query errors. This
supports the new driver's behavior on this board and boot. It does not prove
that every possible transmit/control producer is excluded during suspension,
identify the earlier packet, exercise every capability-query failure branch,
or establish long-term radio reliability. The source failure-path tests remain
separate evidence from these successful hardware runs.

NEO-88's installation and attended debug comparison are complete. Actual sleep,
product power-key gestures, firmware-country readback, NEO-55 and energy savings
remain unqualified. Physical keypad taps, speaker playback and cable cycles were
not repeated in this slice. Normal sleep stays masked and the diagnostic short
power press still requests shutdown. Diagnostic.15 recovery remains available.
