# Diagnostic.20 card installation and startup qualification

5 October 2026; capture timestamps are UTC. NEO-117.

Diagnostic.20 is installed and running on the owner's CPI v3.1. Full 4 GiB
readback matched the verified image, the owner confirmed the boot handoff, and
both SSH routes and all awake startup checks passed. The live MUSB, USB-supply
and AC-supply wake controls are all disabled as specified.
**No debug suspend or actual sleep test has run on this image.** Staying asleep
when USB is attached remains pending attended qualification.

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
and confirm the login screen, keeping the Mac awake on PXL10, and replied
"Done." The subsequent checks kept the display on and required no key or cable
action. The new boot ID is `86a43151-7d9b-44bd-83b3-cc1b9fcff215`.

## Installed identity and awake checks

The installed `/etc/gameshellneo/image.json` exactly matches the built artifact,
including all 278 recorded project input hashes. Its SHA-256 is
`2da06c8e32d6741708036682ac881ba89b599a49a9270fc0159209d99e301bf7`.
The image is `0.1.0-diagnostic.20`; its intentionally unchanged kernel is
`6.18.54-gameshellneo19`.

Saved commands, run from the candidate worktree:

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:exec ROUTE=usb -- cat /etc/gameshellneo/image.json
task device:check ROUTE=usb
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
task device:pm-inspect
task device:power-policy-inspect
# Repeat the two read-only status commands after the awake checks.
```

| Check | Private capture beneath this worktree's `.local/diagnostics/` | Result |
| --- | --- | --- |
| Initial USB / Wi-Fi status | `20261005T043706.316880Z` / `20261005T043706.324136Z` | Both routes work; configured high-speed USB; no failed units or kernel taint |
| Integration | `20261005T043750.179311Z` | All seven groups pass, including image, services, wake policy, journal access and country |
| Journal rotation | `20261005T044103.242005Z` | Journald instance, kernel history and displaced-journal evidence unchanged |
| Awake POWER ownership | `20261005T044128.065269Z` | Inhibitor and exclusive input ownership pass; no input events; logical release, descriptor close and handback verified |
| Awake RTC | `20261005T044145.919131Z` | One alarm event, flags `0xa0`, elapsed 10.964 seconds; alarm restored |
| PM inspection | `20261005T044223.683601Z` | Existing health validator passes; PM success/fail 0/0, all failure counters zero; Wi-Fi SDIO usage 2 |
| Effective POWER policy | `20261005T044245.802327Z` | No retained diagnostic owner or drop-in; diagnostic poweroff action and idle-ignore policy restored |
| Final USB / Wi-Fi status | `20261005T044312.704461Z` / `20261005T044312.761470Z` | Both routes still work, services remain active and no failed units or kernel taint |

The RTC run ID is `09147b367b3f47a7b0612f0f2bc7a2ae`; its original completed
record reports both `passed=true` and `restored=true`. The trailing restoration
record also succeeds. The RTC clock value and charging configuration were not
changed by these checks.

Live wake policy is `disabled` for the MUSB controller and both
`axp20x-usb` and `axp22x-ac` supply devices. Integration and PM inspection
independently checked these against the image inputs. Configured/global radio
country is NZ on this hotspot; phy domain remains 99 and firmware-country
qualification remains false. No historical AU override was applied.

The PM snapshot has `pm_test=none`, s2idle selected, all ordinary sleep targets
masked, normal dim brightness 1 and no checked kernel fault markers. The SDIO
consumer remains active, runtime forbidden, control `on`, usage 2. These awake
observations are not a completed PM qualification sequence.

Battery telemetry is valid at 100%, reporting Charging and approximately
4.176 V. This uncalibrated, full-battery observation does not prove current
delivery during sleep or resolve the existing battery-voltage investigation.
Local userspace readiness is 16.914 monotonic seconds and systemd completion is
22.335 seconds; neither measures physical power-on to interaction.

Original evidence SHA-256 values:

| File | SHA-256 |
| --- | --- |
| Integration `integration.json` | `74e37f1a19c4a7adb3fe0f93dd7c4360f49e17229c63e6e1316c10e24232e72d` |
| Journal `summary.json` | `070b90e35678952be806abf1887da4682d69257ad39c81887a0a1a471f94efae` |
| POWER `result.jsonl` | `36bc3b3b8f8b28bf8fa5d51836476f469fa20f3794d33c094f6650239a17b712` |
| RTC `result.jsonl` | `574ab438f9737b7aaa33f3432e7c321339657b6a9b583453a755740341d8f7b4` |
| PM `inspection.json` | `6399388fa8039b91f3c47982e8cba2c7de5da05d4d68d224163af0d16c9d05a2` |
| POWER policy `before.json` | `cc0289556556b9a3cd0963f8e1bfbe815c51e24f101736df6e2f7d4d3cd6a582` |

## Next checks

Obtain fresh readiness for freezer/driver and late/noirq debug checks, with a
long audible warning before every dark interval and review of each original
result before continuing. Then qualify an unchanged-cable RTC sleep/wake before
the independent USB-attachment baseline, awake rehearsal and single attended
attachment attempt. The old consumed diagnostic.19 baselines remain historical.
Collect the original result and requested display/cable observations before any
recovery action. No further screen or sleep test is currently running.

Card verification alone does not prove staying asleep during USB insertion,
charging through sleep, wake-button behavior, deep retention or energy savings.
NEO-117 remains in progress.
