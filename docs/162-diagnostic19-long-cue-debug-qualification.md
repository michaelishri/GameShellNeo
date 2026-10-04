# Diagnostic.19: refreshed qualification with long warnings

5 October 2026, Pacific/Auckland; capture timestamps are UTC. NEO-112 and
NEO-115.

The refreshed debug sequence passed, and the owner confirmed clear long
warnings and normal dim-console return after all six dark intervals. This
prepares a fresh admission record for the USB-removal sleep scenario. It does
not itself enter real sleep or qualify removal during sleep.

The earlier connected-USB sleep result in
[report 160](160-diagnostic19-first-rtc-wake.md) remains unchanged. The audio
helper changed during [report 161](161-active-audio-path-investigation.md), so
that consumed, different-source chain was not extended or rewritten.

## Admission and readiness

- Image/kernel: `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19`.
- Boot: `2fa86697-ead3-4e6f-a295-44e6ad203983`, unchanged throughout.
- Helper source commit: `749ef9d`; no helper, image, driver or firmware change
  during the sequence.
- Initial read-only PM inspection: `20261004T231012.727320Z`; validated against
  the installed image/source lock, PM successes 8, failures 0, SDIO usage 2,
  configured USB, battery telemetry 100%, no failed services.
- Independent Wi-Fi status passed through the configured Mac route.
- Read-only power policy: `20261004T231025.468850Z`; no retained ownership or
  diagnostic drop-in, original poweroff/idle-ignore policy.
- Read-only RTC inspection: `20261004T231025.455872Z`; alarm disabled. Platform
  admission retained the existing successful same-boot awake RTC qualification.

The owner explicitly agreed to watch and listen through the freezer, driver and
five late/noirq cycles, with USB connected and controls untouched. Each command
was submitted once; the original completed result, trace and both route proofs
were reviewed before the next command.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# Repeat the final command four times, reviewing each result first.
```

## Results

Each capture below contains `cycle-1/result.json` under `.local/diagnostics/`.

| Stage | Capture | Run ID | Stage seconds | Final PM successes |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261004T231143.139171Z` | `9236e4af5e1745138233ecf21b59cf47` | 5.792 | 9 |
| Driver | `20261004T231259.423052Z` | `2394150110b14cb2a08c3bc6c8a09b9a` | 7.775 | 10 |
| Late/noirq 1 | `20261004T231417.955907Z` | `d2a53816914b400aa310b07885d54026` | 7.874 | 11 |
| Late/noirq 2 | `20261004T231551.525827Z` | `39820322fb6d4be5b29d880cf6da1b23` | 8.005 | 12 |
| Late/noirq 3 | `20261004T231710.330558Z` | `e756c102ba4047ffa78a163d0fc74fdf` | 7.953 | 13 |
| Late/noirq 4 | `20261004T231832.398466Z` | `08377d860c674013aae94461b2fb7da2` | 7.814 | 14 |
| Late/noirq 5 | `20261004T232001.622426Z` | `49f2b14776774d15a1d7b4809d7d42a8` | 7.892 | 15 |

Every completed result has independent USB and Wi-Fi SSH proofs. PM failure
counters remain zero; SDIO stays active/forbidden with usage 2 and control `on`.
The original keypad handle survives every driver/platform cycle with no held
key at completion. Power-key ownership is handed back; complete keypad/Wi-Fi
traces and their settings are restored. Every platform trace contains the four
late/noirq phases in order, with successful RSB noirq suspend/resume callbacks.
No unsupported USB-register warning appears in the new journal intervals.

Every screen warning records level 5, duration 1,000 ms, completed playback,
idle amplifiers and restored mixer controls before PM. The owner answered
**“Yes—warnings clear and all returns normal.”** The freezer check does not
blank the display and remains silent. These stage timings include the debug
delay; they are not production sleep/wake latency or an energy measurement.

The first platform collector retained `SSHException: No existing session` and
a protocol-banner exception in its private log. It then collected the exact
original completed run and independently proved both routes. No cycle was
resubmitted and no transport cause was inferred from the transient failure.

## Evidence and continuation

The saved `check:sdio-ref-history -- --require-stable` task generated
`.local/neo112-long-cue-debug-history.json`, SHA-256
`3d266bac27eea6690059a02532951598656279f28fb0061ac46879ef0024be47`.
Fresh inspection `20261004T232149.495555Z` matches PM 15/0. The actual-sleep
controller's receipt validator accepted all seven records for `usb-remove`,
with no prior sleep records in this new chain.

Original result SHA-256 values, in table order:

```text
5e5d3e3d7148d11c567c604dfe44dfa0a89060f9556643315373d51197e0450c
0bba1827ed53aa1de8d9217fc39c9fbf363294e79564eb8e164bec5df8740bf6
9d05f3b69230c55877d23361f5b436b079aafaf2cc91fbf46d368d88ab3d6b11
28dcfcb9bd631f1bb30eed0695c9a3af315b7d942f43c1f302203aaa03c4e98c
209a919b6470b05faa8e93d3f10af74c3f8dc25a3f9d29d369f134a82976d5c4
65fc8e28e7770a2e19f3a9bcc739cb7ac7a76c9a24f1df964e83750928061cb0
cc02a5aee57123bfc6b9cbd320f1e7115e2f4a247d6154844f2e239761c547eb
```

NEO-115's screen-warning observation is now satisfied for this batch. Its reboot
observation remains pending the next required reboot; none was introduced here.
The next step is a separately described, freshly attended single removal
attempt after the successful awake rehearsal below. Normal sleep
remains disabled. The installed image's prospective masked-removal dispatch
criteria are unchanged; this slice also corrects the README's outdated
exact-dispatch description to match [report 154](154-usb-sleep-session-retirement.md).

## Awake removal rehearsal

The saved command completed without entering sleep or changing the cable:

```sh
task device:sleep-cable-remove-rehearse \
  QUALIFICATION=.local/neo112-long-cue-debug-history.json CABLE_ACTION=1
```

Capture `20261004T232223.856659Z`, run `0758d0c21a3143e8a6e540123e798da4`,
passed same-source revalidation. Its `result.json` SHA-256 is
`c653216437b3fedf00c2c44b0159c91380420ed97f68391ad3c493210816f275`.
The 30.603-second awake deadline delivered one RTC event with flags `0xa0`;
IRQ 31 rose from 4 to 5. The alarm, original power policy and all owned settings
were restored. PM counters stayed 15/0; both SSH routes were verified.

USB stayed configured/carrier 1, PHY present, and AC/USB present/online at all
three cable observations. All four cable-handler counters remained unchanged.
This is an awake admission check, not removal or wake-from-sleep evidence.
