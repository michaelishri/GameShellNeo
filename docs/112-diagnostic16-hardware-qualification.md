# Diagnostic.16 hardware qualification (NEO-88)

3 October 2026, Pacific/Auckland. Diagnostic.16 has been written to the owner's
Samsung DEV card, verified by full readback and safely ejected. The owner
confirmed first boot; integration, journal and awake prerequisites passed.
One freezer and one driver cycle passed the automated checks. Visual
confirmation after the driver cycle and late/noirq qualification remain pending.

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

The owner has been asked to confirm normal dim-console return and readiness
for one late/noirq cycle. No further PM test is running while that response is
pending. No actual sleep has been entered.

The prior diagnostic.15 warning occurred in one of five late/noirq cycles.
Repeated reviewed runs and complete logs are required for comparison; successful
flashing does not resolve that warning. Actual sleep, product power-key gestures,
firmware-country readback, NEO-55 and energy savings remain unqualified.
