# Diagnostic.22 installation and ADC validation

7 October 2026; capture timestamps are UTC. NEO-132. Diagnostic.22 is installed; full card readback,
owner-confirmed login and awake startup/ADC checks pass. NEO-133 follows with
separate attended PM qualification.
[Report 193](193-diagnostic22-adc-integration.md) records the source-qualified
ADC correction, verified image and source-only Mac transfer.

## Shutdown and card write

The owner confirmed readiness for the DEV-card swap. USB status passed on
kernel `6.18.54-gameshellneo20`, boot
`50dc8224-95e2-4f92-b35e-e35ca5566340`.
`task device:audio-test ROUTE=usb` passed three one-second warning cues with
same-boot mixer/amplifier restoration. Audio run:
`a4f164ee9b3441098381b5a6063b2ffc`; private capture:
`.local/diagnostics/20261007T051839.194263Z/`. Result SHA-256:
`fa778d628b642b098adf2e3b2bfc24521378e2c3c0dffd01540b700fd5011607`.
`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
The owner then confirmed the Samsung DEV card was in the Mac reader.

The saved workflow runs from `.local/worktrees/power-insertion-wake`:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Fresh inspection found one external physical card, 64,013,467,648 bytes,
with its existing GameShell boot/Linux partitions. Its recorded volume UUID
and device identity passed preflight. Compressed/expanded image hashes passed.
The mount guard successfully vetoed an attempted mount before writing.
Private flash evidence is `.local/diagnostics/20261007T052040.740129Z/`.
The original task logs are `.local/neo132-*.log`.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.22-cpi31-08136efbd5f9.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `08136efbd5f939c88d1390240ecc00cd60f0a40ae7789b90cd6d7377f622fadf` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash result SHA-256 | `66b26f9c3709763dc323bc97d06b4bb7bf3d9ae5b5ac26da7eb8f39e5dc3b4ad` |
| Hardware boot tested by flash helper | False |

The owner reinstalled the ejected card, reconnected USB and confirmed the
normal login screen. New boot: `7884d229-2309-47df-9af0-b6fe500ad9ac`.

## Startup and awake checks

The installed image manifest exactly matches the verified build:
`0.1.0-diagnostic.22`, kernel `6.18.54-gameshellneo21`, all 293 recorded project
inputs. Its SHA-256 is
`03afef9f431e9f58afaa3d408db5d993a329379d28953c3afb5534dc6aba8c85`.
Both USB and Wi-Fi SSH work before and after the awake checks.

The home network advertises AU, previously accepted by the owner; the configured
country remains NZ. `task device:check ROUTE=usb ACTIVE_COUNTRY=AU` passes all
seven integration groups without changing network or regulatory settings. The
first direct `iw` query failed because the noninteractive user's PATH excludes
its directory; `/usr/sbin/iw reg get` succeeded. Both command logs are retained.

```sh
task device:status ROUTE=usb
task device:status ROUTE=wifi
task device:exec ROUTE=usb -- cat /etc/gameshellneo/image.json
task device:charge-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
task device:journal-rotation
task device:power-key-smoke
task device:rtc-smoke
task device:pm-inspect
task device:power-policy-inspect
# Repeat both route status commands after the awake checks.
```

| Check | Private capture beneath `.local/diagnostics/` | Result |
| --- | --- | --- |
| Initial route status | `20261007T052819.240470Z`, `20261007T052819.278858Z` | USB and Wi-Fi work |
| ADC/gauge inventory | `20261007T052838.473246Z` | Schema 4 and masked-helper profile pass |
| Integration | `20261007T052913.680940Z` | Seven groups pass with accepted AU expectation |
| Journal rotation | `20261007T052929.177152Z` | Policy and continuity pass; no restart or repair |
| Awake POWER ownership | `20261007T052944.499624Z` | Passed; ownership handed back |
| Awake RTC | `20261007T052953.479325Z` | Alarm delivery/restoration pass, 10.542 seconds |
| PM inspection | `20261007T053014.988568Z` | Existing image/health validator passes |
| Effective POWER policy | `20261007T053014.971810Z` | No retained owner or drop-in |
| Final route status | `20261007T053042.161136Z`, `20261007T053042.263040Z` | USB and Wi-Fi still work |

At this awake checkpoint PM success/fail is 0/0, every failure counter is zero,
kernel taint is zero and no units have failed. Brightness is 1 with backlight
power 0. MUSB and both supply wake controls remain disabled; normal sleep is
still masked. The diagnostic power-key action remains poweroff, with no
retained diagnostic suppression. PM inspection SHA-256:
`6bb35ee159c466c96f504163917098e1bc547b82d6539f4823f909e4842a9b9f`.

## Corrected ADC formula and preserved limits

The read-only inventory admits the exact diagnostic.22/kernel pair with
`adc_width_masked=true`, schema 4, and the volatile-B8 profile. Its raw voltage
bytes are `ec/03`, with unused low bits zero. Corrected and legacy formulas both
produce 4,156,900 µV; the separate sysfs sample agrees. The report preserves
both formulas and marks coherence and physical accuracy unqualified.

The battery reports 100%, Charging, instantaneous 2 mA and health Good. B8 reads
`c0` through volatile regmap access. Gauge/coulomb counting are enabled; capacity
calibration and calibration-in-progress are clear, and E0/E1 still describe no
configured capacity. No calibration was provoked.

REG33/34/B8/E0/E1/E6 are `c6/45/c0/00/00/a0`, matching the diagnostic.21
read-only capture `20261007T034242.541079Z`. Reported limits also match: 4.2 V
target, 1.2 A constant-current setting and 900 mA USB input limit. Nonvolatile
configuration reads can still be cached; agreement is not independent electrical
verification. Inventory SHA-256:
`17a7d164c5f408aebd52def94c85e6d3725eca4306ff3d1de74011f67abc286b`.

## Qualification boundary

The corrected helper is installed and the initial awake inventory passes. This
sample has no unused bits set, so it cannot distinguish the corrected formula
from the legacy formula or attribute the earlier 4.2559 V discrepancy to that
defect. Source tests provide the counterexample and exhaustive mask coverage;
this hardware check establishes compatible operation on the observed sample.

Charger/gauge controls are unchanged. Physical voltage accuracy, calibration,
usable capacity, direct charging during sleep and energy remain unresolved.
NEO-132 ends at the awake checkpoint. The owner separately confirmed readiness
for NEO-133's freezer/driver tests; their evidence is kept in the PM slice and
does not retroactively qualify this awake-only checkpoint as a sleep result.
