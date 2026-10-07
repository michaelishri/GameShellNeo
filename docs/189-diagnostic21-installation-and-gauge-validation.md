# Diagnostic.21 installation and fresh gauge-status validation

7 October 2026; capture timestamps are UTC. NEO-126. Diagnostic.21 is installed
and its startup/read-only gauge checks pass. B8 is volatile on the live AXP223
regmap and reads successfully. No debug suspend or actual sleep test has run on
this new image; full PM qualification remains separate.

[Report 187](187-diagnostic21-gauge-integration.md) records the built identity,
source tests, offline verification, checked transfer and recovery checkpoint.
This slice verifies the AXP223 B8 read contract without writing charger/gauge
settings or forcing calibration. Electrical voltage accuracy, usable capacity
and direct charge attribution during sleep remain NEO-10/NEO-117 work.

## Shutdown and card write

The owner confirmed readiness for the card swap. USB status passed on the old
diagnostic.20 boot `d49e0999-5edd-4fe1-9c6e-1c8e17cadfa9`.
`task device:audio-test ROUTE=usb` passed three one-second warning cues with
same-boot mixer/amplifier restoration (run
`5eadf5cf43934fa78f65d33e8f8cabac`, private capture
`.local/diagnostics/20261007T023300.632069Z/`).
`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
The owner then confirmed the Samsung DEV card was in the Mac reader.

The saved workflow ran from `.local/worktrees/power-insertion-wake`:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Fresh inspection found one external physical card, 64,013,467,648 bytes,
with its existing GameShell boot/Linux partitions. The recorded boot volume
identity was rechecked before writing. Compressed/expanded source hashes
passed, and the mount guard prevented automatic mounting during the operation.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.21-cpi31-766436e6428c.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `766436e6428c86dcf31003d8f680e6992a6afd217752caa7aca056ff75e3a7a0` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Private flash capture | `.local/diagnostics/20261007T023455.152979Z/` |
| Hardware boot tested by flash helper | False |

The owner reinserted the card, reconnected USB and confirmed the normal login
screen. New boot ID: `50dc8224-95e2-4f92-b35e-e35ca5566340`.

## Startup checks

The installed image manifest exactly matches the verified build: version
`0.1.0-diagnostic.21`, kernel `6.18.54-gameshellneo20`, all 290 recorded project
inputs. Its SHA-256 is
`599064cba13248e16b68125ebb106454efa2515068d0a277e587f89dc18d0d11`.

Both routes passed before and after the awake checks. The first integration
run retained a country mismatch: configured NZ, observed global AU. This is the
home router's previously owner-accepted announcement. A separate run with
`ACTIVE_COUNTRY=AU` passed all seven integration groups; no router, firmware
country, or device country setting was changed to make that check pass.

Saved commands after the owner-confirmed boot:

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:exec ROUTE=usb -- cat /etc/gameshellneo/image.json
task device:check ROUTE=usb
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
task device:pm-inspect
task device:power-policy-inspect
task device:charge-inspect
# Repeat both route status commands after the awake checks.
```

| Check | Private capture beneath `.local/diagnostics/` | Result |
| --- | --- | --- |
| Initial USB / Wi-Fi | `20261007T023816.411659Z` / `20261007T023816.418743Z` | Both routes work |
| Original integration | `20261007T023831.143906Z` | Six groups pass; retained NZ/AU mismatch |
| Accepted AU expectation | `20261007T023851.081124Z` | All seven groups pass |
| Journal rotation | `20261007T023902.337293Z` | Policy/continuity pass, no journal restart or repair |
| Awake POWER ownership | `20261007T023907.202796Z` | Pass; input/inhibitor ownership restored |
| Awake RTC | `20261007T023911.135056Z` | Alarm delivery and restoration pass, 10.719 seconds |
| PM inspection | `20261007T023924.852555Z` | Saved snapshot passes the existing image/health validator |
| Effective POWER policy | `20261007T023928.365792Z` | No retained diagnostic owner/drop-in |
| Gauge inventory | `20261007T023930.963494Z` | Schema 3, volatile-B8 profile passes |
| Final USB / Wi-Fi | `20261007T023945.558578Z` / `20261007T023945.582467Z` | Both routes remain healthy |

PM success/fail remains 0/0, with every failure counter zero, no failed units
and kernel taint zero. SDIO usage remains 2. The MUSB and both supply wake
controls are disabled. Brightness is 1 and backlight power is 0; ordinary sleep
is still masked. The diagnostic power-button action remains poweroff, with no
retained test suppression. These awake checks do not qualify suspend/resume.

## Live B8 and unchanged reported settings

The inventory admits only the matching image/kernel and actual cache metadata.
It reports `cache_profile=axp223-volatile-b8`, with B8 access `b8: y y y n`
(readable, writable, volatile, nonprecious). Cache-only and cache-bypass are both
`N`. The bounded register read returns `c0` with source
`volatile-regmap-read`. Gauge/coulomb counting are enabled; capacity calibration
and the calibration-in-progress bit are clear. Calibration was not triggered.

REG33/34, B8, E0/E1 and E6 match the retained diagnostic.20 inventory:
`c6`, `45`, `c0`, `00/00`, `a0`. Reported limits also match: 4.2 V target,
1.2 A constant-current setting and 900 mA USB input limit. Nonvolatile controls,
including E0/E1, remain potentially cached. Their unchanged values are not
independent bus readback or evidence of calibrated capacity.

The sampled gauge result is 99%, with Charging and instantaneous 147 mA.
Raw voltage bytes `f1/0d` have no unused low-register bits set. Both formula
variants and the separate sysfs read yield 4.2559 V, above the unchanged
4.2 V target. This repeats the earlier discrepancy; the B8 correction has not
resolved it. The observations do not establish ADC coherence, physical terminal
voltage or a compensation formula. No longer charging/discharge experiment,
charger-setting change, cache bypass or raw-bus write occurred in this slice.

This qualifies the deployed fresh-read path and observed settings. It does not
demonstrate a real calibration-status transition, battery accuracy, usable
capacity or charging during sleep. Fresh attended debug/sleep regressions and
the NEO-10/NEO-117 measurement work remain outstanding. USB remains connected,
the device is awake and no test is running.

| Evidence file | SHA-256 |
| --- | --- |
| Flash `flash-result.json` | `0bb0ae6244b62325fc078f1139dbe5abc08ed230188ec91717043a4f6b989885` |
| Gauge `inventory.json` | `885ebf75c0d1c36bd631ddb3ae9e74f4605ebb43d755ac62ef08eca1aa2f369a` |
| PM `inspection.json` | `90409d7e64148d72d9da95db4005ad8bef4fd5840043ac89f69edb7e89f1b438` |
