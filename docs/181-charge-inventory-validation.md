# Read-only charger and gauge inventory

6 October 2026. NEO-120, supporting NEO-117. Source checks and one awake
hardware inventory pass on diagnostic.20. Charging-through-sleep measurement
remains unqualified for the reasons in [report 180](180-sleep-charge-measurement-design.md).

## Saved workflow

```sh
task device:charge-inspect
```

Keep USB connected. The host verifies the locked Linux version and sends the
tracked standalone helper through the existing private SSH transport. It records
the helper and source-lock hashes beside the original JSON and takes the local
PM workflow lock. Errors preserve emitted partial evidence and cannot report
completion. No temporary helper is installed on the device.

The helper checks CPI3/AXP223 identity, installed image and kernel release,
then verifies regmap name, full address layout, readable/non-precious metadata,
volatile classification and normal cache mode. Only documented addresses
00, 01, 33, B8, B9, E0, E1 and E6 are read. Exact seven-byte `pread` operations
avoid buffered read-ahead; each returned address/value is checked. IRQ status,
undocumented E2/E3 and registers beyond the current map are excluded. This
layout is tied to the audited Linux 6.18.54 regmap implementation; an unexpected
layout, cache mode or kernel series rejects the operation before register reads.

Existing battery and input-supply sysfs fields are captured alongside the
registers. Clock brackets and before/after boot/PM counters reject detected
suspend or boot changes. These guards do not prove that a sub-bracket transition
with a pending PM counter update is impossible. The inventory is sequential,
not atomic, and cannot establish uninterrupted electrical conditions.

The task performs no charging, input-path, gauge, cache, alarm, display or sleep
control writes. Regmap itself can populate its software cache on reads. Thus
nonvolatile values are explicitly labeled `regmap-cache-possible`; calibration
status and capacity configuration are not claimed as uncached hardware reads.
`completed=true` means inventory collection completed, not that charging,
capacity calibration or battery health passed qualification.

## Hardware result

Boot `34483a13-9373-4ee3-8984-fd81a99bc5de`, image
`0.1.0-diagnostic.20`, kernel `6.18.54-gameshellneo19`:

| Observation | Result and limit |
| --- | --- |
| Regmap | `axp20x-rsb`, range 00–E6, cache-only/bypass both disabled |
| Charger control 33 | `c6`; cached enable set, other bits untouched |
| Gauge control B8 | `c0`; cached gauge/counting enable set, correction enable/status clear |
| Configured capacity E0/E1 | `00/00`; cached configured flag clear; no capacity value inferred |
| Gauge result B9 | `e4`; volatile valid-result flag and 100% |
| Low warning E6 | `a0`; cached thresholds 15% and 0%, not proof of OS alarm handling |
| Battery telemetry | Present, Good, Charging, 100%; instantaneous 1 mA and 4.1558 V |
| Existing charge configuration | Target 4.2 V, constant-current setting 1.2 A; recorded unchanged, not endorsed as pack-qualified |
| External inputs | USB and AC both present/online; USB limit readback 900 mA is not measured port current |
| PM/display | PM11/0, SDIO usage 2, brightness 1, backlight power 0 |

The unset cached capacity flag is a reason to investigate inherited gauge setup,
not permission to program the generic battery's advertised capacity. No gauge
calibration, charger policy or image change was made. A 100% gauge and tiny
instantaneous current at full charge cannot establish sleep charge acceptance.

The surrounding USB PM inspections both pass the existing health/source
validator, retain the same boot and PM11/0, with no failed units or kernel taint.
No screen test, reboot or sleep ran while the owner was away.

Private evidence beneath `.local/diagnostics/`:

| Capture | SHA-256 |
| --- | --- |
| Before `20261006T102647.615944Z/inspection.json` | `7f9146e2497f63c5da342536af16947bce1bf440350b4a318b9b1c956798a842` |
| Inventory `20261006T102705.810028Z/inventory.json` | `d6a8818fecbe121376c76d15976ae5858e74452baf88913eb5303fb14e7cadad` |
| After `20261006T102745.468835Z/inspection.json` | `8b44de359ea4f6403d00e1957208a407f32fb045575df2d4f55bbfbecda942dc` |

## Verification and remaining work

Nine focused regression tests cover bounded read offsets/allowlist, read-only
open mode, metadata rejection before register access, failed/short/wrong-address
reads, descriptor cleanup, invalid/unconfigured gauge interpretation, clock/PM
continuity, wrong image/board/kernel admission, partial failure output and
standalone remote-source execution. `task check` passes the runtime and 605-tool
test suites (one existing optional skip), compiled current-selector/Mac guard
checks, Bash syntax and ShellCheck. Logs are `.local/neo120-tests.log` and
`.local/neo120-check.log`.

NEO-120's read-only inventory is complete. NEO-117 retains a controlled partial
discharge, awake charging baseline and separately arranged attended comparison.
E2/E3 semantics, gauge calibration and driver volatility/coherent-read handling
need resolution before promising an accumulated-charge measurement. Neither
this inspection nor source research qualifies standby power savings.
