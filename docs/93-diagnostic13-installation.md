# Diagnostic.13 installation (NEO-73)

1 October 2026. The owner requested installation of the prepared image before
bed so unattended work could continue. This follows
[report 91](91-diagnostic13-preparation.md). Observed PM/button/cable tests
remain for an attended session.

## Flash and recovery

The owner confirmed that the Samsung DEV card was in the Mac reader. Fresh
inspection found the expected external physical 64,013,467,648-byte card,
512-byte blocks, Micro SD/M2 reader and diagnostic FAT16/Linux layout.
Its device identifier for this insertion was `disk16`; future operations must
inspect it again.

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

The saved workflow verified the staged compressed/decompressed image, checked
the target identity, demonstrated the Disk Arbitration mount veto, wrote the
image, read back all 4,294,967,296 bytes and safely ejected the card. Readback
SHA-256 matched `a3d09a49e27a48c1e51ac893aa16f899955eb4f3510ac00bf3ce2f03a65cd198`.
The image is `0.1.0-diagnostic.13`, kernel `6.18.54-gameshellneo13`.

Private evidence:

- `.local/neo73-mac-status.log`, `neo73-mac-inspect.log`,
  `neo73-mac-preflight.log` and `neo73-mac-flash.log`.
- `.local/diagnostics/20261001T103033.070036Z/flash-result.json` and `flash.log`.

Diagnostic.12 recovery remains under
`.local/recovery/diagnostic12-before-wifi-worker-errors/`; its raw and compressed
images are retained. [Report 92](92-build-artifact-retention.md) describes
older-artifact pruning and preserved compressed recovery.

## Running baseline

The owner confirmed the normal login screen after reinsertion. USB SSH and
independent Wi-Fi SSH reached boot `b5e3abbd-775f-4004-9100-0c7a20dfb59b`,
reporting the expected image and kernel. The provisioned network worked
without a credential change. An earlier USB probe before startup confirmation
had no route; the subsequent running checks passed.

```sh
task device:status ROUTE=usb
task device:boot-cycles CYCLES=0
task device:exec ROUTE=usb -- /usr/sbin/iw reg get
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
```

`CYCLES=0` checks the current boot and routes; it requests no physical cycle.
All seven boot-inspected services were active with zero restarts, no failed
units and kernel taint zero. Four CPUs, approximately 998 MiB RAM, the display
and both expected input devices were present. USB was configured at high speed.
The pinned BCM43430/0 firmware identity appeared once, with zero tracked
firmware-crash, SDIO-removal or runtime-PM-underflow markers.

All six integration groups passed: image identity, service state,
database/policy, journal ACLs, disposable loopback BPF enforcement and country
state. Provisioning remains NZ; the current AP announces AU, previously
accepted by the owner. The firmware's separate country-99 rules remain
unqualified.

The ready marker was 18.097 seconds after the kernel monotonic origin.
`systemd-analyze` reported 2.698 seconds kernel plus 20.745 seconds userspace.
These are one diagnostic boot's software milestones, not button-to-display
timing or evidence of the five-second goal.

## PM and peripheral baseline

- Normal sleep targets remain masked and all four systemd sleep permissions
  remain disabled. PM test is `none`, async is `1`, and all success/failure
  counters are zero. No PM stage ran in this installation slice.
- SDIO retained power and keypad supply retention remain present. Both USB
  polling/diagnostic experiments remain off. CPU policy remains `schedutil`,
  with 120–1008 MHz limits.
- The keypad is USB `1-1`, device number 2, with the expected input links,
  persistence 1, runtime control `on` and zero port quirks. This is presence
  verification, not physical-button or suspend-continuity qualification.
- The `GameShellNeo` audio card has both PCMs closed, speaker/headphone
  amplifiers Off and the speaker-enable GPIO low. No tone was played.
- External USB/AC input was present and online. Battery monitoring was valid,
  reporting 100%/Charging and 4.2548–4.2559 V. The configured charge target
  remains 4.200 V and current 1.2 A. This repeats the unresolved software-voltage
  discrepancy in [report 30](30-bl5c-battery-identification.md); neither the
  percentage nor these readings establish physical capacity, voltage accuracy
  or matching pack charge limits. No charging setting was changed.

Private evidence under `.local/diagnostics/`:

| Capture | Directory / file |
| --- | --- |
| USB status | `20261001T103634.990528Z/status.txt` |
| Current boot and independent Wi-Fi | `20261001T103714.571544Z/b5e3abbd-775f-4004-9100-0c7a20dfb59b.json` |
| PM baseline | `20261001T103714.589639Z/inspection.json` |
| Keypad baseline | `20261001T103714.430541Z/keypad.json` |
| Audio baseline | `20261001T103714.494772Z/audio.json` |
| Integration | `20261001T103802.426259Z/integration.json` |

Host task transcripts are `.local/neo73-*.log`. Installation and running
baseline checks passed. Subsequent bounded awake radio, storage/load and
battery-policy checks passed in [report 94](94-unattended-diagnostic13-validation.md). The observed freezer/devices,
physical input and USB sequence in report 91 remains for an attended session.
Patch 0018's fatal-error policy still requires cold restart. These baseline
checks do not resolve NEO-55 or qualify actual sleep, injected driver faults,
energy savings or automatic radio recovery.
