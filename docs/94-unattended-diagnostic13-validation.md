# Unattended diagnostic.13 validation (NEO-74)

1 October 2026. Following [installation](93-diagnostic13-installation.md),
the owner left the GameShell on USB power through the awake Mac and authorized
work without physical interaction. This uses the existing bounded tasks.
Observed PM, button, cable and screen/audio tests remain for an attended session.

All captures belong to boot `b5e3abbd-775f-4004-9100-0c7a20dfb59b`, image
`0.1.0-diagnostic.13`, kernel `6.18.54-gameshellneo13`. Private transcripts are
`.local/neo74-*.log`; credentials and network identifiers remain in ignored
storage. No permanent policy or charging change is part of these checks.

## Saved sequence

```sh
task device:wifi-recovery SECONDS=120
task device:stability ROUTE=usb
task device:battery-check ROUTE=usb
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:boot-cycles CYCLES=0
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
```

Finish the radio comparison and restoration before starting the load test.
USB stays connected. `ACTIVE_COUNTRY=AU` checks the owner's previously accepted
AP announcement; configured NZ is unchanged. `CYCLES=0` checks this boot and
both network routes without requesting a power cycle. PM/keypad/audio
inspections do not enter a suspend stage or play sounds. Battery-policy tests
use isolated simulated readings and shutdown functions, not actual discharge
or shutdown.

The stability task writes/flushes a fresh 128 MiB random temporary file and
verifies its SHA-256 with a direct read. The workload then exercises four CPUs
and 256 MiB memory for five minutes, with verification enabled. The
unit has a time limit and stops on a sampled temperature of 80 C, kernel taint
or loss of configured USB. It removes temporary files and verifies that the
boot identity is unchanged. These are bounded software observations, not
continuous electrical measurements.

## Awake Wi-Fi result

The installed firmware remained unchanged. All four software reconnects,
synthetic unavailable-network scanning, original-network restoration and
connected observation passed. The scanning window lasted 120.156 seconds,
with thirteen scanning samples; the connected window lasted 120.178 seconds.
All seven independent Wi-Fi SSH checkpoints reached the same boot. One
expected firmware identity and zero tracked firmware-crash, SDIO-removal or
runtime-PM-underflow markers were recorded. The original configuration was
restored.

Evidence: `.local/diagnostics/20261001T103951.806246Z/`, containing
`firmware-trial.jsonl`, `wifi-ssh.jsonl` and the pinned candidate description.
This exercises ordinary awake radio use; it does not inject the transport
failures addressed by patch 0018 or reproduce physical AP loss.

## Storage, load and final state

All remaining checks passed:

| Check | Observed result |
| --- | --- |
| Storage | All 134,217,728 bytes matched the written SHA-256 through a direct read. |
| CPU/memory | Four CPU workers and one 256 MiB memory worker passed; zero failed stressors, exit 0; roughly 300 seconds each. |
| Temperature | 42.606 C baseline, maximum sampled 64.800 C, final recovery sample 54.594 C. |
| CPU recovery | Final recovery sample at 120 MHz; original `schedutil` policy and 120–1008 MHz limits retained. |
| Cleanup | Temporary storage/load files removed; same boot retained. |
| Battery-policy simulation | All nine isolated tests passed against the hash-verified installed module. |
| Integration | All six groups passed, including image identity, service state and accepted active AU/configured NZ country state. |
| Final access/services | USB and independent Wi-Fi SSH reached the same boot; seven services active with zero restarts and no failed units. |
| Kernel/radio | Kernel taint zero, one expected firmware identity, zero tracked radio faults; kernel journal unchanged from the installation baseline. |
| PM | Success and every failure counter stayed zero; test `none`, async `1`, normal sleep still masked. |
| Keypad/audio | Original devnum 2 keypad, zero port quirks; both PCMs closed and both amplifiers Off. |
| Power | USB/AC present and online; valid software estimate 100%/Charging, final reported voltage 4.1844 V. |

The later battery reading does not resolve the initial voltage discrepancy
recorded in report 93 or qualify the unidentified pack's charge limits. These
USB-powered checks did not measure battery endurance. Wi-Fi power saving
remained off; no firmware replacement, radio reset or PM stage was requested.
The load temperature is an observation for this run, not a controlled comparison
with an earlier image or evidence of a thermal/performance change.

Private evidence under `.local/diagnostics/`:

| Capture | Directory / file |
| --- | --- |
| Awake Wi-Fi | `20261001T103951.806246Z/` |
| Storage/load | `20261001T104518.676598Z/stability.jsonl` |
| Battery policy | `20261001T105124.531251Z/battery-policy.txt` |
| Integration | `20261001T105132.320836Z/integration.json` |
| Final boot/routes | `20261001T105155.266896Z/` |
| Final PM | `20261001T105155.187249Z/inspection.json` |
| Final keypad | `20261001T105155.119827Z/keypad.json` |
| Final audio | `20261001T105155.187581Z/audio.json` |

The checked comparison with the installation baseline is also saved in
`.local/neo74-final-summary.json`.

## Limits and next step

These checks do not qualify actual sleep/wake, the observed driver-debug
sequence, physical inputs/cables, error injection, long-term reliability,
battery capacity or energy savings. Patch 0018's fatal-error policy still
requires a cold restart; automatic recovery and NEO-55's original outage remain
open. Preserve diagnostic.12 recovery and perform the prepared attended
qualification in report 91 next. The known speaker-confirmation delay remains
deferred at the owner's request.
