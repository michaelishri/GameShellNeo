# Diagnostic.18 installation and startup (NEO-95)

4 October 2026, Pacific/Auckland. The exact diagnostic.18 artifact from
[report 128](128-musb-system-sleep-candidate.md) has been written to the Samsung
DEV card, passed full 4 GiB readback and been safely ejected. An earlier attempt
was interrupted when the dongle's charging cable was disconnected. The owner
confirmed the login screen; both SSH routes, startup integration, journal
rotation and awake key/RTC checks pass on the new boot. Attended debug stages
and USB/sleep recovery remain unqualified.

## Source image and shutdown

The owner confirmed regular Wi-Fi and later availability for the card swap.
The already staged image passed compressed and decompressed checksum checks:

| Property | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.18-cpi31-21f78ee232de.img` |
| Raw bytes | 4,294,967,296 |
| Raw SHA-256 | `21f78ee232de9692ac429f06994586fff77aa49d52011fd0350c8e5c85320f87` |
| Compressed bytes | 269,743,893 |
| Compressed SHA-256 | `7a304c154280a3c4f908823528325117796d7e9b0d9e7fbba63511820884abac` |

The running board was still `6.18.54-gameshellneo17`, boot
`4ffd75dc-2dae-4164-8bd2-90ad08ed1885`, with `pm_test=none` and the failed
sleep experiment's retained short-power-press suppression. After the owner
offered to move the card, `task device:exec ROUTE=wifi -- sudo -n systemctl
--no-block poweroff` returned successfully. The owner then confirmed the
Samsung DEV card was in the Mac reader. No further PM experiment was submitted
on the old boot.

## Interrupted first attempt

Fresh `mac:status`, `mac:inspect DISK=disk16` and `mac:preflight` identified
the external physical 64,013,467,648-byte card. The saved `mac:flash` workflow
verified the source/target, started its mount guard, unmounted the card and
observed a rejected mount request before writing all 4 GiB.

Readback stopped with `OSError: [Errno 6] Device not configured`, after the
last progress line at 812 MiB. This attempt **failed verification** and did
not eject the card or report success. Its private evidence is
`.local/diagnostics/20261003T161127.364855Z/flash.log`.

A bounded Mac storage log captured in that directory records
`AppleUSBHostPort::cableChangeOccurred: powering off` at 05:12:48 NZDT,
followed by hub/card-reader termination and the whole disk disappearing.
The card returned and its FAT volume mounted at about 05:12:52. The owner
confirmed disconnecting the charging cable that ran through the dongle.
That physical change agrees with the host-side port interruption; this was
not evidence of a GameShell kernel regression.

After a fresh card inspection, `task mac:compare DISK=disk16` completed a
read-only comparison of all 4 GiB. It found 330 differing 512-byte sectors,
with the first/last differing sector boundaries spanning offsets
16,779,264 through 24,973,823 inclusive, entirely within the FAT boot partition.
The remaining compared bytes matched. The limited changes are consistent with
the observed macOS remount after the failed writer released its guard; their
individual file ownership was not decoded. This comparison did not pass and
did not establish an intact installation. Evidence is
`.local/diagnostics/20261003T161339.371133Z/card-compare.json`.

## Guarded retry

With the card still identified and the owner instructed to keep the charging
cable and dongle connected, the unchanged `task mac:flash DISK=disk16` workflow
started again. No permanent host mount or power settings were changed.

The retry completed all 4,294,967,296 bytes of writing and readback. The raw
SHA-256 exactly matches the image identity above. The result records
`readback: passed`, `mount_guard_verified: true`, `ejected: true` and
`hardware_boot_tested: false`. The owner was then asked to reinsert the card,
reconnect USB and confirm the login screen.

Evidence is `.local/diagnostics/20261003T161548.495987Z/flash.log` and
`flash-result.json`; the latter's SHA-256 is
`ff89f6671e27efca7eec261402232f147e72b8e8791ae8afca62ec44a6011866`.
The original interrupted attempt remains recorded as failed. No boot or
USB/sleep qualification is claimed by the successful card readback.

## New-boot startup and awake checks

The owner confirmed the login console. USB and independent Wi-Fi SSH both
reach `6.18.54-gameshellneo18`, boot
`e419f334-0a16-4b04-96d2-d97a2e4d5d0b`. The installed image manifest exactly
matches `.local/artifacts/image-manifest.json`, including the kernel and all
25 patches. The USB gadget reports configured/high-speed, and its system-wake
policy reads `disabled` as required by diagnostic.18.

All six integration groups pass: image identity, services, database/policy,
journal ACL, BPF enforcement and country policy. The six inspected services
are active with zero restarts; no unit is failed and kernel taint is zero.
Provisioning remains NZ, with the previously accepted AP-announced AU global
country and phy label 99. Firmware-country readback remains unqualified.

The initial SDIO runtime count is **2**, active and forbidden. PM success and
failure counts are both zero. Normal sleep targets remain masked, `pm_test`
is none, async is 1 and the debug delay is five seconds. The RSB supplier is
active with usage 1, control auto and a 1000 ms autosuspend delay. The CPU-idle
driver is still `none`; this image does not contain the later WFI candidate.
Backlight is at level 1 with power 0. Both audio amplifiers are off; no tone
was requested during startup. Battery telemetry reports 100%, Charging and
4.1635 V; no charging policy was changed.

The saved kernel startup log contains the established BCM43430/0 firmware
7.13.53.9 fallback messages, without a firmware crash or runtime-reference
underflow. Ordinary text-log rotation passes continuity checks without a
journald restart, kernel-history loss or changes to displaced journal files.

Awake power-key acquisition, released-state verification and descriptor
handback pass, with no key events. The ten-second RTC check delivers one
notification with flags `0xa0` after **10.034 seconds** and restores the
disabled alarm. Its run ID is `c0736c186b9f4a2186da2f7bd47ef7d7`. These checks
establish awake ownership/delivery only, not waking from sleep.

| Evidence | Capture under `.local/diagnostics/` |
| --- | --- |
| Startup status | `20261003T162033.435268Z` |
| Initial PM snapshot | `20261003T162102.467593Z` |
| Journal inspection | `20261003T162137.257597Z` |
| Idle audio inspection | `20261003T162151.167002Z` |
| Integration | `20261003T162205.425506Z` |
| Ordinary journal rotation | `20261003T162256.129445Z` |
| Awake power-key ownership | `20261003T162322.966647Z` |
| Awake RTC delivery/restoration | `20261003T162341.649579Z` |

The commands are `device:status ROUTE=usb`, `device:pm-inspect`,
`device:journal-inspect`, `device:audio-inspect`,
`device:check ROUTE=usb ACTIVE_COUNTRY=AU`, `device:journal-rotation`,
`device:power-key-smoke` and `device:rtc-smoke`. Explicit read-only
`device:exec` calls captured both route identities, the installed manifest,
USB wake policy, regulatory state, initial SDIO ownership and kernel journal.
Host transcripts are `.local/neo95-diag18-*.log` and
`.local/neo95-diag18-installed-image.json`. An initial concurrent audio read
was refused by the host's shared diagnostic lock before device access; its
later serialized run is the successful capture above.

Startup reports local userspace ready at monotonic **16.949 seconds** and
systemd startup completion at **22.040 seconds**. These are this boot's software
milestones, not measured power-button-to-UI latency or the under-five-second
product target. No boot-performance improvement is claimed here.

## Reproduction and remaining work

The routine commands remain the documented Taskfile workflows:

```sh
task mac:status
task mac:inspect DISK=diskN
task mac:preflight
task mac:flash DISK=diskN
# After a failed attempt, inspect afresh before a read-only diagnosis:
task mac:inspect DISK=diskN
task mac:compare DISK=diskN
```

`disk16` describes this session only. Select the actual newly inspected DEV
card each time. Keep the reader's USB and charging connections intact through
write, full readback and ejection; changing dongle power can interrupt storage.

The installed image, both SSH routes, USB wake policy, services, journal
rotation, idle audio, awake key ownership and RTC delivery are now checked.
Requalify the debug stages with fresh observation before a separately attended
real-sleep attempt. The old boot's consumed prerequisites cannot authorize a
new sleep test. The separate source candidates from reports 132–139 are not
part of this image; diagnostic.18 contains patches 0001–0025 only.
