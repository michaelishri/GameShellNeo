# Diagnostic.8 hardware validation

Date: **30 September 2026 NZDT**. Board: owner's **CPI v3.1**; Samsung
64 GB DEV card. Tracked as **NEO-42**, following
[diagnostic.8 preparation](59-diagnostic8-preparation.md).

Status: **flash, full readback and safe ejection passed**. First boot,
integration and driver PM tests remain pending. No diagnostic.8 suspend test
or actual sleep has been performed.

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

## Pending boot and PM qualification

The owner has been asked to reinstall the DEV card, connect USB and power on.
The next checks are exact image/kernel identity, integration, both SSH routes,
read-only PM/keypad inspection, one freezer debug cycle, one devices debug
cycle and four repeated devices cycles. The initial and repeated display
recovery need owner observation. One additional bounded keypad trace should
record regulator transitions, USB recovery and driver callback timing.

The new image must produce zero unsupported-ULPI warnings during the driver
tests. Keypad re-enumeration and dead original input handles remain open
findings; this image adds diagnosis, not a claimed continuity fix. Normal
sleep remains disabled. Later PM stages, physical wake, sleep energy and
subsecond resume are outside this qualification sequence.
