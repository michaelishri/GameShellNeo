# Diagnostic.11 installation and boot checks (NEO-52)

1 October 2026, Pacific/Auckland. Owner's CPI v3.1 and previously authorized
Samsung DEV card. This follows [image preparation](72-diagnostic11-preparation.md).

The owner placed the card in the Mac reader before going to bed. This slice
covers verified installation and subsequent boot/access checks. Owner-observed
PM stages, button input and cable cycles are deferred until the owner returns.
Normal sleep remains disabled; this is not suspend qualification.

Subsequent owner-assisted qualification, interrupted batches and follow-ups
are recorded in [report 74](74-diagnostic11-pm-validation.md).

## Installation

Fresh `task mac:status` and `task mac:inspect DISK=disk16` identified the sole
external physical card: 64,013,467,648 bytes, 512-byte sectors, the same reader
path and expected `armbi_boot` FAT16/Linux layout. A fresh target record was
saved. The disk number is evidence for this insertion, not a reusable target.

`task mac:preflight` verified the compressed and decompressed staged image
hashes and recorded target identity. The candidate is:

- Image: `GameShellNeo-0.1.0-diagnostic.11-cpi31-b833bedf0ed0.img`.
- Image bytes: `4294967296` (4 GiB).
- SHA-256: `b833bedf0ed068d519f808dfa7f8b4dc3e6585e9e5f143168e7aa260229cae9c`.
- Expected kernel: `6.18.54-gameshellneo11`.

The saved `task mac:flash DISK=disk16` verified the mount guard, wrote all
4 GiB and read back the entire written region. The readback SHA-256 matched
the candidate exactly, and safe ejection passed. The owner reinserted the card,
reconnected USB, powered on and confirmed the normal login screen.

Private host logs: `.local/neo52-mac-status.log`,
`.local/neo52-mac-inspect.log`, `.local/neo52-mac-preflight.log` and
`.local/neo52-mac-flash.log`.
The authoritative flash result is
`.local/diagnostics/20260930T115003.699230Z/flash-result.json`, with the full
progress log in the same directory.

## Boot and integration

The saved tasks completed successfully:

```sh
task device:status ROUTE=usb
task device:boot-cycles CYCLES=0
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
```

USB and independent Wi-Fi SSH reached boot
`3bf2069f-24a7-4e0b-b7d3-18d4048e3c7f`, running image
`0.1.0-diagnostic.11` and kernel `6.18.54-gameshellneo11`. The image's existing
private Wi-Fi provisioning worked; no credential or network change was needed.
`CYCLES=0` captures the current boot only and does not request a power cycle.

All seven boot-inspected services were active with zero restarts. No failed
units or kernel taint were recorded. Four CPUs, approximately 998 MiB RAM,
the display and both expected input devices were present. USB was configured
at high speed; battery monitoring was valid, reporting 100% and charging.
These are software battery readings, not a new capacity measurement.

The pinned radio firmware loaded once with the expected identity. There were
zero tracked firmware crashes, SDIO removals or runtime-PM usage underflows.
The boot log contained the previously documented missing `rdinit`, optional
board-specific firmware and CLM-file fallbacks; see [report 27](27-diagnostic-integration-refresh.md).

All six integration groups passed: image identity, service state,
database/policy, journal ACLs, temporary loopback BPF enforcement and country
checks. Provisioning remains NZ; the owner's previously accepted home access
point announces AU, and the observed global domain was AU. This does not
qualify the firmware's full regulatory behavior.

The ready marker was 16.586 seconds after the kernel's monotonic origin;
`systemd-analyze` reported 2.545 seconds kernel plus 19.469 seconds userspace.
These are one diagnostic boot's software milestones, not button-to-display
timing, repeated performance measurements or evidence of the five-second goal.

## Read-only PM and peripheral baseline

- Normal sleep targets remain masked and all four systemd sleep permissions
  remain disabled. `pm_test=none`, `pm_async=1` and the diagnostic delay is
  five seconds. Both `CONFIG_SUSPEND_FREEZER` and `CONFIG_FREEZER` are enabled.
  PM success and failure counters are zero: no stage was entered on this boot.
- RSB was runtime-active, with usage count 2, control `auto` and a 1,000 ms
  autosuspend delay. This observation alone does not establish supplier
  ordering or safe late/noirq access.
- The internal keypad was device `1-1`, device number 2, input `event1` with
  its expected stable links. Its supply was enabled, USB persistence was 1,
  runtime control was `on`, and both device and port quirk values were zero.
  No physical input or suspend continuity was tested in this slice.
- The `GameShellNeo` sound card exposed playback and capture PCMs, both
  closed. Speaker/headphone DAPM amplifiers were off and the speaker-enable
  GPIO read back low. No audio playback or mixer change was performed.

Private evidence under `.local/diagnostics/`:

| Capture | Directory / file |
| --- | --- |
| USB status | `20260930T115356.577356Z/status.txt` |
| Current boot and independent Wi-Fi access | `20260930T115413.454582Z/3bf2069f-24a7-4e0b-b7d3-18d4048e3c7f.json` |
| PM baseline | `20260930T115413.456712Z/inspection.json` |
| Keypad baseline | `20260930T115413.514632Z/` |
| Audio baseline | `20260930T115413.519542Z/audio.json` |
| Integration | `20260930T115440.468209Z/integration.json` |

## Remaining checks

Installation, boot/access checks and the read-only baseline are complete.
The owner can leave the GameShell USB-powered and the Mac awake on the same
Wi-Fi; no further physical action is required for this slice.

The worker fixes still need the owner-observed freezer/devices sequence and
cable/input qualification in report 72. Their source-level checks and a clean
boot do not establish reliable suspend/resume or real sleep power use.

Diagnostic.10 recovery is retained under
`.local/recovery/diagnostic10-before-notification-freeze/`; the saved selection
task is `task mac:stage-recovery NAME=diagnostic10-before-notification-freeze`.
