# Diagnostic.19: USB attachment wakes before the RTC

5 October 2026, Pacific/Auckland. NEO-110 / NEO-117. Capture timestamps are UTC.

The first attended USB-attachment test returned early through the power-management
chip's interrupt, before the RTC alarm. USB, Wi-Fi and the normal dim console
subsequently recovered, but the original **failed RTC qualification** remains
unchanged. Live settings and the pinned source explain a wake-policy mismatch:
USB-controller wake is disabled, while both external-power supply wake controls
are enabled and their drivers deliberately arm insertion wake.

The owner has now explicitly selected the desired behavior: **connecting USB
while asleep must leave the GameShell asleep and charging**. NEO-117 will make
both supply wake paths follow this policy while retaining POWER/RTC wake. No
live wake setting, charging parameter or driver was changed during this test
or its postmortem.

## Original attempt and physical observation

[Report 164](164-diagnostic19-usb-attachment-debug-qualification.md) records the
fresh seven-debug baseline, confirmed physical unplug, verified absent state
and passing awake attachment rehearsal. Following a separate readiness prompt,
the owner answered **“Ready”**. Exactly one command was submitted:

```sh
task device:sleep-cable-attach \
  QUALIFICATION=.local/neo110-attach-debug-history.json \
  REHEARSAL=d6eb5b5a53f046e6bd7baab1eb967d79 \
  CABLE_ACTION=1 UNPLUGGED=1 ATTENDED=1
```

| Identity | Value |
| --- | --- |
| Source at submission | `53ed53b`; diagnostic helpers unchanged from `749ef9d` |
| Image / kernel | `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19` |
| Boot | `2fa86697-ead3-4e6f-a295-44e6ad203983` |
| Run | `01d3451e1ea34a32b3bcc69e32032442` |
| Capture | `.local/diagnostics/20261005T020202.497694Z/result.json` |
| SHA-256 | `a3cc1ad7b3fecfb6155bdca849db33a1b23ab3e335e46b97edcc863479897272` |

The original error is `No RTC event at return: early/unattributed wake, not an
RTC-wake pass`. There was no second sleep submission. The owner reported:

> Yes, I heard the long warning and waited 10 seconds but the screen came on as
> I clipped the cable in, so I think it was only off for about 10 seconds

The owner then confirmed the normal dim console was visible with USB connected.
Because insertion and visible return were described as coincident, the separate
observer record conservatively uses `OBSERVATION=uncertain DISPLAY=normal`,
rather than inventing a strict ordering at that boundary. The exact account is
preserved above. The saved `report:sleep-cable` task produced
`result-cable-observation.json`, SHA-256
`4ee725fea684872c833ea54736f4025c66b7abbd6263853c7b5e3c63c5937e09`;
`attended_case_passed=false`. Neither the sound nor darkness timestamps the
electrical insertion edge.

## Wake and recovery observations

| Observation | Original result |
| --- | --- |
| Submitted state interval | 16.618 seconds BOOTTIME |
| Trace `machine_suspend[1]` interval | 20222.759469–20236.996601, 14.237 seconds |
| Alarm-to-return interval | 17.342 seconds; the planned alarm was still enabled and pending |
| RTC | No event at return; IRQ31 count 7 → 7; original disabled alarm restored |
| Recorded wake IRQ | 67, the shared `axp22x_irq_chip` parent, count 5 → 6 |
| ACIN / VBUS insertion handlers | Each 2 → 3 |
| ACIN / VBUS removal handlers | Each unchanged at 2 |
| Before and entry cable state | Both supplies absent/offline; PHY absent; UDC not attached/carrier0 |
| Final cable state | Both supplies present/online; PHY present; UDC configured/carrier1 |
| Kernel PM accounting | Success 23 → 24, all failure counters zero |
| Keypad and memory | Original handle connected, no held keys or input errors; process-memory check passed |
| SDIO | Usage 2, active/forbidden, control `on` |
| Trace and controls | Keypad/Wi-Fi/USB trace restoration passed with no recorded loss; PM, RTC, audio and console restored |
| Final health | No failed services or kernel taint |

The one-second level-5 warning completed and restored the idle amplifiers before
entry; the owner heard it. The kernel's successful resume counter does not make
this a passing RTC test. Likewise, the shared parent IRQ does not uniquely
identify one nested supply interrupt as the electrical cause. The temporal
observation, insertion dispatches and armed supply policy together support
power-insertion wake, without exact physical-edge proof.

