# Diagnostic.17 hardware qualification (NEO-92)

3 October 2026, Pacific/Auckland. Diagnostic.17 has been written to the owner's
Samsung DEV card, verified by full 4 GiB readback and safely ejected. The owner
confirmed the login screen; startup integration, journal rotation and awake
power-key/RTC checks passed. One freezer, one driver and five late/noirq cycles
passed, with the SDIO reference count stable at 2 throughout. The owner confirms
normal display after each observed stage/batch. Final restoration and health
checks passed. This completes NEO-92's bounded hardware comparison; real sleep
and energy savings remain unqualified.

[Report 117](117-sdio-runtime-reference-ownership.md) records the SDIO
runtime-reference fix, source regression coverage, build provenance and
diagnostic.16 recovery. This installation uses that exact verified artifact.

## Card installation

The owner confirmed that the DEV card was in the Mac reader. Fresh status and
inspection found the external physical USB card at `disk16`, capacity
`64013467648` bytes, with its existing `armbi_boot` and Linux partitions. The
saved workflow was:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

The disk number describes this installation only; inspect the physical card
afresh before another write. Preflight and flash both verified compressed and
decompressed image hashes and the recorded card identity. The mount guard
started, the card was unmounted, and a blocked macOS mount attempt established
that the guard was effective before writing.

All `4294967296` bytes were written and read back. SHA-256
`7923af46c3e58bc85030adb2702bba9b822f61f25d03ed8573702040f7a31048`
matches `GameShellNeo-0.1.0-diagnostic.17-cpi31-7923af46c3e5.img`.
The saved result records `readback: passed`, `mount_guard_verified: true`,
`ejected: true` and `hardware_boot_tested: false`.

Evidence is
`.local/diagnostics/20261003T021523.043587Z/flash-result.json` and `flash.log`.
Host transcripts are `.local/neo92-mac-inspect.log`,
`.local/neo92-mac-preflight.log` and `.local/neo92-mac-flash.log`. The transfer
and image hashes remain recorded in report 117.

## Startup and awake prerequisites

USB and independent Wi-Fi SSH reach the same boot,
`0dc9db12-dcb4-465d-853c-1a087d9af332`, running
`6.18.54-gameshellneo17` / `0.1.0-diagnostic.17`. The complete installed image
manifest exactly matches the verified build, including patch 0023. The radio
firmware/NVRAM hashes match the retained inputs.

All six integration groups passed: image identity, services, database/policy,
journal ACL, BPF enforcement and country policy. Inspected services were active
with zero restarts, no units were failed and kernel taint was zero. Provisioning
remains NZ; the previously accepted AP announcement sets global AU, with phy
label 99. Firmware-country readback is not qualified.

The startup kernel log selects BCM43430/0 firmware `7.13.53.9`. The existing
board-specific binary/CLM/txcap fallback messages remain; Wi-Fi associates using
the pinned generic binary. There is no runtime-reference underflow, firmware
crash or new suspend warning in this startup capture.

Initial `1c10000.mmc` runtime usage is **2**, active, forbidden and with control
`on`, matching diagnostic.16's initial snapshot. The RSB supplier remains active
with usage 1 and control `auto`. Both suspend success/failure counters start at
zero. Normal sleep targets are masked; the only memory-sleep mode is s2idle,
`pm_test` is none, async is 1 and debug delay is five seconds. Backlight is 1
with power 0. Idle playback/capture PCM streams are closed and both amplifiers
are off; no tone was played.

Ordinary journal rotation passed without journald restart, history loss or
displaced-file changes. Awake power-key acquisition and handoff passed with no
key events. The ten-second RTC check delivered one `RTC_IRQF | RTC_AF`
notification after **10.313 seconds** and restored the disabled logical alarm.
RTC run ID: `2fefe58d144f49c3a13935015b07d79a`. These are awake prerequisites,
not sleep or wake qualification. Initial battery telemetry reports 100%,
Charging, 4.1877 V; no charging policy was changed.

