# Stay asleep when USB power is attached

5 October 2026. NEO-117; prospective diagnostic.20 candidate.

The owner selected **stay asleep and charge** when USB is connected during
sleep. [Report 165](165-diagnostic19-usb-attachment-early-wake.md) preserves the
diagnostic.19 attempt that woke before the RTC. That result is still failed;
this candidate has not been installed or tested on the board.

## Policy and implementation

Three independent interfaces can select cable-related wake on this board:

| Interface | Diagnostic.19 observed | Diagnostic.20 startup policy |
| --- | --- | --- |
| MUSB controller `device/power/wakeup` | disabled | disabled |
| `axp20x-usb` supply `power/wakeup` | enabled | disabled |
| `axp22x-ac` supply `power/wakeup` | enabled | disabled |

The AC and USB drivers already use their supply's `device_may_wakeup()` value
to decide whether to arm insertion wake. The standard driver controls therefore
implement the requested policy without another kernel patch. Charging remains
under the PMIC's existing configuration; this change does not write charger
registers or change current/voltage limits. POWER, RTC and the shared PMIC parent
wake settings are not modified. Physical wake-button qualification remains open.

The existing `gameshellneo-usb` startup service now validates all three controls,
writes `disabled`, and checks each readback before binding the gadget or returning
from an already-bound start. Supply registration creates its wake control after
`device_add()`, so a bare udev add rule would have an ordering gap. Missing or
unexpected controls fail startup before any policy write; the existing service's
bounded startup and restart policy handles registration readiness. A failed
write/readback also fails startup. There is no new resident process, cable-event
handler or polling loop. A driver unbind/rebind after startup is not qualified;
diagnostic admission rejects any resulting enabled or missing wake control.

Installed-image integration and PM snapshots now verify both supply controls.
Each debug prerequisite snapshot and current admission must retain the same
disabled settings. The image explicitly declares
`power_supply_system_wakeup=false` alongside `usb_system_wakeup=false`.
Missing, malformed, enabled or provenance-mismatched settings cannot pass.

The image version advances to `0.1.0-diagnostic.20`. The kernel remains
`6.18.54-gameshellneo19`: source, configuration, DTB and modules are unchanged.
The existing completed-kernel manifest verifies the reused artifacts; it is not
regenerated to authorize different inputs. Image and kernel suffixes therefore
intentionally differ.

## Masked insertion evidence

Disabling supply wake masks insertion interrupts during suspend as well as
removal interrupts. AXP223's regmap `init_ack_masked` behavior can acknowledge a
pending masked event during another interrupt-mask synchronization, before the
event's nested handler runs. Exact handler counts cannot prove the electrical
edge or be required as though all events remain deliverable.

The new image selects the prospective `masked-cable-v2` policy. Only matching
CPI v3.1 image records with both supply wake controls disabled before and after
the test may use it. For the requested direction, each AC/VBUS handler count
may increase by zero or one. Opposite events, extra dispatches and regressing
counts still fail. Awake rehearsals still require no cable change.

The original `exact-v1` and diagnostic.19 `masked-removal-v1` behavior remains
unchanged, including exact insertion counts for diagnostic.19. No stored result
is rewritten. RTC delivery at return, elapsed-time checks, real endpoint state,
original-result hashes, source/boot lineage, independent route recovery and the
separate physical observation remain required. An early cable wake still fails.

## Reproducible verification

The implementation is isolated in `.local/worktrees/power-insertion-wake` on
branch `work/power-insertion-wake`; the installed diagnostic.19 and its saved
evidence are unchanged.

```sh
task check
task lint
python3 -m unittest discover -s tools/tests -p test_usb_wake_policy.py -v
task test:power-irq-mask
task check:kernel
```

- Runtime suite: 13 tests pass; tooling suite: 576 tests, two existing skips.
  The compiled current-selector and Mac mount-guard checks pass. The first
  combined check found one ShellCheck quoting warning in the new array; it was
  corrected, then shell lint and all seven actual-startup-script tests passed.
- Startup fixtures execute the real shell policy against isolated controls:
  repeated starts, the supply-registration gap and retry, invalid settings,
  ineffective setters/readback failures, and untouched POWER policy.
- PM and cable regressions reject changed/missing supply settings, mismatched
  images, wrong endpoints, missing RTC delivery and invalid interrupt deltas.
- Actual Linux 6.18.54 regmap mask/synchronization functions pass ten scenarios
  natively and under ARM32 emulation. Insertion cases cover both supply resume
  orders with and without an intervening mask synchronization. Two deliberately
  broken implementations fail their assertions. Registers and nested interrupt
  delivery are simulated; this is source evidence, not electrical measurement.
- Reused kernel verification passes all 164 configuration assertions and all
  15 completed-artifact hashes, including the unchanged patch/config identity.

Private logs are `.local/neo117-check.log`, `.local/neo117-lint.log`,
`.local/neo117-startup-recheck.log`, and
`.local/build/power-irq-mask-tests/evidence.json` in that worktree.

## Remaining board qualification

After offline image verification, a separately arranged installation must check
all three live wake settings, both SSH routes, charging telemetry, journal
continuity and the existing awake POWER/RTC ownership tests. Establish a fresh
same-image, same-source debug baseline and awake rehearsal before any actual
sleep. Keep the long speaker warnings and obtain fresh observer readiness.

First qualify unchanged-cable RTC sleep. Then separately test attachment during
sleep: start on battery, attach USB once after the requested dark wait, remain
asleep until the RTC, and recover correct external-power/USB state and both SSH
routes. Repeat the removal comparison under the new policy. Qualification must
distinguish external power being present from a battery actually accepting
charge; a full battery is not evidence of charging throughout sleep. Measured
charge accumulation, energy, deeper retention and production POWER wake remain
separate work.

Diagnostic.19 remains connected with its failed run and retained diagnostic
power-key suppression intact. No live wake policy was changed and no additional
sleep, reboot, sound or cable test was submitted while preparing this candidate.
NEO-117 remains open pending hardware qualification; ordinary sleep stays disabled.
