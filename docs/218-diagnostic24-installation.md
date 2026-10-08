# Diagnostic.24 installation and awake prerequisites

8 October 2026; evidence timestamps are UTC. NEO-157 is in progress.
The Samsung DEV card has been written and its full 4 GiB readback verified.
Owner-confirmed boot and awake qualification remain pending. No PM qualification
or energy result is established by the card write.

## Warning and shutdown

[Report 217](217-wfi-s2idle-image-integration.md) records the WFI driver,
BOOTTIME battery contract, awake measurement guards and verified artifact.
NEO-156 transferred the archive after the owner confirmed home regular Wi-Fi.
The owner then confirmed readiness for the card swap.

The matching diagnostic.23 tools in `work/power-insertion-wake` reached kernel
`6.18.54-gameshellneo22` over USB (private status capture
`20261008T102334.226852Z`). `task device:audio-test ROUTE=usb` passed three
one-second level-5 warning cues and restored the same boot's mixer and amplifier
state. Audio run `db952e6ccb0e421ba48e3ecfaf5eb710` is retained in capture
`20261008T102347.045368Z`. Audibility was not separately confirmed for shutdown.

`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
The owner confirmed moving the Samsung DEV card into the Mac reader after
shutdown. Private logs in that worktree are `.local/neo157-before-shutdown.log`,
`.local/neo157-shutdown-warning.log` and `.local/neo157-shutdown.log`.

## Verified card write

From `work/cpi-wfi-integration`, `task mac:status` found one external physical
64 GB card with the existing GameShell boot/Linux partitions.
`task mac:inspect DISK=disk16` freshly recorded its 64,013,467,648-byte capacity,
USB reader path and existing boot-volume UUID. `task mac:preflight` passed the
target identity and both compressed/decompressed source checksums.

`task mac:flash DISK=disk16` verified the mount guard's veto, wrote the image,
read every image byte back and safely ejected the card.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.24-cpi31-11fb47777b62.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `11fb47777b6273667b4702845ffc3f2b4f223d1b63acfea82b86017cee4012c9` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash result SHA-256 | `a95a34da1886046d8cdab8dbfc6fc2e31f68d1bb31c7981cb8616a2478d6b4e9` |
| Hardware boot tested by flash helper | False |

Original evidence is `.local/diagnostics/20261008T102614.682089Z/` in this
worktree. Task logs are `.local/neo157-{mac-status,inspect,preflight,flash}.log`.
The owner has been prompted to reinsert the ejected card, reconnect USB and
confirm the login screen before awake checks.

## Remaining qualification

Use this worktree's diagnostic.24 tools after boot. Verify exact image identity,
both SSH routes, fresh schema-2 battery readings, the all-CPU WFI/timer inventory,
journal continuity, power-key ownership and awake RTC alarm restoration.
Fresh readiness is required before the staged debug and actual sleep tests in
report 217. NEO-96/100/101 remain open for matching-image hardware evidence;
an installed driver alone does not establish all-CPU s2idle participation,
timekeeping freeze, lower current or the standby target.