The test retained its diagnostic power-key policy owner and ignore drop-in after
the failed qualification, as designed. Input ownership was handed back, but
normal short/long logind power-button actions remain suppressed. The original
recovery record reports restored PM controls and no cleanup errors. No guard
was manually deleted, no service restarted and no reboot or recovery reconnect
was used. The owner was told to leave USB connected and buttons untouched.

CPU-idle driver remains `none`, with no states. The BOOTTIME/MONOTONIC difference
is below sample uncertainty; no CPU/DRAM retention, energy saving, charging
through deep sleep or production wake latency is qualified here.

## Separate read-only postmortem

```sh
task device:sleep-collect RUN=01d3451e1ea34a32b3bcc69e32032442 ROUTE=wifi
task device:pm-inspect
task device:exec ROUTE=wifi -- cat \
  /sys/class/power_supply/axp20x-usb/power/wakeup \
  /sys/class/power_supply/axp22x-ac/power/wakeup
task report:sleep-evidence RESULT=.local/diagnostics/20261005T020202.497694Z/result.json
```

The Wi-Fi collection at `20261005T020421.397462Z` recovered byte-identical
original evidence, plus a separate snapshot confirming the same boot, configured
high-speed USB, carrier1, MUSB wake disabled, wake IRQ67 and retained key-policy
guard. `recovery-snapshot.json` SHA-256:
`801e6cfcc685f4a5d957e836aa64e51b0e4e5aabf7cff40e77fbe5c331e3a8c6`.

USB inspection `20261005T020522.891590Z/inspection.json` independently passed
the ordinary PM health validator on the original boot: PM24/0, SDIO2, configured
USB, healthy services and valid battery telemetry at 99%/charging. This is
separate recovery evidence, not a retroactive original-result pass or full
policy-restoration claim. SHA-256:
`78b0f7755ba0e9bf7bce8aac500f59e542d4034520d881f918fe167790121a37`.

The supply policy command returned `enabled` for each supply. Its private log,
`.local/neo110-attach-supply-wakeup.log`, has SHA-256
`7fbdf9200d60f23d3a414b1f7b3e081c6ee890161be17e0dcd283add41a8f361`.

The offline RTC/trace/clock assessment also correctly rejected missing RTC
delivery. Capture `20261005T020522.903516Z/sleep-evidence.json`, SHA-256
`d213e18a64331594a1ec87e4c9d4ee2ae2b233f44f0b2328183300b16191715d`,
keeps `overall_requalified=false` and leaves the original unchanged.

## Source explanation and next correction

The local Linux 6.18.54 source patch manifest matches the repository's current
queue. Relevant paths are:

- `drivers/power/supply/power_supply_core.c`: supply registration enables wake
  by default unless the driver's configuration sets `no_wakeup_source`.
- `drivers/power/supply/axp20x_ac_power.c`: suspend arms ACIN insertion when
  `device_may_wakeup(&power->supply->dev)` is true.
- `drivers/power/supply/axp20x_usb_power.c`: suspend similarly arms VBUS insertion.
- [Patch 0019](../kernel/patches/0019-wake-irq-error-ownership.patch): error
  propagation and ownership of the actual armed wake reference.
- [Current USB startup policy](../runtime/usr/local/sbin/gameshellneo-usb):
  selects the MUSB controller's disabled wake policy, independently of the
  supply-class controls.

The existing source therefore supports distinct configurable wake paths; this
test does not demonstrate that their driver logic is defective. NEO-117 should
select and verify the owner's new policy for both supplies using the standard
driver interfaces, with underlying fixes if required by the audit. It must
preserve POWER/RTC wake and charging/detection, rather than disabling the shared
PMIC parent interrupt.

Supply registration calls `device_add()` before `device_init_wakeup()`, so a
bare udev add rule cannot simply assume the wake control already exists. Startup
ordering and fail-closed diagnostic admission need explicit consideration.
Disabling insertion wake also masks insertion IRQs during suspend; review
masked-event acknowledgment before carrying forward an exact handler-count
expectation. Any new policy and criteria must be prospective and source/image
bound, preserving all endpoint, RTC, observer and recovery requirements.

The consumed attachment baseline and original failed run must not be retried or
relabeled. Complete offline policy work before arranging a fresh attended test.
No further physical test is running. Ordinary sleep remains disabled.