| Evidence | Capture under `.local/diagnostics/` |
| --- | --- |
| Startup status | `20261003T021859.954273Z` |
| Initial PM snapshot | `20261003T021919.973076Z` |
| Integration | `20261003T021945.608923Z` |
| Journal inspection | `20261003T022017.915977Z` |
| Idle audio | `20261003T022025.112735Z` |
| Journal rotation | `20261003T022026.888650Z` |
| Awake power-key ownership | `20261003T022031.563977Z` |
| Awake RTC delivery | `20261003T022035.309919Z` |

The saved commands were `device:status ROUTE=usb`, `device:pm-inspect`,
`device:check ROUTE=usb ACTIVE_COUNTRY=AU`, `device:journal-inspect`,
`device:audio-inspect`, `device:journal-rotation`, `device:power-key-smoke` and
`device:rtc-smoke`. Explicit read-only `device:exec` commands retrieved the
installed manifest, raw kernel log and Wi-Fi boot ID. Host transcripts are
`.local/neo92-startup-*.log`, `.local/neo92-device-startup-status.log` and
`.local/neo92-installed-image.json`.

## Initial attended cycles

The owner explicitly confirmed readiness for the freezer check followed by
one driver cycle, with USB connected and controls untouched. The saved commands
were:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task check:sdio-ref-history -- --require-stable .local/diagnostics/20261003T022229.328290Z/cycle-1/result.json
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task check:sdio-ref-history -- --require-stable .local/diagnostics/20261003T022229.328290Z/cycle-1/result.json .local/diagnostics/20261003T022334.265937Z/cycle-1/result.json
```

The freezer stage passed, run `b616e1f39e8f4fb1a29df8975c873e4a`, followed by
the driver stage, run `7b6e5a630c874d8cb71faf41c06cf2be`. Both SSH routes were
verified after each. PM successes advance 0→1→2, with all failure counters zero.
The driver stage took **7.906 seconds**, including the five-second debug wait;
this is not a real-sleep resume-latency measurement.

Both reference snapshots are **2→2**, with no change between cycles. The saved
strict comparison passes in `.local/neo92-initial-reference-history.json`.
The old diagnostic.16 driver cycle was 2→3. This is initial hardware evidence
for the fix; repeated late/noirq comparison remains required.

The original keypad handle remains healthy with unchanged USB device number 2
and event1 input path. Trace buffers report no loss, and keypad/Wi-Fi tracing
and logging are restored. The radio trace captures two transmitted and two
received EAPOL frames, with completed association. Power-key ownership is
returned with no input events; memory and ordinary PM restoration checks pass.
The raw kernel delta contains the expected debug hold and keypad reset-resume,
without a new warning or reference underflow. The owner confirmed normal dim
console return and readiness before proceeding deeper; no physical button
sequence has been performed.

Cycle evidence is `.local/diagnostics/20261003T022229.328290Z/cycle-1/` and
`.local/diagnostics/20261003T022334.265937Z/cycle-1/`. Host transcripts are
`.local/neo92-freezer.log`, `.local/neo92-devices.log` and
`.local/neo92-kernel-after-devices.log`.

## Initial late/noirq cycle

After that readiness response, `task device:pm-platform` passed, run
`b57e5c282b1942e08a4364e118ab56e9`, with both network routes recovered. All four
late/noirq phases and the RSB suspend/resume noirq callbacks returned normally,
with no nonzero callback result or trace loss. The original keypad handle
remained healthy; key ownership and logging/tracing were restored. The stage
took **7.954 seconds**, including the five-second debug delay, and PM successes
advanced to 3 with all failure counters zero. The same-boot RTC qualification
was checked before entry.

The SDIO snapshots remain **2→2**, also matching both earlier cycles. The strict
three-cycle comparison passes in
`.local/neo92-initial-platform-reference-history.json`. A temporary SSH channel
failure during recovery is retained in the collection evidence; the collector
retrieved this same run after reconnection without repeating PM submission.

Evidence is `.local/diagnostics/20261003T022612.492835Z/cycle-1/` and
`.local/neo92-platform-initial.log`. The owner confirmed normal dim console
return and explicitly requested the four-repeat observation batch next.

## Four observed repeats

The owner confirmed readiness to observe the four-cycle batch. Each repeat used
`task device:pm-platform`; its result, full accumulated strict reference history
and health evidence were reviewed before submitting the next. All four passed.
The owner subsequently confirmed normal dim console return after every cycle
and normal final screen/brightness.

| Repeat | Run ID | Stage seconds | SDIO usage | Capture under `.local/diagnostics/` |
| --- | --- | ---: | --- | --- |
| 1 | `62df54c4ef2242e59ef3c99813d9ede3` | 8.085 | 2→2 | `20261003T022800.726235Z/cycle-1/` |
| 2 | `0939cd7adbc043f688ac3bac5e9bfde0` | 7.998 | 2→2 | `20261003T022930.354463Z/cycle-1/` |
| 3 | `692308aa5efa4c3aba75425431024d85` | 7.845 | 2→2 | `20261003T023102.619598Z/cycle-1/` |
| 4 | `f6acbc9de3a84d38b92d608798a6a435` | 8.042 | 2→2 | `20261003T023237.217285Z/cycle-1/` |

All repeats retain the original keypad handle/identity, complete late/noirq and
RSB callback traces, zero callback errors, restored tracing/logging, returned
power-key ownership, process-memory checks and both verified SSH routes.
No new kernel fault appears in their recorded deltas. Repeat 1 had a transient
SSH channel failure while the collector waited for recovery; the original run
was recovered without another PM submission. Host logs are
`.local/neo92-platform-repeat{1,2,3,4}.log`.

The strict saved comparison on **all seven** accepted result files passes in
`.local/neo92-final-reference-history.json`. Every before/after value is 2;
there is no observed drift within or between the recorded cycles. Intermediate
comparison files `.local/neo92-repeat{1,2,3}-reference-history.json` preserve the
per-repeat gates. No count was reset and no runtime-PM policy was relaxed.

## Final state and conclusion

The later read-only `device:pm-inspect` at
`20261003T023422.093404Z` still records usage 2 and the same
active/forbidden/control-on policy. Its monotonic time is 971.808 seconds,
**60.013 seconds after the final cycle's after-snapshot**. The RSB supplier
remains active with usage 1. This is a later snapshot, not continuous sampling.

The complete final comparison preserves the initial image/kernel/boot identity,
PM settings, debug delay, sleep masks, radio/keypad power-retention settings,
service state, Wi-Fi configuration/power save, charging policy, CPU policy,
input paths, backlight and radio hashes. PM statistics are **7 successes,
0 failures**, with every failure-stage counter zero. The complete idle audio
inspection matches the initial one, including closed PCMs and both amplifiers
off. Journald continuity and policy checks pass across the entire session;
early kernel history is retained with no journald restart or displaced-file
change. Final raw kernel evidence contains no new fault.

The final six integration groups pass again. Power-policy inspection reports
no retained diagnostic owner or drop-in; logind remains active with ordinary
diagnostic `HandlePowerKey=poweroff`. This slice does not implement the agreed
short/2-second/8-second product gestures. Battery monitoring remains valid,
reporting 100%, Charging and 4.1866 V; this is not battery calibration or a power
measurement.

| Final evidence | Capture under `.local/diagnostics/` |
| --- | --- |
| PM inspection | `20261003T023422.093404Z` |
| Idle audio | `20261003T023430.766649Z` |
| Journal inspection | `20261003T023432.541523Z` |
| Integration | `20261003T023435.953030Z` |
| Power policy | `20261003T023442.618831Z` |

The offline final comparison is `.local/neo92-final-baseline-comparison.json`;
host transcripts and raw kernel log use `.local/neo92-final-*.log`.

The source reproduction and board comparison support the transition-based
reference fix: diagnostic.16 advanced **2→8** over one driver and five late/noirq
cycles, while diagnostic.17 stays **2 throughout** that same sequence. The
extra freezer check also leaves the count unchanged. Existing keypad, network,
PM restoration and display gates pass alongside that correction.

This closes the repeated-resume reference leak in the tested configuration.
It does not establish lower battery drain: brcmfmac's intentional forbid and
the active RSB dependency still constrain runtime suspend. Earlier firmware
recovery underflow, complete removal/fault-path qualification, actual sleep,
physical wake and wake latency remain separate work. Normal sleep stays
disabled; this result clears NEO-92's blocker for further guarded sleep work.
