# Diagnostic.19: fresh USB-attachment prerequisites

5 October 2026, Pacific/Auckland; capture timestamps are UTC. NEO-110.

The fresh freezer/driver/five-late-noirq sequence passed on diagnostic.19,
preparing an independent baseline for attaching USB during sleep. PM success
advanced from 16 to 23, with every failure counter still zero and SDIO usage
remaining 2. This sequence did not enter actual sleep or change the cable.
The owner confirmed normal warning sounds and display returns after the batch.

The passing removal case in [report 163](163-diagnostic19-usb-removal-sleep-validation.md)
is separate evidence. Its consumed baseline was not reused for attachment.

## Read-only admission

| Item | Evidence |
| --- | --- |
| Source commit | `48f0024`; diagnostic helpers unchanged from `749ef9d` |
| Image / kernel | `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19` |
| Boot | `2fa86697-ead3-4e6f-a295-44e6ad203983` |
| USB PM inspection | `20261005T014301.450990Z/inspection.json` |
| Independent Wi-Fi status | `20261005T014303.113936Z` |
| Effective power policy | `20261005T014318.338281Z/before.json` |
| Read-only RTC inspection | `20261005T014319.500865Z/result.jsonl` |

The PM inspector matched the pinned image, kernel and radio and passed health
validation: configured USB, connected Wi-Fi, valid fresh battery telemetry at
100%/charging, no kernel taint or failed services, PM16/0 and normal dim
brightness. The boot was unchanged from report163. No diagnostic policy owner
or drop-in remained; the normal diagnostic power-key action remained poweroff,
idle action ignore. The RTC alarm was disabled. The inspect-only RTC record's
default `passed=false`/`restored=false` fields are not a failed alarm test; no
alarm was programmed by that command. Existing same-boot awake RTC qualification
was checked by platform admission.

The owner explicitly answered **“Ready—I’m watching and listening”** for the
whole debug sequence, keeping USB connected, the headphone socket empty and
all controls untouched. Each command was submitted once. Its original result,
trace, restoration and independent USB/Wi-Fi proofs were checked before the
next command.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-platform
# Repeat the last command four times, reviewing each result before continuing.
```

## Automated results

Each capture is under `.local/diagnostics/` and contains `cycle-1/result.json`.

| Stage | Capture | Run ID | Stage seconds | PM successes afterward |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261005T014355.182521Z` | `f7c9212750d94e9d9091970a8f2b6085` | 5.676 | 17 |
| Driver | `20261005T014516.818283Z` | `8c30c26da5404441a4f474d883beda73` | 7.955 | 18 |
| Late/noirq 1 | `20261005T014647.697975Z` | `29c729dddd7044cb84e959c3a78a18b5` | 7.868 | 19 |
| Late/noirq 2 | `20261005T014803.536755Z` | `95a4aa5884684817ba8941872904061c` | 7.868 | 20 |
| Late/noirq 3 | `20261005T014922.406277Z` | `0fc6eabe4b1840f2bf97684a7556bc8a` | 7.886 | 21 |
| Late/noirq 4 | `20261005T015038.955711Z` | `167461f2a2604055bb9212d0429d487b` | 7.848 | 22 |
| Late/noirq 5 | `20261005T015200.494938Z` | `6776e174acf242bea67daf18ff27a488` | 7.903 | 23 |

Every result completed successfully, matched the original boot and independently
verified both SSH routes. All PM failure counters stayed zero; SDIO stayed
active/forbidden with control `on` and usage 2. Process memory and power-key
handoff passed. Every driver/platform cycle retained the original keypad handle
and complete, restored keypad/Wi-Fi traces. Each platform trace passed the four
ordered late/noirq phases and successful RSB noirq suspend/resume callbacks,
without actual-sleep trace boundaries.

All six dark intervals had one recorded level-5, 1,000 ms warning. Playback
passed, mixers were restored and speaker/headphone amplifiers were off before
the PM stage. The freezer check does not blank the display and had no warning.
These timings include the artificial debug delay and are not production wake
latency measurements.

The driver and final platform collectors each retained
`SSHException: No existing session`, with a protocol-banner exception in their
private logs. Platform cycle 3 retained one `SSHException: Timeout opening
channel.` Each collector subsequently recovered the exact original completed
run and independently verified both routes. No PM command was resubmitted and
no radio, host or driver cause is assigned from these transport exceptions.

## Preserved admission evidence

The saved `check:sdio-ref-history -- --require-stable` task summarized exactly
these seven result paths into `.local/neo110-attach-debug-history.json`:

```text
8e2fdf67b03823147463f600fea597b7e6ec69d9e9dbbaf762a967aee5badd6f
```

