# Diagnostic.20 card installation and startup qualification

5 October 2026; capture timestamps are UTC. NEO-117.

Diagnostic.20 has been written to the owner's Samsung DEV card. Full 4 GiB
readback matched the verified image, and the Mac safely ejected the card.
**First boot and live wake-policy checks are pending the owner's confirmation.**
No debug suspend or actual sleep test has run on this image.

[Report 166](166-stay-asleep-usb-charging-policy.md) records the stay-asleep
charging policy, source tests, offline image verification, Mac transfer and
owner-requested shutdown of diagnostic.19. The old early-wake failure remains
preserved; this card write does not qualify the new policy on hardware.

## Confirmed card and verified flash

The owner confirmed switching the Mac back to PXL10, requested shutdown, then
confirmed the Samsung DEV card was in the Mac reader. Three long speaker cues
and audio restoration passed on the previous boot before the remote poweroff
request returned success. The retained diagnostic POWER suppression was not
manually removed.

From `.local/worktrees/power-insertion-wake`, the saved commands were:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Fresh inspection found one external physical USB card, 64,013,467,648 bytes,
with its existing GameShell boot/Linux partitions. The current boot volume UUID
was recorded and rechecked before writing. The source's compressed and
decompressed checksums passed, and the mount guard blocked automatic mounting
while the flash and readback ran. No additional image upload was needed on the
hotspot.

| Evidence | Value |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.20-cpi31-0f8763c74426.img` |
| Written/readback bytes | 4,294,967,296 |
| Image/readback SHA-256 | `0f8763c744265e52b935abc0df8eb34cf0fc05ebd5492b15437211a4f773e52a` |
| Flash capture beneath this worktree | `.local/diagnostics/20261005T042750.196834Z/` |
| Flash-result SHA-256 | `6006b033b8797808e76b6bb40d35e0d7283f5ade4ced03ca779b6204c4befdd2` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Hardware boot tested by flash helper | False |

The owner was asked to reinsert the card, reconnect USB, let the GameShell boot
and confirm the login screen, keeping the Mac awake on PXL10. Until that reply,
there is no claimed new boot ID, battery reading, live wake-policy result or
network recovery result.

## Next checks

After boot confirmation, verify the installed image identity, disabled MUSB and
both supply wake controls, independent USB/Wi-Fi access, journal continuity and
awake POWER/RTC ownership. The retained guard from the old image must not be
assumed to describe the new boot. Fresh readiness and a same-image/source debug
baseline are required before any subsequent screen or sleep test.

Card verification alone does not prove staying asleep during USB insertion,
charging through sleep, wake-button behavior, deep retention or energy savings.
NEO-117 remains in progress.
