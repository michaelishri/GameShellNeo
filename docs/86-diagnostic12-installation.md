# Diagnostic.12 installation and baseline (NEO-65)

1 October 2026, Pacific/Auckland. Owner's CPI v3.1 and previously authorized
Samsung DEV card. This follows the verified
[diagnostic.12 preparation](85-diagnostic12-preparation.md).

Flash, full readback, safe ejection, owner-confirmed login, independent USB
and Wi-Fi access, integration and read-only baseline checks passed. No PM
debug stage was entered in this slice. Owner-observed stages require a
separate ready response; normal sleep remains disabled.

## Card identification and installation

The owner confirmed shutdown and placement of the DEV card in the Mac reader.
Fresh `task mac:status` showed one external physical card; the recorded
inspection identified 64,013,467,648 bytes, 512-byte sectors, the expected
reader and the diagnostic FAT16/Linux layout. It was `disk16` for this
insertion. That disk number must not be reused without a fresh inspection.

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Preflight passed the card-identity comparison and both compressed/decompressed
image checksums. The saved flash task verified the mount guard, wrote all
4 GiB and read back the entire written region. Its SHA-256 matched the source
exactly; safe ejection passed. The owner reinserted the card, connected USB,
powered on and confirmed the normal login screen.

| Candidate | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.12-cpi31-b7c0ac5fe2a8.img` |
| Bytes | `4294967296` (4 GiB) |
| SHA-256 | `b7c0ac5fe2a8836ead3daba2a6b063fc7b002c30a051d45d26a17f00d14c61a2` |
| Expected kernel | `6.18.54-gameshellneo12` |

Private logs: `.local/neo65-mac-status.log`,
`.local/neo65-card-inspection.log`, `.local/neo65-preflight.log` and
`.local/neo65-flash.log`. Personalized images, credentials and raw device
captures remain in ignored storage.

The authoritative result is
`.local/diagnostics/20261001T014634.632924Z/flash-result.json`; the same
directory retains the complete flash log. `hardware_boot_tested=false` in the
flash result is intentional: writing/readback does not test a boot.

## Boot and integration

The saved tasks completed successfully:

```sh
task device:status ROUTE=usb
task device:boot-cycles CYCLES=0
task device:exec ROUTE=usb -- /usr/sbin/iw reg get
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
```

USB and independent Wi-Fi SSH reached boot
`741d1c20-1ae2-4aec-85b4-b6b87f0dfcf4`, running image
`0.1.0-diagnostic.12` and kernel `6.18.54-gameshellneo12`. The provisioned
network worked without a credential or configuration change. `CYCLES=0`
captures the current boot only; it requests no physical power cycle.

All seven boot-inspected services were active with zero restarts. The board
reported four CPUs, approximately 998 MiB RAM, the display and both expected
input devices. There were no failed units or kernel taint. USB was configured
at high speed; battery monitoring was valid, reporting 100% and charging.
These are software readings, not a new battery-capacity measurement.

The pinned BCM43430/0 firmware loaded once with the expected identity. The
boot recorder found zero firmware-crash, SDIO-removal or runtime-PM-underflow
markers. The boot log retains the missing `rdinit` and optional board-specific
firmware/CLM/TXCAP-file fallback messages; the selected firmware loaded and
connected. Firmware regulatory behaviour remains unqualified.

All six integration groups passed: image identity, service state,
database/policy, journal ACLs, temporary loopback BPF enforcement and country
checks. Configured country remains NZ; the observed global domain was AU,
matching the owner's previously accepted access-point announcement. The
integration check used this observed value without changing radio policy.

The ready marker was 17.394 seconds after the kernel's monotonic origin.
`systemd-analyze` reported 2.489 seconds kernel plus 19.885 seconds userspace.
These are one diagnostic boot's software milestones, not button-to-display
timing, repeated performance results or evidence of the five-second goal.

## Read-only PM and peripheral baseline

- Normal sleep targets remain masked and all four systemd sleep permissions
  remain disabled. `pm_test=none`, `pm_async=1`, and the debug delay is five
  seconds. PM success and failure counters are zero: no stage was entered.
  SDIO power retention and keypad supply retention are present; both USB
  polling/diagnostic experiments remain off.
- The saved PM snapshot contains the new raw interrupt and CPU counters.
  This confirms collection on the board; it is not an IRQ-rate comparison or
  measurement of the radio's sleep interval.
- RSB was runtime-active, with usage count 1, control `auto`, a 1,000 ms
  autosuspend delay and 101 ms cumulative runtime-suspended time. A startup
  snapshot does not establish sustained idle behaviour or power savings.
- The keypad remained `1-1`, device number 2, input `event1`, with expected
  stable links. Its supply was enabled, persistence was 1, runtime control
  was `on`, and device/port quirk values were zero. No physical button or PM
  continuity test was performed in this slice.
- The `GameShellNeo` sound card exposed playback/capture PCMs, both closed.
  Speaker and headphone DAPM amplifiers were off, and the speaker-enable GPIO
  read back low. No playback or mixer change was performed.

Private evidence under `.local/diagnostics/`:

| Capture | Directory / file |
| --- | --- |
| USB status | `20261001T015028.330238Z/status.txt` |
| Current boot and independent Wi-Fi access | `20261001T015055.779807Z/741d1c20-1ae2-4aec-85b4-b6b87f0dfcf4.json` |
| PM baseline | `20261001T015110.397094Z/inspection.json` |
| Keypad baseline | `20261001T015110.341140Z/` |
| Audio baseline | `20261001T015110.351843Z/audio.json` |
| Integration | `20261001T015157.195868Z/integration.json` |

Host task summaries are `.local/neo65-usb-status.log`, `.local/neo65-boot.log`,
`.local/neo65-regulatory.log`, `.local/neo65-integration.log`,
`.local/neo65-pm.log`, `.local/neo65-keypad.log` and `.local/neo65-audio.log`.

## Remaining qualification

The later owner-ready freezer/devices, input and cable sequence is recorded
in report 85. Installation and baseline checks are complete; they do not
establish suspend/resume reliability or resolve NEO-55's intermittent Wi-Fi
recovery failure. Preserve diagnostic.11 recovery under
`.local/recovery/diagnostic11-before-wifi-pm-hardening/`:

```sh
task mac:stage-recovery NAME=diagnostic11-before-wifi-pm-hardening
```

Recovery selection does not write a card. Failed radio restoration still
requires a cold restart; automatic reset/reprobe recovery is separate work.
