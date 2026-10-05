# Diagnostic.20: USB-removal preparation

5 October 2026; capture timestamps are UTC. NEO-117 and NEO-110.

The owner requested the next slice after the passing attachment case in
[report 171](171-diagnostic20-usb-attachment-sleep-validation.md). The next
qualification is removal during sleep with diagnostic.20's disabled supply
wake policies. Initial read-only admission and the independent seven-stage
debug baseline pass; the owner confirmed clear warnings and normal display
returns. PM advanced from 16 to 23 with all failure counters zero and SDIO
usage stable at 2. The connected awake removal rehearsal also passes with full
restoration and both SSH routes verified. USB remains connected. No actual
removal-during-sleep attempt has run on this image.

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

## Independent attended debug baseline

The owner explicitly readied one freezer, one driver and five late/noirq debug
cycles with USB connected, headphone socket empty and all controls untouched.
Each original result was reviewed before submitting the next one-cycle command.
The diagnostic sources remained unchanged at the `220430b` host checkpoint.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# Repeat the last command four times, reviewing each original result first.
```

Each capture below contains `cycle-1/result.json`.

| Stage | Capture | Run ID | Stage seconds | Final PM successes |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261005T060304.103641Z` | `86760e2537c8436697ced3b8ae65a876` | 5.705 | 17 |
| Driver | `20261005T060427.234017Z` | `452ff4ba72cc4bc0b3361fcc81aedb89` | 8.082 | 18 |
| Late/noirq 1 | `20261005T060557.513722Z` | `3fbaa88e548f49d69772ac26247b0b14` | 7.930 | 19 |
| Late/noirq 2 | `20261005T060727.673212Z` | `6b014c4426f245eba07dfe97a62fbc69` | 7.953 | 20 |
| Late/noirq 3 | `20261005T060851.571869Z` | `e2918835850b404da1154f6ebddb9479` | 7.986 | 21 |
| Late/noirq 4 | `20261005T061017.748487Z` | `cbd37498b6bf4657a219ea28a1b9298f` | 7.722 | 22 |
| Late/noirq 5 | `20261005T061138.645880Z` | `ecd819ad3bcc4a8384b915c3a5f2358c` | 7.885 | 23 |

Every controller exited zero, and every original result is complete/passed with
both SSH routes independently verified to the original boot. Process memory
and untouched POWER handback pass. All failure counters remain zero; SDIO
remains active/forbidden, control `on`, usage 2. MUSB and both supply wake
controls remain disabled before/after each cycle.

All six driver/platform cycles retain the original keypad handle without input
errors, disconnect or held keys. Keypad/Wi-Fi traces are complete and restored;
each platform trace contains the ordered late/noirq phases and RSB callbacks.
Every dark interval has a level-5, 1,000 ms warning with successful playback,
mixer restoration and idle amplifiers before entry. The owner answered
**"Yes—warnings clear and all returns normal"** after the batch. The five-second
debug delay is included in the times above; these are not actual sleep or
production wake-latency measurements.

Each of the five platform collectors retains `SSHException: No existing session`
and a protocol-banner error in its local log. Every collector recovered the
same original completed run and verified both routes without resubmitting PM.
Their cause remains unassigned under the existing transport-timing follow-up.

Original result SHA-256 values, in table order:

```text
dae1244f6f55dc9ff526c0b28c043c7322176e94bb41776e7a06dfb6c2eef8bd
02ef78be70558202aa07856fa671a3313c92ede003821cefdbc38aad6e5c2457
21b9a45a9406ef91a6154334e0432c604e1415a9ce7c10d67a7a8b778b03a0c2
48d774bc35c38d2998a9fc89690ce0142a0e933b3cac39529746b5d32ea32f7f
7eb2d9a643cef0b45e8c441db5405f95173bf3cc419906efc69b201cf69ae707
ed81b6dc4ad1421fd2f87ce6ce2ca8cb3d310993cf43114a3055bf938a5f98f3
df897b99d1d7ca36f7ed474360ce1bfe63b14408dce738b05689d3b1f81d7aa2
```

The saved `task check:sdio-ref-history -- --require-stable` command accepted
exactly these seven result paths into `.local/neo117-remove-debug-history.json`,
SHA-256 `1488ed5f94266ae232c281de6a69979443f11d82ac6df4b90f42894691ee8c72`.
Fresh PM inspection `20261005T061322.884208Z/inspection.json` passes health checks
at PM23/0; SHA-256
`f8b4f0b595a7609ac18243b33064b5b60c72f7b0151d8f656eadc5b5157990cc`.
The existing receipt validator accepts the seven originals for `usb-remove`
with no prior sleep in this independent chain. This offline validation did not
submit PM or an alarm.

## Connected awake rehearsal

After the owner confirmed the complete debug batch, the saved command ran:

```sh
task device:sleep-cable-remove-rehearse \
  QUALIFICATION=.local/neo117-remove-debug-history.json CABLE_ACTION=1
```

Capture `20261005T061402.753024Z/result.json`, run
`c7f482d799ba4deb89990207953877b1`, passed with the original boot/source chain;
SHA-256 `3679fae5e6ac0e45601b2f663000cb0cd5c566d83d93593c67ead4a2c14bb8bc`.
The alarm delivered one event with flags `0xa0` after 30.429 seconds; RTC IRQ31
count advanced 5 to 6 and the original alarm was restored.

All three cable observations stayed configured/present, with carrier 1, PHY
USB 1/HOST 0, both supplies present/online and handler counts unchanged: ACIN/
VBUS plugin 0, removal 1. PM remains 23/0. Original power policy and input
handoff restored; no policy/drop-in, PM-control, RTC or console owner remains.
USB and Wi-Fi SSH were independently verified. This kept the screen on and
submitted no sleep or cable action.

## Next attended steps

Fresh described readiness is pending for one sleep attempt
with a single unplug ten seconds after darkness. Collect the original result
over Wi-Fi while USB is still absent, preserve the separate observer report,
and only then request an awake reconnect and record it separately.

The prior connected-sleep and attachment baselines are consumed and must not
be reused or replayed. No actual removal, repeated-case or charging-through-
sleep result is claimed by this admission checkpoint.
