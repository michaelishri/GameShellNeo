# Diagnostic.7 hardware validation

Date: **30 September 2026 NZDT**. Board: owner's **CPI v3.1**; Samsung
64 GB DEV card. Tracked as **NEO-37**, following
[staged PM preparation](54-staged-pm-diagnostic.md).

Status: **flash, full readback, first boot, hotspot association, integration,
both SSH routes, one freezer and five devices debug tests passed**. The owner
confirmed normal console/backlight return after the first driver test and
the four-cycle batch. Keypad re-enumeration and unsupported MUSB-register
warnings remain follow-ups. No actual sleep has been performed.

## Baseline and installation

The read-only pre-flash capture is
`.local/diagnostics/20260929T192415.073160Z/inspection.json`.
Diagnostic.6 remained on overnight boot
`6c38af94-5335-41a5-aa97-3d17a549be6d`, with USB configured and Wi-Fi
associated. All seven checked services were active with zero restarts;
there were no failed units, kernel taint or checked fault markers, and one
expected firmware load. Battery telemetry reported 100% while charging;
this does not establish gauge accuracy. The RSB autosuspend delay remained
1,000 ms, with only 155 ms of historical runtime-suspended time.

The owner shut down the board and confirmed moving the DEV card into the
Mac reader. Fresh inspection identified the external physical USB card as
64,013,467,648 bytes, with its existing `armbi_boot` volume. The Mac's staged
transfer manifest matched the local diagnostic.7 manifest exactly. The
saved workflow ran:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

`disk16` was freshly observed for this session; inspect again before future
card operations. Both compressed and decompressed image checksums passed.
The mount guard passed its actual mount-veto check. All 4,294,967,296 bytes
were written and read back with the expected SHA-256, then the card was
safely ejected.

