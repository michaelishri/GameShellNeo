# Diagnostic.20: USB-removal preparation

5 October 2026; capture timestamps are UTC. NEO-117 and NEO-110.

The owner requested the next slice after the passing attachment case in
[report 171](171-diagnostic20-usb-attachment-sleep-validation.md). The next
qualification is removal during sleep with diagnostic.20's disabled supply
wake policies. Initial read-only admission passes; no new debug or sleep cycle
has been submitted at this checkpoint. USB remains connected.

## Initial state

| Item | Evidence |
| --- | --- |
| Host source checkpoint | `9864f47`, `work/power-insertion-wake` |
| Image / kernel | `0.1.0-diagnostic.20` / `6.18.54-gameshellneo19` |
| Boot | `86a43151-7d9b-44bd-83b3-cc1b9fcff215` |
| PM success/fail | 16/0; every failure counter zero |
| Wake policy | MUSB, `axp20x-usb`, `axp22x-ac`: disabled |
| Display | Brightness 1, backlight power 0 |
| Effective POWER policy | Diagnostic poweroff and idle-ignore; no retained owner/drop-in |

Saved commands:

```sh
task device:pm-inspect
task device:status ROUTE=wifi
task device:power-policy-inspect
```

All private captures are beneath this worktree's `.local/diagnostics/`:

- USB PM inspection `20261005T060028.793213Z/inspection.json` passes the existing
  health/source validator, SHA-256
  `1cf2e6daa777e197f33d6136da37823dbaeffc7a609561b76af02605976b01f7`.
- Independent Wi-Fi status `20261005T060030.558052Z/status.txt` succeeds with
  the expected kernel, configured high-speed USB, active services, no failed
  units and kernel taint zero.
- Effective policy `20261005T060057.322404Z/before.json` shows no diagnostic
  owner/drop-in; SHA-256
  `cc0289556556b9a3cd0963f8e1bfbe815c51e24f101736df6e2f7d4d3cd6a582`.

Battery telemetry is valid at 99%/Charging. The 4.2559 V reading repeats the
existing uncalibrated charging-voltage observation under NEO-10; no charging
setting was changed. This is not evidence of charge acceptance during sleep.

## Next attended steps

Fresh readiness has been requested for one freezer, one driver and five
late/noirq debug cycles, with USB left connected and all controls untouched.
Every dark interval must have the long audible warning; review each original
result and independent recovery proof before starting the next. No screen test
starts until that readiness reply.

After the new debug baseline and owner observations pass, run the connected
awake removal rehearsal. Then obtain separate readiness for one sleep attempt
with a single unplug ten seconds after darkness. Collect the original result
over Wi-Fi while USB is still absent, preserve the separate observer report,
and only then request an awake reconnect and record it separately.

The prior connected-sleep and attachment baselines are consumed and must not
be reused or replayed. No actual removal, repeated-case or charging-through-
sleep result is claimed by this admission checkpoint.
