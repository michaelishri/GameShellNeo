# Diagnostic.25 card installation and awake prerequisites

9 October 2026; evidence timestamps are UTC. NEO-171, under NEO-108.
The Samsung DEV card has been flashed, its complete 4 GiB image read back and
verified, and the card safely ejected. Owner-confirmed boot and awake prerequisite
checks are pending. This report does not yet establish hardware qualification.

## Warning and shutdown

[Report 232](232-musb-restart-image-integration.md) records the reviewed MUSB
restart correction, verified image and successful transfer on owner-confirmed
regular Wi-Fi. The owner subsequently confirmed readiness for the card swap.

Matching diagnostic.24 tools in `work/cpi-wfi-integration` verified USB access to
kernel `6.18.54-gameshellneo23`, boot
`a73c7c3c-5ed4-473d-85c4-8d71f4a89bc2`, with configured high-speed USB and no failed
services (capture `20261009T052251.655243Z`). The software battery sample reported
99% and Charging; this does not establish calibrated battery capacity.

`task device:audio-test ROUTE=usb` completed three one-second level-5 speaker
warnings and restored the same boot's mixer controls and amplifier idle state.
Audio run `249282aadb954043bb8982b56e711c3b` is retained in capture
`20261009T052309.049417Z`. Audibility was not separately confirmed for shutdown.

One `task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
It was not retried. The owner confirmed moving the DEV card into the Mac after
the instruction to wait ten seconds after darkness and unplug USB.
Private logs in that worktree are
`.local/diagnostic25-{before-shutdown,shutdown-warning,shutdown}.log`.

## Fresh target identification and verified write

From `work/musb-restart-integration`, `task mac:status` found one external physical
64 GB card, `disk16`, with the existing GameShell FAT16 boot/Linux partitions.
`task mac:inspect DISK=disk16` recorded its 64,013,467,648-byte capacity, 512-byte
sector size, USB reader path and existing boot-volume UUID
`DBBBD048-2FA1-3768-816E-462B39615A0E`. The owner had freshly confirmed that the
DEV card was in the reader; disk numbering was not inferred from the previous
flash. `task mac:preflight` passed the target identity and both compressed and
complete decompressed source checksums without writing the card.

`task mac:flash DISK=disk16` verified the mount guard's veto, unmounted the card,
wrote the image, read every image byte back and safely ejected the card. The
owner was instructed to leave the reader's USB and power connections untouched
through completion. No disconnect or write/readback error was reported.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.25-cpi31-c88d158d446b.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `c88d158d446b6ed14617b815ec17bfd2b3e90fee858ddd30e008ed74640aeb77` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash-result SHA-256 | `903450e19d9449b34a2eb889be8ef6190bab63a7e8a00867d4c6d2bf7de9ceba` |
| Hardware boot tested by flash helper | False |

Original evidence is `.local/diagnostics/20261009T052623.051576Z/` in this
worktree, including `flash.log` and `flash-result.json`. Task logs are
`.local/diagnostic25-mac-status.log` and
`.local/diagnostic25-card-{inspect,preflight,flash}.log`. The original diagnostic.24
recovery image, compressed archive, metadata and matching tools remain retained
in `work/cpi-wfi-integration` as documented in report 232.

## Pending boot and awake qualification

The owner has been asked to reinsert the DEV card, reconnect USB to the Mac and
confirm the normal login screen. Then use this worktree's diagnostic.25 tools to
verify the exact image/manifest, USB and Wi-Fi routes, service health, battery
schema and freshness, all-CPU WFI/timer inventory, journal continuity, power-key
ownership and awake RTC alarm restoration.

Sleep qualification is separate: obtain fresh readiness before screen blanking
or actual suspend, retain the long audible warnings, review each result and stop
on failure. Old source-bound qualification receipts cannot authorize new-image
sleep tests. Full card readback alone does not establish a successful boot,
reliable suspend/resume or reduced power consumption.