| Artifact | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.7-cpi31-74c52a8f6fd0.img` |
| Expected kernel | `6.18.54-gameshellneo7` |
| Source and card readback SHA-256 | `74c52a8f6fd05abfb4e4ebd9c8261bd857a430892e235c2a98c3dc3fd30f99c8` |
| Private flash evidence | `.local/diagnostics/20260929T193938.643597Z/flash-result.json` and `flash.log` |

The original-card backup and diagnostic.6 recovery artifacts remain
available as documented in report 54. No charging policy was changed.

## First boot and restored remote access

The owner confirmed the login screen after returning to the office and
switching back to a mobile hotspot.

At 03:41 UTC on 30 September, the saved `mac:status` and
`device:pm-inspect` tasks were blocked by the agent session's local network
restrictions. Socket creation raised `PermissionError: [Errno 1] Operation
not permitted` before contacting the Mac. This is not evidence of a Mac,
hotspot, USB or GameShell failure. Private logs are
`.local/neo37-office-mac-status.log` and
`.local/neo37-office-pm-inspect.log`. Neither task changed the device.

The owner then changed the session permissions. With network access enabled,
both saved tasks succeeded on retry; no Mac SSH configuration change was
needed. USB inspection is saved at
`.local/diagnostics/20260930T034551.485346Z/inspection.json` and status at
`.local/diagnostics/20260930T034713.138112Z/status.txt`. These identify
diagnostic.7 / `6.18.54-gameshellneo7` on boot
`f3da7d36-2ffc-49ea-888e-f8a8d4ea2aea`, USB configured, all seven checked
services active without restarts, no failed units, zero kernel taint, one
expected radio firmware load and no PM-recorder fault markers. Battery
monitoring reports valid data and 100% while charging.

Local readiness was **16.598 seconds**, and `systemd-analyze` reported
**21.724 seconds**. Neither includes a measured power-on/bootloader interval;
this single observation does not establish a startup improvement.

Live controls expose `freeze mem`, select only `s2idle`, and retain
`pm_test=none`, `pm_async=1` and the five-second debug delay. Both USB
experiment parameters read `N`; the SDIO keep-power property is present.
Normal sleep targets are masked and `AllowSuspend=no` remains configured.

Wi-Fi was scanning. The `.env` candidate differs from the installed Wi-Fi
configuration, and its SSID was absent from four cached scan entries.
The Mac reported a 5 GHz connection but redacted the network name; this
does not prove the hotspot lacks a separate 2.4 GHz band. Owner confirmation
of the current `.env` hotspot credentials was requested before any change.
Private visibility captures are `20260930T034618.512321Z` (GameShell) and
`20260930T034618.503167Z` (Mac), under `.local/diagnostics/`.
The initial global regulatory domain was NZ; the radio had its own `99`
domain.

## Hotspot connection and integration

The owner confirmed that `.env` held the hotspot credentials. The first
saved `task device:wifi-config` attempt could not verify a connection and
restored the previous configuration, with cleanup verified. Its record is
`.local/diagnostics/20260930T034839.007737Z/wifi-change.json`.

After the owner enabled the hotspot's 2.4 GHz compatibility mode, the
saved visibility task found the matching SSID on 2,462 MHz at -58 dBm,
advertising WPA2-PSK/SAE. The Mac briefly timed out while networking changed,
then Mac SSH and USB forwarding returned. A second `device:wifi-config`
transaction passed association, independent Wi-Fi SSH to the same boot,
configuration commit, private `.env` address update and cleanup without a
reboot. Its record is
`.local/diagnostics/20260930T035152.015763Z/wifi-change.json`.

Post-association global regulation remained NZ (radio domain `99`). All six
integration groups passed using `task device:check ROUTE=usb ACTIVE_COUNTRY=NZ`:
identity, services, database/policy, journal ACL, isolated BPF enforcement
and country configuration. This does not qualify the firmware's country
mapping independently. The saved `device:boot-cycles CYCLES=0` task passed
all current-boot checks and both SSH routes; no additional physical power
cycle is claimed.

| Capture under `.local/diagnostics/` | Evidence |
| --- | --- |
| `20260930T035136.465457Z` | Hotspot visible after 2.4 GHz change |
| `20260930T035222.699450Z` | Connected PM inspection; all preflight conditions passed |
| `20260930T035222.707310Z` | Current-boot capture, both SSH routes |
| `20260930T035249.459832Z` | Six passing integration groups |

## Initial advanced RSB counters

The new kernel exposes the previously unavailable runtime-PM counters:

| Device | Control / runtime state | Usage / enabled state |
| --- | --- | --- |
| RSB `1f03400.rsb` | `auto` / active | 1 / enabled |
| SD-card host `1c0f000.mmc` | `auto` / active | 0 / enabled |
| Wi-Fi host `1c10000.mmc` | `on` / active | 2 / forbidden |
| Main pin controller `1c20800.pinctrl` | `auto` / unsupported | 3 / disabled |
| Panel `spi0.0` | `auto` / unsupported | 0 / disabled |

RSB had 88 ms of historical runtime-suspended time and 444,393 ms active,
with its original 1,000 ms delay. The Wi-Fi host has an enabled runtime-PM
dependency link to RSB. This corroborates the reference/dependency
constraint discussed in [report 53](53-rsb-runtime-pm-comparison.md).
It does not identify every held reference or
measure energy impact. Snapshot reads are sequential: linked RSB reads
show usage 2 before the final RSB read shows 1, and the SD-card host is
observed active during collection. These are not atomic idle measurements.
No runtime policy, link or reference ownership was changed.

## First freezer debug test

The saved command `task device:pm-test STAGE=freezer CYCLES=1` passed.
Device run ID: `2688d4c4734f4aaabd1f99e727a8a846`. Private host evidence:
`.local/diagnostics/20260930T035307.586618Z/cycle-1/`.

The bounded stage took **5.318 seconds**, including the deliberate five-second
debug pause and surrounding work. It froze/thawed userspace and freezable
tasks, preserved the test process's memory checksum and returned on the
same boot. The success counter increased from 0 to 1; all failure counters
remained zero. The journal contains exactly one expected debug-wait marker
and no recorder fault markers. The PM controls returned to `pm_test=none`
and `pm_async=1`; configuration, charger limits and display/input state
checks passed. Fresh independent USB and Wi-Fi SSH checks both passed.

The stage duration is not an actual sleep-resume latency measurement.

## First devices debug test

`task device:pm-test STAGE=devices CYCLES=1` passed. Device run ID:
`9e92b9ebacfa4287b815fc9d07f36179`. Private host evidence:
`.local/diagnostics/20260930T035523.418751Z/cycle-1/`.

The bounded stage took **9.506 seconds**, including the deliberate five-second
debug pause and preparation/callback work. PM success increased from 1 to 2;
all failure counters remained zero. The memory checksum, original PM controls,
display/input names, Wi-Fi configuration/power-save policy, CPU policy and
charger limits all passed restoration checks. USB and independent Wi-Fi SSH
returned on the same boot, without a radio firmware reload. The owner confirmed
that the dim login console returned normally.

Two behaviors require follow-up despite those passing checks:

- The internal USB keypad disconnected and re-enumerated as a new input
  instance. Its expected device name returned, but this does not qualify
  held-key state, application input handles or uninterrupted keypad identity.
  Investigate the OHCI/PHY power sequence and keypad recovery before normal
  sleep and latency qualification.
- MUSB printed two `sunxi-musb does not have ULPI bus control register`
  warnings. In the pinned Linux source, generic MUSB context save/restore
  unconditionally read/write `MUSB_ULPI_BUSCONTROL`
  (`drivers/usb/musb/musb_core.c`, `musb_save_context()` and
  `musb_restore_context()`). Sunxi's accessors explicitly warn and return
  zero/ignore the write for this unsupported register
  (`drivers/usb/musb/sunxi.c`). No kernel `WARNING:` backtrace, taint, PM
  failure or failed SSH recovery accompanied these messages. Investigate a
  capability-aware context path rather than concealing the warning.

The keypad uses the OHCI host path; the MUSB warnings concern the separate
USB gadget/OTG controller. Their presence in the same cycle does not establish
a causal relationship. The existing recorder rejects its specified fault
markers; it does not reject every `dev_warn()` message.

## Four repeated devices cycles

After the first automated pass and owner confirmation,
`task device:pm-test STAGE=devices CYCLES=4` completed all four cycles. The
host evidence root is `.local/diagnostics/20260930T035718.366943Z/`, with
one `cycle-N/` directory per run. The owner confirmed the final dim login
console and brightness looked normal.

| Repeat | Device run ID | Bounded stage, seconds | PM success counter |
| --- | --- | ---: | ---: |
| 1 | `d19ddfdb8b8341b59e1d8aaeff29b233` | 9.480886 | 3 |
| 2 | `92e7e18c077646aaae6079d3b7dd046e` | 9.467199 | 4 |
| 3 | `b2ebffb124624b2f8f9183703d6d7a21` | 9.585154 | 5 |
| 4 | `8ed4fe9a1aa3432ab4cd067d0da3886b` | 9.623574 | 6 |

All four passed fresh independent USB/Wi-Fi SSH to the original boot,
process-memory integrity, exact one-cycle statistics, recorded health and
configuration restoration checks. All failure counters stayed zero.
Each devices cycle produced one keypad disconnect/re-enumeration and two
unsupported-ULPI warnings; the behavior occurred in **all five** driver
cycles, not in the freezer-only cycle. There were no radio firmware reloads
or recorder fault markers. This is a small functional sample, not a
production-reliability claim.

Final read-only PM inspection is
`.local/diagnostics/20260930T040331.324606Z/inspection.json`; the saved
diagnostic archive is
`.local/diagnostics/20260930T040332.692798Z/device.tar.gz`.
The full PM preflight validator passed again. The board retained
`pm_test=none`, `pm_async=1`, normal sleep masks, all checked services active
without restarts, no failed units, zero taint and one expected firmware
identity. Battery telemetry reported 100% while charging. Charger readbacks
remained 1,200,000 µA current/max and 4,200,000 µV voltage target; no charging
change or battery calibration is implied. RSB historical suspended time
remained 88 ms across all six test results.

## Next qualification gates

NEO-37's staged qualification is complete. Before testing late/noirq or
actual s2idle, address the AXP USB polling worker's suspend quiescence and
rearming, and brcmfmac's bounded freeze/error propagation. Investigate keypad
re-enumeration and the separate unsupported MUSB-register accesses. Power-key
wake handling, deliberate radio power removal and deep/DRAM-retention support
still need their own implementation and owner-present qualification. These
items are recorded in `FOLLOW-UP.md`.

These bounded PM debug stages return before late/noirq/platform and actual
sleep. They cannot qualify energy savings, power-button wake, DRAM
retention, week-long standby or subsecond resume. Normal sleep remains
disabled. See report 54 for the saved commands, recovery and driver gates.