Fresh USB inspection `20261005T015327.173590Z/inspection.json` passes health
validation with PM23/0. The actual-sleep controller's receipt validator accepted
all seven originals for `usb-attach`, with no prior sleep records in this new
chain. This is an offline admission validation, not a sleep submission or a
successful attachment result.

Original result file SHA-256 values, in table order:

```text
288415fcf1442d9d2ee168de31ba828f17d82522bfc98e820043a6518b96560a
14d690b4ba5b068ee047be3b24357ddbfe2b8451282f5398320514eb74532d8f
71c0289ea1b974e99ad1be99700113b09955592596fec0d64f935430635662ac
ae174958481bb52eb5cdee7a67979eb7a73bb835d4a8e98b2b159fc20df351e1
42e078d693dcb927eeb0fb5849a91c94e08346a46667e888ef0659c9f08d0cf9
61f72f4c37fa186ee3f19421e16024f7d1b740150fac12c24811f1daeade4128
1c2b3e5ec578af529b16c4548edb9a825710d9692106d3c075fe21caabf101c5
```

Afterward the owner answered **“All normal; USB unplugged; GameShell running.”**
However, the first Wi-Fi connection inspection,
`20261005T015441.546292Z/connection-inspection.json`, still recorded configured
UDC/carrier1, PHY USB1, AC/USB present and online. All insertion counts were 2
and removal counts 1. The strict absent-state validator rejected that snapshot;
no awake rehearsal or sleep was submitted. A follow-up physical clarification
was requested. This mismatch alone does not establish a driver fault.

A second read-only Wi-Fi capture, `20261005T015547.049357Z`, recorded the same
connected state and unchanged counters, 65.347 seconds after the first
snapshot. Both originals remain preserved, with no USB reset, network change,
PM submission or attempt to force an absent state. Their
`connection-inspection.json` SHA-256 values are:

```text
66142cb79f9de92681692dcb2f7b88232a71dfbd97dffcff8836d584a3027d1c
9c9eacd26f27ccd32d2fda94d6e6eeedf9ca09e6369375ef116a46415fafa679
```

The owner subsequently clarified **“No, I haven't unplugged it. It's still
connected.”** This resolves the apparent mismatch: the connected-state readings
were correct. Neither snapshot is evidence of failed physical disconnect
handling. A new, explicit unplug instruction was issued before the battery
rehearsal; no rehearsal was started on the connected supply.

## Confirmed unplug and awake attachment rehearsal

After the separate unplug instruction, the owner confirmed **“I've unplugged
it”**. Read-only Wi-Fi capture `20261005T015844.525981Z` then passed strict
absent-state validation on the same boot: both external supplies absent/offline,
PHY USB/HOST 0, UDC not attached and carrier 0. AC/VBUS removal counts each
advanced from 1 to 2 while insertion counts remained 2. Its
`connection-inspection.json` SHA-256 is
`680f54be63d74ca5aed2510caeedfa0fc247440e674f40871f19fd64c19ad243`.

The valid, unconsumed seven-debug baseline did not need repeating. The saved
awake command rechecked its source, boot, image and PM history before execution:

```sh
task device:sleep-cable-attach-rehearse \
  QUALIFICATION=.local/neo110-attach-debug-history.json \
  CABLE_ACTION=1 UNPLUGGED=1
```

Capture `20261005T015914.490294Z/result.json`, run
`d6eb5b5a53f046e6bd7baab1eb967d79`, passed original-result revalidation; SHA-256
`489bd0f6943b3ec19d9477e21eb500bc60a84d774cc3fea67124c840694678ea`.
The awake alarm delivered one event with flags `0xa0`, IRQ31 count 6 → 7,
then restored the original disabled alarm. All three cable observations stayed
absent with all four handler counts unchanged at 2. Wi-Fi SSH was independently
verified; USB recovery was intentionally not tested for the absent profile.
PM counters stayed 23/0, SDIO usage 2 and battery telemetry was valid at
99%/discharging. Original policy and owned controls were restored with no RTC,
policy, drop-in or console ownership retained.

Attachment now requires separate readiness for one actual attachment during
darkness. No actual sleep was submitted as part of this debug batch or awake
rehearsal. Ordinary sleep remains disabled; retention, energy and general sleep
reliability are not established by these results.

## Subsequent attachment attempt

The separately attended attempt in [report 165](165-diagnostic19-usb-attachment-early-wake.md)
woke early through the PMIC while insertion wake was enabled. The original RTC
qualification remains failed; this baseline is now consumed and must not be
retried. NEO-117 tracks the owner's subsequently selected stay-asleep-and-charge
policy and future qualification.
