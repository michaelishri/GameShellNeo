# Diagnostic.8 hardware validation

Date: **30 September 2026 NZDT**. Board: owner's **CPI v3.1**; Samsung
64 GB DEV card. Tracked as **NEO-42**, following
[diagnostic.8 preparation](59-diagnostic8-preparation.md).

Status: **flash, full readback, safe ejection, first boot, USB SSH and all six
integration checks passed**. Wi-Fi association and driver PM tests remain
pending. No diagnostic.8 suspend test or actual sleep has been performed.

## Card installation

The owner confirmed that the shut-down GameShell's DEV card was in the Mac
reader. Fresh inspection found one external physical USB card: 64,013,467,648
bytes, 512-byte sectors, the expected reader and an existing `armbi_boot`
volume. The current disk identifier was `disk16`; it was freshly checked for
this write and must be rechecked for any later operation.

The saved workflow was:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Preflight verified the compressed archive, complete decompressed image and
recorded card identity. The flash repeated those checks, unmounted the card
and verified the mount guard's actual rejection of a mount attempt. It wrote
all 4,294,967,296 image bytes, flushed them, read the entire written region
back with the expected SHA-256, and safely ejected the card.

| Item | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.8-cpi31-3df063ed9bee.img` |
| Expected kernel | `6.18.54-gameshellneo8` |
| Source and readback SHA-256 | `3df063ed9bee29ca8ec90af655b683aae3c9c7269234ba587955178eafa66b03` |
| Written and verified bytes | 4,294,967,296 |
| Mount veto | Passed |
| Safe ejection | Passed |

Private evidence is
`.local/diagnostics/20260930T053154.983156Z/{flash-result.json,flash.log}`.
The host command logs are `.local/neo42-mac-{status,inspect,preflight,flash}.log`.
Diagnostic.7's image and matching recovery checkpoint remain available, along
with the earlier recovery artifacts and original-card backup. The physical
original card was not used.

## First boot and integration

The owner reinstalled the card, connected USB and confirmed the normal login
screen. Read-only PM and keypad inspection succeeded over USB. The board runs
`0.1.0-diagnostic.8` / `6.18.54-gameshellneo8`, boot
`b749db5f-89ef-4208-9fc6-fe44bd38c873`. All seven inspected services were active
with zero restarts; there were no failed units, kernel taint or recorded PM
failures. The expected radio firmware loaded once. Battery monitoring was
valid and reported 100% while charging; this does not establish gauge accuracy.

`task device:check ROUTE=usb` passed all six groups: image identity, services,
database/policy, journal ACLs, isolated BPF enforcement and country. Configured
and global country were NZ; the radio reported its existing `99` domain.

Both USB polling experiments read `N`. PM controls remain `pm_test=none`,
`pm_async=1`, only `s2idle` available, and a five-second debug delay. The keypad
is still low-speed `4242:e131` at `/dev/input/event1`, with persistence enabled,
runtime PM forbidden, no advertised remote wake and an enabled `keypad-vbus`
supply. Dynamic debug and regulator tracing are now available. This is initial
enumeration, not evidence of continuity across a PM cycle.

Private initial evidence:

- PM: `.local/diagnostics/20260930T053529.168833Z/inspection.json`.
- Keypad: `.local/diagnostics/20260930T053529.151283Z/keypad.json`.
- Integration: `.local/diagnostics/20260930T053556.245250Z/integration.json`.

Wi-Fi remained in `SCANNING`; the configured SSID was absent from seven cached
entries. The Mac was connected on 5 GHz and redacted its network name. These
observations do not establish whether the regular access point also offers
2.4 GHz. Since the large transfer is complete, the owner was asked to enable
the previously configured 2.4 GHz hotspot and connect the Mac to it. No Wi-Fi
configuration or firmware was changed. Visibility evidence is under
`.local/diagnostics/20260930T053605.217738Z/` and
`.local/diagnostics/20260930T053605.218702Z/`.

## Pending PM qualification

After Wi-Fi association and independent SSH verification, run one freezer
debug cycle, one devices debug cycle and four repeated devices cycles. The
initial and repeated display
recovery need owner observation. One additional bounded keypad trace should
record regulator transitions, USB recovery and driver callback timing.

The new image must produce zero unsupported-ULPI warnings during the driver
tests. Keypad re-enumeration and dead original input handles remain open
findings; this image adds diagnosis, not a claimed continuity fix. Normal
sleep remains disabled. Later PM stages, physical wake, sleep energy and
subsecond resume are outside this qualification sequence.
